"""AIMS Sukkur website - application factory."""
import logging
import os
import sqlite3

from flask import Flask, flash, jsonify, redirect, render_template, request
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.exceptions import HTTPException

from .config import Config
from .extensions import db
from .security import init_csrf, init_security_headers, is_xhr, safe_back
from .utils import safe_url


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record):
    """Faster, safer SQLite: WAL journal lets readers and the writer work at the same time."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        try:
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()
        except sqlite3.Error:
            pass


def create_app(config_object=None, init_database=True):
    app = Flask(__name__, instance_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instance"))
    app.config.from_object(config_object or Config)
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    if app.config.get("TRUST_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    db.init_app(app)
    init_csrf(app)
    init_security_headers(app)
    _init_speed(app)
    _init_templates(app)
    _init_errors(app)

    from .public import bp as public_bp
    from .admin import bp as admin_bp
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)

    if init_database:
        from .services.bootstrap import init_db
        with app.app_context():
            init_db()
    return app


# ------------------------------------------------------------------------ speed
def _init_speed(app):
    # gzip/brotli responses (optional dependency - the site works without it)
    try:
        from flask_compress import Compress
        Compress(app)
    except ImportError:
        app.logger.info("Flask-Compress not installed: responses will not be compressed.")

    # /static/x.css?v=<mtime>  -> browsers can cache forever and still get fresh files after edits
    mtimes = {}

    @app.url_defaults
    def _static_version(endpoint, values):
        if endpoint != "static" or "v" in values:
            return
        filename = values.get("filename")
        if not filename:
            return
        if filename in mtimes and not app.debug:
            values["v"] = mtimes[filename]
            return
        try:
            stamp = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            return
        mtimes[filename] = stamp
        values["v"] = stamp

    @app.after_request
    def _static_cache(resp):
        if request.endpoint == "static" and resp.status_code == 200 and request.args.get("v") and not app.debug:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


# --------------------------------------------------------------------- templates
def _init_templates(app):
    app.jinja_env.filters["safe_url"] = safe_url

    @app.context_processor
    def _site_settings():
        from .services.cache import get_settings
        return {"settings": get_settings()}


# ------------------------------------------------------------------------ errors
_ERROR_TEXT = {
    400: ("Bad request", "We couldn't understand that request."),
    403: ("Not allowed", "You don't have permission to do that."),
    404: ("Page not found", "The page you are looking for doesn't exist or was moved."),
    405: ("Method not allowed", "That action isn't supported on this page."),
    413: ("File too large", "The file you tried to upload is bigger than the allowed limit."),
    429: ("Too many requests", "Please slow down and try again in a little while."),
    500: ("Something went wrong", "An unexpected error occurred. Please try again."),
}


def _init_errors(app):
    @app.errorhandler(HTTPException)
    def _http_error(err):
        code = err.code or 500
        title, text = _ERROR_TEXT.get(code, (err.name, err.description or ""))
        if code == 413:
            text = f"That file is too large (limit {app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)} MB)."
            if request.path.startswith("/admin"):
                flash(text, "danger")
                return redirect(safe_back("admin.admin_dashboard"))
        if is_xhr():
            return text, code
        return render_template("errors/error.html", code=code, title=title, text=text), code

    @app.errorhandler(Exception)
    def _unhandled(err):
        db.session.rollback()
        app.logger.exception("Unhandled error: %s", err)
        if is_xhr():
            return "Something went wrong. Please try again.", 500
        title, text = _ERROR_TEXT[500]
        return render_template("errors/error.html", code=500, title=title, text=text), 500
