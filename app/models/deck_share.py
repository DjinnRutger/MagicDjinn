from app.extensions import db


class DeckShare(db.Model):
    """Tracks which users a deck has been explicitly shared with.

    A shared user can add/remove their own cards and edit card metadata
    inside the deck, but cannot change deck metadata, delete the deck,
    or modify sharing settings — those are owner-only actions.
    """
    __tablename__ = "deck_shares"

    id      = db.Column(db.Integer, primary_key=True)
    deck_id = db.Column(
        db.Integer, db.ForeignKey("decks.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    __table_args__ = (
        db.UniqueConstraint("deck_id", "user_id", name="uq_deck_share"),
    )

    deck = db.relationship("Deck", back_populates="shares")
    user = db.relationship("User")

    def __repr__(self) -> str:
        return f"<DeckShare deck={self.deck_id} user={self.user_id}>"
