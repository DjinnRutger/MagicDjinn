# MTG Card Database Website – Task Breakdown

This is the phased implementation plan for building your multi-user Magic: The Gathering collection & deck tracker using Flask + Python + SQLite.

Work **one phase at a time** with Claude (or any LLM/code assistant).  
After completing a phase, commit/push the changes, test thoroughly, then ask to move to the next phase.

## Phase 0: Project Setup & Core Dependencies

- [ ] Update or create `requirements.txt` with:
  - flask
  - flask-sqlalchemy
  - flask-login
  - flask-wtf
  - flask-bcrypt (or werkzeug.security)
  - requests
  - python-dotenv
  - WTForms
- [ ] Create `config.py` (or use `.env` + os.getenv) containing:
  - SECRET_KEY
  - SQLALCHEMY_DATABASE_URI = 'sqlite:///mtgvault.db'
  - Other Flask config values
- [ ] Set up app factory or `__init__.py` with:
  - Flask app
  - db = SQLAlchemy(app)
  - login_manager = LoginManager(app)
  - bcrypt = Bcrypt(app)
- [ ] Add basic user registration + login routes/templates (build on your existing template)
- [ ] Create a command or route to run `db.create_all()` and create one admin user
- [ ] Test: can register, log in, log out

## Phase 1: Database Models & Basic Admin

- [ ] Implement `models.py` with **all** classes shown in the original spec:
  - User (UserMixin)
  - FriendGroup + association table
  - Card (Scryfall cache)
  - Inventory (physical card instances)
  - Deck
- [ ] Add relationships and helper properties (e.g. `User.total_cards`, `Deck.total_value`)
- [ ] Run `db.create_all()` or set up basic Alembic migration
- [ ] Create a simple admin-only route/page showing all users (list view)

## Phase 2: Authentication, Roles & Friend Groups CRUD

- [ ] Add `@login_required` and custom `@admin_required` decorators
- [ ] Admin routes/forms:
  - Create new user
  - Create new Friend Group
  - Add/remove users to/from a Friend Group
- [ ] User profile page showing:
  - Username, email
  - List of Friend Groups they belong to
- [ ] Test: admin can manage groups, normal user sees only their own groups

## Phase 3: Scryfall Integration & Mass Import

- [ ] Create helper module `scryfall.py` with functions:
  - `get_card_data(identifier, fuzzy=False)` → returns dict or raises error
  - `get_or_create_card(session, scryfall_id_or_name)` → caches in DB
- [ ] Build import route/form:
  - Textarea for pasting decklist
  - Parser that handles common formats (quantity name (set) foil, etc.)
  - Rate-limited Scryfall calls (time.sleep(0.1))
  - Adds cards to user's Box (Inventory with deck_id=None)
- [ ] Success feedback showing imported cards + any failures

## Phase 4: Box (Collection) View & Card Management

- [ ] Route: `/box` – grid/list of user's Box cards (images, quantity badges)
- [ ] Clickable card → modal with:
  - Large image
  - Full card text, mana cost, type, oracle text
  - Edit form: quantity, foil, condition, purchase price, move to deck
  - Artwork selector (other printings of same oracle_id)
- [ ] Basic filters/search on Box page (name, color, type, etc.)

## Phase 5: Decks CRUD + Card Movement

- [ ] Routes/forms:
  - Create deck (name, description, visible_to_friends toggle)
  - Edit/delete deck
  - Deck detail page: card grid, total value, mana symbols breakdown
- [ ] Add cards to deck (only from own Box)
  - Remove from Box Inventory or reduce quantity
  - Create new Inventory row with deck_id set
- [ ] Move card between decks / back to Box

## Phase 6: Friends Sharing & Transfer Logic

- [ ] Permission helper functions:
  - `can_view_box(user, target_user)`
  - `can_transfer_from_box(actor, target_user, card_inventory)`
- [ ] "Friends Boxes" page/tab: list of group members' boxes (grid view)
- [ ] On friend's Box card: button "Take to my deck" → choose deck → transfer ownership
- [ ] Visible decks: list of friends' public decks (read-only view, no transfer)

## Phase 7: Dashboard & Visual Polish (Flying Cards)

- [ ] Dashboard shows:
  - Total cards in Box
  - Total decks
  - Total collection value
  - Number of cards across all decks
- [ ] "Community Spotlight" / rotating cards section:
  - Pull random cards from own Box + all friends' Boxes
  - CSS/JS animation: cards fly in, hover shows owner + basic info
- [ ] Use lightweight JS library or vanilla + CSS keyframes

## Phase 8: Card Detail Modal & UI Refinement

- [ ] Unified card modal used everywhere (Box, Deck, Friends view)
  - Tabs: Image, Text/Rulings, Printings, Price/History
- [ ] Responsive design (Bootstrap 5 grid + mobile tweaks)
- [ ] Dark/light mode toggle (optional but nice)
- [ ] Card hover zoom/enlarge effect

## Phase 9: Additional Core Features

- [ ] Global collection search (own + friends visible cards)
- [ ] Deck analytics: mana curve chart (Chart.js), color pie
- [ ] Deck export: plain text, Arena .txt format
- [ ] Bulk actions in Box: select multiple → move, change condition, etc.

## Phase 10: Security, Testing & Final Touches

- [ ] Comprehensive permission tests (own, friend, admin, private deck)
- [ ] CSRF protection on all forms
- [ ] Input sanitization / validation everywhere
- [ ] Rate limiting on Scryfall calls
- [ ] Final UI pass: consistent styling, loading indicators, error messages
- [ ] Write basic README.md with setup instructions

## Optional / Stretch Goals (after core is complete)

1. Nightly price refresh job (APScheduler)
2. Deck legality check (Commander, Standard, etc.)
3. Collection value history chart
4. Wishlist & tradelist sections
5. Full CSV import/export
6. Notifications when friend takes card
7. Public shareable deck links
8. User-uploaded card photos
9. Mana curve + CMC distribution
10. PWA support / offline card images
