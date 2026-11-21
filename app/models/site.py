"""Site-wide content blocks."""
from ..extensions import db
from ..utils import utcnow


class SiteSetting(db.Model):
    """Simple key-value store for site content that admin can edit."""
    __tablename__ = "site_settings"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class FunFactor(db.Model):
    __tablename__ = "fun_factors"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), nullable=False)
    label = db.Column(db.String(80), nullable=False)
    order = db.Column(db.Integer, default=0)


class Page(db.Model):
    """Registered pages that admin can edit."""
    __tablename__ = "pages"
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), unique=True, nullable=False)  # e.g. index
    title = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class SliderImage(db.Model):
    """Hero slider slides for the index page."""
    __tablename__ = "slider_images"
    id = db.Column(db.Integer, primary_key=True)
    page_slug = db.Column(db.String(80), default="index", nullable=False)
    image = db.Column(db.String(255), nullable=False)  # URL path
    title = db.Column(db.String(200), nullable=True)
    subtitle = db.Column(db.Text, nullable=True)
    button_text = db.Column(db.String(80), default="View Courses")
    button_link = db.Column(db.String(255), default="course.html")
    order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    # background-position for perfect framing
    pos_desktop = db.Column(db.String(40), default="center center")
    pos_mobile = db.Column(db.String(40), default="center center")


class WhyChoose(db.Model):
    __tablename__ = "why_choose"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(80), default="zmdi-accounts")  # material icon class suffix
    order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)


class AboutBlock(db.Model):
    """Reusable about-page blocks: mission, vision, values, hero, etc."""
    __tablename__ = "about_blocks"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), unique=True, nullable=False)  # mission, vision, values, hero_title, hero_text
    title = db.Column(db.String(200), nullable=True)
    content = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(80), nullable=True)
    image = db.Column(db.String(255), nullable=True)
    order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)


class ContactMessage(db.Model):
    __tablename__ = "contact_messages"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40), nullable=True)
    subject = db.Column(db.String(200), nullable=True)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)


class PageVisit(db.Model):
    """Anonymous page-view log for site-owner analytics (IP, path, time)."""
    __tablename__ = "page_visits"
    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(64), nullable=False, index=True)
    path = db.Column(db.String(255), nullable=False, default="/")
    method = db.Column(db.String(10), default="GET")
    user_agent = db.Column(db.String(255), nullable=True)
    referrer = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, index=True)
