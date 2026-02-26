"""
Collection (Box) blueprint.

A user's "Box" is their unassigned card collection — Inventory rows where
current_deck_id is NULL. This blueprint owns all Box CRUD operations and
the card import pipeline.

URLs:
  GET  /box                   – collection grid
  GET  /box/import            – import form
  POST /box/import            – process import
  POST /box/<id>/edit         – AJAX: update a card (quantity, foil, condition…)
  POST /box/<id>/delete       – AJAX: remove a card from Box
"""
import logging

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, abort, Response, stream_with_context,
)
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.extensions import db
from app.utils.decorators import permission_required
from app.utils.helpers import log_audit

log = logging.getLogger(__name__)
collection_bp = Blueprint("collection", __name__)


# ── Box / Collection grid ─────────────────────────────────────────────────────

@collection_bp.route("/box")
@login_required
@permission_required("collection.view")
def box():
    from app.models.inventory import Inventory
    from app.models.card import Card

    search = request.args.get("q", "").strip()
    sort   = request.args.get("sort", "name")
    foil_only = request.args.get("foil", "") == "1"

    query = (
        Inventory.query
        .join(Card, Inventory.card_scryfall_id == Card.scryfall_id)
        .filter(
            Inventory.user_id == current_user.id,
            Inventory.current_deck_id.is_(None),  # Box only
        )
    )

    if search:
        query = query.filter(
            or_(
                Card.name.ilike(f"%{search}%"),
                Card.type_line.ilike(f"%{search}%"),
            )
        )

    if foil_only:
        query = query.filter(Inventory.is_foil.is_(True))

    if sort == "value":
        query = query.order_by(Card.usd.desc().nulls_last())
    elif sort == "newest":
        query = query.order_by(Inventory.acquired_date.desc())
    elif sort == "rarity":
        # order: mythic → rare → uncommon → common → others
        from sqlalchemy import case
        rarity_order = case(
            {"mythic": 1, "rare": 2, "uncommon": 3, "common": 4},
            value=Card.rarity,
            else_=5,
        )
        query = query.order_by(rarity_order, Card.name.asc())
    else:
        query = query.order_by(Card.name.asc())

    items = query.all()

    total_qty   = sum(i.quantity for i in items)
    total_value = sum(
        (i.effective_unit_price or 0) * i.quantity
        for i in items if not i.is_proxy
    )

    # Batch-compute price directions to avoid N+1 queries
    from app.utils.price_service import get_price_direction
    price_directions = {
        inv.card.scryfall_id: get_price_direction(inv.card.scryfall_id)
        for inv in items
    }

    return render_template(
        "collection/box.html",
        items=items,
        total_qty=total_qty,
        total_value=total_value,
        search=search,
        sort=sort,
        foil_only=foil_only,
        price_directions=price_directions,
        active_page="collection",
    )


# ── Import ────────────────────────────────────────────────────────────────────

@collection_bp.route("/box/import", methods=["GET", "POST"])
@login_required
@permission_required("cards.import")
def import_cards():
    from app.forms.collection import ImportForm
    from app.utils.card_service import bulk_import_decklist

    form = ImportForm()
    result = None

    if form.validate_on_submit():
        result = bulk_import_decklist(
            form.decklist.data,
            current_user.id,
            physical_location=form.physical_location.data or "",
        )
        log_audit(
            "cards_imported",
            "inventory",
            details=f"{result.success_count} cards imported, {result.failure_count} failures",
        )
        # Feed post
        from app.utils.feed_service import create_cards_added_post
        added_cards = [r["card"] for r in result.successes if r.get("card")]
        if added_cards:
            create_cards_added_post(current_user.id, added_cards)
        db.session.commit()

        if result.failure_count == 0:
            flash(
                f"Successfully imported {result.success_count} card(s) into your Box!",
                "success",
            )
            return redirect(url_for("collection.box"))
        # Has failures — stay on page and show results

    return render_template(
        "collection/import.html",
        form=form,
        result=result,
        active_page="collection",
    )


# ── Streaming import ──────────────────────────────────────────────────────────

@collection_bp.route("/box/import-stream", methods=["POST"])
@login_required
@permission_required("cards.import")
def import_stream():
    """Streaming variant of box import — yields NDJSON progress events."""
    import json
    from app.forms.collection import ImportForm
    from app.utils.card_service import stream_box_import

    form = ImportForm()
    if not form.validate_on_submit():
        def _err():
            yield json.dumps({"type": "error",
                              "message": "Invalid form or CSRF token expired. Please refresh."}) + "\n"
        return Response(stream_with_context(_err()), content_type="application/x-ndjson")

    user_id  = current_user.id
    text     = form.decklist.data
    location = form.physical_location.data or ""

    def _gen():
        try:
            stream_result = yield from stream_box_import(text, user_id, physical_location=location)
            log_audit("cards_imported", "inventory",
                      details="Streaming import via /box/import-stream")
            # Feed post
            from app.utils.feed_service import create_cards_added_post
            added_cards = [r["card"] for r in (stream_result.successes if stream_result else []) if r.get("card")]
            if added_cards:
                create_cards_added_post(user_id, added_cards)
            db.session.commit()
        except Exception as exc:
            log.exception("Streaming box import failed")
            import json as _j
            yield _j.dumps({"type": "error", "message": str(exc)}) + "\n"

    resp = Response(stream_with_context(_gen()), content_type="application/x-ndjson")
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


# ── AJAX: edit card ───────────────────────────────────────────────────────────

@collection_bp.route("/box/<int:inv_id>/edit", methods=["POST"])
@login_required
@permission_required("collection.edit")
def edit_card(inv_id):
    from app.models.inventory import Inventory, CardCondition

    inv = Inventory.query.filter_by(id=inv_id, user_id=current_user.id).first_or_404()

    data = request.get_json(silent=True)
    if not data:
        return jsonify(error="No data provided"), 400

    # Validate quantity
    qty = data.get("quantity")
    try:
        qty = int(qty)
        if qty < 1 or qty > 99:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify(error="Quantity must be between 1 and 99"), 400

    # Validate condition
    condition_str = data.get("condition", "NM")
    try:
        condition = CardCondition[condition_str]
    except KeyError:
        return jsonify(error="Invalid condition value"), 400

    # Validate purchase price
    purchase = data.get("purchase_price_usd")
    if purchase is not None and purchase != "":
        try:
            purchase = float(purchase)
            if purchase < 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify(error="Invalid purchase price"), 400
    else:
        purchase = None

    # ── Optional: switch to a different printing ──────────────────────────────
    new_sid = data.get("card_scryfall_id")
    if new_sid and new_sid != inv.card_scryfall_id:
        from app.utils.card_service import get_or_create_card
        try:
            new_card = get_or_create_card(scryfall_id=new_sid)
        except Exception as exc:
            return jsonify(error=f"Could not load new printing: {exc}"), 400

        is_foil_new = bool(data.get("is_foil", inv.is_foil))
        # Find existing row for new printing (to merge into)
        duplicate = Inventory.query.filter(
            Inventory.id != inv.id,
            Inventory.user_id == current_user.id,
            Inventory.card_scryfall_id == new_card.scryfall_id,
            Inventory.is_foil == is_foil_new,
            Inventory.current_deck_id == inv.current_deck_id,
        ).first()

        if inv.quantity == 1:
            # Only one copy — change this row's printing (merge if duplicate exists)
            if duplicate:
                duplicate.quantity += 1
                db.session.delete(inv)
                db.session.commit()
                log_audit("card_updated", "inventory", duplicate.id,
                          f"Merged into {new_card.set_code} #{new_card.collector_number}")
                return jsonify(success=True,
                               message=f"Merged into existing {new_card.name} ({new_card.set_code}).")
            inv.card_scryfall_id = new_card.scryfall_id
            # Fall through to update other fields
        else:
            # Multiple copies — only move exactly 1 copy to the new printing
            inv.quantity -= 1
            if duplicate:
                duplicate.quantity += 1
            else:
                db.session.add(Inventory(
                    user_id=current_user.id,
                    card_scryfall_id=new_card.scryfall_id,
                    quantity=1,
                    is_foil=is_foil_new,
                    condition=inv.condition,
                    current_deck_id=inv.current_deck_id,
                ))
            # Update metadata on the original row and return early
            inv.condition          = condition
            inv.purchase_price_usd = purchase
            inv.notes              = str(data.get("notes", ""))[:500]
            db.session.commit()
            log_audit("card_updated", "inventory", inv.id,
                      f"Changed 1 of {inv.card.name} → {new_card.set_code} #{new_card.collector_number}")
            return jsonify(success=True,
                           message=f"Changed 1 copy to {new_card.name} ({new_card.set_code}). "
                                   f"{inv.quantity} original cop{'y' if inv.quantity == 1 else 'ies'} remain.")

    inv.quantity           = qty
    inv.is_foil            = bool(data.get("is_foil", False))
    inv.is_proxy           = bool(data.get("is_proxy", False))
    inv.condition          = condition
    inv.purchase_price_usd = purchase
    inv.notes              = str(data.get("notes", ""))[:500]

    # Physical location — editable on both Box and deck cards
    if "physical_location" in data:
        inv.physical_location = str(data["physical_location"] or "")[:200] or None

    # Deck-only flags (ignored when card is in the Box)
    if inv.current_deck_id is not None:
        inv.is_sideboard  = bool(data.get("is_sideboard", inv.is_sideboard))
        inv.is_commander  = bool(data.get("is_commander",  inv.is_commander))

    db.session.commit()
    log_audit("card_updated", "inventory", inv.id, f"Updated {inv.card.name}")

    return jsonify(success=True, message=f"{inv.card.name} updated.")


# ── AJAX: delete card ─────────────────────────────────────────────────────────

@collection_bp.route("/box/<int:inv_id>/delete", methods=["POST"])
@login_required
@permission_required("collection.edit")
def delete_card(inv_id):
    from app.models.inventory import Inventory

    inv = Inventory.query.filter_by(id=inv_id, user_id=current_user.id).first_or_404()
    # Only allow deleting Box items here (deck cards handled in decks blueprint)
    if not inv.in_box:
        abort(403)

    card_name = inv.card.name
    db.session.delete(inv)
    db.session.commit()
    log_audit("card_deleted", "inventory", inv_id, f"Removed {card_name} from Box")

    return jsonify(success=True, message=f"{card_name} removed from your Box.")
