from flask import Blueprint, request

from ..services import cache

bp = Blueprint("admin", __name__)


@bp.context_processor
def _admin_notification_counts():
    try:
        from .site import get_unread_notif_count, get_unread_messages_count
        return {
            "unread_notif_count": get_unread_notif_count(),
            "unread_messages_count": get_unread_messages_count(),
        }
    except Exception:
        return {
            "unread_notif_count": 0,
            "unread_messages_count": 0,
        }


@bp.after_request
def _refresh_public_cache(resp):
    """Any admin write may change site settings -> drop the cached copy."""
    if request.method == "POST":
        cache.invalidate()
    return resp


from . import auth, content, site  # noqa: E402,F401  (register the routes)
