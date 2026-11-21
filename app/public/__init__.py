import time
from threading import Lock
from flask import Blueprint, request, g

bp = Blueprint("public", __name__)

from . import routes, pdf  # noqa: E402,F401  (register the routes)

# In-memory IP tracking cache to prevent duplicate visit logging within 2 minutes (120s)
_recent_ip_visits = {}
_recent_ip_lock = Lock()
IP_DEDUPE_SECONDS = 120  # 2 minutes


@bp.before_request
def _track_page_visit():
    """Log anonymous page views for the site owner (legal analytics).
    If the same IP address appears within 2 minutes, ignore and count as same visit.
    """
    if request.method not in ("GET", "HEAD"):
        return
    # Skip static-like noise and bots that hit robots only
    path = (request.path or "/")[:255]
    if path.startswith("/static") or path.startswith("/admin") or path == "/robots.txt":
        return
    try:
        from ..extensions import db
        from ..models import PageVisit
        from ..security import client_ip
        from datetime import datetime, timedelta

        ip = client_ip()[:64]
        now_ts = time.time()

        # Check in-memory 2-minute deduplication window
        with _recent_ip_lock:
            # Clean up cache if it grows large
            if len(_recent_ip_visits) > 5000:
                cutoff_cleanup = now_ts - (IP_DEDUPE_SECONDS * 4)
                _recent_ip_visits.clear()

            last_seen = _recent_ip_visits.get(ip)
            if last_seen and (now_ts - last_seen) < IP_DEDUPE_SECONDS:
                return  # Skip: same IP within 2 minutes

            # Also check database for persistence across server restarts
            cutoff_dt = datetime.utcnow() - timedelta(seconds=IP_DEDUPE_SECONDS)
            existing = PageVisit.query.filter(
                PageVisit.ip == ip,
                PageVisit.created_at >= cutoff_dt
            ).order_by(PageVisit.created_at.desc()).first()

            if existing:
                _recent_ip_visits[ip] = existing.created_at.timestamp() if existing.created_at else now_ts
                return  # Skip: same IP logged in DB within last 2 minutes

            _recent_ip_visits[ip] = now_ts

        ua = (request.headers.get("User-Agent") or "")[:255]
        # Light bot filter
        ua_l = ua.lower()
        if any(b in ua_l for b in ("bot", "spider", "crawler", "slurp", "bingpreview")):
            return
        ref = (request.referrer or "")[:255]
        visit = PageVisit(
            ip=ip,
            path=path,
            method=request.method[:10],
            user_agent=ua or None,
            referrer=ref or None,
        )
        db.session.add(visit)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
