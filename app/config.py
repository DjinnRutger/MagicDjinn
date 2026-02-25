"""
App configuration classes.
Load from .env → fall back to safe defaults.
"""
import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

# Compute absolute path to the project-root instance/ folder so SQLite always works
_HERE         = os.path.dirname(os.path.abspath(__file__))   # …/app/
_PROJECT_ROOT = os.path.dirname(_HERE)                        # …/D1-Test/
_INSTANCE_DIR = os.path.join(_PROJECT_ROOT, "instance")
_DEFAULT_DB   = "sqlite:///" + os.path.join(_INSTANCE_DIR, "app.db").replace("\\", "/")


class Config:
    # ── Core ────────────────────────────────────────────────────────────────
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-CHANGE-ME")
    SQLALCHEMY_DATABASE_URI: str = os.environ.get("DATABASE_URI", _DEFAULT_DB)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── Session / Cookies ───────────────────────────────────────────────────
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False          # override True in ProductionConfig
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_DURATION = timedelta(days=14)

    # ── CSRF ────────────────────────────────────────────────────────────────
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600            # 1 hour

    # ── Rate Limiting ───────────────────────────────────────────────────────
    RATELIMIT_STORAGE_URI = "memory://"
    RATELIMIT_DEFAULT = ["200 per day", "50 per hour"]

    # ── Talisman (security headers) ─────────────────────────────────────────
    TALISMAN_ENABLED = True
    TALISMAN_CONFIG: dict = {
        "force_https": False,                    # LAN app – no HTTPS initially
        "strict_transport_security": False,
        "content_security_policy": {
            "default-src": "'self'",
            "script-src":  ["'self'", "'unsafe-inline'", "cdn.jsdelivr.net"],
            "style-src":   ["'self'", "'unsafe-inline'", "cdn.jsdelivr.net"],
            "font-src":    ["'self'", "cdn.jsdelivr.net", "fonts.gstatic.com"],
            "img-src":     ["'self'", "data:", "https:"],
        },
        "referrer_policy": "strict-origin-when-cross-origin",
    }


class DevelopmentConfig(Config):
    DEBUG = True
    TALISMAN_ENABLED = False               # no header friction while building
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    TALISMAN_ENABLED = True


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    TALISMAN_ENABLED = False
    RATELIMIT_ENABLED = False


config: dict = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
    "testing":     TestingConfig,
    "default":     DevelopmentConfig,
}
