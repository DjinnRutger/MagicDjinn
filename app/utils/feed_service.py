"""
Feed service — helpers that create FeedPost rows from application events.

All functions add to the current db.session but do NOT commit.
Caller is responsible for committing.
"""
import json
from datetime import datetime, timedelta

from app.extensions import db


def create_cards_added_post(user_id: int, cards: list) -> None:
    """
    Create (or extend) a feed post summarising cards added to a user's Box.
    'cards' is a list of Card ORM objects.

    If a card_added post for this user already exists within the last 2 minutes,
    merge the new cards into that post's extra_data instead of creating a new one.
    """
    if not cards:
        return
    from app.models.feed import FeedPost

    cutoff  = datetime.utcnow() - timedelta(minutes=2)
    existing = (
        FeedPost.query
        .filter(
            FeedPost.user_id   == user_id,
            FeedPost.post_type == "card_added",
            FeedPost.created_at >= cutoff,
        )
        .order_by(FeedPost.created_at.desc())
        .first()
    )

    new_entries = [
        {
            "scryfall_id":  c.scryfall_id,
            "name":         c.name,
            "image_small":  c.image_small  or "",
            "image_normal": c.image_normal or "",
            "type_line":    c.type_line    or "",
            "mana_cost":    c.mana_cost    or "",
            "oracle_text":  c.oracle_text  or "",
            "rarity":       c.rarity       or "",
            "usd":          float(c.usd)      if c.usd      is not None else None,
            "usd_foil":     float(c.usd_foil) if c.usd_foil is not None else None,
        }
        for c in cards
    ]

    if existing:
        try:
            data = json.loads(existing.extra_data or "{}")
        except (ValueError, TypeError):
            data = {}
        all_cards = data.get("cards", []) + new_entries
        # De-duplicate by scryfall_id, keep order
        seen = set()
        deduped = []
        for e in all_cards:
            if e["scryfall_id"] not in seen:
                seen.add(e["scryfall_id"])
                deduped.append(e)
        total = data.get("total", 0) + len(cards)
        data.update({"cards": deduped[:10], "total": total})
        existing.extra_data = json.dumps(data)
        n = total
        existing.body = f"added {n} card{'s' if n != 1 else ''} to their Box"
        existing.card_scryfall_id = deduped[0]["scryfall_id"] if deduped else None
    else:
        total = len(cards)
        extra = {
            "cards": new_entries[:10],
            "total": total,
        }
        post = FeedPost(
            user_id          = user_id,
            post_type        = "card_added",
            body             = f"added {total} card{'s' if total != 1 else ''} to their Box",
            card_scryfall_id = cards[0].scryfall_id,
            extra_data       = json.dumps(extra),
        )
        db.session.add(post)


def create_deck_post(user_id: int, deck, post_type: str = "deck_created") -> None:
    """
    Create a feed post for deck_created or deck_updated.
    Always creates a post — the creator always sees their own deck activity.
    Friends only see the post if they share a friend group with the creator
    (controlled by the feed query, not by is_visible_to_friends here).
    For deck_updated: replaces any existing update post for the same deck in the last hour.
    """
    from app.models.feed import FeedPost

    extra = {
        "deck_name":      deck.name,
        "format":         deck.format or "Casual",
        "color_identity": deck.color_identity or "",
        "total_quantity": deck.total_quantity,
        "cover_image":    deck.cover_card_image,
    }

    if post_type == "deck_updated":
        cutoff = datetime.utcnow() - timedelta(hours=1)
        existing = (
            FeedPost.query
            .filter(
                FeedPost.user_id   == user_id,
                FeedPost.post_type == "deck_updated",
                FeedPost.deck_id   == deck.id,
                FeedPost.created_at >= cutoff,
            )
            .first()
        )
        if existing:
            existing.extra_data = json.dumps(extra)
            existing.body       = f"updated their deck: {deck.name}"
            existing.created_at = datetime.utcnow()   # bump to top of feed
            return

    body = f"created a new deck: {deck.name}" if post_type == "deck_created" else f"updated their deck: {deck.name}"

    post = FeedPost(
        user_id    = user_id,
        post_type  = post_type,
        body       = body,
        deck_id    = deck.id,
        extra_data = json.dumps(extra),
    )
    db.session.add(post)
