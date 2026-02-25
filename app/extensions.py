"""
Flask extension singletons.
Import from here everywhere – avoids circular imports.
"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=["200 per day", "50 per hour"],
)

# Flask-Login configuration
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "warning"
login_manager.refresh_view = "auth.login"
login_manager.needs_refresh_message_category = "info"


@login_manager.user_loader
def load_user(user_id: str):
    from app.models.user import User
    return db.session.get(User, int(user_id))
