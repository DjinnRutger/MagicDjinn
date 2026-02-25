# MagicDjinn – Build Tasks & Progress Tracker

**Project:** MTG Card Collection & Deck Tracker with Social Features
**Stack:** Flask + SQLAlchemy + SQLite → Bootstrap 5 + HTMX
**API:** Scryfall (card data, images, prices)
**Starting Point:** LocalVibe admin template (auth, RBAC, settings, audit fully working)

> Work **one phase at a time**. Test thoroughly before moving on. Check off tasks as completed.

---

## What's Already Done (Template Foundation)

- [x] Flask app factory with blueprints
- [x] User model with Argon2 password hashing
- [x] Flask-Login session management
- [x] CSRF protection (Flask-WTF) on all forms
- [x] Rate limiting on auth routes (Flask-Limiter)
- [x] Role-based access control (RBAC) with fine-grained permissions
- [x] Admin panel: users, roles, permissions, settings, audit log
- [x] Dynamic settings table (key/value, configurable from admin UI)
- [x] Audit logging for all actions
- [x] 3 themes: Light, Dark, Terminal — user preference persisted to DB
- [x] Responsive layout: fixed sidebar + top navbar + Bootstrap 5
- [x] Database backup/restore (SQLite)
- [x] First-run setup wizard
- [x] Error handlers (403, 404, 500)

---

## Phase 1 — Rebrand & MTG Foundations ✅

> Update app identity and lay the groundwork. No new MTG features yet, just prep.

- [x] **1.1 Rebrand to MagicDjinn**
  - Updated `app_name` default → "MagicDjinn"
  - Updated `app_tagline` → "Your Personal MTG Vault"
  - Updated `app_icon` → `bi-stars`
  - Updated `footer_text` default
  - `_run_migrations()` auto-updates existing DBs from old LocalVibe defaults

- [x] **1.2 Add MTG dependencies to `requirements.txt`**
  - `requests==2.31.*` — Scryfall HTTP calls (installed)
  - `APScheduler==3.10.*` — nightly price refresh (installed, wired in Phase 10)

- [x] **1.3 Initialize Flask-Migrate properly**
  - `flask db init` — `migrations/` folder created
  - `flask db stamp head` — existing schema baselined (tables built by `db.create_all()`)
  - Future model changes: `flask db migrate -m "message"` then `flask db upgrade`

- [x] **1.4 Add MTG-specific permissions to seed data**
  - 8 new permissions: `collection.view/edit`, `deck.view/edit/delete`, `friends.view/manage`, `cards.import`
  - Administrator gets all 24 permissions
  - Standard User gets all MTG permissions (collection, decks, friends, import)
  - `_seed_database()` made fully idempotent (get-or-create for all permissions & roles)
  - `_run_migrations()` upserts MTG permissions to existing databases automatically

- [x] **1.5 Add MTG menu items to sidebar**
  - Dynamic `sidebar_nav()` in context processor — items appear automatically as blueprints are registered
  - Endpoints ready for: My Collection, My Decks, Friends, Card Search
  - No 404 errors when blueprints not yet built (safe url_for fallback)

---

## Phase 2 — Database Models (MTG Schema) ✅

> Add all MTG-specific models. No UI yet — just schema + migrations.

- [x] **2.1 Create `app/models/card.py`** — Scryfall card cache
  - Fields: scryfall_id (PK), oracle_id, name, set_code/name, collector_number,
    image_normal/small/art_crop, usd/usd_foil, mana_cost, cmc, type_line,
    oracle_text, colors, color_identity, rarity, power, toughness, loyalty,
    keywords (JSON), legalities (JSON), last_updated
  - Helpers: `is_stale`, `display_price`, `price_for(is_foil)`

- [x] **2.2 Create `app/models/inventory.py`** — Physical card instances
  - Fields: user_id (FK), card_scryfall_id (FK), quantity, is_foil,
    condition (CardCondition Enum), purchase_price_usd, acquired_date, notes,
    current_deck_id (FK→Deck, nullable)
  - Helpers: `in_box`, `current_value`, `condition_label`

- [x] **2.3 Create `app/models/deck.py`** — User decks
  - Fields: user_id (FK), name, description, format, color_identity,
    is_visible_to_friends, created_at, updated_at
  - Helpers: `card_count`, `total_quantity`, `total_value`, `display_value`
  - MTG_FORMATS constant exported

- [x] **2.4 Create `app/models/friend_group.py`** — Social groups
  - FriendGroup + user_friend_groups association table
  - `FriendGroup.members` ↔ `User.friend_groups` (many-to-many, both sides)
  - Helper: `has_member(user)`

- [x] **2.5 Update `app/models/__init__.py`** — all 4 new models + types exported

- [x] **2.6 Migrations** — tables created via `db.create_all()`, stamped as head
  - All 5 tables confirmed: cards, decks, inventory, friend_groups, user_friend_groups
  - User model extended: `inventory`, `decks`, `friend_groups` relationships + MTG helpers
    (`box_count`, `deck_count`, `shares_group_with`)

---

## Phase 3 — Scryfall Integration Module ✅

> Build the API wrapper. No UI yet — just the data fetching layer.

- [x] **3.1 Create `app/utils/scryfall.py`**
  - `get_card_by_name(name, fuzzy=False)` → `/cards/named`
  - `get_card_by_id(scryfall_id)` → `/cards/{id}`
  - `get_card_by_set(set_code, collector_number)` → exact printing
  - `search_cards(query, page)` → `/cards/search`
  - `get_printings(oracle_id)` → all editions of a card (for art selector)
  - `normalize_card(data)` → flattens Scryfall JSON to our Card model fields
  - Handles double-faced cards (image_uris in card_faces[0])
  - `ScryfallError` with `not_found` flag for 404 vs other errors
  - 0.1 s rate-limit sleep, 10 s timeout, shared requests.Session

- [x] **3.2 Create `app/utils/card_service.py`**
  - `ParsedLine` dataclass — structured result of one parsed line
  - `ImportResult` dataclass — success/failure lists + summary counts
  - `parse_line(raw)` — parses a single line, returns ParsedLine or None
  - `parse_decklist(text)` → `(parsed_lines, failures)`
  - `get_or_create_card(...)` — DB cache first, Scryfall fallback, auto-upsert
  - `bulk_import_decklist(text, user_id)` — full pipeline: parse → fetch → upsert inventory
    - Increments quantity on existing Box rows (no duplicate rows)
    - Fuzzy fallback when exact name fails
    - Per-line error collection — partial success supported

- [x] **3.3 Tests** (`tests/test_card_service.py`) — **34/34 passing**
  - All quantity formats: `4`, `4x`, `x4`
  - Set codes: `(LEA)`, `(LEA) 1`, `(2X2) 357`
  - Foil: `*F*`, `(foil)`, with + without set code
  - Skip lines: blank, `//`, `#`, `SB:`, `Sideboard`
  - Edge cases: no quantity, qty=0, qty≥100, extra whitespace
  - Full realistic 60-card decklist integration test

---

## Phase 4 — Card Import & Box (Collection) ✅

> First real user-facing MTG feature. Users can import cards and view their collection.

- [x] **4.1 `app/blueprints/collection.py`** — registered in `__init__.py`
  - `GET /box` — card grid with search (name/type), sort (A-Z, value, newest, rarity), foil filter
  - `GET|POST /box/import` — paste decklist, shows success/failure results inline
  - `POST /box/<id>/edit` — AJAX: update quantity, foil, condition, purchase price, notes
  - `POST /box/<id>/delete` — AJAX: remove card from Box (guard: Box-only, own cards)

- [x] **4.2 `app/forms/collection.py`**
  - `ImportForm`: textarea with format hints in placeholder

- [x] **4.3 `app/templates/collection/box.html`**
  - Responsive auto-fill grid (min 130px tiles, scales to 6+ per row on wide screens)
  - Each tile: Scryfall image, quantity badge, foil shimmer effect, name + price
  - Toolbar: live search form, sort dropdown, foil-only checkbox, live stats (count + value)
  - Empty state with CTA — different message when filtered vs truly empty
  - Hover: lift + scale animation, keyboard navigable (Enter/Space opens modal)

- [x] **4.4 `app/templates/collection/import.html`**
  - Two-column layout: textarea left, format hints + tips sidebar right
  - Submit spinner — button disabled during long Scryfall import
  - Results section: stat cards (added/failed), scrollable success list with tiny images, failure list with error reasons
  - Redirects to Box on clean import, stays on page with results if any failures

- [x] **4.5 `app/templates/components/card_modal.html`** — reusable `<dialog>`
  - Large image left, details right (mana cost, type, oracle text, prices)
  - Foil shimmer overlay on image when card is foil
  - Rarity badge with color coding (mythic=orange, rare=gold, uncommon=blue, common=grey)
  - Edit controls: quantity, condition select, foil checkbox, purchase price, notes
  - Save (AJAX + page reload) and Delete (confirm + AJAX) — both include CSRF token
  - Backdrop click closes; fully keyboard accessible

- [x] **4.6 Sidebar nav** — "My Collection" auto-appeared when blueprint was registered (Phase 1 wiring)

---

## Phase 5 — Decks CRUD & Card Movement ✅

> Users can create decks and move cards from their Box into decks.

- [x] **5.1 Create `app/blueprints/decks.py`** (register in `__init__.py`)
  - `GET /decks` — list user's decks
  - `GET|POST /decks/new` — create deck
  - `GET /decks/<id>` — deck detail: card grid + stats
  - `GET|POST /decks/<id>/edit` — edit deck metadata
  - `POST /decks/<id>/delete` — delete deck (returns cards to Box)
  - `POST /decks/<id>/add-card` — AJAX: move card from Box to deck (smart split/merge)
  - `POST /decks/<id>/remove-card/<inv_id>` — AJAX: return card to Box (merge-aware)
  - `POST /decks/move-card` — AJAX: move card between any two decks or to Box

- [x] **5.2 Create deck forms** (`app/forms/decks.py`)
  - `DeckForm`: name, description, format (select from MTG_FORMATS), is_visible_to_friends (checkbox)

- [x] **5.3 Build Decks list template** (`app/templates/decks/index.html`)
  - Responsive grid (minmax 260px): format badge, color identity pips, card count, value, date
  - "New Deck" button in page header
  - Empty state CTA

- [x] **5.4 Build Deck detail template** (`app/templates/decks/detail.html`)
  - Stats row: total qty, unique slots, est. value, last updated
  - Same card grid as Box (min 130px tiles, Scryfall images)
  - Hover overlay: card name + "← Return to Box" button (AJAX)
  - "Add Cards" button → native `<dialog>` modal with searchable Box list, qty input, confirm
  - Edit / Delete buttons in page header; format badge + color identity pips
  - Empty state with search-aware message

- [x] **5.5 Add to sidebar nav**: "My Decks" → `/decks` (auto-appears via Phase 1 wiring)

---

## Phase 6 — Friend Groups & Social Features ✅

> The social layer — admins create Friend Groups, users can see each other's boxes and transfer cards.

- [x] **6.1 Admin: Friend Group management** (extended `app/blueprints/admin.py`)
  - `GET /admin/friend-groups` — list all groups with member avatar chips
  - `GET|POST /admin/friend-groups/new` — create group
  - `GET|POST /admin/friend-groups/<id>/edit` — edit name + members
  - `POST /admin/friend-groups/<id>/delete` — delete group (cascade removes memberships)
  - Added "Friend Groups" entry to `admin_nav()` in `__init__.py`

- [x] **6.2 Friend Group templates** (`app/templates/admin/friend_groups/`)
  - `index.html` — table with member avatar chips, creator, date, edit/delete actions
  - `form.html` — checkbox member picker with live JS filter (no multi-select UX issues)

- [x] **6.3 Permission helpers** (`app/utils/friends.py`)
  - `can_view_box(viewer, target_user)` — admin bypass + group-membership check
  - `can_transfer_card(actor, inventory_item)` — Box-only + different-user + group check
  - `get_friend_group_members(user)` — deduplicated, alphabetically sorted list

- [x] **6.4 Friends blueprint** (`app/blueprints/friends.py`, registered in `__init__.py`)
  - `GET /friends` — grid of friend-group members
  - `GET /friends/<id>/box` — friend's Box with search/foil filter + Take Card hover overlay
  - `GET /friends/<id>/decks` — friend's public (visible) decks, read-only
  - `POST /friends/transfer` — AJAX: validates group membership → removes from friend's Box
    → adds to actor's deck → recomputes color identity → audit logs the transfer

- [x] **6.5 Friends templates** (`app/templates/friends/`)
  - `index.html` — avatar grid with box count + deck count + "View Box" / "Decks" buttons
  - `box.html` — card grid with "Take Card" hover overlay → transfer `<dialog>` with deck
    selector + qty input → AJAX POST to `/friends/transfer`
  - `decks.html` — read-only deck cards matching decks/index.html style

- [x] **6.6 Sidebar nav** — "Friends" → `/friends` (auto-appeared via Phase 1 wiring)

---

## Phase 7 — Dashboard & Community Spotlight ✅

> Make the dashboard fun and MTG-flavored. Show stats and flying cards.

- [x] **7.1 Update dashboard route** (`app/blueprints/main.py`)
  - MTG stats: box_qty, deck_count, collection_value (all inventory), friend_count
  - MTG activity feed: last 12 events filtered to MTG actions from user + friend group members
  - Admin system stats (total_users, active_users, roles, settings) — only passed if admin
  - Added `GET /api/spotlight-cards` endpoint (random 20 cards from user + friends, JSON)

- [x] **7.2 Dashboard template rewrite** (`app/templates/main/dashboard.html`)
  - 4 MTG stat cards: Cards in Box, Active Decks, Collection Value ($), Friends
  - Quick links row: My Box, Import Cards, New Deck, My Decks, Friends
  - Community Spotlight section: skeleton loader → 12-card auto-fill grid loaded via JS
    - Hover overlay shows card name + owner username
  - Recent Activity feed: humanized MTG events with action-specific icon + colour coding
    - Actions: collection_import, deck_created/updated/deleted, card_moved, card_transferred
    - Shows "You" for own events, actual usernames for friends
  - Admin System Overview card (collapsible, admin-only)
  - Flying cards stage element (conditional on `enable_flying_cards` setting)

- [x] **7.3 Flying cards animation** (`app/static/js/flying_cards.js`)
  - Fetches `/api/spotlight-cards` on load, builds an image pool
  - Spawns card images at random screen edges, drifts across with rotation
  - Low opacity (0.07–0.14) — atmospheric, never distracting
  - CSS `@keyframes fcFly` with CSS custom properties for per-card path/rotation
  - Respects `enable_flying_cards` admin setting (JS file only loaded when enabled)

---

## Phase 8 — Card Search & Advanced UI ✅

> Global search, better modals, responsive polish.

- [x] **8.1 Global card search page** (`app/blueprints/cards.py`, registered in `__init__.py`)
  - `GET /cards/search?q=&source=collection|scryfall` — two-tab search (own collection + friends vs Scryfall)
  - `GET /cards/scryfall-search` (AJAX) — Scryfall proxy, returns 24-card JSON with legality
  - `GET /api/cards/autocomplete?q=` — prefix-match against user's own collection (8 results)
  - `POST /cards/add-to-box` — get-or-create card from Scryfall, merge into Box inventory
  - `GET /api/cards/<scryfall_id>/printings` — other DB-cached printings of same oracle_id
  - `app/templates/cards/search.html` — tabbed search page with skeleton loaders, legality pills,
    autocomplete dropdown (keyboard-navigable), "Add to Box" with ✓ Added feedback

- [x] **8.2 Enhanced card modal** (`app/templates/components/card_modal.html`)
  - 3 tabs: **Details** (mana cost, type, oracle text) | **Printings** (lazy-loaded grid via
    `/api/cards/<id>/printings`) | **Price** (regular + foil USD)
  - Edit section (quantity, condition, foil, paid, notes) stays always-visible below tabs
  - MutationObserver resets to Details tab + clears printings cache on every modal open
  - XSS-safe attribute escaping in printings HTML builder
  - `box.html` updated: `scryfall_id` added to `data-card` dict; `dlg.dataset.scryfallId` set in
    `openCardModal`; price last-updated line populated

- [x] **8.3 Scryfall card search integration** (included in 8.1 above)
  - Scryfall tab on `/cards/search` — AJAX search, skeleton loader, legality badge pills
  - "Add to Box" per card result; button changes to "✓ Added" on success
  - Collection tab — server-side search across own collection + friend group members' boxes

- [x] **8.4 Responsive / mobile polish** (`app/static/css/custom.css`)
  - Full-screen `<dialog>` modal on ≤ 576px (100vw / 100dvh, no border-radius)
  - 44px minimum touch targets for buttons, selects, inputs, tab nav on ≤ 768px
  - `hover: none / pointer: coarse` — disables card-tile hover lift on touch devices
  - Scryfall/collection result grids: 2-column at ≤ 400px

- [x] **8.5 Loading states & empty states** (included in 8.1 and 8.2 above)
  - Skeleton loaders on Scryfall search tab (gradient-animated cards while fetching)
  - Empty states with icon + message + CTA on both collection and Scryfall tabs
  - Toast notifications for add-to-box, save, and delete actions throughout

---

## Phase 9 — Deck Analytics & Export

> Power-user features: mana curves, color pies, deck export.

- [ ] **9.1 Mana curve chart on deck detail**
  - Use Chart.js (bar chart of CMC 0–7+)
  - Data from deck's inventory → group by `card.cmc`
  - Add Chart.js to `requirements.txt` (CDN is fine)

- [ ] **9.2 Color identity / pie chart on deck detail**
  - Count cards by color
  - Chart.js doughnut chart
  - Show mana symbol icons using Scryfall SVG symbols

- [ ] **9.3 Deck export**
  - `GET /decks/<id>/export/text` → plain text: `4 Lightning Bolt`
  - `GET /decks/<id>/export/arena` → Arena format: `4 Lightning Bolt (M10) 123`
  - `GET /decks/<id>/export/csv` → CSV with all inventory metadata

- [ ] **9.4 Deck legality check**
  - Pull format legalities from Scryfall card data
  - Store `legalities` JSON field on Card model (add migration)
  - Deck detail shows "Legal / Not Legal / Banned" badge per format

- [ ] **9.5 Bulk Box actions**
  - Multi-select checkboxes on Box grid
  - Bulk actions: Move to Deck, Change Condition, Delete
  - Select-all / deselect-all

---

## Phase 10 — Price Refresh & Nightly Jobs

> Keep prices fresh automatically.

- [ ] **10.1 Wire APScheduler for nightly price updates**
  - Create `app/utils/scheduler.py`
  - Job: fetch updated prices for all Cards in DB where `last_updated < 24h ago`
  - Rate-limited: 0.1s between requests
  - Log results to AuditLog (cards updated / errors)
  - Admin setting: `enable_price_refresh` (toggle on/off)
  - Admin setting: `price_refresh_hour` (default: 3 AM)

- [ ] **10.2 Price history tracking** (stretch)
  - New model: `PriceHistory(card_scryfall_id, usd, usd_foil, recorded_at)`
  - Migration to add table
  - Chart on card detail Price tab showing 30-day history
  - Admin setting: `enable_price_history` (storage consideration)

- [ ] **10.3 "Stale price" indicator**
  - Show warning badge on card if `last_updated > 7 days`
  - Admin panel stat: "X cards with stale prices" + refresh button

---

## Phase 11 — Security Hardening & Testing

> Final review before calling it production-ready.

- [ ] **11.1 Comprehensive permission audit**
  - Every route: verify `@login_required` + appropriate permission check
  - Box routes: only owner or admin can edit/delete
  - Deck routes: only owner can edit; friends can view if `is_visible_to_friends`
  - Transfer: strict validation (same group, qty > 0, target deck belongs to actor)
  - Friend box view: strict group membership check, no cross-group leakage

- [ ] **11.2 Input sanitization pass**
  - All free-text fields: strip HTML, enforce max length
  - Decklist import: sanitize each line before processing
  - Deck descriptions: allow safe markdown or strip all HTML
  - Card name search queries: escaped before SQL/API call

- [ ] **11.3 Rate limiting review**
  - Scryfall proxy endpoints: limit to 60/min per user
  - Import endpoint: limit to 5/min per user (prevent abuse)
  - Card search: limit to 30/min per user

- [ ] **11.4 CSRF verification pass**
  - All state-changing routes are POST with CSRF token
  - HTMX requests include CSRF header (verify in JS)
  - API endpoints that modify data require CSRF or API key

- [ ] **11.5 Write tests** (`tests/`)
  - `test_auth.py` — login, logout, rate limiting, bad password
  - `test_permissions.py` — friend group isolation, own-only access, admin bypass
  - `test_collection.py` — import parsing, add/remove cards
  - `test_transfer.py` — valid transfer, invalid group, zero quantity edge cases
  - `test_scryfall.py` — mock API responses, cache behavior, error handling

- [ ] **11.6 Final UI pass**
  - Consistent button styles, spacing, typography
  - Dark mode: verify all MTG pages look good in dark/terminal themes
  - Loading indicators on all async operations
  - Error messages: clear and actionable
  - Audit all flash message copy for tone (helpful, not scary)

---

## Stretch Goals (after core complete)

- [ ] **S1** — Wishlist & tradelist sections per user
- [ ] **S2** — Notifications when a friend takes a card from your Box
- [ ] **S3** — Public shareable deck links (no login required to view)
- [ ] **S4** — Full CSV import/export for entire collection
- [ ] **S5** — User-uploadable card condition photos
- [ ] **S6** — PWA support (offline card images cached in service worker)
- [ ] **S7** — OAuth login (Discord? — good for MTG friend groups)
- [ ] **S8** — Collection value history chart (30/90/365 day)
- [ ] **S9** — Commander bracket / power level rating per deck
- [ ] **S10** — Printable proxy sheets for playtesting

---

## Current Focus

**→ Phase 7 complete. Next: Phase 8** (Card Search & Advanced UI)

---

## Notes & Decisions

| Decision | Choice | Reason |
|---|---|---|
| Card image hosting | Use Scryfall CDN URLs directly | No storage cost, always current |
| Price data source | Scryfall `prices` field | Free, no API key needed |
| Format validation | Scryfall legalities field | Authoritative source |
| Decklist format | Support 4 common formats | Most MTG tools use these |
| Friend groups | Admin-created only | Keeps social layer controlled |
| Transfer flow | Reduce qty → move to deck | Preserves card history |
| Dark mode | Already working via template | Just need MTG page polish |
| HTMX usage | Modals, search autocomplete | No full-page reloads for card ops |
