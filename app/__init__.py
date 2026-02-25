"""
MagicDjinn – Flask application factory.
MTG card collection & deck tracker with social features.
"""
import os
from flask import Flask, render_template, redirect, url_for, request
from sqlalchemy import inspect, text
from app.config import config
from app.extensions import db, login_manager, csrf, limiter, migrate


def create_app(config_name: str = "default") -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config[config_name])

    # Ensure instance directory exists (SQLite lives here)
    os.makedirs(app.instance_path, exist_ok=True)

    # ── Initialise extensions ────────────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    migrate.init_app(app, db)

    if app.config.get("TALISMAN_ENABLED"):
        from flask_talisman import Talisman
        Talisman(app, **app.config.get("TALISMAN_CONFIG", {}))

    # ── Register blueprints ──────────────────────────────────────────────────
    from app.blueprints.auth import auth_bp
    from app.blueprints.main import main_bp
    from app.blueprints.admin import admin_bp
    from app.blueprints.database_mgr import database_bp
    from app.blueprints.setup import setup_bp
    from app.blueprints.collection import collection_bp
    from app.blueprints.decks import decks_bp
    from app.blueprints.friends import friends_bp
    from app.blueprints.cards import cards_bp
    from app.blueprints.notifications import notif_bp
    from app.blueprints.feed import feed_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(database_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(collection_bp)
    app.register_blueprint(decks_bp)
    app.register_blueprint(friends_bp)
    app.register_blueprint(cards_bp)
    app.register_blueprint(notif_bp)
    app.register_blueprint(feed_bp)

    # ── Context processors ───────────────────────────────────────────────────
    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from app.utils.settings import get_setting

        def admin_nav():
            """Build admin sidebar items — only called when user is admin."""
            return [
                {"icon": "bi-gauge",        "label": "Overview",    "url": url_for("admin.index"),    "key": "admin"},
                {"icon": "bi-people",        "label": "Users",       "url": url_for("admin.users"),    "key": "admin_users"},
                {"icon": "bi-shield-check",  "label": "Roles & Perms", "url": url_for("admin.roles"), "key": "admin_roles"},
                {"icon": "bi-sliders",       "label": "Settings",    "url": url_for("admin.settings"), "key": "admin_settings"},
                {"icon": "bi-journal-text",  "label": "Audit Log",   "url": url_for("admin.audit"),      "key": "admin_audit"},
                {"icon": "bi-database",      "label": "Database",    "url": url_for("database.index"),   "key": "admin_database"},
                {"icon": "bi-people-fill",   "label": "Friend Groups", "url": url_for("admin.friend_groups"), "key": "admin_friend_groups"},
            ]

        def sidebar_nav():
            """Build MTG module nav items. Only includes items whose blueprints are registered.
            New phases auto-appear in the sidebar as their blueprints are added."""
            nav_defs = [
                ("bi-collection-fill", "My Collection", "collection.box",   "collection"),
                ("bi-layers-fill",     "My Decks",      "decks.index",      "decks"),
                ("bi-people-fill",     "Friends",       "friends.index",    "friends"),
                ("bi-search",          "Card Search",   "cards.search",     "card_search"),
            ]
            items = []
            for icon, label, endpoint, key in nav_defs:
                try:
                    items.append({
                        "icon": icon, "label": label,
                        "url": url_for(endpoint), "key": key,
                    })
                except Exception:
                    pass  # Blueprint not registered yet — skip silently
            return items

        return dict(get_setting=get_setting, admin_nav=admin_nav, sidebar_nav=sidebar_nav)

    # ── First-run guard ──────────────────────────────────────────────────────
    @app.before_request
    def first_run_check():
        """Redirect to the setup wizard if no users exist yet."""
        # Let the setup route and static files through unconditionally
        if request.endpoint in ("setup.index", "static"):
            return
        try:
            from app.models.user import User
            if not User.query.first():
                return redirect(url_for("setup.index"))
        except Exception:
            # DB tables may not exist yet during the very first create_all() pass
            pass

    # ── Error handlers ───────────────────────────────────────────────────────
    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(e):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    # ── Database + seed ──────────────────────────────────────────────────────
    with app.app_context():
        # Register all models with SQLAlchemy before create_all().
        # Using importlib avoids the "import app.models" pattern which would
        # silently shadow the local 'app' Flask-instance variable with the module.
        import importlib
        importlib.import_module("app.models")
        db.create_all()
        _run_migrations()
        _seed_database()

    return app


# ── Migration helper ─────────────────────────────────────────────────────────
def _run_migrations() -> None:
    """Apply lightweight schema migrations that Flask-Migrate doesn't handle for SQLite."""
    inspector = inspect(db.engine)

    # ── inventory table migrations ────────────────────────────────────────────
    try:
        inv_cols = [c["name"] for c in inspector.get_columns("inventory")]
        if "is_sideboard" not in inv_cols:
            db.session.execute(text(
                "ALTER TABLE inventory ADD COLUMN is_sideboard BOOLEAN NOT NULL DEFAULT 0"
            ))
            db.session.commit()
        if "is_commander" not in inv_cols:
            db.session.execute(text(
                "ALTER TABLE inventory ADD COLUMN is_commander BOOLEAN NOT NULL DEFAULT 0"
            ))
            db.session.commit()
        if "physical_location" not in inv_cols:
            db.session.execute(text(
                "ALTER TABLE inventory ADD COLUMN physical_location VARCHAR(200)"
            ))
            db.session.commit()
        if "is_proxy" not in inv_cols:
            db.session.execute(text(
                "ALTER TABLE inventory ADD COLUMN is_proxy BOOLEAN NOT NULL DEFAULT 0"
            ))
            db.session.commit()
    except Exception:
        pass  # table may not exist yet on very first run

    # ── decks table migrations ────────────────────────────────────────────────
    try:
        deck_cols = [c["name"] for c in inspector.get_columns("decks")]
        if "cover_card_scryfall_id" not in deck_cols:
            db.session.execute(text(
                "ALTER TABLE decks ADD COLUMN cover_card_scryfall_id VARCHAR(50)"
            ))
            db.session.commit()
        if "bracket" not in deck_cols:
            db.session.execute(text(
                "ALTER TABLE decks ADD COLUMN bracket INTEGER"
            ))
            db.session.commit()
    except Exception:
        pass

    # ── deck_shares table ─────────────────────────────────────────────────────
    existing_tables = inspector.get_table_names()
    if "deck_shares" not in existing_tables:
        from app.models.deck_share import DeckShare
        DeckShare.__table__.create(db.engine)

    # ── feed tables ───────────────────────────────────────────────────────────
    if "feed_posts" not in existing_tables:
        from app.models.feed import FeedPost
        FeedPost.__table__.create(db.engine)
    if "feed_likes" not in existing_tables:
        from app.models.feed import FeedLike
        FeedLike.__table__.create(db.engine)
    if "feed_comments" not in existing_tables:
        from app.models.feed import FeedComment
        FeedComment.__table__.create(db.engine)

    cols = [c["name"] for c in inspector.get_columns("users")]
    if "avatar_art_crop" not in cols:
        db.session.execute(text(
            "ALTER TABLE users ADD COLUMN avatar_art_crop VARCHAR(500)"
        ))
        db.session.commit()

    if "theme" not in cols:
        db.session.execute(text(
            "ALTER TABLE users ADD COLUMN theme VARCHAR(32) NOT NULL DEFAULT 'light'"
        ))
        if "dark_mode" in cols:
            db.session.execute(text(
                "UPDATE users SET theme='dark' WHERE dark_mode=1"
            ))
        db.session.commit()

    from app.models.setting import Setting
    from app.models.permission import Permission
    from app.models.role import Role

    changed = False

    # ── Upsert settings missing from older databases ──────────────────────────
    _new_settings = [
        ("ui_scale", "100%", "select",
         "UI font scale for large monitors — 100% is default",
         "appearance", '["100%","110%","125%","140%"]'),
        ("login_layout", "above", "select",
         "Login page layout — logo above the form, or side-by-side",
         "appearance", '["above","side"]'),
        ("secondary_color", "#2563eb", "color",
         "Accent colour for active items, buttons, and focus rings",
         "appearance", None),
        ("show_recent_activity", "true", "boolean",
         "Show the Recent Activity table on the dashboard",
         "general", None),
        ("enable_flying_cards", "true", "boolean",
         "Animate card images flying across the dashboard",
         "appearance", None),
        ("scryfall_cache_days", "7", "number",
         "Days before cached card data is considered stale",
         "general", None),
        ("spotlight_cycle_seconds", "9", "number",
         "Community Spotlight auto-cycle interval in seconds (3–60)",
         "general", None),
        ("primary_color_2", "", "color",
         "Sidebar gradient end colour — leave blank for a flat sidebar",
         "appearance", None),
    ]
    for key, value, stype, desc, cat, opts in _new_settings:
        if not Setting.query.filter_by(key=key).first():
            db.session.add(Setting(
                key=key, value=value, type=stype,
                description=desc, category=cat, options=opts,
            ))
            changed = True

    # Re-purpose primary_color: if still at the old accent-colour default,
    # reset it to the sidebar-background default and update its description.
    pc = Setting.query.filter_by(key="primary_color").first()
    if pc:
        if pc.value == "#2563eb":          # user never changed it from old default
            pc.value = "#0f172a"
            changed = True
        pc.description = "Sidebar navigation bar background colour"
        changed = True

    # ── Rebrand from LocalVibe to MagicDjinn (existing databases) ────────────
    _rebrand_map = {
        "app_name":    ("LocalVibe",                          "MagicDjinn"),
        "app_tagline": ("Your Local Network Hub",             "Your Personal MTG Vault"),
        "app_icon":    ("bi-lightning-charge-fill",           "bi-stars"),
        "footer_text": ("LocalVibe \u2014 Built with Flask",  "MagicDjinn \u2014 Built with Flask"),
    }
    for key, (old_val, new_val) in _rebrand_map.items():
        s = Setting.query.filter_by(key=key).first()
        if s and s.value == old_val:
            s.value = new_val
            changed = True

    if changed:
        db.session.commit()
        changed = False

    # ── Upsert MTG permissions (only on existing databases that already have roles)
    # Fresh databases get these permissions via _seed_database() instead.
    if not Role.query.first():
        return

    mtg_perm_defs = [
        ("collection.view",  "View own card collection (Box)"),
        ("collection.edit",  "Add, edit and remove cards in own Box"),
        ("deck.view",        "View own decks"),
        ("deck.edit",        "Create and edit own decks"),
        ("deck.delete",      "Delete own decks"),
        ("friends.view",     "View friend groups and friends' boxes"),
        ("friends.manage",   "Manage friend group membership"),
        ("cards.import",     "Import cards via decklist paste"),
    ]
    upserted_perms: dict[str, Permission] = {}
    for name, desc in mtg_perm_defs:
        p = Permission.query.filter_by(name=name).first()
        if not p:
            p = Permission(name=name, description=desc)
            db.session.add(p)
            changed = True
        upserted_perms[name] = p

    if changed:
        db.session.flush()

    # ── Assign MTG permissions to existing roles ──────────────────────────────
    admin_role = Role.query.filter_by(name="Administrator").first()
    if admin_role:
        existing = {p.name for p in admin_role.permissions}
        for name, perm in upserted_perms.items():
            if name not in existing:
                admin_role.permissions.append(perm)
                changed = True

    std_role = Role.query.filter_by(name="Standard User").first()
    if std_role:
        std_mtg_perms = [
            "collection.view", "collection.edit",
            "deck.view", "deck.edit", "deck.delete",
            "friends.view", "cards.import",
        ]
        existing = {p.name for p in std_role.permissions}
        for name in std_mtg_perms:
            if name in upserted_perms and name not in existing:
                std_role.permissions.append(upserted_perms[name])
                changed = True

    if changed:
        db.session.commit()


# ── Seed helper ──────────────────────────────────────────────────────────────
def _seed_database() -> None:
    """Seed roles, permissions, and settings on a fresh database.

    The admin user is NOT created here — the first-run setup wizard
    (/setup) handles that so the operator can choose their own credentials.
    """
    from app.models.role import Role
    from app.models.permission import Permission
    from app.models.setting import Setting

    # Idempotent: skip if both roles and all base permissions already exist
    if Role.query.first() and Permission.query.filter_by(name="admin.full_access").first():
        return

    # ── Permissions (idempotent — get-or-create each one) ────────────────────
    perm_defs = [
        # System / admin
        ("admin.full_access",  "Full admin panel access"),
        ("dashboard.view",     "View dashboard"),
        ("users.view",         "View user list"),
        ("users.create",       "Create users"),
        ("users.edit",         "Edit users"),
        ("users.delete",       "Delete users"),
        ("roles.view",         "View roles"),
        ("roles.create",       "Create roles"),
        ("roles.edit",         "Edit roles"),
        ("roles.delete",       "Delete roles"),
        ("settings.view",      "View settings"),
        ("settings.edit",      "Edit settings"),
        ("audit.view",         "View audit log"),
        ("database.view",      "View database management"),
        ("database.backup",    "Download database backups"),
        ("database.configure", "Configure database connection"),
        # MTG features
        ("collection.view",    "View own card collection (Box)"),
        ("collection.edit",    "Add, edit and remove cards in own Box"),
        ("deck.view",          "View own decks"),
        ("deck.edit",          "Create and edit own decks"),
        ("deck.delete",        "Delete own decks"),
        ("friends.view",       "View friend groups and friends' boxes"),
        ("friends.manage",     "Manage friend group membership"),
        ("cards.import",       "Import cards via decklist paste"),
    ]
    perms: dict[str, Permission] = {}
    for name, desc in perm_defs:
        p = Permission.query.filter_by(name=name).first()
        if not p:
            p = Permission(name=name, description=desc)
            db.session.add(p)
        perms[name] = p
    db.session.flush()

    # ── Roles (idempotent — get-or-create each one) ───────────────────────────
    admin_role = Role.query.filter_by(name="Administrator").first()
    if not admin_role:
        admin_role = Role(name="Administrator", description="Full system access")
        db.session.add(admin_role)
    admin_role.permissions = list(perms.values())

    user_role = Role.query.filter_by(name="Standard User").first()
    if not user_role:
        user_role = Role(name="Standard User", description="Basic MTG user access")
        db.session.add(user_role)
    user_role.permissions = [
        perms["dashboard.view"],
        perms["collection.view"],
        perms["collection.edit"],
        perms["deck.view"],
        perms["deck.edit"],
        perms["deck.delete"],
        perms["friends.view"],
        perms["cards.import"],
    ]

    db.session.flush()

    # ── Default settings (idempotent — skip any that already exist) ──────────
    setting_defs = [
        ("app_name",          "MagicDjinn",                 "text",    "Application display name",                        "general",    None),
        ("app_tagline",       "Your Personal MTG Vault",    "text",    "Tagline shown on the login page",                 "general",    None),
        ("app_icon",          "bi-stars",                   "text",    "Bootstrap Icons class for the sidebar logo",      "appearance", None),
        ("footer_text",       "MagicDjinn \u2014 Built with Flask", "text", "Footer copyright text",                     "general",    None),
        ("primary_color",     "#0f172a",                    "color",   "Sidebar navigation bar background colour",         "appearance", None),
        ("secondary_color",   "#2563eb",                    "color",   "Accent colour for active items, buttons, and focus rings", "appearance", None),
        ("default_theme",     "light",                      "select",  "Default colour theme for new users",              "appearance", '["light","dark","terminal"]'),
        ("allow_registration","false",                      "boolean", "Allow new visitors to self-register",             "security",   None),
        ("maintenance_mode",  "false",                      "boolean", "Show maintenance page to non-admin users",        "general",    None),
        ("show_recent_activity", "true",                   "boolean", "Show the Recent Activity table on the dashboard",  "general",    None),
        ("items_per_page",    "20",                         "number",  "Rows shown per page in data tables",              "general",    None),
        ("session_timeout",   "480",                        "number",  "Session idle timeout in minutes (0 = never)",     "security",   None),
        ("ui_scale",          "100%",                       "select",  "UI font scale for large monitors — 100% is default", "appearance", '["100%","110%","125%","140%"]'),
        ("login_layout",      "above",                      "select",  "Login page layout: logo above the form or side-by-side", "appearance", '["above","side"]'),
        ("enable_flying_cards", "true",                     "boolean", "Animate card images flying across the dashboard", "appearance", None),
        ("scryfall_cache_days",  "7",                       "number",  "Days before cached card data is considered stale", "general",    None),
        ("primary_color_2",      "",                        "color",   "Sidebar gradient end colour — leave blank for a flat sidebar", "appearance", None),
    ]
    for key, value, stype, desc, cat, opts in setting_defs:
        if not Setting.query.filter_by(key=key).first():
            db.session.add(Setting(key=key, value=value, type=stype,
                                   description=desc, category=cat, options=opts))

    db.session.commit()
