# LocalVibe

A clean, professional, fully configurable internal web app built with Flask. Designed to run on a local network (LAN) as a ready-to-go starting point for internal tools, dashboards, and admin panels. Everything is configurable from the admin panel — no hardcoded strings, no magic numbers.

---

## What You Get Out of the Box

- **Authentication** — login/logout, remember me, argon2 password hashing, rate limiting on login
- **Role-Based Access Control (RBAC)** — roles with fine-grained permission strings (`users.create`, `settings.edit`, etc.)
- **Admin Panel** — manage users, roles, permissions, and global app settings from the browser
- **Audit Log** — every important action is recorded with timestamp, user, and IP address
- **3 Themes** — Light, Dark (GitHub-style), and Terminal (Fallout phosphor-green CRT). Users pick their theme from the account popup in the top-right corner; preference persists across sessions
- **Responsive sidebar** — collapsible on desktop (icon-only mode), slide-in on mobile
- **Global Settings** — key/value settings table drives the app name, logo icon, colors, tagline, and more — all editable live from `/admin/settings`
- **Zero CDN dependency for JS** — all interactive UI (sidebar, modal, theme switching) uses plain JavaScript so it works on a local network without internet

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
| Security Headers | Flask-Talisman 1.1 (disabled in dev, enabled in prod) |
| Frontend | Bootstrap 5.3 CSS + custom CSS + vanilla JS |
| Fonts | Inter (body), VT323 (terminal theme) via Google Fonts |

---

## Project Structure

```
D1-Test/
├── app/
│   ├── __init__.py          # App factory, blueprint registration, DB seed & migrations
│   ├── config.py            # Dev / Prod / Testing config classes
│   ├── extensions.py        # db, login_manager, csrf, limiter, migrate
│   ├── blueprints/
│   │   ├── auth.py          # /login  /logout
│   │   ├── main.py          # /dashboard  /profile  /api/set-theme  /api/change-password
│   │   └── admin.py         # /admin/*  — users, roles, settings, audit
│   ├── models/
│   │   ├── user.py          # User — username, email, password, theme, role_id
│   │   ├── role.py          # Role ↔ Permission (many-to-many)
│   │   ├── permission.py    # Permission name strings
│   │   ├── setting.py       # Key/value app settings with type metadata
│   │   └── audit.py         # AuditLog — action, resource, user, IP, timestamp
│   ├── forms/
│   │   ├── auth.py          # LoginForm
│   │   ├── admin.py         # UserCreateForm, UserEditForm, RoleForm
│   │   └── profile.py       # ChangePasswordForm
│   ├── templates/
│   │   ├── base.html        # Master layout — sidebar, navbar, user settings dialog
│   │   ├── auth/login.html
│   │   ├── main/dashboard.html
│   │   ├── main/profile.html
│   │   ├── admin/           # index, users, user_form, roles, role_form, settings, audit
│   │   └── errors/          # 403, 404, 500
│   ├── static/
│   │   ├── css/custom.css   # Full design system — light / dark / terminal themes
│   │   └── js/sidebar.js    # Sidebar collapse + window.applyTheme()
│   └── utils/
│       ├── decorators.py    # @permission_required('x.y')  @admin_required
│       ├── settings.py      # get_setting() — reads settings table
│       └── helpers.py       # log_audit() helper
├── instance/                # SQLite database lives here (git-ignored)
├── migrations/              # Flask-Migrate / Alembic migration files
├── .env                     # Your secrets — NEVER commit this file
├── .flaskenv                # FLASK_APP, FLASK_ENV, FLASK_DEBUG
├── requirements.txt         # Python dependencies
├── run.py                   # Entry point — python run.py to start
└── CLAUDE.md                # AI coding guidelines for this project
```

---

## Setup on a New Machine

### Prerequisites

- **Python 3.11 or 3.12** — [python.org/downloads](https://www.python.org/downloads/)
- **Git** — [git-scm.com](https://git-scm.com)
- A terminal and a code editor (VS Code recommended)

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/D1-Test.git
cd D1-Test
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

You should see `(.venv)` at the start of your terminal prompt. If you don't, the venv isn't active and packages will install to the wrong place.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create your `.env` file

The `.env` file holds secrets and is git-ignored — every developer creates their own. Create it in the project root:

```env
SECRET_KEY=paste-a-generated-key-here
DATABASE_URI=sqlite:///app.db
FLASK_ENV=development
```

Generate a strong secret key with:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output and paste it as your `SECRET_KEY`. Don't use the placeholder.

### 5. Run the app

```bash
python run.py
```

On first run the app automatically:
1. Creates the SQLite database at `instance/app.db`
2. Applies any pending schema migrations
3. Seeds default roles, permissions, settings, and an admin user

Open your browser to **[http://localhost:5000](http://localhost:5000)**

### Default Login

| Field | Value |
|---|---|
| Username | `admin` |
| Password | `Admin@1234!` |

**Change this immediately.** Click your username in the top-right corner → Change Password.

---

## Accessing From Other Devices on Your LAN

`run.py` binds to `0.0.0.0:5000` so any device on the same network can reach it.

Find your machine's local IP address:
- **Windows:** open a terminal and run `ipconfig`, look for **IPv4 Address** (e.g. `192.168.1.50`)
- **Mac:** `ifconfig | grep "inet "`
- **Linux:** `ip addr show`

Then visit `http://192.168.1.50:5000` from any phone, tablet, or other computer on the same network. No extra config needed.

---

## Adding a New Module

This is the repeatable pattern for every new feature.

### 1. Create a blueprint file

```python
# app/blueprints/mymodule.py
from flask import Blueprint, render_template
from flask_login import login_required
from app.utils.decorators import permission_required

mymodule_bp = Blueprint("mymodule", __name__)

@mymodule_bp.route("/mymodule")
@login_required
@permission_required("mymodule.view")
def index():
    return render_template("main/mymodule.html", active_page="mymodule")
```

### 2. Register the blueprint

Open `app/__init__.py` and add two lines inside `create_app()`, after the existing blueprint imports:

```python
from app.blueprints.mymodule import mymodule_bp
app.register_blueprint(mymodule_bp)
```

### 3. Add a sidebar link

Open `app/templates/base.html` and find the comment block that reads **ADD FUTURE MODULE LINKS HERE**:

```html
<li class="nav-item">
  <a href="{{ url_for('mymodule.index') }}"
     class="nav-link {% if active_page == 'mymodule' %}active{% endif %}">
    <i class="bi bi-grid"></i>
    <span>My Module</span>
  </a>
</li>
```

Browse [Bootstrap Icons](https://icons.getbootstrap.com/) for icon class names (`bi-grid`, `bi-table`, `bi-bar-chart`, etc.).

### 4. Add permissions to the seed

Open `app/__init__.py`, find `perm_defs` inside `_seed_database()`, and add your new permissions:

```python
("mymodule.view",   "View my module"),
("mymodule.create", "Create items in my module"),
("mymodule.delete", "Delete items in my module"),
```

> On a **fresh database** these seed automatically when you run `python run.py`.
> On an **existing database** add them through `/admin/roles` in the browser, or delete `instance/app.db` and let it re-seed.

### 5. Create your template

```html
{# app/templates/main/mymodule.html #}
{% extends "base.html" %}

{% block title %}My Module — {{ get_setting('app_name', 'LocalVibe') }}{% endblock %}

{% block page_header %}
<div class="page-header">
  <div>
    <h1><i class="bi bi-grid me-2"></i>My Module</h1>
    <p class="lead">Description of what this does.</p>
  </div>
</div>
{% endblock %}

{% block content %}
  {# Your content here — cards, tables, forms, etc. #}
{% endblock %}
```

That's the full loop. Theme support, sidebar highlighting, CSRF protection, security headers, and audit logging all happen automatically.

---

## Permissions System

Permissions are dot-separated strings in the format `resource.action`.

**Protecting a route:**
```python
from app.utils.decorators import permission_required

@mymodule_bp.route("/sensitive")
@login_required
@permission_required("mymodule.edit")
def sensitive_view():
    ...
```

**Checking in a template:**
```html
{% if current_user.has_permission('mymodule.create') %}
  <a href="{{ url_for('mymodule.create') }}" class="btn btn-primary">New Item</a>
{% endif %}
```

**Admin shortcut:** users with `is_admin = True` bypass all permission checks automatically.

Built-in permissions:

| Permission | Description |
|---|---|
| `admin.full_access` | Full admin panel access |
| `dashboard.view` | View the dashboard |
| `users.view` / `.create` / `.edit` / `.delete` | User management |
| `roles.view` / `.create` / `.edit` / `.delete` | Role management |
| `settings.view` / `.edit` | App settings |
| `audit.view` | View audit log |

---

## Global Settings

Settings are stored in the `settings` table and available in every template automatically:

```html
{{ get_setting('app_name', 'LocalVibe') }}
{{ get_setting('primary_color', '#2563eb') }}
```

In Python code:
```python
from app.utils.settings import get_setting
name = get_setting("app_name", "LocalVibe")
```

Add new settings by adding rows to `_seed_database()` in `app/__init__.py`:

```python
("my_setting", "default value", "text", "Description of what this does", "general", None),
```

Setting types: `text`, `number`, `boolean`, `color`, `select` (pass options as JSON string), `json`.

All settings are editable live at `/admin/settings` — no code changes needed.

---

## Themes

Three themes ship with the app. Users switch via the account popup (click username, top-right corner).

| Theme | Visual Style |
|---|---|
| `light` | Clean white, blue accents, soft shadows |
| `dark` | GitHub-style — `#0d1117` background, `#161b22` cards, `#30363d` borders |
| `terminal` | Fallout/hacker — `#0d0208` background, `#00ff41` phosphor green, VT323 font, CRT scanlines |

**How it works:**
- The `<html>` element gets two attributes: `data-theme="light|dark|terminal"` and `data-bs-theme="light|dark"` (Bootstrap)
- An anti-FOUC inline script in `<head>` reads `localStorage` before any CSS loads — no theme flash on page load
- `window.applyTheme(theme)` in `sidebar.js` updates the DOM, saves to `localStorage`, and syncs to the server via `/api/set-theme`

To add your own theme, add a `[data-theme="mytheme"]` CSS block in `custom.css` following the same pattern as the terminal theme.

---

## Key Files Reference

| File | What to edit |
|---|---|
| `app/config.py` | Session timeouts, rate limits, security settings, env config |
| `app/templates/base.html` | Sidebar links, navbar layout, user settings dialog |
| `app/static/css/custom.css` | All styling — design tokens at top, theme sections below |
| `app/static/js/sidebar.js` | Sidebar behavior, `window.applyTheme()` |
| `app/__init__.py` | Register blueprints, add seed data, schema migrations |
| `app/models/user.py` | User model — add user-level fields here |
| `CLAUDE.md` | AI coding instructions — keep updated when you change architecture |

---

## Common Tasks

**Wipe and re-seed the database:**
```bash
# Stop the server, then:
rm instance/app.db        # Mac/Linux
del instance\app.db       # Windows CMD
python run.py             # auto re-seeds on startup
```

**Generate a secret key:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Open an interactive Flask shell:**
```bash
flask shell
>>> from app.models.user import User
>>> User.query.all()
>>> from app.utils.settings import get_setting
>>> get_setting("app_name")
```

**Install a new package and save it:**
```bash
pip install somepackage
# Then manually add it to requirements.txt with a version pin
```

**Run with auto-reload (development):**
```bash
python run.py
# or
flask run
```
Both work — `run.py` always uses `debug=True` and binds to `0.0.0.0` for LAN access.

---

## Environment Files Explained

| File | Purpose | Committed to Git? |
|---|---|---|
| `.env` | Secrets — `SECRET_KEY`, `DATABASE_URI` | **No — git-ignored** |
| `.flaskenv` | Flask CLI settings — `FLASK_APP`, `FLASK_ENV`, `FLASK_DEBUG` | Yes |
| `.gitignore` | What Git ignores — `.env`, `instance/`, `__pycache__`, `.venv` | Yes |

If you clone this repo and `.env` is missing, create it from scratch (see Setup step 4 above). The app will start with placeholder defaults but nothing will work securely until you set a real `SECRET_KEY`.

---

## Security Notes

- Passwords are hashed with **argon2** — memory-hard, resists GPU brute-force attacks
- **CSRF tokens** on every form via Flask-WTF — can't be forged from another site
- **Rate limiting** on login — 200 requests/day, 50/hour by default (Flask-Limiter)
- **Flask-Talisman** adds `Content-Security-Policy`, `X-Frame-Options`, and other headers in production. It's disabled in `DevelopmentConfig` to reduce friction while building
- Session cookies: `HttpOnly=True`, `SameSite=Lax`. Add `Secure=True` if you set up HTTPS
- All admin routes check `is_admin` or `admin.full_access` via a `before_request` hook — you can't sneak in by guessing URLs
- This is a LAN app, but it's written as if it could be exposed one day. Don't skip the security config before putting it on a network you don't fully control

---

## Vibe Coding Tips

- **CLAUDE.md** in the project root is the AI's constitution for this project. Show it to Claude at the start of every session. Keep it updated if you change the architecture so the AI stays consistent with your patterns.
- **Tell Claude what module you want**, and it will follow the blueprint pattern automatically — new file, register, sidebar link, permissions, template, the whole loop.
- **Never hardcode** app names, feature flags, or display strings in templates. Put them in the `settings` table so they're live-editable from `/admin/settings`.
- **The `active_page` variable** drives sidebar link highlighting. Always pass it from your route as a string (`active_page="mymodule"`), matching the key you used in the sidebar `{% if active_page == ... %}` check.
- **Bootstrap CSS loads from CDN** — the app still needs internet for styles. All JavaScript is local/vanilla so interactive features (sidebar, theme switching, the account popup) work on a LAN without internet. If you need fully offline support, download Bootstrap CSS and put it in `app/static/`.
- **SQLite is fine for a LAN tool** — when you're ready to scale, swap `DATABASE_URI` in `.env` to a PostgreSQL connection string. Nothing else in the code needs to change.
- **The terminal theme** is fully functional — not just cosmetic. If your team is into the aesthetic, encourage it. The VT323 font and phosphor-glow effects apply to everything automatically.
