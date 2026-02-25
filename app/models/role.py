from datetime import datetime, timezone
from app.extensions import db

# Many-to-many join table
role_permissions = db.Table(
    "role_permissions",
    db.Column("role_id",       db.Integer, db.ForeignKey("roles.id"),       primary_key=True),
    db.Column("permission_id", db.Integer, db.ForeignKey("permissions.id"), primary_key=True),
)


class Role(db.Model):
    __tablename__ = "roles"

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.String(255))
    created_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    permissions = db.relationship(
        "Permission",
        secondary=role_permissions,
        backref=db.backref("roles", lazy="dynamic"),
        lazy="joined",
    )
    users = db.relationship("User", backref="role", lazy="dynamic")

    def has_permission(self, perm_name: str) -> bool:
        return any(p.name == perm_name for p in self.permissions)

    def __repr__(self) -> str:
        return f"<Role {self.name}>"
