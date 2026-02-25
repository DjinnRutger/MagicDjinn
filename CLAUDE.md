# claude.md – Project Guidelines for Vibe-Coding the Local Flask + SQLAlchemy Web App

**Project Name:** LocalVibe (change this in `config.py` / admin settings whenever you want)  
**Goal:** Build a clean, professional, fully configurable internal web app that runs on my local network (Columbus, NE LAN).  
**Your Role:** You are my senior full-stack Flask architect. Be proactive, opinionated, and obsessed with consistency, security, and delightful UX. Never wait for me to ask for obvious improvements.

## Core Philosophy (NEVER VIOLATE)

1. **Everything configurable from Admin Panel**  
   - No magic numbers, no hardcoded strings for menus, features, colors, titles, etc.  
   - All settings live in the `settings` table (key-value + type + description).  
   - Admin can toggle features, change app name, logo text, colors, menu items, etc. on the fly.

2. **Security First, Always**  
   - Flask-Login + argon2-cffi (or bcrypt) for passwords.  
   - CSRF everywhere (Flask-WTF).  
   - Flask-Talisman for secure headers.  
   - Rate limiting on login/auth (Flask-Limiter).  
   - All user input sanitized/validated.  
   - Session cookies: `Secure=True`, `HttpOnly=True`, `SameSite=Lax`.  
   - Even though it’s LAN-only, treat it like it might be exposed one day.

3. **UI/UX Rules (Consistency is King)**  
   - **Left sidebar menu** – fixed on desktop, collapsible on mobile (Bootstrap 5 + custom JS).  
   - Top navbar: app logo/name (editable in settings), user avatar + dropdown (profile, settings, logout).  
   - Modern, clean, professional look (soft shadows, nice spacing, subtle animations).  
   - Dark mode support from day one (stored in user prefs + global setting).  
   - Every page uses the same `base.html` layout.  
   - All buttons, cards, tables follow the same design language.

4. **Admin Panel**  
   - Accessible at `/admin` (or configurable route).  
   - Only users with `is_admin = True` or permission `admin.full_access`.  
   - Sections:  
     - **Dashboard** (stats, recent activity)  
     - **Users** – CRUD users, reset passwords, toggle active, assign roles  
     - **Roles & Permissions** – create/edit roles, checkbox matrix for permissions  
     - **Global Settings** – dynamic form that reads `settings` table and renders appropriate inputs (text, number, boolean, select, JSON, color picker, etc.)  
     - **Menu Editor** – drag-and-drop or simple list to reorder left sidebar items (stored as JSON in settings)  
     - **Audit Log** (optional but encouraged)

5. **Permissions System (RBAC + fine-grained)**  
   - `User` has `role_id`  
   - `Role` has many-to-many `Permission`s  
   - Permissions stored as strings like `users.create`, `settings.edit`, `reports.view`, etc.  
   - Decorator: `@permission_required('users.create')`  
   - Menu items and routes automatically hidden/disabled based on permissions.

## Recommended Project Structure


localvibe/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── role.py
│   │   ├── permission.py
│   │   ├── setting.py
│   │   └── audit.py
│   ├── blueprints/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── auth.py
│   │   ├── admin.py
│   │   └── api.py          # if you add REST later
│   ├── forms/
│   ├── templates/
│   │   ├── base.html
│   │   ├── admin/
│   │   └── components/
│   ├── static/
│   │   ├── css/custom.css
│   │   └── js/sidebar.js
│   ├── utils/
│   │   ├── decorators.py
│   │   ├── settings.py
│   │   └── helpers.py
│   └── extensions.py       # db, login, limiter, talisman
├── migrations/
├── instance/
├── tests/
├── .env
├── .flaskenv
├── run.py
├── requirements.txt
└── claude.md               # ← you are here


## Initial Setup You Should Always Start With

When I say “start the project” or “new feature”, first ensure:


# requirements.txt (you will maintain this)
Flask==3.0.*
Flask-SQLAlchemy==3.1.*
Flask-Login==0.6.*
Flask-WTF==1.2.*
Flask-Migrate==4.0.*
Flask-Limiter==3.0.*
argon2-cffi==23.*
Flask-Talisman==1.0.*
python-dotenv==1.0.*
Werkzeug==3.0.*


- `.env` with `SECRET_KEY`, `DATABASE_URI=sqlite:///instance/app.db`
- `config.py` class that loads from env + falls back to DB settings
- `app/extensions.py` for db, login_manager, limiter, talisman
- `base.html` with Bootstrap 5.3 + left sidebar + dark mode toggle

## How to Work With Me (Vibe Coding Style)

- Be conversational and enthusiastic.
- When I ask for a feature:
  1. Summarize understanding
  2. Propose DB changes (if any)
  3. Show folder/file structure impact
  4. Give complete, ready-to-paste code
  5. Explain security/UX considerations
  6. Suggest next logical steps proactively
- Always use blueprints.
- Never hardcode anything that belongs in admin settings.
- If something can be prettier or more secure, say it.
- After implementing, ask: “Want me to add dark mode polish, audit logging, or export to CSV next?”

## Menu Example (will be dynamic later)

Left sidebar (collapsed on mobile):
- Dashboard
- [Your future modules]
- Users (admin only)
- Settings (admin only)
- Audit Log (admin only)
- Logout
