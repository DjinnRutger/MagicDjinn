"""First-run setup wizard – creates the initial admin account."""
from flask import Blueprint, render_template, redirect, url_for, flash

from app.extensions import db
from app.models.user import User
from app.models.role import Role

setup_bp = Blueprint("setup", __name__, url_prefix="/setup")


@setup_bp.route("/", methods=["GET", "POST"])
def index():
    # Already configured — send to login
    if User.query.first():
        return redirect(url_for("auth.login"))

    from app.forms.setup import SetupForm
    form = SetupForm()

    if form.validate_on_submit():
        admin_role = Role.query.filter_by(name="Administrator").first()
        user = User(
            username=form.username.data.strip(),
            email=form.email.data.strip().lower(),
            is_admin=True,
            is_active=True,
            role_id=admin_role.id if admin_role else None,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        flash("Your admin account has been created. Welcome!", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/setup.html", form=form)
