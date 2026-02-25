from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user

from app.extensions import db
from app.utils.decorators import permission_required

main_bp = Blueprint("main", __name__)

VALID_THEMES = {"light", "dark", "terminal"}


@main_bp.route("/")
@main_bp.route("/dashboard")
@login_required
@permission_required("dashboard.view")
def dashboard():
    from app.models.user import User
    from app.models.role import Role
    from app.models.setting import Setting
    from app.models.audit import AuditLog
    from app.models.inventory import Inventory
    from app.models.deck import Deck
    from app.utils.friends import get_friend_group_members
    from sqlalchemy import func

    # ── MTG stats ────────────────────────────────────────────────────────────
    box_qty = (
        db.session.query(func.sum(Inventory.quantity))
        .filter(
            Inventory.user_id == current_user.id,
            Inventory.current_deck_id.is_(None),
        )
        .scalar() or 0
    )
    deck_count = Deck.query.filter_by(user_id=current_user.id).count()

    # Total collection value (box + all decks) — Python loop is fine at personal scale
    all_inv = Inventory.query.filter_by(user_id=current_user.id).all()
    collection_value = round(
        sum((inv.effective_unit_price or 0) * inv.quantity
            for inv in all_inv if not inv.is_proxy),
        2,
    )

    friends = get_friend_group_members(current_user)
    friend_count = len(friends)

    # ── MTG activity feed ────────────────────────────────────────────────────
    mtg_actions = [
        "collection_import",
        "deck_created", "deck_updated", "deck_deleted",
        "card_moved", "card_transferred",
    ]
    relevant_ids = [current_user.id] + [f.id for f in friends]
    activity = (
        AuditLog.query
        .filter(
            AuditLog.user_id.in_(relevant_ids),
            AuditLog.action.in_(mtg_actions),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(12)
        .all()
    )

    # ── Admin system stats ───────────────────────────────────────────────────
    admin_stats = None
    if current_user.is_admin or current_user.has_permission("admin.full_access"):
        admin_stats = {
            "total_users":    User.query.count(),
            "active_users":   User.query.filter_by(is_active=True).count(),
            "total_roles":    Role.query.count(),
            "total_settings": Setting.query.count(),
        }

    return render_template(
        "main/dashboard.html",
        box_qty=box_qty,
        deck_count=deck_count,
        collection_value=collection_value,
        friend_count=friend_count,
        activity=activity,
        admin_stats=admin_stats,
        active_page="dashboard",
    )


# ── API: spotlight card images ────────────────────────────────────────────────

@main_bp.route("/api/spotlight-cards")
@login_required
def spotlight_cards():
    """Return up to 20 random cards from the user's + friends' boxes and decks."""
    from app.models.inventory import Inventory
    from app.models.card import Card
    from app.models.deck import Deck
    from app.utils.friends import get_friend_group_members

    friends    = get_friend_group_members(current_user)
    user_ids   = [current_user.id] + [f.id for f in friends]
    friend_map = {f.id: f.username for f in friends}

    items = (
        Inventory.query
        .join(Card, Inventory.card_scryfall_id == Card.scryfall_id)
        .filter(
            Inventory.user_id.in_(user_ids),
            Card.image_small.isnot(None),
        )
        .order_by(db.func.random())
        .limit(20)
        .all()
    )

    # Batch-load deck names to avoid N+1 queries
    deck_ids = {inv.current_deck_id for inv in items if inv.current_deck_id}
    deck_map = {}
    if deck_ids:
        for d in Deck.query.filter(Deck.id.in_(deck_ids)).all():
            deck_map[d.id] = d.name

    result = []
    for inv in items:
        if not inv.card or not inv.card.image_small:
            continue
        is_own = inv.user_id == current_user.id
        uname  = "You" if is_own else friend_map.get(inv.user_id, "Friend")
        if inv.current_deck_id:
            deck_name = deck_map.get(inv.current_deck_id, "a Deck")
            location  = f"Your Deck: {deck_name}" if is_own else f"{uname}'s Deck: {deck_name}"
        else:
            location  = "Your Box" if is_own else f"{uname}'s Box"
        result.append({
            "inv_id":      inv.id,
            "is_own":      is_own,
            "image":       inv.card.image_normal or inv.card.image_small,
            "image_small": inv.card.image_small,
            "name":        inv.card.name,
            "owner":       uname,
            "location":    location,
            "is_foil":     inv.is_foil,
            "is_proxy":    inv.is_proxy,
            "scryfall_id": inv.card.scryfall_id,
            "set_name":    inv.card.set_name or "",
            "set_code":    (inv.card.set_code or "").upper(),
            "type_line":   inv.card.type_line or "",
            "oracle_text": inv.card.oracle_text or "",
            "mana_cost":   inv.card.mana_cost or "",
            "rarity":      inv.card.rarity or "",
            "usd":         inv.card.usd,
            "usd_foil":    inv.card.usd_foil,
            "quantity":    inv.quantity,
            "condition":   inv.condition.value,
            "purchase_price": inv.purchase_price_usd,
            "physical_location": inv.physical_location or "",
            "notes":       inv.notes or "",
        })
    return jsonify(result)


# ── Password change ──────────────────────────────────────────────────────────

@main_bp.route("/api/change-password", methods=["POST"])
@login_required
def change_password():
    """AJAX endpoint – change the current user's password."""
    data = request.get_json(silent=True) or {}
    current_pw = data.get("current_password", "")
    new_pw     = data.get("new_password", "")
    confirm_pw = data.get("confirm_password", "")

    if not current_pw:
        return jsonify(error="Current password is required."), 400
    if not current_user.check_password(current_pw):
        return jsonify(error="Current password is incorrect."), 400
    if not new_pw:
        return jsonify(error="New password is required."), 400
    if len(new_pw) < 8:
        return jsonify(error="New password must be at least 8 characters."), 400
    if new_pw != confirm_pw:
        return jsonify(error="Passwords do not match."), 400

    current_user.set_password(new_pw)
    db.session.commit()
    return jsonify(success=True, message="Password updated successfully.")


@main_bp.route("/api/profile/avatar", methods=["POST"])
@login_required
def save_avatar():
    """AJAX endpoint – save a Scryfall art_crop URL as the user's avatar."""
    data = request.get_json(silent=True) or {}
    url  = (data.get("art_crop_url") or "").strip()
    if url and not url.startswith("https://cards.scryfall.io/art_crop/"):
        return jsonify(error="Invalid image URL"), 400
    current_user.avatar_art_crop = url or None
    db.session.commit()
    return jsonify(success=True)


@main_bp.route("/api/profile/avatar/search")
@login_required
def avatar_art_search():
    """AJAX endpoint – search Scryfall and return art_crop URLs for avatar picker."""
    from app.utils.scryfall import search_cards, ScryfallError
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    try:
        cards = search_cards(q, page=1)
        results = []
        for c in cards[:16]:
            if c.get("image_art_crop"):
                results.append({
                    "name":        c["name"],
                    "set_code":    c.get("set_code", ""),
                    "art_crop":    c["image_art_crop"],
                    "scryfall_id": c["scryfall_id"],
                })
        return jsonify(results)
    except ScryfallError:
        return jsonify([])


@main_bp.route("/api/set-theme", methods=["POST"])
@login_required
def set_theme():
    """AJAX endpoint – persist theme preference to the database."""
    data  = request.get_json(silent=True) or {}
    theme = data.get("theme", "light")
    if theme not in VALID_THEMES:
        return jsonify(error="Invalid theme"), 400
    current_user.theme = theme
    db.session.commit()
    return jsonify(theme=current_user.theme)


@main_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    from app.forms.profile import ChangePasswordForm
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "danger")
        elif form.new_password.data:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            flash("Password updated successfully.", "success")
        return redirect(url_for("main.profile"))
    return render_template("main/profile.html", form=form, active_page="profile")
