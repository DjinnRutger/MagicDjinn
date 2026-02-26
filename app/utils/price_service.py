"""
Price service — scheduled price refresh and price history utilities.

Public API:
  refresh_all_card_prices(app_context=None)
      Fetch fresh prices from Scryfall for every card in the DB,
      record history rows on change, prune old rows, notify users.

  get_price_direction(scryfall_id) -> "up" | "down" | "same" | None
      Compare the last two CardPriceHistory rows.

  get_price_history(scryfall_id, days=90) -> list[dict]
      Return {date, usd, usd_foil} dicts for the graph.
"""
import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)


# ── Direction helper ──────────────────────────────────────────────────────────

def get_price_direction(scryfall_id: str) -> str | None:
    """Compare the last 2 CardPriceHistory rows for this card.

    Returns "up", "down", "same", or None (< 2 rows exist).
    Only the non-foil USD price is used for the trend arrow.
    """
    try:
        from app.models.card_price_history import CardPriceHistory
        rows = (
            CardPriceHistory.query
            .filter_by(scryfall_id=scryfall_id)
            .order_by(CardPriceHistory.recorded_at.desc())
            .limit(2)
            .all()
        )
        if len(rows) < 2:
            return None
        newer, older = rows[0].usd, rows[1].usd
        if newer is None or older is None:
            return None
        if newer > older:
            return "up"
        if newer < older:
            return "down"
        return "same"
    except Exception:
        return None


# ── History query ─────────────────────────────────────────────────────────────

def get_price_history(scryfall_id: str, days: int = 90) -> list[dict]:
    """Return price history for the last *days* days, oldest-first.

    Each item: {"date": "YYYY-MM-DD", "usd": float|None, "usd_foil": float|None}
    """
    from app.models.card_price_history import CardPriceHistory
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        CardPriceHistory.query
        .filter(
            CardPriceHistory.scryfall_id == scryfall_id,
            CardPriceHistory.recorded_at >= cutoff,
        )
        .order_by(CardPriceHistory.recorded_at.asc())
        .all()
    )
    return [
        {
            "date":     r.recorded_at.strftime("%Y-%m-%d"),
            "usd":      r.usd,
            "usd_foil": r.usd_foil,
        }
        for r in rows
    ]


# ── Main refresh ──────────────────────────────────────────────────────────────

def refresh_all_card_prices(app=None):
    """Fetch fresh prices from Scryfall for every card in the cards table.

    - Records a CardPriceHistory row for each card (only when price changed
      from the most-recent history row, or when no history exists yet).
    - Prunes rows older than the price_history_retention_days setting.
    - Sends price-change notifications to users whose inventory contains
      a card that changed by >= price_notify_threshold %.

    Designed to run inside an APScheduler background thread.
    Pass the Flask app instance so we can push an app context.
    """
    if app is None:
        # Late import to avoid circular dependency at module load time
        from flask import current_app
        app = current_app._get_current_object()

    with app.app_context():
        try:
            _do_refresh(app)
        except Exception:
            log.exception("Price refresh failed")


def _do_refresh(app) -> tuple[int, int]:
    """Inner refresh logic — must be called from within an active app context.

    Returns (refreshed_count, history_rows_added).
    """
    import time as _time
    from app.extensions import db
    from app.models.card import Card
    from app.models.card_price_history import CardPriceHistory
    from app.utils.settings import get_setting
    from app.utils.scryfall import _get, ScryfallError

    keep_history = bool(get_setting("price_keep_history", True))
    retention    = int(get_setting("price_history_retention_days", 90))

    cards = Card.query.all()
    if not cards:
        log.info("Price refresh: no cards in DB — skipping.")
        return 0, 0

    changes: list[dict] = []
    refreshed     = 0
    history_added = 0

    for card in cards:
        try:
            data     = _get(f"https://api.scryfall.com/cards/{card.scryfall_id}")
            prices   = data.get("prices", {})
            new_usd  = _to_float(prices.get("usd"))
            new_foil = _to_float(prices.get("usd_foil"))

            # Get the most recent history row for comparison
            last = (
                CardPriceHistory.query
                .filter_by(scryfall_id=card.scryfall_id)
                .order_by(CardPriceHistory.recorded_at.desc())
                .first()
            )

            # Record a new snapshot when: no history yet OR price changed
            price_changed = (
                last is None
                or last.usd != new_usd
                or last.usd_foil != new_foil
            )

            if price_changed and keep_history:
                db.session.add(CardPriceHistory(
                    scryfall_id=card.scryfall_id,
                    usd=new_usd,
                    usd_foil=new_foil,
                ))
                history_added += 1

            # Track significant USD changes for notifications
            if last and last.usd is not None and new_usd is not None and new_usd != last.usd:
                pct = abs(new_usd - last.usd) / last.usd * 100
                changes.append({
                    "scryfall_id": card.scryfall_id,
                    "name":        card.name,
                    "old_usd":     last.usd,
                    "new_usd":     new_usd,
                    "pct":         pct,
                })

            card.usd      = new_usd
            card.usd_foil = new_foil
            refreshed += 1

        except ScryfallError:
            log.warning("Price refresh: Scryfall error for %s — skipping.", card.scryfall_id)
        except Exception:
            log.exception("Price refresh: unexpected error for %s", card.scryfall_id)

        _time.sleep(0.11)   # honour Scryfall's ≤ 10 req/s guideline

    db.session.commit()
    log.info("Price refresh: %d cards checked, %d history rows written, %d price changes.",
             refreshed, history_added, len(changes))

    # Prune old rows
    if keep_history and retention > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention)
        deleted = (
            CardPriceHistory.query
            .filter(CardPriceHistory.recorded_at < cutoff)
            .delete(synchronize_session=False)
        )
        if deleted:
            db.session.commit()
            log.info("Price history pruned: %d rows older than %d days removed.", deleted, retention)

    # Notifications
    notify_enabled   = bool(get_setting("price_notify_change", False))
    notify_threshold = float(get_setting("price_notify_threshold", 10))
    if notify_enabled and changes:
        significant = [c for c in changes if c["pct"] >= notify_threshold]
        if significant:
            _send_price_notifications(significant)

    return refreshed, history_added


def _send_price_notifications(changes: list[dict]) -> None:
    """Create one Notification per user per card per day for significant price changes."""
    from app.extensions import db
    from app.models.inventory import Inventory
    from app.models.notification import Notification
    from datetime import date

    today_str = date.today().isoformat()

    for change in changes:
        sid      = change["scryfall_id"]
        name     = change["name"]
        old_usd  = change["old_usd"]
        new_usd  = change["new_usd"]
        pct      = change["pct"]
        direction = "↑" if new_usd > old_usd else "↓"

        msg = (
            f"{direction} {name} price changed {pct:.1f}%: "
            f"${old_usd:.2f} → ${new_usd:.2f}"
        )

        # Find all users who own this card (in their Box or a deck)
        user_ids = (
            db.session.query(Inventory.user_id)
            .filter(Inventory.card_scryfall_id == sid)
            .distinct()
            .all()
        )

        for (uid,) in user_ids:
            # Deduplicate: one notification per card per day per user
            already = Notification.query.filter(
                Notification.user_id == uid,
                Notification.type == "price_change",
                Notification.message.like(f"%{name}%"),
            ).filter(
                Notification.created_at >= datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            ).first()

            if not already:
                db.session.add(Notification(
                    user_id=uid,
                    type="price_change",
                    message=msg,
                ))

    db.session.commit()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _to_float(val) -> float | None:
    """Convert Scryfall price string ('1.23', None) to float or None."""
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None
