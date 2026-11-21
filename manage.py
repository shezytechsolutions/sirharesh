"""
Maintenance commands.

    python manage.py reset-password               set a NEW random admin password (forgot it?)
    python manage.py reset-password MyNewPass123  set a specific one
    python manage.py clean-uploads                delete all files inside static/uploads folder
    python manage.py reset-db [admin_password]    wipe database + clean uploads folder + fresh admin
    python manage.py check                        quick health check of the installation
"""
import glob
import os
import secrets
import sys

from app import create_app
from app.extensions import db
from app.models import (
    Admin, AboutBlock, Book, ContactMessage, Course, Event, FunFactor,
    LearningVideo, News, Page, PageVisit, SiteSetting, SliderImage,
    TeamMember, Testimonial, UpcomingCourse, WhyChoose
)
from app.security import password_problem


def purge_uploads(app):
    upload_folder = app.config.get("UPLOAD_FOLDER") or os.path.join(app.root_path, "static", "uploads")
    count = 0
    if os.path.isdir(upload_folder):
        for f in glob.glob(os.path.join(upload_folder, "**", "*"), recursive=True):
            if os.path.isfile(f) and not f.endswith(".gitkeep"):
                try:
                    os.remove(f)
                    count += 1
                except OSError as exc:
                    print(f"  Could not remove {os.path.basename(f)}: {exc}")
    print(f"Cleaned uploads folder: {count} file(s) removed.")
    return count


def do_reset_db(app, custom_password=None):
    # 1. Purge uploads first
    purge_uploads(app)

    # 2. Clear content tables
    Course.query.delete()
    UpcomingCourse.query.delete()
    News.query.delete()
    Event.query.delete()
    Book.query.delete()
    LearningVideo.query.delete()
    TeamMember.query.delete()
    Testimonial.query.delete()
    WhyChoose.query.delete()
    ContactMessage.query.delete()
    PageVisit.query.delete()
    SliderImage.query.delete()
    AboutBlock.query.delete()
    FunFactor.query.delete()
    Page.query.delete()
    SiteSetting.query.delete()
    Admin.query.delete()
    db.session.commit()
    print("All database tables cleared.")

    # 3. Create fresh Admin
    username = "admin"
    password = custom_password or "AimsSukkur2026"
    prob = password_problem(password, username)
    if prob:
        print(f"Error with chosen password: {prob}")
        print("Falling back to standard: AimsSukkur2026")
        password = "AimsSukkur2026"

    admin = Admin(username=username, email="admin@aimssukkur.edu.pk")
    admin.set_password(password)
    db.session.add(admin)

    # 4. Register base page and settings
    db.session.add(Page(slug="index", title="Home (Index)", is_active=True))

    baseline_settings = {
        "site_name": "AIMS Sukkur",
        "phone": "+92 300 0000000",
        "email": "info@aimssukkur.edu.pk",
        "address": "Sukkur, Sindh, Pakistan",
        "working_hours": "Mon - Sat: 9:00 AM - 5:00 PM",
        "copyright_text": "Copyright © 2026 AIMS Sukkur. All rights reserved.",
        "privacy_url": "/privacy",
        "terms_url": "/terms",
        "footer_about": "Academy of Innovative Management Sciences — Quality education and professional training in Sukkur.",
        "header_top_enabled": "1",
        "header_top_phone": "+92 300 0000000",
        "header_top_email": "info@aimssukkur.edu.pk",
        "facebook": "#",
        "twitter": "#",
        "instagram": "#",
        "youtube": "#",
        "linkedin": "#",
    }
    for k, v in baseline_settings.items():
        db.session.add(SiteSetting(key=k, value=v))

    db.session.commit()
    print("\nDatabase reset complete!")
    print(f"  Admin Username: {username}")
    print(f"  Admin Password: {password}")
    print("  Login URL     : /admin/login")


def main(argv):
    commands = ("reset-password", "check", "clean-uploads", "reset-db")
    if not argv or argv[0] not in commands:
        print(__doc__)
        return 1

    cmd = argv[0]
    app = create_app()
    with app.app_context():
        if cmd == "check":
            print("Database:", app.config["SQLALCHEMY_DATABASE_URI"].split("///")[-1][-60:])
            print("Admins  :", Admin.query.count())
            print("OK")
            return 0

        if cmd == "clean-uploads":
            purge_uploads(app)
            return 0

        if cmd == "reset-db":
            pwd = argv[1] if len(argv) > 1 else None
            do_reset_db(app, pwd)
            return 0

        if cmd == "reset-password":
            admin = Admin.query.filter_by(username="admin").first() or Admin.query.first()
            if admin is None:
                print("No admin account exists yet. Start the site once with: python run.py")
                return 1
            password = argv[1] if len(argv) > 1 else secrets.token_urlsafe(12)
            problem = password_problem(password, admin.username)
            if problem:
                print("Not accepted:", problem)
                return 1
            admin.set_password(password)
            db.session.commit()
            print(f"Password for '{admin.username}' is now: {password}")
            print("Log in at /admin/login, then change it under 'Change password'.")
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
