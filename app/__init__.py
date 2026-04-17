import hashlib
import os
from datetime import timedelta
import bleach
import markdown as md_lib
from markupsafe import Markup
from flask import Flask, request, redirect
from flask_login import LoginManager
from .models import db, User, MediaItem, MeetingFile, Reading, UrlRedirect

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"


def create_app():
    app = Flask(__name__, instance_relative_config=False)

    data_dir = os.path.abspath(os.environ.get("TSP_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")))
    upload_dir = os.path.abspath(os.environ.get("TSP_UPLOAD_DIR", os.path.join(data_dir, "uploads")))
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(upload_dir, exist_ok=True)

    db_path = os.path.join(data_dir, "tsp.db")
    app.config.update(
        SECRET_KEY=os.environ.get("TSP_SECRET_KEY", "dev-secret-change-me"),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=upload_dir,
        MAX_CONTENT_LENGTH=256 * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(days=180),
        REMEMBER_COOKIE_DURATION=timedelta(days=180),
        REMEMBER_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SAMESITE="Lax",
    )

    db.init_app(app)
    login_manager.init_app(app)

    @app.template_filter("file_type")
    def file_type(src):
        """Return a short type key for a filename string or object with original_filename/stored_filename/url."""
        if isinstance(src, str):
            name = src
        else:
            name = (getattr(src, "original_filename", None)
                    or getattr(src, "stored_filename", None)
                    or "")
            if not name and getattr(src, "url", None):
                return "link"
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext == "pdf": return "pdf"
        if ext in ("zip", "7z", "rar", "tar", "gz", "tgz", "bz2"): return "zip"
        if ext == "pages": return "pages"
        if ext in ("doc", "docx", "rtf", "odt"): return "doc"
        if ext in ("xls", "xlsx", "csv", "ods"): return "xls"
        if ext in ("ppt", "pptx", "odp"): return "ppt"
        if ext in ("jpg", "jpeg", "png", "gif", "webp", "svg", "bmp"): return "img"
        if ext in ("mp4", "mov", "avi", "mkv", "webm"): return "vid"
        if ext in ("mp3", "wav", "m4a", "ogg", "flac"): return "aud"
        if ext in ("txt", "md"): return "doc"
        if not ext and getattr(reading, "url", None): return "link"
        return "file"

    SAFE_TAGS = {"a", "b", "strong", "i", "em", "u", "s", "br", "span", "code",
                 "sup", "sub", "mark", "small", "abbr"}
    SAFE_ATTRS = {"a": ["href", "title", "target", "rel"], "abbr": ["title"], "span": ["class"]}

    @app.template_filter("safe_html")
    def safe_html(value):
        if not value:
            return ""
        cleaned = bleach.clean(str(value), tags=SAFE_TAGS, attributes=SAFE_ATTRS,
                               protocols=["http", "https", "mailto"], strip=True)
        return Markup(cleaned)

    @app.template_filter("markdown")
    def markdown_filter(value):
        if not value:
            return ""
        html = md_lib.markdown(str(value), extensions=["extra", "nl2br", "sane_lists"])
        return Markup(html)

    @app.template_filter("from_json")
    def from_json_filter(value):
        import json
        try:
            return json.loads(value) if value else []
        except (ValueError, TypeError):
            return []

    @app.template_filter("fmt12h")
    def fmt12h(value):
        if not value:
            return ""
        try:
            h, m = value.split(":")[:2]
            h = int(h); m = int(m)
        except (ValueError, AttributeError):
            return value
        suffix = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {suffix}"

    from .crypto import init_fernet
    init_fernet(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from .auth import bp as auth_bp
    from .routes import bp as main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    @app.before_request
    def _legacy_redirect():
        p = request.path or ""
        if not p.startswith("/wp-"):
            return None
        row = UrlRedirect.query.filter_by(source_path=p).first()
        if row:
            return redirect(row.target_path, code=301)
        return None

    @app.after_request
    def _no_store_dynamic(response):
        # Stops Cloudflare/browsers from caching per-user pages and stale
        # form responses. /static/ and /pub/ are deterministic and safe to cache.
        path = request.path or ""
        if path.startswith("/static/") or path.startswith("/pub/"):
            return response
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers.setdefault("Pragma", "no-cache")
        response.headers.setdefault("Expires", "0")
        return response

    with app.app_context():
        db.create_all()
        _migrate_sqlite(app)
        _seed_admin(app)
        _backfill_media(app)

    return app


def _backfill_media(app):
    """Index any stored_filenames referenced by MeetingFile/Reading into MediaItem."""
    upload_dir = app.config["UPLOAD_FOLDER"]
    known = {m.stored_filename for m in MediaItem.query.all()}
    candidates = set()
    for row in db.session.query(MeetingFile.stored_filename, MeetingFile.original_filename).all():
        if row[0] and row[0] not in known:
            candidates.add((row[0], row[1] or row[0]))
    for row in db.session.query(Reading.stored_filename, Reading.original_filename).all():
        if row[0] and row[0] not in known:
            candidates.add((row[0], row[1] or row[0]))
    for row in db.session.query(Reading.thumbnail_filename).filter(Reading.thumbnail_filename.isnot(None)).all():
        if row[0] and row[0] not in known:
            candidates.add((row[0], row[0]))
    added = 0
    for stored, original in candidates:
        path = os.path.join(upload_dir, stored)
        if not os.path.isfile(path):
            continue
        try:
            h = hashlib.sha256()
            size = 0
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk); size += len(chunk)
            m = MediaItem(stored_filename=stored, original_filename=original,
                          content_hash=h.hexdigest(), size_bytes=size)
            db.session.add(m); added += 1
        except OSError:
            continue
    if added:
        db.session.commit()
        app.logger.info(f"Backfilled {added} media items")


def _migrate_sqlite(app):
    """Add new columns to existing tables if missing (SQLite)."""
    from sqlalchemy import text
    with db.engine.begin() as conn:
        def add(table, col, ddl):
            cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            if col not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
        for col, ddl in (("zoom_meeting_id", "VARCHAR(64)"),
                         ("zoom_passcode", "VARCHAR(128)"),
                         ("zoom_opens_time", "VARCHAR(16)"),
                         ("meeting_type", "VARCHAR(16) NOT NULL DEFAULT 'in_person'"),
                         ("logo_filename", "VARCHAR(500)"),
                         ("zoom_account_id", "INTEGER REFERENCES zoom_account(id)"),
                         ("zoom_link", "VARCHAR(1000)"),
                         ("alert_message", "TEXT"),
                         ("archived_at", "DATETIME"),
                         ("show_otp", "BOOLEAN NOT NULL DEFAULT 1")):
            add("meeting", col, ddl)
        for col, ddl in (("alert_message", "TEXT"),):
            add("library", col, ddl)
        for col, ddl in (("mode", "VARCHAR(16) NOT NULL DEFAULT 'all'"),):
            add("meeting_libraries", col, ddl)
        for col, ddl in (("position", "INTEGER NOT NULL DEFAULT 0"),):
            add("meeting_file", col, ddl)
        for col, ddl in (("opens_time", "VARCHAR(8)"),):
            add("meeting_schedule", col, ddl)
        for col, ddl in (("location_type", "VARCHAR(16) NOT NULL DEFAULT 'in_person'"),
                         ("address", "VARCHAR(500)"),
                         ("maps_url", "VARCHAR(1000)")):
            add("location", col, ddl)
        for col, ddl in (("footer_logo_filename", "VARCHAR(500)"),
                         ("footer_logo_url", "VARCHAR(1000)"),
                         ("footer_logo_width", "INTEGER"),
                         ("intergroup_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("ig_intro", "TEXT"),
                         ("ig_webmail_url", "VARCHAR(1000)"),
                         ("ig_incoming_host", "VARCHAR(255)"),
                         ("ig_incoming_port", "VARCHAR(16)"),
                         ("ig_outgoing_host", "VARCHAR(255)"),
                         ("ig_outgoing_port", "VARCHAR(16)"),
                         ("ig_setup_notes", "TEXT"),
                         ("ig_learn_more_url", "VARCHAR(1000)"),
                         ("ig_page_title", "VARCHAR(120)"),
                         ("dash_show_stats", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_intergroup", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_meetings", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_libraries", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_files", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_pic", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("pic_name", "VARCHAR(200)"),
                         ("pic_email", "VARCHAR(255)"),
                         ("pic_phone", "VARCHAR(64)"),
                         ("zoom_tech_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("zoom_tech_title", "VARCHAR(120)"),
                         ("zoom_tech_content", "TEXT"),
                         ("zoom_tech_blocks_json", "TEXT"),
                         ("zoom_tech_template", "VARCHAR(16) NOT NULL DEFAULT 'standard'"),
                         ("smtp_host", "VARCHAR(255)"),
                         ("smtp_port", "INTEGER"),
                         ("smtp_username", "VARCHAR(255)"),
                         ("smtp_password_enc", "BLOB"),
                         ("smtp_from_email", "VARCHAR(255)"),
                         ("smtp_from_name", "VARCHAR(200)"),
                         ("smtp_security", "VARCHAR(16) NOT NULL DEFAULT 'starttls'"),
                         ("access_request_to", "VARCHAR(500)"),
                         ("login_particle_effect", "VARCHAR(32) NOT NULL DEFAULT 'stars'"),
                         ("login_bg_color", "VARCHAR(32)"),
                         ("login_bg_colors", "TEXT"),
                         ("login_particle_speed", "INTEGER NOT NULL DEFAULT 85"),
                         ("login_particle_size", "INTEGER NOT NULL DEFAULT 185"),
                         ("login_transition_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("turnstile_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("turnstile_site_key", "VARCHAR(128)"),
                         ("turnstile_secret_key_enc", "BLOB")):
            add("site_setting", col, ddl)
        for col, ddl in (("url", "VARCHAR(1000)"),
                         ("stored_filename", "VARCHAR(500)"),
                         ("original_filename", "VARCHAR(500)"),
                         ("thumbnail_filename", "VARCHAR(500)"),
                         ("position", "INTEGER NOT NULL DEFAULT 0")):
            add("reading", col, ddl)


def _seed_admin(app):
    from werkzeug.security import generate_password_hash
    if User.query.count() == 0:
        username = os.environ.get("TSP_ADMIN_USERNAME", "admin")
        password = os.environ.get("TSP_ADMIN_PASSWORD", "admin")
        email = os.environ.get("TSP_ADMIN_EMAIL", "admin@example.com")
        u = User(username=username, email=email,
                 password_hash=generate_password_hash(password), role="admin")
        db.session.add(u)
        db.session.commit()
        app.logger.info(f"Seeded admin user: {username}")
