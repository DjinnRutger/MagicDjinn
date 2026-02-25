"""
Notifications blueprint.

GET  /api/notifications              – unread count + last 50 notifications
POST /api/notifications/mark-read   – mark all as read (history kept)
"""
from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models.notification import Notification

notif_bp = Blueprint("notifications", __name__)


@notif_bp.route("/api/notifications")
@login_required
def get_notifications():
    notifs = (
        Notification.query
        .filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )
    unread = sum(1 for n in notifs if not n.is_read)
    return jsonify({
        "unread": unread,
        "notifications": [
            {
                "id":         n.id,
                "type":       n.type,
                "message":    n.message,
                "is_read":    n.is_read,
                "created_at": n.created_at.isoformat(),
                "actor":      n.actor.username if n.actor else None,
            }
            for n in notifs
        ],
    })


@notif_bp.route("/api/notifications/mark-read", methods=["POST"])
@login_required
def mark_read():
    Notification.query.filter_by(
        user_id=current_user.id,
        is_read=False,
    ).update({"is_read": True})
    db.session.commit()
    return jsonify(success=True)
