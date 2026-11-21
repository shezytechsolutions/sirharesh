"""Public (visitor) pages. URLs are identical to the previous version."""
import re

from flask import (Response, flash, redirect, render_template, request, url_for)

from ..extensions import db
from ..models import (Book, ContactMessage, Course, Event, FunFactor, LearningVideo, News,
                      SliderImage, TeamMember, Testimonial, UpcomingCourse, WhyChoose, AboutBlock)
from ..security import client_ip, contact_by_ip, is_xhr
from ..utils import form_str
from . import bp
from .pdf import pdf_urls

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _active(model, *order, limit=None, **flt):
    q = model.query.filter_by(is_active=True, **flt).order_by(*order)
    return q.limit(limit).all() if limit else q.all()


def _by_order(model):
    return (model.order, model.created_at.desc())


@bp.route("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /admin\n", mimetype="text/plain")


@bp.route("/")
def index():
    return render_template(
        "index.html",
        fun_factors=FunFactor.query.order_by(FunFactor.order).all(),
        testimonials=_active(Testimonial, Testimonial.order),
        sliders=SliderImage.query.filter_by(page_slug="index", is_active=True).order_by(SliderImage.order).all(),
        home_news=_active(News, *_by_order(News), limit=4, show_on_home=True),
        home_courses=_active(Course, *_by_order(Course), limit=4, show_on_home=True),
        home_events=_active(Event, *_by_order(Event), limit=4, show_on_home=True),
        home_books=_active(Book, *_by_order(Book), limit=4, show_on_home=True),
        home_videos=_active(LearningVideo, *_by_order(LearningVideo), limit=8, show_on_home=True),
    )


@bp.route("/about")
@bp.route("/about.html")
def about():
    return render_template(
        "about.html",
        fun_factors=FunFactor.query.order_by(FunFactor.order).all(),
        testimonials=_active(Testimonial, Testimonial.order),
        why_choose=_active(WhyChoose, WhyChoose.order),
        team_members=_active(TeamMember, TeamMember.order),
        blocks={b.key: b for b in AboutBlock.query.filter_by(is_active=True).all()},
    )


@bp.route("/course.html")
@bp.route("/courses")
def courses():
    q = request.args.get("q", "").strip()
    if q:
        pattern = f"%{q}%"
        course_list = Course.query.filter(
            Course.is_active.is_(True),
            (Course.title.ilike(pattern) | Course.description.ilike(pattern) | Course.teacher.ilike(pattern))
        ).order_by(Course.order, Course.created_at.desc()).all()
        upcoming_list = UpcomingCourse.query.filter(
            UpcomingCourse.is_active.is_(True),
            (UpcomingCourse.title.ilike(pattern) | UpcomingCourse.description.ilike(pattern) | UpcomingCourse.batch_name.ilike(pattern))
        ).order_by(UpcomingCourse.order, UpcomingCourse.created_at.desc()).all()
    else:
        course_list = _active(Course, *_by_order(Course))
        upcoming_list = _active(UpcomingCourse, *_by_order(UpcomingCourse))

    return render_template(
        "course.html",
        course_list=course_list,
        upcoming_list=upcoming_list,
        search_query=q,
    )


@bp.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return {"query": q, "count": 0, "results": []}

    pattern = f"%{q}%"
    results = []

    # 1. Courses
    courses_found = Course.query.filter(
        Course.is_active.is_(True),
        (Course.title.ilike(pattern) | Course.description.ilike(pattern) | Course.teacher.ilike(pattern))
    ).order_by(Course.order, Course.created_at.desc()).limit(5).all()
    for c in courses_found:
        results.append({
            "type": "Course",
            "title": c.title,
            "subtitle": f"By {c.teacher}" if c.teacher else "Academic Course",
            "url": url_for("public.course_detail", course_id=c.id),
            "icon": "fa-graduation-cap",
        })

    # 2. Upcoming Courses
    upcoming_found = UpcomingCourse.query.filter(
        UpcomingCourse.is_active.is_(True),
        (UpcomingCourse.title.ilike(pattern) | UpcomingCourse.description.ilike(pattern) | UpcomingCourse.batch_name.ilike(pattern))
    ).order_by(UpcomingCourse.order, UpcomingCourse.created_at.desc()).limit(3).all()
    for u in upcoming_found:
        results.append({
            "type": "Upcoming",
            "title": u.title,
            "subtitle": f"Batch: {u.batch_name}" if u.batch_name else "Upcoming Batch",
            "url": url_for("public.upcoming_detail", course_id=u.id),
            "icon": "fa-calendar-plus-o",
        })

    # 3. Books / E-Library
    books_found = Book.query.filter(
        Book.is_active.is_(True),
        (Book.title.ilike(pattern) | Book.author.ilike(pattern) | Book.description.ilike(pattern))
    ).order_by(Book.order, Book.created_at.desc()).limit(4).all()
    for b in books_found:
        results.append({
            "type": "E-Library",
            "title": b.title,
            "subtitle": f"Author: {b.author}" if b.author else "Digital Book",
            "url": url_for("public.book_detail", book_id=b.id),
            "icon": "fa-book",
        })

    # 4. Learning Videos
    videos_found = LearningVideo.query.filter(
        LearningVideo.is_active.is_(True),
        (LearningVideo.title.ilike(pattern) | LearningVideo.instructor.ilike(pattern) | LearningVideo.category.ilike(pattern))
    ).order_by(LearningVideo.order, LearningVideo.created_at.desc()).limit(4).all()
    for v in videos_found:
        results.append({
            "type": "Video",
            "title": v.title,
            "subtitle": f"{v.category or 'Video'} • {v.instructor}" if v.instructor else (v.category or "Lecture"),
            "url": url_for("public.learning_videos"),
            "icon": "fa-play-circle",
        })

    # 5. Events
    events_found = Event.query.filter(
        Event.is_active.is_(True),
        (Event.title.ilike(pattern) | Event.content.ilike(pattern) | Event.location.ilike(pattern))
    ).order_by(Event.order, Event.created_at.desc()).limit(3).all()
    for e in events_found:
        results.append({
            "type": "Event",
            "title": e.title,
            "subtitle": f"{e.date} • {e.location}" if e.date and e.location else (e.date or "Campus Event"),
            "url": url_for("public.event_detail", event_id=e.id),
            "icon": "fa-calendar",
        })

    # 6. News
    news_found = News.query.filter(
        News.is_active.is_(True),
        (News.title.ilike(pattern) | News.content.ilike(pattern))
    ).order_by(News.order, News.created_at.desc()).limit(3).all()
    for n in news_found:
        results.append({
            "type": "News",
            "title": n.title,
            "subtitle": n.date or "Announcement",
            "url": url_for("public.news_detail", news_id=n.id),
            "icon": "fa-newspaper-o",
        })

    # 7. Faculty / Team
    faculty_found = TeamMember.query.filter(
        TeamMember.is_active.is_(True),
        (TeamMember.name.ilike(pattern) | TeamMember.role.ilike(pattern))
    ).order_by(TeamMember.order, TeamMember.id.desc()).limit(3).all()
    for m in faculty_found:
        results.append({
            "type": "Faculty",
            "title": m.name,
            "subtitle": m.role or "Faculty Member",
            "url": url_for("public.faculty_detail", member_id=m.id),
            "icon": "fa-user",
        })

    return {"query": q, "count": len(results), "results": results[:12]}


@bp.route("/courses/<int:course_id>")
def course_detail(course_id):
    item = Course.query.filter_by(id=course_id, is_active=True).first_or_404()
    related = (Course.query.filter(Course.is_active.is_(True), Course.id != item.id)
               .order_by(*_by_order(Course)).limit(5).all())
    pdf_url, pdf_download_url = pdf_urls(item, "public.course_pdf", "course_id")
    return render_template("course_detail.html", item=item, related=related,
                           pdf_url=pdf_url, pdf_download_url=pdf_download_url)


@bp.route("/upcoming-courses/<int:course_id>")
@bp.route("/upcoming-course/<int:course_id>")
def upcoming_detail(course_id):
    item = UpcomingCourse.query.filter_by(id=course_id, is_active=True).first_or_404()
    related = (UpcomingCourse.query.filter(UpcomingCourse.is_active.is_(True), UpcomingCourse.id != item.id)
               .order_by(*_by_order(UpcomingCourse)).limit(6).all())
    return render_template("upcoming_detail.html", item=item, related=related)


@bp.route("/gallery")
@bp.route("/gallery.html")
def gallery():
    return render_template("gallery.html")


@bp.route("/events")
@bp.route("/event.html")
def events():
    return render_template("event.html", events_list=_active(Event, *_by_order(Event)))


@bp.route("/events/<int:event_id>")
@bp.route("/event/<int:event_id>")
def event_detail(event_id):
    item = Event.query.filter_by(id=event_id, is_active=True).first_or_404()
    related = (Event.query.filter(Event.is_active.is_(True), Event.id != item.id)
               .order_by(*_by_order(Event)).limit(20).all())
    return render_template("event_detail.html", item=item, related=related)


@bp.route("/faculty")
@bp.route("/faculty.html")
def faculty():
    return render_template("faculty.html", faculty_list=_active(TeamMember, TeamMember.order))


@bp.route("/teacher/<int:member_id>")
@bp.route("/faculty/<int:member_id>")
def faculty_detail(member_id):
    member = TeamMember.query.filter_by(id=member_id, is_active=True).first_or_404()
    related = (TeamMember.query.filter(TeamMember.is_active.is_(True), TeamMember.id != member.id)
               .order_by(TeamMember.order).all())
    # escape LIKE wildcards so a name such as "A_li" or "100%" matches literally
    needle = member.name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    teacher_courses = (Course.query.filter(Course.is_active.is_(True), Course.teacher.ilike(f"%{needle}%", escape="\\"))
                       .order_by(Course.order).all())
    return render_template("faculty_detail.html", member=member, related=related, teacher_courses=teacher_courses)


@bp.route("/contact", methods=["GET", "POST"])
@bp.route("/contact.html", methods=["GET", "POST"])
def contact():
    if request.method == "GET":
        return render_template("contact.html")

    def respond(ok, message, status=None):
        status = status or (200 if ok else 400)
        if is_xhr():
            return message, status
        flash(message, "success" if ok else "danger")
        return redirect(url_for("public.contact"))

    # hidden "website" field: humans leave it empty, spam bots fill it. Pretend success.
    if form_str(request.form, "website"):
        return respond(True, "Thank you! Your message has been received.")

    wait = contact_by_ip.retry_after(client_ip())
    if wait:
        return respond(False, f"Too many messages sent. Please try again in {wait // 60 + 1} minute(s).", 429)

    name = form_str(request.form, "name")
    email = form_str(request.form, "email")
    phone = form_str(request.form, "phone") or None
    subject = form_str(request.form, "subject") or "General Inquiry"
    message = form_str(request.form, "message")

    if not name or not email or not message:
        return respond(False, "Please fill in all required fields (Name, Email, Message).")
    if not _EMAIL_RE.match(email):
        return respond(False, "Please enter a valid email address.")
    if len(name) > 120 or len(email) > 120 or len(subject) > 200 or len(message) > 5000 or (phone and len(phone) > 40):
        return respond(False, "One of the fields is too long. Please shorten it and try again.")

    try:
        db.session.add(ContactMessage(name=name, email=email, phone=phone, subject=subject, message=message))
        db.session.commit()
    except Exception:
        db.session.rollback()
        return respond(False, "Sorry, we could not save your message right now. Please try again in a moment.", 500)

    contact_by_ip.hit(client_ip())
    return respond(True, f"Thank you, {name}! Your message has been sent successfully. We will get back to you shortly.")


@bp.route("/e-library")
@bp.route("/elibrary.html")
def elibrary():
    return render_template("elibrary.html", book_list=_active(Book, *_by_order(Book)))


@bp.route("/e-library/<int:book_id>")
def book_detail(book_id):
    item = Book.query.filter_by(id=book_id, is_active=True).first_or_404()
    related = (Book.query.filter(Book.is_active.is_(True), Book.id != item.id)
               .order_by(*_by_order(Book)).limit(20).all())
    pdf_url, pdf_download_url = pdf_urls(item, "public.book_pdf", "book_id")
    return render_template("book_detail.html", item=item, related=related,
                           pdf_url=pdf_url, pdf_download_url=pdf_download_url)


@bp.route("/videos")
@bp.route("/learning-videos")
@bp.route("/videos.html")
def learning_videos():
    videos = _active(LearningVideo, *_by_order(LearningVideo))
    categories = sorted({v.category.strip() for v in videos if v.category and v.category.strip()})
    return render_template("learning_videos.html", videos=videos, categories=categories)


@bp.route("/news")
def news():
    return render_template("news.html", news_list=_active(News, *_by_order(News)))


@bp.route("/news/<int:news_id>")
def news_detail(news_id):
    item = News.query.filter_by(id=news_id, is_active=True).first_or_404()
    related = (News.query.filter(News.is_active.is_(True), News.id != item.id)
               .order_by(*_by_order(News)).limit(3).all())
    return render_template("news_detail.html", item=item, related=related)
