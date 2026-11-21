"""
Admin pages that manage lists of content (news, courses, events, ...).
Each page is declared once with the generic Crud helper - see crud.py.
"""
from datetime import datetime

from flask import redirect, render_template, request, url_for

from ..models import (Book, Course, Event, FunFactor, LearningVideo, News, TeamMember, Testimonial,
                      UpcomingCourse, WhyChoose)
from ..security import login_required
from ..utils import extract_youtube_id
from . import bp
from .crud import Crud, Field, FileField

TITLE = lambda: Field("title", required=True)           # noqa: E731
ORDER = lambda: Field("order", "int")                   # noqa: E731
HOME = lambda: Field("show_on_home", "bool")            # noqa: E731


def _today():
    return {"date": datetime.now().strftime("%d %b %Y")}


def _video_fill(item, form, mode):
    item.video_id = extract_youtube_id(item.youtube_url)


NEWS = Crud(
    News, "News",
    fields=[TITLE(), Field("content", required=True), Field("date"), ORDER(), HOME()],
    files=[FileField("image", "image_path", "image", "image", "news")],
    allow=("add", "edit", "delete", "toggle"),
    add_defaults=_today,
    msgs={"delete": "News deleted.", "edit": "News updated.", "add": "News published."},
)

COURSES = Crud(
    Course, "Course",
    fields=[TITLE(), Field("description", required=True), Field("teacher"),
            Field("teacher_role", default="Professor"), Field("students", "int", default=0), Field("likes", "int", default=0),
            Field("rating", default="4.5"), ORDER(), HOME()],
    files=[FileField("image", "image_path", "image", "image", "courses"),
           FileField("teacher_image", "teacher_image_path", "teacher_image", "image", "courses", prefix="teacher_"),
           FileField("pdf", "pdf_path", "pdf", "pdf", "courses", clear_on_blank=True)],
    msgs={"delete": "Course deleted.", "edit": "Course updated.", "add": "Course published."},
)

UPCOMING = Crud(
    UpcomingCourse, "Upcoming course",
    fields=[TITLE(), Field("description"), Field("batch_name"), Field("start_date"), Field("last_apply_date"),
            Field("form_link", "link"), Field("duration"), Field("fee"), Field("seats"), Field("instructor"),
            ORDER()],
    files=[FileField("image", "image_path", "image", "image", "upcoming")],
    msgs={"delete": "Upcoming course deleted.", "edit": "Upcoming course updated.", "add": "Upcoming course published."},
)

EVENTS = Crud(
    Event, "Event",
    fields=[TITLE(), Field("content", required=True), Field("date"), Field("time"), Field("location"),
            Field("form_link", "link"), ORDER(), HOME()],
    files=[FileField("image", "image_path", "image", "image", "events")],
    msgs={"delete": "Event deleted.", "edit": "Event updated.", "add": "Event published."},
)

BOOKS = Crud(
    Book, "Book",
    fields=[TITLE(), Field("author"), Field("pages"), Field("badge"), Field("description"), ORDER(), HOME()],
    files=[FileField("image", "image_path", "image", "image", "books"),
           FileField("pdf", "pdf_path", "pdf", "pdf", "books", clear_on_blank=True)],
    msgs={"delete": "Book deleted.", "edit": "Book updated.", "add": "Book published."},
)

VIDEOS = Crud(
    LearningVideo, "Learning video",
    fields=[TITLE(), Field("youtube_url", required=True), Field("category", default="General"),
            Field("instructor"), Field("duration"), Field("description"), ORDER(), HOME()],
    files=[FileField("thumbnail", "thumbnail_path", "custom_thumbnail", "image", "videos",
                     prefix="video_", clear_on_blank=True)],
    after_fill=_video_fill,
    msgs={"add": "Learning video added successfully.", "edit": "Learning video updated successfully.",
          "delete": "Learning video deleted.", "toggle": "Video visibility updated."},
)

WHY = Crud(
    WhyChoose, "Item",
    fields=[TITLE(), Field("content"), Field("icon", default="zmdi-accounts"), ORDER()],
    allow=("add", "delete", "toggle"),
    msgs={"delete": "Deleted."},
    order_by=lambda m: (m.order,),
)

TEAM = Crud(
    TeamMember, "Team member",
    fields=[Field("name", required=True), Field("role"), Field("qualification"), Field("description"),
            Field("facebook", "link"), Field("twitter", "link"), Field("linkedin", "link"),
            Field("instagram", "link"), Field("email"), ORDER()],
    files=[FileField("image", "image_path", "image", "image", "team")],
    msgs={"delete": "Deleted."},
    order_by=lambda m: (m.order,),
)

FUN = Crud(
    FunFactor, "Fun factor",
    fields=[Field("number", default="0"), Field("label", required=True), ORDER()],
    allow=("add", "edit", "delete"),
    msgs={"edit": "Updated.", "delete": "Deleted."},
)

TESTIMONIALS = Crud(
    Testimonial, "Testimonial",
    fields=[Field("author", required=True), Field("content", required=True), Field("image", "path"), ORDER()],
    allow=("add", "delete", "toggle"),
    msgs={"delete": "Deleted."},
    order_by=lambda m: (m.order,),
)


def crud_page(rule, endpoint, crud, template, extra_rules=()):
    """Register GET (list) + POST (actions) for a Crud-driven admin page, keeping the endpoint name."""

    def view():
        if request.method == "POST":
            crud.dispatch(request.form, request.files)
            return redirect(url_for(f"admin.{endpoint}"))
        return render_template(template, items=crud.list())

    view.__name__ = endpoint
    wrapped = login_required(view)
    for r in (rule, *extra_rules):
        bp.add_url_rule(r, endpoint=endpoint, view_func=wrapped, methods=["GET", "POST"])


crud_page("/admin/news", "admin_news", NEWS, "admin/news.html")
crud_page("/admin/courses", "admin_courses", COURSES, "admin/courses.html")
crud_page("/admin/upcoming-courses", "admin_upcoming_courses", UPCOMING, "admin/upcoming_courses.html")
crud_page("/admin/events", "admin_events", EVENTS, "admin/events.html")
crud_page("/admin/e-library", "admin_elibrary", BOOKS, "admin/elibrary.html")
crud_page("/admin/videos", "admin_learning_videos", VIDEOS, "admin/learning_videos.html",
          extra_rules=("/admin/learning-videos",))
@bp.route("/admin/why-choose")
@login_required
def admin_why_choose():
    return redirect(url_for("admin.admin_about", _anchor="why-choose"))


@bp.route("/admin/team")
@login_required
def admin_team():
    return redirect(url_for("admin.admin_about", _anchor="team"))


@bp.route("/admin/fun-factors")
@login_required
def admin_fun_factors():
    return redirect(url_for("admin.admin_homepage", _anchor="fun-factors"))


@bp.route("/admin/testimonials")
@login_required
def admin_testimonials():
    return redirect(url_for("admin.admin_homepage", _anchor="testimonials"))
