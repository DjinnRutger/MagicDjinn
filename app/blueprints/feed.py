"""
Social feed blueprint.

GET  /api/feed                         – paginated feed (20 per page)
POST /api/feed/<id>/like               – toggle like on a post
POST /api/feed/<id>/comment            – add a comment
DELETE /api/feed/comment/<id>          – delete own comment
"""
import json
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from app.extensions import db

feed_bp = Blueprint("feed", __name__)

# ── helpers ───────────────────────────────────────────────────────────────────

def _friend_ids():
    """Return set of user_ids that share a FriendGroup with current_user."""
    from app.utils.friends import get_friend_group_members
    return {m.id for m in get_friend_group_members(current_user)}


def _relative_time(dt: datetime) -> str:
    diff = datetime.utcnow() - dt
    s    = int(diff.total_seconds())
    if s < 60:      return "just now"
    if s < 3600:    return f"{s // 60}m ago"
    if s < 86400:   return f"{s // 3600}h ago"
    if s < 604800:  return f"{s // 86400}d ago"
    return dt.strftime("%b %d")


def _serialize_post(post, liked_set: set, friend_ids: set) -> dict:
    author = post.author
    try:
        extra = json.loads(post.extra_data or "{}")
    except (ValueError, TypeError):
        extra = {}

    # Build card list for card_added posts
    cards_preview = []
    if post.post_type == "card_added":
        raw_cards = extra.get("cards", [])[:5]
        total     = extra.get("total", len(raw_cards))
        # Hydrate full card data from DB so both old (sparse) and new posts
        # return all fields needed for the detail popup.
        from app.models.card import Card as CardModel
        sids = [c.get("scryfall_id") for c in raw_cards if c.get("scryfall_id")]
        card_map = {}
        if sids:
            card_map = {
                c.scryfall_id: c
                for c in CardModel.query.filter(CardModel.scryfall_id.in_(sids)).all()
            }
        for ec in raw_cards:
            sid  = ec.get("scryfall_id")
            db_c = card_map.get(sid)
            if db_c:
                cards_preview.append({
                    "scryfall_id":  db_c.scryfall_id,
                    "name":         db_c.name,
                    "image_small":  db_c.image_small  or "",
                    "image_normal": db_c.image_normal or "",
                    "type_line":    db_c.type_line    or "",
                    "mana_cost":    db_c.mana_cost    or "",
                    "oracle_text":  db_c.oracle_text  or "",
                    "rarity":       db_c.rarity       or "",
                    "set_code":     (db_c.set_code or "").upper(),
                    "set_name":     db_c.set_name     or "",
                    "usd":          float(db_c.usd)      if db_c.usd      is not None else None,
                    "usd_foil":     float(db_c.usd_foil) if db_c.usd_foil is not None else None,
                })
            else:
                cards_preview.append(ec)
    else:
        total = 0

    # Deck info for deck posts
    deck_info = None
    if post.post_type in ("deck_created", "deck_updated") and post.deck_id:
        deck_info = {
            "id":             post.deck_id,
            "name":           extra.get("deck_name", ""),
            "format":         extra.get("format", ""),
            "color_identity": extra.get("color_identity", ""),
            "total_quantity": extra.get("total_quantity", 0),
            "cover_image":    extra.get("cover_image"),
        }

    return {
        "id":            post.id,
        "post_type":     post.post_type,
        "body":          post.body,
        "created_at":    post.created_at.isoformat(),
        "relative_time": _relative_time(post.created_at),
        "author": {
            "id":         author.id,
            "username":   author.username,
            "initials":   author.get_initials(),
            "avatar":     author.avatar_art_crop,
        },
        "cards_preview": cards_preview,
        "cards_total":   total,
        "deck":          deck_info,
        "like_count":    len(post.likes),
        "liked_by_me":   post.id in liked_set,
        "comment_count": len(post.comments),
        "comments": [
            {
                "id":            c.id,
                "body":          c.body,
                "created_at":    c.created_at.isoformat(),
                "relative_time": _relative_time(c.created_at),
                "author": {
                    "id":       c.author.id,
                    "username": c.author.username,
                    "initials": c.author.get_initials(),
                    "avatar":   c.author.avatar_art_crop,
                },
                "is_mine": c.user_id == current_user.id,
            }
            for c in post.comments
        ],
        "is_mine": post.user_id == current_user.id,
    }


# ── Feed endpoint ─────────────────────────────────────────────────────────────

@feed_bp.route("/api/feed")
@login_required
def get_feed():
    from app.models.feed import FeedPost, FeedLike

    page     = max(1, int(request.args.get("page", 1)))
    per_page = 15
    fids     = _friend_ids()
    visible  = list(fids | {current_user.id})

    posts = (
        FeedPost.query
        .filter(FeedPost.user_id.in_(visible))
        .order_by(FeedPost.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page + 1)
        .all()
    )
    has_more = len(posts) > per_page
    posts    = posts[:per_page]

    liked_set = {
        like.post_id
        for like in FeedLike.query.filter(
            FeedLike.user_id == current_user.id,
            FeedLike.post_id.in_([p.id for p in posts]),
        ).all()
    }

    return jsonify({
        "posts":    [_serialize_post(p, liked_set, fids) for p in posts],
        "has_more": has_more,
        "page":     page,
    })


# ── Like toggle ───────────────────────────────────────────────────────────────

@feed_bp.route("/api/feed/<int:post_id>/like", methods=["POST"])
@login_required
def toggle_like(post_id):
    from app.models.feed import FeedPost, FeedLike

    post = FeedPost.query.get_or_404(post_id)

    # Privacy check
    fids = _friend_ids()
    if post.user_id not in (fids | {current_user.id}):
        return jsonify(error="Not found"), 404

    existing = FeedLike.query.filter_by(post_id=post_id, user_id=current_user.id).first()
    if existing:
        db.session.delete(existing)
        liked = False
    else:
        db.session.add(FeedLike(post_id=post_id, user_id=current_user.id))
        liked = True
    db.session.commit()

    count = FeedLike.query.filter_by(post_id=post_id).count()
    return jsonify(success=True, liked=liked, like_count=count)


# ── Comment CRUD ──────────────────────────────────────────────────────────────

@feed_bp.route("/api/feed/<int:post_id>/comment", methods=["POST"])
@login_required
def add_comment(post_id):
    from app.models.feed import FeedPost, FeedComment

    post = FeedPost.query.get_or_404(post_id)
    fids = _friend_ids()
    if post.user_id not in (fids | {current_user.id}):
        return jsonify(error="Not found"), 404

    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()[:500]
    if not body:
        return jsonify(error="Comment cannot be empty"), 400

    comment = FeedComment(post_id=post_id, user_id=current_user.id, body=body)
    db.session.add(comment)
    db.session.commit()

    return jsonify(success=True, comment={
        "id":            comment.id,
        "body":          comment.body,
        "relative_time": "just now",
        "author": {
            "id":       current_user.id,
            "username": current_user.username,
            "initials": current_user.get_initials(),
            "avatar":   current_user.avatar_art_crop,
        },
        "is_mine": True,
    })


@feed_bp.route("/api/feed/comment/<int:comment_id>", methods=["DELETE"])
@login_required
def delete_comment(comment_id):
    from app.models.feed import FeedComment

    comment = FeedComment.query.get_or_404(comment_id)
    if comment.user_id != current_user.id:
        return jsonify(error="Forbidden"), 403
    db.session.delete(comment)
    db.session.commit()
    return jsonify(success=True)
