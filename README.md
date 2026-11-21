# AIMS Sukkur website (Flask)

Public website + admin panel for courses, news, events, e-library, videos, faculty and contact messages.

## Run it

```bat
start_server.bat          (Windows: creates venv, installs, starts, opens the browser)
```
or manually:

```bash
pip install -r requirements.txt
python run.py             # production-style server (Waitress)  -> http://localhost:5000
python run.py --debug     # development server with auto-reload (this PC only)
```

Admin panel: `http://localhost:5000/admin/login` (username `admin`).
**Forgot the password?** `python manage.py reset-password` prints a new one.
**Reset everything?** `python manage.py reset-db` clears the database + purges the `static/uploads/` folder.
**Clean uploads only?** `python manage.py clean-uploads` deletes all uploaded files.

On the very first start of a brand-new install a random admin password is printed in the console
(or set `ADMIN_PASSWORD` in `.env`). There is no default password any more.

## Settings (.env)

Copy `.env.example` to `.env`. Everything is optional. The important ones when the site is public
(Cloudflare Tunnel / HTTPS): `TRUST_PROXY=1` and `COOKIE_SECURE=1`.

## Folder layout

```
run.py / serve.py / manage.py     start the site / maintenance commands
app/
  __init__.py                     create_app(): wires everything together
  config.py                       settings (env vars / .env)
  security.py                     CSRF, login lockout, security headers, session checks
  utils.py                        small helpers (safe links, int parsing)
  models/                         database tables: content.py, people.py, site.py
  public/                         visitor pages: routes.py, pdf.py (PDF streaming + caching)
  admin/                          admin panel
    auth.py                       login / logout / change password
    content.py                    news, courses, events, books, videos, team ... (declarative)
    crud.py                       the ONE generic add/edit/delete/toggle engine
    site.py                       dashboard, messages inbox, about, settings, page editor
  services/
    uploads.py                    every image/PDF upload goes through here
    bootstrap.py                  DB tables, light migrations, indexes, first admin
    seed.py                       demo content for a brand-new database
    cache.py                      30-second cache for site settings
  templates/  static/             same design as before
instance/                         edubuzz.db (your data) + secret key  - never share this folder
tests/                            pytest suite (pip install pytest; python -m pytest)
docs/NOTES.md                     your original project notes
```

## How to add a new admin list page (example: "Notices")

1. Add the model in `app/models/content.py` (and export it in `app/models/__init__.py`).
2. In `app/admin/content.py` declare it - no request-handling code needed:

```python
NOTICES = Crud(Notice, "Notice",
               fields=[Field("title", required=True), Field("content"), Field("order", "int")],
               files=[FileField("image", "image_path", "image", "image", "notices")])
crud_page("/admin/notices", "admin_notices", NOTICES, "admin/notices.html")
```
3. Copy an existing admin template (e.g. `testimonials.html`) and adjust the fields.

## PDFs (courses and e-library)

The PDF section is the **original one from the first version of the project** (restored unchanged):
the detail pages show the PDF in an `<iframe>` (the browser's own viewer) and the PDF is delivered by
`/course-pdf/<id>` and `/book-pdf/<id>` - see `app/public/pdf.py`.

* Upload limit for PDFs: 95 MB (`MAX_UPLOAD_MB` in `.env`).
* **Admin > PDF check** lists every course/book PDF and tells you if the file is OK, MISSING, EMPTY (0 bytes)
  or not a real PDF - and exactly which folder the file must be in. (Read-only helper; it does not change
  how PDFs are shown.)
* Moving the project to a new folder? Copy the old `static/uploads/` folder into `app/static/uploads/`
  (files from an old `static/uploads/` next to `run.py` are copied automatically on start).

## Backups

Copy `instance/edubuzz.db` and `app/static/uploads/`. That is all your data.

## Tests

```bash
pip install pytest
python -m pytest tests -q
```
