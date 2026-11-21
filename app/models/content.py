"""Main content models."""
from ..extensions import db
from ..utils import utcnow
from ..utils import extract_youtube_id


class News(db.Model):
    __tablename__ = "news"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(255), nullable=True)
    date = db.Column(db.String(40), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    show_on_home = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)


class Course(db.Model):
    __tablename__ = "courses"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image = db.Column(db.String(255), nullable=True)
    pdf = db.Column(db.String(255), nullable=True)
    teacher = db.Column(db.String(120), nullable=True)
    teacher_role = db.Column(db.String(80), default="Professor")
    teacher_image = db.Column(db.String(255), nullable=True)
    students = db.Column(db.Integer, default=0)
    likes = db.Column(db.Integer, default=0)
    rating = db.Column(db.String(10), default="4.5")
    is_active = db.Column(db.Boolean, default=True)
    show_on_home = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)


class UpcomingCourse(db.Model):
    __tablename__ = "upcoming_courses"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image = db.Column(db.String(255), nullable=True)
    batch_name = db.Column(db.String(120), nullable=True)
    start_date = db.Column(db.String(40), nullable=True)
    last_apply_date = db.Column(db.String(40), nullable=True)
    form_link = db.Column(db.String(500), nullable=True)
    duration = db.Column(db.String(120), nullable=True)
    fee = db.Column(db.String(120), nullable=True)
    seats = db.Column(db.String(60), nullable=True)
    instructor = db.Column(db.String(120), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)


class Event(db.Model):
    __tablename__ = "events"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(255), nullable=True)
    date = db.Column(db.String(40), nullable=True)
    time = db.Column(db.String(40), nullable=True)
    location = db.Column(db.String(200), nullable=True)
    form_link = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    show_on_home = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)


class Book(db.Model):
    __tablename__ = "books"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(120), nullable=True)
    pages = db.Column(db.String(40), nullable=True)
    image = db.Column(db.String(255), nullable=True)
    pdf = db.Column(db.String(255), nullable=True)
    badge = db.Column(db.String(40), default="Available")
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    show_on_home = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)


class LearningVideo(db.Model):
    """Learning videos embedded from YouTube with overlay lightbox player."""
    __tablename__ = "learning_videos"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    youtube_url = db.Column(db.String(500), nullable=False)
    video_id = db.Column(db.String(50), nullable=True)
    category = db.Column(db.String(100), default="General")
    instructor = db.Column(db.String(120), nullable=True)
    duration = db.Column(db.String(40), nullable=True)
    description = db.Column(db.Text, nullable=True)
    custom_thumbnail = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    show_on_home = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)

    @property
    def resolved_video_id(self):
        return (self.video_id or "").strip() or extract_youtube_id(self.youtube_url)

    @property
    def embed_url(self):
        vid = self.resolved_video_id
        return f"https://www.youtube.com/embed/{vid}?autoplay=1&rel=0"

    @property
    def thumbnail_url(self):
        if self.custom_thumbnail and self.custom_thumbnail.strip():
            return self.custom_thumbnail.strip()
        vid = self.resolved_video_id
        if vid:
            return f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
        return "/static/img/course/1.jpg"
