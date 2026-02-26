"""
Cards blueprint.

Global card search across own collection + friends' boxes, Scryfall search
proxy, autocomplete, and add-to-box from search results.

URLs:
  GET  /cards/search                  – search own collection + friends' boxes
  GET  /cards/scryfall-search         – AJAX: proxy Scryfall search, returns JSON
  GET  /api/cards/autocomplete        – AJAX: autocomplete from own collection
  POST /cards/add-to-box              – AJAX: add a Scryfall card to own Box
  GET  /api/cards/<scryfall_id>/printings  – AJAX: other printings from DB cache
"""
from flask import Blueprint, render_template, request, jsonify, abort
from flask_login import login_required, current_user

from app.extensions import db
from app.utils.decorators import permission_required
from app.utils.helpers import log_audit

cards_bp = Blueprint("cards", __name__)


# ── Collection search ─────────────────────────────────────────────────────────

@cards_bp.route("/cards/search")
@login_required
@permission_required("collection.view")
def search():
    q      = request.args.get("q", "").strip()
    source = request.args.get("source", "all")   # All Cards is the default tab

    # Collection data is loaded client-side via /api/cards/my-collection

    return render_template(
        "cards/search.html",
        q=q,
        source=source,
        active_page="card_search",
    )


# ── Scryfall search proxy (AJAX) ──────────────────────────────────────────────

@cards_bp.route("/cards/scryfall-search")
@login_required
@permission_required("collection.view")
def scryfall_search_api():
    """Proxy Scryfall card search and return normalized card dicts as JSON."""
    from app.utils.scryfall import search_cards, ScryfallError

    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"cards": [], "total": 0, "has_more": False})

    try:
        cards = search_cards(q, page=1)
        subset = cards[:24]          # cap at 24 for display performance
        return jsonify({
            "cards":    subset,
            "total":    len(cards),
            "has_more": len(cards) > 24,
        })
    except ScryfallError as e:
        # Return the error as a 200 so JS can display it gracefully
        return jsonify({"error": str(e), "cards": [], "total": 0})


# ── Autocomplete (AJAX) ───────────────────────────────────────────────────────

@cards_bp.route("/api/cards/autocomplete")
@login_required
def autocomplete():
    """Return up to 8 card names from the user's own collection."""
    from app.models.card import Card
    from app.models.inventory import Inventory

    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])

    names = (
        db.session.query(Card.name)
        .join(Inventory, Inventory.card_scryfall_id == Card.scryfall_id)
        .filter(
            Inventory.user_id == current_user.id,
            Card.name.ilike(f"{q}%"),
        )
        .distinct()
        .order_by(Card.name)
        .limit(8)
        .all()
    )
    return jsonify([n[0] for n in names])


# ── Add card from Scryfall search → Box (AJAX) ────────────────────────────────

@cards_bp.route("/cards/add-to-box", methods=["POST"])
@login_required
@permission_required("collection.edit")
def add_to_box():
    """Fetch (or reuse) a cached Card and add the specified qty to the user's Box."""
    from app.models.inventory import Inventory, CardCondition
    from app.utils.card_service import get_or_create_card

    data = request.get_json(silent=True)
    if not data:
        return jsonify(error="No data provided"), 400

    scryfall_id = data.get("scryfall_id", "")
    name        = data.get("name", "")
    try:
        qty = max(1, min(int(data.get("qty", 1)), 99))
    except (TypeError, ValueError):
        qty = 1
    is_foil = bool(data.get("is_foil", False))

    if not scryfall_id and not name:
        return jsonify(error="scryfall_id or name required"), 400

    try:
        card = get_or_create_card(name=name, scryfall_id=scryfall_id)
    except Exception as exc:
        return jsonify(error=f"Could not load card: {exc}"), 400

    # Merge into an existing Box row (same card + foil flag)
    existing = Inventory.query.filter_by(
        user_id=current_user.id,
        card_scryfall_id=card.scryfall_id,
        is_foil=is_foil,
        current_deck_id=None,
    ).first()

    if existing:
        existing.quantity += qty
    else:
        db.session.add(Inventory(
            user_id=current_user.id,
            card_scryfall_id=card.scryfall_id,
            quantity=qty,
            is_foil=is_foil,
        ))

    db.session.commit()
    log_audit("collection_import", "inventory", None,
              f"Added {qty}× {card.name} via card search")
    db.session.commit()

    return jsonify(success=True, message=f"Added {qty}× {card.name} to your Box.")


# ── All printings (AJAX — edition selector) ──────────────────────────────────

@cards_bp.route("/api/cards/<scryfall_id>/all-printings")
@login_required
def all_printings(scryfall_id: str):
    """Return all Scryfall printings of a card, grouped by set, for the edition selector.

    Calls the live Scryfall API so the data is always current.
    Caches new printings into the Card table as a side-effect.
    """
    from app.models.card import Card
    from app.utils.scryfall import get_printings, ScryfallError

    base = Card.query.get(scryfall_id)
    if not base or not base.oracle_id:
        return jsonify(error="Card not found or missing oracle_id"), 404

    try:
        printings = get_printings(base.oracle_id)
    except ScryfallError as e:
        return jsonify(error=str(e)), 502

    # Group by set, newest-first (Scryfall already returns newest-first)
    sets_seen: list[dict] = []
    set_index: dict[str, int] = {}

    for p in printings:
        sc = p.get("set_code", "").upper()
        sn = p.get("set_name", sc)
        if sc not in set_index:
            set_index[sc] = len(sets_seen)
            sets_seen.append({"set_code": sc, "set_name": sn, "printings": []})
        sets_seen[set_index[sc]]["printings"].append({
            "scryfall_id":      p["scryfall_id"],
            "collector_number": p.get("collector_number", ""),
            "image_small":      p.get("image_small"),
            "frame_effects":    p.get("frame_effects", []),
            "finishes":         p.get("finishes", ["nonfoil"]),
            "usd":              p.get("usd"),
            "usd_foil":         p.get("usd_foil"),
        })

    return jsonify({"current_scryfall_id": scryfall_id, "sets": sets_seen})


# ── All Cards (AJAX — All Cards tab) ─────────────────────────────────────────

def _inv_to_dict(inv, location: str) -> dict:
    """Serialize an Inventory row to a plain dict for the All Cards API."""
    card = inv.card
    return {
        "inv_id":      inv.id,
        "name":        card.name or "",
        "image":       card.image_normal or card.image_small or "",
        "image_small": card.image_small or "",
        "set_code":    (card.set_code or "").upper(),
        "set_name":    card.set_name or "",
        "type_line":   card.type_line or "",
        "oracle_text": card.oracle_text or "",
        "mana_cost":   card.mana_cost or "",
        "rarity":      card.rarity or "",
        "scryfall_id": card.scryfall_id or "",
        "usd":         float(card.usd)      if card.usd      is not None else None,
        "usd_foil":    float(card.usd_foil) if card.usd_foil is not None else None,
        "purchase_price_usd": float(inv.purchase_price_usd) if inv.purchase_price_usd is not None else None,
        "quantity":    inv.quantity,
        "is_foil":            inv.is_foil,
        "is_proxy":           inv.is_proxy,
        "condition":          inv.condition.value if inv.condition else "NM",
        "location":           location,
        "physical_location":  inv.physical_location or "",
        "price_direction":    inv.card.price_direction,
    }


@cards_bp.route("/api/cards/all-cards")
@login_required
@permission_required("collection.view")
def all_cards_api():
    """Return all cards accessible to the current user for the All Cards tab.

    Sources:
      - User's own Box (inventory with current_deck_id=NULL)
      - Friends' Boxes
      - User's own Decks
      - Friends' visible Decks (is_visible_to_friends=True)
    """
    from app.models.inventory import Inventory
    from app.models.card import Card
    from app.models.deck import Deck
    from app.utils.friends import get_friend_group_members

    friends    = get_friend_group_members(current_user)
    friend_ids = [f.id for f in friends]
    friend_map = {f.id: f.username for f in friends}

    out = []

    # 1. User's Box
    for inv in (
        Inventory.query
        .join(Card, Inventory.card_scryfall_id == Card.scryfall_id)
        .filter(Inventory.user_id == current_user.id, Inventory.current_deck_id.is_(None))
        .order_by(Card.name.asc())
        .limit(300)
        .all()
    ):
        out.append(_inv_to_dict(inv, "Your Box"))

    # 2. Friends' Boxes
    if friend_ids:
        for inv in (
            Inventory.query
            .join(Card, Inventory.card_scryfall_id == Card.scryfall_id)
            .filter(
                Inventory.user_id.in_(friend_ids),
                Inventory.current_deck_id.is_(None),
            )
            .order_by(Card.name.asc())
            .limit(300)
            .all()
        ):
            uname = friend_map.get(inv.user_id, "Friend")
            out.append(_inv_to_dict(inv, f"{uname}'s Box"))

    # 3. User's Decks — batch-load deck names first
    user_deck_invs = (
        Inventory.query
        .join(Card, Inventory.card_scryfall_id == Card.scryfall_id)
        .filter(
            Inventory.user_id == current_user.id,
            Inventory.current_deck_id.isnot(None),
        )
        .order_by(Card.name.asc())
        .limit(300)
        .all()
    )
    deck_ids  = {inv.current_deck_id for inv in user_deck_invs if inv.current_deck_id}
    decks_map = {d.id: d.name for d in Deck.query.filter(Deck.id.in_(deck_ids)).all()} if deck_ids else {}
    for inv in user_deck_invs:
        deck_name = decks_map.get(inv.current_deck_id, "Unknown Deck")
        out.append(_inv_to_dict(inv, f"Your Deck: {deck_name}"))

    # 4. Friends' visible Decks
    if friend_ids:
        friend_deck_invs = (
            Inventory.query
            .join(Card, Inventory.card_scryfall_id == Card.scryfall_id)
            .join(Deck, Inventory.current_deck_id == Deck.id)
            .filter(
                Inventory.user_id.in_(friend_ids),
                Inventory.current_deck_id.isnot(None),
                Deck.is_visible_to_friends == True,  # noqa: E712
            )
            .order_by(Card.name.asc())
            .limit(300)
            .all()
        )
        fdeck_ids  = {inv.current_deck_id for inv in friend_deck_invs if inv.current_deck_id}
        fdecks_map = {d.id: d.name for d in Deck.query.filter(Deck.id.in_(fdeck_ids)).all()} if fdeck_ids else {}
        for inv in friend_deck_invs:
            uname     = friend_map.get(inv.user_id, "Friend")
            deck_name = fdecks_map.get(inv.current_deck_id, "Unknown Deck")
            out.append(_inv_to_dict(inv, f"{uname}'s Deck: {deck_name}"))

    return jsonify(out)


# ── My Decks list (AJAX — for "Add to Deck" picker) ──────────────────────────

@cards_bp.route("/api/cards/my-decks")
@login_required
def my_decks_api():
    """Return the current user's decks for the Add-to-Deck dropdown."""
    from app.models.deck import Deck
    decks = (
        Deck.query
        .filter_by(user_id=current_user.id)
        .order_by(Deck.name.asc())
        .all()
    )
    return jsonify([{"id": d.id, "name": d.name, "format": d.format} for d in decks])


# ── My Collection (AJAX — My Collection tab) ──────────────────────────────────

@cards_bp.route("/api/cards/my-collection")
@login_required
@permission_required("collection.view")
def my_collection_api():
    """Return all of the current user's cards (Box + every Deck) as JSON."""
    from app.models.inventory import Inventory
    from app.models.card import Card
    from app.models.deck import Deck

    rows = (
        Inventory.query
        .join(Card, Inventory.card_scryfall_id == Card.scryfall_id)
        .filter(Inventory.user_id == current_user.id)
        .order_by(Card.name.asc())
        .limit(500)
        .all()
    )

    deck_ids = {inv.current_deck_id for inv in rows if inv.current_deck_id}
    deck_map = {d.id: d.name for d in Deck.query.filter(Deck.id.in_(deck_ids)).all()} if deck_ids else {}

    result = []
    for inv in rows:
        loc = f"Deck: {deck_map.get(inv.current_deck_id, '?')}" if inv.current_deck_id else "Your Box"
        result.append(_inv_to_dict(inv, loc))
    return jsonify(result)


# ── Price history (AJAX — Chart.js modal) ────────────────────────────────────

@cards_bp.route("/api/cards/<scryfall_id>/price-history")
@login_required
def card_price_history(scryfall_id: str):
    """Return price history JSON for the Chart.js modal."""
    from app.utils.price_service import get_price_history
    days = request.args.get("days", 90, type=int)
    return jsonify(get_price_history(scryfall_id, days=days))


# ── Printings (AJAX) ──────────────────────────────────────────────────────────

@cards_bp.route("/api/cards/<scryfall_id>/printings")
@login_required
def card_printings(scryfall_id: str):
    """Return other DB-cached printings of the same oracle card."""
    from app.models.card import Card

    base = Card.query.get(scryfall_id)
    if not base or not base.oracle_id:
        return jsonify([])

    others = (
        Card.query
        .filter(
            Card.oracle_id == base.oracle_id,
            Card.scryfall_id != scryfall_id,
            Card.image_small.isnot(None),
        )
        .order_by(Card.set_name.asc())
        .all()
    )
    return jsonify([
        {
            "scryfall_id":      c.scryfall_id,
            "set_name":         c.set_name or "",
            "set_code":         (c.set_code or "").upper(),
            "collector_number": c.collector_number or "",
            "image_small":      c.image_small,
            "usd":              c.usd,
            "usd_foil":         c.usd_foil,
        }
        for c in others
    ])
