"""Database preparation that runs at start-up: tables, light migrations, indexes, admin account."""
import os
import secrets
import shutil

from flask import current_app
from sqlalchemy import inspect, text

from ..extensions import db
from ..models import Admin

INDEXES = [
    ("ix_news_listing", "news", '(is_active, show_on_home, "order")'),
    ("ix_courses_listing", "courses", '(is_active, show_on_home, "order")'),
    ("ix_events_listing", "events", '(is_active, show_on_home, "order")'),
    ("ix_books_listing", "books", '(is_active, show_on_home, "order")'),
    ("ix_videos_listing", "learning_videos", '(is_active, show_on_home, "order")'),
    ("ix_upcoming_listing", "upcoming_courses", '(is_active, "order")'),
    ("ix_team_listing", "team_members", '(is_active, "order")'),
    ("ix_testimonials_listing", "testimonials", '(is_active, "order")'),
    ("ix_whychoose_listing", "why_choose", '(is_active, "order")'),
    ("ix_slider_listing", "slider_images", '(page_slug, is_active, "order")'),
    ("ix_funfactors_order", "fun_factors", '("order")'),
    ("ix_contact_created", "contact_messages", "(created_at)"),
    ("ix_page_visits_created", "page_visits", "(created_at)"),
    ("ix_page_visits_ip", "page_visits", "(ip)"),
]


def ensure_schema():
    """Add columns that older databases lack, and create speed-up indexes (idempotent)."""
    insp = inspect(db.engine)
    wanted = [
        ("slider_images", "pos_desktop", "VARCHAR(40) DEFAULT 'center center'"),
        ("slider_images", "pos_mobile", "VARCHAR(40) DEFAULT 'center center'"),
        ("courses", "pdf", "VARCHAR(255)"),
    ]
    for table, column, ddl in wanted:
        try:
            if table in insp.get_table_names() and column not in [c["name"] for c in insp.get_columns(table)]:
                with db.engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        except Exception as exc:            # never block start-up on a migration hiccup
            current_app.logger.warning("Schema note (%s.%s): %s", table, column, exc)

    for name, table, cols in INDEXES:
        try:
            with db.engine.begin() as conn:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {cols}"))
        except Exception as exc:
            current_app.logger.warning("Index note (%s): %s", name, exc)


def _password_file():
    return os.path.join(current_app.instance_path, "first_admin_password.txt")


def forget_first_password_file():
    try:
        os.remove(_password_file())
    except OSError:
        pass


def _announce(username, password, reason):
    msg = (
        "\n" + "=" * 66 +
        f"\n  {reason}\n  Admin login  ->  username: {username}   password: {password}"
        "\n  Log in at /admin/login and change it right away (Change password)."
        "\n" + "=" * 66 + "\n"
    )
    print(msg, flush=True)
    try:
        os.makedirs(current_app.instance_path, exist_ok=True)
        with open(_password_file(), "w", encoding="utf-8") as fh:
            fh.write(f"username: {username}\npassword: {password}\n(delete this file after logging in)\n")
    except OSError:
        pass


def ensure_admin():
    """
    Make sure an admin exists and that nobody can log in with the old default password.
    Returns True when this is a brand-new installation (no admin existed before).
    """
    fresh = Admin.query.count() == 0
    if fresh:
        password = current_app.config.get("ADMIN_PASSWORD") or secrets.token_urlsafe(12)
        admin = Admin(username="admin", email="admin@example.com")
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        if not current_app.config.get("ADMIN_PASSWORD"):
            _announce("admin", password, "FIRST RUN - an admin account was created.")
        return True

    legacy = Admin.query.filter_by(username="admin").first()
    if legacy and legacy.check_password("admin123"):
        password = secrets.token_urlsafe(12)
        legacy.set_password(password)
        db.session.commit()
        _announce("admin", password, "SECURITY - the insecure default password 'admin123' was replaced.")
    return False


def migrate_legacy_uploads():
    """
    Before the restructure uploads lived in <project>/static/uploads. Copy anything found there into
    app/static/uploads (never overwrites, never deletes) so old PDFs / images keep working.
    """
    from ..config import BASE_DIR
    legacy = os.path.join(BASE_DIR, "static", "uploads")
    target = current_app.config["UPLOAD_FOLDER"]
    if not os.path.isdir(legacy) or os.path.realpath(legacy) == os.path.realpath(target):
        return
    copied = 0
    for root, _dirs, files in os.walk(legacy):
        rel = os.path.relpath(root, legacy)
        for name in files:
            dest = os.path.join(target, rel, name)
            if os.path.exists(dest):
                continue
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(os.path.join(root, name), dest)
                copied += 1
            except OSError as exc:
                current_app.logger.warning("Could not migrate %s: %s", name, exc)
    if copied:
        current_app.logger.info("Migrated %d uploaded file(s) from the old static/uploads folder.", copied)


def check_pdfs():
    """Log (once, at start-up) every PDF that the database points to but the server cannot serve."""
    from ..models import Book, Course
    from .pdf_files import inspect_pdf
    problems = []
    for model in (Course, Book):
        for item in model.query.all():
            state = inspect_pdf(item.pdf)["state"]
            if state in ("missing", "empty", "invalid"):
                problems.append(f"{model.__name__} #{item.id} '{item.title}': {state}")
    if problems:
        current_app.logger.warning("PDF self-check: %d missing/invalid file(s):\n  %s",
                                   len(problems), "\n  ".join(problems))


def init_db():
    db.create_all()
    ensure_schema()
    fresh = ensure_admin()
    if fresh:
        from .seed import seed_defaults
        seed_defaults()
    migrate_legacy_uploads()
    check_pdfs()
