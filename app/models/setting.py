import json
from app.extensions import db


class Setting(db.Model):
    __tablename__ = "settings"

    id          = db.Column(db.Integer, primary_key=True)
    key         = db.Column(db.String(128), unique=True, nullable=False, index=True)
    value       = db.Column(db.Text)
    # text | number | boolean | select | json | color
    type        = db.Column(db.String(32), default="text", nullable=False)
    description = db.Column(db.String(255))
    category    = db.Column(db.String(64), default="general", index=True)
    options     = db.Column(db.Text)   # JSON array string for select type

    def get_typed_value(self):
        """Return value cast to its declared type."""
        if self.type == "boolean":
            return str(self.value).lower() in ("true", "1", "yes")
        if self.type == "number":
            try:
                return int(self.value)
            except (ValueError, TypeError):
                try:
                    return float(self.value)
                except (ValueError, TypeError):
                    return 0
        if self.type == "json":
            try:
                return json.loads(self.value)
            except (json.JSONDecodeError, TypeError):
                return {}
        return self.value

    def get_options_list(self) -> list:
        if self.options:
            try:
                return json.loads(self.options)
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    def __repr__(self) -> str:
        return f"<Setting {self.key}={self.value!r}>"
