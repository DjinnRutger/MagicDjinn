"""Database management blueprint — statistics, backup, restore, and connection configuration."""
import os
import re
import shutil
import sqlite3 as _sqlite3
import tempfile
from datetime import datetime, timezone, timedelta

from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    request, jsonify, send_file, abort,
)
from flask_login import login_required, current_user
from sqlalchemy import inspect, text

from app.extensions import db
from app.utils.helpers import log_audit

# Maximum accepted size for a restore upload (50 MB)
RESTORE_MAX_BYTES = 50 * 1024 * 1024

# ── Known schema migrations (applied to older backups before restore) ─────────
# Each entry:
#   "description"   – human-readable label shown in the UI
#   "applies_if"    – callable(backup_tables: set, backup_cols: dict) → bool
#   "sql"           – list of SQL statements to execute unconditionally
#   "conditional_sql" – callable(backup_cols: dict) → list[str] (extra SQL)
_BACKUP_MIGRATIONS = [
    {
        "id": 1,
        "description": "Add 'theme' column to users table (v1 → v2)",
        "applies_if": lambda tables, cols: (
            "users" in tables and "theme" not in cols.get("users", set())
        ),
        "sql": [
            "ALTER TABLE users ADD COLUMN theme VARCHAR(32) NOT NULL DEFAULT 'light'",
        ],
        "conditional_sql": lambda cols: (
            ["UPDATE users SET theme='dark' WHERE dark_mode=1"]
            if "dark_mode" in cols.get("users", set()) else []
        ),
    },
]

database_bp = Blueprint("database", __name__, url_prefix="/admin/database")


# ── Blueprint-wide access guard ──────────────────────────────────────────────
@database_bp.before_request
@login_required
def require_admin_access():
    if not (current_user.is_admin or current_user.has_permission("admin.full_access")):
        abort(403)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _human_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _mask_db_url(url: str) -> str:
    """Hide password in connection strings for display."""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


def _get_db_info() -> dict:
    """Gather database statistics and metadata."""
    engine = db.engine
    db_url = str(engine.url)
    is_sqlite = db_url.startswith("sqlite")

    inspector = inspect(engine)
    tables = sorted(inspector.get_table_names())

    table_stats = []
    total_rows = 0
    for table in tables:
        try:
            count = db.session.execute(
                text(f'SELECT COUNT(*) FROM "{table}"')
            ).scalar() or 0
        except Exception:
            count = 0
        total_rows += count
        table_stats.append({"name": table, "rows": count})

    table_stats.sort(key=lambda x: x["rows"], reverse=True)

    db_size_bytes = None
    db_path = None
    if is_sqlite:
        db_path = db_url.replace("sqlite:///", "").replace("sqlite://", "")
        if os.path.isfile(db_path):
            db_size_bytes = os.path.getsize(db_path)

    return {
        "is_sqlite": is_sqlite,
        "db_url_safe": _mask_db_url(db_url),
        "db_path": db_path,
        "tables": table_stats,
        "table_count": len(tables),
        "total_rows": total_rows,
        "db_size_bytes": db_size_bytes,
        "db_size_human": _human_size(db_size_bytes) if db_size_bytes is not None else "N/A",
    }


def _get_activity_data(days: int = 14) -> list:
    """Audit log entry counts per day for the last N days."""
    from app.models.audit import AuditLog
    today = datetime.now(timezone.utc).date()
    result = []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        count = AuditLog.query.filter(
            AuditLog.created_at >= start,
            AuditLog.created_at < end,
        ).count()
        result.append({"date": day.strftime("%b %d"), "count": count})
    return result


def _update_env_db_uri(new_uri: str) -> bool:
    """Update DATABASE_URI in .env. Returns True on success.
    Raises ValueError if new_uri contains line-break characters.
    """
    if any(c in new_uri for c in ("\n", "\r", "\x00")):
        raise ValueError("URI must not contain newline or null characters.")
    here = os.path.dirname(os.path.abspath(__file__))       # app/blueprints/
    project_root = os.path.dirname(os.path.dirname(here))   # project root
    env_path = os.path.join(project_root, ".env")
    if not os.path.isfile(env_path):
        return False
    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    new_lines = []
    updated = False
    for line in lines:
        if line.startswith("DATABASE_URI="):
            new_lines.append(f"DATABASE_URI={new_uri}\n")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"DATABASE_URI={new_uri}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    return True


# ── Restore helpers ───────────────────────────────────────────────────────────
def _inspect_backup(path: str) -> dict:
    """Inspect a SQLite backup file for schema compatibility.

    Returns a dict with keys:
        valid           – bool: passes the SQLite magic-byte check
        error           – str|None: set when valid=False
        tables          – list[str]: table names found in the backup
        file_size_human – human-readable file size
        migrations      – list of resolved migration dicts to apply
        warnings        – list[str]: non-fatal issues (missing tables, etc.)
    """
    result: dict = {
        "valid": False,
        "error": None,
        "tables": [],
        "file_size_human": _human_size(os.path.getsize(path)),
        "migrations": [],
        "warnings": [],
    }

    # 1. SQLite magic-byte check ──────────────────────────────────────────────
    try:
        with open(path, "rb") as fh:
            header = fh.read(16)
    except OSError as exc:
        result["error"] = str(exc)
        return result

    if header != b"SQLite format 3\x00":
        result["error"] = "File is not a valid SQLite 3 database."
        return result

    result["valid"] = True

    # 2. Read tables + columns from the backup ────────────────────────────────
    backup_tables: set = set()
    backup_cols: dict[str, set] = {}
    try:
        con = _sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        backup_tables = {row[0] for row in cur.fetchall()}
        for tbl in backup_tables:
            cur.execute(f"PRAGMA table_info([{tbl}])")
            backup_cols[tbl] = {row[1] for row in cur.fetchall()}
        con.close()
    except _sqlite3.Error as exc:
        result["error"] = f"SQLite read error: {exc}"
        return result

    result["tables"] = sorted(backup_tables)

    # 3. Compare against the ORM-defined schema ───────────────────────────────
    for table_name, table_obj in db.metadata.tables.items():
        if table_name not in backup_tables:
            result["warnings"].append(
                f"Table '{table_name}' is missing from backup — "
                "it will be recreated empty when the server restarts."
            )
            continue

        # Check for columns present in the current model but absent in backup
        current_col_names = {c.name for c in table_obj.columns}
        missing_cols = current_col_names - backup_cols.get(table_name, set())
        for col_name in missing_cols:
            col_obj = table_obj.c[col_name]
            has_default = (
                col_obj.default is not None or col_obj.server_default is not None
            )
            # Non-nullable + no default = we can't auto-add; warn instead
            if not col_obj.nullable and not has_default:
                result["warnings"].append(
                    f"Column '{table_name}.{col_name}' is missing from the backup "
                    "and has no safe default — manual correction may be needed after restore."
                )

    # 4. Resolve known migration definitions ──────────────────────────────────
    for migration in _BACKUP_MIGRATIONS:
        if migration["applies_if"](backup_tables, backup_cols):
            extra_sql = migration["conditional_sql"](backup_cols)
            result["migrations"].append(
                {
                    "id": migration["id"],
                    "description": migration["description"],
                    "sql": migration["sql"] + extra_sql,
                }
            )

    return result


def _apply_migrations_to_backup(path: str, migrations: list) -> list:
    """Apply schema migrations to a SQLite file in-place.

    Raises on any SQL error so the caller can abort the restore.
    Returns a list of applied migration descriptions.
    """
    applied = []
    con = _sqlite3.connect(path)
    try:
        for m in migrations:
            for sql in m["sql"]:
                con.execute(sql)
            con.commit()
            applied.append(m["description"])
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return applied


# ── Routes ────────────────────────────────────────────────────────────────────
@database_bp.route("/")
def index():
    db_info      = _get_db_info()
    activity     = _get_activity_data(14)
    max_activity = max((d["count"] for d in activity), default=1) or 1
    max_rows     = max((t["rows"] for t in db_info["tables"]), default=1) or 1

    from app.models.setting import Setting
    db_type_s  = Setting.query.filter_by(key="db_type").first()
    ext_uri_s  = Setting.query.filter_by(key="external_db_uri").first()
    pending_db_type = db_type_s.value if db_type_s else "sqlite"
    pending_ext_uri = ext_uri_s.value if ext_uri_s else ""

    return render_template(
        "admin/database.html",
        db_info=db_info,
        activity=activity,
        max_activity=max_activity,
        max_rows=max_rows,
        pending_db_type=pending_db_type,
        pending_ext_uri=pending_ext_uri,
        active_page="admin_database",
    )


@database_bp.route("/backup/download")
def backup_download():
    engine = db.engine
    db_url = str(engine.url)

    if not db_url.startswith("sqlite"):
        flash(
            "Backup download is only available for SQLite. "
            "Use <code>pg_dump</code> for PostgreSQL.",
            "warning",
        )
        return redirect(url_for("database.index") + "#backup")

    db_path = db_url.replace("sqlite:///", "").replace("sqlite://", "")
    if not os.path.isfile(db_path):
        flash("Database file not found.", "danger")
        return redirect(url_for("database.index"))

    # Copy to a temp file so we read safely while DB may be open
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    shutil.copy2(db_path, tmp.name)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = f"localvibe_backup_{timestamp}.db"
    log_audit("backup_download", "database", details=f"file={filename}")

    return send_file(
        tmp.name,
        as_attachment=True,
        download_name=filename,
        mimetype="application/octet-stream",
    )


@database_bp.route("/backup/restore", methods=["POST"])
def backup_restore():
    """Upload a .db file and restore it as the live database.

    Safety steps:
      1. Validate magic bytes (must be a real SQLite file)
      2. Check schema compatibility vs current ORM models
      3. Apply any needed migrations to a temp copy of the backup
      4. Write a timestamped safety backup of the current DB
      5. Swap the migrated backup into place
      6. Audit-log the operation against the newly restored DB
    """
    engine = db.engine
    db_url = str(engine.url)

    if not db_url.startswith("sqlite"):
        flash(
            "Restore is only available for SQLite databases. "
            "Use your PostgreSQL tooling (<code>pg_restore</code>) instead.",
            "warning",
        )
        return redirect(url_for("database.index") + "#backup")

    db_path = db_url.replace("sqlite:///", "").replace("sqlite://", "")
    if not os.path.isfile(db_path):
        flash("Current database file not found on disk.", "danger")
        return redirect(url_for("database.index") + "#backup")

    # Require the explicit confirmation checkbox
    if request.form.get("confirm_restore") != "yes":
        flash("You must tick the confirmation checkbox to proceed with a restore.", "warning")
        return redirect(url_for("database.index") + "#backup")

    uploaded = request.files.get("backup_file")
    if not uploaded or not uploaded.filename:
        flash("No backup file was uploaded.", "danger")
        return redirect(url_for("database.index") + "#backup")

    if not uploaded.filename.lower().endswith(".db"):
        flash("Invalid file type — please upload a .db SQLite backup file.", "danger")
        return redirect(url_for("database.index") + "#backup")

    # Save upload to a temp file for inspection / migration
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        uploaded.save(tmp.name)
        upload_size = os.path.getsize(tmp.name)

        if upload_size == 0:
            flash("Uploaded file is empty.", "danger")
            return redirect(url_for("database.index") + "#backup")

        if upload_size > RESTORE_MAX_BYTES:
            flash(
                f"Uploaded file ({_human_size(upload_size)}) exceeds the "
                f"{_human_size(RESTORE_MAX_BYTES)} limit.",
                "danger",
            )
            return redirect(url_for("database.index") + "#backup")

        # ── Compatibility check ───────────────────────────────────────────
        compat = _inspect_backup(tmp.name)
        if not compat["valid"]:
            flash(f"Backup is not a valid SQLite database: {compat['error']}", "danger")
            return redirect(url_for("database.index") + "#backup")

        # ── Apply schema migrations to the temp copy ──────────────────────
        applied_migrations: list[str] = []
        if compat["migrations"]:
            try:
                applied_migrations = _apply_migrations_to_backup(
                    tmp.name, compat["migrations"]
                )
            except Exception as exc:
                flash(f"Schema migration failed: {exc}", "danger")
                return redirect(url_for("database.index") + "#backup")

        # ── Safety backup of the current live database ────────────────────
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        instance_dir = os.path.dirname(os.path.abspath(db_path))
        safety_filename = f"pre_restore_{timestamp}.db"
        safety_path = os.path.join(instance_dir, safety_filename)
        shutil.copy2(db_path, safety_path)

        # ── Close all SQLAlchemy connections, then swap files ─────────────
        # dispose() drains and closes every connection in the pool so the
        # file is not locked when we overwrite it.
        db.session.remove()
        db.engine.dispose()
        shutil.copy2(tmp.name, db_path)

        # ── Audit-log against the newly restored database ─────────────────
        try:
            log_audit(
                "restore",
                "database",
                details=(
                    f"file={uploaded.filename}, "
                    f"size={_human_size(upload_size)}, "
                    f"migrations_applied={applied_migrations or 'none'}, "
                    f"safety_backup={safety_filename}"
                ),
            )
        except Exception:
            pass  # Don't fail the restore if the new DB lacks the audit table yet

        # ── Build success flash ───────────────────────────────────────────
        parts = ["<strong>Database restored successfully.</strong>"]
        if applied_migrations:
            parts.append(
                f" Schema updated automatically: "
                + "; ".join(f"<em>{m}</em>" for m in applied_migrations) + "."
            )
        for w in compat["warnings"]:
            parts.append(f"<br><i class='bi bi-exclamation-triangle me-1 text-warning'></i>{w}")
        parts.append(
            f"<br>Safety backup of the previous database saved as "
            f"<code>{safety_filename}</code> in <code>instance/</code>."
        )
        parts.append(
            "<br><strong>Restart the server</strong> to fully reload the restored database."
        )
        flash("".join(parts), "success")

    except Exception as exc:
        flash(f"Restore failed unexpectedly: {exc}", "danger")
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    return redirect(url_for("database.index") + "#backup")


@database_bp.route("/config", methods=["POST"])
def config_save():
    new_type = request.form.get("db_type", "sqlite")
    new_uri  = request.form.get("external_db_uri", "").strip()

    if new_type not in ("sqlite", "postgresql"):
        flash("Invalid database type.", "danger")
        return redirect(url_for("database.index") + "#config")

    if new_type == "postgresql" and not new_uri:
        flash("A PostgreSQL connection URI is required.", "danger")
        return redirect(url_for("database.index") + "#config")

    # Reject control characters that could inject extra lines into .env
    if any(c in new_uri for c in ("\n", "\r", "\x00")):
        flash("Connection URI must not contain newline or null characters.", "danger")
        return redirect(url_for("database.index") + "#config")

    from app.models.setting import Setting

    def _upsert(key, value, desc, cat):
        s = Setting.query.filter_by(key=key).first()
        if s:
            s.value = value
        else:
            db.session.add(Setting(
                key=key, value=value, type="text",
                description=desc, category=cat,
            ))

    _upsert("db_type",        new_type, "Active database type",             "database")
    _upsert("external_db_uri", new_uri, "External database connection URI", "database")

    env_updated = False
    if new_type == "postgresql" and new_uri:
        env_updated = _update_env_db_uri(new_uri)
    elif new_type == "sqlite":
        from app.config import _DEFAULT_DB
        env_updated = _update_env_db_uri(_DEFAULT_DB)

    db.session.commit()
    log_audit("updated", "database_config", details=f"db_type={new_type}")

    if env_updated:
        flash(
            "Configuration saved and <strong>.env</strong> updated. "
            "Restart the server to apply the new database connection.",
            "success",
        )
    else:
        flash(
            "Configuration saved. Update <strong>DATABASE_URI</strong> in your "
            "<code>.env</code> file manually, then restart the server.",
            "warning",
        )

    return redirect(url_for("database.index") + "#config")


@database_bp.route("/test-connection", methods=["POST"])
def test_connection():
    data = request.get_json(silent=True) or {}
    uri  = data.get("uri", "").strip()

    if not uri:
        return jsonify(ok=False, error="Connection URI is required.")

    if not uri.startswith((
        "postgresql://", "postgresql+psycopg2://",
        "postgresql+pg8000://", "postgresql+asyncpg://",
    )):
        return jsonify(ok=False, error="URI must start with postgresql://")

    try:
        from sqlalchemy import create_engine
        test_engine = create_engine(uri, connect_args={"connect_timeout": 5})
        with test_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        test_engine.dispose()
        return jsonify(ok=True, message="Connection successful!")
    except ImportError:
        return jsonify(
            ok=False,
            error="psycopg2 driver not installed. Run: pip install psycopg2-binary",
        )
    except Exception as e:
        return jsonify(ok=False, error=str(e))
