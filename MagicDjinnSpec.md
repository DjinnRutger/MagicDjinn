# Magic: The Gathering Card Database Website - Full Project Spec & Task Breakdown

**Project Name:** MTG Vault (or whatever you want to call it)  
**Goal:** A secure, polished, multi-user Flask + Python + SQLite web app for tracking personal MTG collections (Boxes) and Decks. Friends groups allow sharing Box cards (transfer ownership to your Deck). Admin has full CRUD oversight. Everything looks modern, responsive, and fun with card images everywhere.

**Current Starting Point:** You already have a basic Flask/Python/SQLite template. We will build on top of it.

**Tech Stack (add these):**
- Backend: Flask, Flask-SQLAlchemy, Flask-Login, Flask-WTF, Flask-Bcrypt (or Werkzeug), Flask-Admin (optional for quick CRUD), Requests
- Frontend: Bootstrap 5 + Tailwind CSS (or pure Bootstrap + custom), HTMX (for dynamic updates without full page reloads), Chart.js (for value/mana charts), Alpine.js or vanilla JS for card animations
- External API: Scryfall (card lookup, images, prices, rulings)
- Security: CSRF protection, secure sessions, password hashing, role-based access, input sanitization
- Optional later: Alembic for migrations, APScheduler for price updates

**Core Security Rules (non-negotiable):**
- Every endpoint checks current_user and ownership.
- Friends can ONLY see Boxes of users in the same Friend Group.
- Decks marked "visible to friends" can be viewed but NEVER modified or cards pulled.
- Admin (is_admin=True) bypasses all restrictions and sees everything.
- No raw SQL – use SQLAlchemy queries with filters.
- Rate-limit Scryfall calls (sleep 0.1s between requests).
- All forms use WTForms with validation.

## Detailed Database Schema (models.py)

```python
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Many-to-many for Friend Groups
user_friend_groups = db.Table('user_friend_groups',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('friend_group.id'), primary_key=True)
)

class FriendGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    members = db.relationship('User', secondary=user_friend_groups, backref='friend_groups')

class Card(db.Model):  # Cached Scryfall data
    scryfall_id = db.Column(db.String(40), primary_key=True)  # unique printing ID
    oracle_id = db.Column(db.String(40))
    name = db.Column(db.String(200), nullable=False)
    set_code = db.Column(db.String(10))
    collector_number = db.Column(db.String(10))
    image_normal = db.Column(db.String(300))   # Scryfall normal image URL
    image_small = db.Column(db.String(300))
    usd = db.Column(db.Float)   # non-foil price
    usd_foil = db.Column(db.Float)
    mana_cost = db.Column(db.String(50))
    cmc = db.Column(db.Float)
    type_line = db.Column(db.String(200))
    oracle_text = db.Column(db.Text)
    colors = db.Column(db.String(20))  # e.g. "WUB"
    rarity = db.Column(db.String(20))
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

class Inventory(db.Model):  # Every physical card instance
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    card_scryfall_id = db.Column(db.String(40), db.ForeignKey('card.scryfall_id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    is_foil = db.Column(db.Boolean, default=False)
    condition = db.Column(db.Enum('NM','EX','GD','LP','PL','PO'), default='NM')
    purchase_price_usd = db.Column(db.Float)
    acquired_date = db.Column(db.Date, default=datetime.utcnow().date)
    current_deck_id = db.Column(db.Integer, db.ForeignKey('deck.id'), nullable=True)  # NULL = in Box
    user = db.relationship('User', backref='inventory')
    card = db.relationship('Card')

class Deck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    is_visible_to_friends = db.Column(db.Boolean, default=False)  # False = private
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)