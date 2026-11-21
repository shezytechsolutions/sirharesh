"""Default demo content, inserted into tables (first run or on demo request)."""
from ..extensions import db


def seed_defaults():
    from ..admin.site import do_create_demo_data
    do_create_demo_data()
