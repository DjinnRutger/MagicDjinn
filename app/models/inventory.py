import enum
from datetime import datetime, timezone
from app.extensions import db


class CardCondition(enum.Enum):
    NM = "NM"   # Near Mint
    EX = "EX"   # Excellent
    GD = "GD"   # Good
    LP = "LP"   # Lightly Played
    PL = "PL"   # Played
    PO = "PO"   # Poor

    @property
    def label(self) -> str:
        labels = {
            "NM": "Near Mint",
            "EX": "Excellent",
            "GD": "Good",
            "LP": "Lightly Played",
            "PL": "Played",
            "PO": "Poor",
        }
        return labels[self.value]


class Inventory(db.Model):
    """One physical card instance (or stack of identical copies) owned by a user.

    current_deck_id = NULL  →  card is in the user's Box (unassigned collection)
    current_deck_id = <id>  →  card is slotted into that deck

    quantity tracks how many copies this row represents. Moving a card to a deck
    either adjusts quantity on an existing Inventory row or creates a new one.
    """
    __tablename__ = "inventory"

    id                 = db.Column(db.Integer, primary_key=True)
    user_id            = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    card_scryfall_id   = db.Column(
        db.String(40), db.ForeignKey("cards.scryfall_id"), nullable=False, index=True
    )
    quantity           = db.Column(db.Integer, default=1, nullable=False)
    is_foil            = db.Column(db.Boolean, default=False, nullable=False)
    condition          = db.Column(
        db.Enum(CardCondition), default=CardCondition.NM, nullable=False
    )
    purchase_price_usd = db.Column(db.Float, nullable=True)
    acquired_date      = db.Column(
        db.Date, default=lambda: datetime.now(timezone.utc).date()
    )
    notes              = db.Column(db.String(500))
    current_deck_id    = db.Column(
        db.Integer, db.ForeignKey("decks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_sideboard       = db.Column(db.Boolean, default=False, nullable=False)
    is_commander       = db.Column(db.Boolean, default=False, nullable=False)
    physical_location  = db.Column(db.String(200), nullable=True)
    is_proxy           = db.Column(db.Boolean, default=False, nullable=False)

    # ── Relationships ────────────────────────────────────────────────────────
    user = db.relationship("User", back_populates="inventory")
    card = db.relationship("Card", back_populates="inventory_items")
    deck = db.relationship(
        "Deck", back_populates="cards", foreign_keys=[current_deck_id]
    )

    # ── Helpers ─────────────────────────────────────────────────────────────
    @property
    def in_box(self) -> bool:
        """True when this card is not assigned to any deck."""
        return self.current_deck_id is None

    @property
    def current_value(self) -> float | None:
        """Current market value of this inventory row (quantity × unit price).
        Returns None for proxy cards since they have no real monetary value."""
        if self.is_proxy:
            return None
        if self.card is None:
            return None
        unit = self.card.price_for(self.is_foil)
        if unit is None:
            return None
        return round(unit * self.quantity, 2)

    @property
    def condition_label(self) -> str:
        return self.condition.label if self.condition else "Unknown"

    def __repr__(self) -> str:
        loc = f"deck={self.current_deck_id}" if self.current_deck_id else "box"
        return f"<Inventory {self.quantity}x {self.card_scryfall_id} [{loc}]>"
