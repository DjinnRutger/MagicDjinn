# MagicDjinn

A local-network MTG card collection and deck tracker with social features. Track your collection, build decks, share cards with friends, and browse a live activity feed — all from a clean web interface that runs on your home server or LAN.

Built on a secure Flask foundation with full admin control over every setting, user, and permission.

---

## What It Does

- **Collection management** — Add cards manually or import via Scryfall/Moxfield. Track condition, foil, quantity, and current market price.
- **Deck builder** — Create and manage decks, move cards between your collection and decks, view mana curves and color breakdowns.
- **Friend groups** — Group up with other players on your network. Transfer or loan cards between group members.
- **Activity feed** — A shared social feed that shows collection additions, deck changes, and card transfers across your friend group.
- **Scryfall integration** — Live card search and auto-fill of card details (name, mana cost, type, art, price) from the Scryfall API.
- **Moxfield import** — Import an existing Moxfield deck list directly.
- **Notifications** — In-app notifications for friend requests, card transfers, and group activity.
- **Admin panel** — Manage users, roles, permissions, global settings, audit log, and database backups from the browser.
- **3 themes** — Light, Dark (GitHub-style), and Terminal (Fallout phosphor-green CRT). Each user picks their own.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | Flask 3.1 |
| Database ORM | Flask-SQLAlchemy 3.1 (SQLite by default) |
| Auth | Flask-Login 0.6 + argon2-cffi |
| Forms / CSRF | Flask-WTF 1.2 |
| Migrations | Flask-Migrate 4.0 |
| Rate Limiting | Flask-Limiter 3.5 |
| Security Headers | Flask-Talisman 1.1 |
| Scheduling | APScheduler 3.10 (nightly price refresh) |
| Card Data | Scryfall API (free, no key required) |
| Frontend | Bootstrap 5.3 + vanilla JS |

---

## Prerequisites

- **Python 3.11 or 3.12** — [python.org/downloads](https://www.python.org/downloads/)
- **Git** — [git-scm.com](https://git-scm.com)
- Internet access on the server machine (needed for Scryfall card lookups and Bootstrap CSS)

---

## Setup on a New Machine

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/MagicDjinn.git
cd MagicDjinn
```

### 2. Create a virtual environment

**Windows:**
```bash
python -m venv .venv
.venv\Scripts\activate
```

**Mac / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

You should see `(.venv)` at the start of your terminal prompt. If not, the venv isn't active and packages will install globally.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create your `.env` file

The `.env` file holds your secrets. It is git-ignored — create it yourself in the project root:

```env
SECRET_KEY=paste-a-generated-key-here
DATABASE_URI=sqlite:///app.db
FLASK_ENV=development
```

Generate a strong secret key with:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output and paste it as your `SECRET_KEY`. Do not use the placeholder.

### 5. Start the app

```bash
python run.py
```

On first run the app will automatically:
1. Create the SQLite database at `instance/app.db`
2. Apply all schema migrations
3. Seed default roles, permissions, settings, and an admin user

Open your browser to **http://localhost:5000**

### Default Login

| Field | Value |
|---|---|
| Username | `admin` |
| Password | `Admin@1234!` |

**Change this immediately after first login.** Click your username in the top-right corner → Change Password.

---

## Accessing From Other Devices on Your LAN

`run.py` binds to `0.0.0.0:5000` so any device on the same network can reach it without extra config.

Find your machine's local IP address:

- **Windows:** open a terminal and run `ipconfig` — look for **IPv4 Address** (e.g. `192.168.1.50`)
- **Mac:** `ifconfig | grep "inet "`
- **Linux:** `ip addr show`

Then visit `http://192.168.1.50:5000` from any phone, tablet, or other computer on the same network.

To keep it running after you close the terminal, use a process manager (see below).

---

## Running as a Persistent Server (LAN / Home Server)

The built-in Flask development server is fine for personal use on a trusted LAN. If you want the app to survive reboots or terminal closes, use one of these options:

### Option A — Windows: Run as a background process with `pythonw`

Create a `start.bat` file in the project root:

```bat
@echo off
cd /d "C:\path\to\MagicDjinn"
call .venv\Scripts\activate
start /B pythonw run.py
```

Double-click `start.bat` to start. The app runs silently in the background. To stop it, open Task Manager and end the `pythonw.exe` process.

### Option B — Windows: NSSM (Non-Sucking Service Manager)

Install [NSSM](https://nssm.cc), then in an admin terminal:

```bash
nssm install MagicDjinn "C:\path\to\MagicDjinn\.venv\Scripts\python.exe" "C:\path\to\MagicDjinn\run.py"
nssm set MagicDjinn AppDirectory "C:\path\to\MagicDjinn"
nssm start MagicDjinn
```

This installs MagicDjinn as a Windows Service that starts automatically on boot.

### Option C — Linux / Mac: systemd service

Create `/etc/systemd/system/magicdjinn.service`:

```ini
[Unit]
Description=MagicDjinn MTG Tracker
After=network.target

[Service]
User=your-username
WorkingDirectory=/path/to/MagicDjinn
EnvironmentFile=/path/to/MagicDjinn/.env
ExecStart=/path/to/MagicDjinn/.venv/bin/python run.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Then enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable magicdjinn
sudo systemctl start magicdjinn
```

Check status: `sudo systemctl status magicdjinn`

### Option D — Linux: tmux / screen (simple, no root needed)

```bash
tmux new -s magicdjinn
cd /path/to/MagicDjinn
source .venv/bin/activate
python run.py
# Press Ctrl+B then D to detach. App keeps running.
```

Reattach later with: `tmux attach -t magicdjinn`

---

## Environment Files Reference

| File | Purpose | Committed to Git? |
|---|---|---|
| `.env` | Secrets — `SECRET_KEY`, `DATABASE_URI` | **No — git-ignored** |
| `.flaskenv` | Flask CLI vars — `FLASK_APP`, `FLASK_ENV` | Yes |
| `.gitignore` | Excludes `.env`, `instance/`, `__pycache__`, `.venv` | Yes |

If you clone this repo and `.env` is missing, create it from scratch (step 4 above). Without a real `SECRET_KEY` the app will start but sessions won't be secure.

---

## Admin Panel

Accessible at `/admin` — requires an account with admin privileges.

Sections:
- **Dashboard** — active users, recent activity stats
- **Users** — create accounts, reset passwords, toggle active status, assign roles
- **Roles & Permissions** — fine-grained permission strings (e.g. `cards.import`, `decks.delete`)
- **Global Settings** — live-editable app name, logo, colors, feature flags — no code changes needed
- **Audit Log** — timestamped record of every significant action with user and IP
- **Database** — download a backup or restore from a previous one

---

## Common Tasks

**Wipe and re-seed the database (fresh start):**
```bash
# Stop the server first, then:
rm instance/app.db          # Mac/Linux
del instance\app.db         # Windows CMD
python run.py               # auto re-seeds on startup
```

**Generate a new secret key:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Open a Flask shell for debugging:**
```bash
flask shell
>>> from app.models.user import User
>>> User.query.all()
```

**Upgrade dependencies:**
```bash
pip install -r requirements.txt --upgrade
```

---

## Security Notes

- Passwords hashed with **argon2** — memory-hard, resists GPU brute-force
- **CSRF tokens** on every form via Flask-WTF
- **Rate limiting** on login — 200 requests/day, 50/hour (Flask-Limiter)
- **Flask-Talisman** adds `Content-Security-Policy`, `X-Frame-Options`, and other security headers
- Session cookies: `HttpOnly=True`, `SameSite=Lax`
- All admin routes require `is_admin=True` or `admin.full_access` permission — enforced by a `before_request` hook
- This is designed for a trusted LAN, but built as if it could be exposed to the internet one day

---

## Project Structure

```
MagicDjinn/
├── app/
│   ├── __init__.py          # App factory, blueprint registration, DB seed
│   ├── config.py            # Dev / Prod / Testing config classes
│   ├── extensions.py        # db, login_manager, csrf, limiter, migrate
│   ├── blueprints/
│   │   ├── auth.py          # /login  /logout
│   │   ├── main.py          # /dashboard  /profile  /api/set-theme
│   │   ├── admin.py         # /admin/* — users, roles, settings, audit
│   │   ├── cards.py         # /cards — search, import, card detail
│   │   ├── collection.py    # /collection — inventory management
│   │   ├── decks.py         # /decks — deck CRUD, card movement
│   │   ├── friends.py       # /friends — groups, requests, card transfers
│   │   ├── feed.py          # /feed — social activity feed
│   │   ├── notifications.py # /notifications
│   │   ├── database_mgr.py  # /admin/database — backup/restore
│   │   └── setup.py         # /setup — first-run wizard
│   ├── models/
│   │   ├── user.py          # User — auth, theme, role
│   │   ├── role.py          # Role ↔ Permission (many-to-many)
│   │   ├── permission.py    # Permission name strings
│   │   ├── setting.py       # Key/value app settings
│   │   ├── audit.py         # AuditLog
│   │   ├── card.py          # Card — Scryfall data cache
│   │   ├── inventory.py     # UserInventory — card ownership per user
│   │   ├── deck.py          # Deck + DeckCard
│   │   ├── friend_group.py  # FriendGroup + membership
│   │   ├── notification.py  # Notification
│   │   └── feed.py          # FeedEvent
│   ├── utils/
│   │   ├── scryfall.py      # Scryfall API client
│   │   ├── moxfield.py      # Moxfield import parser
│   │   ├── card_service.py  # Card lookup / upsert logic
│   │   ├── feed_service.py  # Feed event creation helpers
│   │   ├── friends.py       # Friend group helpers
│   │   ├── decorators.py    # @permission_required  @admin_required
│   │   ├── settings.py      # get_setting()
│   │   └── helpers.py       # log_audit()
│   ├── forms/               # WTForms for all blueprints
│   ├── templates/           # Jinja2 — base.html + per-blueprint subdirs
│   └── static/
│       ├── css/custom.css   # Full design system, all 3 themes
│       └── js/sidebar.js    # Sidebar + theme switcher
├── instance/                # SQLite DB lives here (git-ignored)
├── migrations/              # Flask-Migrate / Alembic migration files
├── .env                     # Your secrets — NEVER commit this
├── .flaskenv                # FLASK_APP, FLASK_ENV
├── requirements.txt
├── run.py                   # Entry point — python run.py
└── CLAUDE.md                # AI coding guidelines
```
