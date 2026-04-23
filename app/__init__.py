# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import os
from datetime import timedelta
import bleach
import markdown as md_lib
from markupsafe import Markup
from flask import Flask, request, redirect
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from .models import db, User, MediaItem, MeetingFile, Reading, UrlRedirect

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"
csrf = CSRFProtect()


def create_app():
    app = Flask(__name__, instance_relative_config=False)

    data_dir = os.path.abspath(os.environ.get("TSP_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")))
    upload_dir = os.path.abspath(os.environ.get("TSP_UPLOAD_DIR", os.path.join(data_dir, "uploads")))
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(upload_dir, exist_ok=True)

    # Secret key: fail loudly in production if unset or still the placeholder.
    secret_key = os.environ.get("TSP_SECRET_KEY", "").strip()
    is_debug = os.environ.get("TSP_DEBUG", "").lower() in ("1", "true", "yes")
    if not secret_key or secret_key == "dev-secret-change-me":
        if is_debug:
            secret_key = secret_key or "dev-secret-change-me"
        else:
            raise RuntimeError(
                "TSP_SECRET_KEY is required. Set a random 32+ byte value via "
                "environment variable. The bundled installer generates one automatically."
            )

    # Secure cookies when not running in debug mode (HTTPS expected in prod).
    cookie_secure = not is_debug

    db_path = os.path.join(data_dir, "tsp.db")
    app.config.update(
        SECRET_KEY=secret_key,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=upload_dir,
        MAX_CONTENT_LENGTH=256 * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(days=180),
        REMEMBER_COOKIE_DURATION=timedelta(days=180),
        REMEMBER_COOKIE_SAMESITE="Lax",
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SECURE=cookie_secure,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=cookie_secure,
        WTF_CSRF_TIME_LIMIT=None,  # tie to session lifetime, not a 1-hour window
    )

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

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
    SAFE_PROTOCOLS = ["http", "https", "mailto", "tel"]

    # Broader allowlist for admin-authored rich HTML (markdown output, legacy
    # zoom-tech content). Blocks <script>, event handlers, javascript: URIs, etc.
    SAFE_RICH_TAGS = SAFE_TAGS | {
        "p", "div", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "li", "blockquote", "pre",
        "img", "figure", "figcaption",
        "table", "thead", "tbody", "tr", "th", "td",
    }
    SAFE_RICH_ATTRS = {
        "*": ["class", "id"],
        "a": ["href", "title", "target", "rel"],
        "abbr": ["title"],
        "img": ["src", "alt", "title", "width", "height"],
        "span": ["class"],
        "td": ["colspan", "rowspan"],
        "th": ["colspan", "rowspan", "scope"],
    }

    @app.template_filter("safe_html")
    def safe_html(value):
        if not value:
            return ""
        cleaned = bleach.clean(str(value), tags=SAFE_TAGS, attributes=SAFE_ATTRS,
                               protocols=SAFE_PROTOCOLS, strip=True)
        return Markup(cleaned)

    @app.template_filter("safe_rich_html")
    def safe_rich_html(value):
        """For admin-authored rich HTML (zoom_tech_content, markdown output)."""
        if not value:
            return ""
        cleaned = bleach.clean(str(value), tags=SAFE_RICH_TAGS, attributes=SAFE_RICH_ATTRS,
                               protocols=SAFE_PROTOCOLS, strip=True)
        return Markup(cleaned)

    @app.template_filter("markdown")
    def markdown_filter(value):
        if not value:
            return ""
        html = md_lib.markdown(str(value), extensions=["extra", "nl2br", "sane_lists"])
        cleaned = bleach.clean(html, tags=SAFE_RICH_TAGS, attributes=SAFE_RICH_ATTRS,
                               protocols=SAFE_PROTOCOLS, strip=True)
        return Markup(cleaned)

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
    from .routes import bp as main_bp, public_bp
    from .frontend import bp as frontend_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(frontend_bp)

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
    def _security_headers(response):
        # Cache-control: stops Cloudflare/browsers from caching per-user pages
        # and stale form responses. /static/ and /pub/ are deterministic.
        path = request.path or ""
        if not (path.startswith("/static/") or path.startswith("/pub/")):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers.setdefault("Pragma", "no-cache")
            response.headers.setdefault("Expires", "0")

        # Common security headers, applied to every response.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy",
                                    "geolocation=(), microphone=(), camera=(), payment=()")
        # HSTS only makes sense when served over TLS; Caddy also adds it in prod.
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security",
                                        "max-age=31536000; includeSubDomains")
        # Loose CSP: allow inline scripts/styles (app relies on them) and the Turnstile
        # origin; block framing from other origins and block object/embed/base hijacks.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data: blob:; "
            "media-src 'self' blob:; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; "
            "frame-src 'self' https://challenges.cloudflare.com; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'self'"
        )
        return response

    with app.app_context():
        # Race-safe: two gunicorn workers can both run create_all at boot.
        # The loser sees "table already exists" — tolerate it rather than
        # crashing.
        from sqlalchemy.exc import OperationalError
        try:
            db.create_all()
        except OperationalError as e:
            if "already exists" not in str(e).lower():
                raise
        _migrate_sqlite(app)
        _seed_admin(app)
        _backfill_media(app)

    from .metrics import prime as _prime_metrics
    _prime_metrics()

    from .icons import icon as _icon
    app.jinja_env.globals["icon"] = _icon

    from .version import __version__ as _app_version, __build_id__ as _app_build_id
    app.jinja_env.globals["app_version"] = _app_version
    app.jinja_env.globals["app_build_id"] = _app_build_id

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
    """Add new columns to existing tables if missing (SQLite).

    Worker-safe: two gunicorn workers starting in parallel can both see the
    column missing via PRAGMA and race on ALTER TABLE. The loser catches the
    duplicate-column error instead of crashing the boot.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    with db.engine.begin() as conn:
        def add(table, col, ddl):
            cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            if col in cols:
                return
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
            except OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
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
                         ("dash_show_server_metrics", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_order_json", "TEXT"),
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
                         ("turnstile_secret_key_enc", "BLOB"),
                         ("og_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("og_title", "VARCHAR(200)"),
                         ("og_description", "TEXT"),
                         ("og_image_filename", "VARCHAR(500)"),
                         ("frontend_module_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("frontend_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("frontend_title", "VARCHAR(200)"),
                         ("frontend_tagline", "VARCHAR(500)"),
                         ("frontend_hero_heading", "VARCHAR(200)"),
                         ("frontend_hero_subheading", "VARCHAR(500)"),
                         ("frontend_about_heading", "VARCHAR(200)"),
                         ("frontend_about_body", "TEXT"),
                         ("frontend_contact_heading", "VARCHAR(200)"),
                         ("frontend_contact_body", "TEXT"),
                         ("frontend_footer_text", "TEXT"),
                         ("frontend_header_width_mode", "VARCHAR(16) NOT NULL DEFAULT 'boxed'"),
                         ("frontend_header_max_width", "INTEGER NOT NULL DEFAULT 1160"),
                         ("frontend_header_padding_pct", "INTEGER NOT NULL DEFAULT 5"),
                         ("frontend_header_height", "INTEGER NOT NULL DEFAULT 72"),
                         ("frontend_header_template", "VARCHAR(64) NOT NULL DEFAULT 'classic'"),
                         ("frontend_footer_template", "VARCHAR(64) NOT NULL DEFAULT 'classic'"),
                         ("frontend_homepage_template", "VARCHAR(64) NOT NULL DEFAULT 'classic'"),
                         ("frontend_megamenu_template", "VARCHAR(64) NOT NULL DEFAULT 'dccma'"),
                         ("frontend_mega_bg_color", "VARCHAR(16) NOT NULL DEFAULT '#0B5CFF'"),
                         ("frontend_mega_text_color", "VARCHAR(16) NOT NULL DEFAULT '#ffffff'"),
                         ("frontend_mega_radius_bl", "INTEGER NOT NULL DEFAULT 18"),
                         ("frontend_mega_radius_br", "INTEGER NOT NULL DEFAULT 18"),
                         ("frontend_logo_filename", "VARCHAR(500)"),
                         ("frontend_logo_width", "INTEGER NOT NULL DEFAULT 40"),
                         ("top_alert_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("top_alert_message", "TEXT"),
                         ("top_alert_bg_color", "VARCHAR(16)"),
                         ("top_alert_text_color", "VARCHAR(16)"),
                         ("top_alert_icon", "VARCHAR(32)"),
                         ("top_alert_icon_position", "VARCHAR(8) NOT NULL DEFAULT 'before'"),
                         ("header_alert_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("header_alert_message", "TEXT"),
                         ("header_alert_bg_color", "VARCHAR(16)"),
                         ("header_alert_text_color", "VARCHAR(16)"),
                         ("header_alert_icon", "VARCHAR(32)"),
                         ("header_alert_icon_position", "VARCHAR(8) NOT NULL DEFAULT 'before'"),
                         ("setup_complete", "BOOLEAN NOT NULL DEFAULT 0")):
            add("site_setting", col, ddl)
        for col, ddl in (("url", "VARCHAR(1000)"),
                         ("stored_filename", "VARCHAR(500)"),
                         ("original_filename", "VARCHAR(500)"),
                         ("thumbnail_filename", "VARCHAR(500)"),
                         ("position", "INTEGER NOT NULL DEFAULT 0")):
            add("reading", col, ddl)
        for col, ddl in (("dash_show_stats", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_intergroup", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_meetings", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_libraries", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_files", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_server_metrics", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_online_users", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_access_requests", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_order_json", "TEXT"),
                         ("last_seen_at", "DATETIME")):
            add("user", col, ddl)
        for col, ddl in (("open_in_new_tab", "BOOLEAN NOT NULL DEFAULT 0"),):
            add("frontend_nav_item", col, ddl)
        for col, ddl in (("kind", "VARCHAR(16) NOT NULL DEFAULT 'link'"),
                         ("button_style", "VARCHAR(16) NOT NULL DEFAULT 'pill'"),
                         ("open_in_new_tab", "BOOLEAN NOT NULL DEFAULT 0")):
            add("frontend_nav_link", col, ddl)


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
