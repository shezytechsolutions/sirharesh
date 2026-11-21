"""Admin: dashboard, messages inbox, about page, site settings, page editor (slider / counters / testimonials)."""
import glob
import os
import shutil
from datetime import datetime, timedelta
from flask import current_app, flash, has_request_context, redirect, render_template, request, session, url_for
from sqlalchemy import func

from ..extensions import db
from ..models import (AboutBlock, Admin, Book, ContactMessage, Course, Event, FunFactor, LearningVideo, News,
                      Page, PageVisit, SiteSetting, SliderImage, TeamMember, Testimonial, UpcomingCourse, WhyChoose)
from ..security import login_required, password_problem, password_stamp, safe_back
from ..services.pdf_files import inspect_pdf
from ..services.uploads import clean_path_input, remove_unreferenced, save_upload
from ..utils import form_str, safe_url, to_int
from . import bp
from .crud import Crud, Field, FileField


# ----------------------------------------------------------------- dashboard
@bp.route("/admin")
@bp.route("/admin/dashboard")
@login_required
def admin_dashboard():
    stats = {
        "news": News.query.count(),
        "courses": Course.query.count(),
        "upcoming": UpcomingCourse.query.count(),
        "events": Event.query.count(),
        "books": Book.query.count(),
        "videos": LearningVideo.query.count(),
        "team": TeamMember.query.count(),
        "testimonials": Testimonial.query.count(),
        "fun_factors": FunFactor.query.count(),
        "messages": ContactMessage.query.count(),
        "unread_messages": get_unread_messages_count(),
    }
    # Visitor analytics (last 24h / 7d / total)
    now = datetime.utcnow()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    stats["visits_today"] = PageVisit.query.filter(PageVisit.created_at >= day_ago).count()
    stats["visits_week"] = PageVisit.query.filter(PageVisit.created_at >= week_ago).count()
    stats["visits_total"] = PageVisit.query.count()
    stats["unique_ips_today"] = (
        db.session.query(func.count(func.distinct(PageVisit.ip)))
        .filter(PageVisit.created_at >= day_ago)
        .scalar()
        or 0
    )

    # Chart data: visits per hour for last 24 hours
    hours = []
    counts = []
    for i in range(23, -1, -1):
        start = now - timedelta(hours=i + 1)
        end = now - timedelta(hours=i)
        label = end.strftime("%H:00")
        c = PageVisit.query.filter(
            PageVisit.created_at >= start, PageVisit.created_at < end
        ).count()
        hours.append(label)
        counts.append(c)

    raw_recent = (
        PageVisit.query.order_by(PageVisit.created_at.desc()).limit(100).all()
    )
    recent_visits = []
    last_seen_by_ip = {}
    for v in raw_recent:
        if not v.created_at:
            recent_visits.append(v)
            continue
        last_t = last_seen_by_ip.get(v.ip)
        if last_t is None or abs((last_t - v.created_at).total_seconds()) >= 120:
            recent_visits.append(v)
            last_seen_by_ip[v.ip] = v.created_at
        if len(recent_visits) >= 20:
            break

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        chart_labels=hours,
        chart_counts=counts,
        recent_visits=recent_visits,
    )


@bp.route("/admin/api/analytics")
@login_required
def admin_api_analytics():
    """JSON endpoint for dashboard chart / live refresh."""
    now = datetime.utcnow()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    hours, counts = [], []
    for i in range(23, -1, -1):
        start = now - timedelta(hours=i + 1)
        end = now - timedelta(hours=i)
        hours.append(end.strftime("%H:00"))
        counts.append(
            PageVisit.query.filter(
                PageVisit.created_at >= start, PageVisit.created_at < end
            ).count()
        )
    raw_recent = (
        PageVisit.query.order_by(PageVisit.created_at.desc()).limit(100).all()
    )
    recent = []
    last_seen_by_ip = {}
    for v in raw_recent:
        if not v.created_at:
            recent.append(v)
            continue
        last_t = last_seen_by_ip.get(v.ip)
        if last_t is None or abs((last_t - v.created_at).total_seconds()) >= 120:
            recent.append(v)
            last_seen_by_ip[v.ip] = v.created_at
        if len(recent) >= 20:
            break

    return {
        "visits_today": PageVisit.query.filter(PageVisit.created_at >= day_ago).count(),
        "visits_week": PageVisit.query.filter(PageVisit.created_at >= week_ago).count(),
        "visits_total": PageVisit.query.count(),
        "unique_ips_today": (
            db.session.query(func.count(func.distinct(PageVisit.ip)))
            .filter(PageVisit.created_at >= day_ago)
            .scalar()
            or 0
        ),
        "chart_labels": hours,
        "chart_counts": counts,
        "recent": [
            {
                "ip": v.ip,
                "path": v.path,
                "ua": (v.user_agent or "")[:80],
                "at": v.created_at.strftime("%Y-%m-%d %H:%M:%S") if v.created_at else "",
            }
            for v in recent
        ],
    }


# ------------------------------------------------------------- notifications & messages helpers
def get_unread_notif_count():
    """Count of unread notifications (contact messages) based on persistent db checkpoint."""
    total = ContactMessage.query.count()
    if total == 0:
        return 0
    row = SiteSetting.query.filter_by(key="admin_notif_last_read_id").first()
    if not row or not row.value:
        return total
    max_id = db.session.query(func.max(ContactMessage.id)).scalar() or 0
    last_id = to_int(row.value, 0)
    if last_id > max_id:
        last_id = max_id
    return ContactMessage.query.filter(ContactMessage.id > last_id).count()


def get_unread_messages_count():
    """Count of unread contact messages based on persistent db checkpoint."""
    total = ContactMessage.query.count()
    if total == 0:
        return 0
    row = SiteSetting.query.filter_by(key="admin_messages_last_read_id").first()
    if not row or not row.value:
        return total
    max_id = db.session.query(func.max(ContactMessage.id)).scalar() or 0
    last_id = to_int(row.value, 0)
    if last_id > max_id:
        last_id = max_id
    return ContactMessage.query.filter(ContactMessage.id > last_id).count()


def mark_notifications_read():
    """Mark all current notifications as read in the database."""
    max_id = db.session.query(func.max(ContactMessage.id)).scalar() or 0
    now_str = datetime.utcnow().isoformat()

    id_row = SiteSetting.query.filter_by(key="admin_notif_last_read_id").first()
    if not id_row:
        id_row = SiteSetting(key="admin_notif_last_read_id", value=str(max_id))
        db.session.add(id_row)
    else:
        id_row.value = str(max_id)

    time_row = SiteSetting.query.filter_by(key="admin_notif_last_read_time").first()
    if not time_row:
        time_row = SiteSetting(key="admin_notif_last_read_time", value=now_str)
        db.session.add(time_row)
    else:
        time_row.value = now_str

    db.session.commit()
    if has_request_context():
        session["notif_checkout_time"] = now_str
        session["notif_checkout_id"] = max_id
        session.modified = True


def mark_messages_read():
    """Mark all current messages as read in the database."""
    max_id = db.session.query(func.max(ContactMessage.id)).scalar() or 0
    now_str = datetime.utcnow().isoformat()

    id_row = SiteSetting.query.filter_by(key="admin_messages_last_read_id").first()
    if not id_row:
        id_row = SiteSetting(key="admin_messages_last_read_id", value=str(max_id))
        db.session.add(id_row)
    else:
        id_row.value = str(max_id)

    time_row = SiteSetting.query.filter_by(key="admin_messages_last_read_time").first()
    if not time_row:
        time_row = SiteSetting(key="admin_messages_last_read_time", value=now_str)
        db.session.add(time_row)
    else:
        time_row.value = now_str

    db.session.commit()
    if has_request_context():
        session["messages_read_time"] = now_str
        session["messages_read_id"] = max_id
        session.modified = True


@bp.route("/admin/api/notifications/checkout", methods=["POST"])
@login_required
def admin_api_notifications_checkout():
    """Checkout notifications and/or messages, resetting badge count to zero in DB."""
    data = request.get_json(silent=True) or {}
    target = request.args.get("type") or data.get("type") or "notifications"
    if target == "messages":
        mark_messages_read()
        return {"ok": True, "type": "messages"}
    elif target == "all":
        mark_notifications_read()
        mark_messages_read()
        return {"ok": True, "type": "all"}
    else:
        mark_notifications_read()
        return {"ok": True, "type": "notifications"}


@bp.route("/admin/api/notifications")
@login_required
def admin_api_notifications():
    """Lightweight notifications feed for badges & popup (poll-friendly)."""
    notif_count = get_unread_notif_count()
    messages_count = get_unread_messages_count()

    notif_row = SiteSetting.query.filter_by(key="admin_notif_last_read_id").first()
    notif_last_id = to_int(notif_row.value, 0) if notif_row and notif_row.value else None

    msg_row = SiteSetting.query.filter_by(key="admin_messages_last_read_id").first()
    msg_last_id = to_int(msg_row.value, 0) if msg_row and msg_row.value else None

    msgs = (
        ContactMessage.query.order_by(ContactMessage.created_at.desc()).limit(8).all()
    )

    items = []
    for m in msgs:
        is_new_notif = (notif_last_id is None) or (m.id > notif_last_id)
        items.append(
            {
                "id": m.id,
                "type": "message",
                "title": m.name or "Visitor",
                "body": (m.subject or m.message or "")[:120],
                "at": m.created_at.strftime("%Y-%m-%d %H:%M") if m.created_at else "",
                "url": url_for("admin.admin_messages"),
                "is_new": is_new_notif,
            }
        )

    visits_1h = PageVisit.query.filter(
        PageVisit.created_at >= datetime.utcnow() - timedelta(hours=1)
    ).count()

    if visits_1h:
        items.insert(
            0,
            {
                "type": "traffic",
                "title": f"{visits_1h} visit(s) in the last hour",
                "body": "Open dashboard for IP and page details.",
                "at": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
                "url": url_for("admin.admin_dashboard"),
                "is_new": False,
            },
        )

    latest_msg = msgs[0] if msgs else None
    latest_info = None
    if latest_msg:
        is_msg_new = (msg_last_id is None) or (latest_msg.id > msg_last_id)
        latest_info = {
            "id": latest_msg.id,
            "name": latest_msg.name or "Website Visitor",
            "subject": latest_msg.subject or "Contact Message",
            "message": (latest_msg.message or "")[:140],
            "is_new": is_msg_new,
            "created_at": latest_msg.created_at.strftime("%H:%M") if latest_msg.created_at else "",
        }

    return {
        "count": notif_count,
        "notif_count": notif_count,
        "messages_count": messages_count,
        "items": items,
        "latest_message": latest_info,
    }


@bp.route("/admin/notifications")
@login_required
def admin_notifications():
    mark_notifications_read()
    msgs = (
        ContactMessage.query.order_by(ContactMessage.created_at.desc()).limit(50).all()
    )
    recent_visits = (
        PageVisit.query.order_by(PageVisit.created_at.desc()).limit(40).all()
    )
    return render_template(
        "admin/notifications.html", messages=msgs, recent_visits=recent_visits
    )



# ------------------------------------------------------------ contact messages
@bp.route("/admin/messages", methods=["GET", "POST"])
@login_required
def admin_messages():
    if request.method == "POST":
        if request.form.get("action") == "delete":
            msg = db.session.get(ContactMessage, to_int(request.form.get("id"), 0))
            if msg:
                db.session.delete(msg)
                db.session.commit()
                flash("Message deleted.", "info")
        return redirect(url_for("admin.admin_messages"))

    mark_messages_read()
    items = ContactMessage.query.order_by(ContactMessage.created_at.desc()).limit(500).all()
    return render_template("admin/messages.html", items=items)


# ------------------------------------------------------------------ about page
ABOUT_KEYS = ["hero_title", "hero_text", "hero_image", "mission", "vision", "values"]


@bp.route("/admin/about", methods=["GET", "POST"])
@login_required
def admin_about():
    """Unified About Page Customizer: About Story/Pillars, Why Choose Us, and Faculty & Team."""
    if request.method == "POST":
        action = request.form.get("action", "")

        # 1. Save About Story & Hero Image
        if action == "save_story":
            existing = {b.key: b for b in AboutBlock.query.all()}

            title_val = form_str(request.form, "hero_title")
            b_title = existing.get("hero_title") or AboutBlock(key="hero_title")
            b_title.title = title_val
            db.session.add(b_title)

            text_val = form_str(request.form, "hero_text")
            b_text = existing.get("hero_text") or AboutBlock(key="hero_text")
            b_text.content = text_val
            db.session.add(b_text)

            b_img = existing.get("hero_image") or AboutBlock(key="hero_image")
            uploaded_img = request.files.get("hero_image")
            img_path, err = save_upload(uploaded_img, "about", "image")
            if err:
                flash(err, "error")
            elif img_path:
                b_img.image = img_path
                db.session.add(b_img)
            elif request.form.get("hero_image_path"):
                clean_img = clean_path_input(request.form.get("hero_image_path"))
                if clean_img:
                    b_img.image = clean_img
                    db.session.add(b_img)

            db.session.commit()
            flash("About Story and Image saved successfully.", "success")
            return redirect(url_for("admin.admin_about", _anchor="story"))

        # 2. Save Mission, Vision, and Values
        elif action == "save_pillars":
            existing = {b.key: b for b in AboutBlock.query.all()}
            for key in ("mission", "vision", "values"):
                b = existing.get(key) or AboutBlock(key=key)
                b.title = form_str(request.form, f"{key}_title") or b.title or key.title()
                b.content = form_str(request.form, f"{key}_text") or b.content
                db.session.add(b)
            db.session.commit()
            flash("Mission, Vision, and Values updated successfully.", "success")
            return redirect(url_for("admin.admin_about", _anchor="story"))

        # 3. Why Choose Us Actions
        elif action == "add_why":
            title = form_str(request.form, "title")
            content = form_str(request.form, "content")
            icon = form_str(request.form, "icon") or "zmdi-check"
            ord_val = to_int(request.form.get("order", 0))
            if not title:
                flash("Title is required for Why Choose Us.", "error")
            else:
                item = WhyChoose(title=title, content=content, icon=icon, order=ord_val, is_active=True)
                db.session.add(item)
                db.session.commit()
                flash("Feature added to Why Choose Us.", "success")
            return redirect(url_for("admin.admin_about", _anchor="why-choose"))

        elif action == "edit_why":
            wid = to_int(request.form.get("id"))
            w = db.session.get(WhyChoose, wid) if wid else None
            if w:
                w.title = form_str(request.form, "title") or w.title
                w.content = form_str(request.form, "content") or w.content
                w.icon = form_str(request.form, "icon") or w.icon
                w.order = to_int(request.form.get("order", w.order))
                db.session.commit()
                flash("Why Choose Us feature updated.", "success")
            else:
                flash("Feature not found.", "error")
            return redirect(url_for("admin.admin_about", _anchor="why-choose"))

        elif action == "delete_why":
            wid = to_int(request.form.get("id"))
            w = db.session.get(WhyChoose, wid) if wid else None
            if w:
                db.session.delete(w)
                db.session.commit()
                flash("Feature deleted.", "success")
            return redirect(url_for("admin.admin_about", _anchor="why-choose"))

        # 4. Faculty & Team Actions
        elif action == "add_team":
            name = form_str(request.form, "name")
            role = form_str(request.form, "role")
            qualification = form_str(request.form, "qualification")
            email = form_str(request.form, "email")
            linkedin = safe_url(form_str(request.form, "linkedin")) if form_str(request.form, "linkedin") else None
            ord_val = to_int(request.form.get("order", 0))

            if not name:
                flash("Name is required.", "error")
            else:
                uploaded_photo = request.files.get("image")
                photo_path, err = save_upload(uploaded_photo, "team", "image")
                if err:
                    flash(err, "error")
                elif not photo_path and request.form.get("image_path"):
                    photo_path = clean_path_input(request.form.get("image_path"))

                member = TeamMember(
                    name=name,
                    role=role or "Faculty",
                    qualification=qualification,
                    email=email,
                    linkedin=linkedin,
                    image=photo_path,
                    order=ord_val,
                    is_active=True
                )
                db.session.add(member)
                db.session.commit()
                flash(f"Faculty member '{name}' added successfully.", "success")
            return redirect(url_for("admin.admin_about", _anchor="team"))

        elif action == "edit_team":
            mid = to_int(request.form.get("id"))
            m = db.session.get(TeamMember, mid) if mid else None
            if m:
                m.name = form_str(request.form, "name") or m.name
                m.role = form_str(request.form, "role") or m.role
                m.qualification = form_str(request.form, "qualification") or m.qualification
                m.email = form_str(request.form, "email") or m.email
                if form_str(request.form, "linkedin"):
                    m.linkedin = safe_url(form_str(request.form, "linkedin"))
                m.order = to_int(request.form.get("order", m.order))

                uploaded_photo = request.files.get("image")
                photo_path, err = save_upload(uploaded_photo, "team", "image")
                if photo_path:
                    m.image = photo_path
                elif request.form.get("image_path"):
                    clean_p = clean_path_input(request.form.get("image_path"))
                    if clean_p:
                        m.image = clean_p

                db.session.commit()
                flash(f"Faculty member '{m.name}' updated.", "success")
            else:
                flash("Faculty member not found.", "error")
            return redirect(url_for("admin.admin_about", _anchor="team"))

        elif action == "toggle_team":
            mid = to_int(request.form.get("id"))
            m = db.session.get(TeamMember, mid) if mid else None
            if m:
                m.is_active = not m.is_active
                db.session.commit()
                flash(f"'{m.name}' is now {'visible' if m.is_active else 'hidden'}.", "success")
            return redirect(url_for("admin.admin_about", _anchor="team"))

        elif action == "delete_team":
            mid = to_int(request.form.get("id"))
            m = db.session.get(TeamMember, mid) if mid else None
            if m:
                name = m.name
                db.session.delete(m)
                db.session.commit()
                flash(f"Faculty member '{name}' deleted.", "success")
            return redirect(url_for("admin.admin_about", _anchor="team"))

        return redirect(url_for("admin.admin_about"))

    blocks = {b.key: b for b in AboutBlock.query.all()}
    why_choose = WhyChoose.query.order_by(WhyChoose.order).all()
    team_members = TeamMember.query.order_by(TeamMember.order).all()

    return render_template(
        "admin/about.html",
        blocks=blocks,
        why_choose=why_choose,
        team_members=team_members,
    )


# ------------------------------------------------------------------- settings & maintenance
def do_database_wipe(purge_files=False):
    """
    Clears database records. If purge_files is True, also deletes all files in static/uploads.
    Restores clean default admin (admin / AimsSukkur2026) and baseline settings.
    """
    if purge_files:
        upload_folder = current_app.config.get("UPLOAD_FOLDER") or os.path.join(current_app.root_path, "static", "uploads")
        if os.path.isdir(upload_folder):
            for f in glob.glob(os.path.join(upload_folder, "**", "*"), recursive=True):
                if os.path.isfile(f) and not f.endswith(".gitkeep"):
                    try:
                        os.remove(f)
                    except OSError:
                        pass

    # Clear all content tables
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

    # Recreate default admin
    admin = Admin(username="admin", email="admin@aimssukkur.edu.pk")
    admin.set_password("AimsSukkur2026")
    db.session.add(admin)

    # Recreate default index page
    db.session.add(Page(slug="index", title="Home (Index)", is_active=True))

    # Baseline site settings
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
    try:
        from ..services.cache import invalidate
        invalidate()
    except Exception:
        pass


def do_create_demo_data():
    """
    Creates complete, comprehensive demo data across the entire site:
    - 4 Courses (with syllabus PDF, cover posters, and instructor profile)
    - 2 Upcoming Courses (with batches, dates, and instructor)
    - 4 News / Announcements (with dates, details, and cover images)
    - 4 E-Library / Books (with attached PDF syllabus, author, and covers)
    - 4 Events (with dates, times, locations, and descriptions)
    - 8 Learning Videos (with real YouTube embed IDs, durations, categories)
    - Vision, Mission, Values & About Blocks (with modern content and hero image)
    - 4 Why Choose Us pillars (with icons and modern copy)
    - 3 Teachers / Faculty members (using user's provided character image)
    - 4 Fun Factor counters
    - 3 Student Testimonials
    - 2 Hero Sliders for Index Page
    """
    demo_assets_dir = os.path.join(current_app.root_path, "static", "demo_assets")
    uploads_dir = current_app.config.get("UPLOAD_FOLDER") or os.path.join(current_app.root_path, "static", "uploads")
    courses_dir = os.path.join(uploads_dir, "courses")
    team_dir = os.path.join(uploads_dir, "team")
    os.makedirs(courses_dir, exist_ok=True)
    os.makedirs(team_dir, exist_ok=True)

    # 1. Assets copy
    pdf_rel = "/static/uploads/courses/demo_course_syllabus.pdf"
    pdf_dest = os.path.join(courses_dir, "demo_course_syllabus.pdf")
    pdf_src = os.path.join(demo_assets_dir, "sample_syllabus.pdf")
    if os.path.isfile(pdf_src):
        shutil.copy2(pdf_src, pdf_dest)

    cover1_rel = "/static/uploads/courses/demo_cover_1.jpg"
    cover1_dest = os.path.join(courses_dir, "demo_cover_1.jpg")
    cover1_src = os.path.join(demo_assets_dir, "sample_cover_1.jpg")
    if os.path.isfile(cover1_src):
        shutil.copy2(cover1_src, cover1_dest)

    cover2_rel = "/static/uploads/courses/demo_cover_2.jpg"
    cover2_dest = os.path.join(courses_dir, "demo_cover_2.jpg")
    cover2_src = os.path.join(demo_assets_dir, "sample_cover_2.jpg")
    if os.path.isfile(cover2_src):
        shutil.copy2(cover2_src, cover2_dest)

    teacher_rel = "/static/uploads/team/demo_instructor.png"
    teacher_dest = os.path.join(team_dir, "demo_instructor.png")
    teacher_src = os.path.join(demo_assets_dir, "sample_teacher.png")
    if os.path.isfile(teacher_src):
        shutil.copy2(teacher_src, teacher_dest)

    # 2. Courses (4 courses)
    courses_spec = [
        {
            "title": "Full-Stack Web Development Bootcamp",
            "description": "Comprehensive practical training in modern HTML5, CSS3, JavaScript, Python Flask, and RESTful APIs. Build and deploy real-world responsive web applications.",
            "image": cover1_rel,
            "pdf": pdf_rel,
            "teacher": "Engr. Shahzad Ahmed",
            "teacher_role": "Lead Web Instructor",
            "teacher_image": teacher_rel,
            "students": 145,
            "likes": 92,
            "rating": "4.9",
            "order": 1,
        },
        {
            "title": "Python Programming & Data Science",
            "description": "Master Python from foundational syntax to object-oriented programming, data analytics with Pandas & NumPy, and introductory machine learning algorithms.",
            "image": cover2_rel,
            "pdf": pdf_rel,
            "teacher": "Engr. Shahzad Ahmed",
            "teacher_role": "Data Science Specialist",
            "teacher_image": teacher_rel,
            "students": 120,
            "likes": 78,
            "rating": "4.8",
            "order": 2,
        },
        {
            "title": "UI/UX Design & Front-End Engineering",
            "description": "Learn professional user experience design, wireframing, interactive prototyping in Figma, design systems, and converting layouts into polished web components.",
            "image": cover1_rel,
            "pdf": pdf_rel,
            "teacher": "Engr. Shahzad Ahmed",
            "teacher_role": "UI/UX & Creative Director",
            "teacher_image": teacher_rel,
            "students": 98,
            "likes": 65,
            "rating": "5.0",
            "order": 3,
        },
        {
            "title": "Mobile App Development with Flutter & Dart",
            "description": "Build high-performance, cross-platform mobile apps for Android and iOS using Flutter. Master responsive UI, reactive state management, and Firebase APIs.",
            "image": cover2_rel,
            "pdf": pdf_rel,
            "teacher": "Engr. Shahzad Ahmed",
            "teacher_role": "Mobile Solutions Architect",
            "teacher_image": teacher_rel,
            "students": 135,
            "likes": 88,
            "rating": "4.9",
            "order": 4,
        },
    ]
    for spec in courses_spec:
        c = Course.query.filter_by(title=spec["title"]).first()
        if not c:
            c = Course(
                title=spec["title"],
                description=spec["description"],
                image=spec["image"],
                pdf=spec["pdf"],
                teacher=spec["teacher"],
                teacher_role=spec["teacher_role"],
                teacher_image=spec["teacher_image"],
                students=spec["students"],
                likes=spec["likes"],
                rating=spec["rating"],
                order=spec["order"],
                is_active=True,
                show_on_home=True,
            )
            db.session.add(c)
        else:
            c.description = spec["description"]
            c.image = spec["image"]
            c.pdf = spec["pdf"]
            c.teacher = spec["teacher"]
            c.teacher_role = spec["teacher_role"]
            c.teacher_image = spec["teacher_image"]
            c.order = spec["order"]
            c.is_active = True
            c.show_on_home = True

    # 3. Upcoming Courses (2 items)
    upcoming_spec = [
        {
            "title": "Full-Stack Web Development — Weekend Batch",
            "description": "Special weekend batch designed for working professionals and university students. Hands-on coding sessions every Saturday and Sunday.",
            "image": cover1_rel,
            "batch_name": "Batch 09 (Weekend)",
            "start_date": "01 Dec 2026",
            "last_apply_date": "25 Nov 2026",
            "form_link": "/contact.html",
            "duration": "12 Weeks (Saturdays & Sundays)",
            "fee": "Rs. 15,000",
            "seats": "25 Seats Only",
            "instructor": "Engr. Shahzad Ahmed",
            "order": 1,
        },
        {
            "title": "Python Programming & AI Intensive",
            "description": "Evening crash course focusing on data analysis, machine learning foundations, and automated script development.",
            "image": cover2_rel,
            "batch_name": "Batch 04 (Evening)",
            "start_date": "15 Dec 2026",
            "last_apply_date": "08 Dec 2026",
            "form_link": "/contact.html",
            "duration": "8 Weeks (Mon - Thu)",
            "fee": "Rs. 12,000",
            "seats": "30 Seats Only",
            "instructor": "Engr. Shahzad Ahmed",
            "order": 2,
        },
    ]
    for spec in upcoming_spec:
        uc = UpcomingCourse.query.filter_by(title=spec["title"]).first()
        if not uc:
            uc = UpcomingCourse(
                title=spec["title"],
                description=spec["description"],
                image=spec["image"],
                batch_name=spec["batch_name"],
                start_date=spec["start_date"],
                last_apply_date=spec["last_apply_date"],
                form_link=spec["form_link"],
                duration=spec["duration"],
                fee=spec["fee"],
                seats=spec["seats"],
                instructor=spec["instructor"],
                order=spec["order"],
                is_active=True,
            )
            db.session.add(uc)
        else:
            uc.description = spec["description"]
            uc.image = spec["image"]
            uc.batch_name = spec["batch_name"]
            uc.start_date = spec["start_date"]
            uc.last_apply_date = spec["last_apply_date"]
            uc.form_link = spec["form_link"]
            uc.duration = spec["duration"]
            uc.fee = spec["fee"]
            uc.seats = spec["seats"]
            uc.instructor = spec["instructor"]
            uc.order = spec["order"]
            uc.is_active = True

    # 4. News / Announcements (4 items)
    news_spec = [
        {
            "title": "Admissions Open for New Professional Technical Batches",
            "content": "AIMS Sukkur announces admissions for upcoming professional diploma and certification batches in Full-Stack Web Development, Python Data Science, and UI/UX Architecture. Early registration is encouraged to reserve your seat.",
            "image": cover1_rel,
            "date": "10 Nov 2026",
            "order": 1,
        },
        {
            "title": "Annual Technology Innovation Showcase & Project Expo",
            "content": "Students presented capstone projects, cross-platform mobile apps, and enterprise web solutions to visiting tech executives and industry alumni during our annual innovation showcase.",
            "image": cover2_rel,
            "date": "04 Nov 2026",
            "order": 2,
        },
        {
            "title": "Specialized Workshop on Cloud Computing & REST APIs",
            "content": "A full-day intensive masterclass led by guest software architects covering microservices architecture, serverless deployments, and cloud scalability attended by over 120 students.",
            "image": cover1_rel,
            "date": "28 Oct 2026",
            "order": 3,
        },
        {
            "title": "Merit-Based Scholarship Award Ceremony Fall 2026",
            "content": "AIMS Sukkur recognized academic excellence and rewarded tuition fee scholarships to top-performing students across IT and management programs for outstanding semester performance.",
            "image": cover2_rel,
            "date": "18 Oct 2026",
            "order": 4,
        },
    ]
    for spec in news_spec:
        n = News.query.filter_by(title=spec["title"]).first()
        if not n:
            n = News(
                title=spec["title"],
                content=spec["content"],
                image=spec["image"],
                date=spec["date"],
                order=spec["order"],
                is_active=True,
                show_on_home=True,
            )
            db.session.add(n)
        else:
            n.content = spec["content"]
            n.image = spec["image"]
            n.date = spec["date"]
            n.order = spec["order"]
            n.is_active = True
            n.show_on_home = True

    # 5. E-Library / Books (4 items with PDF attached)
    books_spec = [
        {
            "title": "Modern Web Development Fundamentals",
            "author": "Engr. Shahzad Ahmed",
            "pages": "248 pages",
            "image": cover1_rel,
            "pdf": pdf_rel,
            "badge": "Available",
            "description": "Comprehensive reference guide covering modern HTML5, CSS3, JavaScript, Python Flask, and backend RESTful architectures.",
            "order": 1,
        },
        {
            "title": "Python for Data Science & Automation",
            "author": "AIMS Academic Press",
            "pages": "312 pages",
            "image": cover2_rel,
            "pdf": pdf_rel,
            "badge": "Available",
            "description": "Practical exercises and code walkthroughs for data analysis, Pandas, NumPy, and automation scripts.",
            "order": 2,
        },
        {
            "title": "User Experience Design & Prototyping",
            "author": "Creative Design Lab",
            "pages": "196 pages",
            "image": cover1_rel,
            "pdf": pdf_rel,
            "badge": "Featured",
            "description": "Essential principles of UI typography, color theory, accessibility standards, and responsive layout hierarchy.",
            "order": 3,
        },
        {
            "title": "Cross-Platform Mobile Development",
            "author": "Engr. Furqan Ali",
            "pages": "260 pages",
            "image": cover2_rel,
            "pdf": pdf_rel,
            "badge": "Available",
            "description": "Step-by-step guide to developing, debugging, and deploying native-speed apps with Flutter and Dart.",
            "order": 4,
        },
    ]
    for spec in books_spec:
        b = Book.query.filter_by(title=spec["title"]).first()
        if not b:
            b = Book(
                title=spec["title"],
                author=spec["author"],
                pages=spec["pages"],
                image=spec["image"],
                pdf=spec["pdf"],
                badge=spec["badge"],
                description=spec["description"],
                order=spec["order"],
                is_active=True,
                show_on_home=True,
            )
            db.session.add(b)
        else:
            b.author = spec["author"]
            b.pages = spec["pages"]
            b.image = spec["image"]
            b.pdf = spec["pdf"]
            b.badge = spec["badge"]
            b.description = spec["description"]
            b.order = spec["order"]
            b.is_active = True
            b.show_on_home = True

    # 6. Events (4 items)
    events_spec = [
        {
            "title": "AIMS Annual Tech Symposium & Hackathon 2026",
            "content": "Join our 24-hour coding sprint where student teams build innovative software solutions addressing local community and educational challenges.",
            "image": cover1_rel,
            "date": "28 Nov 2026",
            "time": "09:00 AM - 05:00 PM",
            "location": "Main Auditorium & Computing Lab, AIMS Sukkur",
            "form_link": "/contact.html",
            "order": 1,
        },
        {
            "title": "Career Mentorship & Tech Industry Panel",
            "content": "Panel discussion with software architects, startup founders, and hiring managers providing actionable advice on portfolio building and technical interviews.",
            "image": cover2_rel,
            "date": "05 Dec 2026",
            "time": "02:00 PM - 04:30 PM",
            "location": "Conference Hall B, AIMS Sukkur",
            "form_link": "/contact.html",
            "order": 2,
        },
        {
            "title": "Open House & Campus Orientation Day",
            "content": "Prospective students and parents are invited to explore our campus facilities, meet the faculty, and discover scholarship options for new batches.",
            "image": cover1_rel,
            "date": "12 Dec 2026",
            "time": "10:00 AM - 02:00 PM",
            "location": "Executive Seminar Room, AIMS Sukkur",
            "form_link": "/contact.html",
            "order": 3,
        },
        {
            "title": "Digital Literacy & Community Outreach Workshop",
            "content": "Free community workshop providing fundamental digital skills, internet safety, and introduction to computing for high school students.",
            "image": cover2_rel,
            "date": "20 Dec 2026",
            "time": "11:00 AM - 01:00 PM",
            "location": "Lab 02, AIMS Sukkur",
            "form_link": "/contact.html",
            "order": 4,
        },
    ]
    for spec in events_spec:
        ev = Event.query.filter_by(title=spec["title"]).first()
        if not ev:
            ev = Event(
                title=spec["title"],
                content=spec["content"],
                image=spec["image"],
                date=spec["date"],
                time=spec["time"],
                location=spec["location"],
                form_link=spec["form_link"],
                order=spec["order"],
                is_active=True,
                show_on_home=True,
            )
            db.session.add(ev)
        else:
            ev.content = spec["content"]
            ev.image = spec["image"]
            ev.date = spec["date"]
            ev.time = spec["time"]
            ev.location = spec["location"]
            ev.form_link = spec["form_link"]
            ev.order = spec["order"]
            ev.is_active = True
            ev.show_on_home = True

    # 7. Learning Videos (8 items with real playable YouTube IDs)
    videos_spec = [
        ("Introduction to Computer Science & Programming", "https://www.youtube.com/watch?v=zOjov-2OZ0E", "zOjov-2OZ0E", "Computer Science", "Dr. David J. Malan", "28:40", "Learn the foundational concepts of computer science, algorithms, memory, and how software systems work from the ground up.", 0),
        ("Python for Beginners: Full Crash Course", "https://www.youtube.com/watch?v=kqtD5dpn9C8", "kqtD5dpn9C8", "Programming", "Engr. Mosh Hamedani", "45:15", "Master the basics of Python programming, data types, conditional statements, loops, and building real-world automation scripts.", 1),
        ("Web Development Full Roadmap: HTML, CSS & JavaScript", "https://www.youtube.com/watch?v=mU6anWqZJcc", "mU6anWqZJcc", "Web Development", "Brad Traversy", "32:10", "A comprehensive walkthrough covering front-end architecture, responsive design principles, and modern JavaScript techniques.", 2),
        ("Mathematics for Machine Learning: Linear Algebra & Matrices", "https://www.youtube.com/watch?v=fNk_zzaMoSs", "fNk_zzaMoSs", "Mathematics", "Grant Sanderson", "22:50", "Visualize vectors, matrices, linear transformations, and geometric intuition behind modern machine learning mathematics.", 3),
        ("Data Structures & Algorithms: Fundamentals Explained", "https://www.youtube.com/watch?v=RBSGKlAnoiM", "RBSGKlAnoiM", "Computer Science", "Prof. John Doe", "35:20", "Understanding Big-O notation, arrays, linked lists, stacks, queues, and tree traversal algorithms with practical examples.", 4),
        ("English Communication & Public Speaking for Professionals", "https://www.youtube.com/watch?v=7Tvy4n86qY0", "7Tvy4n86qY0", "Communication", "Dr. Sarah Jenkins", "19:45", "Practical strategies to articulate ideas clearly, overcome stage fright, and deliver compelling presentations in academic and professional settings.", 5),
        ("Graphic Design Essentials & UI Principles", "https://www.youtube.com/watch?v=YqQx75OPWV4", "YqQx75OPWV4", "Design", "Gareth David", "24:15", "Explore visual balance, typography, color theory, grid systems, and layout hierarchies for impactful digital design.", 6),
        ("Database Systems & SQL: From Queries to Optimization", "https://www.youtube.com/watch?v=HXV3zeRR3h4", "HXV3zeRR3h4", "Databases", "Alex The Analyst", "27:30", "Learn relational database design, writing complex SQL queries, JOIN operations, indexing, and optimizing query performance.", 7),
    ]
    for title, yurl, vid, cat, inst, dur, desc, ordr in videos_spec:
        v = LearningVideo.query.filter_by(title=title).first()
        if not v:
            v = LearningVideo(
                title=title,
                youtube_url=yurl,
                video_id=vid,
                category=cat,
                instructor=inst,
                duration=dur,
                description=desc,
                order=ordr,
                is_active=True,
                show_on_home=True,
            )
            db.session.add(v)
        else:
            v.youtube_url = yurl
            v.video_id = vid
            v.category = cat
            v.instructor = inst
            v.duration = dur
            v.description = desc
            v.order = ordr
            v.is_active = True
            v.show_on_home = True

    # 8. Vision, Mission, Values & About Blocks
    about_spec = [
        ("hero_title", "Excellence in Modern Education", "Academy of Innovative Management Sciences — Empowering minds through practical skills, modern technology, and leadership in Sukkur.", None, teacher_rel, 0),
        ("hero_text", None, "We prepare ambitious students with hands-on technical skills, strong ethical values, and industry-aligned competencies. Our mission-driven campus fosters critical thinking, technological mastery, and continuous professional growth.", None, None, 1),
        ("mission", "Our Mission", "To deliver accessible, world-class education that develops technically skilled, ethically grounded, and innovative graduates ready to excel in the global marketplace.", "zmdi-flag", None, 2),
        ("vision", "Our Vision", "To be recognized as a premier institute of technical and management excellence, driving regional transformation through innovation and academic leadership.", "zmdi-eye", None, 3),
        ("values", "Our Core Values", "Integrity, academic excellence, innovation, inclusivity, and student empowerment guide every curriculum and mentorship program we deliver.", "zmdi-favorite", None, 4),
    ]
    for key, title, content, icon, image, order in about_spec:
        ab = AboutBlock.query.filter_by(key=key).first()
        if not ab:
            ab = AboutBlock(
                key=key,
                title=title,
                content=content,
                icon=icon,
                image=image,
                order=order,
                is_active=True,
            )
            db.session.add(ab)
        else:
            if title is not None:
                ab.title = title
            if content is not None:
                ab.content = content
            if icon is not None:
                ab.icon = icon
            if image is not None:
                ab.image = image
            ab.order = order
            ab.is_active = True

    # 9. Why Choose Us (4 pillars)
    why_spec = [
        ("Industry-Experienced Faculty", "Learn directly from seasoned software engineers, researchers, and subject-matter experts dedicated to student mentorship.", "zmdi-accounts", 1),
        ("Modern Hands-On Curriculum", "Every course is designed around real-world projects, modern coding standards, and current enterprise demands.", "zmdi-library", 2),
        ("Practical Lab Facilities", "High-speed networked computer labs equipped with modern development tools, high-speed internet, and testing devices.", "zmdi-desktop-windows", 3),
        ("Career Support & Placement", "Dedicated internship assistance, resume workshops, and industry networking sessions to launch student careers.", "zmdi-globe-alt", 4),
    ]
    for title, content, icon, order in why_spec:
        wc = WhyChoose.query.filter_by(title=title).first()
        if not wc:
            wc = WhyChoose(title=title, content=content, icon=icon, order=order, is_active=True)
            db.session.add(wc)
        else:
            wc.content = content
            wc.icon = icon
            wc.order = order
            wc.is_active = True

    # 10. Teachers / Faculty (3 members using provided character image)
    teachers_spec = [
        {
            "name": "Engr. Shahzad Ahmed",
            "role": "Lead Technical Instructor & Full-Stack Specialist",
            "qualification": "BS Software Engineering & System Architecture",
            "description": "Passionate technical educator with 8+ years of industry experience architecting scalable web, cloud, and mobile solutions.",
            "email": "shahzad@aimssukkur.edu.pk",
            "linkedin": "https://linkedin.com",
            "image": teacher_rel,
            "order": 1,
        },
        {
            "name": "Engr. Asadullah Shaikh",
            "role": "Head of Computing & Data Sciences",
            "qualification": "MS Computer Science (Data Mining & AI)",
            "description": "Researcher and instructor specializing in algorithms, data structures, Python analytics, and educational technologies.",
            "email": "asad@aimssukkur.edu.pk",
            "linkedin": "https://linkedin.com",
            "image": teacher_rel,
            "order": 2,
        },
        {
            "name": "Engr. Furqan Ali",
            "role": "Senior Mobile Solutions Architect",
            "qualification": "BS Computer Systems & Mobile Application Engineering",
            "description": "Expert mobile app developer with specialized experience in Flutter, Dart, RESTful microservices, and cross-platform UI.",
            "email": "furqan@aimssukkur.edu.pk",
            "linkedin": "https://linkedin.com",
            "image": teacher_rel,
            "order": 3,
        },
    ]
    for spec in teachers_spec:
        tm = TeamMember.query.filter_by(name=spec["name"]).first()
        if not tm:
            tm = TeamMember(
                name=spec["name"],
                role=spec["role"],
                qualification=spec["qualification"],
                description=spec["description"],
                email=spec["email"],
                linkedin=spec["linkedin"],
                image=spec["image"],
                order=spec["order"],
                is_active=True,
            )
            db.session.add(tm)
        else:
            tm.role = spec["role"]
            tm.qualification = spec["qualification"]
            tm.description = spec["description"]
            tm.email = spec["email"]
            tm.linkedin = spec["linkedin"]
            tm.image = spec["image"]
            tm.order = spec["order"]
            tm.is_active = True

    # 11. Fun Factors (4 counters)
    ff_spec = [
        ("85+", "Certified Teachers", 1),
        ("1,200+", "Enrolled Students", 2),
        ("24+", "Active Programs", 3),
        ("98%", "Career Placement", 4),
    ]
    for num, label, order in ff_spec:
        ff = FunFactor.query.filter_by(label=label).first()
        if not ff:
            ff = FunFactor(number=num, label=label, order=order)
            db.session.add(ff)
        else:
            ff.number = num
            ff.order = order

    # 12. Testimonials (3 reviews)
    test_spec = [
        ("Ali Raza", "The Full-Stack Web Bootcamp at AIMS gave me the practical skills I needed to land my first developer job within two months of completion.", 1),
        ("Khadija Noor", "Exceptional faculty and hands-on lab sessions. Learning Python and Data Science here was structured, practical, and highly rewarding.", 2),
        ("Bilal Tariq", "High-quality curriculum, modern facilities, and great instructor mentorship. I highly recommend AIMS Sukkur to aspiring engineers.", 3),
    ]
    for author, content, order in test_spec:
        t = Testimonial.query.filter_by(author=author).first()
        if not t:
            t = Testimonial(author=author, content=content, image=teacher_rel, order=order, is_active=True)
            db.session.add(t)
        else:
            t.content = content
            t.image = teacher_rel
            t.order = order
            t.is_active = True

    # 13. Sliders for Index Page
    slider_spec = [
        (cover1_rel, "Empowering Your Future with Quality Education", "Explore career-driven technical programs and hands-on computing courses designed for modern industry success.", "Explore Courses", "course.html", 1),
        (cover2_rel, "Learn Modern Technology & Innovation at AIMS", "Join our comprehensive diplomas in Web Development, Python, and Mobile Apps with expert mentorship.", "Admissions Desk", "contact.html", 2),
    ]
    for img, title, subtitle, btn_txt, btn_lnk, order in slider_spec:
        sl = SliderImage.query.filter_by(title=title, page_slug="index").first()
        if not sl:
            sl = SliderImage(
                page_slug="index",
                image=img,
                title=title,
                subtitle=subtitle,
                button_text=btn_txt,
                button_link=btn_lnk,
                order=order,
                is_active=True,
            )
            db.session.add(sl)
        else:
            sl.image = img
            sl.subtitle = subtitle
            sl.button_text = btn_txt
            sl.button_link = btn_lnk
            sl.order = order
            sl.is_active = True

    # 14. Homepage Hero Settings
    home_settings = {
        "home_about_img": teacher_rel,
        "home_about_badge": "EXCELLENCE IN EDUCATION",
        "home_about_title": "Building Futures Through Quality Education & Innovation",
        "home_about_text": "Join AIMS Sukkur — a premier technical institute where modern curriculum meets hands-on software development. Discover programs designed for tomorrow's technology challenges.",
        "home_about_stat1_num": "1,200+",
        "home_about_stat1_lbl": "Enrolled Students",
        "home_about_stat2_num": "85+",
        "home_about_stat2_lbl": "Certified Faculty",
        "home_about_stat3_num": "24+",
        "home_about_stat3_lbl": "Active Courses",
    }
    for k, v in home_settings.items():
        st = SiteSetting.query.filter_by(key=k).first()
        if not st:
            st = SiteSetting(key=k, value=v)
            db.session.add(st)
        else:
            st.value = v

    db.session.commit()
    try:
        from ..services.cache import invalidate
        invalidate()
    except Exception:
        pass


@bp.route("/admin/settings", methods=["GET", "POST"])
@login_required
def admin_settings():
    """Admin Settings: Change password, generate demo data, and database reset maintenance."""
    admin = db.session.get(Admin, session.get("admin_id"))
    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "change_password":
            current_pass = request.form.get("current_password", "").strip()
            new_pass = request.form.get("new_password", "").strip()
            confirm_pass = request.form.get("confirm_password", "").strip()

            if not admin or not admin.check_password(current_pass):
                flash("Current password is incorrect.", "error")
                return redirect(url_for("admin.admin_settings"))

            if new_pass != confirm_pass:
                flash("New passwords do not match.", "error")
                return redirect(url_for("admin.admin_settings"))

            prob = password_problem(new_pass, admin.username)
            if prob:
                flash(prob, "error")
                return redirect(url_for("admin.admin_settings"))

            admin.set_password(new_pass)
            db.session.commit()
            session["pv"] = password_stamp(admin)
            flash("Your password has been changed successfully.", "success")
            return redirect(url_for("admin.admin_settings"))

        elif action == "remove_db":
            do_database_wipe(purge_files=False)
            refreshed_admin = Admin.query.filter_by(username="admin").first()
            if refreshed_admin:
                session["admin_id"] = refreshed_admin.id
                session["admin_username"] = refreshed_admin.username
                session["pv"] = password_stamp(refreshed_admin)
            flash("Database records cleared successfully! Uploaded files were preserved. Default credentials: admin / AimsSukkur2026", "success")
            return redirect(url_for("admin.admin_settings"))

        elif action == "reset_all":
            do_database_wipe(purge_files=True)
            session.clear()
            flash("All database records and uploaded files have been completely reset! Please log in using username: admin and password: AimsSukkur2026", "warning")
            return redirect(url_for("admin.admin_login"))

        elif action == "create_demo_data":
            do_create_demo_data()
            flash("Demo data created successfully with 4 sample courses, syllabus PDFs, cover posters, and instructor profile.", "success")
            return redirect(url_for("admin.admin_settings"))

    return render_template("admin/settings.html", admin=admin)


# ----------------------------------------------------- page editor (overlays)
SLIDERS = Crud(
    SliderImage, "Slider image",
    fields=[Field("title", default="Education Needs Complete Solution", keep_if_blank=True),
            Field("subtitle"),
            Field("button_text", default="View Courses", keep_if_blank=True),
            Field("button_link", "link", default="course.html", keep_if_blank=True),
            Field("order", "int"),
            Field("pos_desktop", "pos", default="center center", keep_if_blank=True),
            Field("pos_mobile", "pos", default="center center", keep_if_blank=True)],
    files=[FileField("image", "image_path", "image", "image", "sliders")],
    required_files=("image",),
    msgs={"add": "Slider image added.", "edit": "Slider updated.", "delete": "Slider deleted.",
          "toggle": "Slider status updated."},
    order_by=lambda m: (m.order,),
)

PAGE_FUN = Crud(
    FunFactor, "Fun factor",
    fields=[Field("number", default="0"), Field("label"), Field("order", "int")],
    allow=("add", "edit", "delete"),
    msgs={"edit": "Fun factor updated.", "delete": "Fun factor deleted."},
)

PAGE_TESTIMONIALS = Crud(
    Testimonial, "Testimonial",
    fields=[Field("author", required=True), Field("content", required=True), Field("order", "int")],
    files=[FileField("image", "image_path", "image", "image", "testimonials")],
    msgs={"delete": "Testimonial deleted.", "toggle": "Testimonial status updated."},
    order_by=lambda m: (m.order,),
)

_GROUPS = [
    # (crud, {form action -> crud action}, redirect anchor)
    (SLIDERS, {"add_slider": "add", "update_slider": "edit", "delete_slider": "delete",
               "toggle_slider": "toggle"}, "#overlay-slider"),
    (PAGE_FUN, {"add_fun": "add", "update_fun": "edit", "delete_fun": "delete"}, "#overlay-fun"),
    (PAGE_TESTIMONIALS, {"add_testimonial": "add", "update_testimonial": "edit",
                         "delete_testimonial": "delete", "toggle_testimonial": "toggle"}, "#overlay-testimonial"),
]


# ------------------------------------------------------------- Homepage Management
HOME_ABOUT_KEYS = [
    "home_about_badge",
    "home_about_title",
    "home_about_text",
    "home_about_btn_text",
    "home_about_btn_link",
    "home_about_stat1_num",
    "home_about_stat1_lbl",
    "home_about_stat2_num",
    "home_about_stat2_lbl",
    "home_about_stat3_num",
    "home_about_stat3_lbl",
    "home_about_img",
    "home_about_bg",
]


@bp.route("/admin/homepage", methods=["GET", "POST"])
@login_required
def admin_homepage():
    """Customizes homepage sections: About Hero (image & content), Fun Factors, and Testimonials."""
    if request.method == "POST":
        action = request.form.get("action", "")

        # 1. Save About Hero Section
        if action == "save_about_hero":
            existing = {r.key: r for r in SiteSetting.query.all()}
            for key in HOME_ABOUT_KEYS:
                if key in ("home_about_img", "home_about_bg"):
                    continue
                val = form_str(request.form, key)[:2000]
                row = existing.get(key)
                if not row:
                    row = SiteSetting(key=key)
                    db.session.add(row)
                row.value = val

            # Check hero_image upload (student / front image)
            uploaded_img = request.files.get("hero_image")
            img_path, err = save_upload(uploaded_img, "about", kind="image")
            if err:
                flash(err, "error")
            elif img_path:
                row = existing.get("home_about_img") or SiteSetting(key="home_about_img")
                row.value = img_path
                db.session.add(row)
            elif request.form.get("hero_image_path"):
                clean_img = clean_path_input(request.form.get("hero_image_path"))
                if clean_img:
                    row = existing.get("home_about_img") or SiteSetting(key="home_about_img")
                    row.value = clean_img
                    db.session.add(row)

            # Check hero_bg upload (background banner)
            uploaded_bg = request.files.get("hero_bg")
            bg_path, err_bg = save_upload(uploaded_bg, "banner", kind="image")
            if err_bg:
                flash(err_bg, "error")
            elif bg_path:
                row = existing.get("home_about_bg") or SiteSetting(key="home_about_bg")
                row.value = bg_path
                db.session.add(row)
            elif request.form.get("hero_bg_path"):
                clean_bg = clean_path_input(request.form.get("hero_bg_path"))
                if clean_bg:
                    row = existing.get("home_about_bg") or SiteSetting(key="home_about_bg")
                    row.value = clean_bg
                    db.session.add(row)

            db.session.commit()
            try:
                from ..services.cache import invalidate
                invalidate()
            except Exception:
                pass
            flash("About Hero section saved successfully.", "success")
            return redirect(url_for("admin.admin_homepage", _anchor="about-hero"))

        # 2. Fun Factor Actions
        elif action == "add_fun":
            num = form_str(request.form, "number")
            lbl = form_str(request.form, "label")
            ord_val = to_int(request.form.get("order", 0))
            if not num or not lbl:
                flash("Number and label are required for Fun Factor.", "error")
            else:
                ff = FunFactor(number=num, label=lbl, order=ord_val)
                db.session.add(ff)
                db.session.commit()
                flash("Fun factor counter added successfully.", "success")
            return redirect(url_for("admin.admin_homepage", _anchor="fun-factors"))

        elif action == "edit_fun":
            fid = to_int(request.form.get("id"))
            ff = db.session.get(FunFactor, fid) if fid else None
            if ff:
                ff.number = form_str(request.form, "number") or ff.number
                ff.label = form_str(request.form, "label") or ff.label
                ff.order = to_int(request.form.get("order", ff.order))
                db.session.commit()
                flash("Fun factor counter updated.", "success")
            else:
                flash("Fun factor not found.", "error")
            return redirect(url_for("admin.admin_homepage", _anchor="fun-factors"))

        elif action == "delete_fun":
            fid = to_int(request.form.get("id"))
            ff = db.session.get(FunFactor, fid) if fid else None
            if ff:
                db.session.delete(ff)
                db.session.commit()
                flash("Fun factor counter deleted.", "success")
            return redirect(url_for("admin.admin_homepage", _anchor="fun-factors"))

        # 3. Testimonial Actions
        elif action == "add_testimonial":
            author = form_str(request.form, "author")
            content = form_str(request.form, "content")
            ord_val = to_int(request.form.get("order", 0))
            if not author or not content:
                flash("Author name and feedback are required.", "error")
            else:
                t_img, _ = save_upload(request.files.get("image"), "testimonials", kind="image")
                if not t_img and request.form.get("image_path"):
                    t_img = clean_path_input(request.form.get("image_path"))
                item = Testimonial(author=author, content=content, image=t_img, order=ord_val, is_active=True)
                db.session.add(item)
                db.session.commit()
                flash("Testimonial added successfully.", "success")
            return redirect(url_for("admin.admin_homepage", _anchor="testimonials"))

        elif action == "edit_testimonial":
            tid = to_int(request.form.get("id"))
            t = db.session.get(Testimonial, tid) if tid else None
            if t:
                t.author = form_str(request.form, "author") or t.author
                t.content = form_str(request.form, "content") or t.content
                t.order = to_int(request.form.get("order", t.order))
                uploaded_t_img, _ = save_upload(request.files.get("image"), "testimonials", kind="image")
                if uploaded_t_img:
                    t.image = uploaded_t_img
                elif request.form.get("image_path"):
                    clean_t_img = clean_path_input(request.form.get("image_path"))
                    if clean_t_img:
                        t.image = clean_t_img
                db.session.commit()
                flash("Testimonial updated.", "success")
            return redirect(url_for("admin.admin_homepage", _anchor="testimonials"))

        elif action == "toggle_testimonial":
            tid = to_int(request.form.get("id"))
            t = db.session.get(Testimonial, tid) if tid else None
            if t:
                t.is_active = not t.is_active
                db.session.commit()
                flash(f"Testimonial is now {'visible' if t.is_active else 'hidden'}.", "success")
            return redirect(url_for("admin.admin_homepage", _anchor="testimonials"))

        elif action == "delete_testimonial":
            tid = to_int(request.form.get("id"))
            t = db.session.get(Testimonial, tid) if tid else None
            if t:
                db.session.delete(t)
                db.session.commit()
                flash("Testimonial deleted.", "success")
            return redirect(url_for("admin.admin_homepage", _anchor="testimonials"))

        return redirect(url_for("admin.admin_homepage"))

    from ..services.cache import get_settings
    settings_dict = get_settings()
    fun_factors = FunFactor.query.order_by(FunFactor.order).all()
    testimonials = Testimonial.query.order_by(Testimonial.order).all()

    return render_template(
        "admin/homepage.html",
        settings=settings_dict,
        fun_factors=fun_factors,
        testimonials=testimonials,
    )


# ------------------------------------------------------------- Header Management
HEADER_SETTING_KEYS = [
    "header_top_enabled",
    "header_top_question",
    "header_top_phone",
    "header_top_email",
    "site_name",
]

@bp.route("/admin/header", methods=["GET", "POST"])
@login_required
def admin_header():
    """Customizes header details: Top bar notification, contact info, and header logo."""
    if request.method == "POST":
        existing = {r.key: r for r in SiteSetting.query.all()}
        for key in HEADER_SETTING_KEYS:
            if key == "header_top_enabled":
                val = "1" if request.form.get("header_top_enabled") else "0"
            else:
                val = form_str(request.form, key)[:2000]
            row = existing.get(key)
            if not row:
                row = SiteSetting(key=key)
                db.session.add(row)
            row.value = val

        # Handle Header Logo Upload
        uploaded_logo = request.files.get("header_logo")
        logo_path, err = save_upload(uploaded_logo, "site", kind="image")
        if err:
            flash(err, "error")
        elif logo_path:
            row = existing.get("header_logo") or SiteSetting(key="header_logo")
            row.value = logo_path
            db.session.add(row)
        elif request.form.get("header_logo_path"):
            clean_logo = clean_path_input(request.form.get("header_logo_path"))
            if clean_logo:
                row = existing.get("header_logo") or SiteSetting(key="header_logo")
                row.value = clean_logo
                db.session.add(row)

        db.session.commit()
        try:
            from ..services.cache import invalidate
            invalidate()
        except Exception:
            pass

        flash("Header details saved successfully.", "success")
        return redirect(url_for("admin.admin_header"))

    from ..services.cache import get_settings
    settings_dict = get_settings()
    return render_template("admin/header.html", settings=settings_dict)


# ------------------------------------------------------------- Footer Management
FOOTER_SETTING_KEYS = [
    "footer_about",
    "phone",
    "email",
    "address",
    "working_hours",
    "facebook",
    "twitter",
    "instagram",
    "youtube",
    "linkedin",
    "copyright_text",
    "privacy_url",
    "terms_url",
]
_FOOTER_URL_KEYS = {"facebook", "twitter", "instagram", "youtube", "linkedin", "privacy_url", "terms_url"}

@bp.route("/admin/footer", methods=["GET", "POST"])
@login_required
def admin_footer():
    """Customizes footer details: Brand about text, contact info, social links, bottom bar copyright."""
    if request.method == "POST":
        existing = {r.key: r for r in SiteSetting.query.all()}
        for key in FOOTER_SETTING_KEYS:
            val = form_str(request.form, key)[:2000]
            if key in _FOOTER_URL_KEYS and val and val != "#":
                val = safe_url(val)
            row = existing.get(key)
            if not row:
                row = SiteSetting(key=key)
                db.session.add(row)
            row.value = val

        # Handle Footer Logo Upload
        uploaded_logo = request.files.get("footer_logo")
        logo_path, err = save_upload(uploaded_logo, "site", kind="image")
        if err:
            flash(err, "error")
        elif logo_path:
            row = existing.get("footer_logo") or SiteSetting(key="footer_logo")
            row.value = logo_path
            db.session.add(row)
        elif request.form.get("footer_logo_path"):
            clean_logo = clean_path_input(request.form.get("footer_logo_path"))
            if clean_logo:
                row = existing.get("footer_logo") or SiteSetting(key="footer_logo")
                row.value = clean_logo
                db.session.add(row)

        db.session.commit()
        try:
            from ..services.cache import invalidate
            invalidate()
        except Exception:
            pass

        flash("Footer details saved successfully.", "success")
        return redirect(url_for("admin.admin_footer"))

    from ..services.cache import get_settings
    settings_dict = get_settings()
    return render_template("admin/footer.html", settings=settings_dict)


@bp.route("/admin/pages")
@login_required
def admin_pages():
    return redirect(url_for("admin.admin_dashboard"))


@bp.route("/admin/pages/<slug>", methods=["GET", "POST"])
@login_required
def admin_edit_page(slug):
    page = Page.query.filter_by(slug=slug).first_or_404()

    if request.method == "POST":
        action = request.form.get("action", "")
        for crud, action_map, anchor in _GROUPS:
            if action in action_map:
                extra = {"page_slug": slug} if crud is SLIDERS and action_map[action] == "add" else {}
                crud.dispatch(request.form, request.files, action_map=action_map, **extra)
                return redirect(url_for("admin.admin_edit_page", slug=slug) + anchor)
        return redirect(url_for("admin.admin_edit_page", slug=slug))

    return render_template(
        "admin/edit_page.html",
        page=page,
        sliders=SliderImage.query.filter_by(page_slug=slug).order_by(SliderImage.order).all(),
        fun_factors=FunFactor.query.order_by(FunFactor.order).all(),
        testimonials=Testimonial.query.order_by(Testimonial.order).all(),
    )


# ------------------------------------------------------------- PDF Documents (Removed / Deprecated)
@bp.route("/admin/pdf-check", methods=["GET", "POST"])
@bp.route("/admin/pdf-documents", methods=["GET", "POST"])
@login_required
def admin_pdf_check():
    return redirect(url_for("admin.admin_dashboard"))
