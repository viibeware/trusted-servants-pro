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
from .models import db, User, MediaItem, MeetingFile, LibraryItem, UrlRedirect

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
        DATA_DIR=data_dir,
        DB_PATH=db_path,
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
        _seed_custom_layouts(app)
        _backfill_media(app)
        # Boot-time recycle-bin sweep. The Delete Log page also runs
        # this lazily on every visit; the boot sweep covers installs
        # whose admin doesn't routinely open the page.
        try:
            from . import trash as _trash
            _trash.expire_old()
        except Exception:
            db.session.rollback()

    # Daily SQLite snapshot. Runs every boot; no-op when today's
    # snapshot already exists. Pruned to the most recent 14 days.
    # Defensive — any failure is logged, never raised, so a backup
    # hiccup can't block the app from coming up.
    try:
        from .backup import daily_snapshot, list_snapshots as _list_snapshots
        daily_snapshot(app)

        def _snapshots_for_template():
            try:
                return _list_snapshots(app)
            except Exception:  # noqa: BLE001
                return []
        app.jinja_env.globals["db_snapshots"] = _snapshots_for_template
    except Exception:  # noqa: BLE001
        app.logger.exception("daily_snapshot crashed during boot")
        app.jinja_env.globals["db_snapshots"] = lambda: []

    from .metrics import prime as _prime_metrics
    _prime_metrics()

    from .icons import icon as _icon
    app.jinja_env.globals["icon"] = _icon

    from .colors import (dark_variant as _dark_variant, hex_lightness as _hex_lightness,
                         avg_lightness as _avg_lightness, slugify as _slugify)
    app.jinja_env.filters["dark_variant"] = _dark_variant
    app.jinja_env.filters["hex_lightness"] = _hex_lightness
    app.jinja_env.filters["avg_lightness"] = _avg_lightness
    app.jinja_env.filters["slugify"] = _slugify

    from .version import __version__ as _app_version, __build_id__ as _app_build_id
    app.jinja_env.globals["app_version"] = _app_version
    app.jinja_env.globals["app_build_id"] = _app_build_id

    # Slug-change history rows for a given (kind, entity_id) pair, ordered
    # newest-first. Used by the URL-history timeline rendered on the
    # meeting and post edit screens.
    def _slug_history_rows(kind, entity_id):
        from .models import EntitySlugHistory
        if not entity_id:
            return []
        return (EntitySlugHistory.query
                .filter_by(entity_type=kind, entity_id=entity_id)
                .order_by(EntitySlugHistory.changed_at.desc())
                .all())
    app.jinja_env.globals["slug_history_rows"] = _slug_history_rows

    # Make THEMES available to every template so the global theme picker
    # in the Web Frontend admin top bar always has its option list without
    # threading it through every render_template call.
    from .frontend import THEMES as _THEMES
    app.jinja_env.globals["frontend_themes"] = _THEMES

    # Font helpers — resolve_fonts/font_css_vars are used by the public
    # base template to set semantic --fe-font-* CSS variables per theme.
    # frontend_fonts is now a callable that merges vendored fonts with
    # admin-uploaded CustomFont rows, so pickers reflect new uploads.
    from .fonts import (
        font_css_vars as _font_css_vars,
        all_fonts as _all_fonts,
        custom_fonts as _custom_fonts,
        ROLES as _FONT_ROLES,
    )
    app.jinja_env.globals["font_css_vars"] = _font_css_vars
    app.jinja_env.globals["frontend_fonts"] = _all_fonts
    app.jinja_env.globals["custom_fonts"] = _custom_fonts
    app.jinja_env.globals["frontend_font_roles"] = _FONT_ROLES

    # Site-wide design tokens. Same layered model as fonts: theme
    # defaults + per-site overrides → flat dict + a CSS-vars string the
    # public base template inlines on <body>.
    from .design import (
        design_css_vars as _design_css_vars,
        resolve_design as _resolve_design,
        derive_dark_color as _derive_dark_color,
        DESIGN_FIELDS as _DESIGN_FIELDS,
        DESIGN_GROUPS as _DESIGN_GROUPS,
        SPACING_SCALE as _SPACING_SCALE,
        RADIUS_SCALE as _RADIUS_SCALE,
        SHADOW_SCALE as _SHADOW_SCALE,
        THEME_DEFAULTS as _DESIGN_THEME_DEFAULTS,
    )
    app.jinja_env.globals["design_css_vars"] = _design_css_vars
    app.jinja_env.globals["resolve_design"] = _resolve_design
    app.jinja_env.globals["derive_dark_color"] = _derive_dark_color
    app.jinja_env.globals["design_fields"] = _DESIGN_FIELDS
    app.jinja_env.globals["design_groups"] = _DESIGN_GROUPS
    app.jinja_env.globals["design_spacing_scale"] = _SPACING_SCALE
    app.jinja_env.globals["design_radius_scale"] = _RADIUS_SCALE
    app.jinja_env.globals["design_shadow_scale"] = _SHADOW_SCALE
    app.jinja_env.globals["design_theme_defaults"] = _DESIGN_THEME_DEFAULTS

    # Sidebar data layer — single source of truth for what shows up in
    # the main sidebar, with sorting + manual ordering applied.
    from .sidebar import build_sidebar as _build_sidebar, admin_reorder_catalog as _sidebar_catalog
    from flask import url_for as _url_for, request as _req
    from flask_login import current_user as _cu

    def _sidebar_for_template(site, nav_links):
        return _build_sidebar(site, _cu, _req.endpoint, nav_links, _url_for)

    app.jinja_env.globals["sidebar_data"] = _sidebar_for_template
    app.jinja_env.globals["sidebar_reorder_catalog"] = _sidebar_catalog

    # Per-module role gating tiers.
    from .permissions import ROLE_TIERS as _ROLE_TIERS, user_meets_role as _user_meets_role
    app.jinja_env.globals["role_tiers"] = _ROLE_TIERS
    app.jinja_env.globals["user_meets_role"] = _user_meets_role

    # ── 404 error handler ────────────────────────────────────────────
    # Three render paths:
    #   /tspro/*                              → playful admin 404
    #   any non-/tspro URL + module enabled   → customizable public 404
    #   any non-/tspro URL + module disabled  → branch on auth:
    #       authenticated → admin 404 (they're already in)
    #       unauth        → redirect to /tspro login so they can sign in
    from flask import render_template, request as _request, redirect, url_for
    from flask_login import current_user as _current_user
    from .models import SiteSetting as _SiteSetting

    @app.errorhandler(404)
    def _handle_404(_err):
        path = (_request.path or "")
        if path.startswith("/tspro"):
            return render_template("404.html"), 404
        try:
            s = _SiteSetting.query.first()
        except Exception:  # noqa: BLE001 — DB might be unavailable mid-boot
            s = None
        if s and getattr(s, "frontend_module_enabled", False):
            # Build the full frontend context so the 404 page renders
            # with the active theme's header / footer / mega menu (the
            # template defaults to Classic when those keys aren't set).
            from .frontend import _frontend_context
            return render_template("frontend/404.html",
                                   **_frontend_context(s)), 404
        # Module off: redirect anonymous visitors to login, render the
        # admin 404 for anyone already authenticated.
        if _current_user.is_authenticated:
            return render_template("404.html"), 404
        return redirect(url_for("auth.login"))

    return app


def _backfill_media(app):
    """Index any stored_filenames referenced by MeetingFile/LibraryItem into MediaItem."""
    upload_dir = app.config["UPLOAD_FOLDER"]
    known = {m.stored_filename for m in MediaItem.query.all()}
    candidates = set()
    for row in db.session.query(MeetingFile.stored_filename, MeetingFile.original_filename).all():
        if row[0] and row[0] not in known:
            candidates.add((row[0], row[1] or row[0]))
    for row in db.session.query(LibraryItem.stored_filename, LibraryItem.original_filename).all():
        if row[0] and row[0] not in known:
            candidates.add((row[0], row[1] or row[0]))
    for row in db.session.query(LibraryItem.thumbnail_filename).filter(LibraryItem.thumbnail_filename.isnot(None)).all():
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
    newly_added = set()  # (table, col) tuples added in this boot
    with db.engine.begin() as conn:
        def add(table, col, ddl):
            cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            if col in cols:
                return
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                newly_added.add((table, col))
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
                         ("public_alert_message", "TEXT"),
                         ("slug", "VARCHAR(255)"),
                         ("archived_at", "DATETIME"),
                         ("show_otp", "BOOLEAN NOT NULL DEFAULT 1")):
            add("meeting", col, ddl)
        for col, ddl in (("alert_message", "TEXT"),
                         ("is_intergroup", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("categories_required", "BOOLEAN NOT NULL DEFAULT 1")):
            add("library", col, ddl)
        # On the boot that first added is_intergroup, flag the two
        # pre-existing default Intergroup libraries so the permission
        # gate (now keyed on the column) keeps working for upgraded
        # installs that already had those rows.
        if ("library", "is_intergroup") in newly_added:
            from .models import INTERGROUP_LIBRARY_NAMES
            placeholders = ",".join(f":n{i}" for i in range(len(INTERGROUP_LIBRARY_NAMES)))
            params = {f"n{i}": n for i, n in enumerate(INTERGROUP_LIBRARY_NAMES)}
            conn.execute(text(
                f"UPDATE library SET is_intergroup = 1 WHERE name IN ({placeholders})"
            ), params)
        # The frontend_editor role was retired in favor of admin-only
        # Web Frontend access. Demote any pre-existing frontend_editor
        # user to editor (they keep their broad editor authority — the
        # only thing they lose is the Web Frontend module, which is now
        # admin-only). Run on every boot rather than guarded on a column
        # add: there's no schema flag indicating "FE users have been
        # migrated", so we let the UPDATE be a cheap no-op when the
        # role doesn't appear in the table.
        conn.execute(text(
            "UPDATE user SET role = 'editor' WHERE role = 'frontend_editor'"))
        # Same idea on SiteSetting.frontend_module_required_role — flip
        # any lingering 'frontend_editor' value to 'admin' so the module
        # gate resolves cleanly under the new role set.
        conn.execute(text(
            "UPDATE site_setting SET frontend_module_required_role = 'admin' "
            "WHERE frontend_module_required_role = 'frontend_editor'"))
        for col, ddl in (("mode", "VARCHAR(16) NOT NULL DEFAULT 'all'"),):
            add("meeting_libraries", col, ddl)
        for col, ddl in (("position", "INTEGER NOT NULL DEFAULT 0"),
                         ("public_visible", "BOOLEAN NOT NULL DEFAULT 0")):
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
                         ("site_url", "VARCHAR(255)"),
                         ("intergroup_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("intergroup_module_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("intergroup_module_required_role", "VARCHAR(32) NOT NULL DEFAULT 'viewer'"),
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
                         ("posts_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("intergroup_required_role", "VARCHAR(32) NOT NULL DEFAULT 'viewer'"),
                         ("zoom_tech_required_role", "VARCHAR(32) NOT NULL DEFAULT 'viewer'"),
                         ("posts_required_role", "VARCHAR(32) NOT NULL DEFAULT 'admin'"),
                         ("frontend_module_required_role", "VARCHAR(32) NOT NULL DEFAULT 'admin'"),
                         ("sidebar_sort_mode", "VARCHAR(16) NOT NULL DEFAULT 'auto-asc'"),
                         ("sidebar_order_json", "TEXT"),
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
                         ("frontend_og_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("frontend_og_title", "VARCHAR(200)"),
                         ("frontend_og_description", "TEXT"),
                         ("frontend_og_image_filename", "VARCHAR(500)"),
                         ("frontend_favicon_filename", "VARCHAR(500)"),
                         ("frontend_design_json", "TEXT"),
                         ("frontend_404_heading", "VARCHAR(200)"),
                         ("frontend_404_subheading", "TEXT"),
                         ("frontend_404_cta_label", "VARCHAR(120)"),
                         ("frontend_404_cta_url", "VARCHAR(500)"),
                         ("frontend_404_image_filename", "VARCHAR(500)"),
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
                         ("frontend_megamenu_template", "VARCHAR(64) NOT NULL DEFAULT 'recovery-blue'"),
                         ("frontend_meeting_template", "VARCHAR(64) NOT NULL DEFAULT 'classic'"),
                         ("frontend_event_template", "VARCHAR(64) NOT NULL DEFAULT 'classic'"),
                         ("frontend_template_settings_json", "TEXT"),
                         ("frontend_theme", "VARCHAR(64) NOT NULL DEFAULT 'classic'"),
                         ("frontend_fonts_json", "TEXT"),
                         ("frontend_blocks_json", "TEXT"),
                         ("frontend_mega_bg_color", "VARCHAR(16) NOT NULL DEFAULT '#0B5CFF'"),
                         ("frontend_mega_text_color", "VARCHAR(16) NOT NULL DEFAULT '#ffffff'"),
                         ("frontend_mega_radius_bl", "INTEGER NOT NULL DEFAULT 18"),
                         ("frontend_mega_radius_br", "INTEGER NOT NULL DEFAULT 18"),
                         ("frontend_megamenu_animate", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("frontend_megamenu_animate_ms", "INTEGER NOT NULL DEFAULT 320"),
                         ("frontend_tagline_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("frontend_hero_heading_font", "VARCHAR(32) NOT NULL DEFAULT 'fraunces'"),
                         ("frontend_hero_heading_size", "INTEGER NOT NULL DEFAULT 100"),
                         ("frontend_hero_heading_grad_start", "VARCHAR(16)"),
                         ("frontend_hero_heading_grad_end", "VARCHAR(16)"),
                         ("frontend_hero_text_dynamic", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("frontend_hero_bg_style", "VARCHAR(16) NOT NULL DEFAULT 'frosty'"),
                         ("frontend_hero_bg_color", "VARCHAR(16)"),
                         ("frontend_hero_bg_color_2", "VARCHAR(16)"),
                         ("frontend_hero_bg_gradient_angle", "INTEGER NOT NULL DEFAULT 180"),
                         ("frontend_hero_bg_hue", "INTEGER NOT NULL DEFAULT 225"),
                         ("frontend_hero_bg_hue_2", "INTEGER NOT NULL DEFAULT 170"),
                         ("frontend_hero_bg_blur", "INTEGER NOT NULL DEFAULT 80"),
                         ("frontend_hero_bg_opacity", "INTEGER NOT NULL DEFAULT 45"),
                         ("frontend_hero_bg_randomize", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("frontend_hero_bg_image_filename", "VARCHAR(500)"),
                         ("frontend_hero_bg_image_mode", "VARCHAR(16) NOT NULL DEFAULT 'cover'"),
                         ("frontend_hero_bg_image_scale", "INTEGER NOT NULL DEFAULT 100"),
                         ("frontend_hero_bg_video_filename", "VARCHAR(500)"),
                         ("frontend_hero_bg_video_mode", "VARCHAR(16) NOT NULL DEFAULT 'loop'"),
                         ("frontend_hero_bg_video_speed", "INTEGER NOT NULL DEFAULT 100"),
                         ("frontend_hero_sinewave_colors", "TEXT"),
                         ("frontend_hero_particle_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("frontend_hero_particle_effect", "VARCHAR(32) NOT NULL DEFAULT 'stars'"),
                         ("frontend_hero_particle_speed", "INTEGER NOT NULL DEFAULT 100"),
                         ("frontend_hero_particle_size", "INTEGER NOT NULL DEFAULT 100"),
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
                         ("position", "INTEGER NOT NULL DEFAULT 0"),
                         ("created_by", "INTEGER REFERENCES user(id)")):
            add("reading", col, ddl)
        for col, ddl in (("dash_show_stats", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_intergroup", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_meetings", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_libraries", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_files", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_server_metrics", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_online_users", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_access_requests", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_deletions", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_currently_online", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_order_json", "TEXT"),
                         ("last_seen_at", "DATETIME"),
                         ("phone", "VARCHAR(64)"),
                         ("last_endpoint", "VARCHAR(128)"),
                         ("last_path", "VARCHAR(500)"),
                         ("password_reset_allowed", "BOOLEAN NOT NULL DEFAULT 1")):
            add("user", col, ddl)
        for col, ddl in (("open_in_new_tab", "BOOLEAN NOT NULL DEFAULT 0"),):
            add("frontend_nav_item", col, ddl)
        for col, ddl in (("asset_files_json", "TEXT"),):
            add("custom_font", col, ddl)
        for col, ddl in (("is_draft", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("slug", "VARCHAR(255)")):
            add("post", col, ddl)
        for col, ddl in (("is_archived", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("archived_at", "DATETIME")):
            add("access_request", col, ddl)
        for col, ddl in (("kind", "VARCHAR(16) NOT NULL DEFAULT 'link'"),
                         ("button_style", "VARCHAR(16) NOT NULL DEFAULT 'pill'"),
                         ("open_in_new_tab", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("icon_before_color", "VARCHAR(16)"),
                         ("icon_after_color", "VARCHAR(16)"),
                         ("icon_before_size", "INTEGER"),
                         ("icon_after_size", "INTEGER"),
                         ("link_size", "VARCHAR(16)"),
                         ("override_color", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("custom_color", "VARCHAR(16)")):
            add("frontend_nav_link", col, ddl)

        # One-shot data migration: when the new frontend_og_* columns are
        # added on an existing deployment, seed them from the legacy og_*
        # columns. The frontend Branding admin page used to write to og_*,
        # so existing public-site link previews would otherwise vanish on
        # upgrade.
        if ("site_setting", "frontend_og_enabled") in newly_added:
            conn.execute(text(
                "UPDATE site_setting SET "
                "frontend_og_enabled = og_enabled, "
                "frontend_og_title = og_title, "
                "frontend_og_description = og_description, "
                "frontend_og_image_filename = og_image_filename"
            ))

        # Internal theme key was renamed dccma → recovery-blue. Sweep
        # any stored keys forward each boot — idempotent (no-op once
        # nothing references the old key) and cheap.
        conn.execute(text(
            "UPDATE site_setting SET "
            "frontend_theme            = CASE WHEN frontend_theme            = 'dccma' THEN 'recovery-blue' ELSE frontend_theme            END, "
            "frontend_header_template  = CASE WHEN frontend_header_template  = 'dccma' THEN 'recovery-blue' ELSE frontend_header_template  END, "
            "frontend_footer_template  = CASE WHEN frontend_footer_template  = 'dccma' THEN 'recovery-blue' ELSE frontend_footer_template  END, "
            "frontend_homepage_template = CASE WHEN frontend_homepage_template = 'dccma' THEN 'recovery-blue' ELSE frontend_homepage_template END, "
            "frontend_megamenu_template = CASE WHEN frontend_megamenu_template = 'dccma' THEN 'recovery-blue' ELSE frontend_megamenu_template END"
        ))


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


def _seed_custom_layouts(app):
    """Insert / refresh the pre-built marketing layout presets. Custom
    layouts created via the drag-and-drop builder are kept untouched —
    only rows with ``is_prebuilt = True`` get re-seeded."""
    import json
    from .models import CustomLayout
    PRESETS = [
        {
            "key": "classic",
            "name": "Classic",
            "description": "Hero, four quick-link cards, upcoming meetings, about pillars, and a contact card. Our original homepage layout.",
            "blocks": ["hero", "quick_links", "meetings", "about", "contact"],
        },
        {
            "key": "long-form",
            "name": "Long-form",
            "description": "Story-driven layout: hero, about pillars, three-up features, testimonials, contact. Best for fellowships that want to share their story before the call to action.",
            "blocks": ["hero", "about", "features", "testimonials", "contact"],
        },
        {
            "key": "features-focus",
            "name": "Features focus",
            "description": "Hero, then three feature columns, then a bold call-to-action banner, then contact. Conversion-friendly.",
            "blocks": ["hero", "features", "cta", "contact"],
        },
        {
            "key": "social-proof",
            "name": "Social proof",
            "description": "Hero, stats row, three-up features, testimonials, CTA, contact. Lots of validation cues for newcomers.",
            "blocks": ["hero", "stats", "features", "testimonials", "cta", "contact"],
        },
        {
            "key": "support-first",
            "name": "Support-first",
            "description": "Hero with a prominent CTA, the meetings list immediately below, then about + contact. Best when finding a meeting is the most-clicked action.",
            "blocks": ["hero", "cta", "meetings", "about", "contact"],
        },
        {
            "key": "info-dense",
            "name": "Info-dense",
            "description": "Hero, four quick links, three-up features, FAQ accordion, contact. Great for portals with lots of pre-meeting questions to answer.",
            "blocks": ["hero", "quick_links", "features", "faq", "contact"],
        },
        {
            "key": "minimal",
            "name": "Minimal",
            "description": "Just hero + contact card. Use this when the rest of the site does the heavy lifting.",
            "blocks": ["hero", "contact"],
        },
    ]
    for p in PRESETS:
        row = CustomLayout.query.filter_by(key=p["key"]).first()
        blocks_json = json.dumps([{"type": b} for b in p["blocks"]])
        if row is None:
            db.session.add(CustomLayout(
                key=p["key"], name=p["name"], description=p["description"],
                blocks_json=blocks_json, kind="homepage", is_prebuilt=True,
            ))
        elif row.is_prebuilt:
            row.name = p["name"]
            row.description = p["description"]
            row.blocks_json = blocks_json
    db.session.commit()
