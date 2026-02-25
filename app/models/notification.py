"""
Notification model.

Stores per-user notifications for social card events (card taken from your
Box, card returned to your Box, etc.).  is_read is set to True when the user
opens the notification panel, but rows are kept indefinitely for history.
"""
from datetime import datetime
from app.extensions import db


class Notification(db.Model):
    __tablename__ = "notifications"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)   # recipient
    actor_id   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)    # who acted
    type       = db.Column(db.String(50),  nullable=False)   # e.g. 'card_taken'
    message    = db.Column(db.String(500), nullable=False)
    is_read    = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user  = db.relationship("User", foreign_keys=[user_id], backref="notifications")
    actor = db.relationship("User", foreign_keys=[actor_id], lazy="select")
