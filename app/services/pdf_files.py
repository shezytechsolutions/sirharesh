"""
Locating and checking PDF files on disk. Used by the public viewer, the PDF streaming route,
the admin "PDF check" page and the start-up self-check - so they all agree on what "exists" means.
"""
import os
from urllib.parse import unquote

from flask import current_app


def resolve_pdf(raw):
    """Map a stored path such as /static/uploads/courses/x.pdf to a real file inside static/ (or None)."""
    rel = unquote((raw or "").strip()).split("?")[0].split("#")[0].replace("\\", "/").lstrip("/")
    if rel.startswith("static/"):
        rel = rel[len("static/"):]
    if not rel or not rel.lower().endswith(".pdf"):
        return None
    root = os.path.realpath(current_app.static_folder)
    full = os.path.realpath(os.path.join(root, rel))
    try:
        inside = os.path.commonpath([root, full]) == root
    except ValueError:                      # different drives on Windows
        inside = False
    return full if inside and os.path.isfile(full) else None


def expected_location(raw):
    """Where the file is expected on disk (for messages), even if it is missing."""
    rel = unquote((raw or "").strip()).split("?")[0].split("#")[0].replace("\\", "/").lstrip("/")
    if rel.startswith("static/"):
        rel = rel[len("static/"):]
    return os.path.join(current_app.static_folder, *rel.split("/")) if rel else ""


def inspect_pdf(raw):
    """
    Returns a dict: state, size, full, expected
      state: none | external | missing | empty | invalid | ok
    """
    raw = (raw or "").strip()
    info = {"state": "none", "size": 0, "full": None, "expected": ""}
    if not raw:
        return info
    if raw.startswith(("http://", "https://")):
        info["state"] = "external"
        return info
    info["expected"] = expected_location(raw)
    full = resolve_pdf(raw)
    if not full:
        info["state"] = "missing"
        return info
    info["full"] = full
    info["size"] = os.path.getsize(full)
    if info["size"] == 0:
        info["state"] = "empty"
        return info
    try:
        with open(full, "rb") as fh:
            head = fh.read(1024)
    except OSError:
        info["state"] = "missing"
        return info
    info["state"] = "ok" if b"%PDF-" in head else "invalid"     # e.g. an HTML error page saved as .pdf
    return info
