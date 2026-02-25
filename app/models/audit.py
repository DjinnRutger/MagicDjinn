from datetime import datetime, timezone
from app.extensions import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action      = db.Column(db.String(64),  nullable=False)   # login, created, updated, deleted …
    resource    = db.Column(db.String(64))                    # user, role, setting …
    resource_id = db.Column(db.Integer)
    details     = db.Column(db.Text)                          # free-form detail string
    ip_address  = db.Column(db.String(45))
    created_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.resource} uid={self.user_id}>"
