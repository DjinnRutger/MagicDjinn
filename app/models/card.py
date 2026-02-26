from datetime import datetime, timezone
from app.extensions import db


class Card(db.Model):
    """Cached Scryfall card data.

    Each row is one specific printing (scryfall_id is unique per edition).
    Cards sharing the same oracle_id are different printings of the same card.
    Prices are refreshed periodically; last_updated tracks staleness.
    """
    __tablename__ = "cards"

    scryfall_id      = db.Column(db.String(40), primary_key=True)
    oracle_id        = db.Column(db.String(40), index=True)
    name             = db.Column(db.String(200), nullable=False, index=True)
    set_code         = db.Column(db.String(10))
    set_name         = db.Column(db.String(100))
    collector_number = db.Column(db.String(20))

    # Images (Scryfall CDN URLs — no local storage)
    image_normal     = db.Column(db.String(400))
    image_small      = db.Column(db.String(400))
    image_art_crop   = db.Column(db.String(400))

    # Prices (USD, updated periodically from Scryfall)
    usd              = db.Column(db.Float, nullable=True)
    usd_foil         = db.Column(db.Float, nullable=True)

    # Card attributes
    mana_cost        = db.Column(db.String(100))
    cmc              = db.Column(db.Float, default=0.0)
    type_line        = db.Column(db.String(200))
    oracle_text      = db.Column(db.Text)
    colors           = db.Column(db.String(20))   # e.g. "WUB", "" for colorless
    color_identity   = db.Column(db.String(20))   # includes command zone colors
    rarity           = db.Column(db.String(20))   # common/uncommon/rare/mythic
    power            = db.Column(db.String(10))   # nullable (non-creatures have none)
    toughness        = db.Column(db.String(10))
    loyalty          = db.Column(db.String(10))   # planeswalkers
    keywords         = db.Column(db.Text)         # JSON array string
    legalities       = db.Column(db.Text)         # JSON dict: format → legal/banned/etc.

    last_updated     = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ────────────────────────────────────────────────────────
    inventory_items = db.relationship(
        "Inventory", back_populates="card", lazy="dynamic"
    )
    price_history = db.relationship(
        "CardPriceHistory",
        back_populates="card",
        order_by="CardPriceHistory.recorded_at.desc()",
        lazy="dynamic",
    )

    # ── Helpers ─────────────────────────────────────────────────────────────
    @property
    def is_stale(self) -> bool:
        """True if the cached data is older than the configured threshold."""
        from app.utils.settings import get_setting
        days = int(get_setting("scryfall_cache_days", "7"))
        if not self.last_updated:
            return True
        age = datetime.now(timezone.utc) - self.last_updated.replace(tzinfo=timezone.utc)
        return age.days >= days

    @property
    def display_price(self) -> str:
        """Human-friendly price string."""
        if self.usd is not None:
            return f"${self.usd:.2f}"
        return "N/A"

    @property
    def display_price_foil(self) -> str:
        if self.usd_foil is not None:
            return f"${self.usd_foil:.2f}"
        return "N/A"

    def price_for(self, is_foil: bool = False) -> float | None:
        """Return the appropriate price based on foil status."""
        return self.usd_foil if is_foil else self.usd

    @property
    def price_direction(self) -> str | None:
        """Compare the last 2 price history rows. Returns 'up', 'down', 'same', or None."""
        from app.utils.price_service import get_price_direction
        return get_price_direction(self.scryfall_id)

    def __repr__(self) -> str:
        return f"<Card {self.name} [{self.set_code}]>"
