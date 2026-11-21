"""Tiny TTL cache for site settings (read on every page render)."""
import threading
import time

_TTL_SECONDS = 30
_lock = threading.Lock()
_state = {"data": None, "stamp": 0.0}


def get_settings():
    from ..models import SiteSetting
    now = time.time()
    with _lock:
        if _state["data"] is not None and now - _state["stamp"] < _TTL_SECONDS:
            return _state["data"]
    try:
        data = {r.key: (r.value or "") for r in SiteSetting.query.all()}
    except Exception:
        return {}
    with _lock:
        _state["data"], _state["stamp"] = data, now
    return data


def invalidate():
    with _lock:
        _state["data"] = None
