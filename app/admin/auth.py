"""Admin login / logout / change password."""
import math

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash

from ..extensions import db
from ..models import Admin
from ..security import (client_ip, login_by_ip, login_by_user, login_required, password_problem,
                        password_stamp, start_admin_session)
from ..services.bootstrap import forget_first_password_file
from ..utils import form_str
from . import bp

_DUMMY_HASH = generate_password_hash("not-a-real-password")   # equalises timing for unknown users


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "GET" and session.get("admin_id"):
        return redirect(url_for("admin.admin_dashboard"))

    if request.method == "POST":
        username = form_str(request.form, "username")
        password = request.form.get("password", "")
        user_key, ip_key = username.lower(), client_ip()

        wait = max(login_by_user.retry_after(user_key), login_by_ip.retry_after(ip_key))
        if wait:
            flash(f"Too many failed attempts. Please try again in {math.ceil(wait / 60)} minute(s).", "danger")
            return render_template("admin/login.html"), 429

        admin = Admin.query.filter_by(username=username).first()
        ok = check_password_hash(admin.password_hash if admin else _DUMMY_HASH, password) and admin is not None
        if ok:
            login_by_user.reset(user_key)
            start_admin_session(admin)
            flash("Welcome back!", "success")
            return redirect(url_for("admin.admin_dashboard"))

        login_by_user.hit(user_key)
        login_by_ip.hit(ip_key)
        flash("Invalid username or password.", "danger")
    return render_template("admin/login.html")


@bp.route("/admin/logout", methods=["GET", "POST"])
def admin_logout():
    if request.method == "POST":          # logging out needs a POST so other sites can't trigger it
        session.clear()
        flash("You have been logged out.", "info")
        return redirect(url_for("admin.admin_login"))
    return redirect(url_for("admin.admin_dashboard"))


@bp.route("/admin/change-password", methods=["GET", "POST"])
@login_required
def admin_change_password():
    from flask import g
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        admin = g.admin
        problem = password_problem(new, admin.username)
        if not admin.check_password(current):
            flash("Current password is incorrect.", "danger")
        elif new != confirm:
            flash("New passwords do not match.", "danger")
        elif problem:
            flash(problem, "danger")
        else:
            admin.set_password(new)
            db.session.commit()
            session["pv"] = password_stamp(admin)       # keep THIS session; all others are signed out
            forget_first_password_file()
            flash("Password changed successfully.", "success")
            return redirect(url_for("admin.admin_dashboard"))
    return render_template("admin/change_password.html")
