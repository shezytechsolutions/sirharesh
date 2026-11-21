"""Configuration. Everything sensitive comes from environment variables / .env."""
import os
import secrets
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


def _load_dotenv(path):
    """Tiny .env reader (no extra dependency). Existing environment variables win."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(os.path.join(BASE_DIR, ".env"))


def _env_bool(name, default=False):
    return os.environ.get(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


def _secret_key():
    """SECRET_KEY from env, else a random key generated once and kept in instance/secret_key."""
    key = os.environ.get("SECRET_KEY", "").strip()
    if key and not key.startswith("change-me"):
        return key
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    path = os.path.join(INSTANCE_DIR, "secret_key")
    try:
        with open(path, encoding="utf-8") as fh:
            saved = fh.read().strip()
        if len(saved) >= 32:
            return saved
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(key)
    except OSError:
        pass  # read-only disk: key lives only for this process (sessions reset on restart)
    return key


def _database_uri():
    url = os.environ.get("DATABASE_URL", "").strip()
    if url and os.environ.get("USE_SQLITE", "0") != "1":
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return url
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    new_path = os.path.join(INSTANCE_DIR, "edubuzz.db")
    legacy_path = os.path.join(BASE_DIR, "edubuzz.db")   # old location (before restructure)
    path = legacy_path if (os.path.isfile(legacy_path) and not os.path.isfile(new_path)) else new_path
    return "sqlite:///" + path.replace("\\", "/")


class Config:
    SECRET_KEY = _secret_key()
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # uploads live inside static/ so existing "/static/uploads/..." DB paths keep working
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "95")) * 1024 * 1024
    MAX_IMAGE_BYTES = 8 * 1024 * 1024

    # sessions / cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_bool("COOKIE_SECURE", False)   # set COOKIE_SECURE=1 when served over HTTPS
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.environ.get("SESSION_HOURS", "8")))

    # speed
    TEMPLATES_AUTO_RELOAD = _env_bool("TEMPLATES_AUTO_RELOAD", True)
    SEND_FILE_MAX_AGE_DEFAULT = timedelta(days=7)
    JSON_SORT_KEYS = False
    CSRF_ENABLED = True
    COMPRESS_MIN_SIZE = 500

    # deployment
    TRUST_PROXY = _env_bool("TRUST_PROXY", False)   # 1 when behind Cloudflare / nginx
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-only-secret-key-not-used-in-production-0123456789"
