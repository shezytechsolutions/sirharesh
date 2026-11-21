"""
One place for every file upload (images and PDFs).

  save_upload(...)          -> (web_path or None, error message or None)
  remove_unreferenced(...)  -> delete old upload files nobody uses any more

Safety: the file CONTENT is checked (magic bytes), not just the extension; names are
randomised; size limits are enforced; paths can never leave the uploads folder.
"""
import os
import re
import uuid

from flask import current_app
from werkzeug.utils import secure_filename

from ..extensions import db
from ..utils import safe_url

IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "gif"}
PDF_EXT = {"pdf"}
UPLOAD_URL_PREFIX = "/static/uploads/"
_SUBDIR_RE = re.compile(r"^[a-z0-9_]{1,40}$")


def _sniff_image(head):
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _sniff_pdf(head):
    return "pdf" if head.lstrip(b"\x00 \t\r\n")[:5] == b"%PDF-" else None


def save_upload(file_storage, subdir, kind="image", prefix=""):
    """
    Save an uploaded file. Returns (web_path, error).
      (None, None)  -> nothing was uploaded
      (path, None)  -> saved
      (None, "msg") -> rejected, show `msg` to the admin
    """
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None, None
    if not _SUBDIR_RE.match(subdir):
        return None, "Invalid upload folder."

    original = file_storage.filename
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    allowed = IMAGE_EXT if kind == "image" else PDF_EXT
    label = "image (PNG, JPG, WEBP or GIF)" if kind == "image" else "PDF"
    if ext not in allowed:
        return None, f"Unsupported file '{original}'. Please upload a {label}."

    stream = file_storage.stream
    head = stream.read(16)
    stream.seek(0)
    real_ext = _sniff_image(head) if kind == "image" else _sniff_pdf(head)
    if not real_ext:
        if not head:
            return None, f"The uploaded file '{original}' is empty (0 bytes). Please choose it again."
        return None, f"'{original}' does not look like a valid {label}."

    stem = secure_filename(os.path.splitext(original)[0])[:50].strip("._-") or ("file" if kind == "image" else "document")
    fname = f"{prefix}{stem}_{uuid.uuid4().hex[:10]}.{real_ext}"

    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], subdir)
    os.makedirs(folder, exist_ok=True)
    full = os.path.join(folder, fname)
    file_storage.save(full)

    size = os.path.getsize(full)
    limit = current_app.config["MAX_IMAGE_BYTES"] if kind == "image" else current_app.config["MAX_CONTENT_LENGTH"]
    if size == 0:
        os.remove(full)
        return None, f"The uploaded file '{original}' is empty (0 bytes). Please choose it again."
    if size > limit:
        os.remove(full)
        return None, f"'{original}' is too large (max {limit // (1024 * 1024)} MB)."

    return f"{UPLOAD_URL_PREFIX}{subdir}/{fname}", None


def clean_path_input(value):
    """Sanitise a typed-in image/PDF path or URL (blocks javascript:, data:, ...)."""
    return safe_url(value)


# --------------------------------------------------------------------- cleanup
def _file_columns():
    from ..models import (SliderImage, News, Course, UpcomingCourse, Event, Book,
                          LearningVideo, TeamMember, Testimonial, AboutBlock)
    return [
        (SliderImage, "image"), (News, "image"), (Course, "image"), (Course, "pdf"),
        (Course, "teacher_image"), (UpcomingCourse, "image"), (Event, "image"),
        (Book, "image"), (Book, "pdf"), (LearningVideo, "custom_thumbnail"),
        (TeamMember, "image"), (Testimonial, "image"), (AboutBlock, "image"),
    ]


def _is_referenced(path):
    for model, col in _file_columns():
        if db.session.query(model.id).filter(getattr(model, col) == path).first():
            return True
    return False


def remove_unreferenced(paths):
    """Delete uploaded files in `paths` that no database row points to any more."""
    root = os.path.realpath(current_app.config["UPLOAD_FOLDER"])
    for path in {p for p in paths if p}:
        if not path.startswith(UPLOAD_URL_PREFIX):
            continue                      # shipped assets (/static/img/...) are never deleted
        rel = path[len(UPLOAD_URL_PREFIX):].split("?")[0].split("#")[0]
        full = os.path.realpath(os.path.join(root, rel))
        if os.path.commonpath([root, full]) != root or not os.path.isfile(full):
            continue
        try:
            if not _is_referenced(path):
                os.remove(full)
        except OSError:
            pass
