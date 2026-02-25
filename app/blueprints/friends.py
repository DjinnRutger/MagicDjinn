"""
Friends blueprint.

Lets users view friend-group members' Boxes and transfer cards into their
own decks.

Permission model:
  - friends.view  → view /friends list + member Boxes + member public decks
  - friends.view  → transfer cards (additional runtime checks via can_transfer_card)

URLs:
  GET  /friends                        – list my friend-group members
  GET  /friends/<user_id>/box          – view a member's Box (+ transfer UI)
  GET  /friends/<user_id>/decks        – view a member's public decks
  POST /friends/transfer               – AJAX: take a card from member's Box → my deck
"""
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, abort,
)
from flask_login import login_required, current_user

from app.extensions import db
from app.utils.decorators import permission_required
from app.utils.helpers import log_audit, create_notification
from app.utils.friends import can_view_box, can_transfer_card, get_friend_group_members

friends_bp = Blueprint("friends", __name__)

# ── Colour identity helper (same logic as decks.py) ──────────────────────────

_COLOUR_ORDER = "WUBRG"

def _compute_color_identity(deck) -> str:
    colors = set()
    for inv in deck.cards:
        if inv.card and inv.card.color_identity:
            colors.update(inv.card.color_identity)
    return "".join(c for c in _COLOUR_ORDER if c in colors)


# ── Friends list ──────────────────────────────────────────────────────────────

@friends_bp.route("/friends")
@login_required
@permission_required("friends.view")
def index():
    members = get_friend_group_members(current_user)
    return render_template(
        "friends/index.html",
        members=members,
        active_page="friends",
    )


# ── Friend's Box ──────────────────────────────────────────────────────────────

@friends_bp.route("/friends/<int:user_id>/box")
@login_required
@permission_required("friends.view")
def friend_box(user_id):
    from app.models.user import User
    from app.models.inventory import Inventory
    from app.models.card import Card
    from app.models.deck import Deck

    friend = User.query.get_or_404(user_id)

    if not can_view_box(current_user, friend):
        abort(403)

    search = request.args.get("q", "").strip()
    foil_only = request.args.get("foil", "") == "1"

    query = (
        Inventory.query
        .join(Card, Inventory.card_scryfall_id == Card.scryfall_id)
        .filter(
            Inventory.user_id == friend.id,
            Inventory.current_deck_id.is_(None),
        )
    )
    if search:
        query = query.filter(Card.name.ilike(f"%{search}%"))
    if foil_only:
        query = query.filter(Inventory.is_foil.is_(True))

    cards = query.order_by(Card.name.asc()).all()

    # My decks for the transfer modal
    my_decks = (
        Deck.query
        .filter_by(user_id=current_user.id)
        .order_by(Deck.name.asc())
        .all()
    )

    return render_template(
        "friends/box.html",
        friend=friend,
        cards=cards,
        my_decks=my_decks,
        search=search,
        foil_only=foil_only,
        active_page="friends",
    )


# ── Friend's public decks ─────────────────────────────────────────────────────

@friends_bp.route("/friends/<int:user_id>/decks")
@login_required
@permission_required("friends.view")
def friend_decks(user_id):
    from app.models.user import User
    from app.models.deck import Deck

    friend = User.query.get_or_404(user_id)

    if not can_view_box(current_user, friend):
        abort(403)

    decks = (
        Deck.query
        .filter_by(user_id=friend.id, is_visible_to_friends=True)
        .order_by(Deck.updated_at.desc())
        .all()
    )
    return render_template(
        "friends/decks.html",
        friend=friend,
        decks=decks,
        active_page="friends",
    )


# ── AJAX: transfer card from friend's Box → my deck or my Box ────────────────

@friends_bp.route("/friends/transfer", methods=["POST"])
@login_required
@permission_required("friends.view")
def transfer():
    from app.models.inventory import Inventory
    from app.models.deck import Deck

    data = request.get_json(silent=True)
    if not data:
        return jsonify(error="No data"), 400

    inv_id         = data.get("inv_id")
    target_deck_id = data.get("deck_id")   # None means "add to my Box"
    try:
        qty = int(data.get("qty", 1))
        if qty < 1:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify(error="Invalid quantity"), 400

    # Validate source row — must be a Box card (not in a deck)
    src_inv = Inventory.query.filter_by(id=inv_id, current_deck_id=None).first_or_404()

    if not can_transfer_card(current_user, src_inv):
        abort(403)

    qty        = min(qty, src_inv.quantity)
    card_name  = src_inv.card.name
    owner_id   = src_inv.user_id
    owner_name = src_inv.user.username

    # Resolve destination
    target_deck = None
    if target_deck_id:
        target_deck = Deck.query.filter_by(
            id=target_deck_id, user_id=current_user.id
        ).first_or_404()

    dest_deck_id = target_deck.id if target_deck else None

    # Look for an existing matching row in my destination
    existing = Inventory.query.filter_by(
        user_id=current_user.id,
        card_scryfall_id=src_inv.card_scryfall_id,
        is_foil=src_inv.is_foil,
        current_deck_id=dest_deck_id,
    ).first()

    # Remove from friend's Box
    if qty >= src_inv.quantity:
        db.session.delete(src_inv)
    else:
        src_inv.quantity -= qty

    # Add to my destination
    if existing:
        existing.quantity += qty
    else:
        db.session.add(Inventory(
            user_id=current_user.id,
            card_scryfall_id=src_inv.card_scryfall_id,
            quantity=qty,
            is_foil=src_inv.is_foil,
            condition=src_inv.condition,
            current_deck_id=dest_deck_id,
        ))

    # Recompute color identity when adding to a deck
    if target_deck:
        target_deck.color_identity = _compute_color_identity(target_deck)

    db.session.commit()

    dest_label = f"'{target_deck.name}'" if target_deck else "your Box"
    log_audit(
        "card_transferred", "inventory", inv_id,
        f"Took {qty}× {card_name} from {owner_name} → {dest_label}"
    )
    create_notification(
        user_id=owner_id,
        actor_id=current_user.id,
        notif_type="card_taken",
        message=f"{current_user.username} took {qty}× {card_name} from your Box into {dest_label}",
    )
    db.session.commit()

    return jsonify(
        success=True,
        message=f"Took {qty}× {card_name} from {owner_name} into {dest_label}."
    )


# ── AJAX: friend deck cards (read-only) ───────────────────────────────────────

@friends_bp.route("/friends/decks/<int:deck_id>/cards")
@login_required
@permission_required("friends.view")
def friend_deck_cards(deck_id):
    from app.models.deck import Deck
    from app.models.user import User
    from app.models.inventory import Inventory
    from app.models.card import Card

    deck = Deck.query.get_or_404(deck_id)
    if not deck.is_visible_to_friends:
        abort(403)

    owner = User.query.get_or_404(deck.user_id)
    if not can_view_box(current_user, owner):
        abort(403)

    invs = (
        Inventory.query
        .join(Card, Inventory.card_scryfall_id == Card.scryfall_id)
        .filter(Inventory.current_deck_id == deck_id)
        .order_by(Card.name.asc())
        .all()
    )

    cards = []
    for inv in invs:
        c = inv.card
        cards.append({
            "name":        c.name,
            "image_small": c.image_small,
            "image_normal": c.image_normal,
            "set_code":    (c.set_code or "").upper(),
            "type_line":   c.type_line or "",
            "mana_cost":   c.mana_cost or "",
            "oracle_text": c.oracle_text or "",
            "rarity":      c.rarity or "",
            "usd":         c.usd,
            "usd_foil":    c.usd_foil,
            "quantity":    inv.quantity,
            "is_foil":     inv.is_foil,
            "is_sideboard": inv.is_sideboard,
        })

    return jsonify({
        "deck_name":      deck.name,
        "format":         deck.format,
        "color_identity": deck.color_identity or "",
        "total_quantity": deck.total_quantity,
        "cover_image":    deck.cover_card_image,
        "cards":          cards,
    })
