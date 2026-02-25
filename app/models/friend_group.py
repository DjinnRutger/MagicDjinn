from datetime import datetime, timezone
from app.extensions import db

# Many-to-many association table: users ↔ friend_groups
user_friend_groups = db.Table(
    "user_friend_groups",
    db.Column(
        "user_id", db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "group_id", db.Integer, db.ForeignKey("friend_groups.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class FriendGroup(db.Model):
    """A named group of users who can view each other's Boxes and transfer cards.

    Groups are admin-created. Any user in the same group can:
      - View other members' Box collections
      - Transfer cards from a member's Box into their own deck

    Deck visibility (is_visible_to_friends) is a separate concept: friends can
    *view* a visible deck but never pull cards from it.
    """
    __tablename__ = "friend_groups"

    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    created_by = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # ── Relationships ────────────────────────────────────────────────────────
    members = db.relationship(
        "User",
        secondary=user_friend_groups,
        back_populates="friend_groups",
        lazy="joined",
    )
    creator = db.relationship(
        "User", foreign_keys=[created_by], backref="created_groups"
    )

    # ── Helpers ─────────────────────────────────────────────────────────────
    def has_member(self, user) -> bool:
        """Check if a user is a member of this group."""
        return any(m.id == user.id for m in self.members)

    def __repr__(self) -> str:
        return f"<FriendGroup {self.name!r} ({len(self.members)} members)>"
