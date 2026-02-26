import os
import time as _time
import urllib.request

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, current_app, jsonify
from flask_login import login_required, current_user
from markupsafe import Markup, escape

from app.extensions import db
from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission
from app.models.setting import Setting
from app.models.audit import AuditLog
from app.forms.admin import UserCreateForm, UserEditForm, RoleForm, FriendGroupForm
from app.utils.helpers import log_audit
from app.utils.settings import get_settings_by_category

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# ── Version check (cached, runs at most once per hour) ───────────────────────

_GITHUB_VERSION_URL = (
    "https://raw.githubusercontent.com/DjinnRutger/MagicDjinn/main/version.txt"
)
_ver_cache: dict = {"ts": 0.0, "local": "0.0.0", "remote": None, "newer": False}
_VER_TTL = 3600  # seconds


def _ver_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except Exception:
        return (0,)


def _check_new_version() -> tuple:
    """Return (local_ver, remote_ver, update_available). Cached for 1 hour."""
    global _ver_cache
    now = _time.time()
    if now - _ver_cache["ts"] < _VER_TTL:
        return _ver_cache["local"], _ver_cache["remote"], _ver_cache["newer"]

    # Read local version.txt (project root, one level above app/)
    try:
        vfile = os.path.join(os.path.dirname(current_app.root_path), "version.txt")
        with open(vfile) as fh:
            local = fh.read().strip()
    except Exception:
        local = "0.0.0"

    # Fetch remote version with short timeout
    try:
        req = urllib.request.Request(
            _GITHUB_VERSION_URL, headers={"User-Agent": "MagicDjinn"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            remote = resp.read().decode().strip()
    except Exception:
        _ver_cache = {"ts": now, "local": local, "remote": None, "newer": False}
        return local, None, False

    newer = _ver_tuple(remote) > _ver_tuple(local)
    _ver_cache = {"ts": now, "local": local, "remote": remote, "newer": newer}
    return local, remote, newer


def _notify_admins_of_update(remote_ver: str) -> None:
    """Create one unread version_update notification per admin (idempotent)."""
    from app.models.notification import Notification
    msg = f"MagicDjinn v{remote_ver} is available — check GitHub to update"
    admins = User.query.filter(
        db.or_(User.is_admin == True, User.role.has(name="Administrator"))  # noqa: E712
    ).all()
    changed = False
    for admin in admins:
        exists = Notification.query.filter_by(
            user_id=admin.id, type="version_update", message=msg
        ).first()
        if not exists:
            db.session.add(Notification(
                user_id=admin.id,
                type="version_update",
                message=msg,
            ))
            changed = True
    if changed:
        db.session.commit()


# ── Blueprint-wide access guard ─────────────────────────────────────────────
@admin_bp.before_request
@login_required
def require_admin_access():
    """Every admin route requires authentication + admin/full_access permission."""
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=request.url))
    if not (current_user.is_admin or current_user.has_permission("admin.full_access")):
        abort(403)


# ── Dashboard ────────────────────────────────────────────────────────────────
@admin_bp.route("/")
def index():
    stats = {
        "total_users":      User.query.count(),
        "active_users":     User.query.filter_by(is_active=True).count(),
        "total_roles":      Role.query.count(),
        "total_permissions": Permission.query.count(),
        "total_settings":   Setting.query.count(),
        "total_logs":       AuditLog.query.count(),
    }
    recent_logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(15).all()

    local_ver, remote_ver, update_available = _check_new_version()
    if update_available and remote_ver:
        _notify_admins_of_update(remote_ver)

    return render_template(
        "admin/index.html",
        stats=stats,
        recent_logs=recent_logs,
        local_ver=local_ver,
        remote_ver=remote_ver,
        update_available=update_available,
        active_page="admin",
    )


# ── Users ─────────────────────────────────────────────────────────────────────
@admin_bp.route("/users")
def users():
    page   = request.args.get("page", 1, type=int)
    search = request.args.get("search", "").strip()
    query  = User.query
    if search:
        like = f"%{search}%"
        query = query.filter(
            db.or_(User.username.ilike(like), User.email.ilike(like))
        )
    pagination = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template(
        "admin/users.html",
        users=pagination,
        search=search,
        active_page="admin_users",
    )


@admin_bp.route("/users/new", methods=["GET", "POST"])
def user_create():
    form = UserCreateForm()
    form.role_id.choices = [(0, "— No Role —")] + [(r.id, r.name) for r in Role.query.order_by(Role.name)]

    if form.validate_on_submit():
        user = User(
            username=form.username.data.strip(),
            email=form.email.data.strip().lower(),
            is_admin=form.is_admin.data,
            is_active=form.is_active.data,
            role_id=form.role_id.data or None,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()
        log_audit("created", "user", resource_id=user.id, details=f"username={user.username}")
        db.session.commit()
        flash(Markup(f"User <strong>{escape(user.username)}</strong> created successfully."), "success")
        return redirect(url_for("admin.users"))

    return render_template(
        "admin/user_form.html", form=form, user=None,
        title="Create User", active_page="admin_users",
    )


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
def user_edit(user_id: int):
    user = db.get_or_404(User, user_id)
    form = UserEditForm(user=user, obj=user)
    form.role_id.choices = [(0, "— No Role —")] + [(r.id, r.name) for r in Role.query.order_by(Role.name)]

    if request.method == "GET":
        form.role_id.data = user.role_id or 0

    if form.validate_on_submit():
        user.username  = form.username.data.strip()
        user.email     = form.email.data.strip().lower()
        user.is_admin  = form.is_admin.data
        user.is_active = form.is_active.data
        user.role_id   = form.role_id.data or None
        if form.password.data:
            user.set_password(form.password.data)
        log_audit("updated", "user", resource_id=user.id, details=f"username={user.username}")
        db.session.commit()
        flash(Markup(f"User <strong>{escape(user.username)}</strong> updated."), "success")
        return redirect(url_for("admin.users"))

    return render_template(
        "admin/user_form.html", form=form, user=user,
        title="Edit User", active_page="admin_users",
    )


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
def user_delete(user_id: int):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("admin.users"))
    username = user.username
    log_audit("deleted", "user", resource_id=user.id, details=f"username={username}")
    db.session.delete(user)
    db.session.commit()
    flash(Markup(f"User <strong>{escape(username)}</strong> deleted."), "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
def user_toggle(user_id: int):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("You cannot deactivate your own account.", "danger")
        return redirect(url_for("admin.users"))
    user.is_active = not user.is_active
    status = "activated" if user.is_active else "deactivated"
    log_audit(status, "user", resource_id=user.id)
    db.session.commit()
    flash(Markup(f"User <strong>{escape(user.username)}</strong> {escape(status)}."), "success")
    return redirect(url_for("admin.users"))


# ── Roles ─────────────────────────────────────────────────────────────────────
@admin_bp.route("/roles")
def roles():
    all_roles = Role.query.order_by(Role.name).all()
    return render_template("admin/roles.html", roles=all_roles, active_page="admin_roles")


@admin_bp.route("/roles/new", methods=["GET", "POST"])
def role_create():
    form = RoleForm()
    all_permissions = Permission.query.order_by(Permission.name).all()
    form.permissions.choices = [(p.id, p.name) for p in all_permissions]

    if form.validate_on_submit():
        role = Role(name=form.name.data.strip(), description=form.description.data)
        if form.permissions.data:
            role.permissions = Permission.query.filter(
                Permission.id.in_(form.permissions.data)
            ).all()
        db.session.add(role)
        db.session.flush()
        log_audit("created", "role", resource_id=role.id, details=f"name={role.name}")
        db.session.commit()
        flash(Markup(f"Role <strong>{escape(role.name)}</strong> created."), "success")
        return redirect(url_for("admin.roles"))

    return render_template(
        "admin/role_form.html", form=form, role=None,
        all_permissions=all_permissions, title="Create Role", active_page="admin_roles",
    )


@admin_bp.route("/roles/<int:role_id>/edit", methods=["GET", "POST"])
def role_edit(role_id: int):
    role = db.get_or_404(Role, role_id)
    form = RoleForm(obj=role)
    all_permissions = Permission.query.order_by(Permission.name).all()
    form.permissions.choices = [(p.id, p.name) for p in all_permissions]

    if request.method == "GET":
        form.permissions.data = [p.id for p in role.permissions]

    if form.validate_on_submit():
        role.name        = form.name.data.strip()
        role.description = form.description.data
        role.permissions = Permission.query.filter(
            Permission.id.in_(form.permissions.data or [])
        ).all()
        log_audit("updated", "role", resource_id=role.id, details=f"name={role.name}")
        db.session.commit()
        flash(Markup(f"Role <strong>{escape(role.name)}</strong> updated."), "success")
        return redirect(url_for("admin.roles"))

    return render_template(
        "admin/role_form.html", form=form, role=role,
        all_permissions=all_permissions, title="Edit Role", active_page="admin_roles",
    )


@admin_bp.route("/roles/<int:role_id>/delete", methods=["POST"])
def role_delete(role_id: int):
    role = db.get_or_404(Role, role_id)
    if role.users.count() > 0:
        flash(Markup(f"Cannot delete <strong>{escape(role.name)}</strong> — it has assigned users."), "danger")
        return redirect(url_for("admin.roles"))
    name = role.name
    log_audit("deleted", "role", resource_id=role.id, details=f"name={name}")
    db.session.delete(role)
    db.session.commit()
    flash(Markup(f"Role <strong>{escape(name)}</strong> deleted."), "success")
    return redirect(url_for("admin.roles"))


# ── Settings ──────────────────────────────────────────────────────────────────
@admin_bp.route("/settings", methods=["GET", "POST"])
def settings():
    categorized = get_settings_by_category()

    _PRICE_REFRESH_KEYS = {
        "price_refresh_frequency", "price_refresh_day_of_week",
        "price_refresh_day_of_month", "price_refresh_time",
    }

    if request.method == "POST":
        price_schedule_changed = False

        # Update every setting that appears in the form
        for key in request.form:
            if key.startswith("csrf_"):
                continue
            s = Setting.query.filter_by(key=key).first()
            if s:
                if key in _PRICE_REFRESH_KEYS and s.value != request.form[key]:
                    price_schedule_changed = True
                s.value = request.form[key]

        # Unchecked booleans are absent from POST data – force them to 'false'
        for settings_list in categorized.values():
            for s in settings_list:
                if s.type == "boolean" and s.key not in request.form:
                    s.value = "false"

        log_audit("updated", "settings", details="bulk update")
        db.session.commit()

        # Reschedule APScheduler job if price refresh timing changed
        if price_schedule_changed:
            try:
                from app import _schedule_price_refresh
                from app.extensions import scheduler
                _schedule_price_refresh(current_app._get_current_object())
            except Exception:
                pass  # Non-fatal — job will use old schedule until restart

        flash("Settings saved successfully.", "success")
        return redirect(url_for("admin.settings"))

    local_ver, remote_ver, update_available = _check_new_version()
    if update_available and remote_ver:
        _notify_admins_of_update(remote_ver)

    return render_template(
        "admin/settings.html",
        categorized=categorized,
        local_ver=local_ver,
        remote_ver=remote_ver,
        update_available=update_available,
        active_page="admin_settings",
    )


# ── Friend Groups ─────────────────────────────────────────────────────────────

@admin_bp.route("/friend-groups")
def friend_groups():
    from app.models.friend_group import FriendGroup
    groups = FriendGroup.query.order_by(FriendGroup.name).all()
    return render_template(
        "admin/friend_groups/index.html",
        groups=groups,
        active_page="admin_friend_groups",
    )


@admin_bp.route("/friend-groups/new", methods=["GET", "POST"])
def friend_group_create():
    from app.models.friend_group import FriendGroup
    form = FriendGroupForm()
    all_users = User.query.order_by(User.username).all()
    form.member_ids.choices = [(u.id, u.username) for u in all_users]

    if form.validate_on_submit():
        group = FriendGroup(name=form.name.data.strip(), created_by=current_user.id)
        if form.member_ids.data:
            group.members = User.query.filter(User.id.in_(form.member_ids.data)).all()
        db.session.add(group)
        db.session.flush()
        log_audit("created", "friend_group", group.id, f"name={group.name}")
        db.session.commit()
        flash(f"Friend group '{group.name}' created.", "success")
        return redirect(url_for("admin.friend_groups"))

    return render_template(
        "admin/friend_groups/form.html",
        form=form, group=None,
        title="New Friend Group",
        active_page="admin_friend_groups",
    )


@admin_bp.route("/friend-groups/<int:group_id>/edit", methods=["GET", "POST"])
def friend_group_edit(group_id: int):
    from app.models.friend_group import FriendGroup
    group = db.get_or_404(FriendGroup, group_id)
    form  = FriendGroupForm(obj=group)
    all_users = User.query.order_by(User.username).all()
    form.member_ids.choices = [(u.id, u.username) for u in all_users]

    if request.method == "GET":
        form.member_ids.data = [m.id for m in group.members]

    if form.validate_on_submit():
        group.name    = form.name.data.strip()
        group.members = User.query.filter(User.id.in_(form.member_ids.data or [])).all()
        log_audit("updated", "friend_group", group.id, f"name={group.name}")
        db.session.commit()
        flash(f"Friend group '{group.name}' updated.", "success")
        return redirect(url_for("admin.friend_groups"))

    return render_template(
        "admin/friend_groups/form.html",
        form=form, group=group,
        title=f"Edit — {group.name}",
        active_page="admin_friend_groups",
    )


@admin_bp.route("/friend-groups/<int:group_id>/delete", methods=["POST"])
def friend_group_delete(group_id: int):
    from app.models.friend_group import FriendGroup
    group = db.get_or_404(FriendGroup, group_id)
    name  = group.name
    log_audit("deleted", "friend_group", group.id, f"name={name}")
    db.session.delete(group)
    db.session.commit()
    flash(f"Friend group '{name}' deleted.", "success")
    return redirect(url_for("admin.friend_groups"))


# ── Card Values: Refresh Now ──────────────────────────────────────────────────

@admin_bp.route("/card-values/refresh-now", methods=["POST"])
def card_values_refresh_now():
    """AJAX endpoint — runs a price refresh synchronously in the request context.

    Threading is intentionally avoided: SQLite cannot tolerate a second thread
    committing while the request thread still holds a shared lock on the same
    connection (raises "database is locked").  Releasing the scoped session
    first and running inline is safe and simpler.
    """
    from app.utils.price_service import _do_refresh

    # Release the current scoped session so SQLite's shared lock is freed
    # before _do_refresh opens its own writes.
    db.session.remove()

    try:
        refreshed, history_added = _do_refresh(current_app._get_current_object())
        log_audit(
            "price_refresh", "cards",
            details=f"Manual refresh — {refreshed} cards checked, {history_added} history rows written",
        )
        return jsonify(
            success=True,
            message=(
                f"Price refresh complete. "
                f"{refreshed} card{'s' if refreshed != 1 else ''} checked, "
                f"{history_added} price record{'s' if history_added != 1 else ''} saved."
            ),
            refreshed_count=refreshed,
            history_count=history_added,
        )
    except Exception as exc:
        current_app.logger.exception("Manual price refresh failed")
        return jsonify(success=False, message=f"Refresh failed: {exc}"), 500


# ── API: Price history (for Chart.js modal) ───────────────────────────────────

@admin_bp.route("/api/cards/<scryfall_id>/price-history")
def card_price_history_api(scryfall_id: str):
    """Return price history JSON for Chart.js."""
    from app.utils.price_service import get_price_history
    days = request.args.get("days", 90, type=int)
    return jsonify(get_price_history(scryfall_id, days=days))


# ── Audit Log ─────────────────────────────────────────────────────────────────
@admin_bp.route("/audit")
def audit():
    page = request.args.get("page", 1, type=int)
    logs = (
        AuditLog.query
        .order_by(AuditLog.created_at.desc())
        .paginate(page=page, per_page=50, error_out=False)
    )
    return render_template("admin/audit.html", logs=logs, active_page="admin_audit")
