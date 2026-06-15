# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import os
from datetime import datetime, timedelta
import bleach
import markdown as md_lib
from markupsafe import Markup
from flask import Flask, request, redirect
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from .models import db, User, MediaItem, MeetingFile, LibraryItem, UrlRedirect

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"
csrf = CSRFProtect()


class _CloudflareRemoteAddr:
    """Rewrite ``REMOTE_ADDR`` from Cloudflare's ``CF-Connecting-IP`` header.

    When the app is fronted by Cloudflare (Cloudflare → Caddy → gunicorn),
    the real visitor IP rides in ``CF-Connecting-IP`` as a single,
    Cloudflare-set value. That's more reliable than counting
    ``X-Forwarded-For`` hops: the XFF chain length varies (Cloudflare +
    Caddy = two entries), so a fixed ``ProxyFix(x_for=1)`` peels off only
    the last hop and lands on the Cloudflare edge IP (e.g. 172.71.x.x)
    instead of the client. Reading the dedicated header sidesteps the
    hop-count guesswork entirely.

    Wired up *inside* ProxyFix so it runs after XFF processing and wins
    when the header is present, while still falling back to ProxyFix's
    XFF result (and to the bare socket ``REMOTE_ADDR``) when it isn't.
    Only installed when a proxy is trusted, so direct-bind deploys never
    honor a header a client could forge; disable explicitly with
    ``TSP_TRUST_CF_HEADER=0`` if a non-Cloudflare proxy sits in front.
    """

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        cf_ip = environ.get("HTTP_CF_CONNECTING_IP")
        if cf_ip:
            environ["REMOTE_ADDR"] = cf_ip.strip()
        return self.app(environ, start_response)


def create_app():
    app = Flask(__name__, instance_relative_config=False)
    # Accept URLs with or without a trailing slash. Werkzeug's
    # default behaviour 404s ``/foo/`` when the route was declared
    # as ``/foo`` (and vice-versa) — flipping this once on the URL
    # map relaxes the rule globally so external links / typos with
    # a stray trailing slash still resolve. Routes that need to
    # enforce one form can override per-rule via ``strict_slashes``
    # on the decorator.
    app.url_map.strict_slashes = False

    # Production deploys (install.sh) front the app with Caddy → gunicorn,
    # so request.remote_addr is the Caddy container's IP unless we honor
    # X-Forwarded-For. Without this, Watchtower's IP block gate, probe
    # logger, login log, and activity log all record the docker bridge IP
    # (172.x.x.x) instead of the real client. ProxyFix is the standard
    # Flask remedy. Hop count is configurable via TSP_TRUSTED_PROXIES so
    # direct-bind deploys can disable it (set to 0) to avoid trusting
    # spoofable headers when no proxy sits in front.
    #
    # Cloudflare adds a second hop, so XFF hop-counting alone lands on the
    # CF edge IP — _CloudflareRemoteAddr (installed inside ProxyFix) reads
    # CF-Connecting-IP to recover the true client. See that class's docstring.
    try:
        _proxy_hops = int(os.environ.get("TSP_TRUSTED_PROXIES", "1"))
    except ValueError:
        _proxy_hops = 1
    if _proxy_hops > 0:
        # Added first so it sits *inside* ProxyFix: ProxyFix runs first and
        # sets REMOTE_ADDR from XFF, then this overrides it with the
        # Cloudflare header when present (and is a no-op when it isn't).
        if os.environ.get("TSP_TRUST_CF_HEADER", "1") != "0":
            app.wsgi_app = _CloudflareRemoteAddr(app.wsgi_app)
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=_proxy_hops,
            x_proto=_proxy_hops,
            x_host=_proxy_hops,
        )

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

    # Per-instance cookie names. Browsers scope cookies by hostname only
    # (NOT by port), so two instances on the same host — e.g. localhost:8090
    # prod + localhost:8091 test — collide on the default ``session`` cookie:
    # whichever side last set the cookie wins, and the other side can't
    # validate the CSRF token in any form rendered before the swap (the
    # token was signed with one TSP_SECRET_KEY; the cookie now says the
    # session belongs to the other). The visible symptom is a 400 "CSRF
    # token is missing/invalid" the moment you switch tabs and submit a
    # form. Suffixing the cookie name with a stable hash of TSP_SECRET_KEY
    # keeps each instance on its own cookie (different secret → different
    # name → no overlap) without needing any per-env config. An explicit
    # ``TSP_SESSION_COOKIE_NAME`` / ``TSP_REMEMBER_COOKIE_NAME`` env var
    # still wins when set.
    import hashlib as _hashlib
    _cookie_suffix = _hashlib.blake2b(
        secret_key.encode("utf-8"), digest_size=4
    ).hexdigest()
    session_cookie_name = os.environ.get(
        "TSP_SESSION_COOKIE_NAME", f"tspro_session_{_cookie_suffix}")
    remember_cookie_name = os.environ.get(
        "TSP_REMEMBER_COOKIE_NAME", f"tspro_remember_{_cookie_suffix}")

    db_path = os.path.join(data_dir, "tsp.db")
    # Upload cap. Default is generous (4 GiB) so full-portal restore bundles
    # — which carry the whole uploads dir + the SQLite DB inside a single
    # multipart POST — aren't truncated to HTTP 413 the moment a deployment
    # accumulates non-trivial media. Override via ``TSP_MAX_UPLOAD_MB``
    # (megabytes) for installs that need a tighter ceiling. The previous
    # 256 MiB default was a foot-gun: any prod export much past a few-hundred
    # media uploads silently failed to import on the destination.
    try:
        _max_upload_mb = int(os.environ.get("TSP_MAX_UPLOAD_MB", "4096"))
    except ValueError:
        _max_upload_mb = 4096
    app.config.update(
        SECRET_KEY=secret_key,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        DATA_DIR=data_dir,
        DB_PATH=db_path,
        UPLOAD_FOLDER=upload_dir,
        MAX_CONTENT_LENGTH=_max_upload_mb * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(days=180),
        REMEMBER_COOKIE_DURATION=timedelta(days=180),
        REMEMBER_COOKIE_NAME=remember_cookie_name,
        REMEMBER_COOKIE_SAMESITE="Lax",
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SECURE=cookie_secure,
        SESSION_COOKIE_NAME=session_cookie_name,
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

    @app.template_filter("markdown_inline")
    def markdown_inline_filter(value):
        """Inline-friendly markdown — same processing + bleach allowlist
        as `markdown`, but strips the single outer `<p>` wrapper that
        Python-Markdown adds by default. Used for contexts where the
        rendered fragment sits inside an inline element (`<span>`,
        `<li>` flow content) — the wrapping `<p>` would force a block
        boundary the parser can't honour and would inflate spacing
        with paragraph margins. Multi-paragraph inputs keep all their
        `<p>` tags intact so authors can still embed line breaks when
        they want them."""
        if not value:
            return ""
        html = md_lib.markdown(str(value), extensions=["extra", "nl2br", "sane_lists"])
        cleaned = bleach.clean(html, tags=SAFE_RICH_TAGS, attributes=SAFE_RICH_ATTRS,
                               protocols=SAFE_PROTOCOLS, strip=True).strip()
        # Drop the outer <p>...</p> only when the entire fragment is
        # a SINGLE paragraph — if the inner content has its own <p>
        # tags, leave them all alone (multi-paragraph input).
        if cleaned.startswith("<p>") and cleaned.endswith("</p>"):
            inner = cleaned[3:-4]
            if "<p>" not in inner and "</p>" not in inner:
                cleaned = inner
        return Markup(cleaned)

    import re as _re

    _MD_FENCE_RE = _re.compile(r"^(?:```|~~~)")
    _MD_LIST_RE  = _re.compile(r"^\s*(?:[-*+]\s|\d+\.\s)")
    _MD_HEAD_RE  = _re.compile(r"^#{1,6}\s")
    _MD_BQ_RE    = _re.compile(r"^>\s?")

    def _markdown_block_breaks(text):
        """Insert blank lines before list items, headings, and blockquotes
        when they directly follow a non-blank line that isn't already the
        same kind of marker. Python-Markdown requires that blank line for
        the block to be recognized as a list/heading/quote — we add it for
        the user so typing `intro⏎- item` "just works". Fenced code blocks
        are passed through untouched."""
        out = []
        in_fence = False
        for line in text.split("\n"):
            if _MD_FENCE_RE.match(line):
                in_fence = not in_fence
                out.append(line); continue
            if in_fence:
                out.append(line); continue
            prev = out[-1] if out else ""
            prev_blank = prev.strip() == ""
            is_list = bool(_MD_LIST_RE.match(line))
            is_head = bool(_MD_HEAD_RE.match(line))
            is_bq   = bool(_MD_BQ_RE.match(line))
            if (is_list or is_head or is_bq) and prev and not prev_blank:
                same_kind = (
                    (is_list and _MD_LIST_RE.match(prev)) or
                    (is_head and _MD_HEAD_RE.match(prev)) or
                    (is_bq   and _MD_BQ_RE.match(prev))
                )
                if not same_kind:
                    out.append("")
            out.append(line)
        return "\n".join(out)

    @app.template_filter("markdown_block")
    def markdown_block_filter(value):
        """Block-friendly markdown rendering for admin-authored prose. Same
        allowlist as `markdown` but auto-inserts the blank line Python-
        Markdown requires before a list/heading/blockquote when the user
        types one directly under a paragraph. Hard line-breaks within a
        paragraph still work (nl2br stays on). Use this filter for fields
        where the user types `paragraph⏎- item` and expects a list. The
        standard `markdown` filter is left intact for legacy fields whose
        persisted content was authored against the no-preprocessing
        behaviour."""
        if not value:
            return ""
        prepped = _markdown_block_breaks(str(value))
        html = md_lib.markdown(prepped, extensions=["extra", "nl2br", "sane_lists"])
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

    @app.template_filter("tspro_fp")
    def tspro_fp_filter(public_key):
        """Short fingerprint of a TS Pro Backup site public key."""
        from .pubkey import fingerprint
        return fingerprint(public_key or "")

    @app.template_filter("regex_search")
    def regex_search_filter(value, pattern):
        """Run `re.search(pattern, value)` and return the match's groups
        as a list, or None when there's no match. Lets templates branch
        on a regex hit (e.g. detecting a paragraph whose only content
        is a single markdown link)."""
        import re as _re
        if value is None:
            return None
        m = _re.search(pattern, str(value))
        if not m:
            return None
        groups = m.groups()
        return list(groups) if groups else [m.group(0)]

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

    @app.template_filter("phone_fmt")
    def phone_fmt(value):
        """Display-only phone formatting — hyphenated NANP, international
        style for other country codes. See app/phone.py."""
        from .phone import format_phone
        return format_phone(value)

    @app.template_filter("fmt_site_local")
    def fmt_site_local(value, fmt="%Y-%m-%d %H:%M %Z"):
        """Format a naive-UTC datetime in the site's configured timezone.

        Every model column the app writes with ``datetime.utcnow()``
        ends up naive in the database (no tzinfo) but conventionally
        UTC. This filter attaches UTC, converts to the site's IANA
        zone, and runs ``strftime`` with the supplied format —
        ``%Z`` in the default format expands to the local tz
        abbreviation (e.g. "PDT", "PST", "EST") so the rendered value
        carries an explicit zone marker instead of an implicit one.
        Falsy / non-datetime inputs return an empty string so callers
        don't need ``{% if x %}…{% endif %}`` guards just for the
        format step. Already-aware datetimes are converted directly
        rather than double-stamped with UTC.
        """
        from datetime import datetime, timezone as _tz
        if not value or not isinstance(value, datetime):
            return ""
        from .timezone import site_timezone as _stz
        from .models import SiteSetting as _SS
        try:
            site = _SS.query.first()
        except Exception:  # noqa: BLE001 — DB hiccup; fall back to UTC
            site = None
        zone = _stz(site)
        aware = value if value.tzinfo else value.replace(tzinfo=_tz.utc)
        return aware.astimezone(zone).strftime(fmt)

    from .crypto import init_fernet
    init_fernet(app)

    @login_manager.user_loader
    def load_user(user_id):
        u = db.session.get(User, int(user_id))
        # Disabled accounts get evicted on the next request — returning
        # None here makes ``current_user`` anonymous so any
        # ``@login_required`` route bounces them to /login. Without this
        # the toggle would only take effect at next sign-in.
        if u is not None and getattr(u, "disabled", False):
            return None
        return u

    from .auth import bp as auth_bp
    from .routes import bp as main_bp, public_bp, restore_bp, frontend_sync_bp
    from .frontend import bp as frontend_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(frontend_bp)
    app.register_blueprint(restore_bp)
    app.register_blueprint(frontend_sync_bp)
    # Inbound remote-restore + frontend-sync APIs are authenticated by a
    # shared token, not a session cookie — exempt the whole blueprints from
    # form-CSRF.
    csrf.exempt(restore_bp)
    csrf.exempt(frontend_sync_bp)

    # Common attacker probe paths (env files, git internals, server config
    # files, off-the-shelf admin panels). We don't serve any of these — Flask
    # would 404 them anyway — but matching here lets us:
    #   1. Skip the heavy 404 template render (cheaper under probe storms).
    #   2. Return an empty body so nothing about the app's stack or
    #      branding is reflected back to the scanner.
    #   3. Emit a single INFO log line so production has visibility into
    #      attack patterns without filling logs with full request dumps.
    #
    # Patterns are matched against the lowercased path. Suffix tuples are
    # for filenames (`.env`, `.env.backup`, `.aws/credentials`, etc.);
    # prefix tuples gate whole directories.
    _PROBE_PATH_SUFFIXES = (
        ".env", ".env.bak", ".env.backup", ".env.local", ".env.prod",
        ".env.production", ".env.dev", ".env.development", ".env.save",
        ".env.swp", ".env.old", ".env.example", ".env~",
        "/.DS_Store", "/Thumbs.db",
        "/composer.json", "/composer.lock",
        "/package.json.bak", "/yarn.lock.bak",
        "/web.config", "/.htaccess", "/.htpasswd",
        "/id_rsa", "/id_dsa", "/.ssh/authorized_keys",
        "/credentials", "/credentials.json", "/secrets.yml", "/secrets.json",
        "/dump.sql", "/backup.sql", "/backup.zip", "/backup.tar.gz",
    )
    _PROBE_PATH_PREFIXES = (
        "/.git/", "/.svn/", "/.hg/", "/.bzr/",
        "/.aws/", "/.azure/", "/.gcp/", "/.kube/",
        "/.vscode/", "/.idea/",
        "/wp-admin/", "/wp-login.php", "/wp-content/", "/wp-includes/",
        "/xmlrpc.php",
        "/phpmyadmin/", "/pma/", "/phpmyadmin",
        "/server-status", "/server-info",
        "/.well-known/security.txt.bak",
        "/vendor/phpunit/",
        "/cgi-bin/",
        "/admin.php", "/adminer.php",
    )

    @app.before_request
    def _ip_block_gate():
        """Reject inbound traffic from admin-banned IP addresses with a
        flat 403. Runs ahead of routing + the probe gate so a banned IP
        gets dropped on every request — including assets — for the full
        duration of the ban. Hit-count + last-hit-at are stamped on the
        matching row so the Watchtower dashboard can show whether the
        ban is actually being exercised."""
        from .models import IPBlock
        ip = (request.remote_addr or "").strip()
        if not ip:
            return None
        try:
            now = datetime.utcnow()
            row = IPBlock.query.filter_by(ip=ip).first()
            if not row:
                return None
            if row.expires_at and row.expires_at <= now:
                # Lazy expiry: delete the row in-place so the dashboard
                # reflects "no longer active" the next time it polls.
                try:
                    db.session.delete(row)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                return None
            row.hit_count = (row.hit_count or 0) + 1
            row.last_hit_at = now
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
            return ("Access denied", 403, {"Cache-Control": "no-store"})
        except Exception:
            # Never let the gate break the request; log + fall through.
            app.logger.exception("ip_block_gate failed")
            db.session.rollback()
            return None

    @app.before_request
    def _block_known_probes():
        """Return a tight 404 for known attacker probe paths before the
        request flows into Flask's route matching + 404 template render.

        Why: scanners hammer for `/.env`, `/.git/config`, `/wp-admin/`,
        etc. Each one would otherwise hit our HTML 404 template — a
        ~25 KB render — and reflect site branding back at the scanner.
        Short-circuiting here keeps per-probe cost near zero and avoids
        any chance the 404 template leaks anything useful to recon.
        """
        p = (request.path or "").lower()
        # Cheap structural filter before the more expensive tuple scan —
        # legit traffic never hits these and we want the fast path tight.
        if not (p.endswith((".env",)) or "/." in p or "/wp-" in p
                or "phpmyadmin" in p or "xmlrpc.php" in p
                or "server-status" in p or "server-info" in p
                or "/cgi-bin/" in p or "admin.php" in p
                or "/vendor/" in p or "/credentials" in p
                or "/dump.sql" in p or "/backup." in p
                or p.endswith(("/web.config", "/.htaccess", "/.htpasswd",
                               "/id_rsa", "/id_dsa",
                               "/composer.json", "/composer.lock",
                               "/secrets.yml", "/secrets.json",
                               "/.ds_store", "/thumbs.db"))):
            return None
        if p.endswith(_PROBE_PATH_SUFFIXES) or any(p.startswith(pre) for pre in _PROBE_PATH_PREFIXES):
            app.logger.info("probe-block %s from %s",
                            request.path, request.remote_addr or "?")
            # Empty body + no-store. The default 404 template's branding
            # / nav would otherwise be reflected back to scanners.
            return ("", 404, {"Cache-Control": "no-store"})
        return None

    @app.before_request
    def _url_redirect_handler():
        """Look up the incoming path in the `UrlRedirect` table and 301
        to the target if a row matches. Lets admins manage arbitrary
        path → URL mappings centrally from Web Frontend → Structure →
        Redirects (covers legacy WordPress URLs, renamed pages,
        external short-links, etc.).

        Two match modes:
        - Exact (with trailing-slash tolerance) — O(log n) on the
          unique `source_path` index. Tried first; an exact rule
          always wins over a wildcard.
        - Wildcard (`/prefix/*`) — full scan of the (small,
          admin-curated) set of wildcard rows, longest-prefix winner.
          Lands every URL under the prefix on the literal target.

        Cheap early-out for static-asset prefixes so the assets path
        doesn't pay either lookup.
        """
        p = request.path or ""
        # Skip asset paths — these never redirect, but they're the
        # bulk of per-page request volume.
        if p.startswith("/static/") or p.startswith("/pub/"):
            return None
        # Trailing-slash-insensitive match: a rule stored as "/donate"
        # should also fire for "/donate/" and vice versa. Query both
        # variants in one indexed lookup; when both happen to exist,
        # prefer the exact match over the slash-variant. Root ("/") has
        # no meaningful variant, so it's matched as-is.
        candidates = [p]
        if p != "/":
            candidates.append(p[:-1] if p.endswith("/") else p + "/")
        rows = UrlRedirect.query.filter(
            UrlRedirect.source_path.in_(candidates)).all()
        if rows:
            row = next((r for r in rows if r.source_path == p), rows[0])
            return redirect(row.target_path, code=301)
        # Wildcard fallback. Source paths of the form "/foo/*" match
        # any request whose path starts with "/foo/" (the "/" boundary
        # prevents "/foo/*" from accidentally matching "/foobar").
        # Longest prefix wins so "/swag/sale/*" beats "/swag/*".
        wild = UrlRedirect.query.filter(
            UrlRedirect.source_path.endswith("/*")).all()
        best = None
        for r in wild:
            prefix = r.source_path[:-1]  # strip the trailing "*", keep the "/"
            if p == prefix[:-1] or p.startswith(prefix):
                if best is None or len(r.source_path) > len(best.source_path):
                    best = r
        if best:
            return redirect(best.target_path, code=301)
        return None

    # Cache-bust token (?v=) on image + static asset URLs. See app/imgcache.py.
    from . import imgcache
    imgcache.register(app)

    @app.after_request
    def _security_headers(response):
        # Asset caching is centralized in imgcache: it stamps image/static
        # responses with the admin-configured Cache-Control (Web Frontend →
        # Caching) and returns True when it owns the header. Anything it
        # doesn't own falls through to the no-store rule below.
        path = request.path or ""
        if not imgcache.apply_cache_headers(response):
            # Cache-control: stops Cloudflare/browsers from caching per-user
            # pages and stale form responses. /static/ and /pub/ are
            # deterministic (and asset caching above already handled their
            # image/static responses).
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
        # Cross-origin isolation. COOP=same-origin keeps any window we
        # open (or that opens us) in a separate browsing-context group so
        # window.opener attacks can't reach across; CORP=same-origin
        # blocks other origins from embedding our responses as resources
        # (image hot-linking, <link rel=stylesheet href=us> from external
        # sites, etc.). Both are scoped to our own origin — Caddy /
        # Cloudflare / our own /pub/ assets stay on the same host so
        # nothing legitimate breaks.
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
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
        # Pre-create_all: rename the legacy ``phone_list_entry`` table to
        # ``recovery_contact`` BEFORE create_all runs, so create_all never
        # makes an empty ``recovery_contact`` that would then need dropping
        # (dropping it is a data-loss hazard under the two-worker boot
        # race). Rename only — never drop — and tolerate the race (the
        # loser sees "no such table" / "already exists"). No-op once
        # migrated and on fresh installs.
        from sqlalchemy import text as _text
        try:
            with db.engine.begin() as _c:
                _names = {r[0] for r in _c.execute(_text(
                    "SELECT name FROM sqlite_master WHERE type='table'"))}
                if "phone_list_entry" in _names and "recovery_contact" not in _names:
                    _c.execute(_text("ALTER TABLE phone_list_entry RENAME TO recovery_contact"))
        except OperationalError:
            pass
        try:
            db.create_all()
        except OperationalError as e:
            if "already exists" not in str(e).lower():
                raise
        _migrate_sqlite(app)
        _seed_admin(app)
        _seed_custom_layouts(app)
        _seed_footer_layouts(app)
        _seed_page_layouts(app)
        # Seed the public `/` homepage Page after page layouts so
        # we can default to the 'page-blank' preset key on the new
        # row without it dangling.
        _seed_homepage_page(app)
        _backfill_media(app)
        _migrate_unique_post_slugs(app)
        _migrate_trusted_servant_user_id_nullable(app)
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

    # Off-site backup scheduler — file-locked so only one gunicorn
    # worker drives the loop; the others see the lock and idle.
    try:
        from .backup_scheduler import start_scheduler
        start_scheduler(app)
    except Exception:  # noqa: BLE001
        app.logger.exception("backup scheduler failed to start")

    def _backup_targets_for_template():
        try:
            from .models import BackupTarget
            return BackupTarget.query.order_by(BackupTarget.created_at.desc()).all()
        except Exception:  # noqa: BLE001
            return []
    app.jinja_env.globals["backup_targets"] = _backup_targets_for_template

    from .metrics import prime as _prime_metrics
    _prime_metrics()

    from .icons import icon as _icon
    app.jinja_env.globals["icon"] = _icon

    # Release-notes + changelog single source of truth. The About modal
    # in templates/base.html iterates these at render time so editing
    # RELEASE_NOTES.md / CHANGELOG.md at the repo root is the only step
    # needed to update the in-app view. See app/about_docs.py.
    from . import about_docs as _about_docs
    app.jinja_env.globals["app_release_notes"] = _about_docs.load_release_notes
    app.jinja_env.globals["app_changelog"] = _about_docs.load_changelog

    # Dynamic-background catalog. The admin's dynbg picker macro and
    # any future template that wants to enumerate available presets
    # reads this at render time, so a new entry in app/dynbg.py
    # appears in every picker the moment it's added.
    from . import dynbg as _dynbg
    app.jinja_env.globals["dynbg_catalog"] = lambda: _dynbg.CATALOG
    app.jinja_env.globals["dynbg_overlays"] = lambda: _dynbg.OVERLAYS
    # Helpers used by the trigger macro + public render partials so
    # template authors don't have to import Python to decode a stored
    # config blob into its (overlay, colors, scope, grain knobs)
    # shape, generate the noise-grain data-URL with admin-chosen
    # size/intensity, or resolve the per-render colour palette
    # (which differs from the saved palette when `randomize` is on).
    app.jinja_env.globals["dynbg_decode"] = _dynbg.decode_config
    app.jinja_env.globals["dynbg_colors_css"] = _dynbg.colors_to_css_vars
    app.jinja_env.globals["dynbg_resolve_colors"] = _dynbg.resolve_colors
    app.jinja_env.globals["dynbg_resolve_positions"] = _dynbg.resolve_positions_css
    app.jinja_env.globals["dynbg_noise_url"] = _dynbg.noise_grain_data_url
    # Per-render randomised inline-style for a preset thumbnail (fresh
    # palette + positions each load) — drives the picker grid thumbs.
    app.jinja_env.globals["dynbg_thumb_style"] = _dynbg.thumb_style
    # Per-preset knob CSS-vars (dot size/gap, line angle/thickness, …)
    # stamped on a surface's dynbg-host so the recipe reads them.
    app.jinja_env.globals["dynbg_knobs_css"] = _dynbg.knobs_to_css_vars
    # Per-preset capability spec (which Options controls + knobs apply
    # to each background) — the modal stamps this as JSON to drive
    # show/hide + slider rendering. Also the overlay Size/Intensity
    # spec keyed by overlay so the modal can set per-overlay bounds.
    app.jinja_env.globals["dynbg_preset_caps"] = lambda: _dynbg.PRESET_CAPS
    app.jinja_env.globals["dynbg_overlay_knobs"] = lambda: _dynbg.OVERLAY_KNOBS
    # Per-template settings dict — list-page shells read this so the
    # admin's customize-panel choices (font / size / dynbg) take
    # effect on the public site. Falls back to flat columns inside
    # each shell when the per-template entry is empty.
    from .frontend import template_settings as _template_settings
    app.jinja_env.globals["template_settings"] = _template_settings
    app.jinja_env.globals["dynbg_animated_keys"] = lambda: list(_dynbg.ANIMATED_KEYS)
    app.jinja_env.globals["dynbg_defaults"] = lambda: {
        "noise_size": _dynbg.NOISE_SIZE_DEFAULT,
        "noise_size_min": _dynbg.NOISE_SIZE_MIN,
        "noise_size_max": _dynbg.NOISE_SIZE_MAX,
        "noise_intensity": _dynbg.NOISE_INTENSITY_DEFAULT,
        "noise_intensity_min": _dynbg.NOISE_INTENSITY_MIN,
        "noise_intensity_max": _dynbg.NOISE_INTENSITY_MAX,
    }

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

    # Canonical post URL — picks /archive/<slug> for archived posts and
    # the live /event/<slug> or /announcement/<slug> URL otherwise. Cards
    # and other list templates call this so a single archive flip on a
    # post propagates to every link without each partial re-deriving the
    # URL itself.
    from .frontend import _post_url as _post_url_helper
    app.jinja_env.globals["post_url"] = _post_url_helper

    # IANA timezone names + a "now in tz" helper for the Settings → Timezone
    # tab. Cached at module level — the zone list never changes at runtime.
    from .timezone import available_timezone_names as _tz_names, now_in_name as _now_in_name
    app.jinja_env.globals["available_timezone_names"] = _tz_names
    app.jinja_env.globals["now_in_timezone"] = _now_in_name

    from .utility_bar import utility_bar_context as _utility_bar_context
    app.jinja_env.globals["utility_bar_admin"] = _utility_bar_context
    app.jinja_env.globals["utility_bar_icon_choices"] = lambda: [
        ("", "No icon"),
        ("phone", "Phone"),
        ("mail", "Mail"),
        ("info", "Info"),
        ("alert-triangle", "Warning"),
        ("bell", "Bell"),
        ("megaphone", "Megaphone"),
        ("calendar", "Calendar"),
        ("clock", "Clock"),
        ("camera", "Camera"),
        ("video", "Video"),
        ("users", "Users"),
        ("user", "User"),
        ("heart", "Heart"),
        ("star", "Star"),
        ("zap", "Zap"),
        ("help-circle", "Help"),
        ("globe", "Globe"),
        ("map-pin", "Map pin"),
        ("facebook", "Facebook"),
        ("instagram", "Instagram"),
        ("twitter", "Twitter"),
        ("youtube", "YouTube"),
        ("github", "GitHub"),
    ]

    # `footer_content(site)` resolves the structured footer content
    # (brand / columns / social / secondary nav / copyright) for any
    # template that includes a footer partial. Exposed as a global so
    # we don't have to thread it through every render_template call.
    from .blocks import footer_content as _footer_content
    app.jinja_env.globals["footer_content"] = _footer_content

    # `lookup_locations_by_ids(ids)` — bulk fetch Location rows for the
    # meeting_locations footer block's `predefined_ids`. Returned in
    # arbitrary order (the partial re-orders to the admin's checklist
    # order). Returns [] when given an empty/falsy iterable so the
    # partial's `{% if %}` guard works without surprises.
    def _lookup_locations_by_ids(ids):
        if not ids:
            return []
        from .models import Location
        return Location.query.filter(Location.id.in_(ids)).all()
    app.jinja_env.globals["lookup_locations_by_ids"] = _lookup_locations_by_ids

    # `now_year()` — small convenience for the footer copyright `{year}`
    # placeholder substitution. Computed at render time so a long-running
    # process doesn't get stuck on last year's value.
    def _now_year():
        from datetime import datetime
        return datetime.utcnow().year
    app.jinja_env.globals["now_year"] = _now_year

    # Font helpers — resolve_fonts/font_css_vars are used by the public
    # base template to set semantic --fe-font-* CSS variables per theme.
    # frontend_fonts is now a callable that merges vendored fonts with
    # admin-uploaded CustomFont rows, so pickers reflect new uploads.
    from .fonts import (
        font_css_vars as _font_css_vars,
        all_fonts as _all_fonts,
        custom_fonts as _custom_fonts,
        font_stack as _font_stack,
        ROLES as _FONT_ROLES,
    )
    app.jinja_env.globals["font_css_vars"] = _font_css_vars
    app.jinja_env.globals["frontend_fonts"] = _all_fonts
    app.jinja_env.globals["custom_fonts"] = _custom_fonts
    app.jinja_env.globals["font_stack"] = _font_stack
    app.jinja_env.globals["frontend_font_roles"] = _FONT_ROLES

    # Intergroup officers — repeatable contact roster managed under
    # Settings → Global. Two helpers:
    #   • `intergroup_officers()` returns the full ordered list (used
    #     by the page editor to populate the `intergroup_member` block's
    #     dropdown of all officers).
    #   • `intergroup_officer(id)` resolves a single row by id (used by
    #     the public block renderer to look up the chosen officer at
    #     request time).
    def _intergroup_officers():
        from .models import IntergroupOfficer
        return (IntergroupOfficer.query
                .order_by(IntergroupOfficer.sort_order, IntergroupOfficer.id)
                .all())
    def _intergroup_officer(oid):
        from .models import IntergroupOfficer
        try:
            oid = int(oid)
        except (TypeError, ValueError):
            return None
        if not oid:
            return None
        return db.session.get(IntergroupOfficer, oid)
    app.jinja_env.globals["intergroup_officers"] = _intergroup_officers
    app.jinja_env.globals["intergroup_officer"] = _intergroup_officer

    # Library lookups for the page-block renderer:
    #   • `library_block_data(library_id, mode, item_ids)` resolves to
    #     `(library, items)` at request time, applying the granular
    #     filter when mode='granular'. Returns (None, []) if the library
    #     doesn't exist so the renderer can short-circuit cleanly.
    #   • `all_libraries()` returns every library (sorted) for the
    #     editor's picker dropdown — surfaced via window.tspLibraries
    #     in frontend_page_edit.html so the Library block's settings
    #     panel can populate without an extra round-trip.
    def _library_block_data(library_id, mode='all', item_ids=None, sort='manual'):
        """Resolve a Library + the items the block should render.

        ``sort`` is applied AFTER the granular filter so hand-picked
        subsets honour the requested order. Recognised values:
          - ``manual``     → library position then id (default)
          - ``name-asc``   → A → Z by title (case-insensitive)
          - ``name-desc``  → Z → A
          - ``date-desc``  → newest first by created_at
          - ``date-asc``   → oldest first
        Any unrecognised value falls back to manual."""
        from .models import Library, LibraryItem
        try:
            lid = int(library_id or 0)
        except (TypeError, ValueError):
            lid = 0
        if not lid:
            return (None, [])
        lib = db.session.get(Library, lid)
        if lib is None:
            return (None, [])
        items = (LibraryItem.query
                 .filter_by(library_id=lib.id)
                 .order_by(LibraryItem.position, LibraryItem.id)
                 .all())
        if (mode or 'all') == 'granular':
            wanted = set()
            for i in (item_ids or []):
                try:
                    wanted.add(int(i))
                except (TypeError, ValueError):
                    pass
            items = [it for it in items if it.id in wanted]
        s = (sort or 'manual').lower()
        if s == 'name-asc':
            items = sorted(items, key=lambda it: (it.title or '').lower())
        elif s == 'name-desc':
            items = sorted(items, key=lambda it: (it.title or '').lower(), reverse=True)
        elif s == 'date-desc':
            from datetime import datetime
            items = sorted(items,
                           key=lambda it: it.created_at or datetime.min,
                           reverse=True)
        elif s == 'date-asc':
            from datetime import datetime
            items = sorted(items,
                           key=lambda it: it.created_at or datetime.min)
        return (lib, items)
    def _all_libraries():
        from .models import Library
        return Library.query.order_by(Library.name).all()
    app.jinja_env.globals["library_block_data"] = _library_block_data
    app.jinja_env.globals["all_libraries"] = _all_libraries

    # Blog block data — resolves the post list a page-embedded blog
    # block should render, plus the matching category/tag for the
    # block's header. Filters apply per-block: a single Blog table
    # can power many distinct frontend "blogs" by scoping each
    # embed to a different category or tag.
    def _blog_block_data(category_id=0, tag_id=0, *, sort="newest",
                         max_items=0, only_featured=False, only_pinned=False):
        """Return ``(category, tag, posts)`` for a blog block. The
        posts query filters out drafts + archives (so the public
        view never sees them), then narrows by category / tag and
        applies the requested sort. ``max_items`` of 0 = show every
        match; a positive int caps the list."""
        from .models import BlogPost, BlogCategory, BlogTag
        from datetime import datetime
        try:
            cid = int(category_id or 0)
        except (TypeError, ValueError):
            cid = 0
        try:
            tid = int(tag_id or 0)
        except (TypeError, ValueError):
            tid = 0
        category = db.session.get(BlogCategory, cid) if cid else None
        tag = db.session.get(BlogTag, tid) if tid else None

        q = (BlogPost.query
             .filter(BlogPost.is_archived.is_(False),
                     BlogPost.is_draft.is_(False)))
        if category:
            q = q.filter(BlogPost.categories.any(BlogCategory.id == category.id))
        if tag:
            q = q.filter(BlogPost.tags.any(BlogTag.id == tag.id))
        if only_featured:
            q = q.filter(BlogPost.is_featured.is_(True))
        if only_pinned:
            q = q.filter(BlogPost.is_pinned.is_(True))
        s = (sort or "newest").lower()
        if s == "oldest":
            q = q.order_by(BlogPost.is_pinned.desc(),
                           BlogPost.published_at.asc().nulls_last(),
                           BlogPost.created_at.asc())
        elif s == "title":
            q = q.order_by(BlogPost.is_pinned.desc(), BlogPost.title.asc())
        elif s == "random":
            from sqlalchemy import func as _func
            q = q.order_by(BlogPost.is_pinned.desc(), _func.random())
        else:  # newest
            q = q.order_by(BlogPost.is_pinned.desc(),
                           BlogPost.published_at.desc().nulls_last(),
                           BlogPost.created_at.desc())
        try:
            limit = int(max_items or 0)
        except (TypeError, ValueError):
            limit = 0
        if limit > 0:
            q = q.limit(limit)
        posts = q.all()
        return (category, tag, posts)

    def _all_blog_categories():
        from .models import BlogCategory
        return (BlogCategory.query
                .order_by(BlogCategory.position, BlogCategory.name)
                .all())

    def _all_blog_tags():
        from .models import BlogTag
        return BlogTag.query.order_by(BlogTag.name).all()

    app.jinja_env.globals["blog_block_data"] = _blog_block_data
    app.jinja_env.globals["all_blog_categories"] = _all_blog_categories
    app.jinja_env.globals["all_blog_tags"] = _all_blog_tags

    # `css_color` Jinja filter — translate stored color values into
    # CSS-emitable strings. Accepts:
    #   • blank / None       → ''        (caller usually skips emission)
    #   • '#rgb' / '#rrggbb' → returned verbatim
    #   • 'token:<key>'      → 'var(--fe-color-<key-with-dashes>)'
    # Used everywhere a color stored in block data lands in inline
    # styles, so the `token:` storage form (writable via the editor's
    # token picker) round-trips into a live `var(...)` reference. The
    # CSS variable comes from `design_css_vars()` on <body>, so a
    # token edit under Settings → Design retints every consumer
    # automatically — no re-save required.
    def _css_color(value):
        if not value:
            return ""
        v = str(value).strip()
        if not v:
            return ""
        if v.startswith("token:"):
            key = v[6:]
            if not key:
                return ""
            return "var(--fe-" + key.replace("_", "-") + ")"
        return v
    app.jinja_env.filters["css_color"] = _css_color

    # Site-wide design tokens. Same layered model as fonts: theme
    # defaults + per-site overrides → flat dict + a CSS-vars string the
    # public base template inlines on <body>.
    from .design import (
        design_css_vars as _design_css_vars,
        neobrutal_hero_css_vars as _neobrutal_hero_css_vars,
        resolve_design as _resolve_design,
        derive_dark_color as _derive_dark_color,
        DESIGN_FIELDS as _DESIGN_FIELDS,
        DESIGN_FIELDS_BY_KEY as _DESIGN_FIELDS_BY_KEY,
        DESIGN_GROUPS as _DESIGN_GROUPS,
        SPACING_SCALE as _SPACING_SCALE,
        RADIUS_SCALE as _RADIUS_SCALE,
        SHADOW_SCALE as _SHADOW_SCALE,
        BORDER_WIDTH_SCALE as _BORDER_WIDTH_SCALE,
        TRANSITION_SCALE as _TRANSITION_SCALE,
        TRANSFORM_SCALE as _TRANSFORM_SCALE,
        THEME_DEFAULTS as _DESIGN_THEME_DEFAULTS,
    )
    app.jinja_env.globals["design_css_vars"] = _design_css_vars
    app.jinja_env.globals["neobrutal_hero_css_vars"] = _neobrutal_hero_css_vars
    app.jinja_env.globals["resolve_design"] = _resolve_design
    app.jinja_env.globals["derive_dark_color"] = _derive_dark_color
    app.jinja_env.globals["design_fields"] = _DESIGN_FIELDS
    app.jinja_env.globals["design_fields_by_key"] = _DESIGN_FIELDS_BY_KEY
    app.jinja_env.globals["design_groups"] = _DESIGN_GROUPS
    app.jinja_env.globals["design_spacing_scale"] = _SPACING_SCALE
    app.jinja_env.globals["design_radius_scale"] = _RADIUS_SCALE
    app.jinja_env.globals["design_shadow_scale"] = _SHADOW_SCALE
    app.jinja_env.globals["design_border_width_scale"] = _BORDER_WIDTH_SCALE
    app.jinja_env.globals["design_transition_scale"] = _TRANSITION_SCALE
    app.jinja_env.globals["design_transform_scale"] = _TRANSFORM_SCALE
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

    # Upload-too-large: Flask short-circuits with HTTP 413 BEFORE the route
    # runs, so the bundle-restore form would otherwise navigate to a bare
    # error body the browser renders as a blank page. Flash a useful message
    # and bounce back to where the user came from so they see what went wrong.
    from flask import flash as _flash
    @app.errorhandler(413)
    def _handle_413(_err):
        cap_mb = app.config.get("MAX_CONTENT_LENGTH", 0) // (1024 * 1024)
        _flash(
            f"Upload too large — exceeds the {cap_mb} MB limit. "
            f"Raise TSP_MAX_UPLOAD_MB on the server and restart, then retry.",
            "danger",
        )
        # Prefer the Referer so the user lands back on the form that
        # triggered the upload; fall back to the admin index. Validate
        # the referrer points at this host to avoid open-redirect.
        from urllib.parse import urlparse
        ref = _request.headers.get("Referer", "")
        try:
            host_ok = bool(ref) and urlparse(ref).netloc == _request.host
        except ValueError:
            host_ok = False
        return redirect(ref if host_ok else url_for("main.index"))

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
            # Log the miss so Watchtower's 404s tab can surface broken
            # inbound links / dead URLs. Defensive inside record_404 —
            # never lets a logging failure escalate a 404 into a 500.
            try:
                from . import visitor_metrics
                visitor_metrics.record_404(path)
            except Exception:  # noqa: BLE001
                pass
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


def _migrate_unique_post_slugs(app):
    """Idempotent sweep: walk every Post in id order and disambiguate
    public_slug collisions by appending ``-2``, ``-3``, ... onto later
    duplicates. Stores the resolved slug explicitly on Post.slug and
    logs each rename to EntitySlugHistory so old URLs continue to 301
    via the history-based redirect path. Runs on every boot — cheap
    against the small post table and safe to repeat (no-op when nothing
    collides)."""
    from .models import Post, EntitySlugHistory
    used = set()
    renamed = 0
    for p in Post.query.order_by(Post.id).all():
        current = p.public_slug
        if current and current not in used:
            used.add(current)
            continue
        # Collision (or empty) — rebuild from a stable base.
        base = current or "post"
        n = 2
        candidate = f"{base}-{n}"
        while candidate in used:
            n += 1
            candidate = f"{base}-{n}"
        old_slug = current
        p.slug = candidate
        used.add(candidate)
        if old_slug and old_slug != candidate:
            db.session.add(EntitySlugHistory(
                entity_type="post", entity_id=p.id,
                old_slug=old_slug, new_slug=candidate,
                changed_by=None,
            ))
        renamed += 1
    if renamed:
        db.session.commit()
        app.logger.info(f"Disambiguated {renamed} post slug(s)")


def _migrate_trusted_servant_user_id_nullable(app):
    """Rebuild ``trusted_servant_subscriber`` if its ``user_id`` column
    is still NOT NULL.

    The table shipped in 2.1.2 with ``user_id NOT NULL UNIQUE`` so every
    row was tied to a portal-user account. 2.1.3 lifts that constraint
    so admins can manually add external trusted servants who don't have
    accounts. SQLite's ALTER TABLE can't drop a NOT NULL constraint, so
    we do the canonical table-rebuild dance — copy rows into a fresh
    table with the relaxed schema, drop the old one, rename in place.

    Idempotent: PRAGMA table_info reports the column's NOT NULL state;
    when it's already nullable (fresh installs that picked up the
    updated model from day one) the function is a no-op.
    """
    from sqlalchemy import text
    with db.engine.begin() as conn:
        cols = list(conn.execute(text("PRAGMA table_info(trusted_servant_subscriber)")))
        if not cols:
            return  # table doesn't exist yet — db.create_all() will build it correctly
        user_id_col = next((c for c in cols if c[1] == "user_id"), None)
        if user_id_col is None:
            return
        # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
        if not user_id_col[3]:
            return  # already nullable, nothing to do
        app.logger.info("Rebuilding trusted_servant_subscriber to allow NULL user_id")
        # Preserve any existing rows. The rebuild order has to drop the
        # old table before renaming the new one, so we use a temp name
        # and commit each statement individually via the same engine
        # transaction (begin() above wraps them).
        conn.execute(text("""
            CREATE TABLE trusted_servant_subscriber__new (
                id INTEGER NOT NULL,
                user_id INTEGER,
                name VARCHAR(120) NOT NULL,
                phone VARCHAR(64),
                email VARCHAR(255) NOT NULL,
                notes TEXT,
                created_at DATETIME,
                updated_at DATETIME,
                PRIMARY KEY (id),
                FOREIGN KEY(user_id) REFERENCES "user" (id) ON DELETE CASCADE,
                UNIQUE (user_id)
            )
        """))
        conn.execute(text("""
            INSERT INTO trusted_servant_subscriber__new
                (id, user_id, name, phone, email, notes, created_at, updated_at)
            SELECT id, user_id, name, phone, email, notes, created_at, updated_at
              FROM trusted_servant_subscriber
        """))
        conn.execute(text("DROP TABLE trusted_servant_subscriber"))
        conn.execute(text("ALTER TABLE trusted_servant_subscriber__new RENAME TO trusted_servant_subscriber"))
        conn.execute(text("CREATE INDEX ix_trusted_servant_subscriber_user_id ON trusted_servant_subscriber (user_id)"))


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

        # ── Recovery Contacts rename (dev-era) ───────────────────────
        # The module shipped as "Phone List": ``site_setting.phone_list_*``
        # columns (and table ``phone_list_entry``, renamed to
        # ``recovery_contact`` pre-create_all in create_app). Rename the
        # columns to ``recovery_contacts_*`` in place. Race-tolerant: with
        # two workers booting, the loser's RENAME raises "no such column" /
        # "duplicate" after the winner committed — caught and treated as
        # already-done (RENAME COLUMN never loses data). No-op once
        # migrated and on fresh installs.
        def rename_col(table, old, new):
            cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            if old in cols and new not in cols:
                try:
                    conn.execute(text(f'ALTER TABLE {table} RENAME COLUMN {old} TO {new}'))
                except OperationalError:
                    pass
        for _old, _new in (
                ("phone_list_enabled", "recovery_contacts_enabled"),
                ("phone_list_required_role", "recovery_contacts_required_role"),
                ("phone_list_heading", "recovery_contacts_heading"),
                ("phone_list_subheading", "recovery_contacts_subheading"),
                ("phone_list_intro", "recovery_contacts_intro"),
                ("phone_list_success_message", "recovery_contacts_success_message"),
                ("phone_list_submit_label", "recovery_contacts_submit_label"),
                ("phone_list_to", "recovery_contacts_to"),
                ("phone_list_width_mode", "recovery_contacts_width_mode"),
                ("phone_list_max_width", "recovery_contacts_max_width"),
                ("phone_list_padding_pct", "recovery_contacts_padding_pct")):
            rename_col("site_setting", _old, _new)

        for col, ddl in (("zoom_meeting_id", "VARCHAR(64)"),
                         ("zoom_passcode", "VARCHAR(128)"),
                         ("zoom_opens_time", "VARCHAR(16)"),
                         ("meeting_type", "VARCHAR(16) NOT NULL DEFAULT 'in_person'"),
                         ("logo_filename", "VARCHAR(500)"),
                         ("zoom_account_id", "INTEGER REFERENCES zoom_account(id)"),
                         ("zoom_link", "VARCHAR(1000)"),
                         ("alert_message", "TEXT"),
                         ("public_alert_message", "TEXT"),
                         ("public_alert_expires_at", "DATETIME"),
                         ("slug", "VARCHAR(255)"),
                         ("archived_at", "DATETIME"),
                         ("show_otp", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("location_notes", "TEXT"),
                         ("extended_content_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("extended_blocks_json", "TEXT")):
            add("meeting", col, ddl)
        for col, ddl in (("alert_message", "TEXT"),
                         ("is_intergroup", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("categories_required", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("public_visible", "BOOLEAN NOT NULL DEFAULT 0")):
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
        # gate resolves cleanly under the new role set. Guarded by a
        # column-existence check because the column itself is only added
        # later in this migration block — on a DB that predates the
        # column, this UPDATE would otherwise crash _migrate_sqlite before
        # any of the later ALTER TABLE statements got a chance to run.
        _ss_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(site_setting)"))}
        if "frontend_module_required_role" in _ss_cols:
            conn.execute(text(
                "UPDATE site_setting SET frontend_module_required_role = 'admin' "
                "WHERE frontend_module_required_role = 'frontend_editor'"))
        for col, ddl in (("mode", "VARCHAR(16) NOT NULL DEFAULT 'all'"),
                         ("public_visible", "BOOLEAN NOT NULL DEFAULT 0")):
            add("meeting_libraries", col, ddl)
        for col, ddl in (("position", "INTEGER NOT NULL DEFAULT 0"),
                         ("public_visible", "BOOLEAN NOT NULL DEFAULT 0")):
            add("meeting_file", col, ddl)
        for col, ddl in (("opens_time", "VARCHAR(8)"),):
            add("meeting_schedule", col, ddl)
        for col, ddl in (("imap_host", "VARCHAR(255)"),
                         ("imap_port", "INTEGER DEFAULT 993"),
                         ("imap_ssl", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("imap_username", "VARCHAR(255)"),
                         ("imap_password_enc", "BLOB"),
                         ("imap_mailbox", "VARCHAR(128) DEFAULT 'INBOX'")):
            add("zoom_otp_email", col, ddl)
        for col, ddl in (("location_type", "VARCHAR(16) NOT NULL DEFAULT 'in_person'"),
                         ("address", "VARCHAR(500)"),
                         ("maps_url", "VARCHAR(1000)"),
                         ("street", "VARCHAR(255)"),
                         ("city", "VARCHAR(120)"),
                         ("state", "VARCHAR(64)"),
                         ("zip_code", "VARCHAR(20)"),
                         ("website_url", "VARCHAR(1000)"),
                         ("notes", "TEXT")):
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
                         # Outgoing-mail transport: SMTP (default) vs HTTPS API relay
                         ("mail_transport", "VARCHAR(16) NOT NULL DEFAULT 'smtp'"),
                         ("relay_url", "VARCHAR(500)"),
                         ("relay_api_key_enc", "BLOB"),
                         # Persisted relay connection-test result (status pill)
                         ("relay_status", "VARCHAR(16)"),
                         ("relay_status_detail", "VARCHAR(500)"),
                         ("relay_checked_at", "DATETIME"),
                         ("access_request_to", "VARCHAR(500)"),
                         ("submission_to", "VARCHAR(500)"),
                         ("submission_form_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("submission_form_blocks_json", "TEXT"),
                         ("submission_form_slug", "VARCHAR(120)"),
                         ("contact_form_blocks_json", "TEXT"),
                         ("contact_form_slug", "VARCHAR(120)"),
                         ("story_form_blocks_json", "TEXT"),
                         ("story_form_slug", "VARCHAR(120)"),
                         ("story_form_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("story_form_heading", "VARCHAR(200)"),
                         ("story_form_subheading", "VARCHAR(500)"),
                         ("story_form_intro", "TEXT"),
                         ("story_form_success_message", "VARCHAR(500)"),
                         ("story_form_submit_label", "VARCHAR(100)"),
                         ("story_form_to", "VARCHAR(500)"),
                         ("story_form_name_label", "VARCHAR(120)"),
                         ("story_form_email_label", "VARCHAR(120)"),
                         ("story_form_email_required", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("story_form_story_label", "VARCHAR(120)"),
                         ("story_form_story_placeholder", "VARCHAR(200)"),
                         ("story_form_file_label", "VARCHAR(120)"),
                         ("story_form_file_help", "TEXT"),
                         ("story_form_terms_label", "VARCHAR(120)"),
                         ("story_form_terms_intro", "VARCHAR(200)"),
                         ("story_form_terms_text", "TEXT"),
                         ("story_form_terms_checkbox_label", "VARCHAR(200)"),
                         ("submission_form_heading", "VARCHAR(200)"),
                         ("submission_form_subheading", "VARCHAR(500)"),
                         ("submission_form_modal_heading", "VARCHAR(200)"),
                         ("submission_form_intro", "TEXT"),
                         ("submission_form_success_message", "VARCHAR(500)"),
                         ("submission_form_allowed_types", "VARCHAR(16) NOT NULL DEFAULT 'both'"),
                         ("submission_form_submit_label", "VARCHAR(100)"),
                         ("frontend_submission_form_template", "VARCHAR(64) NOT NULL DEFAULT 'classic'"),
                         ("frontend_submission_form_width_mode", "VARCHAR(16) NOT NULL DEFAULT 'boxed'"),
                         ("frontend_submission_form_max_width", "INTEGER NOT NULL DEFAULT 720"),
                         ("frontend_submission_form_padding_pct", "INTEGER NOT NULL DEFAULT 5"),
                         ("frontend_submission_form_bg_dynamic_key", "VARCHAR(64)"),
                         ("frontend_submission_form_bg_dynbg_config_json", "TEXT"),
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
                         ("apple_touch_icon_filename", "VARCHAR(500)"),
                         ("apple_touch_icon_name", "VARCHAR(100)"),
                         ("frontend_apple_touch_icon_filename", "VARCHAR(500)"),
                         ("frontend_apple_touch_icon_name", "VARCHAR(100)"),
                         ("frontend_design_json", "TEXT"),
                         ("frontend_404_heading", "VARCHAR(200)"),
                         ("frontend_404_subheading", "TEXT"),
                         ("frontend_404_cta_label", "VARCHAR(120)"),
                         ("frontend_404_cta_url", "VARCHAR(500)"),
                         ("frontend_404_image_filename", "VARCHAR(500)"),
                         ("frontend_module_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("frontend_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         # Cookie & privacy compliance — see app/cookie_compliance.py
                         # and SiteSetting.cookie_compliance_* commentary.
                         ("cookie_compliance_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("cookie_compliance_mode", "VARCHAR(16) NOT NULL DEFAULT 'notice'"),
                         ("cookie_compliance_auto_region", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("cookie_compliance_title", "VARCHAR(200)"),
                         ("cookie_compliance_body", "TEXT"),
                         ("cookie_compliance_accept_label", "VARCHAR(60)"),
                         ("cookie_compliance_reject_label", "VARCHAR(60)"),
                         ("cookie_compliance_more_label", "VARCHAR(60)"),
                         ("cookie_compliance_position", "VARCHAR(16) NOT NULL DEFAULT 'bottom-bar'"),
                         ("cookie_compliance_policy_page_id", "INTEGER REFERENCES page(id) ON DELETE SET NULL"),
                         ("cookie_compliance_policy_external_url", "VARCHAR(500)"),
                         ("cookie_compliance_remember_days", "INTEGER NOT NULL DEFAULT 365"),
                         # Which `Page` row renders at the public `/` root.
                         # Nullable for the brief window between column add
                         # and the auto-seed running; in normal operation
                         # always points at a Page (the Pages admin guards
                         # delete to keep the homepage from being orphaned).
                         ("homepage_page_id", "INTEGER REFERENCES page(id) ON DELETE SET NULL"),
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
                         ("frontend_meetings_list_template", "VARCHAR(64) NOT NULL DEFAULT 'sidebar'"),
                         ("frontend_meetings_list_width_mode", "VARCHAR(16) NOT NULL DEFAULT 'boxed'"),
                         ("frontend_meetings_list_max_width", "INTEGER NOT NULL DEFAULT 1160"),
                         ("frontend_meetings_list_padding_pct", "INTEGER NOT NULL DEFAULT 5"),
                         ("frontend_meetings_list_heading", "VARCHAR(200)"),
                         ("frontend_meetings_list_subheading", "VARCHAR(500)"),
                         ("frontend_meetings_list_protips_json", "TEXT"),
                         ("frontend_meetings_list_sidebar_links_json", "TEXT"),
                         ("frontend_events_list_template", "VARCHAR(64) NOT NULL DEFAULT 'cards'"),
                         ("frontend_events_list_width_mode", "VARCHAR(16) NOT NULL DEFAULT 'boxed'"),
                         ("frontend_events_list_max_width", "INTEGER NOT NULL DEFAULT 1160"),
                         ("frontend_events_list_padding_pct", "INTEGER NOT NULL DEFAULT 5"),
                         ("frontend_events_list_heading", "VARCHAR(200)"),
                         ("frontend_events_list_subheading", "VARCHAR(500)"),
                         ("frontend_announcements_list_template", "VARCHAR(64) NOT NULL DEFAULT 'omni'"),
                         ("frontend_announcements_list_width_mode", "VARCHAR(16) NOT NULL DEFAULT 'boxed'"),
                         ("frontend_announcements_list_max_width", "INTEGER NOT NULL DEFAULT 1160"),
                         ("frontend_announcements_list_padding_pct", "INTEGER NOT NULL DEFAULT 5"),
                         ("frontend_announcements_list_heading", "VARCHAR(200)"),
                         ("frontend_announcements_list_subheading", "VARCHAR(500)"),
                         ("frontend_archive_template", "VARCHAR(64) NOT NULL DEFAULT 'year-sidebar'"),
                         ("frontend_archive_pagination_mode", "VARCHAR(16) NOT NULL DEFAULT 'infinite'"),
                         ("frontend_archive_page_size", "INTEGER NOT NULL DEFAULT 20"),
                         ("frontend_archive_bg_dynamic_key", "VARCHAR(64)"),
                         ("frontend_archive_bg_dynbg_config_json", "TEXT"),
                         ("frontend_fellowships_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("frontend_fellowships_list_template", "VARCHAR(64) NOT NULL DEFAULT 'sidebar'"),
                         ("frontend_fellowships_list_width_mode", "VARCHAR(16) NOT NULL DEFAULT 'boxed'"),
                         ("frontend_fellowships_list_max_width", "INTEGER NOT NULL DEFAULT 1160"),
                         ("frontend_fellowships_list_padding_pct", "INTEGER NOT NULL DEFAULT 5"),
                         ("frontend_fellowships_list_heading", "VARCHAR(200)"),
                         ("frontend_fellowships_list_subheading", "VARCHAR(500)"),
                         ("frontend_fellowships_list_sort_mode", "VARCHAR(32) NOT NULL DEFAULT 'name-asc'"),
                         ("frontend_fellowships_list_bg_dynamic_key", "VARCHAR(64)"),
                         ("frontend_fellowships_list_bg_dynbg_config_json", "TEXT"),
                         ("stories_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("stories_required_role", "VARCHAR(32) NOT NULL DEFAULT 'admin'"),
                         ("trusted_servants_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("trusted_servants_required_role", "VARCHAR(32) NOT NULL DEFAULT 'admin'"),
                         ("frontend_stories_list_template", "VARCHAR(64) NOT NULL DEFAULT 'paper-stack'"),
                         ("frontend_stories_list_width_mode", "VARCHAR(16) NOT NULL DEFAULT 'boxed'"),
                         ("frontend_stories_list_max_width", "INTEGER NOT NULL DEFAULT 1160"),
                         ("frontend_stories_list_padding_pct", "INTEGER NOT NULL DEFAULT 5"),
                         ("frontend_stories_list_heading", "VARCHAR(200)"),
                         ("frontend_stories_list_subheading", "VARCHAR(500)"),
                         ("frontend_story_template", "VARCHAR(64) NOT NULL DEFAULT 'paper'"),
                         ("blog_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("blog_required_role", "VARCHAR(32) NOT NULL DEFAULT 'admin'"),
                         ("frontend_blog_list_template", "VARCHAR(64) NOT NULL DEFAULT 'magazine'"),
                         ("frontend_blog_list_width_mode", "VARCHAR(16) NOT NULL DEFAULT 'boxed'"),
                         ("frontend_blog_list_max_width", "INTEGER NOT NULL DEFAULT 1160"),
                         ("frontend_blog_list_padding_pct", "INTEGER NOT NULL DEFAULT 5"),
                         ("frontend_blog_list_heading", "VARCHAR(200)"),
                         ("frontend_blog_list_subheading", "VARCHAR(500)"),
                         ("frontend_blog_post_template", "VARCHAR(64) NOT NULL DEFAULT 'modern'"),
                         ("frontend_blog_post_width_mode", "VARCHAR(16) NOT NULL DEFAULT 'boxed'"),
                         ("frontend_blog_post_max_width", "INTEGER NOT NULL DEFAULT 1160"),
                         ("frontend_blog_post_padding_pct", "INTEGER NOT NULL DEFAULT 5"),
                         ("frontend_blog_list_bg_dynamic_key", "VARCHAR(64)"),
                         ("frontend_blog_list_bg_dynbg_config_json", "TEXT"),
                         ("frontend_blog_post_bg_dynamic_key", "VARCHAR(64)"),
                         ("frontend_blog_post_bg_dynbg_config_json", "TEXT"),
                         ("frontend_printlist_subheading", "VARCHAR(500)"),
                         ("frontend_printlist_website", "VARCHAR(200)"),
                         ("frontend_printlist_page_size", "VARCHAR(16) NOT NULL DEFAULT 'letter'"),
                         ("frontend_literature_library_template", "VARCHAR(64) NOT NULL DEFAULT 'classic'"),
                         ("frontend_event_template", "VARCHAR(64) NOT NULL DEFAULT 'classic'"),
                         ("frontend_template_settings_json", "TEXT"),
                         ("frontend_theme", "VARCHAR(64) NOT NULL DEFAULT 'classic'"),
                         ("frontend_theme_states_json", "TEXT"),
                         ("frontend_default_theme", "VARCHAR(16) NOT NULL DEFAULT 'system'"),
                         ("frontend_footer_width_mode", "VARCHAR(16) NOT NULL DEFAULT 'boxed'"),
                         ("frontend_footer_max_width", "INTEGER NOT NULL DEFAULT 1160"),
                         ("frontend_footer_padding_pct", "INTEGER NOT NULL DEFAULT 5"),
                         ("frontend_footer_blocks_json", "TEXT"),
                         ("frontend_brand_logo_filename", "VARCHAR(500)"),
                         ("frontend_footer_bg_mode", "VARCHAR(16) NOT NULL DEFAULT 'dark'"),
                         ("frontend_footer_min_height_vh", "INTEGER NOT NULL DEFAULT 0"),
                         ("frontend_footer_font_scale", "INTEGER NOT NULL DEFAULT 100"),
                         ("frontend_fonts_json", "TEXT"),
                         ("frontend_blocks_json", "TEXT"),
                         ("frontend_mega_bg_color", "VARCHAR(16) NOT NULL DEFAULT '#0B5CFF'"),
                         ("frontend_mega_text_color", "VARCHAR(16) NOT NULL DEFAULT '#ffffff'"),
                         ("frontend_mega_radius_bl", "INTEGER NOT NULL DEFAULT 18"),
                         ("frontend_mega_radius_br", "INTEGER NOT NULL DEFAULT 18"),
                         ("frontend_mega_bg_dynamic_key", "TEXT"),
                         ("frontend_mega_bg_dynbg_config_json", "TEXT"),
                         ("frontend_mega_bg_dynbg_dark", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("frontend_mega_bg_color_dark", "VARCHAR(16)"),
                         ("frontend_mega_text_color_dark", "VARCHAR(16)"),
                         ("frontend_mega_bg_dynbg_blend", "INTEGER NOT NULL DEFAULT 100"),
                         ("frontend_megamenu_animate", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("frontend_megamenu_animate_ms", "INTEGER NOT NULL DEFAULT 320"),
                         ("frontend_megamenu_panel_fade", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("frontend_megamenu_panel_fade_ms", "INTEGER NOT NULL DEFAULT 180"),
                         ("frontend_megamenu_animate_mobile", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("frontend_megamenu_animate_mobile_ms", "INTEGER NOT NULL DEFAULT 320"),
                         ("frontend_megamenu_panel_fade_mobile_ms", "INTEGER NOT NULL DEFAULT 180"),
                         ("frontend_megamenu_heading_size", "INTEGER"),
                         ("frontend_megamenu_subheading_size", "INTEGER"),
                         ("frontend_tagline_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("frontend_hero_heading_font", "VARCHAR(32) NOT NULL DEFAULT 'fraunces'"),
                         ("frontend_hero_heading_size", "INTEGER NOT NULL DEFAULT 100"),
                         ("frontend_hero_heading_grad_start", "VARCHAR(16)"),
                         ("frontend_hero_heading_grad_end", "VARCHAR(16)"),
                         ("frontend_hero_subheading_font", "VARCHAR(32) NOT NULL DEFAULT 'inter'"),
                         ("frontend_hero_subheading_size", "INTEGER NOT NULL DEFAULT 100"),
                         ("frontend_hero_subheading_color", "VARCHAR(16)"),
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
                         ("frontend_hero_bg_dynamic_key", "VARCHAR(64)"),
                         ("frontend_hero_sinewave_colors", "TEXT"),
                         ("frontend_hero_particle_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("frontend_hero_particle_effect", "VARCHAR(32) NOT NULL DEFAULT 'stars'"),
                         ("frontend_hero_particle_speed", "INTEGER NOT NULL DEFAULT 100"),
                         ("frontend_hero_particle_size", "INTEGER NOT NULL DEFAULT 100"),
                         ("frontend_hero_height_vh_desktop", "INTEGER NOT NULL DEFAULT 0"),
                         ("frontend_hero_height_vh_mobile", "INTEGER NOT NULL DEFAULT 0"),
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
                         ("setup_complete", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("timezone", "VARCHAR(64) NOT NULL DEFAULT 'UTC'"),
                         ("utility_bar_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("utility_bar_bg_color", "VARCHAR(16)"),
                         ("utility_bar_text_color", "VARCHAR(16)"),
                         ("utility_bar_left_json", "TEXT"),
                         ("utility_bar_right_json", "TEXT"),
                         ("utility_bar_live_meetings", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("utility_bar_mobile_default", "VARCHAR(32)"),
                         # Stories-list "Submit a story" CTA. Holds a
                         # form identifier (registry key or
                         # ``custom:<id>``) + the button label text.
                         ("frontend_stories_list_submit_form", "VARCHAR(64)"),
                         ("frontend_stories_list_submit_label", "VARCHAR(100)")):
            add("site_setting", col, ddl)
        for col, ddl in (("url", "VARCHAR(1000)"),
                         ("stored_filename", "VARCHAR(500)"),
                         ("original_filename", "VARCHAR(500)"),
                         ("thumbnail_filename", "VARCHAR(500)"),
                         ("position", "INTEGER NOT NULL DEFAULT 0"),
                         ("created_by", "INTEGER REFERENCES user(id)"),
                         ("public_visible", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("summary", "TEXT")):
            add("reading", col, ddl)
        for col, ddl in (("dash_show_stats", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_intergroup", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_meetings", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_libraries", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_files", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_server_metrics", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_online_users", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_access_requests", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_contact_form", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_forms", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_deletions", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_currently_online", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_visitor_metrics", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_backups", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_trusted_servants", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_show_release_notes", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("fe_admin_autohide_sidebar", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("dash_order_json", "TEXT"),
                         # Web Frontend overview widget toggles + order.
                         ("fe_dash_show_status", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("fe_dash_show_visitor_metrics", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("fe_dash_show_pages", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("fe_dash_show_redirects", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("fe_dash_show_navigation", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("fe_dash_show_forms", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("fe_dash_show_branding", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("fe_dash_show_header_footer", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("fe_dash_order_json", "TEXT"),
                         ("last_seen_at", "DATETIME"),
                         ("name", "VARCHAR(120)"),
                         ("phone", "VARCHAR(64)"),
                         ("last_endpoint", "VARCHAR(128)"),
                         ("last_path", "VARCHAR(500)"),
                         ("password_reset_allowed", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("disabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         # Optional TOTP second factor (any role).
                         ("mfa_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("mfa_secret_enc", "BLOB"),
                         ("mfa_recovery_codes_json", "TEXT"),
                         # Master "2FA on for this account" switch, distinct
                         # from mfa_enabled (enrolment complete).
                         ("mfa_required", "BOOLEAN NOT NULL DEFAULT 0")):
            add("user", col, ddl)
        # 2.14.0 shipped before mfa_required existed and gated the login
        # challenge on mfa_enabled alone. Under the new master-gate model
        # (mfa_active = required AND enabled), anyone already enrolled must
        # have the requirement turned on or their live 2FA would silently
        # stop challenging. Run only on the boot that first adds the column.
        if ("user", "mfa_required") in newly_added:
            conn.execute(text(
                "UPDATE user SET mfa_required = 1 WHERE mfa_enabled = 1"))
        for col, ddl in (("open_in_new_tab", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("form_trigger", "VARCHAR(64)")):
            add("frontend_nav_item", col, ddl)
        # Dropbox OAuth refresh-token columns. The legacy
        # ``oauth_token_enc`` column already exists from earlier migrations
        # (it shipped with the original Dropbox backend); these add the
        # app credentials + refresh token so the SDK can mint short-lived
        # access tokens on every call instead of failing every 4 hours.
        for col, ddl in (("app_key", "VARCHAR(64)"),
                         ("app_secret_enc", "BLOB"),
                         ("refresh_token_enc", "BLOB"),
                         # TS Pro Backup target (end-to-end encrypted HTTP
                         # destination): API endpoint, Fernet-encrypted API
                         # key, and the site's tsppk_ recipient public key.
                         ("api_base_url", "VARCHAR(500)"),
                         ("api_key_enc", "BLOB"),
                         ("e2ee_public_key", "VARCHAR(80)"),
                         # Remote restore (push a stored backup back to this
                         # portal): opt-in flag, shared token, our public URL.
                         ("allow_remote_restore", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("restore_token_enc", "BLOB"),
                         ("public_url", "VARCHAR(500)"),
                         ("last_remote_restore_at", "DATETIME")):
            add("backup_target", col, ddl)
        for col, ddl in (("asset_files_json", "TEXT"),):
            add("custom_font", col, ddl)
        for col, ddl in (("is_draft", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("slug", "VARCHAR(255)"),
                         ("is_pending_review", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("submitter_name", "VARCHAR(120)"),
                         ("submitter_email", "VARCHAR(255)"),
                         ("submitter_phone", "VARCHAR(64)"),
                         ("submitter_notes", "TEXT"),
                         ("submitted_at", "DATETIME"),
                         ("published_at", "DATETIME"),
                         ("announcement_auto_archive_at", "DATETIME"),
                         ("links_json", "TEXT"),
                         ("gallery_json", "TEXT")):
            add("post", col, ddl)
        for col, ddl in (("published_at", "DATETIME"),
                         ("is_pending_review", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("submitter_name", "VARCHAR(120)"),
                         ("submitter_email", "VARCHAR(255)"),
                         ("submitter_phone", "VARCHAR(64)"),
                         ("submitter_notes", "TEXT"),
                         ("submitted_at", "DATETIME"),
                         ("submission_attachment_filename", "VARCHAR(500)"),
                         ("submission_attachment_original", "VARCHAR(500)")):
            add("story", col, ddl)
        # Blog post body block editor: stores the visual drag-and-drop
        # payload as a JSON list. NULL means "fall back to the legacy
        # markdown `body` column" so upgrades don't blank existing posts.
        for col, ddl in (("body_blocks_json", "TEXT"),):
            add("blog_post", col, ddl)
        for col, ddl in (("is_archived", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("archived_at", "DATETIME")):
            add("access_request", col, ddl)
        for col, ddl in (("is_archived", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("archived_at", "DATETIME")):
            add("form_submission", col, ddl)
        for col, ddl in (("submission_roles_csv", "VARCHAR(200)"),
                         ("bg_dynamic_key", "VARCHAR(64)"),
                         ("bg_dynbg_config_json", "TEXT")):
            add("custom_form", col, ddl)
        for col, ddl in (("contact_form_enabled",       "BOOLEAN NOT NULL DEFAULT 0"),
                         ("contact_form_to",            "VARCHAR(500)"),
                         ("contact_form_heading",       "VARCHAR(200)"),
                         ("contact_form_subheading",    "VARCHAR(500)"),
                         ("contact_form_intro",         "TEXT"),
                         ("contact_form_success_message", "VARCHAR(500)"),
                         ("contact_form_submit_label",  "VARCHAR(100)"),
                         ("contact_form_subject_required", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("contact_form_show_phone",    "BOOLEAN NOT NULL DEFAULT 1"),
                         ("contact_form_show_pic_name", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("contact_form_show_pic_email","BOOLEAN NOT NULL DEFAULT 1"),
                         ("contact_form_show_pic_phone","BOOLEAN NOT NULL DEFAULT 1"),
                         ("contact_form_width_mode",   "VARCHAR(16) NOT NULL DEFAULT 'boxed'"),
                         ("contact_form_max_width",    "INTEGER NOT NULL DEFAULT 1160"),
                         ("contact_form_padding_pct",  "INTEGER NOT NULL DEFAULT 5"),
                         # Recovery Contacts module (public /contactlist directory).
                         ("recovery_contacts_enabled",        "BOOLEAN NOT NULL DEFAULT 0"),
                         ("recovery_contacts_required_role",  "VARCHAR(32) NOT NULL DEFAULT 'admin'"),
                         ("recovery_contacts_heading",        "VARCHAR(200)"),
                         ("recovery_contacts_subheading",     "VARCHAR(500)"),
                         ("recovery_contacts_intro",          "TEXT"),
                         ("recovery_contacts_success_message", "VARCHAR(500)"),
                         ("recovery_contacts_submit_label",   "VARCHAR(100)"),
                         ("recovery_contacts_to",             "VARCHAR(500)"),
                         ("recovery_contacts_width_mode",     "VARCHAR(16) NOT NULL DEFAULT 'boxed'"),
                         ("recovery_contacts_max_width",      "INTEGER NOT NULL DEFAULT 1160"),
                         ("recovery_contacts_padding_pct",    "INTEGER NOT NULL DEFAULT 5"),
                         ("recovery_contacts_email_alerts",   "BOOLEAN NOT NULL DEFAULT 0"),
                         ("recovery_contacts_removal_alerts", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("frontend_meetings_list_bg_dynamic_key", "VARCHAR(64)"),
                         ("frontend_events_list_bg_dynamic_key", "VARCHAR(64)"),
                         ("frontend_announcements_list_bg_dynamic_key", "VARCHAR(64)"),
                         ("frontend_stories_list_bg_dynamic_key", "VARCHAR(64)"),
                         ("frontend_story_bg_dynamic_key", "VARCHAR(64)"),
                         ("frontend_literature_library_bg_dynamic_key", "VARCHAR(64)"),
                         ("frontend_printlist_bg_dynamic_key", "VARCHAR(64)"),
                         ("frontend_meetings_list_bg_dynbg_config_json", "TEXT"),
                         ("frontend_events_list_bg_dynbg_config_json", "TEXT"),
                         ("frontend_announcements_list_bg_dynbg_config_json", "TEXT"),
                         ("frontend_stories_list_bg_dynbg_config_json", "TEXT"),
                         ("frontend_story_bg_dynbg_config_json", "TEXT"),
                         ("frontend_literature_library_bg_dynbg_config_json", "TEXT"),
                         ("frontend_printlist_bg_dynbg_config_json", "TEXT"),
                         ("frontend_hero_bg_dynbg_config_json", "TEXT"),
                         ("frontend_site_index_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("frontend_site_index_template", "VARCHAR(64) NOT NULL DEFAULT 'grouped'"),
                         ("frontend_site_index_heading", "VARCHAR(200)"),
                         ("frontend_site_index_subheading", "VARCHAR(500)"),
                         ("frontend_site_index_sort_mode", "VARCHAR(32) NOT NULL DEFAULT 'grouped'"),
                         ("frontend_site_index_show_pages", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("frontend_site_index_show_meetings", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("frontend_site_index_show_events", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("frontend_site_index_show_announcements", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("frontend_site_index_show_stories", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("frontend_site_index_show_library", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("frontend_site_index_bg_dynamic_key", "VARCHAR(64)"),
                         ("frontend_site_index_bg_dynbg_config_json", "TEXT"),
                         # Frontend asset caching (Web Frontend → Caching).
                         ("media_cache_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("media_cache_max_age", "INTEGER NOT NULL DEFAULT 604800"),
                         ("media_cache_immutable", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("media_cache_static_assets", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("media_cache_static_max_age", "INTEGER NOT NULL DEFAULT 2592000"),
                         ("media_cache_autobump", "BOOLEAN NOT NULL DEFAULT 1"),
                         ("media_cache_version", "INTEGER NOT NULL DEFAULT 1"),
                         ("media_cache_cleared_at", "DATETIME")):
            add("site_setting", col, ddl)
        # Recovery Contacts entries — columns added after the table shipped, so
        # existing installs need them patched on (fresh installs get them
        # from db.create_all()). matched_entry_id is a self-referential FK
        # used by the public "update my entry" flow.
        for col, ddl in (("available_to_sponsor", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("wants_update", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("wants_removal", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("removal_token", "VARCHAR(64)"),
                         ("removal_confirmed_at", "DATETIME"),
                         ("contact_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("contact_count", "INTEGER NOT NULL DEFAULT 0"),
                         ("matched_entry_id", "INTEGER REFERENCES recovery_contact(id) ON DELETE SET NULL"),
                         # Anti-abuse on the self-service update/removal flow
                         # (24 h update rate-limit + 7-day disavow lock).
                         ("last_update_request_at", "DATETIME"),
                         ("requests_locked_until", "DATETIME")):
            add("recovery_contact", col, ddl)
        for col, ddl in (("kind", "VARCHAR(16) NOT NULL DEFAULT 'link'"),
                         ("button_style", "VARCHAR(16) NOT NULL DEFAULT 'pill'"),
                         ("open_in_new_tab", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("icon_before_color", "VARCHAR(16)"),
                         ("icon_after_color", "VARCHAR(16)"),
                         ("icon_before_size", "INTEGER"),
                         ("icon_after_size", "INTEGER"),
                         ("link_size", "VARCHAR(16)"),
                         ("link_size_pct", "INTEGER"),
                         ("override_color", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("custom_color", "VARCHAR(16)"),
                         ("form_trigger", "VARCHAR(64)")):
            add("frontend_nav_link", col, ddl)
        for col, ddl in (("bg_image_filename", "VARCHAR(500)"),
                         ("bg_mode", "VARCHAR(16) NOT NULL DEFAULT 'cover'"),
                         ("bg_tile_scale", "INTEGER NOT NULL DEFAULT 100"),
                         ("heading_color", "VARCHAR(16)"),
                         ("heading_align", "VARCHAR(16) NOT NULL DEFAULT 'auto'"),
                         ("heading_font", "VARCHAR(64)"),
                         ("subheading_color", "VARCHAR(16)"),
                         ("subheading_font", "VARCHAR(64)"),
                         ("layout_key", "VARCHAR(64) NOT NULL DEFAULT 'custom'"),
                         ("width_mode", "VARCHAR(16) NOT NULL DEFAULT 'boxed'"),
                         ("max_width", "INTEGER NOT NULL DEFAULT 1160"),
                         ("full_padding_pct", "INTEGER NOT NULL DEFAULT 4"),
                         ("pad_top", "INTEGER NOT NULL DEFAULT 80"),
                         ("pad_bottom", "INTEGER NOT NULL DEFAULT 96"),
                         ("pad_x", "INTEGER NOT NULL DEFAULT 16"),
                         ("section_gap", "INTEGER NOT NULL DEFAULT 32"),
                         ("block_margin_y", "INTEGER NOT NULL DEFAULT 12"),
                         ("bg_dynamic_key", "VARCHAR(64)"),
                         ("bg_dynbg_config_json", "TEXT"),
                         ("bg_color", "VARCHAR(16)"),
                         ("bg_color_dark", "VARCHAR(16)"),
                         ("bg_color_dark_mode", "VARCHAR(16) NOT NULL DEFAULT 'same'"),
                         ("is_private", "BOOLEAN NOT NULL DEFAULT 0"),
                         ("og_title", "VARCHAR(200)"),
                         ("og_description", "TEXT"),
                         ("og_image_filename", "VARCHAR(500)"),
                         ("draft_json", "TEXT"),
                         ("draft_saved_at", "DATETIME")):
            add("page", col, ddl)

        # NotFoundEvent — added in 2.8.1. Captures the source IP on
        # public 404s so the Watchtower 404s tab can show "who's hitting
        # this URL" and offer a one-click block. Existing rows get NULL
        # IPs (the column was added after the fact); new 404s carry IPs.
        add("not_found_event", "ip", "VARCHAR(45)")

        # FrontendSyncPeer.self_role — added in 2.12.1. The 2.12.0 table was
        # created without it, so existing paired installs need the column
        # back-filled. "" means "role not chosen yet"; the setup wizard sets
        # it to 'live' or 'staging'.
        add("frontend_sync_peer", "self_role", "VARCHAR(16) NOT NULL DEFAULT ''")

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

        # Seed the dynamic utility-bar columns from the Recovery Blue
        # header's hardcoded content (Hyperlist beta link on the left,
        # 24-hour helpline on the right, blue-on-white palette). The
        # update runs only on Recovery Blue installs whose utility-bar
        # fields are still entirely null — so once an admin saves their
        # own bar config, this stops touching anything. Safe to re-run
        # every boot: the WHERE clause makes it a no-op past the first
        # successful seed.
        import json as _ub_json
        _ub_left = _ub_json.dumps([
            {"kind": "link", "label": "Hyperlist (beta)", "url": "#",
             "icon": "", "open_in_new_tab": False},
        ])
        _ub_right = _ub_json.dumps([
            {"kind": "text",   "label": "CMA 24-Hour Helpline",
             "url": "", "icon": "phone", "open_in_new_tab": False},
            {"kind": "button", "label": "855-METH-FREE",
             "url": "tel:+18556384373",
             "icon": "", "open_in_new_tab": False},
        ])
        # "Empty" matches both NULL and the literal '[]' the save route
        # writes for an empty list — so the seed runs whether the install
        # never touched the form or saved a blank one before the seed
        # was wired up.
        _ub_res = conn.execute(text(
            "UPDATE site_setting "
            "SET utility_bar_bg_color    = '#0B5CFF', "
            "    utility_bar_text_color  = '#ffffff', "
            "    utility_bar_left_json   = :left, "
            "    utility_bar_right_json  = :right "
            "WHERE frontend_header_template = 'recovery-blue' "
            "  AND COALESCE(utility_bar_left_json, '[]')  = '[]' "
            "  AND COALESCE(utility_bar_right_json, '[]') = '[]'"
        ), {"left": _ub_left, "right": _ub_right})
        app.logger.info("utility_bar seed rowcount=%s", _ub_res.rowcount)


def _seed_homepage_page(app):
    """Ensure there's a Page designated as the public `/` root.

    Runs after `_migrate_sqlite` (which adds the `homepage_page_id`
    column on existing DBs) and after `db.create_all()` (which creates
    the Page table on fresh installs). The function is idempotent —
    it short-circuits when `SiteSetting.homepage_page_id` is already
    set, so it's safe to run on every boot.

    Strategy:
      1. If `SiteSetting.homepage_page_id` is already set → no-op.
      2. Else, look for an existing Page with slug='home' → adopt it.
      3. Else, create a fresh "Home" Page (slug='home', published,
         minimal hero placeholder so the admin sees something on first
         render) and link it.

    Net effect: every install has a homepage Page after first boot. The
    admin can re-point `homepage_page_id` to any other Page from the
    Pages admin if they prefer a different page as the root."""
    import json
    import uuid
    from .models import Page, SiteSetting
    s = SiteSetting.query.first()
    if s is None:
        # First boot, no SiteSetting yet — skip; we'll seed on the
        # next boot once SiteSetting exists (created lazily on first
        # admin save).
        return
    if s.homepage_page_id:
        existing = Page.query.get(s.homepage_page_id)
        if existing is not None:
            return
        # Stale FK — fall through and re-seed below.
        s.homepage_page_id = None
    # Prefer an existing slug='home' page if the admin happened to
    # create one before this auto-seed ran.
    page = Page.query.filter_by(slug="home").first()
    if page is None:
        # Single-section blank shell with one hero block so the admin
        # immediately sees the page-builder rather than a blank
        # canvas. The hero defaults match the legacy homepage's
        # opening copy so existing admins recognise the starting
        # point. Block ids use uuid4 hex so they don't collide with
        # any future block additions.
        hero_id = uuid.uuid4().hex[:8]
        sections = [{
            "title": "",
            "blocks": [{
                "id": hero_id,
                "type": "hero",
                "data": {
                    "heading": "You are not alone.",
                    "subheading": "Find meetings, connect with your community, and take the next step in your recovery journey.",
                    "eyebrow": "A recovery fellowship portal.",
                    "tagline_enabled": True,
                    "buttons": [],
                },
            }],
        }]
        page = Page(
            slug="home", title="Home",
            blocks_json=json.dumps(sections),
            template="standard", is_published=True, is_private=False,
            layout_key="page-blank",
        )
        db.session.add(page)
        db.session.flush()  # populate page.id
    s.homepage_page_id = page.id
    db.session.commit()
    app.logger.info("Seeded homepage Page id=%s slug='home' as SiteSetting.homepage_page_id", page.id)


def _seed_admin(app):
    from werkzeug.security import generate_password_hash
    if User.query.count() == 0:
        username = os.environ.get("TSP_ADMIN_USERNAME", "admin")
        password = os.environ.get("TSP_ADMIN_PASSWORD", "").strip()
        email = os.environ.get("TSP_ADMIN_EMAIL", "admin@example.com")
        # Production: refuse to seed admin/admin. The installer always
        # generates a random TSP_ADMIN_PASSWORD into the .env file, but
        # someone bringing the image up manually (docker run / a
        # hand-written compose) can easily miss it, and a public
        # /tspro/auth/login with `admin` / `admin` is a takeover in one
        # request. Fail loudly so the operator notices and supplies a
        # real password rather than silently shipping a known default.
        is_debug = os.environ.get("TSP_DEBUG", "").lower() in ("1", "true", "yes")
        if not password:
            if is_debug:
                password = "admin"
                app.logger.warning(
                    "TSP_ADMIN_PASSWORD not set — seeding %s/admin "
                    "because TSP_DEBUG=1. Do NOT run with this in "
                    "production.", username,
                )
            else:
                raise RuntimeError(
                    "TSP_ADMIN_PASSWORD is required on first boot. "
                    "Set a strong password via environment variable "
                    "(the bundled installer generates one automatically; "
                    "manual docker-run setups need to provide it). "
                    "TSP_DEBUG=1 falls back to admin/admin for local dev."
                )
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


def _seed_footer_layouts(app):
    """Seed the editable Recovery Blue footer as a CustomLayout
    (kind='footer', is_prebuilt=False) on first boot. Unlike the
    homepage layouts above (is_prebuilt=True, locked from edits) this
    one is intentionally editable — admins can rearrange its blocks in
    the layout builder, and the corresponding admin content sections
    on the Footer page populate the block content. The other footer
    presets (classic / minimal / stacked / mega) stay non-editable in
    FOOTER_TEMPLATES with their own Jinja files.

    The seed only inserts when the row is missing (idempotent at boot);
    once seeded, edits stick and we never overwrite. If the admin
    deletes the seeded row, it WILL come back on next boot — that's
    intentional so a wiped footer can always be restored to a known
    starting point."""
    import json
    from .models import CustomLayout
    KEY = "recovery-blue"
    if CustomLayout.query.filter_by(key=KEY).first():
        return  # Already seeded (or admin-customised) — leave alone.
    blocks = [
        {"type": "row", "cols": 1, "columns": [
            [{"type": "meeting_locations"}],
        ]},
        {"type": "row", "cols": 1, "columns": [
            [{"type": "contact_section"}],
        ]},
        {"type": "row", "cols": 3, "columns": [
            [{"type": "brand"}],
            [{"type": "copyright"}],
            [{"type": "secondary_nav"}],
        ]},
    ]
    db.session.add(CustomLayout(
        key=KEY, name="Recovery Blue",
        description=("Fellowship-style footer: meeting-location cards, a contact "
                     "section, then brand + copyright + secondary nav at the bottom. "
                     "Editable — drag blocks around in the layout builder."),
        blocks_json=json.dumps(blocks),
        kind="footer", is_prebuilt=False,
    ))
    db.session.commit()
    app.logger.info("Seeded Recovery Blue footer CustomLayout")


def _seed_page_layouts(app):
    """Seed the prebuilt Page layout presets. Mirrors the homepage's
    pattern (kind='homepage', is_prebuilt=True, locked from edits) but
    targets content-page block types — paragraphs, headings, images,
    buttons, lists, and containers — instead of homepage-specific
    blocks. Each preset's blocks_json is a sequence of `{type: <key>}`
    dicts; selecting one in the page editor copies fresh blank blocks
    of those types into page.blocks_json so the admin can fill in the
    actual content.

    Keys are prefixed `page-` to avoid colliding with the homepage
    presets in the shared CustomLayout.key namespace."""
    import json
    from .models import CustomLayout
    PRESETS = [
        {
            "key": "page-blank",
            "name": "Blank",
            "description": "An empty page with one section. Add any content blocks you like.",
            "blocks": [],
        },
        {
            "key": "page-article",
            "name": "Article",
            "description": "Heading, paragraph, hero image, then more paragraphs. Best for long-form text content.",
            "blocks": ["heading", "paragraph", "image", "paragraph"],
        },
        {
            "key": "page-marketing",
            "name": "Marketing landing",
            "description": "Hero container with a heading + lead paragraph + CTA button, followed by a three-column feature container and a closing CTA.",
            "blocks": ["container", "container", "button"],
        },
        {
            "key": "page-faq",
            "name": "FAQ",
            "description": "Heading, intro paragraph, and a numbered list. Drop in additional sections to expand.",
            "blocks": ["heading", "paragraph", "list"],
        },
        {
            "key": "page-showcase",
            "name": "Two-column showcase",
            "description": "Two-column hero (image left, heading + paragraph + CTA right) plus a single-column content area underneath — heading + paragraph + bulleted list ready for a guidelines / cards / policy block.",
            # Each entry's `data` field carries the stamped block's
            # initial styling. The user inherits these on layout
            # apply and can edit any of them via the block's
            # settings — they're a starting point, not a constant.
            "blocks": [
                {
                    "type": "split",
                    "data": {"gap": "3rem", "padding": "0", "align": "center"},
                    "left":  [{"type": "image"}],
                    "right": [
                        {"type": "heading", "data": {"level": 2}},
                        {"type": "paragraph"},
                        {"type": "button"},
                    ],
                },
                # Single-column section underneath the hero. Stays
                # unstyled by default (transparent, no border / shadow
                # / radius); the admin opts into card chrome via the
                # container settings if they want it. Carries a small
                # gap so the heading + paragraph + list have breathing
                # room without imposing visual chrome.
                {
                    "type": "container",
                    "data": {"gap": "1rem"},
                    "blocks": [
                        {"type": "heading", "data": {"level": 2}},
                        {"type": "paragraph"},
                        {"type": "list"},
                    ],
                },
            ],
        },
        {
            "key": "page-wiki",
            "name": "Wiki",
            "description": "Long-form article on the left with a sticky 'On this page' TOC sidebar on the right. The sidebar auto-populates from heading blocks anywhere on the page.",
            "blocks": [
                {
                    "type": "split",
                    "data": {"gap": "3rem", "padding": "0",
                              "grid_columns": "minmax(0, 1fr) 260px"},
                    "left":  [
                        {"type": "heading", "data": {"level": 2}},
                        {"type": "paragraph"},
                        {"type": "heading", "data": {"level": 2}},
                        {"type": "paragraph"},
                    ],
                    "right": [{"type": "toc_sidebar"}],
                },
            ],
        },
    ]
    for p in PRESETS:
        row = CustomLayout.query.filter_by(key=p["key"]).first()
        # Preset entries can either be shorthand strings ("image") or
        # full dicts ({"type":"split","left":[…],"right":[…]}). Strings
        # get wrapped into {type: ...}; dicts pass through verbatim.
        blocks_json = json.dumps([
            (b if isinstance(b, dict) else {"type": b}) for b in p["blocks"]
        ])
        if row is None:
            db.session.add(CustomLayout(
                key=p["key"], name=p["name"], description=p["description"],
                blocks_json=blocks_json, kind="page", is_prebuilt=True,
            ))
        elif row.is_prebuilt:
            row.name = p["name"]
            row.description = p["description"]
            row.blocks_json = blocks_json
            row.kind = "page"
    db.session.commit()
