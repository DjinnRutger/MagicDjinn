from app.extensions import db


class Permission(db.Model):
    __tablename__ = "permissions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)   # e.g. 'users.create'
    description = db.Column(db.String(255))

    def __repr__(self) -> str:
        return f"<Permission {self.name}>"
