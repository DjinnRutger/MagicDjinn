"""
CardPriceHistory model.

Tracks USD price snapshots for each card printing over time.
A new row is recorded each time the price refresh job runs and
the price has changed (or on the very first fetch for a card).
"""
from datetime import datetime, timezone
from app.extensions import db


class CardPriceHistory(db.Model):
    __tablename__ = "card_price_history"

    id          = db.Column(db.Integer, primary_key=True)
    scryfall_id = db.Column(
        db.String(40),
        db.ForeignKey("cards.scryfall_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    usd         = db.Column(db.Float, nullable=True)
    usd_foil    = db.Column(db.Float, nullable=True)
    recorded_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    card = db.relationship("Card", back_populates="price_history")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CardPriceHistory {self.scryfall_id} @{self.recorded_at}>"
