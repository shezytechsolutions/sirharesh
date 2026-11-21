"""Shared extension objects (created once, bound to the app in create_app)."""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
