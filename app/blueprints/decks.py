"""
Decks blueprint.

Handles deck CRUD and all card movement between Box and decks.

Card movement rules:
  - Adding to deck: takes from user's Box (current_deck_id=NULL)
  - Removing from deck: returns to Box (sets current_deck_id=NULL)
  - Qty splits are handled cleanly: partial moves create/merge rows

URLs:
  GET      /decks                             – deck list
  GET|POST /decks/new                         – create deck
  GET      /decks/<id>                        – deck detail + card grid
  GET|POST /decks/<id>/edit                  – edit deck metadata + sharing
  POST     /decks/<id>/delete               – delete deck (returns cards to Box)
  POST     /decks/<id>/set-cover            – AJAX: set cover card
  POST     /decks/<id>/add-card             – AJAX: move card from Box to deck
  POST     /decks/<id>/remove-card/<inv>    – AJAX: return card to Box
  POST     /decks/move-card                  – AJAX: move card between decks
  POST     /decks/<id>/import-stream        – streaming import into existing deck
"""
import logging

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, abort, Response, stream_with_context,
)
from flask_login import login_required, current_user

from app.extensions import db
from app.utils.decorators import permission_required
from app.utils.helpers import log_audit

log = logging.getLogger(__name__)
decks_bp = Blueprint("decks", __name__)

# ── Colour identity helper ────────────────────────────────────────────────────

_COLOUR_ORDER = "WUBRG"

def _compute_color_identity(deck) -> str:
    """Re-derive a deck's colour identity from its current card list."""
    colors = set()
    for inv in deck.cards:
        if inv.card and inv.card.color_identity:
            colors.update(inv.card.color_identity)
    return "".join(c for c in _COLOUR_ORDER if c in colors)


def _can_access_deck(deck, user):
    """Return (is_owner, can_edit) for the given user and deck, or abort 403."""
    is_owner = (deck.user_id == user.id)
    can_edit = is_owner or deck.is_shared_with(user)
    if not can_edit:
        abort(403)
    return is_owner, can_edit


# ── Deck list ─────────────────────────────────────────────────────────────────

@decks_bp.route("/decks")
@login_required
@permission_required("deck.view")
def index():
    from app.models.deck import Deck
    decks = (
        Deck.query
        .filter_by(user_id=current_user.id)
        .order_by(Deck.updated_at.desc())
        .all()
    )
    return render_template(
        "decks/index.html",
        decks=decks,
        active_page="decks",
    )


# ── Create deck ───────────────────────────────────────────────────────────────

@decks_bp.route("/decks/new", methods=["GET", "POST"])
@login_required
@permission_required("deck.edit")
def new_deck():
    from app.forms.decks import DeckForm
    from app.models.deck import Deck
    from app.utils.card_service import bulk_import_to_deck, bulk_import_moxfield_text

    form = DeckForm()
    if form.validate_on_submit():
        import_type = form.import_type.data

        # ── Create the deck ───────────────────────────────────────────────────
        raw_bracket = form.bracket.data
        deck = Deck(
            user_id=current_user.id,
            name=form.name.data.strip(),
            description=form.description.data.strip() or None,
            format=form.format.data,
            is_visible_to_friends=form.is_visible_to_friends.data,
            bracket=int(raw_bracket) if raw_bracket else None,
        )
        db.session.add(deck)
        db.session.flush()  # get deck.id without committing yet

        # ── Import cards if requested ─────────────────────────────────────────
        result = None
        if import_type == "decklist" and (form.decklist_text.data or "").strip():
            result = bulk_import_to_deck(
                form.decklist_text.data, current_user.id, deck.id
            )
        elif import_type == "moxfield" and (form.moxfield_text.data or "").strip():
            result = bulk_import_moxfield_text(
                form.moxfield_text.data, current_user.id, deck.id
            )

        deck.color_identity = _compute_color_identity(deck)
        db.session.commit()

        log_audit("deck_created", "deck", deck.id, f"Created deck '{deck.name}'")
        from app.utils.feed_service import create_deck_post
        create_deck_post(current_user.id, deck, "deck_created")
        db.session.commit()

        if result:
            if result.failure_count:
                flash(
                    f"Deck '{deck.name}' created with {result.success_count} card(s). "
                    f"{result.failure_count} card(s) could not be imported.",
                    "warning",
                )
            else:
                flash(
                    f"Deck '{deck.name}' created with {result.success_count} card(s)!",
                    "success",
                )
        else:
            flash(f"Deck '{deck.name}' created!", "success")

        return redirect(url_for("decks.detail", deck_id=deck.id))

    return render_template(
        "decks/form.html",
        form=form,
        title="New Deck",
        active_page="decks",
    )


# ── Streaming deck creation ───────────────────────────────────────────────────

@decks_bp.route("/decks/new-stream", methods=["POST"])
@login_required
@permission_required("deck.edit")
def new_deck_stream():
    """Streaming variant of new_deck — yields NDJSON progress events.

    Event sequence:
      {"type": "deck_created", "deck_id": N}
      {"type": "start",        "total": N}           (only when importing)
      {"type": "progress",     "current": i, "total": N, "card": name, "ok": bool}
      {"type": "done",         "successes": N, "failures": N, "redirect_url": "..."}
    """
    import json as _j
    from app.forms.decks import DeckForm
    from app.models.deck import Deck
    from app.utils.card_service import stream_deck_import

    form = DeckForm()
    if not form.validate_on_submit():
        def _err():
            yield _j.dumps({"type": "error",
                            "message": "Invalid form or CSRF token expired. Please refresh."}) + "\n"
        return Response(stream_with_context(_err()), content_type="application/x-ndjson")

    user_id    = current_user.id
    name       = form.name.data.strip()
    description = (form.description.data or "").strip() or None
    fmt        = form.format.data
    visible    = form.is_visible_to_friends.data
    raw_bracket = form.bracket.data
    bracket_val = int(raw_bracket) if raw_bracket else None
    import_type = form.import_type.data
    text       = (form.decklist_text.data if import_type == "decklist"
                  else form.moxfield_text.data) or ""
    is_moxfield = import_type == "moxfield"
    has_import  = bool(text.strip()) and import_type in ("decklist", "moxfield")

    def _gen():
        try:
            deck = Deck(
                user_id=user_id,
                name=name,
                description=description,
                format=fmt,
                is_visible_to_friends=visible,
                bracket=bracket_val,
            )
            db.session.add(deck)
            db.session.flush()

            yield _j.dumps({"type": "deck_created", "deck_id": deck.id}) + "\n"

            if has_import:
                result = yield from stream_deck_import(
                    text, user_id, deck.id, moxfield=is_moxfield
                )
            else:
                from app.utils.card_service import ImportResult
                result = ImportResult()

            deck.color_identity = _compute_color_identity(deck)
            db.session.commit()
            log_audit("deck_created", "deck", deck.id, f"Created deck '{name}'")
            from app.utils.feed_service import create_deck_post
            create_deck_post(user_id, deck, "deck_created")
            db.session.commit()

            yield _j.dumps({
                "type": "done",
                "successes": result.success_count,
                "failures": result.failure_count,
                "redirect_url": url_for("decks.detail", deck_id=deck.id),
            }) + "\n"

        except Exception as exc:
            log.exception("Streaming deck creation failed")
            yield _j.dumps({"type": "error", "message": str(exc)}) + "\n"

    resp = Response(stream_with_context(_gen()), content_type="application/x-ndjson")
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


# ── Deck detail ───────────────────────────────────────────────────────────────

@decks_bp.route("/decks/<int:deck_id>")
@login_required
@permission_required("deck.view")
def detail(deck_id):
    from app.models.deck import Deck
    from app.models.inventory import Inventory
    from app.models.card import Card

    deck = Deck.query.get_or_404(deck_id)
    is_owner, can_edit = _can_access_deck(deck, current_user)

    search = request.args.get("q", "").strip()
    query = (
        Inventory.query
        .join(Card, Inventory.card_scryfall_id == Card.scryfall_id)
        .filter(Inventory.current_deck_id == deck.id)
    )
    if search:
        query = query.filter(Card.name.ilike(f"%{search}%"))
    deck_cards_raw = query.all()

    # ── Sort order ────────────────────────────────────────────────────────────
    _TYPE_ORDER = {
        "commander":    0,
        "creature":     1,
        "instant":      2,
        "sorcery":      3,
        "artifact":     4,
        "enchantment":  5,
        "planeswalker": 6,
        "battle":       7,
        "land":         8,
    }

    def _type_rank(inv) -> int:
        tl = (inv.card.type_line or "").lower()
        for key, rank in _TYPE_ORDER.items():
            if key in tl:
                return rank
        return 9

    def _sort_key(inv):
        return (
            1 if inv.is_sideboard else 0,
            0 if inv.is_commander else 1,
            _type_rank(inv),
            (inv.card.name or "").lower(),
        )

    deck_cards = sorted(deck_cards_raw, key=_sort_key)

    # Box cards for the "add cards" modal — only needed when can_edit
    box_data = []
    if can_edit:
        box_items = (
            Inventory.query
            .join(Card, Inventory.card_scryfall_id == Card.scryfall_id)
            .filter(
                Inventory.user_id == current_user.id,
                Inventory.current_deck_id.is_(None),
            )
            .order_by(Card.name.asc())
            .all()
        )
        box_data = [
            {
                "inv_id":    inv.id,
                "name":      inv.card.name,
                "set_code":  inv.card.set_code or "",
                "image":     inv.card.image_small or "",
                "quantity":  inv.quantity,
                "is_foil":   inv.is_foil,
                "condition": inv.condition.value,
            }
            for inv in box_items
        ]

    mainboard  = [i for i in deck_cards if not i.is_sideboard]
    sideboard  = [i for i in deck_cards if i.is_sideboard]
    total_qty  = sum(i.quantity for i in mainboard)
    total_value = sum(
        (i.card.price_for(i.is_foil) or 0) * i.quantity
        for i in deck_cards if not i.is_proxy
    )

    return render_template(
        "decks/detail.html",
        deck=deck,
        deck_cards=deck_cards,
        mainboard=mainboard,
        sideboard=sideboard,
        box_data=box_data,
        total_qty=total_qty,
        total_value=total_value,
        search=search,
        is_owner=is_owner,
        can_edit=can_edit,
        active_page="decks",
    )


# ── Edit deck ─────────────────────────────────────────────────────────────────

@decks_bp.route("/decks/<int:deck_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("deck.edit")
def edit_deck(deck_id):
    from app.models.deck import Deck
    from app.models.deck_share import DeckShare
    from app.forms.decks import DeckForm
    from app.utils.friends import get_friend_group_members

    # Only the owner can change metadata and sharing settings
    deck = Deck.query.filter_by(id=deck_id, user_id=current_user.id).first_or_404()
    form = DeckForm(obj=deck)
    if not form.is_submitted():
        form.bracket.data = str(deck.bracket) if deck.bracket else ""

    if form.validate_on_submit():
        deck.name                  = form.name.data.strip()
        deck.description           = form.description.data.strip() or None
        deck.format                = form.format.data
        deck.is_visible_to_friends = form.is_visible_to_friends.data
        raw_bracket = form.bracket.data
        deck.bracket = int(raw_bracket) if raw_bracket else None

        # ── Update sharing ────────────────────────────────────────────────────
        raw_ids = request.form.getlist("share_with")
        new_share_ids = set()
        for x in raw_ids:
            try:
                uid = int(x)
                if uid != current_user.id:
                    new_share_ids.add(uid)
            except (ValueError, TypeError):
                pass

        existing_shares = {s.user_id: s for s in deck.shares.all()}

        # Remove shares no longer selected
        for uid, share in existing_shares.items():
            if uid not in new_share_ids:
                db.session.delete(share)

        # Add new shares
        for uid in new_share_ids:
            if uid not in existing_shares:
                db.session.add(DeckShare(deck_id=deck.id, user_id=uid))

        db.session.commit()
        log_audit("deck_updated", "deck", deck.id, f"Updated deck '{deck.name}'")
        from app.utils.feed_service import create_deck_post
        create_deck_post(current_user.id, deck, "deck_updated")
        db.session.commit()
        flash("Deck updated.", "success")
        return redirect(url_for("decks.detail", deck_id=deck.id))

    friends = get_friend_group_members(current_user)
    current_share_ids = deck.shared_user_ids

    return render_template(
        "decks/form.html",
        form=form,
        deck=deck,
        title=f"Edit — {deck.name}",
        friends=friends,
        current_share_ids=current_share_ids,
        active_page="decks",
    )


# ── Delete deck ───────────────────────────────────────────────────────────────

@decks_bp.route("/decks/<int:deck_id>/delete", methods=["POST"])
@login_required
@permission_required("deck.delete")
def delete_deck(deck_id):
    from app.models.deck import Deck
    from app.models.inventory import Inventory

    deck = Deck.query.filter_by(id=deck_id, user_id=current_user.id).first_or_404()
    name = deck.name

    # Return all cards to Box before deleting the deck
    Inventory.query.filter_by(current_deck_id=deck.id).update(
        {"current_deck_id": None}, synchronize_session="fetch"
    )
    db.session.delete(deck)
    db.session.commit()
    log_audit("deck_deleted", "deck", deck_id, f"Deleted deck '{name}'")
    db.session.commit()
    flash(f"Deck '{name}' deleted. All cards returned to your Box.", "success")
    return redirect(url_for("decks.index"))


# ── AJAX: set cover card ─────────────────────────────────────────────────────

@decks_bp.route("/decks/<int:deck_id>/set-cover", methods=["POST"])
@login_required
@permission_required("deck.edit")
def set_cover(deck_id):
    from app.models.deck import Deck
    deck = Deck.query.get_or_404(deck_id)
    _can_access_deck(deck, current_user)  # enforces 403 if no access
    data = request.get_json(silent=True) or {}
    deck.cover_card_scryfall_id = data.get("scryfall_id") or None
    db.session.commit()
    return jsonify(success=True)


# ── AJAX: add card from Box to deck ──────────────────────────────────────────

@decks_bp.route("/decks/<int:deck_id>/add-card", methods=["POST"])
@login_required
@permission_required("deck.edit")
def add_card(deck_id):
    from app.models.deck import Deck
    from app.models.inventory import Inventory, CardCondition

    deck = Deck.query.get_or_404(deck_id)
    _can_access_deck(deck, current_user)

    data = request.get_json(silent=True)
    if not data:
        return jsonify(error="No data provided"), 400

    inv_id = data.get("inv_id")
    try:
        qty = int(data.get("qty", 1))
        if qty < 1:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify(error="Invalid quantity"), 400

    # Must be a Box card belonging to the current user
    box_inv = Inventory.query.filter_by(
        id=inv_id,
        user_id=current_user.id,
        current_deck_id=None,
    ).first_or_404()

    if qty > box_inv.quantity:
        return jsonify(error=f"Only {box_inv.quantity} in your Box"), 400

    # Look for an existing row for this card in the deck (same foil flag, same user)
    deck_inv = Inventory.query.filter_by(
        user_id=current_user.id,
        card_scryfall_id=box_inv.card_scryfall_id,
        is_foil=box_inv.is_foil,
        current_deck_id=deck.id,
    ).first()

    if qty == box_inv.quantity:
        if deck_inv:
            deck_inv.quantity += qty
            db.session.delete(box_inv)
        else:
            box_inv.current_deck_id = deck.id
    else:
        box_inv.quantity -= qty
        if deck_inv:
            deck_inv.quantity += qty
        else:
            deck_inv = Inventory(
                user_id=current_user.id,
                card_scryfall_id=box_inv.card_scryfall_id,
                quantity=qty,
                is_foil=box_inv.is_foil,
                condition=box_inv.condition,
                current_deck_id=deck.id,
            )
            db.session.add(deck_inv)

    deck.color_identity = _compute_color_identity(deck)
    db.session.commit()
    log_audit("card_moved", "deck", deck.id,
              f"Added {qty}× {box_inv.card.name} to '{deck.name}'")
    db.session.commit()

    return jsonify(success=True, message=f"Added {qty}× {box_inv.card.name} to {deck.name}.")


# ── AJAX: return card from deck to Box ───────────────────────────────────────

@decks_bp.route("/decks/<int:deck_id>/remove-card/<int:inv_id>", methods=["POST"])
@login_required
@permission_required("deck.edit")
def remove_card(deck_id, inv_id):
    from app.models.deck import Deck
    from app.models.inventory import Inventory

    deck = Deck.query.get_or_404(deck_id)
    _can_access_deck(deck, current_user)

    # The inventory row must belong to the current user (can't remove others' cards)
    deck_inv = Inventory.query.filter_by(
        id=inv_id,
        user_id=current_user.id,
        current_deck_id=deck.id,
    ).first_or_404()

    data = request.get_json(silent=True) or {}
    try:
        qty = int(data.get("qty", deck_inv.quantity))
        if qty < 1:
            raise ValueError
    except (TypeError, ValueError):
        qty = deck_inv.quantity

    qty = min(qty, deck_inv.quantity)
    card_name = deck_inv.card.name

    box_inv = Inventory.query.filter_by(
        user_id=current_user.id,
        card_scryfall_id=deck_inv.card_scryfall_id,
        is_foil=deck_inv.is_foil,
        current_deck_id=None,
    ).first()

    if qty >= deck_inv.quantity:
        if box_inv:
            box_inv.quantity += deck_inv.quantity
            db.session.delete(deck_inv)
        else:
            deck_inv.current_deck_id = None
    else:
        deck_inv.quantity -= qty
        if box_inv:
            box_inv.quantity += qty
        else:
            new_box = Inventory(
                user_id=current_user.id,
                card_scryfall_id=deck_inv.card_scryfall_id,
                quantity=qty,
                is_foil=deck_inv.is_foil,
                condition=deck_inv.condition,
                current_deck_id=None,
            )
            db.session.add(new_box)

    deck.color_identity = _compute_color_identity(deck)
    db.session.commit()
    log_audit("card_moved", "deck", deck.id,
              f"Returned {qty}× {card_name} from '{deck.name}' to Box")
    db.session.commit()

    return jsonify(success=True, message=f"{qty}× {card_name} returned to your Box.")


# ── AJAX: move card between decks ────────────────────────────────────────────

@decks_bp.route("/decks/move-card", methods=["POST"])
@login_required
@permission_required("deck.edit")
def move_card():
    from app.models.deck import Deck
    from app.models.inventory import Inventory

    data = request.get_json(silent=True)
    if not data:
        return jsonify(error="No data"), 400

    inv_id         = data.get("inv_id")
    target_deck_id = data.get("target_deck_id")

    src_inv = Inventory.query.filter_by(
        id=inv_id, user_id=current_user.id
    ).first_or_404()

    if target_deck_id:
        target = Deck.query.get_or_404(target_deck_id)
        _can_access_deck(target, current_user)
        target_id = target.id
    else:
        target = None
        target_id = None  # move to Box

    try:
        qty = int(data.get("qty", src_inv.quantity))
        qty = max(1, min(qty, src_inv.quantity))
    except (TypeError, ValueError):
        qty = src_inv.quantity

    existing = Inventory.query.filter_by(
        user_id=current_user.id,
        card_scryfall_id=src_inv.card_scryfall_id,
        is_foil=src_inv.is_foil,
        current_deck_id=target_id,
    ).first()

    if qty >= src_inv.quantity:
        if existing:
            existing.quantity += src_inv.quantity
            db.session.delete(src_inv)
        else:
            src_inv.current_deck_id = target_id
    else:
        src_inv.quantity -= qty
        if existing:
            existing.quantity += qty
        else:
            new_inv = Inventory(
                user_id=current_user.id,
                card_scryfall_id=src_inv.card_scryfall_id,
                quantity=qty,
                is_foil=src_inv.is_foil,
                condition=src_inv.condition,
                current_deck_id=target_id,
            )
            db.session.add(new_inv)

    if src_inv.current_deck_id:
        src_deck = Deck.query.get(src_inv.current_deck_id)
        if src_deck:
            src_deck.color_identity = _compute_color_identity(src_deck)
    if target_id:
        tgt = Deck.query.get(target_id)
        if tgt:
            tgt.color_identity = _compute_color_identity(tgt)

    db.session.commit()
    dest = target.name if target_id else "Box"
    log_audit("card_moved", "inventory", inv_id,
              f"Moved {qty}× {src_inv.card.name} → {dest}")
    db.session.commit()

    return jsonify(success=True, message=f"Moved to {dest}.")


# ── Streaming import into existing deck ───────────────────────────────────────

@decks_bp.route("/decks/<int:deck_id>/import-stream", methods=["POST"])
@login_required
@permission_required("deck.edit")
def import_deck_stream(deck_id):
    """Stream-import more cards into an existing deck.

    Works for both the deck owner and users the deck is explicitly shared with.
    Each imported card belongs to the importing user (their user_id).
    """
    import json as _j
    from app.forms.decks import DeckImportForm
    from app.models.deck import Deck
    from app.utils.card_service import stream_deck_import

    form = DeckImportForm()
    if not form.validate_on_submit():
        def _err():
            yield _j.dumps({"type": "error",
                            "message": "Invalid form or CSRF token expired. Please refresh."}) + "\n"
        return Response(stream_with_context(_err()), content_type="application/x-ndjson")

    deck = Deck.query.get_or_404(deck_id)
    if not deck.can_edit_by(current_user):
        def _denied():
            yield _j.dumps({"type": "error", "message": "Permission denied."}) + "\n"
        return Response(stream_with_context(_denied()), content_type="application/x-ndjson")

    import_type = form.import_type.data
    text = (
        (form.moxfield_text.data if import_type == "moxfield" else form.decklist_text.data) or ""
    ).strip()
    is_moxfield = (import_type == "moxfield")

    if not text:
        def _empty():
            yield _j.dumps({"type": "error", "message": "No cards to import."}) + "\n"
        return Response(stream_with_context(_empty()), content_type="application/x-ndjson")

    user_id  = current_user.id
    deck_id_ = deck.id

    def _gen():
        try:
            result = yield from stream_deck_import(text, user_id, deck_id_, moxfield=is_moxfield)
            deck.color_identity = _compute_color_identity(deck)
            db.session.commit()
            log_audit(
                "cards_imported", "deck", deck.id,
                f"Imported {result.success_count} card(s) into '{deck.name}'"
            )
            db.session.commit()
            yield _j.dumps({
                "type": "done",
                "successes": result.success_count,
                "failures":  result.failure_count,
                "redirect_url": url_for("decks.detail", deck_id=deck.id),
            }) + "\n"
        except Exception as exc:
            log.exception("Streaming deck import failed")
            yield _j.dumps({"type": "error", "message": str(exc)}) + "\n"

    resp = Response(stream_with_context(_gen()), content_type="application/x-ndjson")
    resp.headers["X-Accel-Buffering"] = "no"
    return resp
