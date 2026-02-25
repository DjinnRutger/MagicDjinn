from datetime import datetime, timezone
from app.extensions import db

# Valid MTG formats — stored as plain string in DB
MTG_FORMATS = [
    "Commander",
    "Standard",
    "Pioneer",
    "Modern",
    "Legacy",
    "Vintage",
    "Pauper",
    "Casual",
    "Other",
]


class Deck(db.Model):
    """A named deck belonging to a user.

    Cards in a deck are Inventory rows with current_deck_id set to this deck's id.
    Inventory rows with current_deck_id=NULL are in the user's Box (collection).

    is_visible_to_friends=True allows friends in the same FriendGroup to view
    the deck (read-only). Cards can never be transferred out of a visible deck.
    """
    __tablename__ = "decks"

    id                    = db.Column(db.Integer, primary_key=True)
    user_id               = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name                  = db.Column(db.String(100), nullable=False)
    description           = db.Column(db.Text)
    format                = db.Column(db.String(30), default="Casual")
    color_identity        = db.Column(db.String(10))  # e.g. "WUBRG", computed on save
    is_visible_to_friends = db.Column(db.Boolean, default=True, nullable=False)
    cover_card_scryfall_id = db.Column(db.String(50), nullable=True)  # optional cover image
    created_at            = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at            = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ────────────────────────────────────────────────────────
    user  = db.relationship("User", back_populates="decks")
    cards = db.relationship(
        "Inventory", back_populates="deck", lazy="dynamic",
        foreign_keys="Inventory.current_deck_id",
    )

    # ── Computed properties ──────────────────────────────────────────────────
    @property
    def card_count(self) -> int:
        """Total number of individual card slots (distinct Inventory rows)."""
        return self.cards.count()

    @property
    def total_quantity(self) -> int:
        """Sum of all card quantities (e.g. 4x Lightning Bolt counts as 4)."""
        from sqlalchemy import func
        from app.models.inventory import Inventory
        result = (
            db.session.query(func.sum(Inventory.quantity))
            .filter(Inventory.current_deck_id == self.id)
            .scalar()
        )
        return result or 0

    @property
    def total_value(self) -> float:
        """Approximate deck value in USD based on current Scryfall prices."""
        total = 0.0
        for inv in self.cards:
            price = inv.card.price_for(inv.is_foil) if inv.card else None
            if price is not None:
                total += price * inv.quantity
        return round(total, 2)

    @property
    def display_value(self) -> str:
        return f"${self.total_value:.2f}"

    @property
    def cover_card_image(self) -> str | None:
        """URL of the cover card image, or None if not set / card not cached."""
        if not self.cover_card_scryfall_id:
            return None
        from app.models.card import Card
        card = Card.query.get(self.cover_card_scryfall_id)
        if card is None:
            return None
        return card.image_normal or card.image_small

    def __repr__(self) -> str:
        return f"<Deck {self.name!r} (user={self.user_id})>"
