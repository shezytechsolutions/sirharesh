"""
PDF section - restored exactly as it was in the original project (old app.py).

* The detail pages show the PDF in a plain <iframe> (the browser's own viewer).
* Local PDFs are streamed by the two routes below: read once, plain 200 response,
  "no-cache, must-revalidate", Content-Disposition only for ?download=1.
* External http(s) links are used as they are.

Only change compared with the old file: the code lives in the `public` blueprint
(so url_for endpoints are 'public.course_pdf' / 'public.book_pdf').
"""
import os
from urllib.parse import unquote

from flask import Response, abort, current_app, request, url_for

from ..models import Book, Course
from . import bp


def pdf_urls(item, endpoint, id_kwarg):
    """Original logic from course_detail() / book_detail(): returns (pdf_url, pdf_download_url)."""
    # Local PDFs are streamed by our own route (correct PDF headers + range support);
    # external http(s) links are used as-is.
    pdf_url = pdf_download_url = ""
    raw = (item.pdf or "").strip()
    if raw.startswith(("http://", "https://")):
        pdf_url = pdf_download_url = raw
    elif raw:
        try:
            _static_root = os.path.abspath(current_app.static_folder)
            _rel = unquote(raw).split("?")[0].replace("\\", "/").lstrip("/")
            _rel = _rel[len("static/"):] if _rel.startswith("static/") else _rel
            _ver = int(os.path.getmtime(os.path.join(_static_root, _rel)))
        except OSError:
            _ver = 0
        pdf_url = url_for(endpoint, **{id_kwarg: item.id}, v=_ver)
        pdf_download_url = url_for(endpoint, **{id_kwarg: item.id}, download=1, v=_ver)
    return pdf_url, pdf_download_url


def _serve_pdf(item, reupload_hint):
    """Original body of course_pdf() / book_pdf() (they were identical apart from the hint text)."""
    rel = unquote((item.pdf or "").strip()).split("?")[0].split("#")[0]
    rel = rel.replace("\\", "/").lstrip("/")
    if rel.startswith("static/"):
        rel = rel[len("static/"):]
    static_root = os.path.abspath(current_app.static_folder)
    full = os.path.abspath(os.path.join(static_root, rel))
    if not rel or not full.startswith(static_root + os.sep) or not os.path.isfile(full):
        abort(404)
    if os.path.getsize(full) == 0:
        return Response(f"The PDF file on the server is empty (0 bytes). Re-upload it in {reupload_hint}.",
                        status=422, mimetype="text/plain")

    # Read once and return a plain 200 response: avoids Werkzeug's Range
    # handling, which can answer 204 to edge-case range requests and makes
    # PDF.js abort with UnexpectedResponseException.
    with open(full, "rb") as f:
        data = f.read()

    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Length"] = str(len(data))
    resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    if request.args.get("download"):
        resp.headers["Content-Disposition"] = f'attachment; filename="{os.path.basename(full)}"'
    return resp


@bp.route("/course-pdf/<int:course_id>")
def course_pdf(course_id):
    """Serve a course PDF from the static folder (never outside it)."""
    item = Course.query.filter_by(id=course_id, is_active=True).first_or_404()
    return _serve_pdf(item, "Admin > Courses")


@bp.route("/book-pdf/<int:book_id>")
def book_pdf(book_id):
    """Serve a book PDF from the static folder (never outside it)."""
    item = Book.query.filter_by(id=book_id, is_active=True).first_or_404()
    return _serve_pdf(item, "Admin > E-Library")
