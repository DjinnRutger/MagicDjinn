# Import all models so SQLAlchemy can discover them for db.create_all()
# Order matters: association tables and FK targets must be imported before dependents.
from app.models.permission import Permission
from app.models.role import Role, role_permissions
from app.models.user import User
from app.models.setting import Setting
from app.models.audit import AuditLog

# MTG models — import Card before Inventory (FK dependency)
from app.models.card import Card
from app.models.deck import Deck, MTG_FORMATS
from app.models.inventory import Inventory, CardCondition
from app.models.friend_group import FriendGroup, user_friend_groups
from app.models.deck_share import DeckShare
from app.models.notification import Notification
from app.models.feed import FeedPost, FeedLike, FeedComment
from app.models.card_price_history import CardPriceHistory

__all__ = [
    "Permission", "Role", "role_permissions",
    "User", "Setting", "AuditLog",
    "Card",
    "Deck", "MTG_FORMATS",
    "Inventory", "CardCondition",
    "FriendGroup", "user_friend_groups",
    "DeckShare",
    "Notification",
    "FeedPost", "FeedLike", "FeedComment",
    "CardPriceHistory",
]
