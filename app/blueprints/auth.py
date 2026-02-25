from datetime import datetime, timezone

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db, limiter
from app.models.user import User
from app.forms.auth import LoginForm
from app.utils.helpers import log_audit

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("15 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()

        if user is None or not user.check_password(form.password.data):
            flash("Invalid username or password.", "danger")
            log_audit("login_failed", "user", details=f"username={form.username.data}")
            db.session.commit()
            return render_template("auth/login.html", form=form)

        if not user.is_active:
            flash("Your account is disabled. Contact an administrator.", "danger")
            return render_template("auth/login.html", form=form)

        login_user(user, remember=form.remember_me.data)
        user.last_login = datetime.now(timezone.utc)
        log_audit("login", "user", resource_id=user.id)
        db.session.commit()

        # Safe open redirect – only allow local paths
        next_page = request.args.get("next")
        if next_page and next_page.startswith("/") and not next_page.startswith("//"):
            return redirect(next_page)
        return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    log_audit("logout", "user", resource_id=current_user.id)
    db.session.commit()
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
