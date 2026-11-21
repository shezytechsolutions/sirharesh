"""Small, dependency-free helpers used across the project."""
import re
from datetime import datetime, timezone
from urllib.parse import urlparse


def utcnow():
    """Naive UTC 'now' (same storage format as before, without the deprecated utcnow())."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_int(value, default=0, lo=None, hi=None):
    """Parse an int from user input. Never raises: returns `default` on bad input."""
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if lo is not None and n < lo:
        n = lo
    if hi is not None and n > hi:
        n = hi
    return n


def form_str(form, key, default=""):
    """Stripped string from a form mapping."""
    val = form.get(key, default)
    return (val if isinstance(val, str) else default).strip()


_SAFE_SCHEMES = {"http", "https", "mailto", "tel"}


def safe_url(value, allow_relative=True):
    """
    Return `value` if it is a safe link, else ''.
    Blocks javascript:, data:, vbscript: and similar. Allows http(s), mailto, tel,
    and (optionally) site-relative links such as /courses, course.html, #top.
    """
    if value is None:
        return ""
    val = str(value).strip()
    if not val:
        return ""
    # control characters / whitespace tricks used to smuggle "java\nscript:"
    if re.search(r"[\x00-\x1f\x7f]", val):
        return ""
    if val.startswith("//"):          # protocol-relative -> external
        return ""
    parsed = urlparse(val)
    if parsed.scheme:
        return val if parsed.scheme.lower() in _SAFE_SCHEMES else ""
    if ":" in val.split("/")[0].split("?")[0].split("#")[0]:
        return ""                     # something like "foo:bar" - unknown scheme
    return val if allow_relative else ""


def extract_youtube_id(url_or_id):
    """Extract 11-char YouTube video ID from various YouTube URL formats."""
    if not url_or_id:
        return ""
    val = str(url_or_id).strip()
    if re.match(r'^[a-zA-Z0-9_-]{11}$', val):
        return val
    patterns = [
        r'(?:v=|\/v\/|embed\/|youtu\.be\/|shorts\/|\/e\/|watch\?v=|\&v=)([\w-]{11})',
        r'[\?\&]v=([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        m = re.search(pattern, val)
        if m:
            return m.group(1)
    return val


_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


def is_valid_video_id(val):
    return bool(val and _VIDEO_ID_RE.match(val))
