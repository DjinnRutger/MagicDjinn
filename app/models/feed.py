"""Social feed models — FeedPost, FeedLike, FeedComment."""
from datetime import datetime
from app.extensions import db


class FeedPost(db.Model):
    __tablename__ = "feed_posts"

    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    post_type        = db.Column(db.String(30), nullable=False)   # card_added | deck_created | deck_updated
    body             = db.Column(db.String(500), nullable=False)  # human-readable summary
    card_scryfall_id = db.Column(db.String(50),  db.ForeignKey("cards.scryfall_id", ondelete="SET NULL"), nullable=True)
    deck_id          = db.Column(db.Integer,     db.ForeignKey("decks.id",    ondelete="SET NULL"), nullable=True)
    extra_data       = db.Column(db.Text, nullable=True)          # JSON
    created_at       = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    author   = db.relationship("User",  foreign_keys=[user_id])
    card     = db.relationship("Card",  foreign_keys=[card_scryfall_id])
    deck     = db.relationship("Deck",  foreign_keys=[deck_id])
    likes    = db.relationship("FeedLike",    back_populates="post", cascade="all, delete-orphan")
    comments = db.relationship("FeedComment", back_populates="post", cascade="all, delete-orphan",
                               order_by="FeedComment.created_at")


class FeedLike(db.Model):
    __tablename__ = "feed_likes"
    __table_args__ = (db.UniqueConstraint("post_id", "user_id"),)

    id      = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("feed_posts.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id",      ondelete="CASCADE"), nullable=False)

    post = db.relationship("FeedPost", back_populates="likes")


class FeedComment(db.Model):
    __tablename__ = "feed_comments"

    id         = db.Column(db.Integer, primary_key=True)
    post_id    = db.Column(db.Integer, db.ForeignKey("feed_posts.id", ondelete="CASCADE"), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id",      ondelete="CASCADE"), nullable=False)
    body       = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    post   = db.relationship("FeedPost", back_populates="comments")
    author = db.relationship("User", foreign_keys=[user_id])
