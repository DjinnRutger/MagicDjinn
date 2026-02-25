"""
Helpers for reading/writing the settings table.
`get_setting()` is injected as a Jinja2 global so templates can call it directly.
"""
from app.models.setting import Setting
from app.extensions import db


def get_setting(key: str, default=None):
    """Return the typed value of a setting by key, or `default` if not found."""
    setting = Setting.query.filter_by(key=key).first()
    if setting is None:
        return default
    return setting.get_typed_value()


def set_setting(key: str, value) -> None:
    """Upsert a setting value."""
    setting = Setting.query.filter_by(key=key).first()
    if setting:
        setting.value = str(value)
    else:
        setting = Setting(key=key, value=str(value))
        db.session.add(setting)
    db.session.commit()


def get_all_settings() -> list:
    return Setting.query.order_by(Setting.category, Setting.key).all()


def get_settings_by_category() -> dict:
    """Return {category: [Setting, ...]} ordered dict."""
    settings = get_all_settings()
    categorized: dict = {}
    for s in settings:
        cat = s.category or "general"
        categorized.setdefault(cat, []).append(s)
    return categorized
