"""
Security helpers: CSRF protection, login throttling, security headers,
session validation. No third-party dependencies.
"""
import hashlib
import hmac
import secrets
import threading
import time
from functools import wraps
from urllib.parse import urlparse

from flask import abort, current_app, flash, g, redirect, request, session, url_for

from .extensions import db


# --------------------------------------------------------------------------- CSRF
class CSRFError(Exception):
    pass


def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def is_xhr():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def safe_back(default_endpoint="public.index"):
    """Redirect target: the referrer if it belongs to this site, else a default page."""
    ref = request.referrer or ""
    if ref:
        host = urlparse(ref).netloc
        if host and host == request.host:
            return ref
    return url_for(default_endpoint)


def init_csrf(app):
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def _csrf_protect():
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return
        if not app.config.get("CSRF_ENABLED", True):
            return
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        expected = session.get("_csrf") or ""
        if not expected or not sent or not hmac.compare_digest(sent, expected):
            raise CSRFError()

    @app.errorhandler(CSRFError)
    def _csrf_failed(_e):
        msg = "Your session expired or the form was invalid. Please reload the page and try again."
        if is_xhr():
            return msg, 400
        flash(msg, "danger")
        return redirect(safe_back())


# ------------------------------------------------------------------ rate limiting
class Throttle:
    """Tiny in-memory sliding-window limiter (fine for a single waitress process)."""

    def __init__(self, limit, window_seconds):
        self.limit = limit
        self.window = window_seconds
        self._hits = {}
        self._lock = threading.Lock()

    def _prune(self, key, now):
        hits = [t for t in self._hits.get(key, ()) if now - t < self.window]
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        return hits

    def retry_after(self, key):
        """Seconds to wait if `key` is over the limit, else 0."""
        now = time.time()
        with self._lock:
            hits = self._prune(key, now)
            if len(hits) >= self.limit:
                return int(self.window - (now - hits[0])) + 1
        return 0

    def hit(self, key):
        now = time.time()
        with self._lock:
            if len(self._hits) > 5000:      # memory guard
                for k in list(self._hits):
                    self._prune(k, now)
            self._hits.setdefault(key, []).append(now)

    def reset(self, key):
        with self._lock:
            self._hits.pop(key, None)


login_by_user = Throttle(limit=5, window_seconds=15 * 60)
login_by_ip = Throttle(limit=25, window_seconds=15 * 60)
contact_by_ip = Throttle(limit=5, window_seconds=10 * 60)


def client_ip():
    if current_app.config.get("TRUST_PROXY"):
        ip = request.headers.get("CF-Connecting-IP") or \
             (request.headers.get("X-Forwarded-For", "").split(",")[0].strip())
        if ip:
            return ip
    return request.remote_addr or "unknown"


# --------------------------------------------------------------- admin session
def password_stamp(admin):
    """Changes whenever the password changes -> old sessions stop working."""
    return hashlib.sha256((admin.password_hash or "").encode("utf-8")).hexdigest()[:16]


def start_admin_session(admin):
    session.clear()
    session.permanent = True
    session["admin_id"] = admin.id
    session["admin_username"] = admin.username
    session["pv"] = password_stamp(admin)
    csrf_token()


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        from .models import Admin
        admin_id = session.get("admin_id")
        admin = db.session.get(Admin, admin_id) if admin_id else None
        if admin is None or not hmac.compare_digest(str(session.get("pv", "")), password_stamp(admin)):
            if admin_id:
                session.clear()
            flash("Please log in to access the admin panel.", "warning")
            return redirect(url_for("admin.admin_login"))
        g.admin = admin
        return view(*args, **kwargs)
    return wrapper


PASSWORD_BLACKLIST = {"admin123", "password", "password123", "12345678", "123456789", "1234567890", "admin@123"}


def password_problem(new_password, username=""):
    """Return a human-readable problem with the password, or None if acceptable."""
    if len(new_password) < 10:
        return "Password must be at least 10 characters."
    if new_password.lower() in PASSWORD_BLACKLIST:
        return "That password is too common. Choose something harder to guess."
    if username and username.lower() in new_password.lower():
        return "Password must not contain your username."
    if new_password.isdigit() or new_password.isalpha():
        return "Use a mix of letters and numbers (or symbols)."
    return None


# ----------------------------------------------------------------- HTTP headers
# NOTE: no object-src / sandbox here on purpose - they make Chrome refuse to display PDFs.
CSP = "frame-ancestors 'self'; base-uri 'self'; form-action 'self'"


def init_security_headers(app):
    @app.after_request
    def _headers(resp):
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "SAMEORIGIN")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        h.setdefault("Content-Security-Policy", CSP)
        proto = request.headers.get("X-Forwarded-Proto", request.scheme) if app.config.get("TRUST_PROXY") else request.scheme
        if proto == "https":
            h.setdefault("Strict-Transport-Security", "max-age=31536000")
        if request.path.startswith("/admin"):
            h["Cache-Control"] = "no-store"
            h["Pragma"] = "no-cache"
        return resp
