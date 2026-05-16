# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import json
import os
import re
import time
import uuid
from functools import wraps
from flask import (Blueprint, render_template, redirect, url_for, request,
                   flash, send_from_directory, abort, current_app, jsonify)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from .models import (db, User, Meeting, MeetingFile, MeetingSchedule, MeetingLibrary, CustomIcon, CustomFont, CustomLayout, FrontendHeroButton,
                     Post, Story, BlogPost, BlogCategory, BlogTag,
                     ZoomAccount, ZoomOtpEmail, Location, Library, LibraryItem,
                     LibraryCategory, MediaItem, NavLink, SiteSetting,
                     IntergroupAccount, IntergroupOfficer, AccessRequest, ContactSubmission, PasswordResetToken,
                     FrontendNavItem, UrlRedirect, EntitySlugHistory, Page,
                     FrontendNavColumn, FrontendNavLink, FILE_CATEGORIES,
                     DAYS_OF_WEEK, INTERGROUP_LIBRARY_NAMES)

INTERGROUP_DEFAULT_ACCOUNTS = [
    ('Chair', 'chair@dccma.com'),
    ('Secretary', 'secretary@dccma.com'),
    ('Treasurer', 'treasurer@dccma.com'),
    ('Activities Chair', 'activities@dccma.com'),
    ('H&I Chair', 'hni@dccma.com'),
    ('Literature Chair', 'literature@dccma.com'),
    ('Public Information Chair', 'public@dccma.com'),
    ('General Inbox', 'info@dccma.com'),
]


def _seed_intergroup_defaults(s):
    changed = False
    if IntergroupAccount.query.count() == 0:
        for i, (role, email) in enumerate(INTERGROUP_DEFAULT_ACCOUNTS):
            db.session.add(IntergroupAccount(role=role, email=email, position=i))
        changed = True
    if not s.ig_webmail_url:
        s.ig_webmail_url = "https://webmail.dccma.com"; changed = True
    if not s.ig_incoming_host:
        s.ig_incoming_host = "imap.dreamhost.com"; changed = True
    if not s.ig_incoming_port:
        s.ig_incoming_port = "IMAP Port 993"; changed = True
    if not s.ig_outgoing_host:
        s.ig_outgoing_host = "smtp.dreamhost.com"; changed = True
    if not s.ig_outgoing_port:
        s.ig_outgoing_port = "SMTP Port 465"; changed = True
    if not s.ig_setup_notes:
        s.ig_setup_notes = (
            "Use your entire email address for User Name, e.g. username@example.com\n"
            "Security settings: select SSL/TLS as 'Security Type' and use Normal Password for 'Authentication'."
        ); changed = True
    if changed:
        db.session.commit()


def _get_site_setting():
    s = SiteSetting.query.first()
    if not s:
        s = SiteSetting()
        db.session.add(s)
        db.session.commit()
    return s


def _dynbg_config_from_form(form, config_field):
    """Extract the full dynbg config (overlay + 3 colours + scope +
    noise size/intensity + randomize) from a form submission and
    return the JSON string to persist in the matching `<config_field>`
    column.

    The shared dynbg picker macro emits these hidden inputs alongside
    its base-key input:
      <config_field>__overlay
      <config_field>__c1 / __c2 / __c3
      <config_field>__scope
      <config_field>__noise_size
      <config_field>__noise_intensity
      <config_field>__randomize_colors
      <config_field>__randomize_positions
    Each value flows through ``dynbg.encode_config`` (catalog +
    regex + numeric range gates). Returns None when nothing was set
    so the column stores NULL rather than an empty `{}` blob.
    """
    from . import dynbg as _dynbg
    import json as _json
    cfg = _dynbg.encode_config(
        overlay_key=form.get(f"{config_field}__overlay"),
        colors=[form.get(f"{config_field}__c{i}") for i in (1, 2, 3)],
        scope=form.get(f"{config_field}__scope"),
        noise_size=form.get(f"{config_field}__noise_size"),
        noise_intensity=form.get(f"{config_field}__noise_intensity"),
        randomize_colors=form.get(f"{config_field}__randomize_colors") == "1",
        randomize_positions=form.get(f"{config_field}__randomize_positions") == "1",
        # Animation is opt-out — only the explicit "1" disables motion.
        # encode_config drops the field entirely when animate=True so
        # the JSON stays minimal for the common case.
        animate=False if form.get(f"{config_field}__animate_off") == "1" else True,
        # Legacy single-flag input still accepted on the off-chance an
        # older form posts it — encode_config maps it to both new flags.
        randomize=form.get(f"{config_field}__randomize") == "1" or None,
    )
    return _json.dumps(cfg) if cfg else None


def _get_otp_email():
    otp = ZoomOtpEmail.query.first()
    if not otp:
        otp = ZoomOtpEmail()
        db.session.add(otp)
        db.session.commit()
    return otp

MEETING_TYPES = ("in_person", "online", "hybrid")
from .crypto import encrypt, decrypt

# Admin app blueprint: everything mounted under /tspro.
bp = Blueprint("main", __name__, url_prefix="/tspro")

# Truly public routes (served at the root, no auth or lax auth):
# /pub/*, /site-branding/footer-logo, /site-branding/og-image, /request-access.
public_bp = Blueprint("public", __name__)

CATEGORY_LABELS = {
    "readings": "Readings",
    "scripts": "Scripts",
    "external_links": "External Links",
    "videos": "Videos",
    "images": "Images",
    "documents": "Documents",
}


def _safe_referrer():
    """Return ``request.referrer`` only when it points at our own host.

    Defense-in-depth against an open-redirect class issue: many handlers
    fall back to ``request.referrer`` to bounce the user back where they
    came from after a flash. The Referer header is set by the browser
    and can be steered by an attacker hosting a page that links into a
    protected route — without this validation, a permission-denied flash
    would redirect the victim off to ``https://attacker.example/`` and
    expose them to phishing in the redirected window.

    Same-origin check uses the request's ``host_url`` netloc so a
    visitor coming from ``https://our-site/`` or ``http://our-site:8090/``
    both pass, but ``https://attacker.example/`` fails the netloc
    comparison and we return ``None`` (callers fall through to whatever
    ``url_for(...)`` they intended).
    """
    ref = request.referrer
    if not ref:
        return None
    try:
        from urllib.parse import urlparse
        ref_parsed = urlparse(ref)
        host_parsed = urlparse(request.host_url)
    except Exception:
        return None
    if ref_parsed.scheme not in ("http", "https"):
        return None
    if ref_parsed.netloc != host_parsed.netloc:
        return None
    return ref


def editor_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.can_edit():
            flash("You don't have permission to do that", "danger")
            return redirect(_safe_referrer() or url_for("main.index"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.is_admin():
            flash("Admins only", "danger")
            return redirect(_safe_referrer() or url_for("main.index"))
        return f(*args, **kwargs)
    return wrapper


def meeting_admin_required(f):
    """Gate for meeting create + delete: admins and Intergroup Members
    only. Editors keep edit/schedule/attach
    authority on existing meetings via ``editor_required`` elsewhere
    but can't provision new entries or remove them."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.can_create_meetings():
            flash("You don't have permission to do that", "danger")
            return redirect(_safe_referrer() or url_for("main.index"))
        return f(*args, **kwargs)
    return wrapper


def library_admin_required(f):
    """Gate for library create + metadata edit: admins and Intergroup
    Members only. Editors keep their authority
    to add / edit / delete readings inside existing libraries via
    ``_require_can_edit_library`` elsewhere, but provisioning new
    library entries or renaming / re-describing existing ones is
    held back to the trusted-servant tier."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.can_manage_libraries():
            flash("You don't have permission to do that", "danger")
            return redirect(_safe_referrer() or url_for("main.index"))
        return f(*args, **kwargs)
    return wrapper




def _require_can_edit_library(library):
    """Inline gate used by library/reading edit handlers. Routes that
    accept a library or reading-by-id call this after the lookup so the
    permission check can consult the library's name. Restricted
    Intergroup libraries are limited to admins + ``intergroup_member``;
    everything else uses the broad editor gate."""
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    if not current_user.can_edit_library(library):
        flash("You don't have permission to edit this library", "danger")
        return redirect(_safe_referrer() or url_for("main.index"))
    return None


@bp.app_context_processor
def inject_globals():
    try:
        site = SiteSetting.query.first()
    except Exception:
        site = None
    try:
        nav_links = NavLink.query.order_by(NavLink.position, NavLink.id).all()
    except Exception:
        nav_links = []
    pending_access_count = 0
    unread_contact_count = 0
    try:
        if current_user.is_authenticated and current_user.is_admin():
            pending_access_count = AccessRequest.query.filter_by(
                status="pending", is_archived=False).count()
            unread_contact_count = ContactSubmission.query.filter_by(
                is_read=False, is_archived=False).count()
    except Exception:
        pending_access_count = 0
        unread_contact_count = 0
    try:
        otp = _get_otp_email()
    except Exception:
        otp = None
    return {"CATEGORY_LABELS": CATEGORY_LABELS, "FILE_CATEGORIES": FILE_CATEGORIES,
            "DAYS_OF_WEEK": DAYS_OF_WEEK, "site": site, "nav_links": nav_links,
            "pending_access_count": pending_access_count,
            "unread_contact_count": unread_contact_count, "otp": otp}


DASHBOARD_WIDGET_KEYS = ("server-metrics", "visitor-metrics", "currently-online", "meetings", "libraries", "files", "access-requests", "contact-form", "deletions")

ONLINE_WINDOW = timedelta(minutes=5)
LAST_SEEN_THROTTLE = timedelta(seconds=60)


@bp.before_request
def _guard_frontend_module():
    """When the Web Frontend module is disabled, block the /tspro/frontend/*
    editor routes so they can't be reached by URL. The settings-modal toggle
    (and its handler) stay reachable because they live under /tspro/site/*."""
    if not request.path.startswith("/tspro/frontend"):
        return None
    # The module-enable toggle handler itself must always be reachable so an
    # admin can turn the module back on. Everything else is gated.
    if request.endpoint == "main.frontend_module_toggle":
        return None
    try:
        s = SiteSetting.query.first()
    except Exception:
        return None
    if s is None or getattr(s, "frontend_module_enabled", True):
        return None
    if getattr(current_user, "is_authenticated", False):
        flash("Web Frontend module is disabled. Enable it in Settings → Web Frontend.", "warning")
    return redirect(url_for("main.index"))


# Endpoint-name suffixes that identify asset-serving / sub-resource
# routes (file downloads, image fetches, PDF generators, JSON probes,
# logo fetches, etc.). Resolving an endpoint to one of these means the
# request is fetching a *resource* belonging to a page, not navigating
# to a page itself, so it must not flip the user's "where they are
# right now" pointer to a download URL.
_LOCATION_SKIP_SUFFIXES = (
    "_download", "_pdf", "_content", "_image", "_logo",
    "_favicon", "_serve", "_json", "_thumb", "_thumbnail",
)
# Path extensions (case-insensitive) that always indicate a sub-
# resource even when the endpoint name doesn't follow the convention
# above — covers static-passthrough routes and any new asset endpoint
# that ships before the suffix list catches up.
_LOCATION_SKIP_EXTS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".ico",
    ".pdf", ".json", ".woff", ".woff2", ".ttf", ".otf",
    ".mp4", ".webm", ".mp3", ".zip", ".db", ".css", ".js",
)


@bp.before_app_request
def _track_last_seen():
    """Throttled last_seen_at update for the authenticated user.

    Also captures the user's current navigation location (endpoint +
    path) so the User Log live widget can show where each online
    person is right now. Skips:

      • Non-GET requests — POSTs redirect to the destination, which
        re-fires this hook with the friendlier final URL.
      • API / metrics polling endpoints — these would otherwise pin
        every viewer to ``/api/online-users`` etc.
      • Static + favicon assets.
      • **Sub-resource fetches** — any endpoint whose name ends in
        ``_download`` / ``_image`` / ``_logo`` / ``_pdf`` / ``_content``
        / ``_favicon`` / ``_serve`` / ``_json`` / ``_thumb`` and any
        request whose path ends in a known asset extension. These are
        files the page being viewed is loading, not the page itself,
        so we hold the location pointer at the parent page.

    Within those rules the location is written either when it
    actually changed (snappy: navigation flips inside one tick of the
    5-second poll) OR when the standard last-seen throttle lapses
    (keeps a pure idle user's row warm enough that they don't drop
    off the online list)."""
    if not getattr(current_user, "is_authenticated", False):
        return
    if request.method != "GET":
        return
    endpoint = request.endpoint or ""
    if endpoint.startswith("main.api_") or endpoint == "static":
        return
    if endpoint.endswith("_metrics"):
        return
    # The forgot/reset and login pages aren't reachable when
    # authenticated, but be defensive.
    if endpoint in ("auth.login", "auth.logout", "auth.forgot_password",
                    "auth.reset_password"):
        return
    if endpoint and endpoint.endswith(_LOCATION_SKIP_SUFFIXES):
        return
    path_lower = request.path.lower()
    if path_lower.endswith(_LOCATION_SKIP_EXTS):
        return
    now = datetime.utcnow()
    last_seen = getattr(current_user, "last_seen_at", None)
    last_path = getattr(current_user, "last_path", None)
    path = request.path[:500]
    path_changed = (path != last_path)
    seen_throttled = last_seen is not None and (now - last_seen) < LAST_SEEN_THROTTLE
    if not path_changed and seen_throttled:
        return
    try:
        current_user.last_seen_at = now
        current_user.last_endpoint = endpoint[:128] or None
        current_user.last_path = path or None
        db.session.commit()
        # Touch the open login session too so the User Log's session
        # table reflects the user's freshness without an extra hook.
        from . import activity
        activity.touch_session(current_user)
    except Exception:
        db.session.rollback()


def _online_users():
    """Return (count, list[User]) of users seen within ONLINE_WINDOW."""
    cutoff = datetime.utcnow() - ONLINE_WINDOW
    q = (User.query
         .filter(User.last_seen_at.isnot(None))
         .filter(User.last_seen_at >= cutoff)
         .order_by(User.last_seen_at.desc()))
    users = q.all()
    return len(users), users


def _dashboard_order(user):
    import json
    saved = []
    if user and user.dash_order_json:
        try:
            parsed = json.loads(user.dash_order_json)
            if isinstance(parsed, list):
                saved = [k for k in parsed if k in DASHBOARD_WIDGET_KEYS]
        except (ValueError, TypeError):
            saved = []
    seen = set(saved)
    return saved + [k for k in DASHBOARD_WIDGET_KEYS if k not in seen]


@bp.route("/")
@login_required
def index():
    if current_user.is_admin():
        site = _get_site_setting()
        if not site.setup_complete:
            return redirect(url_for("main.setup_step", step=1))
    meetings = Meeting.query.filter(Meeting.archived_at.is_(None)).order_by(Meeting.name).all()
    libraries = Library.query.order_by(Library.name).all()
    recent_files = MediaItem.query.order_by(MediaItem.created_at.desc()).limit(6).all()
    access_requests = []
    unread_contacts = []
    online_count = 0
    online_users = []
    locked_accounts = []
    recent_deletions = []
    visitor_summary = None
    visitor_sparkline = []
    if current_user.is_admin():
        access_requests = (AccessRequest.query
                           .filter_by(status="pending", is_archived=False)
                           .order_by(AccessRequest.created_at.desc())
                           .limit(6).all())
        # Unread contact-form messages preview for the dashboard widget.
        # Cap at 6 so the card stays compact; full list lives at
        # /tspro/contact-form. Active-only filter mirrors the sidebar
        # badge so the two stay in lockstep.
        unread_contacts = (ContactSubmission.query
                           .filter_by(is_read=False, is_archived=False)
                           .order_by(ContactSubmission.created_at.desc())
                           .limit(6).all())
        online_count, online_users = _online_users()
        from sqlalchemy import func as _sa_func
        from .auth import currently_locked_usernames, user_lockout_expires_in
        locked_set = currently_locked_usernames()
        if locked_set:
            for u in User.query.filter(_sa_func.lower(User.username).in_(locked_set)).all():
                locked_accounts.append({
                    "id": u.id,
                    "username": u.username,
                    "expires_in_minutes": (user_lockout_expires_in(u.username) // 60) + 1,
                })
        # Most recent deletions across the portal — drives the new
        # admin-only Recent Deletions widget. Capped at 6 so the
        # widget stays compact; the full list lives at /delete-log.
        from .models import DeletedFile as _DF
        recent_deletions = (_DF.query
                            .order_by(_DF.deleted_at.desc())
                            .limit(6).all())
        # Visitor-metrics widget — top-line summary + 14-day sparkline
        # for the public frontend. Defensive: a brand-new install with
        # zero VisitorEvent rows still renders the widget (showing
        # zeros across the board) so the customize toggle's effect is
        # visible from the very first page load.
        try:
            from . import visitor_metrics as _vm
            visitor_summary = _vm.summary(days=30)
            visitor_sparkline = _vm.sparkline_views(days=14)
        except Exception:  # noqa: BLE001
            visitor_summary = None
            visitor_sparkline = []
    dashboard_order = _dashboard_order(current_user)
    return render_template("index.html", meetings=meetings, libraries=libraries,
                           recent_files=recent_files, access_requests=access_requests,
                           unread_contacts=unread_contacts,
                           online_count=online_count, online_users=online_users,
                           locked_accounts=locked_accounts,
                           recent_deletions=recent_deletions,
                           visitor_summary=visitor_summary,
                           visitor_sparkline=visitor_sparkline,
                           dashboard_order=dashboard_order)


@bp.route("/dashboard/customize", methods=["POST"])
@login_required
def dashboard_customize():
    current_user.dash_show_stats = request.form.get("dash_show_stats") == "1"
    current_user.dash_show_meetings = request.form.get("dash_show_meetings") == "1"
    current_user.dash_show_libraries = request.form.get("dash_show_libraries") == "1"
    current_user.dash_show_files = request.form.get("dash_show_files") == "1"
    current_user.dash_show_server_metrics = request.form.get("dash_show_server_metrics") == "1"
    if current_user.is_admin():
        current_user.dash_show_access_requests = request.form.get("dash_show_access_requests") == "1"
        current_user.dash_show_contact_form = request.form.get("dash_show_contact_form") == "1"
        current_user.dash_show_deletions = request.form.get("dash_show_deletions") == "1"
        current_user.dash_show_currently_online = request.form.get("dash_show_currently_online") == "1"
        current_user.dash_show_visitor_metrics = request.form.get("dash_show_visitor_metrics") == "1"
    db.session.commit()
    flash("Dashboard updated", "success")
    return redirect(url_for("main.index"))


@bp.route("/api/server-metrics")
@admin_required
def api_server_metrics():
    from .metrics import snapshot
    return jsonify(snapshot())


@bp.route("/api/version")
@login_required
def api_version():
    from .version import __version__, __build_id__
    return jsonify(version=__version__, build_id=__build_id__)


@bp.route("/api/online-users")
@login_required
def api_online_users():
    if not current_user.is_admin():
        abort(403)
    count, users = _online_users()
    return jsonify(count=count, users=[
        {"id": u.id,
         "username": u.username,
         "role": u.role,
         "last_seen_at": u.last_seen_at.isoformat() + "Z" if u.last_seen_at else None,
         "last_endpoint": u.last_endpoint or "",
         "last_path": u.last_path or "",
         "location_label": _endpoint_label(u.last_endpoint, u.last_path),
         "is_self": (u.id == current_user.id)}
        for u in users
    ])


# Friendly labels for the most common navigation endpoints so the
# live "currently online" widget can show readable destinations
# instead of raw paths. Falls back to a tidied path when the endpoint
# isn't in the table.
_ENDPOINT_LABELS = {
    "main.index":              "Dashboard",
    "main.meetings":           "Meetings",
    "main.meeting_detail":     "Meeting detail",
    "main.meeting_new":        "Creating a meeting",
    "main.libraries":          "Libraries",
    "main.library_detail":     "Library detail",
    "main.library_new":        "Creating a library",
    "main.intergroup_library_detail": "Intergroup library",
    "main.library_item_view":  "Library item detail",
    "main.library_item_new":   "Adding a library item",
    "main.intergroup":         "Intergroup",
    "main.zoom_tech":          "Zoom Tech",
    "main.zoom_accounts":      "Zoom Accounts",
    "main.posts":              "Announcements & Events",
    "main.post_new":           "Composing a post",
    "main.post_edit":          "Editing a post",
    "main.stories":            "Stories",
    "main.story_new":          "Composing a story",
    "main.story_edit":         "Editing a story",
    "main.wp_import_start":    "WordPress importer",
    "main.wp_import_map":      "WordPress importer · Map",
    "main.wp_import_dry_run":  "WordPress importer · Preview",
    "main.media":              "File browser",
    "main.locations":          "Meeting locations",
    "main.watchtower":         "Watchtower",
    "main.watchtower_visitors": "Watchtower · Visitors",
    "main.watchtower_access":  "Watchtower · Access",
    "main.watchtower_deletes": "Watchtower · Deletes",
    "main.watchtower_requests": "Watchtower · Requests",
    "main.frontend_dashboard": "Web Frontend",
    "auth.users":              "Settings → Users",
}


def _endpoint_label(endpoint, path):
    if endpoint and endpoint in _ENDPOINT_LABELS:
        return _ENDPOINT_LABELS[endpoint]
    if endpoint and endpoint.startswith("main.frontend_"):
        return "Web Frontend"
    if not path:
        return "—"
    # Strip the /tspro prefix and trim trailing slashes for a tidier
    # fallback on routes the lookup table hasn't covered.
    stub = path
    if stub.startswith("/tspro"):
        stub = stub[len("/tspro"):] or "/"
    return stub


@bp.route("/api/search")
@login_required
def api_search():
    """Backend-wide search. Returns grouped results across the
    content the user can already see in the sidebar — meetings,
    libraries + library items, meeting attachments, posts (when
    the module is enabled), media files, locations, and (admin-only)
    users.

    The query is split into whitespace-separated tokens; every token
    must match somewhere in the row (case-insensitive ``LIKE %tok%``
    on each searchable column, AND'd across tokens, OR'd across
    columns). Per-section cap of 8 keeps the modal compact; results
    arrive grouped + ready-to-render.

    Each result carries a ``url`` (relative path the modal navigates
    to on click), a ``label`` (the visible row), a ``snippet``
    (small muted line), an ``icon`` (Lucide name), and a ``type``
    label keyed by section."""
    from sqlalchemy import or_, and_, func as _sa_func
    raw = (request.args.get("q") or "").strip()
    if len(raw) < 2:
        return jsonify(query=raw, total=0, sections=[])
    tokens = [t for t in raw.split() if t]
    if not tokens:
        return jsonify(query=raw, total=0, sections=[])

    PER_SECTION = 8

    def _match(cols):
        """Build the AND-of-tokens / OR-of-columns predicate. ``cols``
        is a list of SQLAlchemy column expressions; each token must
        match at least one column (LIKE %tok%, case-insensitive)."""
        clauses = []
        for tok in tokens:
            like = f"%{tok.lower()}%"
            clauses.append(or_(*[_sa_func.lower(c).like(like) for c in cols]))
        return and_(*clauses)

    sections = []

    # --- Meetings -----------------------------------------------------------
    meetings = (Meeting.query
                .filter(_match([Meeting.name, Meeting.description,
                                Meeting.location]))
                .order_by(Meeting.name)
                .limit(PER_SECTION).all())
    if meetings:
        sections.append({
            "type": "meeting",
            "label": "Meetings",
            "icon": "calendar",
            "items": [{
                "label": m.name,
                "snippet": (m.location or m.description or "").strip()[:140],
                "url": url_for("main.meeting_detail", slug=m.public_slug),
                "icon": "calendar",
            } for m in meetings],
        })

    # --- Libraries ----------------------------------------------------------
    libraries = (Library.query
                 .filter(_match([Library.name, Library.description]))
                 .order_by(Library.name)
                 .limit(PER_SECTION).all())
    if libraries:
        sections.append({
            "type": "library",
            "label": "Libraries",
            "icon": "book",
            "items": [{
                "label": l.name,
                "snippet": (l.description or "").strip()[:140] or "Library",
                "url": (url_for("main.intergroup_library_detail", slug=l.public_slug)
                        if l.is_intergroup
                        else url_for("main.library_detail", slug=l.public_slug)),
                "icon": "book",
            } for l in libraries],
        })

    # --- Library items (Reading rows) --------------------------------------
    items = (LibraryItem.query
             .filter(_match([LibraryItem.title, LibraryItem.body,
                             LibraryItem.original_filename, LibraryItem.url]))
             .order_by(LibraryItem.created_at.desc())
             .limit(PER_SECTION).all())
    # Filter out items whose library the current user can't see
    # (Intergroup libraries restricted to admins / IG members). The
    # gate is identical to ``can_edit_library`` minus the editor
    # tier — non-IG libraries are visible to every authenticated
    # user, so we skip the check there.
    visible_items = []
    for it in items:
        lib = it.library
        if lib is not None and lib.is_intergroup and not current_user.can_edit_intergroup_libraries():
            continue
        visible_items.append(it)
    if visible_items:
        sections.append({
            "type": "library_item",
            "label": "Library files",
            "icon": "file-text",
            "items": [{
                "label": it.title,
                "snippet": ((it.library.name + " · ") if it.library else "")
                           + (it.original_filename or (it.body or "")[:120]),
                "url": (url_for("main.intergroup_library_detail", slug=it.library.public_slug)
                        if (it.library and it.library.is_intergroup)
                        else url_for("main.library_detail", slug=it.library.public_slug)) if it.library else "#",
                "icon": "file-text",
            } for it in visible_items],
        })

    # --- Meeting attachments (MeetingFile) ----------------------------------
    mfiles = (MeetingFile.query
              .filter(_match([MeetingFile.title, MeetingFile.description,
                              MeetingFile.original_filename, MeetingFile.url,
                              MeetingFile.body]))
              .order_by(MeetingFile.created_at.desc())
              .limit(PER_SECTION).all())
    if mfiles:
        sections.append({
            "type": "meeting_file",
            "label": "Meeting attachments",
            "icon": "file",
            "items": [{
                "label": f.title,
                "snippet": ((f.meeting.name + " · " + f.category.replace('_', ' '))
                            if f.meeting else "Meeting attachment"),
                "url": (url_for("main.meeting_detail", slug=f.meeting.public_slug)
                        + f"#{f.category}") if f.meeting else "#",
                "icon": "file",
            } for f in mfiles],
        })

    # --- Posts (announcements & events) ------------------------------------
    s = _get_site_setting()
    if s and s.posts_enabled:
        posts = (Post.query
                 .filter(Post.is_archived.is_(False))
                 .filter(_match([Post.title, Post.summary, Post.body,
                                 Post.location_name]))
                 .order_by(Post.updated_at.desc())
                 .limit(PER_SECTION).all())
        if posts:
            sections.append({
                "type": "post",
                "label": "Announcements & events",
                "icon": "megaphone",
                "items": [{
                    "label": p.title,
                    "snippet": (p.summary or (p.body or ""))[:140],
                    "url": url_for("main.post_edit", pid=p.id),
                    "icon": "megaphone",
                } for p in posts],
            })

    # --- Media files (the File Browser) ------------------------------------
    media = (MediaItem.query
             .filter(_match([MediaItem.original_filename]))
             .order_by(MediaItem.created_at.desc())
             .limit(PER_SECTION).all())
    # Mirror the media_list filter — non-admin users don't see the
    # featured images attached to pending-review submissions in the
    # global search either.
    if not current_user.is_admin():
        pending_uploads = {p.featured_image_filename for p in
                           Post.query.filter(Post.is_pending_review.is_(True),
                                             Post.featured_image_filename.isnot(None)).all()
                           if p.featured_image_filename}
        if pending_uploads:
            media = [m for m in media if m.stored_filename not in pending_uploads]
    if media:
        sections.append({
            "type": "media",
            "label": "Files",
            "icon": "folder",
            "items": [{
                "label": m.original_filename or m.stored_filename,
                "snippet": (m.mime_type or "File"),
                "url": url_for("main.media_list") + "?q=" + (m.original_filename or "")[:80],
                "icon": "folder",
            } for m in media],
        })

    # --- Locations ----------------------------------------------------------
    locs = (Location.query
            .filter(_match([Location.name, Location.address]))
            .order_by(Location.name)
            .limit(PER_SECTION).all())
    if locs:
        sections.append({
            "type": "location",
            "label": "Locations",
            "icon": "map-pin",
            "items": [{
                "label": l.name,
                "snippet": (l.address or "").strip()[:140] or "Meeting location",
                "url": url_for("main.locations"),
                "icon": "map-pin",
            } for l in locs],
        })

    # --- Users (admin-only) -------------------------------------------------
    if current_user.is_admin():
        users = (User.query
                 .filter(_match([User.username, User.email]))
                 .order_by(User.username)
                 .limit(PER_SECTION).all())
        if users:
            sections.append({
                "type": "user",
                "label": "Users",
                "icon": "user",
                "items": [{
                    "label": u.username,
                    "snippet": (u.email or "") + " · " + u.role.replace("_", " "),
                    "url": url_for("main.watchtower_access") + "?user_id=" + str(u.id),
                    "icon": "user",
                } for u in users],
            })

    total = sum(len(s["items"]) for s in sections)
    return jsonify(query=raw, total=total, sections=sections)


@bp.route("/dashboard/order", methods=["POST"])
@login_required
def dashboard_order_save():
    import json
    payload = request.get_json(silent=True) or {}
    order = payload.get("order") or []
    cleaned = []
    seen = set()
    for key in order:
        if isinstance(key, str) and key in DASHBOARD_WIDGET_KEYS and key not in seen:
            cleaned.append(key); seen.add(key)
    current_user.dash_order_json = json.dumps(cleaned)
    db.session.commit()
    return jsonify(ok=True, order=cleaned)


# --- Meetings ---

@bp.route("/meetings")
@login_required
def meetings():
    sort = request.args.get("sort") or request.cookies.get("view-meetings-sort") or "name"
    direction = request.args.get("dir") or request.cookies.get("view-meetings-dir") or "asc"
    view = request.args.get("view") or request.cookies.get("view-meetings") or "table"
    show = request.args.get("show") or "active"
    q = Meeting.query
    if show == "archived":
        q = q.filter(Meeting.archived_at.isnot(None))
    else:
        q = q.filter(Meeting.archived_at.is_(None))
    items = q.all()
    def first_day(m):
        days = [s.day_of_week for s in m.schedules]
        return (min(days) if days else 99)
    if sort == "day":
        items.sort(key=lambda m: (first_day(m), m.name.lower()))
    elif sort == "type":
        items.sort(key=lambda m: (m.meeting_type or "", m.name.lower()))
    else:
        items.sort(key=lambda m: m.name.lower())
    if direction == "desc":
        items.reverse()
    zoom_accounts = ZoomAccount.query.order_by(ZoomAccount.name).all()
    locations = Location.query.order_by(Location.name).all()
    # Shadow the `all_libraries` Jinja global (which is registered as
    # the underlying function, not its result) with a concrete list so
    # the shared `_meeting_modal.html` partial's `{% for lib in
    # all_libraries %}` loop works on this page too — matches the
    # pattern the meeting-edit route already uses.
    all_libraries = Library.query.order_by(Library.name).all()
    archived_count = Meeting.query.filter(Meeting.archived_at.isnot(None)).count()
    resp = current_app.make_response(
        render_template("meetings.html", meetings=items,
                        zoom_accounts=zoom_accounts, locations=locations,
                        all_libraries=all_libraries,
                        sort=sort, direction=direction, view=view,
                        show=show, archived_count=archived_count))
    resp.set_cookie("view-meetings", view, max_age=60*60*24*365, samesite="Lax")
    resp.set_cookie("view-meetings-sort", sort, max_age=60*60*24*365, samesite="Lax")
    resp.set_cookie("view-meetings-dir", direction, max_age=60*60*24*365, samesite="Lax")
    return resp


def _parse_schedule_form(form, meeting_id=None):
    """Return (list[dict], error_str|None). Each dict: day, start_time, duration, opens_time, zoom_account_id."""
    mtype = form.get("meeting_type", "in_person")
    days = form.getlist("schedule_day", type=int)
    times = form.getlist("schedule_time")
    end_times = form.getlist("schedule_end")
    opens_times = form.getlist("schedule_opens")
    meeting_acct_raw = form.get("zoom_account_id", "")
    meeting_acct = int(meeting_acct_raw) if meeting_acct_raw else None
    if mtype == "in_person":
        meeting_acct = None
    out = []
    for i, day in enumerate(days):
        t = (times[i] if i < len(times) else "").strip()
        if not t:
            continue
        end_t = (end_times[i] if i < len(end_times) else "").strip()
        if end_t:
            sh, sm = t.split(":"); eh, em = end_t.split(":")
            start_min = int(sh) * 60 + int(sm)
            end_min = int(eh) * 60 + int(em)
            if end_min <= start_min:
                end_min += 24 * 60
            dur = end_min - start_min
        else:
            dur = 60
        opens_t = (opens_times[i] if i < len(opens_times) else "").strip() or None
        if mtype == "in_person":
            opens_t = None
        out.append({"day": int(day), "start_time": t,
                    "duration": int(dur or 60), "opens_time": opens_t,
                    "zoom_account_id": meeting_acct})
    # Validate conflicts on zoom account assignments
    err = _check_schedule_conflicts(out, exclude_meeting_id=meeting_id)
    return out, err


def _check_schedule_conflicts(entries, exclude_meeting_id=None):
    existing = MeetingSchedule.query.filter(MeetingSchedule.zoom_account_id.isnot(None))
    if exclude_meeting_id is not None:
        existing = existing.filter(MeetingSchedule.meeting_id != exclude_meeting_id)
    existing = existing.all()
    for e in entries:
        if not e["zoom_account_id"]:
            continue
        h, m = e["start_time"].split(":")
        start = int(h) * 60 + int(m)
        end = start + int(e["duration"])
        for s in existing:
            if s.zoom_account_id != e["zoom_account_id"]:
                continue
            if s.day_of_week != e["day"]:
                continue
            if s.start_minutes() < end and s.end_minutes() > start:
                acct = db.session.get(ZoomAccount, s.zoom_account_id)
                return (f"Zoom account '{acct.name if acct else '?'}' is already booked on "
                        f"{DAYS_OF_WEEK[s.day_of_week]} {s.start_time} "
                        f"({s.meeting.name}).")
        # also check within the submitted batch
        for f in entries:
            if f is e:
                continue
            if f["zoom_account_id"] != e["zoom_account_id"]:
                continue
            if f["day"] != e["day"]:
                continue
            fh, fm = f["start_time"].split(":")
            fstart = int(fh) * 60 + int(fm)
            fend = fstart + int(f["duration"])
            if fstart < end and fend > start:
                return "Two schedule entries use the same Zoom account at overlapping times."
    return None


def _apply_library_selections(m, form):
    ids = set(form.getlist("library_ids", type=int))
    # rebuild association rows
    m.library_assocs = []
    db.session.flush()
    selected_library_items = []
    public_library_items = []
    for lid in ids:
        lib = db.session.get(Library, lid)
        if not lib:
            continue
        mode = form.get(f"library_mode_{lid}", "all")
        if mode not in ("all", "granular"):
            mode = "all"
        # Whole-library Public toggle — only meaningful when mode='all',
        # but we capture it regardless so the value survives mode flips
        # without the admin having to re-tick the box.
        whole_public = form.get(f"library_public_{lid}") == "1"
        m.library_assocs.append(
            MeetingLibrary(library=lib, mode=mode, public_visible=whole_public)
        )
        if mode == "granular":
            rids = form.getlist(f"library_readings_{lid}", type=int)
            if rids:
                selected_library_items.extend(
                    LibraryItem.query.filter(LibraryItem.id.in_(rids),
                                         LibraryItem.library_id == lid).all()
                )
        # Per-reading public-frontend visibility — only honoured when the
        # library is in granular mode. In 'all' mode the whole-library
        # flag above is the source of truth.
        if mode == "granular":
            prids = form.getlist(f"library_public_library_items_{lid}", type=int)
            if prids:
                public_library_items.extend(
                    LibraryItem.query.filter(LibraryItem.id.in_(prids),
                                         LibraryItem.library_id == lid).all()
                )
    m.selected_library_items = selected_library_items
    m.public_library_items = public_library_items


def _normalize_slug(value):
    """Lowercase, replace any non-alphanumeric run with a single hyphen,
    strip leading/trailing hyphens, cap at 200 chars. Returns None for
    blank/empty input so callers can store NULL and let
    ``Meeting.public_slug`` / ``Post.public_slug`` fall back to the
    title-derived default."""
    import re as _re
    if not value:
        return None
    s = _re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return (s[:200] or None)


def _record_slug_change(entity_type, entity_id, old_slug, new_slug):
    """Append a row to ``EntitySlugHistory`` capturing the before/after
    public slugs for an entity. Caller is responsible for skipping when
    they're equal."""
    from .models import EntitySlugHistory
    db.session.add(EntitySlugHistory(
        entity_type=entity_type,
        entity_id=entity_id,
        old_slug=old_slug,
        new_slug=new_slug,
        changed_by=getattr(current_user, "id", None) if hasattr(current_user, "id") else None,
    ))


def _unique_post_slug(base_slug, *, exclude_id=None):
    """Given a target slug, return one that's guaranteed not to collide
    with any other Post.public_slug. Appends ``-2``, ``-3``, ... until
    unique. Returns None when the input is blank.

    Two posts with the same ``public_slug`` would render the same URL
    (``/event/<slug>``, ``/announcement/<slug>``) — the route layer
    walks candidates in id order so the older one wins and the newer
    one becomes unreachable. Force uniqueness at save time so every
    post gets its own URL.
    """
    base = _normalize_slug(base_slug)
    if not base:
        return None
    q = Post.query
    if exclude_id is not None:
        q = q.filter(Post.id != exclude_id)
    used = {p.public_slug for p in q.all()}
    candidate = base
    n = 2
    while candidate in used:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _unique_story_slug(base_slug, *, exclude_id=None):
    """Same uniqueness sweep as ``_unique_post_slug``, scoped to Story
    so the public ``/stories/<slug>`` route can rely on each row owning
    its URL."""
    base = _normalize_slug(base_slug)
    if not base:
        return None
    q = Story.query
    if exclude_id is not None:
        q = q.filter(Story.id != exclude_id)
    used = {st.public_slug for st in q.all()}
    candidate = base
    n = 2
    while candidate in used:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _unique_blog_slug(base_slug, *, exclude_id=None):
    """Same uniqueness sweep as ``_unique_post_slug``, scoped to
    BlogPost so the public ``/blog/<slug>`` route can rely on each
    row owning its URL."""
    base = _normalize_slug(base_slug)
    if not base:
        return None
    q = BlogPost.query
    if exclude_id is not None:
        q = q.filter(BlogPost.id != exclude_id)
    used = {bp.public_slug for bp in q.all()}
    candidate = base
    n = 2
    while candidate in used:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _unique_blog_taxonomy_slug(model, base_slug, *, exclude_id=None):
    """Slug uniqueness sweep for BlogCategory / BlogTag. Each taxonomy
    has a unique ``slug`` column with its own URL surface, so we
    auto-disambiguate by appending ``-2``, ``-3``, ... until free."""
    base = _normalize_slug(base_slug)
    if not base:
        return None
    q = model.query
    if exclude_id is not None:
        q = q.filter(model.id != exclude_id)
    used = {row.slug for row in q.all() if row.slug}
    candidate = base
    n = 2
    while candidate in used:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _parse_date_only(value):
    """Parse a yyyy-mm-dd from the HTML5 date input. Returns None on
    empty / invalid input."""
    if not value:
        return None
    s = (value or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _apply_meeting_form(m, form, schedules, files=None):
    # Capture the previous effective slug *before* mutating name/slug so
    # the history row can record the URL the public site used to serve.
    _prev_public_slug = m.public_slug if m.id else None

    m.name = form["name"].strip()
    m.description = form.get("description", "").strip()
    m.alert_message = form.get("alert_message", "").strip() or None
    m.public_alert_message = form.get("public_alert_message", "").strip() or None

    # Slug edits are gated to admins + frontend editors. Non-editors'
    # form submissions can't change the slug, even by hand-crafting a
    # POST — we silently ignore the field for them.
    if current_user.is_authenticated and current_user.can_edit_frontend():
        m.slug = _normalize_slug(form.get("slug"))
    mtype = form.get("meeting_type", "in_person")
    if mtype not in MEETING_TYPES:
        mtype = "in_person"
    m.meeting_type = mtype
    m.show_otp = form.get("show_otp") == "1"
    loc_choice = form.get("location_choice", "").strip()
    custom = form.get("location_custom", "").strip()
    if loc_choice == "__custom__":
        m.location = custom
    elif loc_choice:
        m.location = loc_choice
    else:
        m.location = custom  # fallback
    m.location_notes = form.get("location_notes", "").strip() or None
    # Extended-content blocks — toggle + per-block title/body fields.
    # Walk `ext_block_present` markers in submission order so the JS-
    # added cards persist in the order the admin arranged them.
    m.extended_content_enabled = form.get("extended_content_enabled") == "1"
    ext_blocks = []
    for raw_idx in form.getlist("ext_block_present"):
        try:
            i = int(raw_idx)
        except (TypeError, ValueError):
            continue
        title = (form.get(f"ext_block_{i}_title") or "").strip()
        body = (form.get(f"ext_block_{i}_body") or "").strip()
        if not (title or body):
            continue
        ext_blocks.append({"title": title[:200], "body": body[:20000]})
    if ext_blocks:
        import json as _json_ext
        m.extended_blocks_json = _json_ext.dumps(ext_blocks)
    else:
        m.extended_blocks_json = None
    if mtype == "in_person":
        m.zoom_meeting_id = ""
        m.zoom_passcode = ""
        m.zoom_opens_time = ""
        m.zoom_link = ""
        m.zoom_account_id = None
    else:
        m.zoom_meeting_id = form.get("zoom_meeting_id", "").strip()
        m.zoom_passcode = form.get("zoom_passcode", "").strip()
        m.zoom_opens_time = form.get("zoom_opens_time", "").strip()
        m.zoom_link = form.get("zoom_link", "").strip()
        acct_raw = form.get("zoom_account_id", "")
        m.zoom_account_id = int(acct_raw) if acct_raw else None
    if files is not None:
        uploaded = files.get("logo")
        if uploaded and uploaded.filename:
            if m.logo_filename:
                _delete_upload(m.logo_filename)
            m.logo_filename, _ = _save_upload(uploaded)
    if form.get("remove_logo") == "1" and m.logo_filename:
        _delete_upload(m.logo_filename)
        m.logo_filename = None
    # Replace schedules
    for s in list(m.schedules):
        db.session.delete(s)
    for e in schedules:
        db.session.add(MeetingSchedule(
            meeting=m, day_of_week=e["day"], start_time=e["start_time"],
            duration_minutes=e["duration"], opens_time=e.get("opens_time"),
            zoom_account_id=e["zoom_account_id"]))

    # Slug-change history. Only meaningful for existing meetings — new
    # ones have no "previous URL" to redirect from. Captures any change
    # to the effective public slug, whether it came from the explicit
    # ``slug`` field flipping or from the meeting being renamed (which
    # changes the auto-derived slug).
    if _prev_public_slug and _prev_public_slug != m.public_slug:
        _record_slug_change("meeting", m.id, _prev_public_slug, m.public_slug)


@bp.route("/meetings/new", methods=["POST"])
@meeting_admin_required
def meeting_new():
    schedules, err = _parse_schedule_form(request.form)
    if err:
        flash(err, "danger")
        return redirect(url_for("main.meetings"))
    m = Meeting(name=request.form["name"].strip())
    _apply_meeting_form(m, request.form, schedules, request.files)
    db.session.add(m)
    db.session.commit()
    from . import activity
    activity.log("meeting.create", entity_type="meeting", entity_id=m.id,
                 summary=f"Created meeting “{m.name}”")
    flash("Meeting created", "success")
    return redirect(url_for("main.meeting_detail", slug=m.public_slug))


def _resolve_meeting_by_slug(slug):
    """Return the Meeting whose ``public_slug`` matches ``slug``, or
    ``None``. Mirrors ``_resolve_library_by_slug`` — case-insensitive
    on the URL side; first match wins on the rare collision."""
    target = (slug or "").lower()
    if not target:
        return None
    rows = Meeting.query.all()
    return next((m for m in rows if m.public_slug == target), None)


@bp.route("/meetings/<slug>")
@login_required
def meeting_detail(slug):
    m = _resolve_meeting_by_slug(slug) or abort(404)
    all_libraries = Library.query.order_by(Library.name).all()
    zoom_accounts = ZoomAccount.query.order_by(ZoomAccount.name).all()
    locations = Location.query.order_by(Location.name).all()
    zoom_password = decrypt(m.zoom_account.password_enc) if m.zoom_account else ""
    otp_email = ZoomOtpEmail.query.first()
    return render_template("meeting_detail.html", meeting=m,
                           all_libraries=all_libraries, zoom_accounts=zoom_accounts,
                           locations=locations, zoom_account_password=zoom_password,
                           otp_email=otp_email)


@bp.route("/meetings/<int:mid>")
@login_required
def meeting_detail_legacy(mid):
    """Legacy id-based URL — 301 to the slug equivalent so external
    bookmarks survive the rename."""
    m = db.session.get(Meeting, mid) or abort(404)
    return redirect(url_for("main.meeting_detail", slug=m.public_slug), code=301)


@bp.route("/meetings/<slug>/edit", methods=["POST"])
@editor_required
def meeting_edit(slug):
    m = _resolve_meeting_by_slug(slug) or abort(404)
    schedules, err = _parse_schedule_form(request.form, meeting_id=m.id)
    if err:
        flash(err, "danger")
        return redirect(_safe_referrer() or url_for("main.meeting_detail", slug=m.public_slug))
    _apply_meeting_form(m, request.form, schedules, request.files)
    if "library_ids" in request.form:
        _apply_library_selections(m, request.form)
    db.session.commit()
    from . import activity
    activity.log("meeting.update", entity_type="meeting", entity_id=m.id,
                 summary=f"Updated meeting “{m.name}”")
    flash("Meeting updated", "success")
    return redirect(url_for("main.meeting_detail", slug=m.public_slug))


@bp.route("/meetings/<int:mid>.json")
@login_required
def meeting_json(mid):
    """Asset endpoint — kept on the int:mid form because callers are
    JS fetches that already have the meeting id in hand."""
    m = db.session.get(Meeting, mid) or abort(404)
    return jsonify({
        "id": m.id, "name": m.name, "description": m.description or "",
        "location": m.location or "",
        "zoom_meeting_id": m.zoom_meeting_id or "",
        "zoom_passcode": m.zoom_passcode or "",
        "zoom_opens_time": m.zoom_opens_time or "",
        "schedules": [{"day": s.day_of_week, "start_time": s.start_time,
                       "duration": s.duration_minutes,
                       "zoom_account_id": s.zoom_account_id} for s in m.schedules],
    })


@bp.route("/meetings/<slug>/delete", methods=["POST"])
@meeting_admin_required
def meeting_delete(slug):
    m = _resolve_meeting_by_slug(slug) or abort(404)
    from . import activity
    activity.log("meeting.delete", entity_type="meeting", entity_id=m.id,
                 summary=f"Deleted meeting “{m.name}”")
    db.session.delete(m)
    db.session.commit()
    flash("Meeting deleted", "success")
    return redirect(url_for("main.meetings"))


@bp.route("/meetings/<slug>/archive", methods=["POST"])
@admin_required
def meeting_archive(slug):
    from datetime import datetime
    m = _resolve_meeting_by_slug(slug) or abort(404)
    m.archived_at = datetime.utcnow()
    db.session.commit()
    flash(f"Archived “{m.name}”", "success")
    return redirect(url_for("main.meetings"))


@bp.route("/meetings/<slug>/unarchive", methods=["POST"])
@admin_required
def meeting_unarchive(slug):
    m = _resolve_meeting_by_slug(slug) or abort(404)
    m.archived_at = None
    db.session.commit()
    flash(f"Restored “{m.name}”", "success")
    return redirect(url_for("main.meetings", show="archived"))


@bp.route("/meetings/<slug>/libraries", methods=["POST"])
@editor_required
def meeting_libraries(slug):
    m = _resolve_meeting_by_slug(slug) or abort(404)
    ids = request.form.getlist("library_ids", type=int)
    m.libraries = Library.query.filter(Library.id.in_(ids)).all() if ids else []
    db.session.commit()
    flash("Libraries updated for meeting", "success")
    return redirect(url_for("main.meeting_detail", slug=m.public_slug))


# --- Locations ---

def _location_address_payload():
    """Pull street/city/state/zip from the request form, sync the
    legacy `address` column from those parts so callers reading the
    single-string field stay correct, and return the dict that
    `Location` columns can be **-spread into."""
    street = (request.form.get("street") or "").strip() or None
    city   = (request.form.get("city") or "").strip() or None
    state  = (request.form.get("state") or "").strip() or None
    zipc   = (request.form.get("zip_code") or "").strip() or None
    csz_parts = [p for p in [city, " ".join(p for p in [state, zipc] if p) or None] if p]
    csz_line = ", ".join(p for p in [city, " ".join(p for p in [state, zipc] if p)] if p) \
               if (city or state or zipc) else ""
    address_lines = [p for p in [street, csz_line] if p]
    address = "\n".join(address_lines) if address_lines else None
    # Legacy single-line fallback — admins authoring with the old form
    # may still post `address` directly; honour it when none of the
    # split fields are filled in.
    if not address and (request.form.get("address") or "").strip():
        address = request.form.get("address").strip()
    return {"street": street, "city": city, "state": state, "zip_code": zipc,
            "address": address}


def _can_edit_locations():
    """Locations gate — admins always; frontend editors too once the
    capability is granted (admin-only today, semantically aligned
    with footer editing). Centralised so the listing route, the
    create/edit/delete handlers, and any future API all use the same
    rule."""
    return current_user.is_admin() or current_user.can_edit_frontend()


@bp.route("/locations")
@login_required
def locations():
    if not _can_edit_locations():
        flash("You don't have permission to manage Meeting Locations.", "danger")
        return redirect(url_for("main.index"))
    from .models import IntergroupOfficer, Fellowship
    items = Location.query.order_by(Location.name).all()
    officers = (IntergroupOfficer.query
                .order_by(IntergroupOfficer.sort_order, IntergroupOfficer.id)
                .all())
    fellowships = (Fellowship.query
                   .order_by(Fellowship.sort_order, Fellowship.id)
                   .all())
    return render_template("locations.html", locations=items, officers=officers,
                           fellowships=fellowships)


@bp.route("/officers/save", methods=["POST"])
@login_required
def officers_save():
    """Save the repeatable Intergroup officers table from Settings →
    Global. Mirrors the form-array pattern used by /intergroupemail/edit:
    arrays of ids / roles / names / phones / emails, one slot per row.
    Empty rows are dropped. Existing rows whose ids aren't in the
    submission are deleted, so unchecking-by-removal works.
    """
    if not _can_edit_locations():
        flash("You don't have permission to manage Intergroup officers.", "danger")
        return redirect(url_for("main.index"))
    from .models import IntergroupOfficer
    ids = request.form.getlist("officer_id")
    roles = request.form.getlist("officer_role")
    names = request.form.getlist("officer_name")
    phones = request.form.getlist("officer_phone")
    emails = request.form.getlist("officer_email")
    existing = {o.id: o for o in IntergroupOfficer.query.all()}
    seen = set()
    for pos, (oid, role, name, phone, email) in enumerate(
        zip(ids, roles, names, phones, emails)
    ):
        role = (role or "").strip()
        name = (name or "").strip()
        phone = (phone or "").strip()
        email = (email or "").strip()
        # Drop rows where every cell is blank — they're empty placeholder
        # rows the admin opened with "+ Add officer" but never filled in.
        if not role and not name and not phone and not email:
            continue
        if oid and oid.isdigit() and int(oid) in existing:
            o = existing[int(oid)]
            o.role = role
            o.name = name or None
            o.phone = phone or None
            o.email = email or None
            o.sort_order = pos
            seen.add(o.id)
        else:
            db.session.add(IntergroupOfficer(
                role=role,
                name=name or None,
                phone=phone or None,
                email=email or None,
                sort_order=pos,
            ))
    for oid, o in existing.items():
        if oid not in seen:
            db.session.delete(o)
    db.session.commit()
    flash("Intergroup officers updated", "success")
    return redirect(url_for("main.locations",
                            **({"embed": "1"} if request.values.get("embed") == "1" else {})))


@bp.route("/fellowships/save", methods=["POST"])
@login_required
def fellowships_save():
    """Save the repeatable Fellowships Index table from Settings →
    Global. Same form-array reconciliation pattern as officers_save:
    parallel ``fellowship_*`` arrays, one slot per row. Empty rows
    (no name) are dropped. Existing rows whose ids aren't in the
    submission are deleted, so unchecking-by-row-removal works.

    Each row submits exactly one ``fellowship_is_virtual`` value
    ("0" or "1") via a hidden input that the per-row JS keeps in
    lockstep with the visible Virtual toggle. That contract is what
    keeps the parallel arrays aligned — a missing or doubled-up
    submission would shift every subsequent row's virtual flag, so
    the template must always render the hidden input alongside the
    checkbox. Virtual rows have their country + state_region wiped
    at save time so a future toggle back to regional starts clean.
    """
    if not _can_edit_locations():
        flash("You don't have permission to manage the Fellowships Index.", "danger")
        return redirect(url_for("main.index"))
    from .models import Fellowship
    ids       = request.form.getlist("fellowship_id")
    names     = request.form.getlist("fellowship_name")
    countries = request.form.getlist("fellowship_country")
    regions   = request.form.getlist("fellowship_state_region")
    urls      = request.form.getlist("fellowship_url")
    raw_virtual = request.form.getlist("fellowship_is_virtual")
    virtuals = [v == "1" for v in raw_virtual]
    existing = {f.id: f for f in Fellowship.query.all()}
    seen = set()
    rows = list(zip(ids, names, virtuals, countries, regions, urls))
    for pos, (fid, name, is_virtual, country, region, url) in enumerate(rows):
        name = (name or "").strip()
        if not name:
            # Blank rows are placeholders the admin opened with
            # +Add but never filled in. Drop them silently.
            continue
        country = (country or "").strip()
        region = (region or "").strip()
        url = (url or "").strip()
        if is_virtual:
            country = ""
            region = ""
        if fid and fid.isdigit() and int(fid) in existing:
            f = existing[int(fid)]
            f.name = name
            f.is_virtual = bool(is_virtual)
            f.country = country or None
            f.state_region = region or None
            f.url = url or None
            f.sort_order = pos
            seen.add(f.id)
        else:
            db.session.add(Fellowship(
                name=name,
                is_virtual=bool(is_virtual),
                country=country or None,
                state_region=region or None,
                url=url or None,
                sort_order=pos,
            ))
    for fid, f in existing.items():
        if fid not in seen:
            db.session.delete(f)
    db.session.commit()
    flash("Fellowships Index updated", "success")
    return redirect(url_for("main.locations",
                            **({"embed": "1"} if request.values.get("embed") == "1" else {})))


@bp.route("/locations/new", methods=["POST"])
@login_required
def location_new():
    if not _can_edit_locations():
        flash("You don't have permission to manage Meeting Locations.", "danger")
        return redirect(url_for("main.index"))
    name = request.form["name"].strip()
    ltype = request.form.get("location_type", "in_person")
    if ltype not in ("in_person", "online"):
        ltype = "in_person"
    payload = _location_address_payload()
    maps_url    = request.form.get("maps_url", "").strip() or None
    website_url = request.form.get("website_url", "").strip() or None
    notes       = request.form.get("notes", "").strip() or None
    if ltype == "online":
        payload = {"street": None, "city": None, "state": None, "zip_code": None, "address": None}
        maps_url = None
    if not name:
        flash("Name required", "danger")
    elif Location.query.filter_by(name=name).first():
        flash("Location already exists", "danger")
    else:
        db.session.add(Location(name=name, location_type=ltype,
                                maps_url=maps_url, website_url=website_url,
                                notes=notes, **payload))
        db.session.commit()
        flash("Location added", "success")
    return redirect(url_for("main.locations", **({"embed": "1"} if request.values.get("embed") == "1" else {})))


@bp.route("/locations/<int:lid>/edit", methods=["POST"])
@login_required
def location_edit(lid):
    if not _can_edit_locations():
        flash("You don't have permission to manage Meeting Locations.", "danger")
        return redirect(url_for("main.index"))
    loc = db.session.get(Location, lid) or abort(404)
    loc.name = request.form["name"].strip()
    ltype = request.form.get("location_type", "in_person")
    if ltype not in ("in_person", "online"):
        ltype = "in_person"
    loc.location_type = ltype
    # Notes + website URL apply to both in-person and online locations.
    loc.notes       = request.form.get("notes", "").strip() or None
    loc.website_url = request.form.get("website_url", "").strip() or None
    if ltype == "online":
        loc.street = loc.city = loc.state = loc.zip_code = None
        loc.address = None
        loc.maps_url = None
    else:
        payload = _location_address_payload()
        loc.street    = payload["street"]
        loc.city      = payload["city"]
        loc.state     = payload["state"]
        loc.zip_code  = payload["zip_code"]
        loc.address   = payload["address"]
        loc.maps_url  = request.form.get("maps_url", "").strip() or None
    db.session.commit()
    flash("Location updated", "success")
    return redirect(url_for("main.locations", **({"embed": "1"} if request.values.get("embed") == "1" else {})))


@bp.route("/locations/<int:lid>/delete", methods=["POST"])
@login_required
def location_delete(lid):
    if not _can_edit_locations():
        flash("You don't have permission to manage Meeting Locations.", "danger")
        return redirect(url_for("main.index"))
    loc = db.session.get(Location, lid) or abort(404)
    db.session.delete(loc)
    db.session.commit()
    flash("Location deleted", "success")
    return redirect(url_for("main.locations", **({"embed": "1"} if request.values.get("embed") == "1" else {})))


# --- Custom Nav Links ---

def _navlinks_redirect():
    """Redirect after a nav-link CRUD operation. The modal-driven flow
    in the Settings → Sidebar tab posts from any page, so prefer the
    referrer over the standalone /nav-links page (which is no longer
    surfaced in the UI). Falls back to /nav-links for backward compat
    if request.referrer isn't set."""
    if request.values.get("embed") == "1":
        return redirect(url_for("main.nav_links", embed="1"))
    return redirect(_safe_referrer() or url_for("main.nav_links"))


@bp.route("/nav-links")
@login_required
def nav_links():
    if not current_user.is_admin():
        flash("Admins only", "danger")
        return redirect(url_for("main.index"))
    items = NavLink.query.order_by(NavLink.position, NavLink.id).all()
    return render_template("nav_links.html", nav_links=items)


@bp.route("/nav-links/new", methods=["POST"])
@admin_required
def nav_link_new():
    title = (request.form.get("title") or "").strip()
    url = (request.form.get("url") or "").strip()
    if not title or not url:
        flash("Title and URL required", "danger")
    else:
        pos = (db.session.query(db.func.coalesce(db.func.max(NavLink.position), -1)).scalar() or -1) + 1
        db.session.add(NavLink(title=title[:100], url=url[:1000], position=pos))
        db.session.commit()
        flash("Navigation link added", "success")
    return _navlinks_redirect()


@bp.route("/nav-links/<int:nid>/edit", methods=["POST"])
@admin_required
def nav_link_edit(nid):
    n = db.session.get(NavLink, nid) or abort(404)
    title = (request.form.get("title") or "").strip()
    url = (request.form.get("url") or "").strip()
    if not title or not url:
        flash("Title and URL required", "danger")
    else:
        n.title = title[:100]
        n.url = url[:1000]
        db.session.commit()
        flash("Navigation link updated", "success")
    return _navlinks_redirect()


@bp.route("/nav-links/reorder", methods=["POST"])
@admin_required
def nav_link_reorder():
    data = request.get_json(silent=True) or {}
    order = data.get("order") or []
    for pos, nid in enumerate(order):
        try:
            nid = int(nid)
        except (TypeError, ValueError):
            continue
        n = db.session.get(NavLink, nid)
        if n:
            n.position = pos
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/nav-links/<int:nid>/delete", methods=["POST"])
@admin_required
def nav_link_delete(nid):
    n = db.session.get(NavLink, nid) or abort(404)
    db.session.delete(n)
    db.session.commit()
    flash("Navigation link deleted", "success")
    return _navlinks_redirect()


@bp.route("/meetings/<int:mid>/logo")
@login_required
def meeting_logo(mid):
    m = db.session.get(Meeting, mid) or abort(404)
    if not m.logo_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], m.logo_filename)


# --- Zoom Accounts ---

@bp.route("/zoom-accounts")
@login_required
def zoom_accounts():
    accounts = ZoomAccount.query.order_by(ZoomAccount.name).all()
    schedules = (MeetingSchedule.query
                 .filter(MeetingSchedule.zoom_account_id.isnot(None))
                 .all())
    # Build calendar grid: rows = hours 6..23, cols = days
    calendar = {a.id: {d: [] for d in range(7)} for a in accounts}
    for s in schedules:
        if s.zoom_account_id in calendar:
            calendar[s.zoom_account_id][s.day_of_week].append(s)
    conflict_ids = set()
    for acct_id, by_day in calendar.items():
        for day, slots in by_day.items():
            for i in range(len(slots)):
                for j in range(i + 1, len(slots)):
                    a, b = slots[i], slots[j]
                    if a.start_minutes() < b.end_minutes() and b.start_minutes() < a.end_minutes():
                        conflict_ids.add(a.id)
                        conflict_ids.add(b.id)
    # Display order: Sunday first, then Monday..Saturday
    day_order = [6, 0, 1, 2, 3, 4, 5]
    otp = _get_otp_email()
    return render_template("zoom_accounts.html", accounts=accounts,
                           calendar=calendar, schedules=schedules,
                           conflict_ids=conflict_ids, day_order=day_order,
                           otp=otp, decrypt=decrypt)


@bp.route("/zoom-accounts/new", methods=["POST"])
@admin_required
def zoom_account_new():
    name = request.form["name"].strip()
    if ZoomAccount.query.filter_by(name=name).first():
        flash("A Zoom account with that name already exists", "danger")
        return redirect(url_for("main.zoom_accounts", **({"embed": "1"} if request.values.get("embed") == "1" else {})))
    acct = ZoomAccount(
        name=name,
        username=request.form["username"].strip(),
        password_enc=encrypt(request.form.get("password", "")),
        notes=request.form.get("notes", "").strip(),
    )
    db.session.add(acct)
    db.session.commit()
    flash("Zoom account created", "success")
    return redirect(url_for("main.zoom_accounts", **({"embed": "1"} if request.values.get("embed") == "1" else {})))


@bp.route("/zoom-accounts/<int:aid>/edit", methods=["POST"])
@admin_required
def zoom_account_edit(aid):
    acct = db.session.get(ZoomAccount, aid) or abort(404)
    acct.name = request.form["name"].strip()
    acct.username = request.form["username"].strip()
    pw = request.form.get("password", "")
    if pw:
        acct.password_enc = encrypt(pw)
    acct.notes = request.form.get("notes", "").strip()
    db.session.commit()
    flash("Zoom account updated", "success")
    return redirect(url_for("main.zoom_accounts", **({"embed": "1"} if request.values.get("embed") == "1" else {})))


@bp.route("/zoom-accounts/<int:aid>/delete", methods=["POST"])
@admin_required
def zoom_account_delete(aid):
    acct = db.session.get(ZoomAccount, aid) or abort(404)
    db.session.delete(acct)
    db.session.commit()
    flash("Zoom account deleted", "success")
    return redirect(url_for("main.zoom_accounts", **({"embed": "1"} if request.values.get("embed") == "1" else {})))


@bp.route("/zoom-accounts/<int:aid>/reveal")
@login_required
def zoom_account_reveal(aid):
    acct = db.session.get(ZoomAccount, aid) or abort(404)
    return jsonify({"username": acct.username, "password": decrypt(acct.password_enc)})


@bp.route("/otp-email")
@login_required
def otp_email_view():
    if not current_user.is_admin():
        flash("Admins only", "danger")
        return redirect(url_for("main.index"))
    otp = _get_otp_email()
    return render_template("otp_email.html", otp=otp)


@bp.route("/otp-email", methods=["POST"])
@admin_required
def otp_email_save():
    otp = _get_otp_email()
    otp.email = request.form.get("email", "").strip() or None
    otp.login_url = request.form.get("login_url", "").strip() or None
    pw = request.form.get("password", "")
    if pw:
        otp.password_enc = encrypt(pw)
    if request.form.get("clear_password") == "1":
        otp.password_enc = None
    db.session.commit()
    flash("OTP email settings updated", "success")
    return redirect(url_for("main.zoom_accounts",
                            **({"embed": "1"} if request.values.get("embed") == "1" else {})))


@bp.route("/otp-email/reveal")
@login_required
def otp_email_reveal():
    otp = _get_otp_email()
    if not otp.password_enc:
        return jsonify({"password": ""})
    return jsonify({"password": decrypt(otp.password_enc)})


# --- Site branding ---

@bp.route("/site-branding", methods=["POST"])
@admin_required
def site_branding_save():
    s = _get_site_setting()
    url = (request.form.get("footer_logo_url") or "").strip()
    s.footer_logo_url = url or None
    w = (request.form.get("footer_logo_width") or "").strip()
    s.footer_logo_width = int(w) if w.isdigit() and 16 <= int(w) <= 150 else None
    if request.form.get("clear_logo") == "1":
        old = s.footer_logo_filename
        s.footer_logo_filename = None
        _cleanup_retired_asset(old)
    uploaded = request.files.get("footer_logo")
    if uploaded and uploaded.filename:
        old = s.footer_logo_filename
        stored, _original = _save_upload(uploaded)
        s.footer_logo_filename = stored
        if old and old != stored:
            _cleanup_retired_asset(old)
    db.session.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        logo_src = (url_for("public.site_footer_logo") + f"?v={int(time.time())}") if s.footer_logo_filename else ""
        return jsonify(
            ok=True,
            has_custom_logo=bool(s.footer_logo_filename),
            footer_logo_src=logo_src,
            footer_logo_link=s.footer_logo_url or "",
            footer_logo_width=s.footer_logo_width or 32,
        )
    flash("Branding updated", "success")
    return redirect(_safe_referrer() or url_for("main.index"))


@bp.route("/site-url", methods=["POST"])
@admin_required
def site_url_save():
    """Persist the canonical public URL used by outbound messages
    (welcome emails, access-request notifications, etc.). Stored
    without a trailing slash. Saving an empty string clears the
    override and falls back to the request's Host header."""
    s = _get_site_setting()
    raw = (request.form.get("site_url") or "").strip()
    if raw:
        # Tolerate users pasting "example.com" without a scheme — assume
        # https since http portals would just redirect anyway.
        if not raw.lower().startswith(("http://", "https://")):
            raw = "https://" + raw
        raw = raw.rstrip("/")
    s.site_url = raw or None
    db.session.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True, site_url=s.site_url or "")
    flash("Site URL saved", "success")
    return redirect(_safe_referrer() or url_for("main.index"))


def _public_url_for(endpoint, **values):
    """Build an absolute URL using the admin-configured site_url when
    set, falling back to Flask's request-context external URL builder
    when no override is present. Used by outbound emails so links
    don't surface internal IPs / Docker hostnames."""
    s = _get_site_setting()
    base = (getattr(s, "site_url", None) or "").rstrip("/")
    if base:
        # Build the path against an arbitrary external host first so
        # url_for emits the full path including the application root,
        # then splice in the configured host. The request's base URL is
        # discarded.
        path = url_for(endpoint, **values)
        return base + path
    return url_for(endpoint, _external=True, **values)


@bp.route("/intergroupemail")
@login_required
def intergroup():
    s = _get_site_setting()
    if not s.intergroup_enabled:
        abort(404)
    # The Email Accounts page is hard-gated to admins + intergroup_members
    # regardless of the per-module role setting on the Modules tab.
    # Surfacing 404 (rather than redirecting) keeps the page's existence
    # opaque to other roles, matching the abort-404 pattern used by
    # `_require_module_role` for module-disabled state.
    if not current_user.can_edit_intergroup_libraries():
        abort(404)
    _seed_intergroup_defaults(s)
    accounts = IntergroupAccount.query.order_by(IntergroupAccount.position,
                                                IntergroupAccount.id).all()
    return render_template("intergroup.html", site=s, accounts=accounts)


@bp.route("/intergroupemail/edit", methods=["GET", "POST"])
@admin_required
def intergroup_edit():
    s = _get_site_setting()
    _seed_intergroup_defaults(s)
    if request.method == "POST":
        s.ig_intro = request.form.get("ig_intro", "").strip() or None
        s.ig_webmail_url = request.form.get("ig_webmail_url", "").strip() or None
        s.ig_incoming_host = request.form.get("ig_incoming_host", "").strip() or None
        s.ig_incoming_port = request.form.get("ig_incoming_port", "").strip() or None
        s.ig_outgoing_host = request.form.get("ig_outgoing_host", "").strip() or None
        s.ig_outgoing_port = request.form.get("ig_outgoing_port", "").strip() or None
        s.ig_setup_notes = request.form.get("ig_setup_notes", "").strip() or None
        s.ig_learn_more_url = request.form.get("ig_learn_more_url", "").strip() or None
        s.ig_page_title = request.form.get("ig_page_title", "").strip() or None

        ids = request.form.getlist("account_id")
        roles = request.form.getlist("account_role")
        emails = request.form.getlist("account_email")
        existing = {a.id: a for a in IntergroupAccount.query.all()}
        seen = set()
        for pos, (aid, role, email) in enumerate(zip(ids, roles, emails)):
            role = (role or "").strip()
            email = (email or "").strip()
            if not role and not email:
                continue
            if aid and aid.isdigit() and int(aid) in existing:
                a = existing[int(aid)]
                a.role = role; a.email = email; a.position = pos
                seen.add(a.id)
            else:
                db.session.add(IntergroupAccount(role=role, email=email, position=pos))
        for aid, a in existing.items():
            if aid not in seen:
                db.session.delete(a)
        db.session.commit()
        flash("Intergroup page updated", "success")
        return redirect(url_for("main.intergroup"))

    return redirect(url_for("main.intergroup"))


@bp.route("/zoom-tech")
@login_required
def zoom_tech():
    import json
    s = _get_site_setting()
    if not s.zoom_tech_enabled:
        abort(404)
    _require_module_role("zoom_tech_required_role")
    sections = []
    if s.zoom_tech_blocks_json:
        try:
            sections = json.loads(s.zoom_tech_blocks_json)
        except (ValueError, TypeError):
            sections = []
    return render_template("zoom_tech.html", site=s, sections=sections,
                           blocks_json=s.zoom_tech_blocks_json or "[]")


@bp.route("/zoom-tech/save", methods=["POST"])
@admin_required
def zoom_tech_save():
    import json
    s = _get_site_setting()
    s.zoom_tech_title = request.form.get("zoom_tech_title", "").strip() or None
    tmpl = request.form.get("zoom_tech_template", "standard").strip()
    s.zoom_tech_template = tmpl if tmpl in ("standard", "wiki") else "standard"
    blocks_json = request.form.get("blocks_json", "").strip()
    if blocks_json:
        try:
            json.loads(blocks_json)
            s.zoom_tech_blocks_json = blocks_json
        except (ValueError, TypeError):
            flash("Invalid blocks JSON", "danger")
            return redirect(url_for("main.zoom_tech"))
    db.session.commit()
    flash("Zoom Tech page updated", "success")
    return redirect(url_for("main.zoom_tech"))


@bp.route("/settings/zoom-tech-toggle", methods=["POST"])
@admin_required
def zoom_tech_toggle():
    s = _get_site_setting()
    s.zoom_tech_enabled = request.form.get("zoom_tech_enabled") == "1"
    db.session.commit()
    flash("Zoom Tech page " + ("enabled" if s.zoom_tech_enabled else "disabled"), "success")
    return redirect(_safe_referrer() or url_for("main.index"))


@bp.route("/settings/sidebar-save", methods=["POST"])
@admin_required
def sidebar_save():
    """Persist sidebar mode + manual order. Mode validates against the
    known set; manual JSON is parsed and only known keys are kept so a
    handcrafted POST can't poison the sidebar with stray entries."""
    import json as _json
    from .sidebar import _MAIN_CATALOG, _ADMIN_CATALOG  # noqa: WPS437
    s = _get_site_setting()
    mode = (request.form.get("sidebar_sort_mode") or "").strip()
    if mode not in {"auto-asc", "auto-desc", "manual"}:
        mode = "auto-asc"
    s.sidebar_sort_mode = mode

    if mode == "manual":
        raw = request.form.get("sidebar_order_json") or ""
        try:
            payload = _json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            payload = {}
        from .sidebar import PINNED_KEYS as _PINNED  # noqa: WPS437
        valid_section_keys = {"main", "intergroup", "external", "admin"}
        # Pinned keys (Dashboard) are excluded from validation so they
        # can't be saved into the manual order — they're always rendered
        # first by the helper regardless of stored JSON.
        valid_main = {it["key"] for it in _MAIN_CATALOG if it["key"] not in _PINNED}
        valid_admin = {it["key"] for it in _ADMIN_CATALOG if it["key"] not in _PINNED}
        # Intergroup keys are *dynamic* — the section's content includes
        # ``ig_email`` plus one ``ig_lib_<id>`` per Intergroup-flagged
        # library. Resolve the valid set from the live reorder catalog
        # so admin-added libraries don't get stripped out at save time.
        from .sidebar import admin_reorder_catalog  # noqa: WPS437
        valid_intergroup = {it["key"] for it
                            in admin_reorder_catalog(s).get("intergroup", [])}
        clean = {}
        sec = payload.get("sections")
        if isinstance(sec, list):
            clean["sections"] = [k for k in sec if isinstance(k, str) and k in valid_section_keys]
        m = payload.get("main")
        if isinstance(m, list):
            clean["main"] = [k for k in m if isinstance(k, str) and k in valid_main]
        ig = payload.get("intergroup")
        if isinstance(ig, list):
            clean["intergroup"] = [k for k in ig if isinstance(k, str) and k in valid_intergroup]
        a = payload.get("admin")
        if isinstance(a, list):
            clean["admin"] = [k for k in a if isinstance(k, str) and k in valid_admin]
        s.sidebar_order_json = _json.dumps(clean) if clean else None
    db.session.commit()
    flash("Sidebar order saved", "success")
    return redirect(_safe_referrer() or url_for("main.index"))


@bp.route("/_sidebar/nav")
@login_required
def sidebar_nav_fragment():
    """Return the rendered inner-HTML of the sidebar nav. Used by the
    live-refresh JS so the sidebar reflects role / toggle / order
    changes immediately without a full page reload."""
    s = _get_site_setting()
    nav_items = NavLink.query.order_by(NavLink.position, NavLink.id).all()
    pending = AccessRequest.query.filter_by(status="pending", is_archived=False).count()
    return render_template("_sidebar_nav.html",
                           site=s, nav_links=nav_items,
                           pending_access_count=pending)


@bp.route("/_sidebar/order-manual")
@admin_required
def sidebar_order_manual_fragment():
    """Inner HTML of the Settings → Sidebar tab's manual drag-drop
    section. Used by the live-refresh JS so the manual reorder list
    mirrors the dynamic Main/Admin section placement of module-gated
    items immediately after a role change, without a page reload."""
    s = _get_site_setting()
    nav_items = NavLink.query.order_by(NavLink.position, NavLink.id).all()
    return render_template("_sidebar_order_manual.html",
                           site=s, nav_links=nav_items)


@bp.route("/settings/module-role-save", methods=["POST"])
@admin_required
def module_role_save():
    """Update a single module's required-role gate. Form posts a hidden
    ``module`` key that maps to one of the four supported columns; only
    pre-validated keys are accepted so a handcrafted POST can't toggle
    arbitrary settings."""
    from .permissions import ROLE_TIER_KEYS
    s = _get_site_setting()
    module = (request.form.get("module") or "").strip()
    role = (request.form.get("required_role") or "").strip().lower()
    columns = {
        "intergroup":        "intergroup_required_role",
        "intergroup_module": "intergroup_module_required_role",
        "zoom_tech":         "zoom_tech_required_role",
        "posts":             "posts_required_role",
        "stories":           "stories_required_role",
        "blog":              "blog_required_role",
        "frontend_module":   "frontend_module_required_role",
    }
    col = columns.get(module)
    if col and role in ROLE_TIER_KEYS:
        setattr(s, col, role)
        db.session.commit()
        flash("Module access saved", "success")
    return redirect(_safe_referrer() or url_for("main.index"))


@bp.route("/settings/posts-toggle", methods=["POST"])
@admin_required
def posts_toggle():
    s = _get_site_setting()
    s.posts_enabled = request.form.get("posts_enabled") == "1"
    db.session.commit()
    flash("Announcements & Events " + ("enabled" if s.posts_enabled else "disabled"), "success")
    return redirect(_safe_referrer() or url_for("main.index"))


def _require_posts_enabled():
    """Bail out early when the module is disabled or the current user's
    role isn't allowed by the admin's Modules-tab dropdown. The role
    gate replaces the @admin_required decorator on Posts routes — the
    default ``posts_required_role`` is ``admin`` so historic behavior
    holds until an admin loosens it."""
    from .permissions import user_meets_role
    s = _get_site_setting()
    if not s.posts_enabled:
        abort(404)
    if not user_meets_role(current_user, s.posts_required_role or "admin"):
        abort(404)


@bp.route("/settings/stories-toggle", methods=["POST"])
@admin_required
def stories_toggle():
    s = _get_site_setting()
    s.stories_enabled = request.form.get("stories_enabled") == "1"
    db.session.commit()
    flash("Stories " + ("enabled" if s.stories_enabled else "disabled"), "success")
    return redirect(_safe_referrer() or url_for("main.index"))


def _require_stories_enabled():
    """Bail out early when the Stories module is off or the user's role
    doesn't satisfy the admin's required-role dropdown. Mirrors
    ``_require_posts_enabled`` — admin-only by default; an admin can
    loosen it via the Modules tab."""
    from .permissions import user_meets_role
    s = _get_site_setting()
    if not s.stories_enabled:
        abort(404)
    if not user_meets_role(current_user, s.stories_required_role or "admin"):
        abort(404)


@bp.route("/settings/blog-toggle", methods=["POST"])
@admin_required
def blog_toggle():
    s = _get_site_setting()
    s.blog_enabled = request.form.get("blog_enabled") == "1"
    db.session.commit()
    flash("Blog " + ("enabled" if s.blog_enabled else "disabled"), "success")
    return redirect(_safe_referrer() or url_for("main.index"))


def _require_blog_enabled():
    """Module gate for the Blog admin section. Same shape as the Posts
    and Stories gates — admin-only by default; an admin loosens it via
    the Modules tab on the Settings page."""
    from .permissions import user_meets_role
    s = _get_site_setting()
    if not getattr(s, "blog_enabled", False):
        abort(404)
    if not user_meets_role(current_user, getattr(s, "blog_required_role", "admin") or "admin"):
        abort(404)


def _require_module_role(site_attr_role, site_attr_enabled=None):
    """Generic gate: aborts with 404 if the module is disabled or the
    current user's role doesn't satisfy the configured required role."""
    from .permissions import user_meets_role
    s = _get_site_setting()
    if site_attr_enabled and not getattr(s, site_attr_enabled, False):
        abort(404)
    if not user_meets_role(current_user, getattr(s, site_attr_role, None) or "admin"):
        abort(404)


@bp.route("/settings/export")
@admin_required
def data_export():
    import io, json, zipfile, tempfile
    from datetime import datetime
    from flask import send_file
    from sqlalchemy import text

    upload_dir = current_app.config["UPLOAD_FOLDER"]
    data_dir = os.path.dirname(upload_dir.rstrip("/"))
    db_path = os.path.join(data_dir, "tsp.db")

    tmp_db = tempfile.NamedTemporaryFile(prefix="tsp-export-", suffix=".db", delete=False)
    tmp_db.close()
    os.unlink(tmp_db.name)
    with db.engine.connect() as conn:
        conn.exec_driver_sql(f"VACUUM INTO '{tmp_db.name}'")

    tmp_zip = tempfile.NamedTemporaryFile(prefix="tsp-export-", suffix=".zip", delete=False)
    tmp_zip.close()
    manifest = {
        "app": "trusted-servants-pro",
        "format_version": 1,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "db_filename": "tsp.db",
        "uploads_dir": "uploads/",
        "fernet_key_filename": "zoom.key",
        "note": "Restore by importing through the Data tab, or extract into the target's data directory (replacing tsp.db, uploads/, and zoom.key) before first boot. zoom.key is required to decrypt Zoom credentials.",
    }
    zoom_key_path = os.path.join(data_dir, "zoom.key")
    with zipfile.ZipFile(tmp_zip.name, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        z.write(tmp_db.name, arcname="tsp.db")
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        if os.path.isfile(zoom_key_path):
            z.write(zoom_key_path, arcname="zoom.key")
        if os.path.isdir(upload_dir):
            for root, _, files in os.walk(upload_dir):
                for fname in files:
                    full = os.path.join(root, fname)
                    rel = os.path.relpath(full, upload_dir)
                    z.write(full, arcname=os.path.join("uploads", rel))
    os.unlink(tmp_db.name)

    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    response = send_file(tmp_zip.name, mimetype="application/zip",
                         as_attachment=True, download_name=f"tsp-export-{stamp}.zip")
    @response.call_on_close
    def _cleanup():
        try: os.unlink(tmp_zip.name)
        except OSError: pass
    return response


@bp.route("/settings/import", methods=["POST"])
@admin_required
def data_import():
    import json, shutil, tempfile, zipfile
    from datetime import datetime

    f = request.files.get("archive")
    if not f or not f.filename:
        flash("Choose an export archive (.zip) to import", "danger")
        return redirect(_safe_referrer() or url_for("main.index"))
    if request.form.get("confirm") != "REPLACE":
        flash('Type REPLACE in the confirmation box to proceed — import overwrites all data', "danger")
        return redirect(_safe_referrer() or url_for("main.index"))

    upload_dir = current_app.config["UPLOAD_FOLDER"]
    data_dir = os.path.dirname(upload_dir.rstrip("/"))
    db_path = os.path.join(data_dir, "tsp.db")

    staging = tempfile.mkdtemp(prefix="tsp-import-", dir=data_dir)
    try:
        zip_path = os.path.join(staging, "in.zip")
        f.save(zip_path)
        try:
            with zipfile.ZipFile(zip_path) as z:
                names = z.namelist()
                if "tsp.db" not in names or "manifest.json" not in names:
                    flash("Archive is missing tsp.db or manifest.json — not a valid export", "danger")
                    return redirect(_safe_referrer() or url_for("main.index"))
                for n in names:
                    if n.startswith("/") or ".." in n.split("/"):
                        flash(f"Archive contains unsafe path: {n}", "danger")
                        return redirect(_safe_referrer() or url_for("main.index"))
                try:
                    manifest = json.loads(z.read("manifest.json").decode("utf-8"))
                    if manifest.get("app") not in ("trusted-servants-pro", "trusted-servants-portal"):
                        flash("Archive manifest does not identify a Trusted Servants Pro export", "danger")
                        return redirect(_safe_referrer() or url_for("main.index"))
                except (ValueError, UnicodeDecodeError):
                    flash("Archive manifest.json is invalid", "danger")
                    return redirect(_safe_referrer() or url_for("main.index"))
                extract_dir = os.path.join(staging, "extracted")
                os.makedirs(extract_dir, exist_ok=True)
                z.extractall(extract_dir)
        except zipfile.BadZipFile:
            flash("File is not a valid zip archive", "danger")
            return redirect(_safe_referrer() or url_for("main.index"))

        new_db = os.path.join(extract_dir, "tsp.db")
        new_uploads = os.path.join(extract_dir, "uploads")
        new_zoom_key = os.path.join(extract_dir, "zoom.key")

        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        backup_dir = os.path.join(data_dir, f"backup-{stamp}")
        os.makedirs(backup_dir, exist_ok=True)

        db.session.remove()
        db.engine.dispose()

        if os.path.isfile(db_path):
            shutil.move(db_path, os.path.join(backup_dir, "tsp.db"))
        for sfx in ("-wal", "-shm"):
            extra = db_path + sfx
            if os.path.isfile(extra):
                shutil.move(extra, os.path.join(backup_dir, "tsp.db" + sfx))
        zoom_key_path = os.path.join(data_dir, "zoom.key")
        if os.path.isfile(zoom_key_path):
            shutil.move(zoom_key_path, os.path.join(backup_dir, "zoom.key"))
        if os.path.isdir(upload_dir):
            shutil.move(upload_dir, os.path.join(backup_dir, "uploads"))

        shutil.copy2(new_db, db_path)
        if os.path.isfile(new_zoom_key):
            shutil.copy2(new_zoom_key, zoom_key_path)
            try: os.chmod(zoom_key_path, 0o600)
            except OSError: pass
        os.makedirs(upload_dir, exist_ok=True)
        if os.path.isdir(new_uploads):
            for entry in os.listdir(new_uploads):
                src = os.path.join(new_uploads, entry)
                dst = os.path.join(upload_dir, entry)
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)

        from . import _migrate_sqlite, _backfill_media
        from .crypto import init_fernet
        init_fernet(current_app)
        _migrate_sqlite(current_app)
        _backfill_media(current_app)

        flash(f"Import complete. Previous data backed up to {os.path.basename(backup_dir)}/ in the data directory. You will be signed out.", "success")
        return redirect(url_for("auth.logout"))
    finally:
        shutil.rmtree(staging, ignore_errors=True)


# Settings on SiteSetting that make up the public frontend. Used by the
# scoped frontend export/import so a single site can ship its look-and-feel
# (content + navigation + assets) without carrying the whole database.
def _frontend_setting_keys():
    """Comprehensive list of every SiteSetting column that belongs to
    the public-facing frontend.

    Derived from the model's column list at call time so a new column
    added to ``SiteSetting`` is automatically included in the next
    export — no manual list maintenance, no quiet drift between what
    the model declares and what the export captures. Selection is by
    prefix: any column starting with ``frontend_``, ``footer_``,
    ``utility_bar_``, ``header_alert_``, ``hero_``, ``mega_``,
    ``submission_form_``, or ``contact_form_`` is in scope. Admin-only
    / sensitive columns live under unrelated prefixes (``smtp_``,
    ``zoom_``, ``intergroup_``, ``dash_``, ``turnstile_``, ``ig_``,
    ``pic_``, ``og_``) so this prefix-based selector never accidentally
    exfiltrates them.

    Recipient columns inside the included prefixes (anything ending in
    ``_to`` — e.g. ``contact_form_to``) are dropped: those are
    deployment routing config, not look-and-feel, and shipping them
    in a frontend bundle would silently re-route mail to the source
    install's recipients. Excluded explicitly here, recreated locally
    on the destination's own settings page.
    """
    from .models import SiteSetting
    prefixes = ("frontend_", "footer_", "utility_bar_",
                "header_alert_", "hero_", "mega_",
                "submission_form_", "contact_form_",
                # Module-gate flags + per-role visibility controls for
                # the public Events / Announcements / Stories / Blog
                # surfaces. Frontend behaviour columns even though they
                # don't carry a `frontend_` prefix in the schema.
                "posts_", "stories_", "blog_")
    return tuple(sorted(
        c.name for c in SiteSetting.__table__.columns
        if any(c.name.startswith(p) for p in prefixes)
        and not c.name.endswith("_to")))


def _frontend_asset_keys():
    """SiteSetting columns whose value is an uploaded filename — drives
    asset bundling. Same prefix filter as ``_frontend_setting_keys``,
    narrowed to columns ending in ``_filename``."""
    return tuple(c for c in _frontend_setting_keys() if c.endswith("_filename"))


# UUID-prefixed stored-filename pattern. All uploads land in the
# uploads dir as ``<32 hex chars>.<ext>`` (see the ``upload_dir``
# usage above and ``_backfill_media``). Walking content blobs with
# this regex finds every embedded reference — image src in pasted
# Markdown, icon refs in custom layouts, file refs in utility bar
# items, etc. — without per-blob schema knowledge.
_ASSET_REF_RE = re.compile(r"[0-9a-f]{32}(?:\.[A-Za-z0-9]{1,8})?", re.IGNORECASE)


def _collect_asset_refs(value):
    """Return a set of stored-filename strings referenced anywhere
    inside ``value``. ``value`` may be a JSON-encoded string, a Python
    structure, or None. Returns an empty set for falsy / unmatched
    input."""
    if not value:
        return set()
    text = value if isinstance(value, str) else json.dumps(value)
    return set(_ASSET_REF_RE.findall(text))


def _frontend_export_payload():
    """Build a content-complete frontend bundle.

    The payload covers everything that shapes the public site:

      * **settings** — every ``frontend_*`` / ``footer_*`` /
        ``utility_bar_*`` / ``header_alert_*`` / ``hero_*`` / ``mega_*`` /
        ``submission_form_*`` / ``contact_form_*`` column on
        ``SiteSetting`` (derived dynamically so new columns join the
        export automatically; ``*_to`` recipient columns are excluded
        as deployment routing).
      * **nav_items** — every top-level nav row + its columns + links.
      * **hero_buttons** — admin-defined CTAs under the hero subheading.
      * **custom_layouts** — drag-drop creations for homepage / footer /
        page (skipping prebuilts which are seeded fresh on every install).
      * **custom_fonts** — uploaded fonts AND Google-fetched CSS bundles
        (the binary asset list rides along so the import side can place
        every woff2 in the right spot).
      * **custom_icons** — uploaded SVG / PNG icons used by the nav and
        feature blocks.
      * **pages** — admin-authored content pages (``Page`` rows). Their
        ``blocks_json`` plus background colour / image / dynbg config
        plus typography overrides ride along; layout_key is preserved
        so the picker shows the right preset on the destination.
      * **intergroup_officers** — roster surfaced by the ``intergroup_member``
        and ``officer_roster`` page blocks. Pages reference these by
        id, so they ship together to keep the references intact.
      * **stories** — recovery stories on /stories, with author byline,
        sobriety / story dates, body, summary, featured image.
      * **media_items** — catalog of every uploaded file referenced from
        frontend content. The import side re-creates the rows so the
        backfill scan doesn't have to re-derive sha256 / size for each
        file from scratch.

    Posts (announcements + events) are intentionally **excluded** —
    they're per-deployment editorial content, not look-and-feel.
    Slug-history is also excluded since the only entity type it carries
    here was ``post``. Old bundles that contained posts still import
    them via the existing import path; new bundles produced by this
    function omit them.
      * **assets** — union of every stored filename referenced by any of
        the above. The export route writes one file per name into the
        bundle's ``assets/`` folder.

    Asset collection has two sources:
      1. ``_filename`` columns on SiteSetting + ``Page.bg_image_filename``
         + ``Story.featured_image_filename`` + ``Post.featured_image_filename``.
      2. ``_collect_asset_refs`` regex-scan of every JSON content blob —
         catches images embedded in homepage feature blocks, icons in
         utility bar items, references inside custom layouts'
         ``blocks_json``, page ``blocks_json``, story bodies, etc.

    Anything matched in (2) is cross-checked against the MediaItem
    catalog before being included so a false-positive 32-hex match in
    a non-asset string can't try to ship a phantom file.
    """
    from .models import (SiteSetting, CustomLayout, CustomFont, CustomIcon,
                         FrontendHeroButton, MediaItem, Page, Story,
                         IntergroupOfficer)
    s = _get_site_setting()
    setting_keys = _frontend_setting_keys()
    asset_keys = _frontend_asset_keys()
    settings = {k: getattr(s, k, None) for k in setting_keys}
    # Homepage designation — `SiteSetting.homepage_page_id` is a Page FK
    # but page IDs aren't stable across installs. Resolve to the page's
    # slug at export time; the import side looks the page up by slug
    # after pages are restored and re-points the column. The key is
    # absent when no homepage is designated (rare — the auto-seed
    # writes one on every install).
    _hp_slug = None
    if s and s.homepage_page_id:
        _hp = Page.query.get(s.homepage_page_id)
        if _hp is not None:
            _hp_slug = _hp.slug
    settings["homepage_page_slug"] = _hp_slug

    # ---- nav_items (existing shape) -----------------------------------
    nav_items = []
    items = FrontendNavItem.query.order_by(FrontendNavItem.position).all()
    for it in items:
        cols = []
        for c in sorted(it.columns, key=lambda x: x.position):
            links = []
            for l in sorted(c.links, key=lambda x: x.position):
                links.append({
                    "position": l.position, "kind": l.kind, "label": l.label,
                    "url": l.url, "icon_before": l.icon_before,
                    "icon_after": l.icon_after,
                    "icon_before_color": l.icon_before_color,
                    "icon_after_color": l.icon_after_color,
                    "icon_before_size": l.icon_before_size,
                    "icon_after_size": l.icon_after_size,
                    "link_size": l.link_size,
                    "link_size_pct": l.link_size_pct,
                    "override_color": bool(l.override_color),
                    "custom_color": l.custom_color,
                    "button_style": l.button_style,
                    "open_in_new_tab": bool(l.open_in_new_tab),
                    "form_trigger": l.form_trigger,
                })
            cols.append({
                "position": c.position, "heading": c.heading, "links": links,
            })
        nav_items.append({
            "position": it.position, "style": it.style, "label": it.label,
            "line1": it.line1, "line2": it.line2, "url": it.url,
            "has_megamenu": bool(it.has_megamenu),
            "open_in_new_tab": bool(it.open_in_new_tab),
            "form_trigger": it.form_trigger,
            "columns": cols,
        })

    # ---- hero_buttons -------------------------------------------------
    hero_buttons = [
        {"position": b.position, "label": b.label, "url": b.url,
         "style": b.style,
         "custom_bg_color": b.custom_bg_color,
         "custom_text_color": b.custom_text_color,
         "icon_before": b.icon_before, "icon_after": b.icon_after,
         "icon_before_color": b.icon_before_color,
         "icon_after_color": b.icon_after_color,
         "icon_before_size": b.icon_before_size,
         "icon_after_size": b.icon_after_size,
         "open_in_new_tab": bool(b.open_in_new_tab)}
        for b in FrontendHeroButton.query.order_by(FrontendHeroButton.position).all()
    ]

    # ---- custom_layouts (homepage / footer / page) --------------------
    # Prebuilts are skipped — they're seeded fresh on every install and
    # round-tripping them would just create duplicate rows on import.
    custom_layouts = [
        {"key": cl.key, "name": cl.name, "description": cl.description,
         "kind": cl.kind, "blocks_json": cl.blocks_json}
        for cl in CustomLayout.query.filter_by(is_prebuilt=False).all()
    ]

    # ---- custom_fonts -------------------------------------------------
    custom_fonts = [
        {"name": cf.name, "family": cf.family, "source": cf.source,
         "stored_filename": cf.stored_filename,
         "google_url": cf.google_url,
         "asset_files_json": cf.asset_files_json,
         "mime_type": cf.mime_type, "size_bytes": cf.size_bytes}
        for cf in CustomFont.query.all()
    ]

    # ---- custom_icons -------------------------------------------------
    custom_icons = [
        {"name": ci.name, "stored_filename": ci.stored_filename,
         "mime_type": ci.mime_type, "size_bytes": ci.size_bytes}
        for ci in CustomIcon.query.all()
    ]

    # ---- pages -------------------------------------------------------
    # Admin-authored content pages (/<slug>). Carries everything that
    # shapes how the page renders: blocks_json, layout key, page
    # background (colour + image + dynbg), width formatting, hero
    # typography overrides, visibility flags. Created/updated_at fields
    # are preserved so import-side ordering reflects the source.
    pages = []
    for p in Page.query.order_by(Page.id).all():
        pages.append({
            "slug": p.slug, "title": p.title,
            "blocks_json": p.blocks_json,
            "template": p.template,
            "is_published": bool(p.is_published),
            "is_private": bool(p.is_private),
            "layout_key": p.layout_key,
            "bg_image_filename": p.bg_image_filename,
            "bg_mode": p.bg_mode,
            "bg_tile_scale": p.bg_tile_scale,
            "bg_color": p.bg_color,
            "bg_color_dark": p.bg_color_dark,
            "bg_color_dark_mode": p.bg_color_dark_mode,
            "bg_dynamic_key": p.bg_dynamic_key,
            "bg_dynbg_config_json": p.bg_dynbg_config_json,
            "width_mode": p.width_mode,
            "max_width": p.max_width,
            "full_padding_pct": p.full_padding_pct,
            "heading_color": p.heading_color,
            "heading_align": p.heading_align,
            "heading_font": p.heading_font,
            "subheading_color": p.subheading_color,
            "subheading_font": p.subheading_font,
            # Per-page spacing controls (added during the page-builder
            # cycle). Each defaults to a sensible value at the model
            # level, so older v3 bundles round-trip without these keys.
            "pad_top": p.pad_top,
            "pad_bottom": p.pad_bottom,
            "pad_x": p.pad_x,
            "section_gap": p.section_gap,
            "block_margin_y": p.block_margin_y,
        })

    # ---- intergroup_officers ----------------------------------------
    # Public-facing roster pulled by intergroup_member / officer_roster
    # blocks. Pages reference rows by id, so the import side preserves
    # the ids when possible (clears the table first, then re-inserts
    # with the source's ids) so block references survive the round-trip.
    intergroup_officers = [
        {"id": o.id, "role": o.role, "name": o.name,
         "phone": o.phone, "email": o.email,
         "sort_order": o.sort_order}
        for o in IntergroupOfficer.query.order_by(
            IntergroupOfficer.sort_order, IntergroupOfficer.id).all()
    ]

    # ---- stories -----------------------------------------------------
    # /stories content. Drafts + archives ride along (admins cloning
    # a frontend usually want the full editorial state) but body /
    # summary blobs feed asset_refs so embedded images come along.
    stories = []
    for st in Story.query.order_by(Story.id).all():
        stories.append({
            "slug": st.slug, "title": st.title,
            "summary": st.summary, "body": st.body,
            "featured_image_filename": st.featured_image_filename,
            "author_name": st.author_name, "author_bio": st.author_bio,
            "sobriety_date": st.sobriety_date.isoformat() if st.sobriety_date else None,
            "story_date": st.story_date.isoformat() if st.story_date else None,
            "is_featured": bool(st.is_featured),
            "is_draft": bool(st.is_draft),
            "is_archived": bool(st.is_archived),
        })

    # ---- posts + slug_history intentionally OMITTED -------------------
    # Posts (announcements + events) are per-deployment editorial
    # content, not "frontend look-and-feel" — shipping them in this
    # bundle would silently overwrite the destination's editorial state
    # on import. Slug-history (driving 301 redirects) only carried
    # `post` entity types, so it goes too. The import side keeps its
    # backwards-compat path so old bundles that DO contain posts still
    # restore them; this export just stops producing them.

    # ---- asset collection --------------------------------------------
    # Layer 1: explicit filename columns.
    asset_refs = set()
    for k in asset_keys:
        v = settings.get(k)
        if v:
            asset_refs.add(v)

    # Layer 2: scan every JSON content blob for stored-filename
    # references.
    blob_columns = (
        "frontend_blocks_json", "frontend_footer_blocks_json",
        "frontend_design_json", "frontend_fonts_json",
        "frontend_template_settings_json",
        "frontend_meetings_list_protips_json",
        "frontend_hero_sinewave_colors",
        "utility_bar_left_json", "utility_bar_right_json",
    )
    for k in blob_columns:
        asset_refs |= _collect_asset_refs(getattr(s, k, None))
    for cl in custom_layouts:
        asset_refs |= _collect_asset_refs(cl.get("blocks_json"))
    for cf in custom_fonts:
        if cf.get("stored_filename"):
            asset_refs.add(cf["stored_filename"])
        # asset_files_json is a JSON list of stored filenames for the
        # Google-fetched woff2 binaries.
        try:
            extras = json.loads(cf.get("asset_files_json") or "[]")
            if isinstance(extras, list):
                for fn in extras:
                    if isinstance(fn, str) and fn:
                        asset_refs.add(fn)
        except (ValueError, TypeError):
            pass
    for ci in custom_icons:
        if ci.get("stored_filename"):
            asset_refs.add(ci["stored_filename"])

    # Layer 3: assets referenced by the new content entities. Each row
    # may carry an explicit ``*_filename`` plus markdown / JSON bodies
    # whose embedded images need to ride along with the bundle.
    for p in pages:
        if p.get("bg_image_filename"):
            asset_refs.add(p["bg_image_filename"])
        asset_refs |= _collect_asset_refs(p.get("blocks_json"))
        asset_refs |= _collect_asset_refs(p.get("bg_dynbg_config_json"))
    for st in stories:
        if st.get("featured_image_filename"):
            asset_refs.add(st["featured_image_filename"])
        asset_refs |= _collect_asset_refs(st.get("body"))
        asset_refs |= _collect_asset_refs(st.get("summary"))
    # Posts are excluded from this bundle (see the notes above) so no
    # per-post asset scan runs here. Story / page / settings / nav /
    # custom-layouts scans below remain.

    # Cross-check matched filenames against the MediaItem catalog (for
    # the regex-discovered ones — explicit columns and table-stored
    # filenames are trusted as-is). Anything that doesn't match a real
    # MediaItem row is dropped: it's almost certainly a false-positive
    # 32-hex coincidence in a non-asset string.
    known_media = {m.stored_filename: m for m in MediaItem.query.all()}
    final_assets = set()
    for ref in asset_refs:
        if ref in known_media:
            final_assets.add(ref)
            continue
        # Files referenced via _filename columns or font/icon rows but
        # absent from MediaItem still ship — pre-MediaItem uploads
        # (older installs) aren't always indexed. The backfill scan on
        # import will re-index them.
        final_assets.add(ref)

    # ---- media_items catalog ------------------------------------------
    # Ride along with the bundle so the import side can re-populate
    # MediaItem rows for the assets we shipped, instead of relying on
    # the boot-time backfill scan to recompute hashes for every file.
    media_items = []
    for fn in sorted(final_assets):
        m = known_media.get(fn)
        if m is None:
            continue
        media_items.append({
            "stored_filename": m.stored_filename,
            "original_filename": m.original_filename,
            "content_hash": m.content_hash,
            "size_bytes": m.size_bytes,
            "mime_type": m.mime_type,
        })

    return {
        "kind": "frontend", "format_version": 4,
        "settings": settings,
        "nav_items": nav_items,
        "hero_buttons": hero_buttons,
        "custom_layouts": custom_layouts,
        "custom_fonts": custom_fonts,
        "custom_icons": custom_icons,
        "pages": pages,
        "intergroup_officers": intergroup_officers,
        "stories": stories,
        "media_items": media_items,
        "assets": sorted(final_assets),
    }


@bp.route("/settings/db-snapshot/<name>")
@admin_required
def data_snapshot_download(name):
    """Download a single SQLite snapshot. Filename is validated against
    the snapshot naming pattern so this can't be used to read arbitrary
    files out of the data directory."""
    from .backup import SNAPSHOT_PREFIX, SNAPSHOT_SUFFIX
    from pathlib import Path
    safe = secure_filename(name)
    if not safe.startswith(SNAPSHOT_PREFIX) or not safe.endswith(SNAPSHOT_SUFFIX):
        abort(404)
    stem = safe[len(SNAPSHOT_PREFIX):-len(SNAPSHOT_SUFFIX)]
    if not (stem.isdigit() and len(stem) == 8):
        abort(404)
    backups_dir = Path(current_app.config["DATA_DIR"]) / "backups"
    target = backups_dir / safe
    if not target.is_file():
        abort(404)
    return send_from_directory(str(backups_dir), safe,
                               as_attachment=True,
                               download_name=safe,
                               mimetype="application/x-sqlite3")


@bp.route("/settings/db-snapshot-now", methods=["POST"])
@admin_required
def data_snapshot_now():
    """Take an on-demand snapshot. Idempotent for the same calendar day —
    if today's snapshot already exists, this is a no-op (matches the
    automatic daily behavior)."""
    from .backup import daily_snapshot
    target = daily_snapshot(current_app)
    if target is not None:
        flash(f"Snapshot saved: {target.name}", "success")
    else:
        flash("Today's snapshot already exists — nothing to do.", "info")
    return redirect(_safe_referrer() or url_for("main.index"))


# ---------------------------------------------------------------------------
# WordPress importer wizard — multi-step flow that pulls posts from a WP
# REST endpoint or a WP All Export CSV and lets the admin map each post
# (or every post in a category) onto Stories / Announcements / Events,
# with a dry-run preview before committing. Mounted in two ways:
#   /tspro/settings/wp-import          — full-page wizard
#   /tspro/settings/wp-import?embed=1  — chromeless wizard for the modal
# Embed mode flows through every redirect via _embed() / _embed_kwargs()
# so refreshing or following a flash redirect doesn't drop chrome.
# ---------------------------------------------------------------------------
def _wp_embed():
    """True when the wizard request came in via the modal iframe.
    Carried through forms as a hidden input + on every redirect URL."""
    return (request.args.get("embed") == "1"
            or request.form.get("embed") == "1")


def _wp_embed_kwargs():
    """Spread into ``url_for(...)`` calls inside wizard redirects so the
    next step keeps embed mode on."""
    return {"embed": 1} if _wp_embed() else {}


@bp.route("/settings/wp-import")
@admin_required
def wp_import_start():
    """Step 1 — source picker. Also opportunistically purges stash files
    older than 24h so an abandoned wizard doesn't leave junk in the data
    directory."""
    from . import wp_importer
    wp_importer.stash_purge_old()
    return render_template("wp_import_start.html", embed=_wp_embed())


@bp.route("/settings/wp-import/connect", methods=["POST"])
@admin_required
def wp_import_connect():
    """Step 2a — fetch from WP REST. Persists the normalized payload to
    a stash JSON, then redirects into the mapping page."""
    from . import wp_importer
    site = (request.form.get("site_url") or "").strip()
    user = (request.form.get("wp_user") or "").strip() or None
    pw = (request.form.get("wp_password") or "").strip() or None
    posts, cats, tags, err = wp_importer.fetch_wp(site, user, pw)
    if err:
        flash(err, "danger")
        return redirect(url_for("main.wp_import_start", **_wp_embed_kwargs()))
    if not posts:
        flash("No posts found at that WordPress site. The REST API returned an empty list.", "warning")
        return redirect(url_for("main.wp_import_start", **_wp_embed_kwargs()))
    token = wp_importer.new_token()
    # Split the rich category/tag dicts into a flat name list (used by
    # the mapping UI's per-category form keys) and a parallel meta map
    # (used by apply_plan's BlogCategory / BlogTag resolver to carry
    # source slug + description through).
    cat_names = [c["name"] for c in (cats or [])]
    cat_meta = {c["name"]: {"slug": c.get("slug", ""), "description": c.get("description", "")}
                for c in (cats or [])}
    tag_names = [t["name"] for t in (tags or [])]
    tag_meta = {t["name"]: {"slug": t.get("slug", "")} for t in (tags or [])}
    wp_importer.stash_save(token, {
        "source": "rest",
        "site_url": site,
        "wp_user": user,
        "posts": posts,
        "categories": cat_names,
        "category_meta": cat_meta,
        "tags": tag_names,
        "tag_meta": tag_meta,
        "mapping": {},
        "category_mapping": {},
        "created_at": datetime.utcnow().isoformat() + "Z",
    })
    flash(f"Connected — fetched {len(posts)} post{'s' if len(posts) != 1 else ''}.", "success")
    return redirect(url_for("main.wp_import_map", token=token, **_wp_embed_kwargs()))


@bp.route("/settings/wp-import/upload-csv", methods=["POST"])
@admin_required
def wp_import_upload_csv():
    """Step 2b — parse a CSV. Same shape as the REST connect endpoint:
    persists the normalized payload to a stash JSON and redirects into
    the mapping page."""
    from . import wp_importer
    f = request.files.get("csv")
    if not f or not f.filename:
        flash("Please choose a CSV file.", "danger")
        return redirect(url_for("main.wp_import_start", **_wp_embed_kwargs()))
    posts, cats, tags, err = wp_importer.parse_csv(f)
    if err:
        flash(err, "danger")
        return redirect(url_for("main.wp_import_start", **_wp_embed_kwargs()))
    token = wp_importer.new_token()
    cat_names = [c["name"] for c in (cats or [])]
    cat_meta = {c["name"]: {"slug": c.get("slug", ""), "description": c.get("description", "")}
                for c in (cats or [])}
    tag_names = [t["name"] for t in (tags or [])]
    tag_meta = {t["name"]: {"slug": t.get("slug", "")} for t in (tags or [])}
    wp_importer.stash_save(token, {
        "source": "csv",
        "filename": f.filename,
        "posts": posts,
        "categories": cat_names,
        "category_meta": cat_meta,
        "tags": tag_names,
        "tag_meta": tag_meta,
        "mapping": {},
        "category_mapping": {},
        "created_at": datetime.utcnow().isoformat() + "Z",
    })
    flash(f"Parsed {len(posts)} row{'s' if len(posts) != 1 else ''} from {f.filename}.", "success")
    return redirect(url_for("main.wp_import_map", token=token, **_wp_embed_kwargs()))


@bp.route("/settings/wp-import/<token>/map", methods=["GET", "POST"])
@admin_required
def wp_import_map(token):
    """Step 3 — review parsed posts and assign each one (or each
    category) to a target. POST persists the mapping back to the stash
    and redirects into the dry-run preview."""
    from . import wp_importer
    stash = wp_importer.stash_load(token)
    if not stash:
        flash("That import wizard session has expired. Start over.", "warning")
        return redirect(url_for("main.wp_import_start", **_wp_embed_kwargs()))

    if request.method == "POST":
        # Per-category mapping — when an admin sets a category to a
        # target, every post tagged with that category inherits the
        # target unless they've also been mapped individually.
        cat_map = {}
        for cat in stash.get("categories") or []:
            v = (request.form.get(f"cat:{cat}") or "skip").strip()
            if v in wp_importer.TARGETS:
                cat_map[cat] = v
        # Per-post mapping wins when set to anything other than the
        # special sentinel "category" (which means "use the category
        # default below"). Default is "category".
        post_map = {}
        for p in stash.get("posts") or []:
            v = (request.form.get(f"post:{p['key']}") or "category").strip()
            if v in wp_importer.TARGETS:
                post_map[p["key"]] = v
            # else "category" — leave the resolved value to be derived
            # from the post's first matching category at compile time.
        # Resolve effective per-post mapping: explicit per-post value
        # wins; otherwise the first category whose value isn't "skip"
        # wins; falls back to "skip".
        effective = {}
        for p in stash.get("posts") or []:
            if p["key"] in post_map:
                effective[p["key"]] = post_map[p["key"]]
            else:
                chosen = "skip"
                for c in p.get("categories") or []:
                    if cat_map.get(c) and cat_map[c] != "skip":
                        chosen = cat_map[c]
                        break
                effective[p["key"]] = chosen
        stash["mapping"] = effective
        stash["category_mapping"] = cat_map
        stash["post_mapping"] = post_map
        wp_importer.stash_save(token, stash)
        return redirect(url_for("main.wp_import_dry_run", token=token, **_wp_embed_kwargs()))

    # GET — render the mapping table. Precompute per-category post
    # counts here (Jinja doesn't have list comprehensions, so doing
    # this in the template requires a namespace dance).
    cat_counts = {}
    for cat in stash.get("categories") or []:
        cat_counts[cat] = sum(1 for p in (stash.get("posts") or [])
                              if cat in (p.get("categories") or []))
    # Hide the Blog target pill when the module is off so an admin can't
    # accidentally route imports into a disabled module. The mapping UI
    # iterates ``targets`` for the radio group, so trimming the tuple
    # keeps the choice off the form entirely.
    site = _get_site_setting()
    blog_on = bool(site and getattr(site, "blog_enabled", False))
    if blog_on:
        targets = wp_importer.TARGETS
    else:
        targets = tuple(t for t in wp_importer.TARGETS if t != "blog")
    # Stale-stash detection. A wizard token created before the ACF
    # capture path was added has a stash whose posts are all missing
    # the ``acf`` key — re-using such a stash would silently produce
    # ACF-less imports. We surface a banner with a Re-connect link so
    # the admin can start a fresh fetch instead of clicking through.
    posts_for_check = stash.get("posts") or []
    stale_acf_stash = (
        (stash.get("source") == "rest")
        and bool(posts_for_check)
        and not any(p.get("acf") for p in posts_for_check)
    )
    return render_template("wp_import_map.html", token=token, stash=stash,
                           targets=targets,
                           target_labels=wp_importer.TARGET_LABELS,
                           cat_counts=cat_counts,
                           blog_enabled=blog_on,
                           stale_acf_stash=stale_acf_stash,
                           embed=_wp_embed())


@bp.route("/settings/wp-import/<token>/dry-run", methods=["GET", "POST"])
@admin_required
def wp_import_dry_run(token):
    """Step 4 — preview the plan. POST commits it; GET renders the
    preview table."""
    from . import wp_importer
    stash = wp_importer.stash_load(token)
    if not stash:
        flash("That import wizard session has expired. Start over.", "warning")
        return redirect(url_for("main.wp_import_start", **_wp_embed_kwargs()))

    actions = wp_importer.compile_plan(stash.get("posts") or [],
                                       stash.get("mapping") or {})

    if request.method == "POST":
        # Per-row archive overrides ride along on the dry-run form. The
        # checkboxes are named ``archive:<post_key>`` and admins can flip
        # any subset (or use the bulk select-all to flag every row).
        # Validated against the actual post keys so a tampered form can't
        # smuggle archive flags onto skipped rows.
        valid_keys = {a["post"]["key"] for a in actions if a["target"] != "skip"}
        archive_keys = set()
        for raw in request.form.keys():
            if raw.startswith("archive:"):
                k = raw[len("archive:"):]
                if k in valid_keys:
                    archive_keys.add(k)
        # Persist the choice to the stash so a re-render after a flash
        # message keeps the admin's selections (e.g. when they forget
        # to type IMPORT and bounce back).
        stash["archive_keys"] = sorted(archive_keys)
        wp_importer.stash_save(token, stash)

        if request.form.get("confirm") != "IMPORT":
            flash("Type IMPORT in the confirmation field to proceed.", "warning")
            return redirect(url_for("main.wp_import_dry_run", token=token, **_wp_embed_kwargs()))

        def _img_cb(url):
            # Returns ``(stored_filename, original_filename)`` so both
            # the featured-image apply step (uses stored) and the
            # inline-image rewriter (uses original to build /pub/<…>)
            # can share one callback.
            return wp_importer._download_image_full(
                url, uploaded_by=getattr(current_user, "id", None))

        result = wp_importer.apply_plan(
            actions, dry_run=False, image_cb=_img_cb,
            created_by=getattr(current_user, "id", None),
            category_meta=stash.get("category_meta") or {},
            tag_meta=stash.get("tag_meta") or {},
            archive_keys=archive_keys,
        )
        from . import activity
        activity.log("wp_import.commit", entity_type="wp_import",
                     summary=(f"Imported {result['counts']['stories']} stor{'y' if result['counts']['stories']==1 else 'ies'}, "
                              f"{result['counts']['announcements']} announcement(s), "
                              f"{result['counts']['events']} event(s), "
                              f"{result['counts']['blog']} blog post(s) from "
                              f"{stash.get('source','?')}"))
        wp_importer.stash_delete(token)
        return render_template("wp_import_done.html", result=result,
                               source=stash.get("source"),
                               embed=_wp_embed())

    archive_keys = set(stash.get("archive_keys") or [])
    preview = wp_importer.apply_plan(
        actions, dry_run=True,
        category_meta=stash.get("category_meta") or {},
        tag_meta=stash.get("tag_meta") or {},
        archive_keys=archive_keys,
    )
    posts_for_check = stash.get("posts") or []
    stale_acf_stash = (
        (stash.get("source") == "rest")
        and bool(posts_for_check)
        and not any(p.get("acf") for p in posts_for_check)
    )
    return render_template("wp_import_dry_run.html",
                           token=token, stash=stash,
                           actions=actions, preview=preview,
                           archive_keys=archive_keys,
                           target_labels=wp_importer.TARGET_LABELS,
                           stale_acf_stash=stale_acf_stash,
                           embed=_wp_embed())


@bp.route("/settings/wp-import/<token>/cancel", methods=["POST"])
@admin_required
def wp_import_cancel(token):
    from . import wp_importer
    wp_importer.stash_delete(token)
    flash("Import cancelled — nothing was changed.", "info")
    return redirect(url_for("main.wp_import_start", **_wp_embed_kwargs()))


@bp.route("/settings/frontend-export")
@admin_required
def data_frontend_export():
    import io, json, tempfile, zipfile
    from datetime import datetime
    from flask import send_file

    upload_dir = current_app.config["UPLOAD_FOLDER"]
    payload = _frontend_export_payload()
    manifest = {
        "app": "trusted-servants-pro",
        "kind": "frontend",
        "format_version": 4,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "content_filename": "frontend.json",
        "assets_dir": "assets/",
        "note": ("Scoped frontend bundle (v4). Includes every "
                 "look-and-feel SiteSetting column (frontend_, footer_, "
                 "utility_bar_, header_alert_, hero_, mega_, "
                 "submission_form_, contact_form_; recipient *_to "
                 "columns excluded as deployment routing), the homepage "
                 "designation (resolved through page slug for "
                 "portability), nav, hero buttons, custom layouts "
                 "(homepage / footer / page), custom fonts, custom "
                 "icons, content pages (full schema including the "
                 "per-page spacing controls pad_top / pad_bottom / "
                 "pad_x / section_gap / block_margin_y), intergroup "
                 "officers, stories, posts (drafts and archives "
                 "included; pending submissions skipped), post slug "
                 "history, MediaItem catalog, plus every uploaded "
                 "file referenced from any of the above. Import via "
                 "the Data tab on another install to overlay the "
                 "public site without touching users, meetings, or "
                 "libraries. v3 bundles still import — the new "
                 "spacing columns fall back to Page defaults and the "
                 "homepage stays whatever the destination's auto-seed "
                 "wrote."),
    }

    tmp_zip = tempfile.NamedTemporaryFile(prefix="tsp-fe-export-", suffix=".zip", delete=False)
    tmp_zip.close()
    with zipfile.ZipFile(tmp_zip.name, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("frontend.json", json.dumps(payload, indent=2))
        for fn in payload["assets"]:
            src = os.path.join(upload_dir, fn)
            if os.path.isfile(src):
                z.write(src, arcname=os.path.join("assets", fn))

    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    response = send_file(tmp_zip.name, mimetype="application/zip",
                         as_attachment=True, download_name=f"tsp-frontend-{stamp}.zip")
    @response.call_on_close
    def _cleanup():
        try: os.unlink(tmp_zip.name)
        except OSError: pass
    return response


@bp.route("/settings/frontend-import", methods=["POST"])
@admin_required
def data_frontend_import():
    import json, shutil, tempfile, zipfile

    f = request.files.get("archive")
    if not f or not f.filename:
        flash("Choose a frontend bundle (.zip) to import", "danger")
        return redirect(_safe_referrer() or url_for("main.index"))
    if request.form.get("confirm") != "REPLACE":
        flash('Type REPLACE in the confirmation box to overwrite frontend content', "danger")
        return redirect(_safe_referrer() or url_for("main.index"))

    upload_dir = current_app.config["UPLOAD_FOLDER"]
    data_dir = os.path.dirname(upload_dir.rstrip("/"))
    staging = tempfile.mkdtemp(prefix="tsp-fe-import-", dir=data_dir)
    try:
        zip_path = os.path.join(staging, "in.zip")
        f.save(zip_path)
        try:
            with zipfile.ZipFile(zip_path) as z:
                names = z.namelist()
                for n in names:
                    if n.startswith("/") or ".." in n.split("/"):
                        flash(f"Archive contains unsafe path: {n}", "danger")
                        return redirect(_safe_referrer() or url_for("main.index"))
                if "frontend.json" not in names or "manifest.json" not in names:
                    flash("Archive is missing frontend.json or manifest.json — not a valid frontend bundle", "danger")
                    return redirect(_safe_referrer() or url_for("main.index"))
                try:
                    manifest = json.loads(z.read("manifest.json").decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    flash("Archive manifest.json is invalid", "danger")
                    return redirect(_safe_referrer() or url_for("main.index"))
                if manifest.get("app") not in ("trusted-servants-pro", "trusted-servants-portal"):
                    flash("Archive manifest does not identify a Trusted Servants Pro export", "danger")
                    return redirect(_safe_referrer() or url_for("main.index"))
                if manifest.get("kind") != "frontend":
                    flash("This looks like a full archive, not a frontend bundle. Use the Import &amp; Replace form instead.", "danger")
                    return redirect(_safe_referrer() or url_for("main.index"))
                try:
                    payload = json.loads(z.read("frontend.json").decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    flash("Archive frontend.json is invalid", "danger")
                    return redirect(_safe_referrer() or url_for("main.index"))
                extract_dir = os.path.join(staging, "extracted")
                os.makedirs(extract_dir, exist_ok=True)
                z.extractall(extract_dir)
        except zipfile.BadZipFile:
            flash("File is not a valid zip archive", "danger")
            return redirect(_safe_referrer() or url_for("main.index"))

        # 1. Copy assets into uploads/ (preserve filenames — they're already
        #    UUID-prefixed on the source install and won't collide in practice).
        assets_src = os.path.join(extract_dir, "assets")
        os.makedirs(upload_dir, exist_ok=True)
        if os.path.isdir(assets_src):
            for entry in os.listdir(assets_src):
                src = os.path.join(assets_src, entry)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(upload_dir, entry))

        # 2. Apply settings onto the singleton SiteSetting row.
        # Use the dynamic key list so a column added after the bundle
        # was exported doesn't trip an AttributeError; only assign keys
        # that the bundle actually carries AND the model still defines.
        s = _get_site_setting()
        incoming = payload.get("settings") or {}
        valid_keys = set(_frontend_setting_keys())
        for key in valid_keys:
            if key in incoming:
                setattr(s, key, incoming[key])

        # 3. Rebuild the nav tree. Cascade deletes columns + links.
        for it in FrontendNavItem.query.all():
            db.session.delete(it)
        db.session.flush()

        for ni in payload.get("nav_items") or []:
            item = FrontendNavItem(
                position=int(ni.get("position") or 0),
                style=(ni.get("style") or "text"),
                label=ni.get("label"),
                line1=ni.get("line1"), line2=ni.get("line2"),
                url=ni.get("url"),
                has_megamenu=bool(ni.get("has_megamenu")),
                open_in_new_tab=bool(ni.get("open_in_new_tab")),
                form_trigger=(ni.get("form_trigger") or None),
            )
            db.session.add(item)
            db.session.flush()
            for nc in (ni.get("columns") or []):
                col = FrontendNavColumn(
                    nav_item_id=item.id,
                    position=int(nc.get("position") or 0),
                    heading=nc.get("heading"),
                )
                db.session.add(col)
                db.session.flush()
                for nl in (nc.get("links") or []):
                    # link_size is the legacy small/large value (kept for
                    # round-trip JSON compat — no longer drives sizing).
                    # link_size_pct is the new per-link percent override
                    # (50–200, NULL = inherit global slider).
                    _lsz = (nl.get("link_size") or "").strip().lower() or None
                    _lpct_raw = nl.get("link_size_pct")
                    try:
                        _lpct = int(_lpct_raw) if _lpct_raw not in (None, "", "null") else None
                    except (TypeError, ValueError):
                        _lpct = None
                    if _lpct is not None:
                        _lpct = max(50, min(_lpct, 200))
                        if _lpct == 100:
                            _lpct = None
                    link = FrontendNavLink(
                        column_id=col.id,
                        position=int(nl.get("position") or 0),
                        kind=(nl.get("kind") or "link"),
                        label=(nl.get("label") or ""),
                        url=nl.get("url"),
                        icon_before=nl.get("icon_before"),
                        icon_after=nl.get("icon_after"),
                        icon_before_color=_sanitize_icon_color(nl.get("icon_before_color")),
                        icon_after_color=_sanitize_icon_color(nl.get("icon_after_color")),
                        icon_before_size=_sanitize_icon_size(nl.get("icon_before_size")),
                        icon_after_size=_sanitize_icon_size(nl.get("icon_after_size")),
                        link_size=_lsz if _lsz in _NAV_LINK_SIZES else None,
                        link_size_pct=_lpct,
                        override_color=bool(nl.get("override_color")),
                        custom_color=_sanitize_icon_color(nl.get("custom_color")),
                        button_style=(nl.get("button_style") or "pill"),
                        open_in_new_tab=bool(nl.get("open_in_new_tab")),
                        form_trigger=(nl.get("form_trigger") or None),
                    )
                    db.session.add(link)

        # 4. Hero buttons — replace wholesale.
        for b in FrontendHeroButton.query.all():
            db.session.delete(b)
        db.session.flush()
        for b in (payload.get("hero_buttons") or []):
            db.session.add(FrontendHeroButton(
                position=int(b.get("position") or 0),
                label=(b.get("label") or "")[:200],
                url=b.get("url"),
                style=(b.get("style") or "primary"),
                custom_bg_color=_sanitize_icon_color(b.get("custom_bg_color")),
                custom_text_color=_sanitize_icon_color(b.get("custom_text_color")),
                icon_before=b.get("icon_before"),
                icon_after=b.get("icon_after"),
                icon_before_color=_sanitize_icon_color(b.get("icon_before_color")),
                icon_after_color=_sanitize_icon_color(b.get("icon_after_color")),
                icon_before_size=_sanitize_icon_size(b.get("icon_before_size")),
                icon_after_size=_sanitize_icon_size(b.get("icon_after_size")),
                open_in_new_tab=bool(b.get("open_in_new_tab")),
            ))

        # 5. CustomLayout — drag-drop creations only. Prebuilts are
        # left alone (they're seeded fresh on every install). Replace
        # any existing non-prebuilt with the matching key, and create
        # rows for keys not present locally.
        from .models import CustomLayout, CustomFont, CustomIcon
        for cl in CustomLayout.query.filter_by(is_prebuilt=False).all():
            db.session.delete(cl)
        db.session.flush()
        for cl in (payload.get("custom_layouts") or []):
            key = (cl.get("key") or "").strip()
            if not key:
                continue
            # Don't collide with seeded prebuilts.
            existing_prebuilt = CustomLayout.query.filter_by(
                key=key, is_prebuilt=True).first()
            if existing_prebuilt:
                continue
            db.session.add(CustomLayout(
                key=key[:64],
                name=(cl.get("name") or key)[:120],
                description=cl.get("description"),
                kind=(cl.get("kind") or "homepage")[:16],
                blocks_json=(cl.get("blocks_json") or "[]"),
                is_prebuilt=False,
            ))

        # 6. CustomFont — replace by family name. Skip rows whose
        # asset files are missing on disk (the bundle either never
        # carried them or the paths got mangled in transit) so we
        # don't leave dangling references.
        for cf in CustomFont.query.all():
            db.session.delete(cf)
        db.session.flush()
        for cf in (payload.get("custom_fonts") or []):
            stored = cf.get("stored_filename") or ""
            if stored and not os.path.isfile(os.path.join(upload_dir, stored)):
                continue
            db.session.add(CustomFont(
                name=(cf.get("name") or "")[:120],
                family=(cf.get("family") or "")[:120],
                source=(cf.get("source") or "upload")[:16],
                stored_filename=stored or None,
                google_url=cf.get("google_url"),
                asset_files_json=cf.get("asset_files_json"),
                mime_type=cf.get("mime_type"),
                size_bytes=int(cf.get("size_bytes") or 0),
            ))

        # 7. CustomIcon — replace wholesale.
        for ci in CustomIcon.query.all():
            db.session.delete(ci)
        db.session.flush()
        for ci in (payload.get("custom_icons") or []):
            stored = ci.get("stored_filename") or ""
            if not stored or not os.path.isfile(os.path.join(upload_dir, stored)):
                continue
            db.session.add(CustomIcon(
                name=(ci.get("name") or "")[:120],
                stored_filename=stored,
                mime_type=(ci.get("mime_type") or "application/octet-stream"),
                size_bytes=int(ci.get("size_bytes") or 0),
            ))

        # 8. MediaItem catalog — upsert by stored_filename so we don't
        # duplicate rows when the same file already exists locally.
        # This skips the boot-time backfill having to re-hash every
        # incoming asset; it just slots the rows in directly.
        for m in (payload.get("media_items") or []):
            stored = m.get("stored_filename")
            if not stored or not os.path.isfile(os.path.join(upload_dir, stored)):
                continue
            existing = MediaItem.query.filter_by(stored_filename=stored).first()
            if existing:
                # Patch missing metadata; don't overwrite a fuller
                # local row with a leaner imported one.
                if not existing.original_filename and m.get("original_filename"):
                    existing.original_filename = m["original_filename"]
                if not existing.content_hash and m.get("content_hash"):
                    existing.content_hash = m["content_hash"]
                if not existing.size_bytes and m.get("size_bytes"):
                    existing.size_bytes = int(m.get("size_bytes") or 0)
                if not existing.mime_type and m.get("mime_type"):
                    existing.mime_type = m["mime_type"]
            else:
                db.session.add(MediaItem(
                    stored_filename=stored,
                    original_filename=(m.get("original_filename") or stored),
                    content_hash=m.get("content_hash"),
                    size_bytes=int(m.get("size_bytes") or 0),
                    mime_type=m.get("mime_type"),
                ))

        # 9. Pages (admin-authored content pages). Replace by slug —
        # the source's slug becomes the destination's. Existing rows
        # with the same slug are dropped first so the import is a
        # clean overlay rather than a partial merge.
        from .models import (Page, IntergroupOfficer, Story, Post,
                             EntitySlugHistory)
        page_payload = payload.get("pages") or []
        if page_payload:
            slugs_to_replace = {p.get("slug") for p in page_payload if p.get("slug")}
            if slugs_to_replace:
                Page.query.filter(Page.slug.in_(slugs_to_replace)).delete(
                    synchronize_session=False)
                db.session.flush()
            for p in page_payload:
                slug = (p.get("slug") or "").strip()
                if not slug:
                    continue
                # `_opt_int` preserves explicit 0 values (the bare
                # `int(p.get(key) or default)` pattern silently rewrote
                # 0 → default because `0 or default` is `default` —
                # which broke full-bleed pages that explicitly set
                # `full_padding_pct: 0`, `pad_x: 0`, etc.). Falls back
                # to the Page model's default only when the key is
                # missing (v3 bundle) or non-numeric. Used for every
                # int column on Page so the round-trip is verbatim.
                def _opt_int(key, default):
                    v = p.get(key)
                    if v is None:
                        return default
                    try:
                        return int(v)
                    except (TypeError, ValueError):
                        return default
                db.session.add(Page(
                    slug=slug[:120],
                    title=(p.get("title") or slug)[:200],
                    blocks_json=p.get("blocks_json"),
                    template=(p.get("template") or "standard")[:16],
                    is_published=bool(p.get("is_published", True)),
                    is_private=bool(p.get("is_private", False)),
                    layout_key=(p.get("layout_key") or "custom")[:64],
                    bg_image_filename=p.get("bg_image_filename"),
                    bg_mode=(p.get("bg_mode") or "cover")[:16],
                    bg_tile_scale=_opt_int("bg_tile_scale", 100),
                    bg_color=p.get("bg_color"),
                    bg_color_dark=p.get("bg_color_dark"),
                    bg_color_dark_mode=(p.get("bg_color_dark_mode") or "same")[:16],
                    bg_dynamic_key=(p.get("bg_dynamic_key") or None),
                    bg_dynbg_config_json=p.get("bg_dynbg_config_json"),
                    width_mode=(p.get("width_mode") or "boxed")[:16],
                    max_width=_opt_int("max_width", 1160),
                    full_padding_pct=_opt_int("full_padding_pct", 4),
                    heading_color=p.get("heading_color"),
                    heading_align=(p.get("heading_align") or "auto")[:16],
                    heading_font=p.get("heading_font"),
                    subheading_color=p.get("subheading_color"),
                    subheading_font=p.get("subheading_font"),
                    pad_top=_opt_int("pad_top", 80),
                    pad_bottom=_opt_int("pad_bottom", 96),
                    pad_x=_opt_int("pad_x", 16),
                    section_gap=_opt_int("section_gap", 32),
                    block_margin_y=_opt_int("block_margin_y", 12),
                ))
            # Flush so the freshly-inserted pages have ids before we
            # look them up by slug for the homepage assignment below.
            db.session.flush()

        # 9b. Homepage designation — the export stores the homepage's
        # SLUG (not its ID, which isn't portable across installs). Now
        # that pages are restored, resolve the slug → new id and pin
        # SiteSetting.homepage_page_id. When the slug is missing or
        # doesn't match any imported page, leave the column whatever
        # the auto-seed wrote on the destination — the public `/`
        # stays 200 either way.
        _hp_slug = (payload.get("settings") or {}).get("homepage_page_slug")
        if _hp_slug:
            _hp_page = Page.query.filter_by(slug=_hp_slug).first()
            if _hp_page is not None:
                s.homepage_page_id = _hp_page.id

        # 10. IntergroupOfficer roster — replace wholesale with the
        # source's ids preserved so block references survive (the
        # `intergroup_member` block stores officer_id verbatim, so
        # renumbering would silently break every reference).
        if "intergroup_officers" in payload:
            for o in IntergroupOfficer.query.all():
                db.session.delete(o)
            db.session.flush()
            for o in (payload.get("intergroup_officers") or []):
                role = (o.get("role") or "").strip()
                if not role:
                    continue
                row = IntergroupOfficer(
                    role=role[:200],
                    name=(o.get("name") or None),
                    phone=(o.get("phone") or None),
                    email=(o.get("email") or None),
                    sort_order=int(o.get("sort_order") or 0),
                )
                src_id = o.get("id")
                if src_id is not None:
                    try: row.id = int(src_id)
                    except (TypeError, ValueError): pass
                db.session.add(row)

        # 11. Stories — replace by slug (preserving the source's
        # creator pointers is impossible cross-install, so created_by
        # is left null).
        from datetime import date as _date
        def _parse_date(v):
            if not v: return None
            try: return _date.fromisoformat(v)
            except (TypeError, ValueError): return None
        story_payload = payload.get("stories") or []
        if story_payload:
            slugs_to_replace = {st.get("slug") for st in story_payload if st.get("slug")}
            if slugs_to_replace:
                Story.query.filter(Story.slug.in_(slugs_to_replace)).delete(
                    synchronize_session=False)
                db.session.flush()
            for st in story_payload:
                title = (st.get("title") or "").strip()
                if not title:
                    continue
                db.session.add(Story(
                    slug=(st.get("slug") or None),
                    title=title[:255],
                    summary=st.get("summary"),
                    body=st.get("body"),
                    featured_image_filename=st.get("featured_image_filename"),
                    author_name=(st.get("author_name") or None),
                    author_bio=st.get("author_bio"),
                    sobriety_date=_parse_date(st.get("sobriety_date")),
                    story_date=_parse_date(st.get("story_date")),
                    is_featured=bool(st.get("is_featured")),
                    is_draft=bool(st.get("is_draft")),
                    is_archived=bool(st.get("is_archived")),
                ))

        # 12. Posts — preserve source ids so the slug_history entries
        # ride along with the right entity_id. Pending submissions
        # were already filtered out on the export side.
        from datetime import datetime as _dt
        def _parse_dt(v):
            if not v: return None
            try: return _dt.fromisoformat(v)
            except (TypeError, ValueError): return None
        post_payload = payload.get("posts") or []
        if post_payload:
            for po in Post.query.filter(Post.is_pending_review.is_(False)).all():
                db.session.delete(po)
            db.session.flush()
            for po in post_payload:
                title = (po.get("title") or "").strip()
                if not title:
                    continue
                row = Post(
                    slug=(po.get("slug") or None),
                    title=title[:255],
                    summary=po.get("summary"),
                    body=po.get("body"),
                    featured_image_filename=po.get("featured_image_filename"),
                    is_announcement=bool(po.get("is_announcement")),
                    is_event=bool(po.get("is_event")),
                    event_starts_at=_parse_dt(po.get("event_starts_at")),
                    event_ends_at=_parse_dt(po.get("event_ends_at")),
                    is_online=bool(po.get("is_online")),
                    location_name=po.get("location_name"),
                    location_address=po.get("location_address"),
                    google_maps_url=po.get("google_maps_url"),
                    website_url=po.get("website_url"),
                    website_label=po.get("website_label"),
                    zoom_meeting_id=po.get("zoom_meeting_id"),
                    zoom_passcode=po.get("zoom_passcode"),
                    zoom_url=po.get("zoom_url"),
                    contact_name=po.get("contact_name"),
                    contact_phone=po.get("contact_phone"),
                    contact_email=po.get("contact_email"),
                    is_draft=bool(po.get("is_draft")),
                    is_archived=bool(po.get("is_archived")),
                )
                src_id = po.get("id")
                if src_id is not None:
                    try: row.id = int(src_id)
                    except (TypeError, ValueError): pass
                db.session.add(row)

        # 13. Slug history — append-only redirect log. Filter to
        # entity types we ship so we don't drop in dangling references
        # to entities the bundle didn't carry.
        kept_types = {"post"}
        if payload.get("slug_history"):
            EntitySlugHistory.query.filter(
                EntitySlugHistory.entity_type.in_(kept_types)
            ).delete(synchronize_session=False)
            db.session.flush()
            for h in payload["slug_history"]:
                etype = (h.get("entity_type") or "").strip()
                if etype not in kept_types:
                    continue
                old_slug = (h.get("old_slug") or "").strip()
                new_slug = (h.get("new_slug") or "").strip()
                if not old_slug or not new_slug:
                    continue
                try: ent_id = int(h.get("entity_id"))
                except (TypeError, ValueError): continue
                db.session.add(EntitySlugHistory(
                    entity_type=etype[:16],
                    entity_id=ent_id,
                    old_slug=old_slug[:255],
                    new_slug=new_slug[:255],
                    changed_at=_parse_dt(h.get("changed_at")) or _dt.utcnow(),
                ))

        db.session.commit()

        # Final pass: index any assets that weren't already in the
        # MediaItem catalog (e.g. files referenced but never paired
        # with a media row on the source install). Hashes get
        # recomputed here so the local catalog is consistent.
        from . import _backfill_media
        _backfill_media(current_app)

        flash("Frontend bundle imported — content, navigation, layouts, fonts, icons, and assets are in place.", "success")
        return redirect(_safe_referrer() or url_for("main.frontend_dashboard"))
    finally:
        shutil.rmtree(staging, ignore_errors=True)


@bp.route("/uploads/<path:stored>")
@login_required
def upload_raw(stored):
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], stored)


# Back-compat alias for content saved before the admin moved under
# /tspro in 1.6.0 — Zoom Tech blocks (and any other rich-content area)
# stored image src values like "/uploads/<stored>" that resolved at the
# root when the admin lived there. Without this shim those URLs 404.
# Same login_required guard as /tspro/uploads/<stored> so anonymous
# visitors can't probe upload filenames.
@public_bp.route("/uploads/<path:stored>")
@login_required
def upload_raw_root(stored):
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], stored)


@public_bp.route("/pub/page-bg/<int:page_id>")
def public_page_bg(page_id):
    """Serve the configured background image for a Page. The bg is
    stored as a UUID-prefixed filename in UPLOAD_FOLDER; this route
    fronts it on a public path so the rendered <style> rule on /<slug>
    can reference it."""
    from .models import Page
    page = Page.query.get(page_id)
    if not page or not page.bg_image_filename or not page.is_published:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"],
                               page.bg_image_filename)


@public_bp.route("/pub/page-og-image/<int:page_id>")
def public_page_og_image(page_id):
    """Serve a Page's per-page Open Graph preview image. The page edit
    screen uploads it as a UUID-prefixed filename in UPLOAD_FOLDER;
    crawlers (Slack / iMessage / Facebook) fetch it anonymously through
    this route so visitors get a per-page link preview before they
    sign in. Falls back to a 404 when the page is unpublished or has
    no OG image set — the public detail route then renders the
    site-wide ``frontend_og_image_filename`` instead."""
    from .models import Page
    page = Page.query.get(page_id)
    if not page or not page.og_image_filename or not page.is_published:
        abort(404)
    response = send_from_directory(current_app.config["UPLOAD_FOLDER"],
                                   page.og_image_filename)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@public_bp.route("/pub/<path:filename>")
def public_file(filename):
    if ".." in filename or filename.startswith("/"):
        abort(404)
    m = MediaItem.query.filter_by(original_filename=filename)\
                       .order_by(MediaItem.created_at.desc()).first()
    if not m:
        abort(404)
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], m.stored_filename)
    if not os.path.isfile(path):
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], m.stored_filename,
                               download_name=m.original_filename)


@bp.route("/settings/pic-save", methods=["POST"])
@admin_required
def pic_save():
    s = _get_site_setting()
    s.pic_name = request.form.get("pic_name", "").strip() or None
    s.pic_email = request.form.get("pic_email", "").strip() or None
    s.pic_phone = request.form.get("pic_phone", "").strip() or None
    db.session.commit()
    flash("Public Information Chair updated", "success")
    return redirect(_safe_referrer() or url_for("main.index"))


@bp.route("/settings/intergroup-toggle", methods=["POST"])
@admin_required
def intergroup_toggle():
    s = _get_site_setting()
    s.intergroup_enabled = request.form.get("intergroup_enabled") == "1"
    db.session.commit()
    flash("Intergroup page " + ("enabled" if s.intergroup_enabled else "disabled"), "success")
    return redirect(_safe_referrer() or url_for("main.index"))


@bp.route("/settings/intergroup-module-toggle", methods=["POST"])
@admin_required
def intergroup_module_toggle():
    """Flip the umbrella Intergroup module on/off. Independent of
    ``intergroup_enabled`` (the page-level toggle for the Email page);
    this controls whether the Intergroup *subsection* of the sidebar
    appears at all.

    Side effect on enable: ensure the two libraries the section links to
    (``Intergroup Minutes`` and ``Intergroup Documents``) exist, so the
    sidebar's sub-entries show up immediately. Existing libraries with
    those names are left alone."""
    s = _get_site_setting()
    enabling = request.form.get("intergroup_module_enabled") == "1"
    s.intergroup_module_enabled = enabling
    if enabling:
        # Seed the two default Intergroup libraries flagged so the
        # permission gate (now keyed on ``is_intergroup``) and the
        # sidebar discovery query both pick them up immediately.
        for name in INTERGROUP_LIBRARY_NAMES:
            existing = Library.query.filter_by(name=name).first()
            if existing is None:
                db.session.add(Library(name=name, is_intergroup=True))
            elif not existing.is_intergroup:
                # Pre-existing rows that pre-date the column should
                # still resolve as Intergroup — backfill them here too.
                existing.is_intergroup = True
    db.session.commit()
    flash("Intergroup module " + ("enabled" if s.intergroup_module_enabled else "disabled"), "success")
    return redirect(_safe_referrer() or url_for("main.index"))


@public_bp.route("/site-branding/footer-logo")
def site_footer_logo():
    s = _get_site_setting()
    if not s.footer_logo_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], s.footer_logo_filename)


_HERO_BG_STYLES = {"frosty", "solid", "gradient", "image", "sinewave", "video", "dynamic"}
_HERO_VIDEO_SPEEDS = {50, 100, 150, 200, 300}
_HERO_HEADING_FONTS = {"fraunces", "inter"}
_HERO_IMAGE_MODES = {"cover", "tile"}
_HERO_BUTTON_STYLES = {"primary", "ghost"}
_HERO_PARTICLE_EFFECTS = ("off", "network", "stars", "fireflies", "bubbles", "snow", "waves", "orbits", "rain")


def _clamp_int(raw, lo, hi, default):
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


@bp.route("/frontend/toggle", methods=["POST"])
@admin_required
def frontend_toggle():
    """Flip the public-frontend on/off switch without touching content fields."""
    s = _get_site_setting()
    s.frontend_enabled = request.form.get("frontend_enabled") == "1"
    db.session.commit()
    flash(
        "Public frontend enabled" if s.frontend_enabled else "Public frontend disabled",
        "success"
    )
    return redirect(url_for("main.frontend_dashboard"))


@bp.route("/frontend/module-toggle", methods=["POST"])
@admin_required
def frontend_module_toggle():
    """Enable or disable the Web Frontend module entirely. When disabled the
    sidebar entry is hidden, the admin editor routes are blocked, and the
    public homepage stops serving regardless of the public-visibility toggle."""
    s = _get_site_setting()
    s.frontend_module_enabled = request.form.get("frontend_module_enabled") == "1"
    db.session.commit()
    flash(
        "Web Frontend module enabled" if s.frontend_module_enabled
        else "Web Frontend module disabled",
        "success",
    )
    # When disabling from the settings modal we stay on the current page;
    # when enabling, jump into the dashboard so the admin can keep going.
    if s.frontend_module_enabled:
        return redirect(url_for("main.frontend_dashboard"))
    return redirect(_safe_referrer() or url_for("main.index"))


ALERT_ICONS = {
    "", "info", "alert-triangle", "bell", "megaphone", "star", "heart",
    "calendar", "zap", "mail", "phone", "help-circle",
}
HEX_RE = None


def _apply_alert_form(s, form, prefix):
    """Save one alert-bar (top or header) from a POST form. prefix is 'top' or 'header'."""
    import re
    global HEX_RE
    if HEX_RE is None:
        HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")
    setattr(s, f"{prefix}_alert_enabled", form.get(f"{prefix}_alert_enabled") == "1")
    setattr(s, f"{prefix}_alert_message",
            (form.get(f"{prefix}_alert_message") or "").strip() or None)
    for color_col in ("bg_color", "text_color"):
        val = (form.get(f"{prefix}_alert_{color_col}") or "").strip()
        setattr(s, f"{prefix}_alert_{color_col}", val if HEX_RE.fullmatch(val) else None)
    icon = (form.get(f"{prefix}_alert_icon") or "").strip()
    setattr(s, f"{prefix}_alert_icon", icon if icon in ALERT_ICONS and icon else None)
    pos = (form.get(f"{prefix}_alert_icon_position") or "before").strip()
    setattr(s, f"{prefix}_alert_icon_position", pos if pos in ("before", "after") else "before")


@bp.route("/frontend/utility-bar-save", methods=["POST"])
@admin_required
def frontend_utility_bar_save():
    """Persist the utility-bar config: enable toggle, palette, left/right
    item lists (parsed out of repeating ``utility_<side>_*[]`` arrays),
    and the live-meeting-bar toggle."""
    import re
    from .utility_bar import parse_form_items, parse_form_payload, serialise_items
    s = _get_site_setting()
    s.utility_bar_enabled = request.form.get("utility_bar_enabled") == "1"
    s.utility_bar_live_meetings = request.form.get("utility_bar_live_meetings") == "1"
    hex_re = re.compile(r"#[0-9a-fA-F]{6}")
    for color_col in ("bg_color", "text_color"):
        val = (request.form.get(f"utility_bar_{color_col}") or "").strip()
        setattr(s, f"utility_bar_{color_col}", val if hex_re.fullmatch(val) else None)
    # JSON-payload submission (new shape, supports containers) takes
    # priority. When it's missing — older browsers, JS disabled, or a
    # programmatic POST — fall back to the legacy parallel-arrays
    # parser. The legacy parser doesn't know about containers; it
    # returns the flat item list it always has.
    left  = parse_form_payload(request.form, "left")
    right = parse_form_payload(request.form, "right")
    if left is None:  left  = parse_form_items(request.form, "left")
    if right is None: right = parse_form_items(request.form, "right")
    s.utility_bar_left_json = serialise_items(left)
    s.utility_bar_right_json = serialise_items(right)
    # Mobile-default selector — validate the posted value against the
    # items the admin just saved so a stale selector (e.g. they removed
    # the row that used to be the default) doesn't survive. Accepts
    # per-item ("left:N" / "right:N") or whole-side ("left" / "right").
    raw_default = (request.form.get("utility_bar_mobile_default") or "").strip().lower()
    chosen = ""
    if raw_default == "left" and left:
        chosen = "left"
    elif raw_default == "right" and right:
        chosen = "right"
    elif ":" in raw_default:
        side, _, idx = raw_default.partition(":")
        try: i = int(idx)
        except (TypeError, ValueError): i = -1
        if side == "left" and 0 <= i < len(left):   chosen = f"left:{i}"
        if side == "right" and 0 <= i < len(right): chosen = f"right:{i}"
    s.utility_bar_mobile_default = chosen or None
    db.session.commit()
    flash("Utility bar saved", "success")
    return redirect(url_for("main.frontend_header"))


@bp.route("/frontend/header-alert-save", methods=["POST"])
@admin_required
def frontend_header_alert_save():
    s = _get_site_setting()
    _apply_alert_form(s, request.form, "header")
    db.session.commit()
    flash("Under-header alert bar saved", "success")
    return redirect(url_for("main.frontend_header"))


@bp.route("/frontend/logo-save", methods=["POST"])
@admin_required
def frontend_logo_save():
    """Upload / clear / resize the public-frontend logo."""
    s = _get_site_setting()
    try:
        w = int(request.form.get("frontend_logo_width") or 40)
    except ValueError:
        w = 40
    s.frontend_logo_width = max(16, min(w, 200))
    if request.form.get("clear_frontend_logo") == "1":
        old = s.frontend_logo_filename
        s.frontend_logo_filename = None
        _cleanup_retired_asset(old)
    uploaded = request.files.get("frontend_logo")
    if uploaded and uploaded.filename:
        old = s.frontend_logo_filename
        stored, _original = _save_upload(uploaded)
        s.frontend_logo_filename = stored
        if old and old != stored:
            _cleanup_retired_asset(old)
    db.session.commit()
    flash("Logo saved", "success")
    return redirect(url_for("main.frontend_header"))


@bp.route("/frontend/header-save", methods=["POST"])
@admin_required
def frontend_header_save():
    """Persist header layout settings (width mode + sizing)."""
    s = _get_site_setting()
    mode = (request.form.get("frontend_header_width_mode") or "boxed").strip()
    s.frontend_header_width_mode = mode if mode in ("boxed", "full") else "boxed"
    try:
        mw = int(request.form.get("frontend_header_max_width") or 1160)
    except ValueError:
        mw = 1160
    s.frontend_header_max_width = max(600, min(mw, 2400))
    try:
        pp = int(request.form.get("frontend_header_padding_pct") or 5)
    except ValueError:
        pp = 5
    s.frontend_header_padding_pct = max(0, min(pp, 20))
    try:
        hh = int(request.form.get("frontend_header_height") or 72)
    except ValueError:
        hh = 72
    s.frontend_header_height = max(48, min(hh, 100))
    db.session.commit()
    flash("Header settings saved", "success")
    return redirect(url_for("main.frontend_dashboard"))


# ------------------------------------------------------------------
# Navigation CRUD (top-level items, mega-menu columns, mega-menu links)
# ------------------------------------------------------------------
import re as _re
_HEX = _re.compile(r"#[0-9a-fA-F]{6}")


@bp.route("/frontend/nav-appearance", methods=["POST"])
@admin_required
def frontend_nav_appearance_save():
    s = _get_site_setting()
    bg = (request.form.get("frontend_mega_bg_color") or "").strip()
    fg = (request.form.get("frontend_mega_text_color") or "").strip()
    if _HEX.fullmatch(bg): s.frontend_mega_bg_color = bg
    if _HEX.fullmatch(fg): s.frontend_mega_text_color = fg
    try:
        bl = int(request.form.get("frontend_mega_radius_bl") or 18)
        br = int(request.form.get("frontend_mega_radius_br") or 18)
    except ValueError:
        bl, br = 18, 18
    s.frontend_mega_radius_bl = max(0, min(bl, 60))
    s.frontend_mega_radius_br = max(0, min(br, 60))
    s.frontend_megamenu_animate = request.form.get("frontend_megamenu_animate") == "1"
    try:
        ms = int(request.form.get("frontend_megamenu_animate_ms") or 320)
    except ValueError:
        ms = 320
    s.frontend_megamenu_animate_ms = max(100, min(ms, 1500))
    # Panel-level fade (independent of the staggered link reveal).
    s.frontend_megamenu_panel_fade = request.form.get("frontend_megamenu_panel_fade") == "1"
    try:
        fms = int(request.form.get("frontend_megamenu_panel_fade_ms") or 180)
    except ValueError:
        fms = 180
    s.frontend_megamenu_panel_fade_ms = max(0, min(fms, 1500))
    # Mobile-only overrides — independent toggle + speeds applied via
    # the existing @media (max-width: 720px) breakpoint. Clamped to
    # the same ranges as the desktop sliders so a forged POST can't
    # push wild values into the JSON column.
    s.frontend_megamenu_animate_mobile = request.form.get("frontend_megamenu_animate_mobile") == "1"
    try:
        ams_m = int(request.form.get("frontend_megamenu_animate_mobile_ms") or 320)
    except ValueError:
        ams_m = 320
    s.frontend_megamenu_animate_mobile_ms = max(100, min(ams_m, 1500))
    try:
        fms_m = int(request.form.get("frontend_megamenu_panel_fade_mobile_ms") or 180)
    except ValueError:
        fms_m = 180
    s.frontend_megamenu_panel_fade_mobile_ms = max(0, min(fms_m, 1500))
    # Heading + link font-size overrides as integer percentages
    # (50 – 200, 100 = theme default). The sliders are centered at 100
    # so a value of exactly 100 is also treated as "no override" — it
    # persists as NULL so the theme's baked CSS base re-engages and
    # we don't store a redundant value. Out-of-range values clamp to
    # the band rather than being rejected.
    def _read_pct(field, lo, hi):
        raw = (request.form.get(field) or "").strip()
        if not raw:
            return None
        try:
            v = int(round(float(raw)))
        except ValueError:
            return None
        v = max(lo, min(v, hi))
        return None if v == 100 else v
    s.frontend_megamenu_heading_size    = _read_pct("frontend_megamenu_heading_size", 50, 200)
    s.frontend_megamenu_subheading_size = _read_pct("frontend_megamenu_subheading_size", 50, 200)
    db.session.commit()
    flash("Mega menu appearance saved", "success")
    return redirect(url_for("main.frontend_navigation"))


def _apply_nav_item_form(item, form):
    from .forms_registry import form_keys as _form_keys
    style = (form.get("style") or "text").strip()
    item.style = style if style in ("text", "button", "button-rounded", "two-line") else "text"
    item.url = (form.get("url") or "").strip() or None
    item.has_megamenu = form.get("has_megamenu") == "1"
    item.open_in_new_tab = form.get("open_in_new_tab") == "1"
    # form_trigger — when set to a registered key, the rendered link
    # opens that form's modal instead of (or in addition to) navigating.
    # Validate against the live registry so a stale value can't sneak
    # through if a form was retired.
    trig = (form.get("form_trigger") or "").strip()
    item.form_trigger = trig if trig in _form_keys() else None
    if item.style == "two-line":
        item.line1 = (form.get("line1") or "").strip() or None
        item.line2 = (form.get("line2") or "").strip() or None
        item.label = item.line1 or item.line2
    else:
        # The modal renders one `<input name="label">` per style pane (text,
        # button, button-rounded). The pane-toggle JS disables inactive
        # panes' inputs so only one value posts — but if that JS hasn't
        # run (or some other client submits the bare form), every pane's
        # label posts. Pick the one whose pane matches the chosen style;
        # fall back to the first non-empty value, then to None.
        labels = form.getlist("label") or []
        pane_index = {"text": 0, "button": 1, "button-rounded": 2}.get(item.style, 0)
        chosen = labels[pane_index] if pane_index < len(labels) else ""
        if not chosen.strip():
            chosen = next((l for l in labels if l.strip()), "")
        item.label = chosen.strip() or None
        item.line1 = item.line2 = None


@bp.route("/frontend/nav-item/new", methods=["POST"])
@admin_required
def frontend_nav_item_new():
    max_pos = db.session.query(db.func.max(FrontendNavItem.position)).scalar() or 0
    item = FrontendNavItem(position=max_pos + 1)
    _apply_nav_item_form(item, request.form)
    db.session.add(item)
    db.session.commit()
    flash("Nav item added", "success")
    return redirect(url_for("main.frontend_navigation"))


@bp.route("/frontend/nav-item/<int:nid>/edit", methods=["POST"])
@admin_required
def frontend_nav_item_edit(nid):
    item = db.session.get(FrontendNavItem, nid) or abort(404)
    _apply_nav_item_form(item, request.form)
    db.session.commit()
    flash("Nav item updated", "success")
    return redirect(_safe_referrer() or url_for("main.frontend_header"))


@bp.route("/frontend/nav-item/<int:nid>/delete", methods=["POST"])
@admin_required
def frontend_nav_item_delete(nid):
    item = db.session.get(FrontendNavItem, nid) or abort(404)
    db.session.delete(item)
    db.session.commit()
    flash("Nav item deleted", "success")
    return redirect(url_for("main.frontend_navigation"))


@bp.route("/frontend/nav-items/reorder", methods=["POST"])
@admin_required
def frontend_nav_item_reorder():
    payload = request.get_json(silent=True) or {}
    for pos, iid in enumerate(payload.get("order") or []):
        row = db.session.get(FrontendNavItem, int(iid)) if str(iid).isdigit() else None
        if row:
            row.position = pos
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/frontend/nav-item/<int:nid>/megamenu")
@admin_required
def frontend_nav_megamenu(nid):
    from .forms_registry import all_forms
    item = db.session.get(FrontendNavItem, nid) or abort(404)
    return render_template("frontend_nav_megamenu.html", item=item, site=_get_site_setting(),
                           form_registry_all=all_forms())


# ---- Columns ----
@bp.route("/frontend/nav-item/<int:nid>/column/new", methods=["POST"])
@admin_required
def frontend_nav_column_new(nid):
    item = db.session.get(FrontendNavItem, nid) or abort(404)
    max_pos = max([c.position for c in item.columns] + [-1]) + 1
    col = FrontendNavColumn(nav_item_id=item.id, position=max_pos,
                            heading=(request.form.get("heading") or "New column").strip())
    db.session.add(col)
    db.session.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        html = render_template("_nav_megacol.html", col=col)
        return jsonify(ok=True, id=col.id, html=html)
    return redirect(url_for("main.frontend_nav_megamenu", nid=item.id))


@bp.route("/frontend/nav-column/<int:cid>/edit", methods=["POST"])
@admin_required
def frontend_nav_column_edit(cid):
    col = db.session.get(FrontendNavColumn, cid) or abort(404)
    col.heading = (request.form.get("heading") or "").strip() or None
    db.session.commit()
    return redirect(url_for("main.frontend_nav_megamenu", nid=col.nav_item_id))


@bp.route("/frontend/nav-column/<int:cid>/delete", methods=["POST"])
@admin_required
def frontend_nav_column_delete(cid):
    col = db.session.get(FrontendNavColumn, cid) or abort(404)
    nid = col.nav_item_id
    db.session.delete(col)
    db.session.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True)
    return redirect(url_for("main.frontend_nav_megamenu", nid=nid))


@bp.route("/frontend/nav-item/<int:nid>/columns/reorder", methods=["POST"])
@admin_required
def frontend_nav_columns_reorder(nid):
    item = db.session.get(FrontendNavItem, nid) or abort(404)
    payload = request.get_json(silent=True) or {}
    valid_ids = {c.id for c in item.columns}
    for pos, cid in enumerate(payload.get("order") or []):
        try:
            cid_int = int(cid)
        except (TypeError, ValueError):
            continue
        if cid_int not in valid_ids:
            continue
        col = db.session.get(FrontendNavColumn, cid_int)
        if col:
            col.position = pos
    db.session.commit()
    return jsonify(ok=True)


# ---- Links (blocks) ----
from .icons import icon_names as _icon_names
_NAV_BLOCK_KINDS = {"link", "title", "button", "section", "search", "admin_login"}
_NAV_BUTTON_STYLES = {"pill", "rounded"}
_NAV_LINK_SIZES = {"small", "large"}
# `admin_login` is special — the renderer ignores the stored label/url
# and swaps in "Login" → /auth/login for anonymous visitors, or
# "Back to TS Pro dashboard" → /tspro for signed-in users. Storage
# defaults so admin-side UI placeholders have something to show.
_NAV_DEFAULT_LABEL = {
    "link": "New link", "title": "Section title",
    "button": "Call to action", "section": "Group heading",
    "search": "Search…",
    "admin_login": "Login",
}
_HEX_COLOR_RE = _re.compile(r"^#[0-9a-fA-F]{3,8}$")
_CUSTOM_ICON_RE = _re.compile(r"^custom:(\d+)$")
_ICON_SIZE_MIN = 12
_ICON_SIZE_MAX = 64


def _sanitize_icon_color(raw):
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    return s if _HEX_COLOR_RE.match(s) else None


def _sanitize_icon_name(raw):
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    m = _CUSTOM_ICON_RE.match(s)
    if m:
        cid = int(m.group(1))
        if db.session.get(CustomIcon, cid):
            return s
        return None
    return s if s in _icon_names() else None


def _sanitize_icon_size(raw):
    if raw in (None, ""):
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if n < _ICON_SIZE_MIN or n > _ICON_SIZE_MAX:
        return None
    return n


def _apply_nav_link_form(link, form):
    kind = (form.get("kind") or link.kind or "link").strip()
    link.kind = kind if kind in _NAV_BLOCK_KINDS else "link"
    raw_label = (form.get("label") or "").strip()
    if link.kind == "search":
        # `label` doubles as the search input's placeholder text.
        link.label = raw_label or link.label or "Search…"
    else:
        link.label = raw_label or link.label
    if link.kind in ("link", "button"):
        link.url = (form.get("url") or "").strip() or None
        link.open_in_new_tab = form.get("open_in_new_tab") == "1"
        link.icon_before = _sanitize_icon_name(form.get("icon_before"))
        link.icon_after = _sanitize_icon_name(form.get("icon_after"))
        link.icon_before_color = _sanitize_icon_color(form.get("icon_before_color"))
        link.icon_after_color = _sanitize_icon_color(form.get("icon_after_color"))
        link.icon_before_size = _sanitize_icon_size(form.get("icon_before_size"))
        link.icon_after_size = _sanitize_icon_size(form.get("icon_after_size"))
    else:
        link.url = None
        link.open_in_new_tab = False
        link.icon_before = None
        link.icon_after = None
        link.icon_before_color = None
        link.icon_after_color = None
        link.icon_before_size = None
        link.icon_after_size = None
    if link.kind == "link":
        # The legacy small/large radio is gone; per-link size is now a
        # toggle + percentage slider that scopes a custom scale to one
        # link. Toggle off → no override (NULL); toggle on → clamp the
        # slider value to 50–200, treat exactly 100 as no-override.
        link.link_size = None
        if form.get("link_size_override") == "1":
            try:
                pct = int(round(float(form.get("link_size_pct") or 100)))
            except (TypeError, ValueError):
                pct = 100
            pct = max(50, min(pct, 200))
            link.link_size_pct = None if pct == 100 else pct
        else:
            link.link_size_pct = None
        link.override_color = form.get("override_color") == "1"
        link.custom_color = _sanitize_icon_color(form.get("custom_color")) if link.override_color else None
    else:
        link.link_size = None
        link.link_size_pct = None
        link.override_color = False
        link.custom_color = None
    if link.kind == "button":
        bs = (form.get("button_style") or "pill").strip()
        link.button_style = bs if bs in _NAV_BUTTON_STYLES else "pill"
    else:
        link.button_style = "pill"
    # form_trigger applies to anything that renders as a clickable
    # element on the public site (link / button). Other kinds keep
    # NULL — a "title" or "section" divider can't be clicked anyway.
    if link.kind in ("link", "button"):
        from .forms_registry import form_keys as _form_keys
        trig = (form.get("form_trigger") or "").strip()
        link.form_trigger = trig if trig in _form_keys() else None
    else:
        link.form_trigger = None


@bp.route("/frontend/nav-column/<int:cid>/link/new", methods=["POST"])
@admin_required
def frontend_nav_link_new(cid):
    col = db.session.get(FrontendNavColumn, cid) or abort(404)
    max_pos = max([l.position for l in col.links] + [-1]) + 1
    kind = (request.form.get("kind") or "link").strip()
    if kind not in _NAV_BLOCK_KINDS:
        kind = "link"
    link = FrontendNavLink(
        column_id=col.id, position=max_pos, kind=kind,
        label=_NAV_DEFAULT_LABEL[kind],
    )
    _apply_nav_link_form(link, request.form)
    db.session.add(link)
    db.session.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        html = render_template("_nav_megalink.html", link=link)
        return jsonify(ok=True, id=link.id, html=html)
    return redirect(url_for("main.frontend_nav_megamenu", nid=col.nav_item_id))


@bp.route("/frontend/nav-link/<int:lid>/edit", methods=["POST"])
@admin_required
def frontend_nav_link_edit(lid):
    link = db.session.get(FrontendNavLink, lid) or abort(404)
    _apply_nav_link_form(link, request.form)
    db.session.commit()
    return redirect(url_for("main.frontend_nav_megamenu", nid=link.column.nav_item_id))


@bp.route("/frontend/nav-link/<int:lid>/delete", methods=["POST"])
@admin_required
def frontend_nav_link_delete(lid):
    link = db.session.get(FrontendNavLink, lid) or abort(404)
    nid = link.column.nav_item_id
    db.session.delete(link)
    db.session.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True)
    return redirect(url_for("main.frontend_nav_megamenu", nid=nid))


@bp.route("/frontend/nav/<int:nid>/megamenu/save-all", methods=["POST"])
@admin_required
def frontend_nav_megamenu_save_all(nid):
    item = db.session.get(FrontendNavItem, nid) or abort(404)
    payload = request.get_json(silent=True) or {}
    valid_ids = {l.id for col in item.columns for l in col.links}
    updated = 0
    for block in payload.get("blocks") or []:
        try:
            lid = int(block.get("id"))
        except (TypeError, ValueError):
            continue
        if lid not in valid_ids:
            continue
        link = db.session.get(FrontendNavLink, lid)
        if not link:
            continue
        form = {k: ("1" if v is True else "" if v is False else ("" if v is None else str(v)))
                for k, v in block.items() if k != "id"}
        _apply_nav_link_form(link, form)
        updated += 1
    db.session.commit()
    return jsonify(ok=True, updated=updated)


@bp.route("/frontend/nav-column/<int:cid>/links/reorder", methods=["POST"])
@admin_required
def frontend_nav_links_reorder(cid):
    col = db.session.get(FrontendNavColumn, cid) or abort(404)
    payload = request.get_json(silent=True) or {}
    valid_ids = {l.id for l in col.links}
    for pos, lid in enumerate(payload.get("order") or []):
        try:
            lid_int = int(lid)
        except (TypeError, ValueError):
            continue
        if lid_int not in valid_ids:
            continue
        link = db.session.get(FrontendNavLink, lid_int)
        if link:
            link.position = pos
    db.session.commit()
    return jsonify(ok=True)


# ---- Custom icon uploads (mega-menu icon picker) ----
_CUSTOM_ICON_MAX_BYTES = 512 * 1024  # 512 KB per icon
_CUSTOM_ICON_EXT_MIME = {".svg": "image/svg+xml", ".png": "image/png"}
_SVG_SANITIZE_PATTERNS = (
    _re.compile(r"<script\b[^>]*>.*?</script\s*>", _re.IGNORECASE | _re.DOTALL),
    _re.compile(r"<script\b[^>]*/\s*>", _re.IGNORECASE),
    _re.compile(r"\s+on\w+\s*=\s*\"[^\"]*\"", _re.IGNORECASE),
    _re.compile(r"\s+on\w+\s*=\s*'[^']*'", _re.IGNORECASE),
    _re.compile(r"\s+on\w+\s*=\s*[^\s>]+", _re.IGNORECASE),
    _re.compile(r"(href|xlink:href)\s*=\s*\"\s*javascript:[^\"]*\"", _re.IGNORECASE),
    _re.compile(r"(href|xlink:href)\s*=\s*'\s*javascript:[^']*'", _re.IGNORECASE),
)


def _sanitize_svg(text_bytes):
    try:
        s = text_bytes.decode("utf-8")
    except UnicodeDecodeError:
        s = text_bytes.decode("utf-8", errors="ignore")
    for pat in _SVG_SANITIZE_PATTERNS:
        s = pat.sub("", s)
    return s.encode("utf-8")


# Affinity Designer / Serif tools export with `width="100%" height="100%"`
# on the root <svg>, which leaves the file with no intrinsic pixel size —
# only an aspect ratio from the viewBox. An <img> pointing at such a file
# collapses to 0 width when placed inside a flex/grid item without a
# definite parent width. The normalizer below rewrites the root tag's
# width + height to the viewBox dimensions so the SVG has real intrinsic
# pixels and renders the same in any container.
_SVG_ROOT_TAG_RE = _re.compile(r'<svg\b([^>]*)>', _re.IGNORECASE)
_SVG_VIEWBOX_RE = _re.compile(
    r'viewBox\s*=\s*["\']\s*([-\d.eE]+)\s+([-\d.eE]+)\s+([-\d.eE]+)\s+([-\d.eE]+)\s*["\']',
    _re.IGNORECASE,
)
_SVG_WIDTH_PCT_RE = _re.compile(r'(\bwidth\s*=\s*)(["\'])100%\2', _re.IGNORECASE)
_SVG_HEIGHT_PCT_RE = _re.compile(r'(\bheight\s*=\s*)(["\'])100%\2', _re.IGNORECASE)


def _normalize_svg_dimensions(svg_bytes):
    """Conservative rewrite: only fires when the root <svg> has BOTH
    width="100%" AND height="100%" AND a parseable viewBox. Partial or
    pixel-valued dimensions, inner <svg> elements, and viewBox-less files
    are left untouched."""
    try:
        s = svg_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return svg_bytes
    m = _SVG_ROOT_TAG_RE.search(s)
    if not m:
        return svg_bytes
    attrs = m.group(1)
    if not (_SVG_WIDTH_PCT_RE.search(attrs) and _SVG_HEIGHT_PCT_RE.search(attrs)):
        return svg_bytes
    vb = _SVG_VIEWBOX_RE.search(attrs)
    if not vb:
        return svg_bytes
    try:
        w = float(vb.group(3))
        h = float(vb.group(4))
    except (ValueError, TypeError):
        return svg_bytes
    if w <= 0 or h <= 0:
        return svg_bytes
    def _fmt(n):
        return str(int(n)) if n == int(n) else str(n)
    new_attrs = _SVG_WIDTH_PCT_RE.sub(rf'\g<1>"{_fmt(w)}"', attrs)
    new_attrs = _SVG_HEIGHT_PCT_RE.sub(rf'\g<1>"{_fmt(h)}"', new_attrs)
    return (s[:m.start(1)] + new_attrs + s[m.end(1):]).encode("utf-8")


def _custom_icon_json(ci):
    return {
        "id": ci.id, "name": ci.name, "mime_type": ci.mime_type,
        "url": f"/pub/icon/{ci.id}",
        "ref": f"custom:{ci.id}",
    }


@bp.route("/frontend/custom-icons.json")
@admin_required
def frontend_custom_icons_list():
    rows = CustomIcon.query.order_by(CustomIcon.created_at.desc()).all()
    return jsonify(icons=[_custom_icon_json(ci) for ci in rows])


@bp.route("/frontend/custom-icon/upload", methods=["POST"])
@admin_required
def frontend_custom_icon_upload():
    uploaded = request.files.get("icon")
    if not uploaded or not uploaded.filename:
        return jsonify(ok=False, error="No file uploaded"), 400
    original = secure_filename(uploaded.filename) or "icon"
    ext = os.path.splitext(original)[1].lower()
    if ext not in _CUSTOM_ICON_EXT_MIME:
        return jsonify(ok=False, error="Only SVG and PNG icons are allowed"), 400
    data = uploaded.read(_CUSTOM_ICON_MAX_BYTES + 1)
    if len(data) > _CUSTOM_ICON_MAX_BYTES:
        return jsonify(ok=False, error="Icon is larger than 512 KB"), 400
    if ext == ".svg":
        data = _sanitize_svg(data)
        data = _normalize_svg_dimensions(data)
    stored = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
    with open(path, "wb") as f:
        f.write(data)
    name = os.path.splitext(original)[0][:120] or "icon"
    ci = CustomIcon(
        name=name, stored_filename=stored,
        mime_type=_CUSTOM_ICON_EXT_MIME[ext],
        size_bytes=len(data),
        uploaded_by=getattr(current_user, "id", None),
    )
    db.session.add(ci)
    db.session.commit()
    return jsonify(ok=True, icon=_custom_icon_json(ci))


@bp.route("/frontend/custom-icon/<int:cid>/delete", methods=["POST"])
@admin_required
def frontend_custom_icon_delete(cid):
    ci = db.session.get(CustomIcon, cid) or abort(404)
    ref = f"custom:{cid}"
    # Clear any nav-link references so we don't leave dangling pointers.
    FrontendNavLink.query.filter_by(icon_before=ref).update({"icon_before": None, "icon_before_color": None, "icon_before_size": None})
    FrontendNavLink.query.filter_by(icon_after=ref).update({"icon_after": None, "icon_after_color": None, "icon_after_size": None})
    _delete_upload(ci.stored_filename)
    db.session.delete(ci)
    db.session.commit()
    return jsonify(ok=True)


@public_bp.route("/pub/icon/<int:cid>")
def public_custom_icon(cid):
    ci = db.session.get(CustomIcon, cid)
    if not ci:
        abort(404)
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    path = os.path.join(upload_dir, ci.stored_filename)
    if not os.path.isfile(path):
        abort(404)
    response = send_from_directory(upload_dir, ci.stored_filename, mimetype=ci.mime_type)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


# ---- Custom fonts (uploaded files + Google Fonts links) ----

_CUSTOM_FONT_MAX_BYTES = 4 * 1024 * 1024  # 4 MB
_CUSTOM_FONT_EXT_MIME = {
    ".ttf":   "font/ttf",
    ".otf":   "font/otf",
    ".woff":  "font/woff",
    ".woff2": "font/woff2",
}


def _clear_font_overrides_for(fid):
    """Remove any heading/body role override that pointed at this font so a
    deleted font doesn't leave the public site rendering an unknown family."""
    import json as _json
    s = _get_site_setting()
    raw = (s.frontend_fonts_json or "").strip()
    if not raw:
        return
    try:
        ov = _json.loads(raw)
    except (ValueError, TypeError):
        return
    ref = f"custom:{fid}"
    changed = False
    for role in list(ov.keys()):
        if ov[role] == ref:
            del ov[role]
            changed = True
    if changed:
        s.frontend_fonts_json = _json.dumps(ov) if ov else None


@bp.route("/frontend/custom-font/upload", methods=["POST"])
@admin_required
def frontend_custom_font_upload():
    uploaded = request.files.get("font")
    if not uploaded or not uploaded.filename:
        flash("No font file uploaded", "error")
        return redirect(url_for("main.frontend_fonts_icons"))
    original = secure_filename(uploaded.filename) or "font"
    ext = os.path.splitext(original)[1].lower()
    if ext not in _CUSTOM_FONT_EXT_MIME:
        flash("Only TTF, OTF, WOFF, and WOFF2 fonts are allowed", "error")
        return redirect(url_for("main.frontend_fonts_icons"))
    data = uploaded.read(_CUSTOM_FONT_MAX_BYTES + 1)
    if len(data) > _CUSTOM_FONT_MAX_BYTES:
        flash("Font is larger than 4 MB", "error")
        return redirect(url_for("main.frontend_fonts_icons"))
    stored = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
    with open(path, "wb") as f:
        f.write(data)
    base = os.path.splitext(original)[0][:120] or "Font"
    name = (request.form.get("name") or "").strip()[:120] or base
    family = (request.form.get("family") or "").strip()[:120] or base
    cf = CustomFont(
        name=name, family=family, source="upload",
        stored_filename=stored,
        mime_type=_CUSTOM_FONT_EXT_MIME[ext],
        size_bytes=len(data),
        uploaded_by=getattr(current_user, "id", None),
    )
    db.session.add(cf)
    db.session.commit()
    flash(f"Font '{name}' uploaded", "success")
    return redirect(url_for("main.frontend_fonts_icons"))


@bp.route("/frontend/custom-font/google", methods=["POST"])
@admin_required
def frontend_custom_font_google():
    """Add a font from a Google Fonts CSS URL. We do NOT serve anything
    from Google at runtime — we fetch the CSS, download every referenced
    woff2 binary to local storage, rewrite the @font-face src URLs to
    point at our own /site-branding/font-asset/<name> route, and persist
    the rewritten CSS as the CustomFont's stored file."""
    import json as _json
    import requests as _requests
    url = (request.form.get("google_url") or "").strip()
    if not url.startswith("https://fonts.googleapis.com/"):
        flash("Paste a Google Fonts CSS URL (https://fonts.googleapis.com/…)", "error")
        return redirect(url_for("main.frontend_fonts_icons"))
    if len(url) > 500:
        flash("Google Fonts URL is too long (max 500 chars)", "error")
        return redirect(url_for("main.frontend_fonts_icons"))
    m = _re.search(r"family=([^&:]+)", url)
    if not m:
        flash("Couldn't parse a font family from that URL", "error")
        return redirect(url_for("main.frontend_fonts_icons"))
    family = m.group(1).replace("+", " ").strip()[:120] or "Font"
    name = (request.form.get("name") or "").strip()[:120] or family

    # Pretend to be a modern browser so Google's CSS endpoint serves the
    # woff2 variant rather than the ttf-fallback for ancient browsers.
    ua = ("Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0")
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    try:
        css_resp = _requests.get(url, headers={"User-Agent": ua}, timeout=15)
        css_resp.raise_for_status()
        css_text = css_resp.text
    except Exception as e:  # noqa: BLE001
        flash(f"Couldn't fetch the Google Fonts CSS: {e}", "error")
        return redirect(url_for("main.frontend_fonts_icons"))

    # Find every gstatic font URL referenced by the CSS. There's typically
    # one per @font-face block; multi-weight families produce several.
    font_urls = list(dict.fromkeys(_re.findall(
        r"url\((https://fonts\.gstatic\.com/[^)\s]+)\)", css_text)))
    if not font_urls:
        flash("Google Fonts CSS didn't reference any font files — try a different URL.", "error")
        return redirect(url_for("main.frontend_fonts_icons"))

    asset_files = []
    total_bytes = 0
    try:
        for furl in font_urls:
            ext = os.path.splitext(furl.split("?", 1)[0])[1].lower() or ".woff2"
            if ext not in (".woff2", ".woff", ".ttf", ".otf"):
                ext = ".woff2"
            stored = f"{uuid.uuid4().hex}{ext}"
            r = _requests.get(furl, headers={"User-Agent": ua}, timeout=20)
            r.raise_for_status()
            data = r.content
            if len(data) > _CUSTOM_FONT_MAX_BYTES:
                raise ValueError(f"font file from {furl} exceeds 4 MB limit")
            with open(os.path.join(upload_dir, stored), "wb") as f:
                f.write(data)
            asset_files.append({"url": furl, "stored": stored})
            total_bytes += len(data)
            css_text = css_text.replace(
                furl,
                url_for("public.site_custom_font_asset", asset=stored, _external=False),
            )
    except Exception as e:  # noqa: BLE001
        # Roll back any partially-saved binaries before bailing.
        for af in asset_files:
            _delete_upload(af["stored"])
        flash(f"Couldn't download a font file: {e}", "error")
        return redirect(url_for("main.frontend_fonts_icons"))

    # Persist the rewritten CSS as the CustomFont's primary stored file.
    css_stored = f"{uuid.uuid4().hex}.css"
    with open(os.path.join(upload_dir, css_stored), "w", encoding="utf-8") as f:
        f.write(css_text)
    total_bytes += len(css_text.encode("utf-8"))

    cf = CustomFont(
        name=name, family=family, source="google",
        google_url=url,
        stored_filename=css_stored,
        asset_files_json=_json.dumps([af["stored"] for af in asset_files]),
        mime_type="text/css",
        size_bytes=total_bytes,
        uploaded_by=getattr(current_user, "id", None),
    )
    db.session.add(cf)
    db.session.commit()
    flash(f"Font '{name}' downloaded and installed locally ({len(asset_files)} file{'s' if len(asset_files) != 1 else ''}, {round(total_bytes/1024)} KB).", "success")
    return redirect(url_for("main.frontend_fonts_icons"))


@bp.route("/frontend/custom-font/<int:fid>/delete", methods=["POST"])
@admin_required
def frontend_custom_font_delete(fid):
    import json as _json
    cf = db.session.get(CustomFont, fid) or abort(404)
    _clear_font_overrides_for(fid)
    if cf.stored_filename:
        _delete_upload(cf.stored_filename)
    if cf.asset_files_json:
        try:
            for stored in _json.loads(cf.asset_files_json):
                if stored:
                    _delete_upload(stored)
        except (ValueError, TypeError):
            pass
    db.session.delete(cf)
    db.session.commit()
    flash("Font deleted", "success")
    return redirect(url_for("main.frontend_fonts_icons"))


_FONT_ASSET_EXTS = {".woff2", ".woff", ".ttf", ".otf", ".css"}


@public_bp.route("/pub/font/<int:fid>")
def public_custom_font(fid):
    """Serves the primary stored file for a CustomFont:
        - source=upload: the font binary (TTF/OTF/WOFF/WOFF2)
        - source=google: the rewritten CSS file with @font-face blocks
          referencing locally-stored binaries (served by site_custom_font_asset)
    """
    cf = db.session.get(CustomFont, fid)
    if not cf or not cf.stored_filename:
        abort(404)
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    path = os.path.join(upload_dir, cf.stored_filename)
    if not os.path.isfile(path):
        abort(404)
    mimetype = cf.mime_type or ("text/css" if cf.source == "google" else None)
    response = send_from_directory(upload_dir, cf.stored_filename, mimetype=mimetype)
    response.headers["Cache-Control"] = "public, max-age=86400"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@public_bp.route("/site-branding/font-asset/<asset>")
def site_custom_font_asset(asset):
    """Serves the locally-cached font binaries that Google-Fonts CustomFonts
    point at. We validate the filename extension and check that the asset
    is referenced by some CustomFont.asset_files_json so this can't be
    used to read arbitrary files out of the uploads directory."""
    import json as _json
    name = secure_filename(asset)
    if not name or os.path.splitext(name)[1].lower() not in _FONT_ASSET_EXTS:
        abort(404)
    # Confirm this filename was registered as a font asset by some CustomFont.
    rows = CustomFont.query.filter(CustomFont.asset_files_json.isnot(None)).all()
    referenced = False
    for cf in rows:
        try:
            if name in (_json.loads(cf.asset_files_json) or []):
                referenced = True
                break
        except (ValueError, TypeError):
            continue
    if not referenced:
        abort(404)
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    path = os.path.join(upload_dir, name)
    if not os.path.isfile(path):
        abort(404)
    response = send_from_directory(upload_dir, name)
    response.headers["Cache-Control"] = "public, max-age=86400"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@bp.route("/frontend/")
@admin_required
def frontend_dashboard():
    s = _get_site_setting()
    return render_template("frontend_dashboard.html", site=s)


@bp.route("/frontend/branding")
@admin_required
def frontend_branding():
    s = _get_site_setting()
    return render_template("frontend_branding.html", site=s)


@bp.route("/frontend/fonts-icons")
@admin_required
def frontend_fonts_icons():
    s = _get_site_setting()
    custom_icons = CustomIcon.query.order_by(CustomIcon.created_at.desc()).all()
    custom_fonts = CustomFont.query.order_by(CustomFont.created_at.desc()).all()
    return render_template("frontend_fonts_icons.html",
                           site=s, custom_icons=custom_icons, custom_fonts=custom_fonts)


@bp.route("/frontend/forms")
@admin_required
def frontend_forms():
    """Forms index — lists every registered public form. The list is
    populated from ``app/forms_registry.py``; future forms join the
    list automatically by adding an entry there. Each registry entry
    declares an ``enabled_setting`` column; the index reads its
    current value off SiteSetting and exposes an inline toggle."""
    from .forms_registry import all_forms
    s = _get_site_setting()
    forms = []
    for f in all_forms():
        enabled = True
        col = f.get("enabled_setting")
        if col:
            enabled = bool(getattr(s, col, True))
        forms.append({**f, "enabled": enabled})
    return render_template("frontend_forms.html", site=s, forms=forms)


@bp.route("/frontend/forms/<key>/toggle", methods=["POST"])
@admin_required
def frontend_form_toggle(key):
    """Inline enable/disable toggle for a registered form. Posts JSON
    in / returns JSON out so the Forms admin's per-row switch can
    fire-and-forget. The form's registry entry must declare an
    ``enabled_setting`` column for this to be meaningful — without
    one we 404 since there's nothing to flip."""
    from .forms_registry import form_by_key
    entry = form_by_key(key)
    if entry is None or not entry.get("enabled_setting"):
        abort(404)
    payload = request.get_json(silent=True) or {}
    s = _get_site_setting()
    enabled = bool(payload.get("enabled"))
    setattr(s, entry["enabled_setting"], enabled)
    db.session.commit()
    return jsonify(key=key, enabled=enabled)


@bp.route("/frontend/forms/submission", methods=["GET", "POST"])
@admin_required
def frontend_form_submission():
    """Settings page for the public Submission Form. GET renders the
    settings form; POST persists every column on SiteSetting that
    drives the form (toggle, copy, success message, allowed types,
    submit button label, recipients)."""
    s = _get_site_setting()
    if request.method == "POST":
        s.submission_form_enabled = request.form.get("submission_form_enabled") == "1"
        s.submission_to = (request.form.get("submission_to") or "").strip()[:500] or None
        s.submission_form_heading = (request.form.get("submission_form_heading") or "").strip()[:200] or None
        s.submission_form_subheading = (request.form.get("submission_form_subheading") or "").strip()[:500] or None
        s.submission_form_modal_heading = (request.form.get("submission_form_modal_heading") or "").strip()[:200] or None
        s.submission_form_intro = (request.form.get("submission_form_intro") or "").strip() or None
        s.submission_form_success_message = (request.form.get("submission_form_success_message") or "").strip()[:500] or None
        allowed = (request.form.get("submission_form_allowed_types") or "both").strip().lower()
        if allowed not in ("both", "announcements", "events"):
            allowed = "both"
        s.submission_form_allowed_types = allowed
        s.submission_form_submit_label = (request.form.get("submission_form_submit_label") or "").strip()[:100] or None
        db.session.commit()
        flash("Submission form settings saved", "success")
        return redirect(url_for("main.frontend_form_submission"))
    return render_template("frontend_form_submission.html", site=s)


@bp.route("/frontend/forms/contact", methods=["GET", "POST"])
@admin_required
def frontend_form_contact():
    """Settings page for the public Contact Form. GET renders the
    settings form; POST persists every column on SiteSetting that
    drives the page (toggle, recipient, copy, success message, field
    behaviour, submit-button label). Submissions themselves live on
    the dedicated Contact Form admin section so this page stays
    purely about configuration."""
    s = _get_site_setting()
    if request.method == "POST":
        s.contact_form_enabled = request.form.get("contact_form_enabled") == "1"
        s.contact_form_to = (request.form.get("contact_form_to") or "").strip()[:500] or None
        s.contact_form_success_message = (request.form.get("contact_form_success_message") or "").strip()[:500] or None
        s.contact_form_submit_label = (request.form.get("contact_form_submit_label") or "").strip()[:100] or None
        s.contact_form_subject_required = request.form.get("contact_form_subject_required") == "1"
        s.contact_form_show_phone = request.form.get("contact_form_show_phone") == "1"
        db.session.commit()
        flash("Contact form settings saved", "success")
        return redirect(url_for("main.frontend_form_contact"))
    return render_template("frontend_form_contact.html", site=s)


@bp.route("/frontend/contact-template/save", methods=["POST"])
@admin_required
def frontend_contact_template_save():
    """Persist the page-level configuration for the public /contact
    page: heading / subheading / Markdown intro plus the per-channel
    PIC visibility toggles. The Forms admin handles form-mechanic
    settings (recipient, fields, success message, bot protection);
    this surface is purely about how the page looks and which PIC
    channels appear in the side panel."""
    s = _get_site_setting()
    s.contact_form_heading = (request.form.get("contact_form_heading") or "").strip()[:200] or None
    s.contact_form_subheading = (request.form.get("contact_form_subheading") or "").strip()[:500] or None
    s.contact_form_intro = (request.form.get("contact_form_intro") or "").strip() or None
    s.contact_form_show_pic_name = request.form.get("contact_form_show_pic_name") == "1"
    s.contact_form_show_pic_email = request.form.get("contact_form_show_pic_email") == "1"
    s.contact_form_show_pic_phone = request.form.get("contact_form_show_pic_phone") == "1"
    # Container-width controls — mirror the events/announcements/stories
    # list endpoints. Width mode falls through to the model default on
    # an out-of-range value rather than blanking it; numeric inputs
    # clamp to the schema bounds.
    width = (request.form.get("contact_form_width_mode") or "").strip()
    if width in ("boxed", "full"):
        s.contact_form_width_mode = width
    if "contact_form_max_width" in request.form:
        try:
            max_w = int(request.form.get("contact_form_max_width") or 1160)
        except ValueError:
            max_w = 1160
        s.contact_form_max_width = max(640, min(2400, max_w))
    if "contact_form_padding_pct" in request.form:
        try:
            pad = int(request.form.get("contact_form_padding_pct") or 5)
        except ValueError:
            pad = 5
        s.contact_form_padding_pct = max(0, min(20, pad))
    db.session.commit()
    flash("Contact page saved", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/404")
@admin_required
def frontend_404():
    """Customize the public 404 page (heading, subheading, CTA, illustration).
    Sensible defaults render when fields are blank — see frontend/404.html."""
    s = _get_site_setting()
    return render_template("frontend_404.html", site=s)


@bp.route("/frontend/404/save", methods=["POST"])
@admin_required
def frontend_404_save():
    s = _get_site_setting()
    s.frontend_404_heading = (request.form.get("frontend_404_heading") or "").strip()[:200] or None
    s.frontend_404_subheading = (request.form.get("frontend_404_subheading") or "").strip() or None
    s.frontend_404_cta_label = (request.form.get("frontend_404_cta_label") or "").strip()[:120] or None
    s.frontend_404_cta_url = (request.form.get("frontend_404_cta_url") or "").strip()[:500] or None
    if request.form.get("clear_404_image") == "1":
        old = s.frontend_404_image_filename
        s.frontend_404_image_filename = None
        _cleanup_retired_asset(old)
    uploaded = request.files.get("frontend_404_image")
    if uploaded and uploaded.filename:
        old = s.frontend_404_image_filename
        stored, _original = _save_upload(uploaded)
        s.frontend_404_image_filename = stored
        if old and old != stored:
            _cleanup_retired_asset(old)
    db.session.commit()
    flash("404 page saved", "success")
    return redirect(url_for("main.frontend_404"))


@bp.route("/frontend/redirects")
@admin_required
def frontend_redirects():
    """Central redirects control panel. Two sections:

    1. **Manual redirects** (`UrlRedirect`) — admin-curated path → URL
       mappings; the public `_url_redirect_handler` (in `__init__.py`)
       walks this table on every incoming request and 301s on match.
    2. **Auto-logged slug renames** (`EntitySlugHistory`) — appended
       whenever a published post / story / blog / meeting / page slug
       changes. The detail-page routes use `(entity_type, old_slug)`
       to look up the entity and redirect to its current canonical
       URL. Editable + deletable from this panel so admins don't
       have to hop into each entity's edit page just to tweak a
       legacy URL alias.
    """
    s = _get_site_setting()
    rows = UrlRedirect.query.order_by(UrlRedirect.source_path.asc()).all()
    history = (EntitySlugHistory.query
               .order_by(EntitySlugHistory.changed_at.desc(),
                         EntitySlugHistory.id.desc())
               .all())
    # Resolve entity titles + current canonical slugs in batch so the
    # template doesn't trigger N queries inside the loop. For each
    # entity_type we collect the referenced ids, fetch them in one
    # round-trip, and stash a simple {(type, id): {title, slug}} map.
    by_type = {}
    for h in history:
        by_type.setdefault(h.entity_type, set()).add(h.entity_id)
    entity_lookup = {}
    type_models = {
        "meeting": (Meeting, "name"),
        "post":    (Post, "title"),
        "story":   (Story, "title"),
        "blog":    (BlogPost, "title"),
        "page":    (Page, "title"),
    }
    for ent_type, ids in by_type.items():
        model_label = type_models.get(ent_type)
        if not model_label:
            continue
        Model, title_attr = model_label
        rows_q = Model.query.filter(Model.id.in_(ids)).all()
        for r in rows_q:
            entity_lookup[(ent_type, r.id)] = {
                "title": getattr(r, title_attr, "") or f"#{r.id}",
                "slug":  getattr(r, "public_slug", None) or getattr(r, "slug", None),
            }
    return render_template("frontend_redirects.html", site=s,
                           redirects=rows,
                           slug_history=history,
                           entity_lookup=entity_lookup)


@bp.route("/frontend/redirects/save", methods=["POST"])
@admin_required
def frontend_redirects_save():
    """Create OR update a redirect. The presence of `redirect_id`
    decides which path: empty → create, set → update by id."""
    rid_raw = (request.form.get("redirect_id") or "").strip()
    src = (request.form.get("source_path") or "").strip()
    tgt = (request.form.get("target_path") or "").strip()
    if not src or not tgt:
        flash("Both source and target are required", "danger")
        return redirect(url_for("main.frontend_redirects"))
    # Normalize source to start with "/" — the before_request handler
    # matches against `request.path` which always starts with "/".
    if not src.startswith("/"):
        src = "/" + src
    src = src[:2000]
    tgt = tgt[:2000]
    # Block `source == target` loops at the form layer.
    if src == tgt:
        flash("Source and target can't be the same path.", "danger")
        return redirect(url_for("main.frontend_redirects"))
    if rid_raw:
        try:
            rid = int(rid_raw)
        except ValueError:
            abort(400)
        row = db.session.get(UrlRedirect, rid) or abort(404)
        if row.source_path != src:
            dup = UrlRedirect.query.filter(
                UrlRedirect.source_path == src,
                UrlRedirect.id != rid).first()
            if dup:
                flash(f"Source path “{src}” already redirects elsewhere.", "danger")
                return redirect(url_for("main.frontend_redirects"))
        row.source_path = src
        row.target_path = tgt
        flash(f"Updated redirect for {src}", "success")
    else:
        if UrlRedirect.query.filter_by(source_path=src).first():
            flash(f"Source path “{src}” already redirects elsewhere.", "danger")
            return redirect(url_for("main.frontend_redirects"))
        db.session.add(UrlRedirect(source_path=src, target_path=tgt))
        flash(f"Added redirect: {src} → {tgt}", "success")
    db.session.commit()
    return redirect(url_for("main.frontend_redirects"))


@bp.route("/frontend/redirects/<int:rid>/delete", methods=["POST"])
@admin_required
def frontend_redirects_delete(rid):
    row = db.session.get(UrlRedirect, rid) or abort(404)
    src = row.source_path
    db.session.delete(row)
    db.session.commit()
    flash(f"Deleted redirect for {src}", "success")
    return redirect(url_for("main.frontend_redirects"))


@bp.route("/frontend/redirects/slug-history/<int:hid>/save", methods=["POST"])
@admin_required
def frontend_slug_history_save(hid):
    """Edit an auto-logged slug-rename row. Admins can adjust the
    `old_slug` (the legacy URL pattern that should redirect) and the
    `new_slug` (informational, also used as the redirect display).
    Validation: slugs must be non-empty and slug-shaped (lowercase,
    digits, hyphens). Uniqueness within `(entity_type, old_slug)` is
    enforced — an `old_slug` collision would silently shadow the
    other row's redirect."""
    row = db.session.get(EntitySlugHistory, hid) or abort(404)
    old = (request.form.get("old_slug") or "").strip().lower()
    new = (request.form.get("new_slug") or "").strip().lower()
    if not old or not new:
        flash("Both old and new slug are required.", "danger")
        return redirect(url_for("main.frontend_redirects"))
    norm_old = _normalize_slug(old)
    norm_new = _normalize_slug(new)
    if not norm_old or not norm_new:
        flash("Slugs must be lowercase letters, digits, and hyphens.", "danger")
        return redirect(url_for("main.frontend_redirects"))
    if norm_old != row.old_slug:
        # Uniqueness check on (entity_type, old_slug) so the redirect
        # lookup stays deterministic.
        dup = EntitySlugHistory.query.filter(
            EntitySlugHistory.entity_type == row.entity_type,
            EntitySlugHistory.old_slug == norm_old,
            EntitySlugHistory.id != row.id).first()
        if dup:
            flash(f"Old slug “{norm_old}” already redirects elsewhere for this entity type.", "danger")
            return redirect(url_for("main.frontend_redirects"))
    row.old_slug = norm_old[:255]
    row.new_slug = norm_new[:255]
    db.session.commit()
    flash("Slug-redirect updated.", "success")
    return redirect(url_for("main.frontend_redirects"))


@bp.route("/frontend/redirects/slug-history/<int:hid>/delete", methods=["POST"])
@admin_required
def frontend_slug_history_delete(hid):
    """Delete an auto-logged slug-rename row. After deletion, requests
    to the old slug will 404 (or hit a real route if one exists).
    The entity's current canonical slug is unaffected."""
    row = db.session.get(EntitySlugHistory, hid) or abort(404)
    old = row.old_slug
    db.session.delete(row)
    db.session.commit()
    flash(f"Deleted slug-redirect for {old}", "success")
    return redirect(url_for("main.frontend_redirects"))


@public_bp.route("/site-branding/frontend-404-image")
def frontend_404_image():
    s = SiteSetting.query.first()
    if not s or not s.frontend_404_image_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], s.frontend_404_image_filename)


@public_bp.route("/preview-404")
def frontend_404_preview():
    """Render the public 404 template directly so admins can preview their
    customizations without having to actually 404 a URL. Returns 200, not
    404, so it's clearly a preview render."""
    from .frontend import _frontend_context
    s = SiteSetting.query.first()
    return render_template("frontend/404.html", **_frontend_context(s))


@bp.route("/frontend/design")
@admin_required
def frontend_design():
    """Site-wide design tokens (colors, spacing, buttons, links, text).
    Theme provides defaults; this page lets the admin override any
    subset. Empty inputs fall through to the theme default."""
    s = _get_site_setting()
    return render_template("frontend_design.html", site=s)


@bp.route("/frontend/design/save", methods=["POST"])
@admin_required
def frontend_design_save():
    """Persist design overrides as JSON. Each form field is named
    ``design_<token_key>``; invalid or empty inputs are dropped so the
    theme default kicks in for that token."""
    import json as _json
    from .design import parse_design_form
    s = _get_site_setting()
    overrides = parse_design_form(request.form)
    s.frontend_design_json = _json.dumps(overrides) if overrides else None
    db.session.commit()
    flash("Design saved", "success")
    return redirect(url_for("main.frontend_design"))


@bp.route("/frontend/default-theme", methods=["POST"])
@admin_required
def frontend_default_theme_save():
    """Persist the public site's default appearance mode for first-time
    visitors. Validation: only 'light' / 'dark' / 'system' accepted; any
    other value coerces to 'system' (matches the column default). A
    returning visitor's localStorage wins over this server default — see
    the bootstrap script in templates/frontend/base.html."""
    s = _get_site_setting()
    raw = (request.form.get("frontend_default_theme") or "").strip().lower()
    s.frontend_default_theme = raw if raw in ("light", "dark", "system") else "system"
    db.session.commit()
    flash("Default theme saved", "success")
    return redirect(url_for("main.frontend_design"))


@bp.route("/frontend/design/reset", methods=["POST"])
@admin_required
def frontend_design_reset():
    """Clear every override so the active theme's defaults take over."""
    s = _get_site_setting()
    s.frontend_design_json = None
    db.session.commit()
    flash("Design reset to theme defaults", "success")
    return redirect(url_for("main.frontend_design"))


@bp.route("/frontend/fonts-icons/save", methods=["POST"])
@admin_required
def frontend_fonts_icons_save():
    """Persist per-role font overrides. Admin can pick any vendored font
    key, ``custom:<id>`` for an admin-uploaded font, or the empty string
    to clear the override and fall back to the theme default."""
    import json as _json
    from .fonts import font_by_key, ROLES
    s = _get_site_setting()
    overrides = {}
    for role in ROLES:
        v = (request.form.get("font_" + role) or "").strip().lower()
        if v and font_by_key(v):
            overrides[role] = v
    s.frontend_fonts_json = _json.dumps(overrides) if overrides else None
    db.session.commit()
    flash("Frontend settings saved", "success")
    return redirect(url_for("main.frontend_fonts_icons"))


@bp.route("/frontend/branding/save", methods=["POST"])
@admin_required
def frontend_branding_save():
    """Save site name + Open Graph metadata (title/description/image) in
    one round trip. The fields written here are the *frontend* OG fields
    (frontend_og_*) — the backend Settings → Appearance modal writes the
    parallel og_* fields used on /tspro pages. Image upload + clear are
    handled like the other branding assets via _save_upload /
    _cleanup_retired_asset."""
    s = _get_site_setting()
    s.frontend_title = (request.form.get("frontend_title") or "").strip() or None
    s.frontend_og_enabled = request.form.get("og_enabled") == "1"
    s.frontend_og_title = (request.form.get("og_title") or "").strip()[:200] or None
    s.frontend_og_description = (request.form.get("og_description") or "").strip() or None
    if request.form.get("clear_og_image") == "1":
        old = s.frontend_og_image_filename
        s.frontend_og_image_filename = None
        _cleanup_retired_asset(old)
    uploaded = request.files.get("og_image")
    if uploaded and uploaded.filename:
        old = s.frontend_og_image_filename
        stored, _original = _save_upload(uploaded)
        s.frontend_og_image_filename = stored
        if old and old != stored:
            _cleanup_retired_asset(old)
    # Favicon — independent from the backend favicon. Same upload/clear
    # semantics as the OG image.
    if request.form.get("clear_favicon") == "1":
        old = s.frontend_favicon_filename
        s.frontend_favicon_filename = None
        _cleanup_retired_asset(old)
    favicon_upload = request.files.get("frontend_favicon")
    if favicon_upload and favicon_upload.filename:
        old = s.frontend_favicon_filename
        stored, _original = _save_upload(favicon_upload)
        s.frontend_favicon_filename = stored
        if old and old != stored:
            _cleanup_retired_asset(old)
    # iOS / iPadOS home-screen icon + display name. Independent of the
    # admin /tspro home-screen icon set under Settings → Appearance.
    s.frontend_apple_touch_icon_name = (request.form.get("frontend_apple_touch_icon_name") or "").strip()[:100] or None
    if request.form.get("clear_frontend_apple_touch_icon") == "1":
        old = s.frontend_apple_touch_icon_filename
        s.frontend_apple_touch_icon_filename = None
        _cleanup_retired_asset(old)
    ati_upload = request.files.get("frontend_apple_touch_icon")
    if ati_upload and ati_upload.filename:
        old = s.frontend_apple_touch_icon_filename
        stored, _original = _save_upload(ati_upload)
        s.frontend_apple_touch_icon_filename = stored
        if old and old != stored:
            _cleanup_retired_asset(old)
    db.session.commit()
    flash("Branding saved", "success")
    return redirect(url_for("main.frontend_branding"))


@bp.route("/frontend/header")
@admin_required
def frontend_header():
    from .frontend import HEADER_TEMPLATES
    s = _get_site_setting()
    return render_template("frontend_header.html", site=s,
                           header_templates=HEADER_TEMPLATES)


@bp.route("/frontend/navigation")
@admin_required
def frontend_navigation():
    from .frontend import MEGAMENU_TEMPLATES
    from .forms_registry import all_forms
    s = _get_site_setting()
    nav_items = FrontendNavItem.query.order_by(FrontendNavItem.position,
                                               FrontendNavItem.id).all()
    return render_template("frontend_navigation.html", site=s, nav_items=nav_items,
                           megamenu_templates=MEGAMENU_TEMPLATES,
                           form_registry_all=all_forms())


@bp.route("/frontend/megamenu-template", methods=["POST"])
@admin_required
def frontend_megamenu_template_save():
    from .frontend import MEGAMENU_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_megamenu_template") or "").strip()
    if key in {t["key"] for t in MEGAMENU_TEMPLATES}:
        s.frontend_megamenu_template = key
        db.session.commit()
        flash(f"Mega menu template set to {key}", "success")
    return redirect(url_for("main.frontend_navigation"))


@bp.route("/frontend/header-template", methods=["POST"])
@admin_required
def frontend_header_template_save():
    from .frontend import HEADER_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_header_template") or "").strip()
    allowed = {t["key"] for t in HEADER_TEMPLATES}
    if key in allowed:
        s.frontend_header_template = key
        db.session.commit()
        flash(f"Header template set to {key}", "success")
    return redirect(url_for("main.frontend_header"))


_FOOTER_PREBUILT_BLOCK_TYPES = {
    # Ordered lists matching the visual order each prebuilt Jinja file
    # renders blocks in. Used for the Footer admin's "structure" card —
    # for prebuilts it's flat (no rows/columns), so we display a single
    # row of clickable pills in this order.
    "classic":  ["brand", "link_columns", "copyright", "secondary_nav", "social_row"],
    "minimal":  ["copyright", "secondary_nav"],
    "stacked":  ["brand", "link_columns", "social_row", "copyright", "secondary_nav"],
    "mega":     ["brand", "link_columns", "social_row", "copyright", "secondary_nav"],
}


def _footer_active_block_types(active_key, active_rows):
    """Return the set of block-type strings used by the active footer
    layout. For prebuilt keys we read from the hardcoded mapping above;
    for custom layouts we walk the saved rows + columns."""
    if active_rows:
        types = set()
        for row in active_rows:
            for col in (row.get("columns") or []):
                for b in col:
                    t = b.get("type") if isinstance(b, dict) else None
                    if t:
                        types.add(t)
        return types
    return set(_FOOTER_PREBUILT_BLOCK_TYPES.get(active_key, []))


def _footer_active_block_order(active_key, active_rows):
    """Return an ordered list of block-type strings (de-duplicated) in
    the order they appear in the active layout — used to render the
    flat pill list for prebuilts AND to drive a stable display order
    when the structure card needs a quick-access "edit any block" row."""
    seen = set()
    order = []
    if active_rows:
        for row in active_rows:
            for col in (row.get("columns") or []):
                for b in col:
                    t = b.get("type") if isinstance(b, dict) else None
                    if t and t not in seen:
                        seen.add(t)
                        order.append(t)
        return order
    for t in _FOOTER_PREBUILT_BLOCK_TYPES.get(active_key, []):
        if t not in seen:
            seen.add(t); order.append(t)
    return order


@bp.route("/frontend/footer")
@admin_required
def frontend_footer():
    """Render the Footer admin. When the active layout is a custom
    CustomLayout (kind='footer'), the page shows an additional
    "Active layout structure" card visualising rows/columns/blocks so
    the admin sees which slots they're filling. Prebuilt layouts skip
    that card — their structure is fixed in the Jinja file.

    `active_block_types` drives which content-editor cards render: only
    the editors whose block type the active layout actually uses are
    shown. Switching to a layout that doesn't include, say, social
    icons hides the Social icons editor — the data still persists in
    JSON; switching back reveals the editor and its saved values."""
    import json as _json
    from .frontend import all_footer_layouts, FOOTER_BLOCK_CATALOG
    s = _get_site_setting()
    active_key = (s.frontend_footer_template if s else None) or "classic"
    active_layout = CustomLayout.query.filter_by(key=active_key, kind="footer").first()
    active_rows = None
    if active_layout:
        try:
            active_rows = _normalize_footer_blocks(_json.loads(active_layout.blocks_json or "[]"))
        except (ValueError, TypeError):
            active_rows = []
    active_block_types = _footer_active_block_types(active_key, active_rows)
    active_block_order = _footer_active_block_order(active_key, active_rows)
    # Pre-defined Meeting Locations from Settings — surfaced in the
    # meeting_locations modal as a checkbox list so the admin can pull
    # them in without retyping. Only in-person locations are shown
    # (online meetings have no address to render in the footer).
    all_locations = (Location.query
                     .filter(Location.location_type == "in_person")
                     .order_by(Location.name).all())
    return render_template("frontend_footer.html", site=s,
                           footer_layouts=all_footer_layouts(),
                           footer_block_catalog=FOOTER_BLOCK_CATALOG,
                           active_layout=active_layout,
                           active_layout_rows=active_rows,
                           active_block_types=active_block_types,
                           active_block_order=active_block_order,
                           all_locations=all_locations)


@bp.route("/frontend/footer-template", methods=["POST"])
@admin_required
def frontend_footer_template_save():
    """Set the active footer layout. Accepts either a hardcoded prebuilt
    key (FOOTER_TEMPLATES) OR a CustomLayout row of kind='footer' built
    via the structure-layout drag-drop builder."""
    from .frontend import FOOTER_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_footer_template") or "").strip()
    valid_keys = {t["key"] for t in FOOTER_TEMPLATES}
    if CustomLayout.query.filter_by(key=key, kind="footer").first():
        valid_keys.add(key)
    if key in valid_keys:
        s.frontend_footer_template = key
        db.session.commit()
        flash(f"Footer layout set to {key}", "success")
    return redirect(url_for("main.frontend_footer"))


_HOMEPAGE_BLOCK_CATALOG = [
    {"key": "hero",         "name": "Hero",          "icon": "panel-top",   "desc": "Headline, subheading, and call-to-action buttons. Required as the first block on most layouts."},
    {"key": "split",        "name": "Two-panel row", "icon": "columns",     "desc": "Full-width row with two side-by-side drop zones. Drag any other block into either panel."},
    {"key": "quick_links",  "name": "Quick links",   "icon": "layout-grid", "desc": "Four navigation cards for the most-used destinations."},
    {"key": "features",     "name": "Features",      "icon": "star",        "desc": "Three-up feature columns with icons and short copy."},
    {"key": "stats",        "name": "Stats",         "icon": "bar-chart",   "desc": "Number-driven metrics row for credibility cues."},
    {"key": "testimonials", "name": "Testimonials",  "icon": "message-circle", "desc": "Member quotes — adds social proof."},
    {"key": "cta",          "name": "Call to action","icon": "megaphone",   "desc": "Bold full-width banner with primary + ghost buttons."},
    {"key": "inclusion",    "name": "Inclusion",     "icon": "heart-handshake", "desc": "Statement of inclusion — heading, prose, optional welcome chips, and a call-to-action."},
    {"key": "meetings",     "name": "Meetings list", "icon": "calendar",    "desc": "Live meetings preview pulled from the admin database. Filter + animation are configured under the meetings card."},
    {"key": "events",       "name": "Upcoming Events","icon": "calendar",   "desc": "Stacked rows for upcoming events from the Announcements & Events module. Past events drop off automatically."},
    {"key": "about",        "name": "About",         "icon": "info",        "desc": "About-the-fellowship copy with the three numbered pillars."},
    {"key": "faq",          "name": "FAQ",           "icon": "help-circle", "desc": "Accordion list of common newcomer questions."},
    {"key": "contact",      "name": "Contact",       "icon": "phone",       "desc": "Contact-and-help section, optionally including the PIC card."},
]


# ---------------------------------------------------------------------------
# Templates admin — single page that hosts pickers for every reusable
# entity-detail template (Meeting Detail, Event Detail, and any future
# content types). Different from layouts: a layout is a block sequence
# bound to a specific page slug, while a template here applies to every
# page rendered for a content type.
# ---------------------------------------------------------------------------
@bp.route("/frontend/templates")
@admin_required
def frontend_templates():
    from .frontend import (MEETING_TEMPLATES, EVENT_TEMPLATES,
                           MEETINGS_LIST_TEMPLATES, EVENTS_LIST_TEMPLATES,
                           ANNOUNCEMENTS_LIST_TEMPLATES, ARCHIVE_TEMPLATES,
                           STORIES_LIST_TEMPLATES, STORY_TEMPLATES,
                           BLOG_LIST_TEMPLATES, BLOG_POST_TEMPLATES,
                           LITERATURE_LIBRARY_TEMPLATES, SITE_INDEX_TEMPLATES,
                           FELLOWSHIPS_LIST_TEMPLATES,
                           template_settings, meetings_list_protips_resolved,
                           meetings_list_sidebar_links_resolved)
    from .fonts import all_fonts
    s = _get_site_setting()
    meeting_key = (s.frontend_meeting_template if s else None) or "classic"
    event_key = (s.frontend_event_template if s else None) or "classic"
    meetings_list_key = (s.frontend_meetings_list_template if s else None) or "sidebar"
    events_list_key = (s.frontend_events_list_template if s else None) or "cards"
    announcements_list_key = (s.frontend_announcements_list_template if s else None) or "omni"
    archive_key = (s.frontend_archive_template if s else None) or "year-sidebar"
    stories_list_key = (s.frontend_stories_list_template if s else None) or "paper-stack"
    story_key = (s.frontend_story_template if s else None) or "paper"
    blog_list_key = (s.frontend_blog_list_template if s else None) or "magazine"
    blog_post_key = (s.frontend_blog_post_template if s else None) or "modern"
    literature_library_key = (s.frontend_literature_library_template if s else None) or "classic"
    site_index_key = (s.frontend_site_index_template if s else None) or "grouped"
    fellowships_list_key = (s.frontend_fellowships_list_template if s else None) or "sidebar"
    # Render the cards alphabetised by display name so admins always
    # see them in a stable, predictable order regardless of how each
    # `*_TEMPLATES` catalog list happens to be declared. Sort is
    # case-insensitive on `name`; only the picker order on this page
    # is affected — the catalogs themselves keep their declared order
    # (which other call sites use as a fallback for "first available
    # template", lookups by key, etc.).
    def _by_name(catalog):
        return sorted(catalog, key=lambda t: (t.get("name") or "").lower())
    return render_template("frontend_templates.html", site=s,
                           meeting_templates=_by_name(MEETING_TEMPLATES),
                           event_templates=_by_name(EVENT_TEMPLATES),
                           meetings_list_templates=_by_name(MEETINGS_LIST_TEMPLATES),
                           meetings_list_active_key=meetings_list_key,
                           meetings_list_protips=meetings_list_protips_resolved(s),
                           meetings_list_sidebar_links=meetings_list_sidebar_links_resolved(s),
                           events_list_templates=_by_name(EVENTS_LIST_TEMPLATES),
                           events_list_active_key=events_list_key,
                           announcements_list_templates=_by_name(ANNOUNCEMENTS_LIST_TEMPLATES),
                           announcements_list_active_key=announcements_list_key,
                           archive_templates=_by_name(ARCHIVE_TEMPLATES),
                           archive_active_key=archive_key,
                           stories_list_templates=_by_name(STORIES_LIST_TEMPLATES),
                           stories_list_active_key=stories_list_key,
                           story_templates=_by_name(STORY_TEMPLATES),
                           story_active_key=story_key,
                           blog_list_templates=_by_name(BLOG_LIST_TEMPLATES),
                           blog_list_active_key=blog_list_key,
                           blog_post_templates=_by_name(BLOG_POST_TEMPLATES),
                           blog_post_active_key=blog_post_key,
                           literature_library_templates=_by_name(LITERATURE_LIBRARY_TEMPLATES),
                           literature_library_active_key=literature_library_key,
                           meeting_active_settings=template_settings(s, "meeting", meeting_key),
                           event_active_settings=template_settings(s, "event", event_key),
                           # All seven list / detail sections also need their per-template
                           # settings dict for the customize panel. Each kind reuses the
                           # same `frontend_template_settings_json` JSON column keyed by
                           # (kind, key) — no schema changes needed.
                           meetings_list_active_settings=template_settings(s, "meetings_list", meetings_list_key),
                           events_list_active_settings=template_settings(s, "events_list", events_list_key),
                           announcements_list_active_settings=template_settings(s, "announcements_list", announcements_list_key),
                           archive_active_settings=template_settings(s, "archive", archive_key),
                           stories_list_active_settings=template_settings(s, "stories_list", stories_list_key),
                           story_active_settings=template_settings(s, "story", story_key),
                           blog_list_active_settings=template_settings(s, "blog_list", blog_list_key),
                           blog_post_active_settings=template_settings(s, "blog_post", blog_post_key),
                           literature_library_active_settings=template_settings(s, "literature_library", literature_library_key),
                           # Printlist has no template variants (single layout); use a
                           # synthetic 'default' key so the customize panel keeps the same
                           # shape as everywhere else.
                           printlist_active_settings=template_settings(s, "printlist", "default"),
                           contact_active_settings=template_settings(s, "contact", "split"),
                           site_index_templates=_by_name(SITE_INDEX_TEMPLATES),
                           site_index_active_key=site_index_key,
                           site_index_active_settings=template_settings(s, "site_index", site_index_key),
                           fellowships_list_templates=_by_name(FELLOWSHIPS_LIST_TEMPLATES),
                           fellowships_list_active_key=fellowships_list_key,
                           fellowships_list_active_settings=template_settings(s, "fellowships_list", fellowships_list_key),
                           font_options=all_fonts())


# Every kind that frontend_template_settings_save accepts. Each must
# resolve a catalog (or a one-key sentinel like printlist_default) so
# the form's `key` URL segment can be validated. Keeping this in one
# place means adding a future section is a single edit.
_TEMPLATE_KINDS = ("meeting", "event", "story", "blog_post",
                   "meetings_list", "events_list",
                   "announcements_list", "archive",
                   "stories_list", "blog_list",
                   "literature_library", "printlist", "contact",
                   "site_index", "fellowships_list")


@bp.route("/frontend/template-settings/<kind>/<key>", methods=["POST"])
@admin_required
def frontend_template_settings_save(kind, key):
    """Persist per-template appearance overrides (background, font choices,
    size scales) into SiteSetting.frontend_template_settings_json. Empty or
    default values are stripped so the template falls through to the site's
    design tokens."""
    import json as _json
    import re as _re
    from .frontend import (MEETING_TEMPLATES, EVENT_TEMPLATES, STORY_TEMPLATES,
                            BLOG_POST_TEMPLATES, BLOG_LIST_TEMPLATES,
                            MEETINGS_LIST_TEMPLATES, EVENTS_LIST_TEMPLATES,
                            ANNOUNCEMENTS_LIST_TEMPLATES, ARCHIVE_TEMPLATES,
                            STORIES_LIST_TEMPLATES,
                            LITERATURE_LIBRARY_TEMPLATES, SITE_INDEX_TEMPLATES,
                            FELLOWSHIPS_LIST_TEMPLATES)
    from .fonts import font_by_key
    if kind not in _TEMPLATE_KINDS:
        abort(404)
    # One-place dispatch: every kind resolves to either a catalog
    # of variants OR a one-key sentinel (printlist / contact have a
    # single rendering, but still get a customize panel for UI
    # uniformity, so they validate against a fixed 'default' or
    # 'split' key).
    catalog_map = {
        "meeting": MEETING_TEMPLATES,
        "event": EVENT_TEMPLATES,
        "story": STORY_TEMPLATES,
        "blog_post": BLOG_POST_TEMPLATES,
        "meetings_list": MEETINGS_LIST_TEMPLATES,
        "events_list": EVENTS_LIST_TEMPLATES,
        "announcements_list": ANNOUNCEMENTS_LIST_TEMPLATES,
        "archive": ARCHIVE_TEMPLATES,
        "stories_list": STORIES_LIST_TEMPLATES,
        "blog_list": BLOG_LIST_TEMPLATES,
        "literature_library": LITERATURE_LIBRARY_TEMPLATES,
        "site_index": SITE_INDEX_TEMPLATES,
        "fellowships_list": FELLOWSHIPS_LIST_TEMPLATES,
    }
    if kind in catalog_map:
        if key not in {t["key"] for t in catalog_map[kind]}:
            abort(404)
    elif kind == "printlist":
        if key != "default":
            abort(404)
    elif kind == "contact":
        if key != "split":
            abort(404)
    s = _get_site_setting()
    raw = (s.frontend_template_settings_json or "").strip()
    try:
        data = _json.loads(raw) if raw else {}
        if not isinstance(data, dict):
            data = {}
    except (ValueError, TypeError):
        data = {}
    bucket = data.setdefault(kind, {})
    leaf = {}
    bg = (request.form.get("bg") or "").strip()
    if _re.match(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", bg) and request.form.get("bg_enabled") == "1":
        leaf["bg"] = bg
        # Dark-mode behaviour for the override. 'same' is the implicit
        # default and is dropped from JSON to keep the leaf lean.
        bg_dm_mode = (request.form.get("bg_dark_mode") or "same").strip()
        if bg_dm_mode in ("auto", "manual"):
            leaf["bg_dark_mode"] = bg_dm_mode
        if bg_dm_mode == "manual":
            bg_dark = (request.form.get("bg_dark") or "").strip()
            if _re.match(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", bg_dark):
                leaf["bg_dark"] = bg_dark
    # Per-template dynamic-background. Stored alongside the colour
    # override so a template can carry its own backdrop without
    # touching the site-wide hero / page settings. Coerced through
    # the catalog so a tampered POST can only land on a known key.
    from . import dynbg as _dynbg
    dyn_key = _dynbg.normalize(request.form.get("bg_dynamic_key"))
    if dyn_key:
        leaf["bg_dynamic_key"] = dyn_key
    # Overlay + custom-colour config — round-trips through the same
    # encode_config gate the per-surface columns use, so a tampered
    # POST can only land on known overlay keys / valid hex colours /
    # in-range noise knobs.
    dynbg_cfg = _dynbg.encode_config(
        overlay_key=request.form.get("bg_dynbg_config_json__overlay"),
        colors=[request.form.get(f"bg_dynbg_config_json__c{i}") for i in (1, 2, 3)],
        scope=request.form.get("bg_dynbg_config_json__scope"),
        noise_size=request.form.get("bg_dynbg_config_json__noise_size"),
        noise_intensity=request.form.get("bg_dynbg_config_json__noise_intensity"),
        randomize_colors=request.form.get("bg_dynbg_config_json__randomize_colors") == "1",
        randomize_positions=request.form.get("bg_dynbg_config_json__randomize_positions") == "1",
        animate=False if request.form.get("bg_dynbg_config_json__animate_off") == "1" else True,
    )
    if dynbg_cfg.get("overlay"):
        leaf["bg_dynbg_overlay"] = dynbg_cfg["overlay"]
    if dynbg_cfg.get("colors"):
        leaf["bg_dynbg_colors"] = dynbg_cfg["colors"]
    if dynbg_cfg.get("overlay_scope"):
        leaf["bg_dynbg_overlay_scope"] = dynbg_cfg["overlay_scope"]
    if dynbg_cfg.get("overlay_size") is not None:
        leaf["bg_dynbg_overlay_size"] = dynbg_cfg["overlay_size"]
    if dynbg_cfg.get("overlay_intensity") is not None:
        leaf["bg_dynbg_overlay_intensity"] = dynbg_cfg["overlay_intensity"]
    if dynbg_cfg.get("randomize_colors"):
        leaf["bg_dynbg_randomize_colors"] = True
    if dynbg_cfg.get("randomize_positions"):
        leaf["bg_dynbg_randomize_positions"] = True
    if dynbg_cfg.get("animate") is False:
        leaf["bg_dynbg_animate"] = False
    # Classic blog detail toggles for the right-side rail. Stored
     # only as explicit `False` so the JSON stays lean — missing keys
     # mean "show the widget" (the default). When the user unchecks
     # the box the form omits the field, so we record the False
     # state; checking it again drops the key back out.
    if kind == "blog_post" and key == "classic":
        if request.form.get("show_related_widget") != "1":
            leaf["show_related_widget"] = False
        if request.form.get("show_categories_widget") != "1":
            leaf["show_categories_widget"] = False
    for fkey in ("heading_font", "body_font"):
        v = (request.form.get(fkey) or "").strip()
        if v and font_by_key(v):
            leaf[fkey] = v
    for skey in ("heading_size", "body_size"):
        # Each size has an accompanying "<key>_enabled" checkbox: skip when
        # absent so leaving "Use template default" off clears the override.
        if request.form.get(f"{skey}_enabled") != "1":
            continue
        try:
            v = float(request.form.get(skey) or "0")
            if 0.5 <= v <= 4.0:
                leaf[skey] = round(v, 1)
        except ValueError:
            pass
    if leaf:
        bucket[key] = leaf
    else:
        bucket.pop(key, None)
    if not bucket:
        data.pop(kind, None)
    s.frontend_template_settings_json = _json.dumps(data) if data else None
    db.session.commit()
    flash(f"{kind.capitalize()} template settings saved", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/meeting-template", methods=["POST"])
@admin_required
def frontend_meeting_template_save():
    from .frontend import MEETING_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_meeting_template") or "").strip()
    if key in {t["key"] for t in MEETING_TEMPLATES}:
        s.frontend_meeting_template = key
        db.session.commit()
        flash(f"Meeting template set to {key}", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/events-list-template", methods=["POST"])
@admin_required
def frontend_events_list_template_save():
    """Persist the events-list template + container-width + page heading
    selections from the admin Templates page in one POST. Mirrors the
    meetings-list save endpoint exactly."""
    from .frontend import EVENTS_LIST_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_events_list_template") or "").strip()
    if key in {t["key"] for t in EVENTS_LIST_TEMPLATES}:
        s.frontend_events_list_template = key
    width = (request.form.get("frontend_events_list_width_mode") or "").strip()
    if width in ("boxed", "full"):
        s.frontend_events_list_width_mode = width
    if "frontend_events_list_max_width" in request.form:
        try:
            max_w = int(request.form.get("frontend_events_list_max_width") or 1160)
        except ValueError:
            max_w = 1160
        s.frontend_events_list_max_width = max(640, min(2400, max_w))
    if "frontend_events_list_padding_pct" in request.form:
        try:
            pad = int(request.form.get("frontend_events_list_padding_pct") or 5)
        except ValueError:
            pad = 5
        s.frontend_events_list_padding_pct = max(0, min(20, pad))
    if "frontend_events_list_heading" in request.form:
        heading = (request.form.get("frontend_events_list_heading") or "").strip()
        s.frontend_events_list_heading = heading[:200] or None
    if "frontend_events_list_subheading" in request.form:
        subheading = (request.form.get("frontend_events_list_subheading") or "").strip()
        s.frontend_events_list_subheading = subheading[:500] or None
    if "frontend_events_list_bg_dynamic_key" in request.form:
        from . import dynbg as _dynbg
        s.frontend_events_list_bg_dynamic_key = _dynbg.normalize(
            request.form.get("frontend_events_list_bg_dynamic_key"))
        s.frontend_events_list_bg_dynbg_config_json = _dynbg_config_from_form(
            request.form, "frontend_events_list_bg_dynbg_config_json")
    db.session.commit()
    flash("Events list settings saved", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/announcements-list-template", methods=["POST"])
@admin_required
def frontend_announcements_list_template_save():
    """Persist the announcements-list template + container-width + page
    heading selections from the admin Templates page in one POST. Mirrors
    the events-list save endpoint exactly."""
    from .frontend import ANNOUNCEMENTS_LIST_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_announcements_list_template") or "").strip()
    if key in {t["key"] for t in ANNOUNCEMENTS_LIST_TEMPLATES}:
        s.frontend_announcements_list_template = key
    width = (request.form.get("frontend_announcements_list_width_mode") or "").strip()
    if width in ("boxed", "full"):
        s.frontend_announcements_list_width_mode = width
    if "frontend_announcements_list_max_width" in request.form:
        try:
            max_w = int(request.form.get("frontend_announcements_list_max_width") or 1160)
        except ValueError:
            max_w = 1160
        s.frontend_announcements_list_max_width = max(640, min(2400, max_w))
    if "frontend_announcements_list_padding_pct" in request.form:
        try:
            pad = int(request.form.get("frontend_announcements_list_padding_pct") or 5)
        except ValueError:
            pad = 5
        s.frontend_announcements_list_padding_pct = max(0, min(20, pad))
    if "frontend_announcements_list_heading" in request.form:
        heading = (request.form.get("frontend_announcements_list_heading") or "").strip()
        s.frontend_announcements_list_heading = heading[:200] or None
    if "frontend_announcements_list_subheading" in request.form:
        subheading = (request.form.get("frontend_announcements_list_subheading") or "").strip()
        s.frontend_announcements_list_subheading = subheading[:500] or None
    if "frontend_announcements_list_bg_dynamic_key" in request.form:
        from . import dynbg as _dynbg
        s.frontend_announcements_list_bg_dynamic_key = _dynbg.normalize(
            request.form.get("frontend_announcements_list_bg_dynamic_key"))
        s.frontend_announcements_list_bg_dynbg_config_json = _dynbg_config_from_form(
            request.form, "frontend_announcements_list_bg_dynbg_config_json")
    db.session.commit()
    flash("Announcements list settings saved", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/archive-template", methods=["POST"])
@admin_required
def frontend_archive_template_save():
    """Persist the /archive layout, pagination strategy, initial page
    size, and per-page dynamic-background selection from the admin
    Templates page. The archive reuses the events-list width/padding
    settings; everything else lives on `frontend_archive_*` columns."""
    from .frontend import ARCHIVE_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_archive_template") or "").strip()
    if key in {t["key"] for t in ARCHIVE_TEMPLATES}:
        s.frontend_archive_template = key
    mode = (request.form.get("frontend_archive_pagination_mode") or "").strip()
    if mode in ("infinite", "numbered"):
        s.frontend_archive_pagination_mode = mode
    if "frontend_archive_page_size" in request.form:
        try:
            size = int(request.form.get("frontend_archive_page_size") or 20)
        except ValueError:
            size = 20
        s.frontend_archive_page_size = max(1, min(200, size))
    if "frontend_archive_bg_dynamic_key" in request.form:
        from . import dynbg as _dynbg
        s.frontend_archive_bg_dynamic_key = _dynbg.normalize(
            request.form.get("frontend_archive_bg_dynamic_key"))
        s.frontend_archive_bg_dynbg_config_json = _dynbg_config_from_form(
            request.form, "frontend_archive_bg_dynbg_config_json")
    db.session.commit()
    flash("Archive settings saved", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/stories-list-template", methods=["POST"])
@admin_required
def frontend_stories_list_template_save():
    """Persist the stories-list template + container-width + page heading
    selections from the admin Templates page in one POST. Mirrors the
    announcements-list save endpoint."""
    from .frontend import STORIES_LIST_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_stories_list_template") or "").strip()
    if key in {t["key"] for t in STORIES_LIST_TEMPLATES}:
        s.frontend_stories_list_template = key
    width = (request.form.get("frontend_stories_list_width_mode") or "").strip()
    if width in ("boxed", "full"):
        s.frontend_stories_list_width_mode = width
    if "frontend_stories_list_max_width" in request.form:
        try:
            max_w = int(request.form.get("frontend_stories_list_max_width") or 1160)
        except ValueError:
            max_w = 1160
        s.frontend_stories_list_max_width = max(640, min(2400, max_w))
    if "frontend_stories_list_padding_pct" in request.form:
        try:
            pad = int(request.form.get("frontend_stories_list_padding_pct") or 5)
        except ValueError:
            pad = 5
        s.frontend_stories_list_padding_pct = max(0, min(20, pad))
    if "frontend_stories_list_heading" in request.form:
        heading = (request.form.get("frontend_stories_list_heading") or "").strip()
        s.frontend_stories_list_heading = heading[:200] or None
    if "frontend_stories_list_subheading" in request.form:
        subheading = (request.form.get("frontend_stories_list_subheading") or "").strip()
        s.frontend_stories_list_subheading = subheading[:500] or None
    if "frontend_stories_list_bg_dynamic_key" in request.form:
        from . import dynbg as _dynbg
        s.frontend_stories_list_bg_dynamic_key = _dynbg.normalize(
            request.form.get("frontend_stories_list_bg_dynamic_key"))
        s.frontend_stories_list_bg_dynbg_config_json = _dynbg_config_from_form(
            request.form, "frontend_stories_list_bg_dynbg_config_json")
    db.session.commit()
    flash("Stories list settings saved", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/story-template", methods=["POST"])
@admin_required
def frontend_story_template_save():
    """Persist the per-story detail template selection."""
    from .frontend import STORY_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_story_template") or "").strip()
    if key in {t["key"] for t in STORY_TEMPLATES}:
        s.frontend_story_template = key
    if "frontend_story_bg_dynamic_key" in request.form:
        from . import dynbg as _dynbg
        s.frontend_story_bg_dynamic_key = _dynbg.normalize(
            request.form.get("frontend_story_bg_dynamic_key"))
        s.frontend_story_bg_dynbg_config_json = _dynbg_config_from_form(
            request.form, "frontend_story_bg_dynbg_config_json")
    db.session.commit()
    flash("Story template settings saved", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/blog-list-template", methods=["POST"])
@admin_required
def frontend_blog_list_template_save():
    """Persist the blog-list template + container width + page heading
    selections from the admin Templates page. Mirrors the announcements-
    list save endpoint."""
    from .frontend import BLOG_LIST_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_blog_list_template") or "").strip()
    if key in {t["key"] for t in BLOG_LIST_TEMPLATES}:
        s.frontend_blog_list_template = key
    width = (request.form.get("frontend_blog_list_width_mode") or "").strip()
    if width in ("boxed", "full"):
        s.frontend_blog_list_width_mode = width
    if "frontend_blog_list_max_width" in request.form:
        try:
            max_w = int(request.form.get("frontend_blog_list_max_width") or 1160)
        except ValueError:
            max_w = 1160
        s.frontend_blog_list_max_width = max(640, min(2400, max_w))
    if "frontend_blog_list_padding_pct" in request.form:
        try:
            pad = int(request.form.get("frontend_blog_list_padding_pct") or 5)
        except ValueError:
            pad = 5
        s.frontend_blog_list_padding_pct = max(0, min(20, pad))
    if "frontend_blog_list_heading" in request.form:
        heading = (request.form.get("frontend_blog_list_heading") or "").strip()
        s.frontend_blog_list_heading = heading[:200] or None
    if "frontend_blog_list_subheading" in request.form:
        subheading = (request.form.get("frontend_blog_list_subheading") or "").strip()
        s.frontend_blog_list_subheading = subheading[:500] or None
    if "frontend_blog_list_bg_dynamic_key" in request.form:
        from . import dynbg as _dynbg
        s.frontend_blog_list_bg_dynamic_key = _dynbg.normalize(
            request.form.get("frontend_blog_list_bg_dynamic_key"))
        s.frontend_blog_list_bg_dynbg_config_json = _dynbg_config_from_form(
            request.form, "frontend_blog_list_bg_dynbg_config_json")
    db.session.commit()
    flash("Blog list settings saved", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/blog-post-template", methods=["POST"])
@admin_required
def frontend_blog_post_template_save():
    """Persist the per-blog-post detail template selection AND its
    container-width controls (same shape as the blog-list save)."""
    from .frontend import BLOG_POST_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_blog_post_template") or "").strip()
    if key in {t["key"] for t in BLOG_POST_TEMPLATES}:
        s.frontend_blog_post_template = key
    width = (request.form.get("frontend_blog_post_width_mode") or "").strip()
    if width in ("boxed", "full"):
        s.frontend_blog_post_width_mode = width
    if "frontend_blog_post_max_width" in request.form:
        try:
            max_w = int(request.form.get("frontend_blog_post_max_width") or 1160)
        except ValueError:
            max_w = 1160
        s.frontend_blog_post_max_width = max(640, min(2400, max_w))
    if "frontend_blog_post_padding_pct" in request.form:
        try:
            pad = int(request.form.get("frontend_blog_post_padding_pct") or 5)
        except ValueError:
            pad = 5
        s.frontend_blog_post_padding_pct = max(0, min(20, pad))
    if "frontend_blog_post_bg_dynamic_key" in request.form:
        from . import dynbg as _dynbg
        s.frontend_blog_post_bg_dynamic_key = _dynbg.normalize(
            request.form.get("frontend_blog_post_bg_dynamic_key"))
        s.frontend_blog_post_bg_dynbg_config_json = _dynbg_config_from_form(
            request.form, "frontend_blog_post_bg_dynbg_config_json")
    db.session.commit()
    flash("Blog post template settings saved", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/meetings-list-template", methods=["POST"])
@admin_required
def frontend_meetings_list_template_save():
    from .frontend import MEETINGS_LIST_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_meetings_list_template") or "").strip()
    if key in {t["key"] for t in MEETINGS_LIST_TEMPLATES}:
        s.frontend_meetings_list_template = key
    width = (request.form.get("frontend_meetings_list_width_mode") or "").strip()
    if width in ("boxed", "full"):
        s.frontend_meetings_list_width_mode = width
    if "frontend_meetings_list_max_width" in request.form:
        try:
            max_w = int(request.form.get("frontend_meetings_list_max_width") or 1160)
        except ValueError:
            max_w = 1160
        s.frontend_meetings_list_max_width = max(640, min(2400, max_w))
    if "frontend_meetings_list_padding_pct" in request.form:
        try:
            pad = int(request.form.get("frontend_meetings_list_padding_pct") or 5)
        except ValueError:
            pad = 5
        s.frontend_meetings_list_padding_pct = max(0, min(20, pad))
    if "frontend_meetings_list_heading" in request.form:
        heading = (request.form.get("frontend_meetings_list_heading") or "").strip()
        s.frontend_meetings_list_heading = heading[:200] or None
    if "frontend_meetings_list_subheading" in request.form:
        subheading = (request.form.get("frontend_meetings_list_subheading") or "").strip()
        s.frontend_meetings_list_subheading = subheading[:500] or None
    # Pro Tips section — collect form fields into a JSON blob layered
    # over the defaults. Items default to the baked list when the admin
    # hasn't supplied a JSON override; we accept either a structured
    # JSON paste in `protips_items_json` or the form-array shape used
    # by the per-item editor (parsed via parse_faq with a custom
    # prefix). The empty / unparseable case stores NULL so the
    # frontend resolver falls back wholesale to defaults.
    import json as _json_pt
    import re as _re_pt
    _hex_re = _re_pt.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    def _hex_or_blank(v):
        v = (v or "").strip()
        return v if _hex_re.match(v) else ""
    pt_cfg = {
        "enabled": request.form.get("protips_enabled") == "1",
        "heading": (request.form.get("protips_heading") or "").strip()[:200],
        "subheading": (request.form.get("protips_subheading") or "").strip()[:500],
        "icon": (request.form.get("protips_icon") or "").strip()[:64],
        "icon_color": _hex_or_blank(request.form.get("protips_icon_color")),
    }
    # Per-item form-array editor — same shape as the homepage FAQ
    # parser, but with a `protip_item_*` prefix. Items keyed by the
    # `protip_item_present` markers so submission order = render order.
    pt_items = []
    for raw_idx in request.form.getlist("protip_item_present"):
        try:
            i = int(raw_idx)
        except (TypeError, ValueError):
            continue
        question = (request.form.get(f"protip_item_{i}_question") or "").strip()
        answer = (request.form.get(f"protip_item_{i}_answer") or "").strip()
        ic = (request.form.get(f"protip_item_{i}_icon") or "").strip()
        ic_size = (request.form.get(f"protip_item_{i}_icon_size") or "").strip()
        if not (question or answer):
            continue
        try:
            sz = int(ic_size) if ic_size else 0
        except (TypeError, ValueError):
            sz = 0
        size_out = str(sz) if 12 <= sz <= 200 else ""
        pt_items.append({
            "icon": ic[:64],
            "icon_size": size_out,
            "question": question[:300],
            "answer": answer[:4000],
        })
    # When the editor submits any rows, that's the canonical list.
    # An entirely empty submission (admin removed every row) saves an
    # empty list so the section hides via the items-empty gate. No
    # JSON-textarea fallback path — the GUI is the source of truth.
    if request.form.getlist("protip_item_present"):
        pt_cfg["items"] = pt_items
    s.frontend_meetings_list_protips_json = _json_pt.dumps(pt_cfg)

    # Sidebar custom-links editor — same form-array pattern as protips,
    # keyed off `sidebar_link_present` so admin row order = render
    # order. Empty rows (missing label OR url) are silently dropped;
    # an entirely empty submission saves an empty list so the section
    # auto-hides via the `if list_sidebar_links` gate in the partial.
    sidebar_links = []
    for raw_idx in request.form.getlist("sidebar_link_present"):
        try:
            i = int(raw_idx)
        except (TypeError, ValueError):
            continue
        label = (request.form.get(f"sidebar_link_{i}_label") or "").strip()
        url = (request.form.get(f"sidebar_link_{i}_url") or "").strip()
        if not (label and url):
            continue
        link_type = (request.form.get(f"sidebar_link_{i}_type") or "internal").strip().lower()
        if link_type not in ("internal", "external"):
            link_type = "internal"
        sidebar_links.append({
            "label":           label[:200],
            "url":             url[:600],
            "link_type":       link_type,
            "open_in_new_tab": request.form.get(f"sidebar_link_{i}_new_tab") == "1",
        })
    s.frontend_meetings_list_sidebar_links_json = _json_pt.dumps(sidebar_links)

    if "frontend_meetings_list_bg_dynamic_key" in request.form:
        from . import dynbg as _dynbg
        s.frontend_meetings_list_bg_dynamic_key = _dynbg.normalize(
            request.form.get("frontend_meetings_list_bg_dynamic_key"))
        s.frontend_meetings_list_bg_dynbg_config_json = _dynbg_config_from_form(
            request.form, "frontend_meetings_list_bg_dynbg_config_json")
    db.session.commit()
    flash("Meetings list settings saved", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/literature-library-template", methods=["POST"])
@admin_required
def frontend_literature_library_template_save():
    """Persist the Literature Library template selection. Today there's
    a single layout; the catalog gives the picker a place to land if
    a second one's added later. The bigger work — flipping individual
    libraries / items public — happens on each Library's own edit
    modal, not here."""
    from .frontend import LITERATURE_LIBRARY_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_literature_library_template") or "").strip()
    if key in {t["key"] for t in LITERATURE_LIBRARY_TEMPLATES}:
        s.frontend_literature_library_template = key
    if "frontend_literature_library_bg_dynamic_key" in request.form:
        from . import dynbg as _dynbg
        s.frontend_literature_library_bg_dynamic_key = _dynbg.normalize(
            request.form.get("frontend_literature_library_bg_dynamic_key"))
        s.frontend_literature_library_bg_dynbg_config_json = _dynbg_config_from_form(
            request.form, "frontend_literature_library_bg_dynbg_config_json")
    db.session.commit()
    flash("Literature Library settings saved", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/printlist-template", methods=["POST"])
@admin_required
def frontend_printlist_template_save():
    """Persist the Printlist subheading, website, and page size. The
    Printlist has a single layout today so there's no template radio —
    the form is purely the configuration fields."""
    s = _get_site_setting()
    sub = (request.form.get("frontend_printlist_subheading") or "").strip()
    s.frontend_printlist_subheading = sub[:500] or None
    web = (request.form.get("frontend_printlist_website") or "").strip()
    s.frontend_printlist_website = web[:200] or None
    size = (request.form.get("frontend_printlist_page_size") or "").strip().lower()
    if size in ("letter", "legal"):
        s.frontend_printlist_page_size = size
    if "frontend_printlist_bg_dynamic_key" in request.form:
        from . import dynbg as _dynbg
        s.frontend_printlist_bg_dynamic_key = _dynbg.normalize(
            request.form.get("frontend_printlist_bg_dynamic_key"))
        s.frontend_printlist_bg_dynbg_config_json = _dynbg_config_from_form(
            request.form, "frontend_printlist_bg_dynbg_config_json")
    db.session.commit()
    flash("Printlist settings saved", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/site-index-template", methods=["POST"])
@admin_required
def frontend_site_index_template_save():
    """Persist Site Index settings — layout choice, page heading copy,
    sort mode, per-section visibility toggles, and dynbg key. Each
    block uses field-presence checks so the cards-only layout form
    and the broader settings form can both POST to this URL without
    clobbering each other's fields."""
    from .frontend import SITE_INDEX_TEMPLATES
    s = _get_site_setting()
    if "frontend_site_index_template" in request.form:
        key = (request.form.get("frontend_site_index_template") or "").strip()
        if key in {t["key"] for t in SITE_INDEX_TEMPLATES}:
            s.frontend_site_index_template = key
    if "frontend_site_index_enabled_present" in request.form:
        s.frontend_site_index_enabled = request.form.get("frontend_site_index_enabled") == "1"
    if "frontend_site_index_heading" in request.form:
        h = (request.form.get("frontend_site_index_heading") or "").strip()
        s.frontend_site_index_heading = h[:200] or None
    if "frontend_site_index_subheading" in request.form:
        sub = (request.form.get("frontend_site_index_subheading") or "").strip()
        s.frontend_site_index_subheading = sub[:500] or None
    if "frontend_site_index_sort_mode" in request.form:
        sort = (request.form.get("frontend_site_index_sort_mode") or "").strip()
        if sort in ("grouped", "alpha"):
            s.frontend_site_index_sort_mode = sort
    # Per-section toggles. We only update when the form carries the
    # `<field>_present` marker so the cards-only POST doesn't blank
    # them all back to False (an unchecked checkbox just doesn't
    # appear in the form data).
    for col in ("show_pages", "show_meetings", "show_events",
                "show_announcements", "show_stories", "show_library"):
        marker = f"frontend_site_index_{col}_present"
        if marker in request.form:
            on = request.form.get(f"frontend_site_index_{col}") == "1"
            setattr(s, f"frontend_site_index_{col}", on)
    if "frontend_site_index_bg_dynamic_key" in request.form:
        from . import dynbg as _dynbg
        s.frontend_site_index_bg_dynamic_key = _dynbg.normalize(
            request.form.get("frontend_site_index_bg_dynamic_key"))
        s.frontend_site_index_bg_dynbg_config_json = _dynbg_config_from_form(
            request.form, "frontend_site_index_bg_dynbg_config_json")
    db.session.commit()
    flash("Site Index settings saved", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/fellowships-list-template", methods=["POST"])
@admin_required
def frontend_fellowships_list_template_save():
    """Persist the /fellowships layout choice, container width, page
    heading copy, default sort mode, enable toggle, and dynbg config
    from the admin Templates page. Field-presence checks let multiple
    forms (cards-only picker vs the broader settings panel) POST here
    without clobbering each other's columns."""
    from .frontend import FELLOWSHIPS_LIST_TEMPLATES
    s = _get_site_setting()
    if "frontend_fellowships_list_template" in request.form:
        key = (request.form.get("frontend_fellowships_list_template") or "").strip()
        if key in {t["key"] for t in FELLOWSHIPS_LIST_TEMPLATES}:
            s.frontend_fellowships_list_template = key
    if "frontend_fellowships_enabled_present" in request.form:
        s.frontend_fellowships_enabled = request.form.get("frontend_fellowships_enabled") == "1"
    width = (request.form.get("frontend_fellowships_list_width_mode") or "").strip()
    if width in ("boxed", "full"):
        s.frontend_fellowships_list_width_mode = width
    if "frontend_fellowships_list_max_width" in request.form:
        try:
            max_w = int(request.form.get("frontend_fellowships_list_max_width") or 1160)
        except ValueError:
            max_w = 1160
        s.frontend_fellowships_list_max_width = max(640, min(2400, max_w))
    if "frontend_fellowships_list_padding_pct" in request.form:
        try:
            pad = int(request.form.get("frontend_fellowships_list_padding_pct") or 5)
        except ValueError:
            pad = 5
        s.frontend_fellowships_list_padding_pct = max(0, min(20, pad))
    if "frontend_fellowships_list_heading" in request.form:
        heading = (request.form.get("frontend_fellowships_list_heading") or "").strip()
        s.frontend_fellowships_list_heading = heading[:200] or None
    if "frontend_fellowships_list_subheading" in request.form:
        subheading = (request.form.get("frontend_fellowships_list_subheading") or "").strip()
        s.frontend_fellowships_list_subheading = subheading[:500] or None
    if "frontend_fellowships_list_sort_mode" in request.form:
        sort = (request.form.get("frontend_fellowships_list_sort_mode") or "").strip()
        if sort in ("name-asc", "name-desc", "country-asc", "newest", "oldest"):
            s.frontend_fellowships_list_sort_mode = sort
    if "frontend_fellowships_list_bg_dynamic_key" in request.form:
        from . import dynbg as _dynbg
        s.frontend_fellowships_list_bg_dynamic_key = _dynbg.normalize(
            request.form.get("frontend_fellowships_list_bg_dynamic_key"))
        s.frontend_fellowships_list_bg_dynbg_config_json = _dynbg_config_from_form(
            request.form, "frontend_fellowships_list_bg_dynbg_config_json")
    db.session.commit()
    flash("Fellowships list settings saved", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/event-template", methods=["POST"])
@admin_required
def frontend_event_template_save():
    from .frontend import EVENT_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_event_template") or "").strip()
    if key in {t["key"] for t in EVENT_TEMPLATES}:
        s.frontend_event_template = key
        db.session.commit()
        flash(f"Event template set to {key}", "success")
    return redirect(url_for("main.frontend_templates"))


_CUSTOM_LAYOUT_BLOCK_TYPES = {
    "hero", "quick_links", "meetings", "events", "about", "contact",
    "features", "cta", "stats", "testimonials", "faq", "inclusion", "split",
}

# Block types valid inside a Page custom layout. Mirrors the keys of
# `_PAGE_BLOCK_CATALOG` plus `split` (which the page route expands into
# a real two-column container at preset-apply time). Distinct from the
# homepage set since pages compose generic content blocks (paragraphs,
# headings, images, …) rather than the homepage's site-section blocks.
_PAGE_LAYOUT_BLOCK_TYPES = {
    "split", "container", "heading", "paragraph", "image", "button",
    "list", "callout", "video", "code", "separator", "toc_sidebar", "icon",
    # Homepage section blocks made available to content pages too.
    # `hero` embeds the site-wide hero (Settings → Frontend → Hero
    # drives every instance). `meetings` / `events` carry their own
    # per-instance config (same defaults as the homepage's section
    # blocks) and the page route pre-fetches the matching rows.
    # `features` is a self-contained cards block — heading / subheading
    # plus an inline list of {icon, title, body, href, …} items.
    # `faq` is a list of {question, answer, icon, icon_size} accordion
    # items; the public render's section heading is hardcoded (same as
    # the homepage's behaviour).
    "hero", "meetings", "events", "features", "faq",
}

# Block types valid inside a footer custom layout. The footer dispatcher
# (frontend/footers/_custom.html) walks these in order; each renders the
# matching `frontend/footers/blocks/_<type>.html` partial which reads
# from the shared structured content (footer_content(site)).
_FOOTER_BLOCK_TYPES = {
    "brand", "link_columns", "social_row", "secondary_nav", "copyright",
    "divider", "spacer", "meeting_locations", "contact_section",
    "powered_by", "admin_login",
}


_FOOTER_VALID_COLS = {1, 2, 3, 4}


def _normalize_footer_blocks(raw_list):
    """Validate a footer custom-layout block list. The canonical shape is:
        [{"type": "row", "cols": 1-4,
          "columns": [[{type: <block-type>}, ...], ...]}, ...]
    The auto-migration path: a legacy flat list ([{type: <bt>}, ...]) gets
    wrapped in a single 1-column row so older saves keep rendering after
    the rows+cols upgrade. Block types must be in _FOOTER_BLOCK_TYPES;
    column count clamps to 1-4; columns past `cols` are dropped, missing
    columns are padded with empty arrays."""
    if not raw_list:
        return []
    out = []
    legacy_flat = []  # any top-level non-row entries collected here
    for b in raw_list:
        if not isinstance(b, dict):
            continue
        t = (b.get("type") or "").strip()
        if t == "row":
            try:
                cols = int(b.get("cols") or 1)
            except (TypeError, ValueError):
                cols = 1
            if cols not in _FOOTER_VALID_COLS:
                cols = 1
            raw_columns = b.get("columns") or []
            columns = []
            for col in raw_columns[:cols]:
                if not isinstance(col, list):
                    columns.append([])
                    continue
                clean = []
                for bb in col:
                    if isinstance(bb, dict) and bb.get("type") in _FOOTER_BLOCK_TYPES:
                        clean.append({"type": bb["type"]})
                columns.append(clean)
            while len(columns) < cols:
                columns.append([])
            out.append({"type": "row", "cols": cols, "columns": columns})
        elif t in _FOOTER_BLOCK_TYPES:
            legacy_flat.append({"type": t})
    # Wrap any top-level legacy blocks as one 1-col row so the saved
    # layout still renders.
    if legacy_flat:
        out.insert(0 if not out else len(out),
                   {"type": "row", "cols": 1, "columns": [legacy_flat]})
    return out


_SPLIT_VALID_WIDTHS = {"boxed", "full"}
_SPLIT_VALID_SPACING = {"none", "tight", "default", "loose"}
_SPLIT_HEX_RE = _re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _normalize_blocks(raw_list, allowed_types=None):
    """Recursively walk a list of {type,...} dicts from the builder.
    Drops unknown block types. For 'split' blocks, recurses into
    `left` / `right` AND round-trips the split's spacing + appearance
    settings (width, padding, top/bottom gap, inner gap, bg color) so
    editing the layout structure in the builder doesn't blow them away.
    The legacy `margin` field — which used to control top + bottom gap
    together — is migrated into `gap_top` + `gap_bottom` on read so old
    layouts upgrade transparently.

    `allowed_types` defaults to the homepage whitelist; pass
    `_PAGE_LAYOUT_BLOCK_TYPES` for the page admin's builder."""
    if allowed_types is None:
        allowed_types = _CUSTOM_LAYOUT_BLOCK_TYPES
    out = []
    for b in (raw_list or []):
        t = ""
        left = right = None
        if isinstance(b, dict):
            t = (b.get("type") or "").strip()
            left = b.get("left")
            right = b.get("right")
        else:
            t = str(b).strip()
        if t not in allowed_types:
            continue
        if t == "split":
            norm = {
                "type": "split",
                "left":  _normalize_blocks(left or [], allowed_types),
                "right": _normalize_blocks(right or [], allowed_types),
            }
            if isinstance(b, dict):
                w = (b.get("width") or "").strip().lower()
                p = (b.get("padding") or "").strip().lower()
                gt = (b.get("gap_top") or "").strip().lower()
                gb = (b.get("gap_bottom") or "").strip().lower()
                gp = (b.get("gap") or "").strip().lower()
                bg = (b.get("bg_color") or "").strip()
                # Legacy migration: pre-existing layouts stored a single
                # `margin` field; copy it forward into both new fields if
                # the new ones aren't explicitly set.
                legacy_m = (b.get("margin") or "").strip().lower()
                if legacy_m in _SPLIT_VALID_SPACING:
                    if not gt: gt = legacy_m
                    if not gb: gb = legacy_m

                if w in _SPLIT_VALID_WIDTHS:  norm["width"] = w
                if p in _SPLIT_VALID_SPACING: norm["padding"] = p
                if gt in _SPLIT_VALID_SPACING: norm["gap_top"] = gt
                if gb in _SPLIT_VALID_SPACING: norm["gap_bottom"] = gb
                if gp in _SPLIT_VALID_SPACING: norm["gap"] = gp
                for pk in ("pad_left_pct", "pad_right_pct"):
                    try:
                        n = int(b.get(pk) or 0)
                    except (TypeError, ValueError):
                        n = 0
                    n = max(0, min(50, n))
                    if n: norm[pk] = n
                if bg and _SPLIT_HEX_RE.match(bg): norm["bg_color"] = bg
                bg_l = (b.get("bg_color_left") or "").strip()
                bg_r = (b.get("bg_color_right") or "").strip()
                if bg_l and _SPLIT_HEX_RE.match(bg_l): norm["bg_color_left"] = bg_l
                if bg_r and _SPLIT_HEX_RE.match(bg_r): norm["bg_color_right"] = bg_r
                if b.get("bg_dark_mode"): norm["bg_dark_mode"] = True
            out.append(norm)
        elif t == "container":
            # Container blocks recurse into a `blocks` array — same
            # whitelist as the parent, so nested containers are allowed
            # but disallowed types (e.g. split inside container, which
            # the builder UI also blocks) get dropped.
            inner = b.get("blocks") if isinstance(b, dict) else None
            cont = {
                "type": "container",
                "blocks": _normalize_blocks(inner or [], allowed_types),
            }
            # Preserve container-level dynbg state on layout-template
            # saves so a layout that ships a textured container makes
            # it through the normalizer with its picks intact. Each
            # value gates through the dynbg helpers so the layout
            # JSON can never carry an unknown overlay key or invalid
            # hex colour.
            from . import dynbg as _dynbg
            if isinstance(b, dict):
                _bk = _dynbg.normalize(b.get("bg_dynamic_key"))
                if _bk:
                    cont["bg_dynamic_key"] = _bk
                _bo = _dynbg.normalize_overlay(b.get("bg_dynbg_overlay"))
                if _bo:
                    cont["bg_dynbg_overlay"] = _bo
                _bcols = [c for c in _dynbg.normalize_colors(b.get("bg_dynbg_colors") or []) if c]
                if _bcols:
                    cont["bg_dynbg_colors"] = _bcols
                _bsc = _dynbg.normalize_scope(b.get("bg_dynbg_overlay_scope"))
                if _bsc and _bsc != "all":
                    cont["bg_dynbg_overlay_scope"] = _bsc
                _bsz = _dynbg.normalize_float(b.get("bg_dynbg_overlay_size"),
                                                _dynbg.NOISE_SIZE_MIN,
                                                _dynbg.NOISE_SIZE_MAX, None)
                if _bsz is not None and abs(_bsz - _dynbg.NOISE_SIZE_DEFAULT) > 1e-6:
                    cont["bg_dynbg_overlay_size"] = round(_bsz, 3)
                _bin = _dynbg.normalize_float(b.get("bg_dynbg_overlay_intensity"),
                                                _dynbg.NOISE_INTENSITY_MIN,
                                                _dynbg.NOISE_INTENSITY_MAX, None)
                if _bin is not None and abs(_bin - _dynbg.NOISE_INTENSITY_DEFAULT) > 1e-6:
                    cont["bg_dynbg_overlay_intensity"] = round(_bin, 4)
                if b.get("bg_dynbg_randomize"):
                    cont["bg_dynbg_randomize"] = True
            out.append(cont)
        else:
            out.append({"type": t})
    return out


@bp.route("/frontend/custom-layout/save", methods=["POST"])
@admin_required
def frontend_custom_layout_save():
    """Persist a user-created layout from the drag-and-drop builder.
    Returns JSON {ok, key, layout} so the picker can re-render and
    auto-select the new entry. The optional `kind` field on the JSON
    payload lets the same endpoint serve homepage AND footer (and any
    future structural layout). Defaults to 'homepage' for backwards
    compat with existing builder calls."""
    import json as _json
    payload = request.get_json(silent=True) or {}
    kind = (payload.get("kind") or "homepage").strip().lower()
    if kind == "footer":
        blocks = _normalize_footer_blocks(payload.get("blocks") or [])
    elif kind == "homepage":
        blocks = _normalize_blocks(payload.get("blocks") or [])
    elif kind == "page":
        blocks = _normalize_blocks(payload.get("blocks") or [],
                                    allowed_types=_PAGE_LAYOUT_BLOCK_TYPES)
    else:
        return jsonify(ok=False, error=f"Unknown layout kind: {kind}"), 400
    if not blocks:
        return jsonify(ok=False, error="At least one block is required"), 400
    raw_name = (payload.get("name") or "").strip()[:120] or "Custom layout"
    # Generate a unique key from the name + a numeric suffix.
    base = _re.sub(r"[^a-z0-9]+", "-", raw_name.lower()).strip("-") or "custom"
    candidate = base
    i = 1
    while CustomLayout.query.filter_by(key=candidate).first() is not None:
        i += 1
        candidate = f"{base}-{i}"
    row = CustomLayout(
        key=candidate, name=raw_name,
        description=f"Custom layout · {len(blocks)} block{'' if len(blocks)==1 else 's'}",
        blocks_json=_json.dumps(blocks),
        kind=kind, is_prebuilt=False,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify(ok=True, key=row.key, name=row.name)


@bp.route("/frontend/custom-layout/<key>/update", methods=["POST"])
@admin_required
def frontend_custom_layout_update(key):
    """Replace a custom layout's name + blocks. Pre-built layouts seeded
    via _seed_custom_layouts are read-only — admins can clone them by
    using "Custom layout" in the picker but not edit the originals.
    Dispatches to the right block-type validator based on row.kind."""
    import json as _json
    row = CustomLayout.query.filter_by(key=key).first() or abort(404)
    if row.is_prebuilt:
        return jsonify(ok=False, error="Built-in layouts can't be edited"), 400
    payload = request.get_json(silent=True) or {}
    if row.kind == "footer":
        blocks = _normalize_footer_blocks(payload.get("blocks") or [])
    elif row.kind == "page":
        blocks = _normalize_blocks(payload.get("blocks") or [],
                                    allowed_types=_PAGE_LAYOUT_BLOCK_TYPES)
    else:
        blocks = _normalize_blocks(payload.get("blocks") or [])
    if not blocks:
        return jsonify(ok=False, error="At least one block is required"), 400
    raw_name = (payload.get("name") or "").strip()[:120] or row.name
    row.name = raw_name
    row.description = f"Custom layout · {len(blocks)} block{'' if len(blocks)==1 else 's'}"
    row.blocks_json = _json.dumps(blocks)
    db.session.commit()
    return jsonify(ok=True, key=row.key, name=row.name)


@bp.route("/frontend/custom-layout/<key>/delete", methods=["POST"])
@admin_required
def frontend_custom_layout_delete(key):
    """Delete a custom layout. If the deleted layout was active on a
    page that uses it, fall back to the default 'classic' layout for
    that kind so the public site doesn't render against a missing key."""
    row = CustomLayout.query.filter_by(key=key).first() or abort(404)
    if row.is_prebuilt:
        return jsonify(ok=False, error="Built-in layouts can't be deleted"), 400
    s = _get_site_setting()
    if row.kind == "homepage" and s.frontend_homepage_template == row.key:
        s.frontend_homepage_template = "classic"
    if row.kind == "footer" and s.frontend_footer_template == row.key:
        s.frontend_footer_template = "classic"
    db.session.delete(row)
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/frontend/theme-save", methods=["POST"])
@admin_required
def frontend_theme_save():
    """Set the global visual theme. Propagates the chosen key to every
    per-section template field so all four regions (header, footer,
    homepage, mega menu) match the theme."""
    from .frontend import THEMES
    s = _get_site_setting()
    key = (request.form.get("frontend_theme") or "").strip()
    if key in {t["key"] for t in THEMES}:
        s.frontend_theme = key
        s.frontend_header_template = key
        s.frontend_footer_template = key
        s.frontend_homepage_template = key
        s.frontend_megamenu_template = key
        db.session.commit()
        flash(f"Theme set to {key}", "success")
    return redirect(_safe_referrer() or url_for("main.frontend_dashboard"))


@bp.route("/frontend/pages")
@admin_required
def frontend_pages():
    from .models import Page
    s = _get_site_setting()
    pages = Page.query.order_by(Page.title.asc()).all()
    page_layouts = _page_layouts_for_picker()
    return render_template("frontend_pages.html", site=s, pages=pages,
                           page_layouts=page_layouts)


# Block catalog for the page-layout drag-and-drop builder. Lists every
# content block type the admin can drop into a custom page layout. Maps
# 1:1 to the JS BlockEditor's BLOCK_TYPES, plus icon strings drawn from
# the same Lucide set the rest of the admin uses.
_PAGE_BLOCK_CATALOG = [
    {"key": "split",     "name": "Two-panel row",
     "icon": "columns",
     "desc": "Side-by-side layout with two drop zones — the page applies it as a real two-column container."},
    {"key": "split3",    "name": "Three-panel row",
     "icon": "layout-grid",
     "desc": "Three-column layout with three drop zones — equal-width grid container with three inner containers ready for content."},
    {"key": "container", "name": "Container",
     "icon": "layout-grid",
     "desc": "Nested layout primitive — flex/grid, padding, gap, background, border, hover. Drop other blocks inside."},
    {"key": "toc_sidebar", "name": "Wiki sidebar",
     "icon": "panel-left",
     "desc": "Sticky 'On this page' table of contents built from the page's heading blocks. Place inside a column to get a wiki-style sidebar."},
    {"key": "heading",   "name": "Heading",
     "icon": "heading",
     "desc": "Section heading (H2-H5)."},
    {"key": "paragraph", "name": "Text",
     "icon": "type",
     "desc": "Markdown paragraph or rich-text block."},
    {"key": "image",     "name": "Image",
     "icon": "image",
     "desc": "Image with alt text + optional caption."},
    {"key": "icon",      "name": "Icon",
     "icon": "star",
     "desc": "Single Lucide / custom icon with size, colour, dark-mode colour, alignment, and optional click-through link."},
    {"key": "button",    "name": "Button",
     "icon": "mouse-pointer-click",
     "desc": "Primary, secondary, or fully-custom CTA button."},
    {"key": "list",      "name": "List",
     "icon": "list",
     "desc": "Bulleted / numbered list — renders as numbered step cards in showcase layouts."},
    {"key": "callout",   "name": "Callout",
     "icon": "alert-triangle",
     "desc": "Info / warn / danger / success callout box."},
    {"key": "video",     "name": "Video",
     "icon": "video",
     "desc": "HTML5 video with optional poster."},
    {"key": "lottie",    "name": "Lottie animation",
     "icon": "play-circle",
     "desc": "Embed a Bodymovin / Lottie JSON animation. Loops, autoplays, and scales to its column."},
    {"key": "intergroup_member", "name": "Intergroup Member",
     "icon": "users",
     "desc": "Render a single officer's contact info (position, name, phone, email). Pulls live from Settings → Global → Intergroup Officers."},
    {"key": "intergroup_member_roster", "name": "Officer Roster",
     "icon": "users",
     "desc": "Loop every Intergroup Officer into a 2- or 3-column card grid. Toggle which fields to show; editing a row in Settings → Global propagates everywhere."},
    {"key": "library",   "name": "Library",
     "icon": "book-open",
     "desc": "Render any Library's items in your chosen style (bulleted list, plain list, or card grid). Pick the whole library or hand-select specific items."},
    {"key": "code",      "name": "Code",
     "icon": "code",
     "desc": "Monospace code block with optional language hint."},
    {"key": "separator", "name": "Divider",
     "icon": "minus",
     "desc": "Horizontal hairline separator."},
    {"key": "hero", "name": "Hero",
     "icon": "image",
     "desc": "Embed the site-wide hero (heading, subheading, CTA buttons, background style). Pulls live from Settings → Frontend → Hero so every page using the block stays in sync."},
    {"key": "meetings", "name": "Meetings list",
     "icon": "calendar-clock",
     "desc": "Live list of meetings filtered by your choice of window (today, next 24h, this week, all). Same configurable card grid the homepage uses."},
    {"key": "events", "name": "Upcoming events",
     "icon": "calendar",
     "desc": "Upcoming-events list pulled from the Posts module. Same configurable list block the homepage uses."},
    {"key": "features", "name": "Features",
     "icon": "layout-grid",
     "desc": "Up to six clickable cards with icon, title, and Markdown body. Same configurable cards grid the homepage 'Features' section uses."},
    {"key": "faq", "name": "FAQ",
     "icon": "help-circle",
     "desc": "Up to twenty accordion items with optional per-question icon. Markdown answers, drag-to-reorder. Same accordion the homepage FAQ section uses."},
]


def _page_layouts_for_picker():
    """Return all page layout rows ordered presets-first-then-custom,
    matching the homepage / footer pickers' sort order."""
    return (CustomLayout.query
            .filter_by(kind="page")
            .order_by(CustomLayout.is_prebuilt.desc(), CustomLayout.created_at)
            .all())


def _page_active_layout(page, layouts):
    """Resolve the page's active layout row. Returns the matching
    CustomLayout, or None when the page is on 'custom' or the saved
    layout was deleted."""
    if not page or not page.layout_key or page.layout_key == "custom":
        return None
    return next((l for l in layouts if l.key == page.layout_key), None)


def _layout_block_shape(b):
    """Return a structural signature for a single block, ignoring
    user-content fields (text, md, src, items, alt, label, url, etc.)
    Used to detect whether a page has been structurally edited away
    from its prebuilt layout's stamped shape — content edits don't
    count as customization, only structural ones (added / removed /
    rearranged blocks, changed container display / grid columns)."""
    if not isinstance(b, dict):
        return None
    t = b.get("type")
    if not t:
        return None
    sig = {"type": t}
    if t == "container":
        d = b.get("data") or {}
        sig["display"] = d.get("display", "flex")
        sig["grid_columns"] = d.get("grid_columns", "")
        sig["blocks"] = [_layout_block_shape(c) for c in (d.get("blocks") or [])]
        sig["blocks"] = [s for s in sig["blocks"] if s is not None]
    return sig


def _layout_section_shape(sections):
    """Walk a sections list and return a hashable signature for the
    structural (non-titled, non-orphan) sections. Skips orphan bins
    and titled sections — only the layout-stamped UNTITLED sections
    contribute, since those are what the layout owns."""
    out = []
    for s in (sections or []):
        if not isinstance(s, dict):
            continue
        if s.get("_orphans"):
            continue
        if (s.get("title") or "").strip():
            continue
        out.append([_layout_block_shape(b) for b in (s.get("blocks") or [])])
    return out


def _page_is_customized(page, active_layout):
    """True when the page's structural shape deviates from what the
    active layout would stamp fresh. Always False for `layout_key=custom`
    (free-form pages don't have a template to deviate from), and for
    pages with no active layout. Orphan-bin content also flags as
    customized — those are blocks the admin lifted out of the layout
    that haven't been re-placed yet."""
    if not active_layout:
        return False
    if not page or not page.layout_key or page.layout_key == "custom":
        return False
    import json as _json
    try:
        page_sections = _json.loads(page.blocks_json or "[]") or []
        preset_entries = _json.loads(active_layout.blocks_json or "[]") or []
    except (ValueError, TypeError):
        return False
    # Anything in the orphan bin = structural drift = customized.
    for s in page_sections:
        if isinstance(s, dict) and s.get("_orphans") and (s.get("blocks") or []):
            return True
    # Compare structural shape: stamp the layout fresh and diff
    # signatures. Identical shape (same number of untitled sections,
    # each with the same block types nested the same way) = not
    # customized.
    expected_sections = []
    for entry in preset_entries:
        b = _instantiate_preset_entry(entry)
        if b:
            expected_sections.append({"title": "", "blocks": [b]})
    return _layout_section_shape(page_sections) != _layout_section_shape(expected_sections)


def _hero_block_modal_proxy(data):
    """Build a SimpleNamespace shim that mirrors `SiteSetting.frontend_hero_*`
    attribute names from a hero block's `data` dict. Lets the page hero
    modal reuse the homepage hero modal's markup verbatim — the markup
    references `site.frontend_hero_<x>` throughout; we hand it this
    proxy instead. Keys mirror the homepage's column names so admins
    edit the same fields in either context."""
    from types import SimpleNamespace
    d = data or {}
    sw_raw = d.get("bg_sinewave_colors") or []
    return SimpleNamespace(
        frontend_hero_heading=d.get("heading", ""),
        frontend_hero_subheading=d.get("subheading", ""),
        frontend_tagline=d.get("eyebrow", ""),
        frontend_tagline_enabled=bool(d.get("tagline_enabled", True)),
        frontend_hero_heading_font=d.get("heading_font", "fraunces"),
        frontend_hero_heading_size=d.get("heading_size_pct", 100),
        frontend_hero_heading_grad_start=d.get("heading_grad_start", "#0f172a"),
        frontend_hero_heading_grad_end=d.get("heading_grad_end", "#374151"),
        # Dark-mode gradient stops. Defaults match the existing dark
        # hero CSS (`#fff → #94a3b8`) so unedited blocks render the
        # same in dark mode as they did before the field existed.
        frontend_hero_heading_grad_start_dark=d.get("heading_grad_start_dark", "#ffffff"),
        frontend_hero_heading_grad_end_dark=d.get("heading_grad_end_dark", "#94a3b8"),
        frontend_hero_subheading_font=d.get("subheading_font", "inter"),
        frontend_hero_subheading_size=d.get("subheading_size_pct", 100),
        frontend_hero_subheading_color=d.get("subheading_color", "#475569"),
        # Same dark-mode default for subheading — `#94a3b8` matches
        # the existing hardcoded dark colour.
        frontend_hero_subheading_color_dark=d.get("subheading_color_dark", "#94a3b8"),
        frontend_hero_text_dynamic=bool(d.get("text_dynamic", False)),
        frontend_hero_height_vh_desktop=d.get("height_vh_desktop", 0),
        frontend_hero_height_vh_mobile=d.get("height_vh_mobile", 0),
        frontend_hero_bg_style=d.get("bg_style", "solid"),
        frontend_hero_bg_color=d.get("bg_color", ""),
        frontend_hero_bg_color_2=d.get("bg_color_2", ""),
        frontend_hero_bg_gradient_angle=d.get("bg_gradient_angle", 180),
        frontend_hero_bg_image_mode=d.get("bg_image_mode", "cover"),
        frontend_hero_bg_image_scale=d.get("bg_image_scale", 100),
        frontend_hero_bg_hue=d.get("bg_hue", 225),
        frontend_hero_bg_hue_2=d.get("bg_hue_2", 170),
        frontend_hero_bg_blur=d.get("bg_blur", 80),
        frontend_hero_bg_opacity=d.get("bg_opacity", 45),
        frontend_hero_bg_randomize=bool(d.get("bg_randomize", False)),
        frontend_hero_sinewave_colors_list=sw_raw if isinstance(sw_raw, list) else [],
        frontend_hero_bg_video_speed=d.get("bg_video_speed", 100),
        frontend_hero_bg_dynamic_key=d.get("bg_dynamic_key", ""),
        frontend_hero_particle_enabled=bool(d.get("particle_enabled", False)),
        frontend_hero_particle_effect=d.get("particle_effect", "stars"),
        frontend_hero_particle_speed=d.get("particle_speed", 100),
        frontend_hero_particle_size=d.get("particle_size", 100),
    )


def _meetings_block_modal_proxy(data):
    """Build a dict shim that mirrors the homepage macro's
    `block_content._meetings` shape from a per-page meetings block's
    `data` dict. The page meetings modal partial reuses the homepage's
    `editor_meetings()` macro markup verbatim — the markup references
    `_ms.<key>` throughout (where `_ms = block_content._meetings`); we
    just pass our block's data through `MEETINGS_DEFAULTS` so missing
    keys fall back to the same defaults the public renderer uses."""
    from .blocks import MEETINGS_DEFAULTS
    d = data or {}
    return {**MEETINGS_DEFAULTS, **d}


def _events_block_modal_proxy(data):
    """Same shim pattern as `_meetings_block_modal_proxy` for the
    per-page upcoming-events block. The modal partial reuses the
    homepage's `editor_events()` macro markup verbatim; the macro
    reads `_es.<key>` (where `_es = block_content._events`) so we
    merge with `EVENTS_DEFAULTS` and hand the dict in as `vals`."""
    from .blocks import EVENTS_DEFAULTS
    d = data or {}
    return {**EVENTS_DEFAULTS, **d}


def _features_block_modal_proxy(data):
    """Per-page features block proxy. Mirrors the homepage's
    `block_content.features` shape so the page modal can reuse the
    homepage's `editor_features()` macro markup. The cards list is
    rendered empty server-side and populated by `page_features_modal.js`
    on pill click — so the initial proxy needs heading / subheading
    keys but an empty `items` list, regardless of what defaults
    `DEFAULTS["features"]` carries (otherwise the placeholder cards
    would flash before JS overwrites them)."""
    d = data or {}
    return {
        "heading": d.get("heading") or "",
        "subheading": d.get("subheading") or "",
        "items": [],
    }


def _faq_block_modal_proxy(data):
    """Per-page FAQ block proxy. Same flash-prevention pattern as
    features: the modal renders an empty `items` list server-side
    and `page_faq_modal.js` clones the `<template>` once per saved
    item on pill click. Heading + subheading are exposed for per-page
    overrides — the public partial falls back to the homepage's
    hardcoded strings when these are empty, so cleared values still
    produce a valid section-head."""
    d = data or {}
    return {
        "heading": d.get("heading") or "",
        "subheading": d.get("subheading") or "",
        "items": [],
    }


def _block_preview(b):
    """Tiny preview payload for a block, surfaced as a hover popover
    on each pill in the structure card / orphan bin. The admin sees
    enough content to identify which block is which without having
    to open the editor. Returns a dict {kind, text?, src?, …} that
    the template stringifies onto `data-preview` for client-side
    rendering."""
    if not isinstance(b, dict):
        return {"kind": "empty"}
    t = b.get("type")
    d = b.get("data") or {}
    if t == "paragraph":
        md = (d.get("md") or "").strip()
        return {"kind": "text", "label": "Text",
                "text": md[:200] if md else "(empty)"}
    if t == "heading":
        text = (d.get("text") or "").strip()
        lvl = d.get("level") or 3
        return {"kind": "text", "label": f"Heading H{lvl}",
                "text": text or "(empty)"}
    if t == "image":
        src = (d.get("src") or "").strip()
        alt = (d.get("alt") or "").strip()
        cap = (d.get("caption") or "").strip()
        return {"kind": "image", "label": "Image",
                "src": src, "alt": alt, "text": cap}
    if t == "button":
        return {"kind": "text", "label": "Button",
                "text": (d.get("label") or "").strip() or "(no label)",
                "subtext": (d.get("url") or "").strip() or "(no link)"}
    if t == "list":
        items = [str(i).strip() for i in (d.get("items") or []) if str(i).strip()]
        n = len(items)
        return {"kind": "list",
                "label": f"{'Numbered' if d.get('ordered') else 'Bulleted'} list",
                "text": " · ".join(items[:5]) + ("…" if n > 5 else ""),
                "subtext": f"{n} item{'' if n == 1 else 's'}"}
    if t == "callout":
        return {"kind": "text", "label": f"Callout · {d.get('variant') or 'info'}",
                "text": (d.get("title") or d.get("md") or "").strip()[:200]}
    if t == "video":
        return {"kind": "text", "label": "Video",
                "text": (d.get("src") or "").strip() or "(no source)"}
    if t == "lottie":
        sp = d.get("speed") or 1
        flags = []
        if d.get("playback") == "hover":
            flags.append("hover-play")
        elif d.get("autoplay"):
            flags.append("autoplay")
        if d.get("loop"):
            flags.append("loop")
        return {"kind": "text", "label": "Lottie",
                "text": (d.get("src") or "").strip() or "(no source)",
                "subtext": " · ".join(flags + [f"{sp}x"])}
    if t == "intergroup_member":
        oid = d.get("officer_id") or 0
        from .models import IntergroupOfficer
        try:
            oid = int(oid)
        except (TypeError, ValueError):
            oid = 0
        officer = db.session.get(IntergroupOfficer, oid) if oid else None
        if officer is None:
            return {"kind": "text", "label": "Intergroup Member",
                    "text": "(no officer selected)",
                    "subtext": "Pick a row from Settings → Global"}
        fields = []
        if d.get("show_role"): fields.append("role")
        if d.get("show_name"): fields.append("name")
        if d.get("show_phone"): fields.append("phone")
        if d.get("show_email"): fields.append("email")
        return {"kind": "text", "label": "Intergroup Member",
                "text": (officer.role or "").strip() or "(unset)",
                "subtext": (officer.name or "").strip() + (
                    "  ·  " + " · ".join(fields) if fields else "")}
    if t == "intergroup_member_roster":
        from .models import IntergroupOfficer
        n = IntergroupOfficer.query.count()
        cols = d.get("columns") or 3
        return {"kind": "text", "label": "Officer Roster",
                "text": f"{n} officer card" + ("" if n == 1 else "s"),
                "subtext": f"{cols}-column grid"}
    if t == "library":
        from .models import Library, LibraryItem
        lib_id = d.get("library_id") or 0
        try: lib_id = int(lib_id)
        except (TypeError, ValueError): lib_id = 0
        lib = db.session.get(Library, lib_id) if lib_id else None
        if lib is None:
            return {"kind": "text", "label": "Library",
                    "text": "(no library selected)",
                    "subtext": "Pick one in the editor"}
        if (d.get("mode") or "all") == "granular":
            ids = d.get("item_ids") or []
            count = sum(1 for i in ids if i)
            mode_label = f"{count} hand-picked"
        else:
            count = LibraryItem.query.filter_by(library_id=lib.id).count()
            mode_label = f"all {count} items"
        return {"kind": "text", "label": "Library",
                "text": lib.name,
                "subtext": f"{d.get('style') or 'cards'}  ·  {mode_label}"}
    if t == "code":
        code = (d.get("code") or "").strip()
        return {"kind": "code", "label": f"Code{' · ' + d.get('lang') if d.get('lang') else ''}",
                "text": code[:200] if code else "(empty)"}
    if t == "container":
        kids = d.get("blocks") or []
        return {"kind": "text", "label": "Container",
                "text": f"{len(kids)} child block{'' if len(kids) == 1 else 's'}",
                "subtext": (d.get("display") or "flex")
                            + (f" · {d.get('grid_columns')}" if d.get("display") == "grid" else "")}
    if t == "toc_sidebar":
        return {"kind": "text", "label": "Wiki sidebar",
                "text": d.get("title") or "On this page",
                "subtext": f"up to H{d.get('max_level') or 3}"}
    if t == "separator":
        return {"kind": "text", "label": "Divider", "text": "—"}
    if t == "icon":
        nm = (d.get("name") or "").strip()
        sz = d.get("size") or 32
        return {"kind": "text", "label": "Icon",
                "text": nm or "(none)",
                "subtext": f"{sz}px"}
    if t == "hero":
        h = (d.get("heading") or "").strip()
        sub = (d.get("subheading") or "").strip()
        n_buttons = len(d.get("buttons") or [])
        return {"kind": "text", "label": "Hero",
                "text": h or "(no heading set)",
                "subtext": (sub[:120] if sub else "")
                            + ((" · " if sub else "") + f"{n_buttons} button"
                               + ("" if n_buttons == 1 else "s") if n_buttons else "")}
    if t == "meetings":
        cap = d.get("max_count") or 6
        flt = d.get("filter") or "upcoming_today"
        return {"kind": "text", "label": "Meetings list",
                "text": (d.get("heading") or "Upcoming Meetings"),
                "subtext": f"{flt} · max {cap}" + (" · grouped by day" if d.get("group_by_day") else "")}
    if t == "events":
        cap = d.get("max_count") or 6
        return {"kind": "text", "label": "Upcoming events",
                "text": (d.get("heading") or "Upcoming Events"),
                "subtext": f"max {cap}"}
    if t == "features":
        n = len(d.get("items") or [])
        h = (d.get("heading") or "").strip()
        return {"kind": "text", "label": "Features",
                "text": h or "(no heading set)",
                "subtext": f"{n} card" + ("" if n == 1 else "s")}
    if t == "faq":
        n = len(d.get("items") or [])
        cols = 2 if str(d.get("columns") or 1) == "2" else 1
        wm = d.get("width_mode") or "boxed"
        sub_bits = [f"{n} item" + ("" if n == 1 else "s"),
                    f"{cols} col"]
        if wm == "full":
            sub_bits.append("full-width")
        return {"kind": "text", "label": "FAQ",
                "text": (d.get("heading") or "Frequently asked questions"),
                "subtext": " · ".join(sub_bits)}
    return {"kind": "text", "label": t or "block"}


def _walk_blocks_by_id(sections):
    """Yield (block_id, block) for every block in `sections`, recursing
    into containers. Used by the page-edit template to attach a
    preview payload to each pill in the structure tree + orphan bin."""
    def _walk(blocks):
        for b in (blocks or []):
            if not isinstance(b, dict):
                continue
            bid = b.get("id")
            if bid:
                yield bid, b
            if b.get("type") == "container":
                yield from _walk((b.get("data") or {}).get("blocks") or [])
    for sec in (sections or []):
        if isinstance(sec, dict):
            yield from _walk(sec.get("blocks") or [])


def _page_active_tree(page):
    """Walk the page's blocks_json into the visualisation shape consumed
    by `structure_page_tree`. Returns `{tree, orphans}` where `tree` is
    a list of row entries:

      {type:'block', block_id, t}              — single pill
      {type:'columns', cols: [[…blocks…], …]}  — multi-column row whose
                                                 cells are themselves
                                                 lists of pills
      {type:'section_label', label}            — section heading divider

    `orphans` is a flat list of `{t, block_id}` pills representing the
    orphan-bin section's contents (or empty if there is no bin). The
    page editor renders orphans as a separate "Unplaced blocks" card
    the admin drags from. Public render skips orphan sections.

    Top-level container blocks whose `display=grid` parses to >1 column
    (or `display=flex direction=row`) become a multi-column row whose
    cells list the container's direct children. Other block types stay
    as single pills carrying their unique `block_id` so the editor modal
    can scroll-and-focus on click."""
    import json as _json
    import re as _re
    if not page or not page.blocks_json:
        return {"tree": [], "orphans": []}
    try:
        sections = _json.loads(page.blocks_json) or []
    except (ValueError, TypeError):
        return {"tree": [], "orphans": []}

    def _grid_col_count(grid_cols):
        # Count column tracks in a grid-template-columns spec.
        # `repeat(N, …)` returns N. Otherwise, count whitespace-separated
        # tokens (so "1fr 1fr" → 2). Returns 0 if unparseable.
        #
        # `auto-fit` / `auto-fill` grids have variable column counts at
        # render time — there's no fixed N the structure tree can map
        # cells to. Treat them as single-column so the editor stacks
        # children flat (the public render still flows them as a grid).
        if not grid_cols:
            return 0
        s = grid_cols.strip()
        if "auto-fit" in s or "auto-fill" in s:
            return 1
        m = _re.match(r"\s*repeat\(\s*(\d+)\s*,", s)
        if m:
            try: return int(m.group(1))
            except (ValueError, TypeError): return 0
        return len([t for t in s.split() if t.strip()])

    def _block_node(b):
        """Recursively walk a block, producing a structure-tree node:

          • {type:'block',   t, block_id}              — leaf pill
          • {type:'columns', block_id, cols:[[node,…],…]} — container row

        EVERY container becomes a 'columns' node — single-column or
        multi-column — so the structure card always exposes a
        container's contents as their own row(s) with their own drop
        zones. Cells contain other nodes recursively, so a Container
        nested inside a column renders AS a row inside that cell, with
        its own droppable cells, ad infinitum. This lets the admin
        compose arbitrarily deep nested layouts directly from the
        structure card without diving into the focused modal."""
        if not isinstance(b, dict):
            return None
        t = b.get("type")
        if not t:
            return None
        if t != "container":
            return {"type": "block", "t": t, "block_id": b.get("id") or ""}
        d = b.get("data") or {}
        kids = [c for c in (d.get("blocks") or []) if isinstance(c, dict)]
        display_mode = (d.get("display") or "flex").lower()
        flex_direction = (d.get("direction") or "column").lower()
        n_cols = 1
        if display_mode == "grid":
            # Grid containers retain their N-cell visualisation — that's
            # how the public CSS lays them out, so the editor mirrors it.
            n_cols = max(1, _grid_col_count(d.get("grid_columns") or "") or 1)
        # Flex containers ALWAYS render as a single zone in the editor,
        # regardless of `direction`. Splitting flex-row children into
        # per-cell columns misrepresented how flexbox works (children
        # are siblings inside one container, not isolated tracks) and
        # left the admin unable to drag siblings between cells. The
        # cell receives a `flex_direction` flag so the template / CSS
        # can flow pills in the configured direction inside it.
        cells = [[] for _ in range(n_cols)]
        # Round-robin distribution mirrors CSS grid's default
        # `grid-auto-flow: row` (item i lands in column `i mod n_cols`),
        # so 6 items in a 3-col grid stack as col0:[0,3], col1:[1,4],
        # col2:[2,5] in the editor instead of dumping everything past
        # the column count into the last cell. Flex containers (n_cols=1)
        # land every child in the single cell preserving source order.
        for i, child in enumerate(kids):
            node = _block_node(child)
            if node is not None:
                cells[i % n_cols].append(node)
        return {
            "type": "columns",
            "block_id": b.get("id") or "",
            "label": (d.get("label") or "").strip(),
            "display_mode": display_mode,
            "flex_direction": flex_direction,
            "cols": cells,
        }

    out = []
    orphans = []
    for si, sec in enumerate(sections):
        if not isinstance(sec, dict):
            continue
        if sec.get("_orphans"):
            for b in (sec.get("blocks") or []):
                if not isinstance(b, dict):
                    continue
                t = b.get("type")
                if not t:
                    continue
                orphans.append({"t": t, "block_id": b.get("id") or ""})
            continue
        title = (sec.get("title") or "").strip()
        if title:
            out.append({"type": "section_label", "label": title})
        for b in (sec.get("blocks") or []):
            node = _block_node(b)
            if node is not None:
                out.append(node)
    return {"tree": out, "orphans": orphans}


@bp.route("/frontend/pages/new")
@admin_required
def frontend_page_new():
    # Legacy URL — the New-page flow now lives in a modal on the
    # pages list. Anyone reaching this URL directly (bookmark or
    # stale link) is bounced back so they hit the modal.
    return redirect(url_for("main.frontend_pages"))


@bp.route("/frontend/pages/create", methods=["POST"])
@admin_required
def frontend_page_create():
    """Create a new page from the New-page modal: just a title +
    layout choice. Stamps the chosen layout's blocks (so the admin
    drops into a ready-shaped editor) and routes straight into the
    edit screen for the freshly-created row. The full block / page-
    settings editor lives there — this endpoint deliberately accepts
    only the minimum fields needed to mint the row."""
    import json as _json
    from .models import Page
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("Page title required", "danger")
        return redirect(url_for("main.frontend_pages"))
    raw_key = (request.form.get("layout_key") or "custom").strip() or "custom"
    layouts = _page_layouts_for_picker()
    valid_keys = {l.key for l in layouts} | {"custom"}
    if raw_key not in valid_keys:
        raw_key = "custom"

    # Stamp the chosen preset's blocks into untitled shell sections.
    # Mirrors `frontend_page_layout_save` (no preserved/orphan logic
    # since this is a fresh page). 'custom' starts blank so the admin
    # can drag freely in the editor.
    blocks_payload = "[]"
    if raw_key != "custom":
        chosen = next((l for l in layouts if l.key == raw_key), None)
        if chosen:
            try:
                preset = _json.loads(chosen.blocks_json or "[]") or []
            except (ValueError, TypeError):
                preset = []
            shell_sections = []
            for entry in preset:
                b = _instantiate_preset_entry(entry)
                if b:
                    shell_sections.append({
                        "id": _uuid_short(), "title": "", "blocks": [b],
                    })
            blocks_payload = _json.dumps(shell_sections or [])

    # Slug uniqueness — same RESERVED set + suffix-bump loop the
    # save route uses, so the modal can't create a row that would
    # later conflict with a public frontend route.
    slug = _slugify_page(title)
    RESERVED = {"meetings", "meeting", "hyperlist", "submissionform",
                "printlist", "library", "events", "archive", "announcements",
                "announcement", "event", "api", "tspro", "static", "uploads",
                "pub", "site-branding", "request-access", "contact", "siteindex"}
    base_slug = slug
    n = 2
    while True:
        existing = Page.query.filter(Page.slug == slug).first()
        if not existing and slug not in RESERVED:
            break
        slug = f"{base_slug}-{n}"
        n += 1

    # Initial publish state: the modal posts a `status` of draft / published
    # / private. Default to draft so the admin lands on the editor with the
    # page hidden until they explicitly publish.
    raw_status = (request.form.get("status") or "draft").strip().lower()
    if raw_status not in ("draft", "published", "private"):
        raw_status = "draft"
    is_published = raw_status in ("published", "private")
    is_private = raw_status == "private"
    page = Page(title=title, slug=slug, layout_key=raw_key,
                blocks_json=blocks_payload, template="standard",
                is_published=is_published, is_private=is_private)
    db.session.add(page)
    db.session.commit()
    return redirect(url_for("main.frontend_page_edit", page_id=page.id))


@bp.route("/frontend/pages/<int:page_id>/edit")
@admin_required
def frontend_page_edit(page_id):
    import json as _json
    from .models import Page
    s = _get_site_setting()
    page = Page.query.get_or_404(page_id)
    layouts = _page_layouts_for_picker()
    active_layout = _page_active_layout(page, layouts)
    tree_data = _page_active_tree(page)
    # Per-block hover-preview payloads, keyed by block id. Built once
    # server-side so each pill can stamp its preview JSON without the
    # template having to reach into nested data structures.
    try:
        _sections_for_preview = _json.loads(page.blocks_json or "[]") or []
    except (ValueError, TypeError):
        _sections_for_preview = []
    block_previews = {}
    block_payloads = {}
    for bid, b in _walk_blocks_by_id(_sections_for_preview):
        block_previews[bid] = _block_preview(b)
        block_payloads[bid] = b
    # Hero-modal proxy — the dedicated `#page-hero-edit-modal` (a verbatim
    # copy of the homepage hero modal markup) reads its values off a
    # `site`-shaped object so the existing markup just works. Default
    # proxy = empty block data; JS repopulates the form when the admin
    # opens a specific hero block.
    hero_modal_vals = _hero_block_modal_proxy({})
    # Same pattern for the per-page meetings modal — verbatim reuse of
    # the homepage's `editor_meetings()` macro markup, fed a dict shim
    # that mirrors the homepage's `block_content._meetings` shape.
    meetings_modal_vals = _meetings_block_modal_proxy({})
    # And again for the per-page upcoming-events modal.
    events_modal_vals = _events_block_modal_proxy({})
    # Per-page features modal — heading + subheading rendered empty
    # server-side, cards list populated by JS on pill click.
    features_modal_vals = _features_block_modal_proxy({})
    # Per-page FAQ modal — same flash-prevention pattern (empty items
    # list server-side, JS clones template on pill click).
    faq_modal_vals = _faq_block_modal_proxy({})
    return render_template("frontend_page_edit.html", site=s, page=page,
                           blocks_json=page.blocks_json or "[]",
                           page_layouts=layouts,
                           active_layout=active_layout,
                           active_layout_key=(page.layout_key or "custom"),
                           active_layout_tree=tree_data["tree"],
                           active_layout_orphans=tree_data["orphans"],
                           active_layout_customized=_page_is_customized(page, active_layout),
                           block_previews=block_previews,
                           block_payloads=block_payloads,
                           page_block_catalog=_PAGE_BLOCK_CATALOG,
                           hero_modal_vals=hero_modal_vals,
                           hero_modal_buttons=[],
                           hero_modal_bg_image_url='',
                           hero_modal_bg_video_url='',
                           meetings_modal_vals=meetings_modal_vals,
                           events_modal_vals=events_modal_vals,
                           features_modal_vals=features_modal_vals,
                           faq_modal_vals=faq_modal_vals)


@bp.route("/frontend/pages/<int:page_id>/layout", methods=["POST"])
@admin_required
def frontend_page_layout_save(page_id):
    """Apply a layout preset (or the 'custom' sentinel) to a page.
    Selecting a preset overwrites the page's blocks_json with fresh
    blank instances of the layout's block types, dropping the admin
    into a pre-shaped editor; selecting 'custom' just records the key
    without touching content."""
    import json as _json
    from .models import Page
    page = Page.query.get_or_404(page_id)
    raw_key = (request.form.get("layout_key") or "").strip()
    if not raw_key:
        flash("Layout key required", "danger")
        return redirect(url_for("main.frontend_page_edit", page_id=page.id))
    layouts = _page_layouts_for_picker()
    valid_keys = {l.key for l in layouts} | {"custom"}
    if raw_key not in valid_keys:
        flash(f"Unknown page layout '{raw_key}'", "danger")
        return redirect(url_for("main.frontend_page_edit", page_id=page.id))
    page.layout_key = raw_key
    if raw_key != "custom":
        # Apply preset, idempotently AND non-destructively:
        #   • Each top-level layout entry stamps as its OWN untitled
        #     section in the page (so a layout `[split, container]`
        #     produces two sections — a 2-column hero and a single-
        #     column block area). `split` entries expand into a real
        #     2-column container at stamp time.
        #   • TITLED sections are always preserved verbatim (admin's
        #     own content like "Chat Conduct Policy").
        #   • UNTITLED sections (structural shells) get replaced —
        #     but blocks they contained are NOT lost. Existing leaf
        #     blocks (anything that isn't a container itself, plus
        #     containers that already hold meaningful content) get
        #     swept into an "orphan bin" section (`_orphans=true`,
        #     unrendered on the public side) so the admin can drag
        #     them back into the new layout from the editor's
        #     Unplaced-blocks card. Re-applying the same layout is
        #     still idempotent because untitled-shell stamping yields
        #     the same shape, and orphan content is the admin's
        #     prior edits — those stay in the bin until placed.
        chosen = next((l for l in layouts if l.key == raw_key), None)
        if chosen:
            try:
                preset = _json.loads(chosen.blocks_json or "[]") or []
            except (ValueError, TypeError):
                preset = []
            shell_sections = []
            for entry in preset:
                b = _instantiate_preset_entry(entry)
                if b:
                    shell_sections.append({
                        "id": _uuid_short(), "title": "", "blocks": [b],
                    })
            try:
                existing_sections = _json.loads(page.blocks_json or "[]") or []
            except (ValueError, TypeError):
                existing_sections = []
            existing_sections = [s for s in existing_sections if isinstance(s, dict)]
            preserved_titled = [
                s for s in existing_sections
                if (s.get("title") or "").strip() and not s.get("_orphans")
            ]
            # Existing orphan bin survives across layout switches — its
            # blocks get merged into the new bin alongside whatever the
            # CURRENT untitled-shell sections held that's worth saving.
            existing_orphans = []
            for s in existing_sections:
                if s.get("_orphans"):
                    existing_orphans.extend(s.get("blocks") or [])
            displaced = []
            for s in existing_sections:
                if s.get("_orphans"):
                    continue
                if (s.get("title") or "").strip():
                    continue
                # This was an untitled (structural) section — collect
                # its leaf blocks for the orphan bin. Containers that
                # are essentially-empty placeholders (no children, no
                # text content) are dropped silently; everything else
                # comes along.
                for b in (s.get("blocks") or []):
                    if _block_has_content(b):
                        displaced.append(b)
            orphan_blocks = existing_orphans + displaced
            new_sections = list(shell_sections) + preserved_titled
            if orphan_blocks:
                new_sections.append({
                    "id": _uuid_short(),
                    "title": "Unplaced blocks",
                    "_orphans": True,
                    "blocks": orphan_blocks,
                })
            if not new_sections:
                new_sections = [{"id": _uuid_short(), "title": "", "blocks": []}]
            page.blocks_json = _json.dumps(new_sections)
    db.session.commit()
    flash(f"Layout “{raw_key}” applied", "success")
    return redirect(url_for("main.frontend_page_edit", page_id=page.id))


def _block_has_content(b):
    """Return True if a block is worth preserving on a layout switch.
    Empty placeholders (a container with no children, a heading with
    no text, a paragraph with no markdown) get dropped silently so the
    orphan bin doesn't collect noise. Anything else — including
    half-edited blocks — gets preserved so the admin can drag them
    back into the new layout."""
    if not isinstance(b, dict):
        return False
    t = b.get("type")
    d = b.get("data") or {}
    if t == "container":
        kids = d.get("blocks") or []
        # A container is meaningful if it carries children OR explicit
        # styling overrides (admin tweaked padding/bg/etc.).
        if any(_block_has_content(c) for c in kids):
            return True
        return False
    if t == "paragraph":
        return bool((d.get("md") or "").strip())
    if t == "heading":
        return bool((d.get("text") or "").strip())
    if t == "image":
        return bool((d.get("src") or "").strip())
    if t == "video":
        return bool((d.get("src") or "").strip())
    if t == "code":
        return bool((d.get("code") or "").strip())
    if t == "callout":
        return bool((d.get("md") or "").strip()
                    or (d.get("title") or "").strip())
    if t == "list":
        items = [i for i in (d.get("items") or []) if (i or "").strip()]
        return bool(items)
    if t == "button":
        return bool((d.get("url") or "").strip()
                    or (d.get("label") or "").strip() != "Click here")
    if t == "toc_sidebar":
        # Sidebar is structural — useful enough to preserve.
        return True
    if t == "separator":
        # Dividers are throwaway; not worth orphan-binning.
        return False
    return True


def _instantiate_preset_entry(entry):
    """Convert a single layout-template entry into a real page block.

    Layout-template entries can carry a `data` field — its keys are
    merged on top of the type's blank defaults so prebuilt layouts can
    ship real styling (background colour, shadow preset, padding,
    border radius, etc.) that the page picks up on stamp. The user
    then edits these via the block's settings panel exactly like any
    other field, so the layout's visual choices become a starting
    point rather than a hard-coded constant.

    Splits expand into a 2-column container holding two inner
    containers (one per panel). Containers honour their nested
    `blocks` array (so a layout authored with a Container holding
    e.g. a Heading + Paragraph stamps that exact tree onto the page).
    Every other type maps to `_blank_page_block(t)` with the entry's
    `data` overrides merged in."""
    if not isinstance(entry, dict):
        return None
    t = entry.get("type")
    if not t:
        return None
    overrides = entry.get("data") if isinstance(entry.get("data"), dict) else {}
    # Pull blocks-list-shape overrides out of `overrides` so they
    # don't fight the recursion logic below for container-style entries.
    overrides = {k: v for k, v in overrides.items() if k != "blocks"}
    if t == "split":
        def _panel(items, panel_overrides=None):
            inner = _blank_page_block("container")
            inner["data"]["padding"] = "0"
            inner["data"]["gap"] = "1.25rem"
            inner["data"]["max_width"] = 0
            inner["data"]["width_mode"] = "full"
            if isinstance(panel_overrides, dict):
                inner["data"].update({k: v for k, v in panel_overrides.items()
                                       if k != "blocks"})
            inner["data"]["blocks"] = [
                ib for ib in (_instantiate_preset_entry(c) for c in (items or []))
                if ib
            ]
            return inner
        outer = _blank_page_block("container")
        outer["data"]["display"] = "grid"
        outer["data"]["grid_columns"] = "1fr 1fr"
        outer["data"]["gap"] = "2.5rem"
        outer["data"]["padding"] = "0"
        outer["data"]["align"] = "center"
        # Outer container's data overrides come from the split's
        # `data`. Per-panel overrides come from `data_left` / `data_right`
        # on the entry — that way a layout can style each panel
        # independently (e.g. tinted left, white right) without
        # having to expand the split into raw containers manually.
        outer["data"].update(overrides)
        outer["data"]["blocks"] = [
            _panel(entry.get("left"), entry.get("data_left")),
            _panel(entry.get("right"), entry.get("data_right")),
        ]
        return outer
    if t == "container":
        block = _blank_page_block("container")
        block["data"].update(overrides)
        children = entry.get("blocks") if isinstance(entry, dict) else None
        block["data"]["blocks"] = [
            ib for ib in (_instantiate_preset_entry(c) for c in (children or []))
            if ib
        ]
        return block
    # Leaf type — merge overrides on top of the blank defaults so
    # things like a heading's font / size / colour land pre-styled.
    block = _blank_page_block(t)
    if isinstance(block.get("data"), dict):
        block["data"].update(overrides)
    return block


def _uuid_short():
    from uuid import uuid4
    return uuid4().hex[:8]


def _blank_page_block(t):
    """Server-side mirror of BlockEditor.js `blankBlock(type)`. Used
    when applying a layout preset — populates a fresh content block of
    the requested type with the SAME minimal defaults the JS editor
    would set on a `+ <type>` click.

    Defaults are deliberately UNSTYLED. Containers ship transparent
    (no bg / border / shadow / radius), with no padding, gap, or
    max-width constraint — width_mode='full' so they fill their
    parent without imposing any chrome. Images ship with no alignment
    override and full natural width capped at the parent (max_width_pct=100).
    Layout primitives (display/direction/justify/align) keep their
    CSS-default values so a freshly-dropped container behaves like a
    plain `<div>` until the admin styles it.

    Unknown types fall through to an empty paragraph so a corrupted
    preset doesn't 500 the route."""
    # Typography colour fields carry a `_dark` (dark-mode hex) and
    # `_dark_mode` ('same' | 'auto' | 'manual') alongside the light
    # value, so a single picker UI can drive both modes. The renderer
    # emits `_dark` as a CSS custom property when non-empty; a global
    # rule under `html[data-theme="dark"]` swaps it in. Default mode
    # is 'same' (no dark override) so existing pages render unchanged.
    TYPO_DARK = {"color_dark": "", "color_dark_mode": "same"}
    DEFAULTS = {
        "paragraph": {"md": "", **TYPO_DARK},
        "heading":   {"level": 3, "text": "", **TYPO_DARK},
        "image":     {"src": "", "alt": "", "caption": "",
                       "max_width_pct": 100, "align": "",
                       "caption_color": "", "caption_size": ""},
        # Icon block — `name` is an icon ref accepted by the `icon()`
        # Jinja helper (Lucide name like "heart" or `custom:<id>` for
        # admin-uploaded icons). Size is rendered as `font-size` on the
        # wrapper since `.icon` is sized via `1em`. Colour rides the
        # standard `*_dark` / `*_dark_mode` triplet so the same picker
        # as headings/paragraphs drives both modes. Align controls the
        # block's flex alignment within its parent. URL turns the icon
        # into a click-through link.
        "icon":      {"name": "", "size": 32,
                       "color": "", "color_dark": "", "color_dark_mode": "same",
                       "align": "center",
                       "url": "", "new_tab": False},
        "video":     {"src": "", "poster": ""},
        "code":      {"lang": "", "code": ""},
        "callout":   {"variant": "info", "title": "", "md": ""},
        # List block — `display_style` switches presentation (plain
        # ul/ol, numbered cards, checklist, arrows, inline pills).
        # When the admin picks 'cards', the `card_*` fields below
        # carry visual overrides that the renderer applies as inline
        # styles + CSS custom properties on `.fe-pp-steps` / `.fe-pp-
        # step` / `.fe-pp-step-num`. Empty strings = inherit the
        # default look (matches `.fe-meeting-card` chrome).
        "list":      {
            "ordered": False, "items": [""], "bullet_style": "",
            "display_style": "",  # '' | 'cards' | 'checklist' | 'arrows' | 'pills'
            # Card-only overrides (only applied when display_style='cards')
            "card_bg": "", "card_bg_dark": "", "card_bg_dark_mode": "same",
            "card_border_color": "", "card_border_color_dark": "",
            "card_border_color_dark_mode": "same",
            "card_border_radius": "",     # CSS px / '' = default 16px
            "card_padding": "",           # CSS shorthand / '' = default 18px 22px
            "card_gap": "",               # CSS gap value / '' = default 14px
            "card_shadow": "",            # '' | 'none' | 'sm' | 'md' | 'lg' | 'xl'
            "card_hover_lift": True,      # bool toggle for translateY(-2px) + shadow on hover
            "card_num_bg": "", "card_num_bg_dark": "",
            "card_num_bg_dark_mode": "same",
            "card_num_color": "", "card_num_color_dark": "",
            "card_num_color_dark_mode": "same",
            **TYPO_DARK,
        },
        "separator": {},
        "button":    {
            "label": "Click here", "url": "", "align": "left",
            "style": "primary", "new_tab": False,
            "bg": "", "hover_bg": "", "text_color": "", "hover_text": "",
            "border": "", "hover_border": "", "shadow": "",
        },
        "container": {
            # Admin-only label surfaced in the page-edit structure tree
            # (next to "Container" / "N-column row") so admins can tell
            # at a glance what a given container is for. Public render
            # ignores it.
            "label": "",
            "display": "flex", "direction": "column",
            "justify": "flex-start", "align": "stretch", "wrap": False,
            "grid_columns": "repeat(2, 1fr)",
            "gap": "0", "padding": "0",
            "width_mode": "full", "max_width": 0,
            "bg_color": "", "bg_color_dark": "", "bg_color_dark_mode": "same",
            "border_width": 0, "border_style": "solid",
            "border_color": "", "border_color_dark": "", "border_color_dark_mode": "same",
            "border_radius": 0, "shadow": "none",
            "hover_bg_color": "", "hover_border_color": "",
            "hover_shadow": "", "hover_lift": False,
            "blocks": [],
        },
        "toc_sidebar": {
            "title": "On this page",
            "max_level": 3,           # include h2..h<max_level>
            "sticky": True,
            "sticky_offset": 96,      # px from top when sticky
        },
        # Intergroup member block — references one officer row in the
        # IntergroupOfficer table by id. Public renderer looks up the
        # row at request time so changes to officer info propagate
        # without re-saving every page that uses the block. Each
        # `show_*` toggle gates one field; if all four are off, the
        # block renders nothing visible (defensive — lets admins
        # temporarily hide a block without removing it).
        "intergroup_member": {
            "officer_id": 0,
            "show_role": True,
            "show_name": True,
            "show_phone": True,
            "show_email": True,
        },
        # Intergroup officer roster — loops every IntergroupOfficer
        # row into a configurable card grid. `columns` is 2 or 3.
        # `gap` accepts any CSS length. Field toggles match the single-
        # member block so the same fields-shown decision rides through
        # to every card in the grid.
        "intergroup_member_roster": {
            "columns": 3,
            "gap": "1rem",
            "show_role": True,
            "show_name": True,
            "show_phone": True,
            "show_email": True,
        },
        # Library block — renders a Library's items in a chosen style.
        # `mode='all'` shows every item in the library; `mode='granular'`
        # shows only those whose ids are in `item_ids` (admin hand-picks
        # a subset). Style picks the visual treatment: 'bulleted' (UL
        # with markers), 'list' (plain stacked list), 'cards' (grid
        # with optional thumbnails). The block re-fetches items at
        # request time so admin edits to the library propagate without
        # re-saving every page that references it.
        "library": {
            "library_id": 0,
            "mode": "all",          # 'all' | 'granular'
            "item_ids": [],
            "style": "cards",       # 'bulleted' | 'list' | 'cards'
            "columns": 2,           # cards-only: 1 / 2 / 3
            "gap": "1rem",
            "show_description": True,
            "show_thumbnails": True,
            "show_categories": True,
            "title": "",
        },
        # Lottie animation block — `src` points at a Bodymovin/Lottie
        # JSON file (uploaded via the file picker -> /pub/<filename>, or
        # an external URL). The public renderer emits a wrapper div with
        # `data-lottie-*` attributes and pages that contain at least one
        # lottie block load `vendor/lottie/lottie.min.js` plus a small
        # init script that calls `lottie.loadAnimation` against each
        # wrapper. Speed is clamped to [0.25, 3.0]; size mirrors the
        # image block (max_width_pct + align). Background is optional —
        # most Lottie animations are transparent.
        "lottie": {
            "src": "",
            "loop": True,
            "autoplay": True,
            "speed": 1,
            "max_width_pct": 100,
            "align": "center",
            "bg_color": "",
            "renderer": "svg",  # svg | canvas — lottie-web's two main render modes
            # Playback mode. 'auto' respects autoplay/loop directly.
            # 'hover' parks the animation at frame 0, plays forward on
            # mouseenter, and reverses back to frame 0 on mouseleave —
            # the public-side init script wires up the listeners and the
            # frame watcher that pauses on reaching frame 0.
            "playback": "auto",
        },
    }
    data = DEFAULTS.get(t, {"md": ""})
    real_t = t if t in DEFAULTS else "paragraph"
    return {"id": _uuid_short(), "type": real_t, "data": data}


def _slugify_page(value):
    import re as _re
    value = (value or "").strip().lower()
    value = _re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "page"


PAGE_BG_EXTS = {"png", "jpg", "jpeg", "webp", "gif", "svg"}


@bp.route("/frontend/pages/save", methods=["POST"])
@admin_required
def frontend_page_save():
    import json as _json
    import os as _os
    from uuid import uuid4 as _uuid4
    from .models import Page
    page_id = (request.form.get("page_id") or "").strip()
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("Title is required", "danger")
        return redirect(_safe_referrer() or url_for("main.frontend_pages"))
    slug = _slugify_page(request.form.get("slug") or title)
    # Layout style toggle was removed — every page is "standard". Wiki
    # behaviour is now achieved by selecting the wiki layout PRESET,
    # which stamps a 2-column layout with a `toc_sidebar` block in the
    # right column. The `template` column is kept for back-compat but
    # always written as 'standard' from this route.
    tmpl = "standard"
    # Three-way visibility — `status` posts as draft / published / private.
    # Falls back to the legacy single-checkbox `is_published` field when the
    # form doesn't carry the new radio (older flows / API calls).
    raw_status = (request.form.get("status") or "").strip().lower()
    if raw_status in ("draft", "published", "private"):
        is_published = raw_status in ("published", "private")
        is_private = raw_status == "private"
    else:
        is_published = request.form.get("is_published") == "1"
        is_private = request.form.get("is_private") == "1"
    # Only update blocks_json when the form carries an actual value.
    # An empty/missing value means the editor didn't serialise — usually
    # a JS hiccup or a partial form submit (e.g. uploading a background
    # without touching the editor). Defaulting to "[]" here would wipe
    # the page's content; preserving the existing column is the safe
    # default. Admins can still clear a page by deleting it outright.
    raw_blocks = request.form.get("blocks_json")
    blocks_json_to_save = None
    if raw_blocks is not None and raw_blocks.strip() != "":
        try:
            _json.loads(raw_blocks)
            blocks_json_to_save = raw_blocks
        except (ValueError, TypeError):
            flash("Invalid blocks JSON", "danger")
            return redirect(_safe_referrer() or url_for("main.frontend_pages"))

    bg_mode = (request.form.get("bg_mode") or "cover").strip().lower()
    if bg_mode not in ("cover", "tile"):
        bg_mode = "cover"
    try:
        bg_tile_scale = int(request.form.get("bg_tile_scale") or 100)
    except (TypeError, ValueError):
        bg_tile_scale = 100
    bg_tile_scale = max(25, min(bg_tile_scale, 400))

    # Page-wide width formatting.
    width_mode = (request.form.get("width_mode") or "boxed").strip().lower()
    if width_mode not in ("boxed", "full"):
        width_mode = "boxed"
    try:
        max_width = int(request.form.get("max_width") or 1160)
    except (TypeError, ValueError):
        max_width = 1160
    max_width = max(640, min(max_width, 1600))
    try:
        full_padding_pct = int(request.form.get("full_padding_pct") or 4)
    except (TypeError, ValueError):
        full_padding_pct = 4
    full_padding_pct = max(0, min(full_padding_pct, 20))

    # Page-shell spacing knobs. All four are px integers with 0 as
    # the minimum (true flush) and a generous upper bound for over-
    # padded layouts. Missing form fields fall back to the legacy
    # defaults so a partial submit (older client / API call) doesn't
    # zero anything out unintentionally.
    def _clamp_px(name, lo, hi, default):
        try:
            v = int(request.form.get(name) or default)
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))
    pad_top = _clamp_px("pad_top", 0, 400, 80)
    pad_bottom = _clamp_px("pad_bottom", 0, 400, 96)
    pad_x = _clamp_px("pad_x", 0, 200, 16)
    section_gap = _clamp_px("section_gap", 0, 200, 32)
    block_margin_y = _clamp_px("block_margin_y", 0, 80, 12)

    # Typography overrides — color hex (#rgb / #rrggbb), font key,
    # alignment. Blank values clear the override and let the theme
    # take over.
    import re as _re_color
    _hex_re = _re_color.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

    def _norm_color(v):
        v = (v or "").strip()
        if not v:
            return None
        # Accept token:<key> for any color token defined under
        # Settings → Design → Colors. The render path translates these
        # to var(--fe-color-<key>) via the css_color filter, so a
        # token edit propagates everywhere the value is consumed.
        if v.startswith("token:"):
            from .design import DESIGN_FIELDS_BY_KEY as _DFK
            key = v[6:]
            f = _DFK.get(key)
            return ("token:" + key) if (f and f.get("kind") == "color") else None
        return v if _hex_re.match(v) else None

    def _norm_font(v):
        from .fonts import font_by_key
        v = (v or "").strip()
        return v if v and font_by_key(v) else None

    # Typography controls were removed from the page edit UI; per-block
    # styling now lives on the heading / paragraph / container blocks
    # themselves. We only touch these page-level columns when the form
    # explicitly posts the field, so legacy values on existing pages
    # survive a save round-trip from the slimmed-down form.
    has_heading_color    = "heading_color"    in request.form
    has_subheading_color = "subheading_color" in request.form
    has_heading_font     = "heading_font"     in request.form
    has_subheading_font  = "subheading_font"  in request.form
    has_heading_align    = "heading_align"    in request.form
    heading_color    = _norm_color(request.form.get("heading_color"))    if has_heading_color    else None
    subheading_color = _norm_color(request.form.get("subheading_color")) if has_subheading_color else None
    heading_font     = _norm_font(request.form.get("heading_font"))      if has_heading_font     else None
    subheading_font  = _norm_font(request.form.get("subheading_font"))   if has_subheading_font  else None
    heading_align    = (request.form.get("heading_align") or "auto").strip().lower() if has_heading_align else None
    if has_heading_align and heading_align not in ("auto", "left", "center", "right"):
        heading_align = "auto"

    if page_id:
        page = Page.query.get_or_404(int(page_id))
    else:
        page = Page()

    # Set the NOT NULL columns up front. Once the Page is added to
    # the session below, ANY subsequent query that triggers
    # SQLAlchemy's autoflush would try to insert the row with all the
    # NULL columns the model has marked nullable=False (slug, title,
    # template, blocks_json default, etc.) and crash with an
    # IntegrityError. Setting them here means the autoflush a few
    # lines down (the slug-uniqueness query) can write a valid row.
    page.title = title
    page.template = tmpl
    page.is_published = is_published
    page.is_private = bool(is_private)
    if blocks_json_to_save is not None:
        page.blocks_json = blocks_json_to_save
    elif page.id is None:
        # Brand-new page — initialise to an empty list so the column
        # isn't NULL when the row is inserted.
        page.blocks_json = "[]"

    # Reserve slugs that collide with existing public frontend routes so
    # the catch-all /<slug> page route never shadows them. We need a
    # fully-resolved slug BEFORE adding the new row to the session
    # because the uniqueness query below triggers an autoflush, and
    # the row needs `slug` non-NULL by then.
    RESERVED = {"meetings", "meeting", "hyperlist", "submissionform",
                "printlist", "library", "events", "archive", "announcements",
                "announcement", "event", "api", "tspro", "static", "uploads",
                "pub", "site-branding", "request-access", "contact", "siteindex"}
    base_slug = slug
    n = 2
    # Disable autoflush during the uniqueness probe — the new Page
    # row hasn't been fully populated yet and a premature flush would
    # crash on NOT NULL fields. Using `no_autoflush` is safer than
    # relying on order alone since future fields could re-introduce
    # the same race.
    with db.session.no_autoflush:
        while True:
            existing = Page.query.filter(Page.slug == slug,
                                         Page.id != (page.id or -1)).first()
            if not existing and slug not in RESERVED:
                break
            slug = f"{base_slug}-{n}"
            n += 1
    page.slug = slug

    if not page_id:
        db.session.add(page)

    # Background upload + remove handling. Removal wins over upload so an
    # admin can clear the image and pick a new one in the same submit.
    if request.form.get("clear_bg") == "1":
        page.bg_image_filename = None
    bg_upload = request.files.get("bg_image")
    if bg_upload and bg_upload.filename:
        ext = bg_upload.filename.rsplit(".", 1)[-1].lower() if "." in bg_upload.filename else ""
        if ext not in PAGE_BG_EXTS:
            flash(f"Unsupported background type .{ext}. Allowed: {', '.join(sorted(PAGE_BG_EXTS))}.",
                  "danger")
            return redirect(_safe_referrer() or url_for("main.frontend_pages"))
        safe = secure_filename(bg_upload.filename) or f"page-bg.{ext}"
        stored = f"{_uuid4().hex}_{safe}"
        bg_upload.save(_os.path.join(current_app.config["UPLOAD_FOLDER"], stored))
        page.bg_image_filename = stored
    page.bg_mode = bg_mode
    page.bg_tile_scale = bg_tile_scale
    # Dynamic-background catalog key (None = no dynbg). Coerced through
    # the catalog so a tampered POST can only land on a known key.
    from . import dynbg as _dynbg
    page.bg_dynamic_key = _dynbg.normalize(request.form.get("bg_dynamic_key"))
    page.bg_dynbg_config_json = _dynbg_config_from_form(request.form, "bg_dynbg_config_json")
    # Background colour — accepts either a hex literal or a design-
    # token reference of the form `token:<key>`. Tokens stay live: at
    # render time the public template emits `var(--fe-color-<key>)`
    # so a token edit in Settings → Design propagates immediately to
    # every page using it. Validation:
    #   • hex   → tight regex (#rgb / #rrggbb)
    #   • token → only accepted if the key matches a DESIGN_FIELDS
    #             entry whose kind == 'color' (rejects bogus keys)
    # Hidden marker `bg_color_present` gates assignment so a partial
    # POST can't wipe a previously-set value.
    if request.form.get("bg_color_present") == "1":
        import re as _bgc_re
        from .design import DESIGN_FIELDS_BY_KEY as _DFK
        _hex = _bgc_re.compile(r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")
        _tok = _bgc_re.compile(r"^token:([a-z0-9_]+)$", _bgc_re.IGNORECASE)
        def _coerce_bg(v):
            v = (v or "").strip()
            if not v:
                return None
            m = _tok.match(v)
            if m:
                key = m.group(1)
                f = _DFK.get(key)
                if f and f.get("kind") == "color":
                    return "token:" + key
                return None
            return v if _hex.match(v) else None
        bg_mode = (request.form.get("bg_color_dark_mode") or "same").strip().lower()
        if bg_mode not in ("same", "auto", "manual"):
            bg_mode = "same"
        page.bg_color = _coerce_bg(request.form.get("bg_color"))
        page.bg_color_dark = _coerce_bg(request.form.get("bg_color_dark"))
        page.bg_color_dark_mode = bg_mode
    page.width_mode = width_mode
    page.max_width = max_width
    page.full_padding_pct = full_padding_pct
    page.pad_top = pad_top
    page.pad_bottom = pad_bottom
    page.pad_x = pad_x
    page.section_gap = section_gap
    page.block_margin_y = block_margin_y
    if has_heading_color:    page.heading_color    = heading_color
    if has_subheading_color: page.subheading_color = subheading_color
    if has_heading_font:     page.heading_font     = heading_font
    if has_subheading_font:  page.subheading_font  = subheading_font
    if has_heading_align:    page.heading_align    = heading_align

    # Per-page Open Graph overrides. Blank values clear the column so
    # the public render falls back to the site-wide frontend_og_*
    # defaults set under Web Frontend → Branding & SEO. Hidden marker
    # `og_present` gates assignment so a partial POST (e.g. the
    # background-only sub-form) can't wipe previously-set OG values.
    if request.form.get("og_present") == "1":
        page.og_title = (request.form.get("og_title") or "").strip()[:200] or None
        page.og_description = (request.form.get("og_description") or "").strip() or None
        if request.form.get("clear_og_image") == "1":
            old_og = page.og_image_filename
            page.og_image_filename = None
            _cleanup_retired_asset(old_og)
        og_upload = request.files.get("og_image")
        if og_upload and og_upload.filename:
            old_og = page.og_image_filename
            stored_og, _orig = _save_upload(og_upload)
            page.og_image_filename = stored_og
            if old_og and old_og != stored_og:
                _cleanup_retired_asset(old_og)

    db.session.commit()
    flash(f"Page “{title}” saved", "success")
    return redirect(url_for("main.frontend_page_edit", page_id=page.id))


@bp.route("/frontend/pages/<int:page_id>/delete", methods=["POST"])
@admin_required
def frontend_page_delete(page_id):
    from .models import Page
    page = Page.query.get_or_404(page_id)
    title = page.title
    db.session.delete(page)
    db.session.commit()
    flash(f"Page “{title}” deleted", "success")
    return redirect(url_for("main.frontend_pages"))


def _apply_page_status(page, status):
    """Resolve a 'draft' / 'published' / 'private' status string onto a
    Page row's ``is_published`` + ``is_private`` flags. Returns True when
    the status was recognised and applied; False for unknown values."""
    if status == "draft":
        page.is_published = False
        page.is_private = False
    elif status == "published":
        page.is_published = True
        page.is_private = False
    elif status == "private":
        page.is_published = True
        page.is_private = True
    else:
        return False
    return True


@bp.route("/frontend/pages/<int:page_id>/status", methods=["POST"])
@admin_required
def frontend_page_status(page_id):
    """Quick-action endpoint that flips a single page's visibility from
    the edit screen's status pills (Draft / Publish / Private) without
    requiring a full form round-trip through ``frontend_page_save``."""
    from .models import Page
    page = Page.query.get_or_404(page_id)
    status = (request.form.get("status") or "").strip().lower()
    if not _apply_page_status(page, status):
        flash("Unknown status", "danger")
        return redirect(url_for("main.frontend_page_edit", page_id=page.id))
    db.session.commit()
    flash(f"Page “{page.title}” marked {status}", "success")
    return redirect(_safe_referrer()
                    or url_for("main.frontend_page_edit", page_id=page.id))


@bp.route("/frontend/pages/<int:page_id>/set-homepage", methods=["POST"])
@admin_required
def frontend_page_set_homepage(page_id):
    """Designate `page_id` as the Page that renders at the public `/`
    root (`SiteSetting.homepage_page_id`). Pages can be promoted /
    demoted freely — the public route reads the current value on every
    request, so there's no cache to invalidate. The previous homepage
    (if any) is left in place as a regular content page; nothing about
    its row changes other than no longer being the homepage."""
    from .models import Page
    page = Page.query.get_or_404(page_id)
    if not page.is_published:
        # Make the page publishable in one step — admins shouldn't have
        # to flip status separately just to designate a homepage. This
        # mirrors the "publish + make homepage" intent of the button.
        page.is_published = True
        page.is_private = False
    s = _get_site_setting()
    s.homepage_page_id = page.id
    db.session.commit()
    flash(f"“{page.title}” is now the homepage", "success")
    return redirect(_safe_referrer()
                    or url_for("main.frontend_page_edit", page_id=page.id))


@bp.route("/frontend/pages/bulk", methods=["POST"])
@admin_required
def frontend_pages_bulk():
    """Bulk-status action invoked from the Pages list checkboxes. Posts
    a list of `page_ids` plus a `status`; applies the same draft /
    published / private flip to every selected row in one commit."""
    from .models import Page
    status = (request.form.get("status") or "").strip().lower()
    if status not in ("draft", "published", "private"):
        flash("Unknown bulk status", "danger")
        return redirect(url_for("main.frontend_pages"))
    raw_ids = request.form.getlist("page_ids")
    page_ids = []
    for raw in raw_ids:
        try:
            page_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not page_ids:
        flash("Select at least one page first", "warning")
        return redirect(url_for("main.frontend_pages"))
    rows = Page.query.filter(Page.id.in_(page_ids)).all()
    for row in rows:
        _apply_page_status(row, status)
    db.session.commit()
    flash(f"{len(rows)} page{'s' if len(rows) != 1 else ''} marked {status}",
          "success")
    return redirect(url_for("main.frontend_pages"))


@bp.route("/frontend/footer-save", methods=["POST"])
@admin_required
def frontend_footer_save():
    """Save the structured footer content + container settings (width
    mode, max width, padding %). The legacy plain-text `frontend_footer_text`
    field is still accepted for backwards compat — old templates that
    haven't migrated yet read from it as a copyright fallback."""
    import json as _json
    from .blocks import parse_footer
    s = _get_site_setting()
    # Width mode
    raw_w = (request.form.get("frontend_footer_width_mode") or "").strip().lower()
    s.frontend_footer_width_mode = raw_w if raw_w in ("boxed", "full") else "boxed"
    try:
        s.frontend_footer_max_width = max(640, min(int(request.form.get("frontend_footer_max_width") or 1160), 2400))
    except (TypeError, ValueError):
        s.frontend_footer_max_width = 1160
    try:
        s.frontend_footer_padding_pct = max(0, min(int(request.form.get("frontend_footer_padding_pct") or 5), 20))
    except (TypeError, ValueError):
        s.frontend_footer_padding_pct = 5
    # Background mode — 'dark' (default; footer always dark) or 'light'
    # (follows page theme).
    raw_bg = (request.form.get("frontend_footer_bg_mode") or "").strip().lower()
    s.frontend_footer_bg_mode = raw_bg if raw_bg in ("light", "dark") else "dark"
    # Min-height in vh (0 = no min-height; clamp 0-100).
    try:
        s.frontend_footer_min_height_vh = max(0, min(int(request.form.get("frontend_footer_min_height_vh") or 0), 100))
    except (TypeError, ValueError):
        s.frontend_footer_min_height_vh = 0
    # Font scale percentage — desktop-first; mobile media queries cap
    # the upper bound so a 200% setting doesn't blow out a phone view.
    try:
        s.frontend_footer_font_scale = max(50, min(int(request.form.get("frontend_footer_font_scale") or 100), 200))
    except (TypeError, ValueError):
        s.frontend_footer_font_scale = 100
    # Brand custom-logo upload — handled before parse_footer so the
    # uploaded filename ends up on `s.frontend_brand_logo_filename`. The
    # brand block's `logo_source` lives in the JSON content (see below)
    # and the public render dispatches on it. A `clear_brand_logo`
    # checkbox on the modal removes the file (the saved filename only;
    # the on-disk asset is left for cleanup later).
    if "footer_brand_present" in request.form:
        if request.form.get("clear_brand_logo") == "1":
            s.frontend_brand_logo_filename = None
        upload = request.files.get("frontend_brand_logo")
        if upload and upload.filename:
            from werkzeug.utils import secure_filename
            from uuid import uuid4
            import os
            safe = secure_filename(upload.filename) or "brand-logo"
            stored = f"{uuid4().hex}_{safe}"
            upload.save(os.path.join(current_app.config["UPLOAD_FOLDER"], stored))
            s.frontend_brand_logo_filename = stored
    # Structured content — only update if the form-level marker is
    # present. parse_footer is given the existing content so any section
    # whose editor card was hidden (because the active layout doesn't
    # use that block) preserves its saved values instead of being wiped.
    if "footer_blocks_present" in request.form:
        from .blocks import footer_content
        existing = footer_content(s)
        content = parse_footer(request.form, existing=existing)
        s.frontend_footer_blocks_json = _json.dumps(content)
    # Legacy single-textarea field — still supported.
    if "frontend_footer_text" in request.form:
        s.frontend_footer_text = (request.form.get("frontend_footer_text") or "").strip() or None
    db.session.commit()
    flash("Footer saved", "success")
    return redirect(url_for("main.frontend_footer"))


@public_bp.route("/site-branding/frontend-logo")
def site_frontend_logo():
    s = SiteSetting.query.first()
    if not s or not s.frontend_logo_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], s.frontend_logo_filename)


@public_bp.route("/site-branding/frontend-brand-logo")
def site_frontend_brand_logo():
    """Custom logo for the public footer's Brand block. Distinct from
    `frontend-logo` (the header logo) so admins can show one mark up
    top and a different mark down below if they want."""
    s = SiteSetting.query.first()
    if not s or not s.frontend_brand_logo_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], s.frontend_brand_logo_filename)


@public_bp.route("/site-branding/og-image")
def site_og_image():
    s = _get_site_setting()
    if not s.og_image_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], s.og_image_filename)


@public_bp.route("/site-branding/frontend-og-image")
def site_frontend_og_image():
    """Serves the frontend-specific OG image (set on the Web Frontend's
    Branding & SEO page). Distinct from /site-branding/og-image which
    serves the backend OG image used on /tspro pages."""
    s = _get_site_setting()
    if not s.frontend_og_image_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], s.frontend_og_image_filename)


@public_bp.route("/site-branding/frontend-favicon")
def site_frontend_favicon():
    """Serves the frontend-specific favicon if one was uploaded. The
    template falls back to the bundled static favicon.png when this
    column is empty."""
    s = _get_site_setting()
    if not s.frontend_favicon_filename:
        abort(404)
    response = send_from_directory(current_app.config["UPLOAD_FOLDER"], s.frontend_favicon_filename)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@public_bp.route("/site-branding/apple-touch-icon")
def site_apple_touch_icon():
    """Serves the admin /tspro home-screen icon when one was uploaded.
    The template falls back to the bundled static asset otherwise. Kept
    on the public blueprint so iOS — which fetches the icon anonymously
    when a visitor taps "Add to Home Screen" — can reach it without an
    auth bounce."""
    s = _get_site_setting()
    if not s.apple_touch_icon_filename:
        abort(404)
    response = send_from_directory(current_app.config["UPLOAD_FOLDER"], s.apple_touch_icon_filename)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@public_bp.route("/site-branding/frontend-apple-touch-icon")
def site_frontend_apple_touch_icon():
    """Serves the public web frontend home-screen icon when one was
    uploaded. Falls back to the bundled static asset otherwise."""
    s = _get_site_setting()
    if not s.frontend_apple_touch_icon_filename:
        abort(404)
    response = send_from_directory(current_app.config["UPLOAD_FOLDER"], s.frontend_apple_touch_icon_filename)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@bp.route("/settings/apple-touch-icon-save", methods=["POST"])
@admin_required
def apple_touch_icon_save():
    """Persists the admin /tspro home-screen icon (apple-touch-icon)
    and the display name shown under it on iOS / iPadOS home screens.
    Upload / clear semantics mirror the favicon and OG image handlers."""
    s = _get_site_setting()
    s.apple_touch_icon_name = (request.form.get("apple_touch_icon_name") or "").strip()[:100] or None
    if request.form.get("clear_apple_touch_icon") == "1":
        old = s.apple_touch_icon_filename
        s.apple_touch_icon_filename = None
        _cleanup_retired_asset(old)
    uploaded = request.files.get("apple_touch_icon")
    if uploaded and uploaded.filename:
        old = s.apple_touch_icon_filename
        stored, _original = _save_upload(uploaded)
        s.apple_touch_icon_filename = stored
        if old and old != stored:
            _cleanup_retired_asset(old)
    db.session.commit()
    flash("Home Screen icon updated", "success")
    return redirect(_safe_referrer() or url_for("main.index"))


@bp.route("/settings/og-save", methods=["POST"])
@admin_required
def og_save():
    s = _get_site_setting()
    s.og_enabled = request.form.get("og_enabled") == "1"
    s.og_title = (request.form.get("og_title") or "").strip()[:200] or None
    s.og_description = (request.form.get("og_description") or "").strip() or None
    if request.form.get("clear_og_image") == "1":
        old = s.og_image_filename
        s.og_image_filename = None
        _cleanup_retired_asset(old)
    uploaded = request.files.get("og_image")
    if uploaded and uploaded.filename:
        old = s.og_image_filename
        stored, _original = _save_upload(uploaded)
        s.og_image_filename = stored
        if old and old != stored:
            _cleanup_retired_asset(old)
    db.session.commit()
    flash("Open Graph settings updated", "success")
    return redirect(_safe_referrer() or url_for("main.index"))


# --- Files ---

@bp.route("/meetings/<slug>/files/new", methods=["GET", "POST"])
@editor_required
def file_new(slug):
    m = _resolve_meeting_by_slug(slug) or abort(404)
    category = request.values.get("category", "documents")
    if category not in FILE_CATEGORIES:
        category = "documents"
    if request.method == "POST":
        # public_visible is gated to admins + frontend editors. For other
        # users we ignore whatever the form says and force False on create.
        _public = (request.form.get("public_visible") == "1"
                   and current_user.can_edit_frontend())
        f = MeetingFile(
            meeting_id=m.id,
            category=category,
            title=request.form["title"].strip(),
            description=request.form.get("description", "").strip(),
            public_visible=_public,
        )
        if category in ("external_links", "videos"):
            f.url = request.form.get("url", "").strip()
        elif category in ("readings", "scripts"):
            f.body = request.form.get("body", "").strip()
            link = request.form.get("url", "").strip()
            if link:
                f.url = link
            _apply_file_upload(f, request.files.get("file"), request.form.get("media_id"))
        else:
            _apply_file_upload(f, request.files.get("file"), request.form.get("media_id"))
            link = request.form.get("url", "").strip()
            if link:
                f.url = link
        db.session.add(f)
        db.session.commit()
        flash("File added", "success")
        return redirect(url_for("main.meeting_detail", slug=m.public_slug) + f"#{category}")
    return render_template("file_form.html", meeting=m, category=category, file=None)


@bp.route("/files/<int:fid>/edit", methods=["GET", "POST"])
@editor_required
def file_edit(fid):
    f = db.session.get(MeetingFile, fid) or abort(404)
    if request.method == "POST":
        f.title = request.form["title"].strip()
        f.description = request.form.get("description", "").strip()
        f.url = request.form.get("url", "").strip() or None
        # Only admins + frontend editors may flip the public_visible flag —
        # other users' toggle in the UI is disabled, but we also enforce
        # server-side so a hand-crafted POST can't sneak through.
        if current_user.can_edit_frontend():
            f.public_visible = (request.form.get("public_visible") == "1")
        if f.category in ("readings", "scripts"):
            f.body = request.form.get("body", "").strip()
        _apply_file_upload(f, request.files.get("file"), request.form.get("media_id"))
        db.session.commit()
        flash("File updated", "success")
        return redirect(url_for("main.meeting_detail", slug=f.meeting.public_slug) + f"#{f.category}")
    return render_template("file_form.html", meeting=f.meeting, category=f.category, file=f)


@bp.route("/files/<int:fid>/public-toggle", methods=["POST"])
@editor_required
def file_public_toggle(fid):
    """Inline toggle for ``MeetingFile.public_visible`` from the meeting
    edit modal's file list. Reads ``public_visible=1|0`` from form data
    and returns JSON so the row can flip without closing the modal.

    Public visibility is gated to admins + frontend editors. Regular
    editors can land on this endpoint (the file list is shown to them)
    but can't actually flip the flag — return 403 instead of silently
    succeeding so the UI rolls back."""
    if not current_user.can_edit_frontend():
        abort(403)
    f = db.session.get(MeetingFile, fid) or abort(404)
    f.public_visible = (request.form.get("public_visible") == "1")
    db.session.commit()
    return jsonify({"ok": True, "public_visible": f.public_visible})


@bp.route("/meetings/<slug>/files/reorder", methods=["POST"])
@editor_required
def meeting_files_reorder(slug):
    m = _resolve_meeting_by_slug(slug) or abort(404)
    data = request.get_json(silent=True) or {}
    category = (data.get("category") or "").strip()
    ids = data.get("order") or []
    if not category or not isinstance(ids, list):
        return jsonify({"error": "invalid"}), 400
    items = {f.id: f for f in m.files.filter_by(category=category).all()}
    for pos, fid in enumerate(ids):
        try:
            fid = int(fid)
        except (TypeError, ValueError):
            continue
        f = items.get(fid)
        if f is not None:
            f.position = pos
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/files/<int:fid>/delete", methods=["POST"])
@editor_required
def file_delete(fid):
    f = db.session.get(MeetingFile, fid) or abort(404)
    parent_slug = f.meeting.public_slug
    cat = f.category
    title = f.title
    from . import trash, activity
    trash.soft_delete_meeting_file(f, current_user.id)
    activity.log("file.delete", entity_type="meeting_file", entity_id=fid,
                 summary=f"Deleted meeting attachment “{title}” (recoverable for {trash.RETENTION_DAYS} days)")
    flash("File moved to the Delete Log — restorable for 30 days.", "success")
    return redirect(url_for("main.meeting_detail", slug=parent_slug) + f"#{cat}")


@bp.route("/files/<int:fid>/view")
@login_required
def file_view(fid):
    f = db.session.get(MeetingFile, fid) or abort(404)
    if f.category in ("readings", "scripts") and f.body:
        return render_template("reading_view.html", title=f.title, body=f.body,
                               back_url=url_for("main.meeting_detail", slug=f.meeting.public_slug))
    if f.url:
        return redirect(f.url)
    if f.stored_filename:
        return redirect(url_for("main.file_download", fid=fid))
    abort(404)


@bp.route("/files/<int:fid>/download")
@login_required
def file_download(fid):
    f = db.session.get(MeetingFile, fid) or abort(404)
    if not f.stored_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"],
                               f.stored_filename,
                               as_attachment=False,
                               download_name=f.original_filename or f.stored_filename)


# --- Libraries ---

@bp.route("/libraries")
@login_required
def libraries():
    view = request.args.get("view") or request.cookies.get("view-libraries") or "table"
    sort = request.args.get("sort") or request.cookies.get("view-libraries-sort") or "name"
    direction = request.args.get("dir") or request.cookies.get("view-libraries-dir") or "asc"
    # Intergroup Documents and Intergroup Minutes are surfaced via the
    # Intergroup subsection in the sidebar (Email Accounts + Minutes +
    # Documents). They're managed through their dedicated entry points
    # rather than the generic libraries list, so we exclude them here
    # to keep the list focused on regular meeting / fellowship content.
    # Direct deep-link access (/libraries/<id>) still works for editors.
    # Hide Intergroup-flagged libraries — they're surfaced in the
    # dedicated Intergroup sidebar subsection instead.
    items = Library.query.filter(Library.is_intergroup == False).all()  # noqa: E712
    if sort == "files":
        items.sort(key=lambda l: (l.items.count(), l.name.lower()))
    else:
        items.sort(key=lambda l: l.name.lower())
    if direction == "desc":
        items.reverse()
    resp = current_app.make_response(
        render_template("libraries.html", libraries=items, view=view,
                        sort=sort, direction=direction))
    resp.set_cookie("view-libraries", view, max_age=60*60*24*365, samesite="Lax")
    resp.set_cookie("view-libraries-sort", sort, max_age=60*60*24*365, samesite="Lax")
    resp.set_cookie("view-libraries-dir", direction, max_age=60*60*24*365, samesite="Lax")
    return resp


@bp.route("/libraries/new", methods=["GET", "POST"])
@library_admin_required
def library_new():
    """Regular library creation — never produces an Intergroup library.
    Promotion into the Intergroup subsection happens through the
    dedicated admin-only ``intergroup_library_new`` route below, or by
    flipping the ``is_intergroup`` toggle in the library-edit modal."""
    if request.method == "POST":
        lib = Library(
            name=request.form["name"].strip(),
            description=request.form.get("description", "").strip(),
            alert_message=request.form.get("alert_message", "").strip() or None,
        )
        db.session.add(lib)
        db.session.commit()
        from . import activity
        activity.log("library.create", entity_type="library", entity_id=lib.id,
                     summary=f"Created library “{lib.name}”")
        flash("Library created", "success")
        return redirect(url_for("main.library_detail", slug=lib.public_slug))
    return render_template("library_form.html", library=None)


@bp.route("/intergroup/libraries/new", methods=["GET", "POST"])
@admin_required
def intergroup_library_new():
    """Admin-only entry point for creating an Intergroup library. The
    new row is force-flagged ``is_intergroup=True`` so it lands in the
    restricted Intergroup sidebar subsection straight away. Surfaced
    via the "+ Add Library" link under the Intergroup section."""
    if request.method == "POST":
        lib = Library(
            name=request.form["name"].strip(),
            description=request.form.get("description", "").strip(),
            alert_message=request.form.get("alert_message", "").strip() or None,
            is_intergroup=True,
        )
        db.session.add(lib)
        db.session.commit()
        from . import activity
        activity.log("library.create", entity_type="library", entity_id=lib.id,
                     summary=f"Created intergroup library “{lib.name}”")
        flash("Intergroup library created", "success")
        return redirect(url_for("main.library_detail", slug=lib.public_slug))
    return render_template("library_form.html", library=None, intergroup_create=True)


def _resolve_library_by_slug(slug):
    """Return the Library whose ``slugify(name)`` matches ``slug``,
    or ``None``. Case-insensitive on the URL side; the first match
    wins on the rare collision (admin can rename to disambiguate)."""
    from .colors import slugify
    target = (slug or "").lower()
    if not target:
        return None
    libs = Library.query.all()
    return next((l for l in libs if slugify(l.name) == target), None)


@bp.route("/libraries/<slug>")
@login_required
def library_detail(slug):
    """Slug-based library detail. Intergroup libraries continue to
    redirect to their dedicated /tspro/intergroup/<slug> URL so the
    address bar reflects which sidebar section the library lives in."""
    lib = _resolve_library_by_slug(slug) or abort(404)
    if lib.is_intergroup:
        return redirect(url_for("main.intergroup_library_detail",
                                slug=lib.public_slug), code=301)
    return render_template("library_detail.html", library=lib)


@bp.route("/libraries/<int:lid>")
@login_required
def library_detail_legacy(lid):
    """Legacy id-based URL — 301 to the slug equivalent so external
    bookmarks survive the rename."""
    lib = db.session.get(Library, lid) or abort(404)
    if lib.is_intergroup:
        return redirect(url_for("main.intergroup_library_detail",
                                slug=lib.public_slug), code=301)
    return redirect(url_for("main.library_detail", slug=lib.public_slug), code=301)


@bp.route("/intergroup/<slug>")
@login_required
def intergroup_library_detail(slug):
    """Slug-based detail URL for Intergroup libraries — the slug is
    derived live from ``Library.name`` so renaming a library
    automatically moves its canonical URL. Non-Intergroup libraries
    keep the id-based URL; only ``is_intergroup=True`` rows resolve
    here. Stale slugs after a rename 404 (no slug-history table for
    libraries today)."""
    from .colors import slugify
    target = (slug or "").lower()
    libs = Library.query.filter(Library.is_intergroup == True).all()  # noqa: E712
    lib = next((l for l in libs if slugify(l.name) == target), None)
    if lib is None:
        abort(404)
    return render_template("library_detail.html", library=lib)


@bp.route("/libraries/<slug>/edit", methods=["GET", "POST"])
@login_required
def library_edit(slug):
    lib = _resolve_library_by_slug(slug) or abort(404)
    deny = _require_can_edit_library(lib)
    if deny is not None:
        return deny
    # Library metadata changes (name, description, alert message,
    # Intergroup flag, category list) are gated to admins + Intergroup
    # Members. Editors retain their authority to
    # add / edit / delete files inside the library (via the per-row
    # gates) but can't rewrite the library's identity.
    if not current_user.can_manage_libraries():
        flash("Only admins and Intergroup Members can edit library settings", "danger")
        return redirect(_library_browse_url(lib))
    if request.method == "POST":
        # Renaming an Intergroup library is admin-only — non-admins
        # could otherwise rename the row to escape the gate it sits
        # behind. The is_intergroup flag itself is admin-only too.
        new_name = request.form["name"].strip()
        if (lib.is_intergroup
                and new_name != lib.name
                and not current_user.is_admin()):
            flash("Only admins can rename Intergroup libraries", "danger")
            return redirect(url_for("main.library_detail", slug=lib.public_slug))
        lib.name = new_name
        lib.description = request.form.get("description", "").strip()
        lib.alert_message = request.form.get("alert_message", "").strip() or None
        # Admin-only: respect the checkbox when the form rendered it
        # (signalled by ``is_intergroup_present``). The hidden marker
        # lets us distinguish "admin unchecked the box" from "non-admin
        # form didn't render the field at all".
        if current_user.is_admin() and request.form.get("is_intergroup_present") == "1":
            lib.is_intergroup = request.form.get("is_intergroup") == "1"
        # Whole-library public-visibility toggle for the /library page.
        # Same hidden-marker pattern as is_intergroup so unchecking the
        # box is distinguishable from the form not rendering it. Admin-
        # only — non-admins can't surface a library to the public.
        if current_user.is_admin() and request.form.get("public_visible_present") == "1":
            lib.public_visible = request.form.get("public_visible") == "1"
        # Categories management is admin-only on every library — the
        # form renders the editor for admins, the re-check here keeps
        # a tampered POST from sneaking categories onto a library if
        # the role check happens to be bypassable client-side.
        if (current_user.is_admin()
                and request.form.get("category_picker") == "1"):
            _apply_library_categories(lib, request.form)
            lib.categories_required = (
                request.form.get("categories_required") == "1")
        db.session.commit()
        from . import activity
        activity.log("library.update", entity_type="library", entity_id=lib.id,
                     summary=f"Updated library “{lib.name}”")
        flash("Library updated", "success")
        return redirect(url_for("main.library_detail", slug=lib.public_slug))
    return render_template("library_form.html", library=lib)


def _apply_library_categories(lib, form):
    """Replace ``lib``'s category list from index-aligned arrays in
    ``form``:

      ``category_id[]``   — existing row id, or empty for a new row
      ``category_name[]`` — display name; empty rows are dropped

    Order of submission becomes the new ``position``. Removed
    categories (existing ids absent from the submitted list) are
    deleted; the cascade unbinds their ``reading_categories`` rows so
    affected readings keep existing but lose that tag. Caller commits."""
    raw_ids = form.getlist("category_id")
    raw_names = form.getlist("category_name")
    existing = {c.id: c for c in lib.categories}
    submitted_ids = set()
    seen_names = set()
    for pos, (rid, raw_name) in enumerate(zip(raw_ids, raw_names)):
        name = (raw_name or "").strip()[:120]
        if not name:
            continue
        # De-duplicate within the submission itself; case-insensitive
        # compare so "General" and "general" don't both land.
        key = name.lower()
        if key in seen_names:
            continue
        seen_names.add(key)
        try:
            cat_id = int(rid) if rid else None
        except ValueError:
            cat_id = None
        cat = existing.get(cat_id) if cat_id is not None else None
        if cat is None:
            db.session.add(LibraryCategory(library_id=lib.id, name=name, position=pos))
        else:
            cat.name = name
            cat.position = pos
            submitted_ids.add(cat_id)
    for cat_id, cat in existing.items():
        if cat_id not in submitted_ids:
            db.session.delete(cat)


@bp.route("/libraries/<slug>/delete", methods=["POST"])
@admin_required
def library_delete(slug):
    lib = _resolve_library_by_slug(slug) or abort(404)
    from . import activity
    activity.log("library.delete", entity_type="library", entity_id=lib.id,
                 summary=f"Deleted library “{lib.name}”")
    db.session.delete(lib)
    db.session.commit()
    flash("Library deleted", "success")
    return redirect(url_for("main.libraries"))


def _resolve_reading_categories(library, form):
    """Read ``category_ids`` from the form and return the matching
    ``LibraryCategory`` rows scoped to ``library``. Silently drops any
    id that doesn't belong to this library so a tampered POST can't
    cross-link a reading to another library's tags."""
    raw_ids = form.getlist("category_ids", type=int)
    if not raw_ids:
        return []
    return LibraryCategory.query.filter(
        LibraryCategory.library_id == library.id,
        LibraryCategory.id.in_(raw_ids),
    ).all()


def _apply_reading_form(r, form, files):
    r.title = form["title"].strip()
    r.summary = (form.get("summary") or "").strip() or None
    mode = (form.get("content_mode") or "").strip()
    # Three-mode authoring: each mode owns exactly one content field.
    # Empty / legacy submissions (no `content_mode` flag) fall through
    # to the old permissive shape so older form posts still work.
    if mode == "paste":
        r.body = form.get("body", "").strip()
        r.url = None
    elif mode == "link":
        r.url = (form.get("url") or "").strip() or None
        r.body = ""
    elif mode == "upload":
        r.body = ""
        r.url = None
    else:
        r.body = form.get("body", "").strip()
        r.url = (form.get("url") or "").strip() or None
    # File / media-picker write-back. Only honoured for `upload` mode
    # AND legacy submissions (no mode). Switching to paste or link
    # explicitly clears any prior file at the bottom of the block.
    uploaded = files.get("file")
    media_id = (form.get("media_id") or "").strip()
    if mode in ("upload", ""):
        if uploaded and uploaded.filename:
            r.stored_filename, r.original_filename = _save_upload(uploaded)
        elif media_id:
            m = db.session.get(MediaItem, int(media_id)) if media_id.isdigit() else None
            if m:
                r.stored_filename, r.original_filename = m.stored_filename, m.original_filename
    if form.get("remove_file") == "1" and r.stored_filename:
        r.stored_filename = None
        r.original_filename = None
    # Switching to paste or link mode implicitly clears any existing
    # file so a single library item never carries two competing
    # content sources simultaneously.
    if mode in ("paste", "link") and r.stored_filename:
        r.stored_filename = None
        r.original_filename = None
    thumb = files.get("thumbnail")
    if thumb and thumb.filename:
        r.thumbnail_filename, _ = _save_upload(thumb)
    if form.get("remove_thumbnail") == "1" and r.thumbnail_filename:
        r.thumbnail_filename = None


@bp.route("/libraries/<slug>/readings/new", methods=["GET", "POST"])
@login_required
def reading_new(slug):
    lib = _resolve_library_by_slug(slug) or abort(404)
    deny = _require_can_edit_library(lib)
    if deny is not None:
        return deny
    if request.method == "POST":
        cats = _resolve_reading_categories(lib, request.form)
        picker_present = request.form.get("category_picker") == "1"
        # Intergroup libraries with the categories-required toggle on
        # must have at least one category per upload so the filter UI on
        # the detail page always has something to group on. When the
        # toggle is off, categories are still selectable but optional.
        if lib.is_intergroup and lib.categories_required and not cats:
            if not lib.categories:
                flash("Add at least one category to this Intergroup library before uploading.", "danger")
            else:
                flash("Pick at least one category for this upload.", "danger")
            return redirect(url_for("main.library_detail", slug=lib.public_slug))
        r = LibraryItem(library_id=lib.id, title=request.form["title"].strip(),
                    created_by=current_user.id)
        _apply_reading_form(r, request.form, request.files)
        if picker_present:
            r.categories = cats
        db.session.add(r)
        db.session.commit()
        from . import activity
        activity.log("reading.create", entity_type="reading", entity_id=r.id,
                     summary=f"Added reading “{r.title}” to library “{lib.name}”")
        flash("Item added to library", "success")
        return redirect(url_for("main.library_detail", slug=lib.public_slug))
    return render_template("reading_form.html", library=lib, reading=None)


def _derive_title_from_filename(filename):
    """Convert an uploaded filename into a readable default title.
    Mirrors the JS-side derivation in the import wizard so a row whose
    title input was left blank still ends up with the same value the
    user previewed."""
    import re
    name = os.path.splitext(os.path.basename(filename or ""))[0]
    name = re.sub(r"[_\-\.]+", " ", name)
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return "Untitled"
    return name.title()


@bp.route("/libraries/<slug>/readings/import", methods=["POST"])
@login_required
def library_import(slug):
    """Bulk-import endpoint backing the library-import wizard. Accepts
    a parallel ``files``/``titles`` pair plus an optional set of
    ``category_ids`` applied to every created item. Each file becomes
    its own ``LibraryItem``; dedup is handled by ``_save_upload`` so
    re-uploading an identical file simply reuses the existing
    ``MediaItem`` row. The category-required gate is re-checked here
    so a tampered POST can't bypass it."""
    lib = _resolve_library_by_slug(slug) or abort(404)
    deny = _require_can_edit_library(lib)
    if deny is not None:
        return deny
    files = request.files.getlist("files")
    titles = request.form.getlist("titles")
    pairs = []
    for i, f in enumerate(files):
        if not f or not f.filename:
            continue
        title = (titles[i] if i < len(titles) else "").strip()
        if not title:
            title = _derive_title_from_filename(f.filename)
        pairs.append((f, title))
    if not pairs:
        flash("Pick at least one file to import.", "danger")
        return redirect(url_for("main.library_detail", slug=lib.public_slug))
    cats = _resolve_reading_categories(lib, request.form)
    if lib.is_intergroup and lib.categories_required and not cats:
        if not lib.categories:
            flash("Add at least one category to this Intergroup library before importing.", "danger")
        else:
            flash("Pick at least one category for this import.", "danger")
        return redirect(url_for("main.library_detail", slug=lib.public_slug))
    created = 0
    for uploaded, title in pairs:
        stored, original = _save_upload(uploaded)
        r = LibraryItem(library_id=lib.id, title=title,
                        stored_filename=stored, original_filename=original,
                        created_by=current_user.id)
        if cats:
            r.categories = list(cats)
        db.session.add(r)
        created += 1
    db.session.commit()
    from . import activity
    activity.log("library.import", entity_type="library", entity_id=lib.id,
                 summary=f"Imported {created} file(s) into library “{lib.name}”")
    flash(f"Imported {created} file(s) into the library.", "success")
    return redirect(url_for("main.library_detail", slug=lib.public_slug))


@bp.route("/readings/<int:rid>")
@login_required
def reading_view(rid):
    r = db.session.get(LibraryItem, rid) or abort(404)
    if r.body:
        return render_template("reading_view.html", reading=r,
                               back_url=url_for("main.library_detail", slug=r.library.public_slug))
    if r.url:
        return redirect(r.url)
    if r.stored_filename:
        return redirect(url_for("main.reading_download", rid=rid))
    return render_template("reading_view.html", reading=r,
                           back_url=url_for("main.library_detail", slug=r.library.public_slug))


@bp.route("/readings/<int:rid>/download")
@login_required
def reading_download(rid):
    r = db.session.get(LibraryItem, rid) or abort(404)
    if not r.stored_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"],
                               r.stored_filename, as_attachment=False,
                               download_name=r.original_filename or r.stored_filename)


@bp.route("/readings/<int:rid>/content")
@login_required
def reading_content(rid):
    """Return the reading's body rendered to HTML (bleached)."""
    r = db.session.get(LibraryItem, rid) or abort(404)
    if not r.body:
        abort(404)
    from flask import render_template_string
    html = render_template_string(
        "{{ body|markdown }}", body=r.body
    )
    return jsonify(title=r.title, html=str(html))


@bp.route("/readings/<int:rid>/pdf")
@login_required
def reading_pdf(rid):
    """Generate a PDF from the reading's body on the fly."""
    r = db.session.get(LibraryItem, rid) or abort(404)
    if not r.body:
        abort(404)
    from weasyprint import HTML
    from flask import render_template_string
    from io import BytesIO
    from werkzeug.wsgi import wrap_file
    body_html = str(render_template_string("{{ body|markdown }}", body=r.body))
    page_html = _pdf_page_html(r.title, body_html)
    pdf_bytes = HTML(string=page_html).write_pdf()
    safe_title = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_"
                         for c in r.title).strip() or f"reading-{r.id}"
    resp = current_app.make_response(pdf_bytes)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = (
        f'attachment; filename="{safe_title}.pdf"')
    return resp


def _pdf_page_html(title, body_html):
    """Wrap rendered body HTML in a minimal letter-style PDF template."""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
@page {{ size: Letter; margin: 0.9in 0.9in; }}
body {{ font-family: Georgia, 'Times New Roman', serif; color: #111; line-height: 1.55; font-size: 11pt; }}
h1.pdf-title {{ font-size: 20pt; font-weight: 700; margin: 0 0 .6em; text-align: center; }}
h1 {{ font-size: 17pt; margin: 1.4em 0 .4em; }}
h2 {{ font-size: 14pt; margin: 1.2em 0 .35em; }}
h3 {{ font-size: 12pt; margin: 1em 0 .25em; }}
p {{ margin: 0 0 .6em; }}
ul, ol {{ margin: 0 0 .6em 1.2em; padding: 0; }}
li {{ margin: .1em 0; }}
blockquote {{ margin: .5em 1em; padding: .3em .9em; border-left: 3px solid #999; color: #444; font-style: italic; }}
code {{ font-family: Consolas, monospace; background: #f0f0f0; padding: 0 .25em; border-radius: 3px; font-size: .95em; }}
pre {{ background: #f6f6f6; padding: .6em .8em; border-radius: 4px; overflow-wrap: break-word; font-size: .95em; }}
a {{ color: #0b5cff; text-decoration: underline; }}
hr {{ border: 0; border-top: 1px solid #bbb; margin: 1em 0; }}
table {{ border-collapse: collapse; margin: .4em 0; }}
th, td {{ border: 1px solid #bbb; padding: .3em .6em; }}
</style></head>
<body>
<h1 class="pdf-title">{title}</h1>
{body_html}
</body></html>"""


@bp.route("/markdown-preview", methods=["POST"])
@login_required
def markdown_preview():
    """Render a markdown snippet to bleached HTML for the editor preview.
    `mode=block` opts into the no-`nl2br` filter so lists render under a
    bare paragraph (matches what `markdown_block` does on the public site).
    Default mode keeps the legacy `markdown` filter behaviour so the
    library reading editor renders identically to its persisted output."""
    if not current_user.can_use_editor_tools():
        return jsonify(error="forbidden"), 403
    from flask import render_template_string
    body = request.form.get("body")
    mode = (request.form.get("mode") or "").strip().lower()
    if body is None:
        payload = request.get_json(silent=True, force=False) or {}
        if isinstance(payload, dict):
            body = payload.get("body", "")
            mode = mode or (payload.get("mode") or "").strip().lower()
    body = body or ""
    filter_name = "markdown_block" if mode == "block" else "markdown"
    html = str(render_template_string("{{ body|" + filter_name + " }}", body=body))
    return jsonify(html=html)


@bp.route("/readings/<int:rid>/thumbnail")
@login_required
def reading_thumbnail(rid):
    r = db.session.get(LibraryItem, rid) or abort(404)
    if not r.thumbnail_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], r.thumbnail_filename)


@bp.route("/readings/<int:rid>/edit", methods=["GET", "POST"])
@login_required
def reading_edit(rid):
    r = db.session.get(LibraryItem, rid) or abort(404)
    deny = _require_can_edit_library(r.library)
    if deny is not None:
        return deny
    if not current_user.can_edit_library_item(r):
        # Editor-tier per-row gate: editors can only modify readings
        # they (or another editor-tier user) uploaded. Admin-uploaded
        # and legacy (creator-unknown) rows are protected.
        flash("You can only edit files uploaded by you or another editor-tier user.", "danger")
        return redirect(_library_browse_url(r.library))
    if request.method == "POST":
        cats = _resolve_reading_categories(r.library, request.form)
        # Forms that render the category picker emit a hidden
        # ``category_picker=1`` marker so we can tell "user submitted
        # zero selected" (an error on Intergroup libraries) apart from
        # "form didn't include the picker at all" (legacy / partial
        # save paths — leave existing categories alone).
        picker_present = request.form.get("category_picker") == "1"
        if (r.library.is_intergroup and r.library.categories_required
                and picker_present and not cats):
            flash("Pick at least one category for this upload.", "danger")
            return redirect(url_for("main.library_detail", slug=r.library.public_slug))
        _apply_reading_form(r, request.form, request.files)
        if picker_present:
            r.categories = cats
        db.session.commit()
        flash("Item updated", "success")
        return redirect(url_for("main.library_detail", slug=r.library.public_slug))
    return render_template("reading_form.html", library=r.library, reading=r)


def _library_browse_url(lib):
    """Canonical detail URL for a library — slug-based for Intergroup
    rows so the redirect lands at the human-readable URL, id-based for
    everything else. Used by routes that flash + redirect after a
    write operation."""
    if lib.is_intergroup:
        from .colors import slugify
        return url_for("main.intergroup_library_detail", slug=slugify(lib.name))
    return url_for("main.library_detail", slug=lib.public_slug)


@bp.route("/libraries/<slug>/readings/bulk-categories", methods=["POST"])
@login_required
def library_readings_bulk_categories(slug):
    """Apply a category change to a multi-select set of readings.

    Form fields:
      ``reading_ids``  — repeated; ids of selected readings
      ``category_ids`` — repeated; categories to add/remove/replace with
      ``action``       — ``add`` | ``remove`` | ``replace``

    Per-row authorization mirrors ``User.can_bulk_edit_categories``:
    rows the user couldn't delete are silently skipped, with a flash
    summary reporting both the applied + skipped counts so the user
    knows when their edit was scoped down. Categories from another
    library (a tampered POST) are silently dropped at the query layer
    via the ``library_id`` filter."""
    lib = _resolve_library_by_slug(slug) or abort(404)
    deny = _require_can_edit_library(lib)
    if deny is not None:
        return deny
    action = request.form.get("action") or "add"
    if action not in ("add", "remove", "replace"):
        action = "add"
    rids = set(request.form.getlist("reading_ids", type=int))
    cat_ids = set(request.form.getlist("category_ids", type=int))
    if not rids:
        flash("Pick at least one file to edit.", "danger")
        return redirect(_library_browse_url(lib))
    cats = []
    if cat_ids:
        cats = LibraryCategory.query.filter(
            LibraryCategory.library_id == lib.id,
            LibraryCategory.id.in_(cat_ids),
        ).all()
    # Block "Replace with empty" on libraries that require categories —
    # otherwise this single click would silently strip every selected
    # row of its tags, violating the upload-time invariant.
    if (action == "replace" and not cats and lib.categories_required
            and lib.is_intergroup):
        flash("This library requires at least one category — pick one before replacing.", "danger")
        return redirect(_library_browse_url(lib))
    readings = LibraryItem.query.filter(
        LibraryItem.library_id == lib.id,
        LibraryItem.id.in_(rids),
    ).all()
    applied = 0
    skipped = 0
    for r in readings:
        if not current_user.can_bulk_edit_categories(r):
            skipped += 1
            continue
        if action == "add":
            existing = {c.id for c in r.categories}
            for c in cats:
                if c.id not in existing:
                    r.categories.append(c)
        elif action == "remove":
            r.categories = [c for c in r.categories if c.id not in cat_ids]
        else:  # replace
            r.categories = list(cats)
        applied += 1
    db.session.commit()
    if applied:
        word = "file" if applied == 1 else "files"
        msg = f"Categories updated on {applied} {word}"
        if skipped:
            msg += f" ({skipped} skipped — not your uploads)"
        flash(msg, "success")
    elif skipped:
        flash(f"None of the {skipped} selected files are yours to edit.", "warning")
    else:
        flash("No matching files found.", "warning")
    return redirect(_library_browse_url(lib))


@bp.route("/libraries/<slug>/readings/bulk-delete", methods=["POST"])
@login_required
def library_readings_bulk_delete(slug):
    """Delete a multi-select set of readings. Per-row authorization
    mirrors ``User.can_delete_library_item`` (Editors can only delete rows
    whose creator was another Editor; admin / intergroup_member
    free-and-clear within a library they can edit; viewers can't
    delete at all). Stored files + thumbnails are cleaned up via
    ``_delete_upload`` before the DB row is removed. Skipped rows are
    silently filtered with a flash summary so the user sees when
    authorization scoped their action down."""
    lib = _resolve_library_by_slug(slug) or abort(404)
    deny = _require_can_edit_library(lib)
    if deny is not None:
        return deny
    rids = set(request.form.getlist("reading_ids", type=int))
    if not rids:
        flash("Pick at least one file to delete.", "danger")
        return redirect(_library_browse_url(lib))
    readings = LibraryItem.query.filter(
        LibraryItem.library_id == lib.id,
        LibraryItem.id.in_(rids),
    ).all()
    deleted = 0
    skipped = 0
    for r in readings:
        if not current_user.can_delete_library_item(r):
            skipped += 1
            continue
        if r.stored_filename:
            _delete_upload(r.stored_filename)
        if r.thumbnail_filename:
            _delete_upload(r.thumbnail_filename)
        db.session.delete(r)
        deleted += 1
    db.session.commit()
    if deleted:
        word = "file" if deleted == 1 else "files"
        msg = f"Deleted {deleted} {word}"
        if skipped:
            msg += f" ({skipped} skipped — not your uploads)"
        flash(msg, "success")
    elif skipped:
        flash(f"None of the {skipped} selected files are yours to delete.", "warning")
    else:
        flash("No matching files found.", "warning")
    return redirect(_library_browse_url(lib))


@bp.route("/libraries/<slug>/readings/reorder", methods=["POST"])
@login_required
def library_readings_reorder(slug):
    lib = _resolve_library_by_slug(slug) or abort(404)
    if not current_user.can_edit_library(lib):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    ids = data.get("order") or []
    if not isinstance(ids, list):
        return jsonify({"error": "invalid"}), 400
    readings = {r.id: r for r in lib.items.all()}
    for pos, rid in enumerate(ids):
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            continue
        r = readings.get(rid)
        if r is not None:
            r.position = pos
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/readings/<int:rid>/public-visible", methods=["POST"])
@login_required
def library_item_public_toggle(rid):
    """Per-item public-visibility toggle for the Literature Library page.

    JSON-in, JSON-out so the per-row toggle in library_detail.html can
    fire-and-forget on every change without a page reload. Authority
    follows the same gate as editing the parent library — anyone who
    can edit the library can flip individual items.

    The flag is only meaningful when ``Library.public_visible`` is
    True; the public /library route consults both. We don't
    short-circuit the save here even when the parent is private — that
    way an admin can pre-stage which items will surface before flipping
    the parent on.
    """
    r = db.session.get(LibraryItem, rid) or abort(404)
    if not current_user.can_edit_library(r.library):
        return jsonify(error="forbidden"), 403
    payload = request.get_json(silent=True) or {}
    visible = bool(payload.get("public_visible"))
    r.public_visible = visible
    db.session.commit()
    return jsonify(public_visible=r.public_visible)


@bp.route("/readings/<int:rid>/delete", methods=["POST"])
@login_required
def reading_delete(rid):
    r = db.session.get(LibraryItem, rid) or abort(404)
    if not current_user.can_delete_library_item(r):
        flash("You don't have permission to delete this file", "danger")
        return redirect(_safe_referrer()
                        or url_for("main.library_detail", slug=r.library.public_slug))
    parent_slug = r.library.public_slug
    title = r.title
    from . import trash, activity
    activity.log("reading.delete", entity_type="reading", entity_id=r.id,
                 summary=f"Deleted reading “{title}” (recoverable for {trash.RETENTION_DAYS} days)")
    trash.soft_delete_library_item(r, current_user.id)
    flash("Item moved to the Delete Log — restorable for 30 days.", "success")
    return redirect(url_for("main.library_detail", slug=parent_slug))


# --- helpers ---

BLOCKED_UPLOAD_EXTENSIONS = {
    # Executables / scripts that could be served back and run if the
    # upload dir ever leaks into an executable path.
    ".exe", ".msi", ".bat", ".cmd", ".com", ".scr",
    ".sh", ".bash", ".zsh", ".ps1",
    ".php", ".phtml", ".php3", ".php4", ".php5", ".phps",
    ".py", ".pyc", ".pyo", ".pl", ".cgi", ".rb",
    ".jsp", ".asp", ".aspx", ".ashx",
    ".jar", ".war",
    # HTML/XML can carry XSS if served inline; bleach output is only applied
    # at template time. Block raw HTML uploads to be safe.
    ".html", ".htm", ".xhtml", ".xml",
}
# SVG is allowed only for admins. It can contain inline <script> that
# executes when the file is opened directly, but admins already control
# site branding and can upload arbitrary content, so the risk is accepted
# in exchange for letting them upload vector logos.
ADMIN_ONLY_UPLOAD_EXTENSIONS = {".svg"}


def _save_upload(uploaded):
    """Save a Werkzeug FileStorage to uploads; also create/reuse a MediaItem. Returns (stored, original)."""
    original = secure_filename(uploaded.filename) or "upload"
    ext = os.path.splitext(original)[1].lower()
    if ext in BLOCKED_UPLOAD_EXTENSIONS:
        abort(400, description=f"File type '{ext}' is not allowed.")
    if ext in ADMIN_ONLY_UPLOAD_EXTENSIONS:
        if not getattr(current_user, "is_authenticated", False) or not current_user.is_admin():
            abort(400, description=f"File type '{ext}' is only allowed for admins.")
    data = uploaded.read()
    if ext == ".svg":
        # Strip <script>, on*= handlers, and javascript: hrefs BEFORE the
        # dimension normaliser touches the file. SVG uploads are
        # admin-only (see ADMIN_ONLY_UPLOAD_EXTENSIONS) but an admin
        # uploading a vector logo from a designer's hand-off shouldn't
        # be a vector for XSS against other admins / visitors who later
        # navigate to the file directly — browsers execute inline
        # <script> in standalone SVGs. Same _sanitize_svg() that the
        # Custom Icons upload path uses.
        data = _sanitize_svg(data)
        data = _normalize_svg_dimensions(data)
    h = hashlib.sha256(data).hexdigest()
    existing = MediaItem.query.filter_by(content_hash=h).first()
    if existing:
        return existing.stored_filename, existing.original_filename
    stored = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
    with open(path, "wb") as f:
        f.write(data)
    m = MediaItem(stored_filename=stored, original_filename=original,
                  content_hash=h, size_bytes=len(data),
                  mime_type=getattr(uploaded, "mimetype", None),
                  uploaded_by=getattr(current_user, "id", None))
    db.session.add(m)
    db.session.flush()
    return stored, original


def _media_json(m):
    return {"id": m.id, "stored_filename": m.stored_filename,
            "original_filename": m.original_filename,
            "size_bytes": m.size_bytes, "mime_type": m.mime_type,
            "type": _media_type(m.original_filename)}


def _apply_file_upload(obj, uploaded, media_id):
    """Set stored_filename/original_filename on a row from either an upload or a media id."""
    if uploaded and uploaded.filename:
        obj.stored_filename, obj.original_filename = _save_upload(uploaded)
        return
    mid = (media_id or "").strip()
    if mid.isdigit():
        m = db.session.get(MediaItem, int(mid))
        if m:
            obj.stored_filename, obj.original_filename = m.stored_filename, m.original_filename


def _media_type(name):
    if not name: return "file"
    ext = name.rsplit(".",1)[-1].lower() if "." in name else ""
    if ext == "pdf": return "pdf"
    if ext in ("doc","docx","rtf","odt","txt","md"): return "doc"
    if ext in ("xls","xlsx","csv","ods"): return "xls"
    if ext in ("ppt","pptx","odp"): return "ppt"
    if ext in ("jpg","jpeg","png","gif","webp","svg","bmp"): return "img"
    if ext in ("mp4","mov","avi","mkv","webm"): return "vid"
    if ext in ("mp3","wav","m4a","ogg","flac"): return "aud"
    return "file"


def _delete_upload(stored):
    if not stored:
        return
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _interface_stored_filenames():
    """Stored filenames currently used by site-wide interface assets
    (branding logo, frontend logo, Open Graph image). These are hidden
    from the File Browser so administrative uploads don't clutter the
    content library."""
    s = SiteSetting.query.first()
    if not s:
        return set()
    names = set()
    if s.footer_logo_filename:
        names.add(s.footer_logo_filename)
    if s.frontend_logo_filename:
        names.add(s.frontend_logo_filename)
    if s.og_image_filename:
        names.add(s.og_image_filename)
    if s.frontend_og_image_filename:
        names.add(s.frontend_og_image_filename)
    if s.frontend_favicon_filename:
        names.add(s.frontend_favicon_filename)
    if s.frontend_404_image_filename:
        names.add(s.frontend_404_image_filename)
    return names


_PUB_URL_RE = re.compile(r'/pub/([^\s"\'<>?#]+)')


def _extract_body_pub_originals(html):
    """Return the set of ``original_filename`` values referenced as
    ``/pub/<filename>`` inside an HTML body chunk. Empty / None HTML
    returns an empty set. The /pub Flask route resolves each token
    back to a ``MediaItem`` via ``original_filename`` — callers can
    look the row up and pull its ``stored_filename`` for cleanup."""
    if not html:
        return set()
    return set(_PUB_URL_RE.findall(html))


def _collect_body_inline_stored(html):
    """Resolve every ``/pub/<original_filename>`` inside a body HTML
    chunk to its current ``stored_filename`` via the MediaItem catalog.
    Returns a list (de-duplicated) of stored filenames that the inline
    images on this body reference — caller pipes each through
    ``_cleanup_retired_asset`` after the parent row is deleted so the
    reference-count scan inside the helper doesn't see the dying row."""
    originals = _extract_body_pub_originals(html)
    if not originals:
        return []
    rows = (MediaItem.query
            .filter(MediaItem.original_filename.in_(originals))
            .all())
    seen = set()
    out = []
    for m in rows:
        if m.stored_filename and m.stored_filename not in seen:
            seen.add(m.stored_filename)
            out.append(m.stored_filename)
    return out


def _cleanup_retired_asset(stored):
    """Delete a file from disk and its MediaItem row, but only if nothing
    else in the system still references it. References checked:

      - SiteSetting branding columns (logos, OG, favicon, 404)
      - MeetingFile.stored_filename
      - LibraryItem.stored_filename + thumbnail_filename
      - Meeting.logo_filename
      - Post / Story.featured_image_filename
      - INLINE references inside Post / Story / BlogPost / Page body
        HTML (``/pub/<original_filename>`` tokens). The body scan
        protects inline screenshots a WP import (or block editor)
        pasted into one post that another post still embeds.

    Safe to call with None or a filename that's already gone."""
    if not stored:
        return
    s = SiteSetting.query.first()
    if s and stored in (s.footer_logo_filename, s.frontend_logo_filename,
                        s.og_image_filename, s.frontend_og_image_filename,
                        s.frontend_favicon_filename,
                        s.frontend_404_image_filename):
        return  # still referenced by another interface asset
    refs = (MeetingFile.query.filter_by(stored_filename=stored).count()
            + LibraryItem.query.filter_by(stored_filename=stored).count()
            + LibraryItem.query.filter_by(thumbnail_filename=stored).count()
            + Meeting.query.filter_by(logo_filename=stored).count()
            + Post.query.filter_by(featured_image_filename=stored).count()
            + Story.query.filter_by(featured_image_filename=stored).count())
    if refs > 0:
        return
    # Inline body image survival — if any post / story / blog body
    # still embeds /pub/<original_filename> pointing at this stored
    # file, keep it alive. Resolve stored -> original through the
    # MediaItem catalog so the body LIKE-scan matches the URL shape
    # the public /pub route resolves on render.
    m_item = MediaItem.query.filter_by(stored_filename=stored).first()
    if m_item and m_item.original_filename:
        token = "/pub/" + m_item.original_filename
        body_refs = (Post.query.filter(Post.body.contains(token)).count()
                     + Story.query.filter(Story.body.contains(token)).count()
                     + BlogPost.query.filter(BlogPost.body.contains(token)).count())
        if body_refs > 0:
            return
    # Drop any cached thumbnails generated from this source so they
    # don't linger as orphans in the uploads dir.
    try:
        from . import thumbnails
        thumbnails.cleanup_for(stored)
    except Exception:  # noqa: BLE001 — cleanup is best-effort
        pass
    _delete_upload(stored)
    MediaItem.query.filter_by(stored_filename=stored).delete()
    db.session.flush()


# --- Media browser ---

MEDIA_PER_PAGE = 100


@bp.route("/files")
@login_required
def media_list():
    from sqlalchemy import case, func, or_
    q = (request.args.get("q") or "").strip().lower()
    picker = request.args.get("picker") == "1"
    view = request.args.get("view") or request.cookies.get("view-media") or "list"
    if view not in ("list", "grid"): view = "list"  # legacy "table" → "list"
    sort = request.args.get("sort") or request.cookies.get("view-media-sort") or "uploaded"
    direction = request.args.get("dir") or request.cookies.get("view-media-dir") or "desc"
    try:
        page = max(1, int(request.args.get("page") or 1))
    except (TypeError, ValueError):
        page = 1

    query = MediaItem.query

    # Site-interface uploads (branding logos, OG images, favicon, etc.)
    # are hidden from the File Browser so administrative uploads don't
    # clutter the content library.
    hidden = _interface_stored_filenames()
    if hidden:
        query = query.filter(MediaItem.stored_filename.notin_(hidden))

    # Public-submission uploads are hidden from non-admin users while
    # the parent post is still in the holding tank — admins see them
    # so they can review before approving, but editors / viewers
    # shouldn't have a curated review surface polluted with raw
    # visitor uploads. Once the admin approves the submission, the
    # parent post leaves pending state and the file appears normally.
    if not current_user.is_admin():
        pending_uploads = {p.featured_image_filename for p in
                           Post.query.filter(Post.is_pending_review.is_(True),
                                             Post.featured_image_filename.isnot(None)).all()
                           if p.featured_image_filename}
        if pending_uploads:
            query = query.filter(MediaItem.stored_filename.notin_(pending_uploads))

    if q:
        query = query.filter(func.lower(MediaItem.original_filename).contains(q))

    # Server-side sort + paginate so the route always returns at most
    # MEDIA_PER_PAGE rows, regardless of how many files exist. The
    # ``type`` sort buckets by extension via a CASE expression so the
    # ordering matches the in-Python ``_media_type`` helper.
    name_col = func.lower(MediaItem.original_filename)
    if sort == "name":
        order_cols = [name_col, MediaItem.id]
    elif sort == "size":
        order_cols = [MediaItem.size_bytes, MediaItem.id]
    elif sort == "type":
        type_case = case(
            (name_col.like("%.pdf"), "pdf"),
            (or_(name_col.like("%.doc"), name_col.like("%.docx"),
                 name_col.like("%.rtf"), name_col.like("%.odt"),
                 name_col.like("%.txt"), name_col.like("%.md")), "doc"),
            (or_(name_col.like("%.xls"), name_col.like("%.xlsx"),
                 name_col.like("%.csv"), name_col.like("%.ods")), "xls"),
            (or_(name_col.like("%.ppt"), name_col.like("%.pptx"),
                 name_col.like("%.odp")), "ppt"),
            (or_(name_col.like("%.jpg"), name_col.like("%.jpeg"),
                 name_col.like("%.png"), name_col.like("%.gif"),
                 name_col.like("%.webp"), name_col.like("%.svg"),
                 name_col.like("%.bmp"), name_col.like("%.avif")), "img"),
            (or_(name_col.like("%.mp4"), name_col.like("%.mov"),
                 name_col.like("%.avi"), name_col.like("%.mkv"),
                 name_col.like("%.webm")), "vid"),
            (or_(name_col.like("%.mp3"), name_col.like("%.wav"),
                 name_col.like("%.m4a"), name_col.like("%.ogg"),
                 name_col.like("%.flac")), "aud"),
            else_="zzz",
        )
        order_cols = [type_case, name_col, MediaItem.id]
    else:  # uploaded (created_at)
        order_cols = [MediaItem.created_at, MediaItem.id]

    if direction == "desc":
        order_cols = [c.desc() for c in order_cols]
    query = query.order_by(*order_cols)

    total = query.count()
    pages = max(1, (total + MEDIA_PER_PAGE - 1) // MEDIA_PER_PAGE)
    if page > pages:
        page = pages
    items = (query.offset((page - 1) * MEDIA_PER_PAGE)
                  .limit(MEDIA_PER_PAGE).all())
    pagination = {
        "page": page, "pages": pages, "per_page": MEDIA_PER_PAGE,
        "total": total,
        "start": 0 if total == 0 else (page - 1) * MEDIA_PER_PAGE + 1,
        "end": min(page * MEDIA_PER_PAGE, total),
        "has_prev": page > 1, "has_next": page < pages,
    }

    resp = current_app.make_response(
        render_template("media.html", items=items, q=q, picker=picker, view=view,
                        sort=sort, direction=direction, media_type=_media_type,
                        pagination=pagination))
    if not picker:
        resp.set_cookie("view-media", view, max_age=60*60*24*365, samesite="Lax")
        resp.set_cookie("view-media-sort", sort, max_age=60*60*24*365, samesite="Lax")
        resp.set_cookie("view-media-dir", direction, max_age=60*60*24*365, samesite="Lax")
    return resp


@bp.route("/files/upload", methods=["POST"])
@editor_required
def media_upload():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "no file"}), 400
    data = uploaded.read()
    original = secure_filename(uploaded.filename) or "upload"
    ext = os.path.splitext(original)[1]
    if ext.lower() == ".svg":
        data = _normalize_svg_dimensions(data)
    h = hashlib.sha256(data).hexdigest()
    existing = MediaItem.query.filter_by(content_hash=h).first()
    if existing:
        return jsonify({"item": _media_json(existing), "deduped": True})
    stored = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(current_app.config["UPLOAD_FOLDER"], stored), "wb") as f:
        f.write(data)
    m = MediaItem(stored_filename=stored, original_filename=original,
                  content_hash=h, size_bytes=len(data),
                  mime_type=uploaded.mimetype,
                  uploaded_by=current_user.id)
    db.session.add(m); db.session.commit()
    return jsonify({"item": _media_json(m), "deduped": False})


@bp.route("/files/<int:mid>/rename", methods=["POST"])
@editor_required
def media_rename(mid):
    m = db.session.get(MediaItem, mid) or abort(404)
    if not current_user.can_rename_media(m):
        # Editor-tier per-row gate: editors and frontend editors can
        # only rename files they (or another editor-tier user)
        # uploaded. Admin-uploaded and legacy (uploader-unknown) files
        # are protected.
        return jsonify({"ok": False,
                        "error": "You can only rename files uploaded by you or another editor-tier user."}), 403
    new_name = (request.form.get("name") or "").strip()
    if new_name:
        m.original_filename = new_name[:500]
        db.session.commit()
    return jsonify({"ok": True, "original_filename": m.original_filename})


@bp.route("/files/<int:mid>/delete", methods=["POST"])
@admin_required
def media_delete(mid):
    m = db.session.get(MediaItem, mid) or abort(404)
    refs = (MeetingFile.query.filter_by(stored_filename=m.stored_filename).count()
            + LibraryItem.query.filter_by(stored_filename=m.stored_filename).count()
            + LibraryItem.query.filter_by(thumbnail_filename=m.stored_filename).count())
    if refs > 0:
        flash(f"Cannot delete — file is used by {refs} item(s)", "warning")
    else:
        from . import trash, activity
        name = m.original_filename
        activity.log("file.delete", entity_type="media_item", entity_id=m.id,
                     summary=f"Deleted file “{name}” from File Browser (recoverable for {trash.RETENTION_DAYS} days)")
        trash.soft_delete_media(m, current_user.id)
        flash("File moved to the Delete Log — restorable for 30 days.", "success")
    return redirect(url_for("main.media_list"))


@bp.route("/files/<int:mid>/download")
@login_required
def media_download(mid):
    m = db.session.get(MediaItem, mid) or abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"],
                               m.stored_filename, as_attachment=True,
                               download_name=m.original_filename)


@bp.route("/files/<int:mid>.json")
@login_required
def media_info(mid):
    m = db.session.get(MediaItem, mid) or abort(404)
    return jsonify(_media_json(m))


@bp.route("/files/images.json")
@login_required
def media_images_json():
    """List image-typed MediaItems for the block-editor's image picker.
    Paged with `limit` (default 200) + optional `q` substring filter
    against original filename. Filters by extension since not every
    upload populates `mime_type` reliably."""
    from sqlalchemy import or_
    q = (request.args.get("q") or "").strip().lower()
    try:
        limit = max(1, min(int(request.args.get("limit") or 200), 500))
    except (TypeError, ValueError):
        limit = 200
    EXT_PATTERNS = ("%.png", "%.jpg", "%.jpeg", "%.webp",
                    "%.gif", "%.svg", "%.avif", "%.bmp")
    query = MediaItem.query.filter(
        or_(*[MediaItem.original_filename.ilike(p) for p in EXT_PATTERNS])
    )
    if q:
        query = query.filter(MediaItem.original_filename.ilike(f"%{q}%"))
    items = (query.order_by(MediaItem.created_at.desc())
                  .limit(limit).all())
    return jsonify({"items": [
        {**_media_json(m), "url": url_for("public.public_file",
                                          filename=m.original_filename)}
        for m in items
    ]})


# --- Login appearance ---

LOGIN_EFFECTS = ("off", "network", "stars", "fireflies", "bubbles", "snow", "waves", "orbits", "rain")


@bp.route("/settings/login-appearance-save", methods=["POST"])
@admin_required
def login_appearance_save():
    import re
    s = _get_site_setting()
    eff = (request.form.get("login_particle_effect") or "network").strip()
    s.login_particle_effect = eff if eff in LOGIN_EFFECTS else "network"
    import json as _json
    mode = (request.form.get("login_bg_mode") or "default").strip()
    hex_re = re.compile(r"#[0-9a-fA-F]{6}")
    if mode == "default":
        s.login_bg_color = None
        s.login_bg_colors = None
    elif mode == "solid":
        color = (request.form.get("login_bg_color") or "").strip()
        if hex_re.fullmatch(color):
            s.login_bg_color = color
            s.login_bg_colors = None
    elif mode.startswith("gradient"):
        try:
            n = int(mode.split("-", 1)[1])
        except (IndexError, ValueError):
            n = 2
        n = max(2, min(4, n))
        colors = []
        for i in range(1, n + 1):
            c = (request.form.get("login_bg_c" + str(i)) or "").strip()
            if hex_re.fullmatch(c):
                colors.append(c)
        if len(colors) >= 2:
            s.login_bg_colors = _json.dumps(colors)
            s.login_bg_color = None
    raw_speed = (request.form.get("login_particle_speed") or "").strip()
    try:
        sp = int(raw_speed) if raw_speed else 100
    except ValueError:
        sp = 100
    s.login_particle_speed = max(10, min(300, sp))
    raw_size = (request.form.get("login_particle_size") or "").strip()
    try:
        sz = int(raw_size) if raw_size else 100
    except ValueError:
        sz = 100
    s.login_particle_size = max(25, min(400, sz))
    s.login_transition_enabled = request.form.get("login_transition_enabled") == "1"
    db.session.commit()
    flash("Login appearance updated", "success")
    return redirect(_safe_referrer() or url_for("main.index"))


# --- Turnstile (login bot protection) ---

@bp.route("/settings/turnstile-save", methods=["POST"])
@admin_required
def turnstile_save():
    s = _get_site_setting()
    s.turnstile_site_key = (request.form.get("turnstile_site_key") or "").strip() or None
    new_secret = request.form.get("turnstile_secret_key") or ""
    if request.form.get("turnstile_secret_clear") == "1":
        s.turnstile_secret_key_enc = None
    elif new_secret.strip():
        s.turnstile_secret_key_enc = encrypt(new_secret.strip())
    wants_enabled = request.form.get("turnstile_enabled") == "1"
    if wants_enabled and (not s.turnstile_site_key or not s.turnstile_secret_key_enc):
        s.turnstile_enabled = False
        db.session.commit()
        flash("Turnstile not enabled: site key and secret key are both required", "danger")
        return redirect(_safe_referrer() or url_for("main.index"))
    s.turnstile_enabled = wants_enabled
    db.session.commit()
    flash("Login bot protection saved", "success")
    return redirect(_safe_referrer() or url_for("main.index"))


# --- Email / SMTP settings ---

@bp.route("/settings/email-save", methods=["POST"])
@admin_required
def email_save():
    s = _get_site_setting()
    s.smtp_host = (request.form.get("smtp_host") or "").strip() or None
    raw_port = (request.form.get("smtp_port") or "").strip()
    try:
        s.smtp_port = int(raw_port) if raw_port else None
    except ValueError:
        flash("SMTP port must be a number", "danger")
        return redirect(_safe_referrer() or url_for("main.index"))
    s.smtp_username = (request.form.get("smtp_username") or "").strip() or None
    new_pw = request.form.get("smtp_password") or ""
    if request.form.get("smtp_password_clear") == "1":
        s.smtp_password_enc = None
    elif new_pw:
        s.smtp_password_enc = encrypt(new_pw)
    s.smtp_from_email = (request.form.get("smtp_from_email") or "").strip() or None
    s.smtp_from_name = (request.form.get("smtp_from_name") or "").strip() or None
    sec = (request.form.get("smtp_security") or "starttls").strip()
    s.smtp_security = sec if sec in ("none", "starttls", "ssl") else "starttls"
    s.access_request_to = (request.form.get("access_request_to") or "").strip() or None
    db.session.commit()
    flash("Email settings saved", "success")
    return redirect(_safe_referrer() or url_for("main.index"))


@bp.route("/settings/timezone-save", methods=["POST"])
@admin_required
def timezone_save():
    try:
        from zoneinfo import available_timezones
    except ImportError:
        flash("Timezone support requires Python 3.9+", "danger")
        return redirect(_safe_referrer() or url_for("main.index"))
    raw = (request.form.get("timezone") or "").strip()
    if not raw or raw not in available_timezones():
        flash("Pick a valid timezone", "danger")
        return redirect(_safe_referrer() or url_for("main.index"))
    s = _get_site_setting()
    s.timezone = raw
    db.session.commit()
    flash("Timezone saved", "success")
    return redirect(_safe_referrer() or url_for("main.index"))


@bp.route("/settings/email-test", methods=["POST"])
@admin_required
def email_test():
    """Send a test email using the persisted SMTP settings. Returns
    JSON when called via XHR (X-Requested-With) so the settings modal
    can surface the actual SMTP outcome — success, recipient address,
    or the underlying SMTP error — instead of the modal's generic
    'Saved' toast that hides whether the message actually went out.

    Falls back to the legacy flash + redirect flow for non-XHR
    callers (e.g. a no-JS submit) so the page always communicates
    the outcome somehow."""
    from .mail import send_mail, _recipients
    s = _get_site_setting()
    wants_json = (request.headers.get("X-Requested-With", "").lower()
                  in ("fetch", "xmlhttprequest"))
    to_raw = (request.form.get("to") or "").strip() or s.access_request_to or s.smtp_from_email
    recipients = _recipients(to_raw)
    if not recipients:
        if wants_json:
            return jsonify(ok=False, message="Provide a test recipient"), 200
        flash("Provide a test recipient", "danger")
        return redirect(_safe_referrer() or url_for("main.index"))
    if not (s.smtp_host and s.smtp_from_email):
        msg = ("SMTP isn't configured yet. Enter SMTP host, port, security, "
               "and From-email above, click Save, then run the test.")
        if wants_json:
            return jsonify(ok=False, message=msg), 200
        flash(msg, "danger")
        return redirect(_safe_referrer() or url_for("main.index"))
    ok, err = send_mail(s, recipients,
                        "Trusted Servants Pro test email",
                        "This is a test message from Trusted Servants Pro. SMTP is configured correctly.")
    if ok:
        msg = f"Test email sent to {', '.join(recipients)}"
        if wants_json:
            return jsonify(ok=True, message=msg), 200
        flash(msg, "success")
    else:
        msg = f"SMTP send failed: {err}"
        if wants_json:
            return jsonify(ok=False, message=msg), 200
        flash(msg, "danger")
    return redirect(_safe_referrer() or url_for("main.index"))


# --- Access requests ---

ACCESS_ROLE_OPTIONS = [
    "Intergroup Member", "Zoom Tech", "Meeting GSR",
    "Meeting Secretary", "Meeting Chair", "Other",
]


@public_bp.route("/request-access", methods=["POST"])
def request_access_submit():
    import json
    from flask import jsonify as _jsonify
    from .mail import send_mail

    name = (request.form.get("name") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip()
    roles = [r for r in request.form.getlist("roles") if r in ACCESS_ROLE_OPTIONS]
    meeting_name = (request.form.get("meeting_name") or "").strip() or None

    wants_json = request.headers.get("X-Requested-With") == "fetch" \
                 or request.accept_mimetypes.best == "application/json"

    if not name or not phone or not email or not roles:
        msg = "Name, phone, email, and at least one role are required."
        if wants_json:
            return _jsonify(ok=False, error=msg), 400
        flash(msg, "danger")
        return redirect(url_for("auth.login"))

    req = AccessRequest(name=name, phone=phone, email=email,
                        roles_json=json.dumps(roles), meeting_name=meeting_name)
    db.session.add(req)
    db.session.commit()

    s = _get_site_setting()
    mail_error = None
    if s.smtp_host and s.access_request_to:
        lines = [
            "A new access request has been submitted to Trusted Servants Pro.",
            "",
            f"Name:    {name}",
            f"Phone:   {phone}",
            f"Email:   {email}",
            f"Roles:   {', '.join(roles)}",
        ]
        if meeting_name:
            lines.append(f"Meeting: {meeting_name}")
        lines += ["", "Review pending requests in the portal under Access Requests."]
        ok, err = send_mail(s, s.access_request_to,
                            f"Access request: {name}",
                            "\n".join(lines))
        if not ok:
            mail_error = err

    if wants_json:
        return _jsonify(ok=True, emailed=mail_error is None, error=mail_error)
    flash("Thanks — your request has been submitted. An administrator will follow up by email.", "success")
    return redirect(url_for("auth.login"))


USER_LOG_PAGE_SIZE = 100


def _user_log_event_dict(ev, label_for):
    label, icon_name = label_for(ev.action)
    return {
        "id": ev.id,
        "action": ev.action,
        "label": label,
        "icon": icon_name,
        "summary": ev.summary or "",
        "ip": ev.ip or "",
        "entity_type": ev.entity_type or "",
        "entity_id": ev.entity_id,
        "created_at": ev.created_at,
        "user_id": ev.user_id,
        "username": (ev.user.username if ev.user else None),
    }


# ---- Watchtower: unified admin security + observability console ----------
#
# Five-tab dashboard that consolidates User Log, Delete Log, Access
# Requests, and Visitor Metrics into one admin-only surface and layers
# new security tools (anomaly detection, IP blocklist, failed-login
# leaderboard) on top. The legacy routes below still resolve so old
# bookmarks and inbound links don't 404; the sidebar surfaces only
# Watchtower.

@bp.route("/watchtower")
@admin_required
def watchtower():
    """Overview tab — KPI tiles, system metrics, anomaly callouts, the
    last 30 days of visitor traffic, the last 24 hours of failed-login
    attempts, top suspicious IPs, and recent admin activity. Polls
    nothing — every panel renders from a fresh DB read so a refresh
    always shows current state."""
    from . import watchtower as wt
    return render_template(
        "watchtower/overview.html",
        active_tab="overview",
        kpis=wt.overview_kpis(),
        daily=wt.daily_visits(days=30),
        hourly_fail=wt.hourly_failed_logins(hours=24),
        anomalies=wt.anomaly_signals(),
        top_ips=wt.top_failed_login_ips(days=7, limit=10),
        recent=wt.recent_admin_activity(limit=12),
        active_sess=wt.active_sessions(minutes=60),
        system=wt.system_snapshot(),
        blocked=wt.blocked_ips(active_only=True),
    )


@bp.route("/watchtower/visitors")
@admin_required
def watchtower_visitors():
    """Frontend visitor analytics tab. Same data as the standalone
    /visitor-metrics page but rendered inside the Watchtower shell."""
    from . import visitor_metrics as vm
    try:
        window = max(7, min(365, int(request.args.get("window", 30))))
    except (TypeError, ValueError):
        window = 30
    return render_template(
        "watchtower/visitors.html",
        active_tab="visitors",
        window=window,
        windows=(7, 14, 30, 60, 90, 180, 365),
        summary=vm.summary(days=window),
        daily=vm.daily_series(days=window),
        hourly=vm.hourly_distribution(days=min(14, window)),
        top_paths=vm.top_paths(days=window, limit=10),
        top_referrers=vm.top_referrers(days=window, limit=10),
        devices=vm.device_breakdown(days=window),
    )


@bp.route("/watchtower/access")
@admin_required
def watchtower_access():
    """Admin activity log + login sessions + IP blocklist + suspicious
    IPs. The activity feed reuses the same per-user filter the legacy
    /user-log page supports (``?user_id=<id>|all``) so deep links from
    the old surface keep working."""
    from . import activity, watchtower as wt
    users = User.query.order_by(User.username).all()
    raw_uid = request.args.get("user_id")
    show_all = raw_uid is None or (raw_uid or "").lower() == "all"
    selected = None
    if not show_all and raw_uid:
        try:
            selected = db.session.get(User, int(raw_uid))
        except (TypeError, ValueError):
            selected = None
    if not show_all and selected is None:
        show_all = True
    scope_uid = None if show_all else selected.id
    try:
        days = max(1, min(365, int(request.args.get("days", 30))))
    except (TypeError, ValueError):
        days = 30
    try:
        sdays = max(1, min(365, int(request.args.get("sdays", 7))))
    except (TypeError, ValueError):
        sdays = 7
    sessions = activity.recent_sessions(scope_uid, since_days=sdays)
    raw_events = activity.recent_activity(scope_uid, since_days=days,
                                          limit=USER_LOG_PAGE_SIZE, offset=0)
    total_events = activity.recent_activity_count(scope_uid, since_days=days)
    events = [_user_log_event_dict(ev, activity.label_for) for ev in raw_events]
    return render_template(
        "watchtower/access.html",
        active_tab="access",
        users=users, selected=selected, show_all=show_all,
        sessions=sessions, events=events,
        days=days, sdays=sdays,
        total_events=total_events,
        page_size=USER_LOG_PAGE_SIZE,
        top_ips=wt.top_failed_login_ips(days=7, limit=20),
        blocked=wt.blocked_ips(active_only=True),
    )


@bp.route("/watchtower/deletes")
@admin_required
def watchtower_deletes():
    """Recycle bin tab — same data and same restore/purge action URLs
    as the legacy /delete-log page so nothing in the form actions has
    to move."""
    from . import trash
    from .models import DeletedFile
    try:
        trash.expire_old()
    except Exception:
        db.session.rollback()
    rows = (DeletedFile.query
            .order_by(DeletedFile.deleted_at.desc())
            .limit(500).all())
    items = []
    now = datetime.utcnow()
    for row in rows:
        seconds_left = max(0, (row.expires_at - now).total_seconds())
        days_left = int((seconds_left + 86399) // 86400) if seconds_left > 0 else 0
        parent_link = None
        if row.parent_type == "library" and row.parent_id:
            lib = db.session.get(Library, row.parent_id)
            if lib:
                parent_link = url_for("main.library_detail", slug=lib.public_slug)
        elif row.parent_type == "meeting" and row.parent_id:
            mt = db.session.get(Meeting, row.parent_id)
            if mt:
                parent_link = url_for("main.meeting_detail", slug=mt.public_slug)
        crumbs = []
        if row.source_type == "reading":
            crumbs.append(("Library", row.parent_label or "(deleted library)", parent_link))
            crumbs.append(("Item", row.title or "(untitled)", None))
        elif row.source_type == "meeting_file":
            import json as _json
            try:
                snap = _json.loads(row.snapshot_json or "{}")
            except (ValueError, TypeError):
                snap = {}
            crumbs.append(("Meeting", row.parent_label or "(deleted meeting)", parent_link))
            cat = snap.get("category") or "documents"
            crumbs.append(("Category", cat.replace("_", " ").title(), None))
            crumbs.append(("File", row.title or "(untitled)", None))
        else:
            crumbs.append(("File browser", row.original_filename or "(unknown file)", None))
        deleter = db.session.get(User, row.deleted_by) if row.deleted_by else None
        items.append({
            "id": row.id,
            "source_type": row.source_type,
            "stored_filename": row.stored_filename,
            "original_filename": row.original_filename,
            "title": row.title,
            "deleted_at": row.deleted_at,
            "deleter": deleter.username if deleter else "(unknown)",
            "expires_at": row.expires_at,
            "days_left": days_left,
            "crumbs": crumbs,
        })
    return render_template("watchtower/deletes.html",
                           active_tab="deletes",
                           items=items, retention_days=trash.RETENTION_DAYS)


@bp.route("/watchtower/requests")
@admin_required
def watchtower_requests():
    """Access-request inbox + active password resets. Action URLs
    (mark handled, archive, delete) still post to the legacy
    /access-requests/<id>/* endpoints so back-compat is automatic."""
    view = (request.args.get("view") or "active").strip().lower()
    if view not in ("active", "archived"):
        view = "active"
    q = AccessRequest.query
    if view == "archived":
        q = q.filter(AccessRequest.is_archived.is_(True))
        items = q.order_by(AccessRequest.archived_at.desc().nullslast(),
                           AccessRequest.created_at.desc()).all()
    else:
        q = q.filter(AccessRequest.is_archived.is_(False))
        items = q.order_by(AccessRequest.status.asc(),
                           AccessRequest.created_at.desc()).all()
    archived_count = AccessRequest.query.filter_by(is_archived=True).count()
    active_count = AccessRequest.query.filter_by(is_archived=False).count()
    pending_resets = []
    recent_resets = []
    if view == "active":
        now = datetime.utcnow()
        live_tokens = (PasswordResetToken.query
                       .filter(PasswordResetToken.used_at.is_(None),
                               PasswordResetToken.expires_at > now)
                       .order_by(PasswordResetToken.created_at.desc()).all())
        seen = {}
        for tok in live_tokens:
            if tok.user_id not in seen:
                seen[tok.user_id] = tok
        for tok in seen.values():
            u = db.session.get(User, tok.user_id)
            if u:
                mins = max(0, int((tok.expires_at - now).total_seconds() // 60))
                pending_resets.append((u, tok, mins))
        cutoff = now - timedelta(days=30)
        all_tokens = (PasswordResetToken.query
                      .filter(PasswordResetToken.created_at >= cutoff)
                      .order_by(PasswordResetToken.created_at.desc()).all())
        for tok in all_tokens:
            u = db.session.get(User, tok.user_id)
            if not u:
                continue
            if tok.used_at is not None:
                status = "used"; effective_at = tok.used_at
            elif tok.expires_at <= now:
                status = "expired"; effective_at = tok.expires_at
            else:
                status = "pending"; effective_at = tok.created_at
            recent_resets.append({
                "kind": "self_service", "username": u.username,
                "email": u.email or "", "status": status,
                "requested_at": tok.created_at,
                "effective_at": effective_at, "actor": u.username,
            })
        from .models import ActivityLog
        admin_resets = (ActivityLog.query
                        .filter(ActivityLog.action == "password.reset.admin",
                                ActivityLog.created_at >= cutoff)
                        .order_by(ActivityLog.created_at.desc())
                        .limit(200).all())
        for ev in admin_resets:
            target = db.session.get(User, ev.entity_id) if ev.entity_id else None
            actor = db.session.get(User, ev.user_id) if ev.user_id else None
            recent_resets.append({
                "kind": "admin",
                "username": target.username if target else f"user #{ev.entity_id}",
                "email": (target.email if target else "") or "",
                "status": "admin_reset",
                "requested_at": ev.created_at,
                "effective_at": ev.created_at,
                "actor": actor.username if actor else "(deleted user)",
                "summary": ev.summary or "",
            })
        recent_resets.sort(key=lambda r: r["requested_at"], reverse=True)
        recent_resets = recent_resets[:100]
    return render_template("watchtower/requests.html",
                           active_tab="requests",
                           items=items, view=view,
                           archived_count=archived_count,
                           active_count=active_count,
                           pending_resets=pending_resets,
                           recent_resets=recent_resets)


@bp.route("/watchtower/ban-ip", methods=["POST"])
@admin_required
def watchtower_ban_ip():
    """Add (or refresh) an IP block. ``ttl_hours=0`` is permanent."""
    from . import watchtower as wt, activity
    ip = (request.form.get("ip") or "").strip()
    reason = request.form.get("reason") or ""
    try:
        ttl_hours = int(request.form.get("ttl_hours") or 0)
    except (TypeError, ValueError):
        ttl_hours = 0
    if not ip:
        flash("Provide an IP to block.", "danger")
        return redirect(url_for("main.watchtower_access"))
    row = wt.ban_ip(ip, reason, current_user.id,
                    ttl_hours=ttl_hours if ttl_hours > 0 else None)
    if row:
        activity.log("watchtower.ban_ip", entity_type="ip_block",
                     entity_id=row.id,
                     summary=f"Banned {ip}" + (f" ({reason})" if reason else ""))
        flash(f"Blocked {ip}.", "success")
    else:
        flash("Couldn't block — invalid input.", "danger")
    return redirect(request.form.get("return_url") or url_for("main.watchtower_access"))


@bp.route("/watchtower/unban-ip/<int:bid>", methods=["POST"])
@admin_required
def watchtower_unban_ip(bid):
    from . import watchtower as wt, activity
    from .models import IPBlock
    row = db.session.get(IPBlock, bid)
    ip = row.ip if row else f"#{bid}"
    ok = wt.unban_ip(bid)
    if ok:
        activity.log("watchtower.unban_ip", entity_type="ip_block",
                     entity_id=bid, summary=f"Unblocked {ip}")
        flash(f"Unblocked {ip}.", "success")
    else:
        flash("Block not found.", "danger")
    return redirect(request.form.get("return_url") or url_for("main.watchtower_access"))


@bp.route("/watchtower/end-session/<int:sid>", methods=["POST"])
@admin_required
def watchtower_end_session(sid):
    from . import watchtower as wt, activity
    from .models import LoginSession
    s = db.session.get(LoginSession, sid)
    label = (s.user.username if s and s.user else f"session #{sid}")
    ok = wt.end_session(sid, reason="forced")
    if ok:
        activity.log("watchtower.end_session", entity_type="login_session",
                     entity_id=sid,
                     summary=f"Force-ended session for {label}")
        flash(f"Ended session for {label}.", "success")
    else:
        flash("Session not open or not found.", "danger")
    return redirect(request.form.get("return_url") or url_for("main.watchtower_access"))


@bp.route("/watchtower/clear-failures", methods=["POST"])
@admin_required
def watchtower_clear_failures():
    from . import watchtower as wt, activity
    ip = (request.form.get("ip") or "").strip()
    n = wt.clear_login_failures(ip)
    if n > 0:
        activity.log("watchtower.clear_failures", entity_type="ip",
                     summary=f"Cleared {n} failed-login records for {ip}")
        flash(f"Cleared {n} failed-login record(s) for {ip}.", "success")
    else:
        flash("No matching records.", "info")
    return redirect(request.form.get("return_url") or url_for("main.watchtower_access"))


@bp.route("/api/user-log-events")
@admin_required
def api_user_log_events():
    """Paginated activity-feed slice for the User Log's infinite
    scroll. Returns rendered HTML <li> rows so the markup matches the
    initial server render exactly (shared partial: _ulog_event.html).
    Accepts the same scope params as the page: ``user_id`` (int or
    ``all``), ``days`` (1–365), and ``offset`` (number of rows
    already on screen)."""
    from . import activity
    raw_uid = request.args.get("user_id")
    show_all = raw_uid is None or (raw_uid or "").lower() == "all"
    scope_uid = None
    if not show_all:
        try:
            scope_uid = int(raw_uid)
        except (TypeError, ValueError):
            show_all = True
            scope_uid = None
    try:
        days = max(1, min(365, int(request.args.get("days", 30))))
    except (TypeError, ValueError):
        days = 30
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    raw_events = activity.recent_activity(scope_uid, since_days=days,
                                          limit=USER_LOG_PAGE_SIZE, offset=offset)
    events = [_user_log_event_dict(ev, activity.label_for) for ev in raw_events]
    html_chunks = [render_template("_ulog_event.html", ev=ev, show_all=show_all)
                   for ev in events]
    return jsonify(
        html="".join(html_chunks),
        count=len(events),
        next_offset=offset + len(events),
        has_more=len(events) == USER_LOG_PAGE_SIZE,
    )


# ---- Watchtower Deletes tab actions (restore / purge) -----------------------

@bp.route("/watchtower/deletes/<int:rid>/restore", methods=["POST"])
@admin_required
def watchtower_delete_restore(rid):
    from . import trash, activity
    from .models import DeletedFile
    row = db.session.get(DeletedFile, rid) or abort(404)
    label = row.original_filename or row.title or f"#{row.id}"
    ok, msg = trash.restore(rid)
    if ok:
        activity.log("file.restore", entity_type="deleted_file", entity_id=rid,
                     summary=f"Restored “{label}” — {msg}")
        flash(f"Restored “{label}”. {msg}.", "success")
    else:
        flash(f"Couldn't restore “{label}”: {msg}", "danger")
    return redirect(url_for("main.watchtower_deletes"))


@bp.route("/watchtower/deletes/<int:rid>/purge", methods=["POST"])
@admin_required
def watchtower_delete_purge(rid):
    from . import trash, activity
    from .models import DeletedFile
    row = db.session.get(DeletedFile, rid) or abort(404)
    label = row.original_filename or row.title or f"#{row.id}"
    activity.log("file.purge", entity_type="deleted_file", entity_id=rid,
                 summary=f"Permanently purged “{label}”")
    trash.purge(rid)
    flash(f"Permanently deleted “{label}”.", "success")
    return redirect(url_for("main.watchtower_deletes"))


@bp.route("/watchtower/requests/<int:rid>/handled", methods=["POST"])
@admin_required
def watchtower_request_handled(rid):
    from datetime import datetime
    r = db.session.get(AccessRequest, rid) or abort(404)
    r.status = "handled" if r.status == "pending" else "pending"
    r.handled_at = datetime.utcnow() if r.status == "handled" else None
    db.session.commit()
    from . import activity
    activity.log("access_request.handle", entity_type="access_request", entity_id=r.id,
                 summary=f"Marked request from {r.name} <{r.email}> as {r.status}")
    return redirect(url_for("main.watchtower_requests",
                            view=request.form.get("view") or "active"))


@bp.route("/watchtower/requests/<int:rid>/archive", methods=["POST"])
@admin_required
def watchtower_request_archive(rid):
    """Move a handled request into the archive view. Pending requests
    are auto-flipped to handled at the same time so the archived row
    has a coherent status. Reversible via ``watchtower_request_unarchive``.
    """
    from datetime import datetime
    r = db.session.get(AccessRequest, rid) or abort(404)
    if r.status == "pending":
        r.status = "handled"
        r.handled_at = datetime.utcnow()
    r.is_archived = True
    r.archived_at = datetime.utcnow()
    db.session.commit()
    from . import activity
    activity.log("access_request.archive", entity_type="access_request", entity_id=r.id,
                 summary=f"Archived request from {r.name} <{r.email}>")
    flash("Request archived", "success")
    return redirect(url_for("main.watchtower_requests",
                            view=request.form.get("view") or "active"))


@bp.route("/watchtower/requests/<int:rid>/unarchive", methods=["POST"])
@admin_required
def watchtower_request_unarchive(rid):
    r = db.session.get(AccessRequest, rid) or abort(404)
    r.is_archived = False
    r.archived_at = None
    db.session.commit()
    flash("Request restored from archive", "success")
    return redirect(url_for("main.watchtower_requests",
                            view=request.form.get("view") or "archived"))


@bp.route("/watchtower/requests/<int:rid>/delete", methods=["POST"])
@admin_required
def watchtower_request_delete(rid):
    r = db.session.get(AccessRequest, rid) or abort(404)
    from . import activity
    activity.log("access_request.delete", entity_type="access_request", entity_id=r.id,
                 summary=f"Deleted request from {r.name} <{r.email}>")
    db.session.delete(r)
    db.session.commit()
    flash("Request deleted", "success")
    return redirect(url_for("main.watchtower_requests",
                            view=request.form.get("view") or "active"))


# --- Contact form ---
#
# Admin surface for the public /contact page. Lists submissions with
# read / archive / delete actions, exposes an inline settings card for
# the page configuration (enable, recipient, copy, turnstile is shared
# with login). Mirrors the access_requests UX so the two admin
# sections feel like siblings.


@bp.route("/contact-form")
@admin_required
def contact_form():
    s = _get_site_setting()
    view = (request.args.get("view") or "active").strip().lower()
    if view not in ("active", "archived"):
        view = "active"
    q = ContactSubmission.query
    if view == "archived":
        q = q.filter(ContactSubmission.is_archived.is_(True))
        items = q.order_by(ContactSubmission.archived_at.desc().nullslast(),
                           ContactSubmission.created_at.desc()).all()
    else:
        q = q.filter(ContactSubmission.is_archived.is_(False))
        # Active list: unread first so new messages catch the eye, then
        # most-recent-first within each group.
        items = q.order_by(ContactSubmission.is_read.asc(),
                           ContactSubmission.created_at.desc()).all()
    archived_count = ContactSubmission.query.filter_by(is_archived=True).count()
    active_count = ContactSubmission.query.filter_by(is_archived=False).count()
    unread_count = ContactSubmission.query.filter_by(is_archived=False, is_read=False).count()
    return render_template("contact_form.html", site=s, items=items, view=view,
                           archived_count=archived_count, active_count=active_count,
                           unread_count=unread_count)


@bp.route("/contact-form/<int:cid>/read", methods=["POST"])
@admin_required
def contact_submission_toggle_read(cid):
    sub = db.session.get(ContactSubmission, cid) or abort(404)
    sub.is_read = not sub.is_read
    db.session.commit()
    return redirect(url_for("main.contact_form",
                            view=request.form.get("view") or "active"))


@bp.route("/contact-form/<int:cid>/archive", methods=["POST"])
@admin_required
def contact_submission_archive(cid):
    sub = db.session.get(ContactSubmission, cid) or abort(404)
    sub.is_archived = True
    sub.archived_at = datetime.utcnow()
    if not sub.is_read:
        sub.is_read = True
    db.session.commit()
    flash("Message archived", "success")
    return redirect(url_for("main.contact_form",
                            view=request.form.get("view") or "active"))


@bp.route("/contact-form/<int:cid>/unarchive", methods=["POST"])
@admin_required
def contact_submission_unarchive(cid):
    sub = db.session.get(ContactSubmission, cid) or abort(404)
    sub.is_archived = False
    sub.archived_at = None
    db.session.commit()
    flash("Message restored", "success")
    return redirect(url_for("main.contact_form",
                            view=request.form.get("view") or "archived"))


@bp.route("/contact-form/<int:cid>/delete", methods=["POST"])
@admin_required
def contact_submission_delete(cid):
    sub = db.session.get(ContactSubmission, cid) or abort(404)
    from . import activity
    activity.log("contact_submission.delete",
                 entity_type="contact_submission", entity_id=sub.id,
                 summary=f"Deleted contact message from {sub.name} <{sub.email}>")
    db.session.delete(sub)
    db.session.commit()
    flash("Message deleted", "success")
    return redirect(url_for("main.contact_form",
                            view=request.form.get("view") or "active"))


# --- First-run setup wizard ---

WIZARD_STEPS = [
    {"n": 1, "key": "password", "title": "Set a strong admin password",
     "desc": "Before anything else, replace the seeded admin password. This is the only required step."},
    {"n": 2, "key": "pic", "title": "Public Information Chair",
     "desc": "Shown to members in the Need Help popup. Leave blank if your group doesn't have one yet."},
    {"n": 3, "key": "smtp", "title": "Email (SMTP)",
     "desc": "Used for sending access-request notifications and test emails."},
    {"n": 4, "key": "theme", "title": "Pick a theme",
     "desc": "Choose the look you want. Themes are saved per-user in your browser."},
    {"n": 5, "key": "branding", "title": "Branding",
     "desc": "Optional sidebar footer logo shown throughout the portal."},
    {"n": 6, "key": "turnstile", "title": "Login bot protection",
     "desc": "Optional Cloudflare Turnstile challenge on the login screen."},
]
WIZARD_TOTAL = len(WIZARD_STEPS)


def _validate_password_strength(pw, user):
    from werkzeug.security import check_password_hash
    if len(pw) < 12:
        return "Password must be at least 12 characters long."
    categories = sum([
        any(c.islower() for c in pw),
        any(c.isupper() for c in pw),
        any(c.isdigit() for c in pw),
        any((not c.isalnum()) and (not c.isspace()) for c in pw),
    ])
    if categories < 3:
        return "Include at least 3 of: lowercase letters, uppercase letters, numbers, symbols."
    if pw.lower() in {"admin", "password", "administrator", "changeme", "welcome", "trustedservants"}:
        return "That password is too common — please choose something harder to guess."
    if user and user.password_hash and check_password_hash(user.password_hash, pw):
        return "Please choose a password different from your current one."
    return None


def _wizard_guard():
    """Return a redirect response if the caller cannot enter the wizard, else None."""
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    if not current_user.is_admin():
        return redirect(url_for("main.index"))
    return None


def _wizard_advance(step):
    if step >= WIZARD_TOTAL:
        site = _get_site_setting()
        site.setup_complete = True
        db.session.commit()
        flash("Setup complete — welcome to Trusted Servants Pro!", "success")
        return redirect(url_for("main.index"))
    return redirect(url_for("main.setup_step", step=step + 1))


@bp.route("/setup")
@login_required
def setup():
    guard = _wizard_guard()
    if guard:
        return guard
    site = _get_site_setting()
    if site.setup_complete:
        return redirect(url_for("main.index"))
    return redirect(url_for("main.setup_step", step=1))


@bp.route("/setup/<int:step>", methods=["GET", "POST"])
@login_required
def setup_step(step):
    guard = _wizard_guard()
    if guard:
        return guard
    site = _get_site_setting()
    if site.setup_complete:
        return redirect(url_for("main.index"))
    if step < 1 or step > WIZARD_TOTAL:
        return redirect(url_for("main.setup_step", step=1))

    error = None
    if request.method == "POST":
        skipped = request.form.get("skip") == "1"
        if step == 1:
            # Password is required; skip is not allowed.
            pw = request.form.get("password", "")
            confirm = request.form.get("password_confirm", "")
            err = _validate_password_strength(pw, current_user)
            if not err and pw != confirm:
                err = "Passwords do not match."
            if err:
                error = err
            else:
                from werkzeug.security import generate_password_hash
                current_user.password_hash = generate_password_hash(pw)
                db.session.commit()
                return _wizard_advance(step)
        elif skipped:
            return _wizard_advance(step)
        elif step == 2:
            site.pic_name = (request.form.get("pic_name") or "").strip() or None
            site.pic_email = (request.form.get("pic_email") or "").strip() or None
            site.pic_phone = (request.form.get("pic_phone") or "").strip() or None
            db.session.commit()
            return _wizard_advance(step)
        elif step == 3:
            site.smtp_host = (request.form.get("smtp_host") or "").strip() or None
            raw_port = (request.form.get("smtp_port") or "").strip()
            try:
                site.smtp_port = int(raw_port) if raw_port else None
            except ValueError:
                error = "SMTP port must be a number."
            if not error:
                site.smtp_username = (request.form.get("smtp_username") or "").strip() or None
                new_pw = (request.form.get("smtp_password") or "").strip()
                if new_pw:
                    site.smtp_password_enc = encrypt(new_pw)
                site.smtp_from_email = (request.form.get("smtp_from_email") or "").strip() or None
                site.smtp_from_name = (request.form.get("smtp_from_name") or "").strip() or None
                sec = (request.form.get("smtp_security") or "starttls").strip()
                site.smtp_security = sec if sec in ("none", "starttls", "ssl") else "starttls"
                db.session.commit()
                return _wizard_advance(step)
        elif step == 4:
            # Theme lives in per-user localStorage; the step 4 client-side JS
            # has already written it. Nothing to persist server-side.
            return _wizard_advance(step)
        elif step == 5:
            uploaded = request.files.get("footer_logo")
            if uploaded and uploaded.filename:
                old = site.footer_logo_filename
                stored, _ = _save_upload(uploaded)
                site.footer_logo_filename = stored
                if old and old != stored:
                    _delete_upload(old)
            w = (request.form.get("footer_logo_width") or "").strip()
            if w.isdigit() and 16 <= int(w) <= 150:
                site.footer_logo_width = int(w)
            link = (request.form.get("footer_logo_url") or "").strip()
            site.footer_logo_url = link or None
            db.session.commit()
            return _wizard_advance(step)
        elif step == 6:
            site.turnstile_site_key = (request.form.get("turnstile_site_key") or "").strip() or None
            new_secret = (request.form.get("turnstile_secret_key") or "").strip()
            if new_secret:
                site.turnstile_secret_key_enc = encrypt(new_secret)
            wants_enabled = request.form.get("turnstile_enabled") == "1"
            site.turnstile_enabled = bool(
                wants_enabled and site.turnstile_site_key and site.turnstile_secret_key_enc
            )
            db.session.commit()
            return _wizard_advance(step)

    meta = WIZARD_STEPS[step - 1]
    return render_template(
        "setup.html",
        step=step, total=WIZARD_TOTAL, steps=WIZARD_STEPS,
        step_title=meta["title"], step_desc=meta["desc"], step_key=meta["key"],
        error=error,
    )


# ============================================================================
# Posts (announcements + events)
# ============================================================================

def _parse_post_dt(value):
    """Parse the HTML5 ``datetime-local`` format the form submits.
    Returns None on empty / invalid input."""
    if not value:
        return None
    s = (value or "").strip()
    if not s:
        return None
    # datetime-local omits seconds: 2026-04-25T18:30
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _fmt_post_dt(dt):
    """Format a stored DateTime back into the value attribute the
    HTML5 ``datetime-local`` input expects."""
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M")


def _auto_archive_events():
    """Archive any active event whose end (or start, if no end) is
    before today. Drafts are skipped — admins can sit on a draft
    indefinitely without it disappearing into the archive. Idempotent
    — safe to call on every list view."""
    today = datetime.utcnow().date()
    cutoff = datetime.combine(today, datetime.min.time())  # midnight today
    q = Post.query.filter(
        Post.is_archived.is_(False), Post.is_draft.is_(False),
        Post.is_event.is_(True),
    )
    changed = False
    for p in q.all():
        # Cutoff = the start of today; an event whose end was BEFORE
        # midnight today (i.e. the event ended yesterday or earlier)
        # auto-archives. An event with no end falls back to start.
        ref = p.event_ends_at or p.event_starts_at
        if ref and ref < cutoff:
            p.is_archived = True
            changed = True
    if changed:
        db.session.commit()


@bp.route("/announcementsevents")
@login_required
def posts():
    _require_posts_enabled()
    _auto_archive_events()
    show = (request.args.get("show") or "active").strip()
    kind = (request.args.get("kind") or "all").strip()
    sort = (request.args.get("sort") or "").strip()
    try:
        page = max(1, int(request.args.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    per_page = 100
    q = Post.query
    if show == "archived":
        q = q.filter(Post.is_archived.is_(True),
                     Post.is_pending_review.is_(False))
    elif show == "drafts":
        q = q.filter(Post.is_draft.is_(True),
                     Post.is_archived.is_(False),
                     Post.is_pending_review.is_(False))
    elif show == "pending":
        # Holding tank for visitor submissions awaiting admin review.
        q = q.filter(Post.is_pending_review.is_(True),
                     Post.is_archived.is_(False))
    else:  # active
        show = "active"
        q = q.filter(Post.is_archived.is_(False),
                     Post.is_draft.is_(False),
                     Post.is_pending_review.is_(False))
    if kind == "events":
        q = q.filter(Post.is_event.is_(True))
    elif kind == "announcements":
        q = q.filter(Post.is_announcement.is_(True))
    # Sort modes. Default flips by tab — pending shows freshest
    # submissions on top, every other tab shows by event-start so
    # upcoming events read first. Admin can override via the column-
    # header click which sets ?sort=… directly.
    default_sort = "submitted_desc" if show == "pending" else "event_desc"
    if sort not in ("event_asc", "event_desc",
                    "title_asc", "title_desc",
                    "updated_asc", "updated_desc",
                    "submitted_asc", "submitted_desc",
                    "posted_asc", "posted_desc",
                    "type_asc", "type_desc"):
        sort = default_sort
    if sort == "event_asc":
        q = q.order_by(Post.event_starts_at.asc().nulls_last(),
                       Post.updated_at.desc())
    elif sort == "event_desc":
        q = q.order_by(Post.event_starts_at.desc().nulls_last(),
                       Post.updated_at.desc())
    elif sort == "title_asc":
        q = q.order_by(Post.title.asc())
    elif sort == "title_desc":
        q = q.order_by(Post.title.desc())
    elif sort == "updated_asc":
        q = q.order_by(Post.updated_at.asc())
    elif sort == "updated_desc":
        q = q.order_by(Post.updated_at.desc())
    elif sort == "submitted_asc":
        q = q.order_by(Post.submitted_at.asc().nulls_last(),
                       Post.updated_at.asc())
    elif sort == "submitted_desc":
        q = q.order_by(Post.submitted_at.desc().nulls_last(),
                       Post.updated_at.desc())
    elif sort == "posted_asc":
        # `published_at` falls back to `created_at` for legacy rows
        # via COALESCE so the order is sensible when most rows have
        # NULL in the new column.
        q = q.order_by(db.func.coalesce(Post.published_at, Post.created_at).asc())
    elif sort == "posted_desc":
        q = q.order_by(db.func.coalesce(Post.published_at, Post.created_at).desc())
    elif sort == "type_asc":
        q = q.order_by(Post.is_event.asc(), Post.is_announcement.asc(),
                       Post.event_starts_at.desc().nulls_last())
    elif sort == "type_desc":
        q = q.order_by(Post.is_event.desc(), Post.is_announcement.desc(),
                       Post.event_starts_at.desc().nulls_last())
    total = q.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    pending_count = (Post.query.filter(Post.is_pending_review.is_(True),
                                        Post.is_archived.is_(False)).count())
    return render_template("posts.html", posts=items, show=show, kind=kind,
                           sort=sort, page=page, per_page=per_page,
                           total=total, total_pages=total_pages,
                           pending_count=pending_count)


@bp.route("/announcementsevents/new")
@login_required
def post_new():
    _require_posts_enabled()
    return render_template("post_edit.html", post=None)


@bp.route("/announcementsevents/<int:pid>")
@login_required
def post_edit(pid):
    _require_posts_enabled()
    post = db.session.get(Post, pid) or abort(404)
    return render_template("post_edit.html", post=post)


@bp.route("/announcementsevents/save", methods=["POST"])
@login_required
def post_save():
    _require_posts_enabled()
    """Create or update a post. The ``post_id`` hidden field decides
    which path: empty/absent → create, set → update. The same form
    template renders both paths."""
    pid_raw = (request.form.get("post_id") or "").strip()
    if pid_raw:
        post = db.session.get(Post, int(pid_raw)) or abort(404)
        creating = False
    else:
        post = Post(created_by=getattr(current_user, "id", None))
        creating = True

    # Capture the previous public slug + title + public-status before
    # mutating any of them. The previous slug is needed to log a
    # redirect when it changes; the previous title gates whether we
    # re-derive the slug from scratch on this save (see comment
    # below); the previous public status gates whether we log a
    # redirect at all — drafts and pending submissions never had a
    # publicly-known URL, so renaming their slug shouldn't pollute the
    # `EntitySlugHistory` table.
    _prev_public_slug = post.public_slug if not creating else None
    _prev_title = post.title if not creating else None
    _was_public = (not creating) and (not post.is_draft) and (not post.is_pending_review)

    title = (request.form.get("title") or "").strip()[:255]
    if not title:
        flash("Title is required", "danger")
        return redirect(_safe_referrer() or url_for("main.post_new"))
    post.title = title

    # Slug edits are gated to admins + frontend editors; all other users'
    # slug field is silently ignored.
    explicit_slug = None
    if current_user.is_authenticated and current_user.can_edit_frontend():
        explicit_slug = _normalize_slug(request.form.get("slug"))

    # Slug resolution. Two modes:
    #   1. Title CHANGED on this save (or creating a new post) — re-
    #      derive the slug from the new title and ignore whatever the
    #      slug input carried (the input is pre-populated from the
    #      database, so without this branch the stale slug would win
    #      and the public URL would never track the new title). The
    #      uniqueness sweep appends -2/-3/… on collision.
    #   2. Title UNCHANGED — respect the editor's explicit slug input
    #      so they can rename the URL without touching the title. When
    #      the input is blank, fall back to the title-derived slug.
    title_slug = _normalize_slug(post.title)
    title_changed = creating or (_prev_title != title)
    if title_changed:
        unique = _unique_post_slug(title_slug,
                                   exclude_id=post.id if not creating else None)
        post.slug = None if unique == title_slug else unique
        # Surface the suffix when the auto-derive had to disambiguate
        # so the editor isn't surprised the public URL gained a `-2`.
        if unique and unique != title_slug:
            flash(f"URL auto-derived to “{unique}” to avoid collision with another post.", "info")
    else:
        base = explicit_slug or title_slug
        unique = _unique_post_slug(base,
                                   exclude_id=post.id if not creating else None)
        if explicit_slug:
            post.slug = unique
            if explicit_slug != unique:
                flash(f"URL already taken — saved as “{unique}”.", "info")
        else:
            post.slug = None if unique == title_slug else unique
    post.summary = (request.form.get("summary") or "").strip() or None
    post.body = (request.form.get("body") or "").strip() or None

    post.is_announcement = request.form.get("is_announcement") == "1"
    post.is_event = request.form.get("is_event") == "1"

    post.event_starts_at = _parse_post_dt(request.form.get("event_starts_at"))
    post.event_ends_at = _parse_post_dt(request.form.get("event_ends_at"))
    # Posted-on timestamp — admin-controllable so a post can be back-
    # or forward-dated. Only overwrite when the form submitted a value;
    # blank input keeps whatever's already on the row (or NULL on a
    # fresh post, which the post-create branch defaults to "now").
    if "published_at" in request.form:
        parsed_pub = _parse_post_dt(request.form.get("published_at"))
        post.published_at = parsed_pub

    post.is_online = request.form.get("is_online") == "1"
    post.location_name = (request.form.get("location_name") or "").strip()[:255] or None
    post.location_address = (request.form.get("location_address") or "").strip() or None
    post.google_maps_url = (request.form.get("google_maps_url") or "").strip()[:500] or None

    post.website_url = (request.form.get("website_url") or "").strip()[:500] or None
    post.website_label = (request.form.get("website_label") or "").strip()[:120] or None

    post.zoom_meeting_id = (request.form.get("zoom_meeting_id") or "").strip()[:64] or None
    post.zoom_passcode = (request.form.get("zoom_passcode") or "").strip()[:128] or None
    post.zoom_url = (request.form.get("zoom_url") or "").strip()[:500] or None

    post.contact_name = (request.form.get("contact_name") or "").strip()[:120] or None
    post.contact_phone = (request.form.get("contact_phone") or "").strip()[:64] or None
    post.contact_email = (request.form.get("contact_email") or "").strip()[:255] or None

    # Featured image — same upload/clear semantics as the OG image.
    if request.form.get("clear_featured_image") == "1":
        old = post.featured_image_filename
        post.featured_image_filename = None
        _cleanup_retired_asset(old)
    uploaded = request.files.get("featured_image")
    if uploaded and uploaded.filename:
        old = post.featured_image_filename
        stored, _original = _save_upload(uploaded)
        post.featured_image_filename = stored
        if old and old != stored:
            _cleanup_retired_asset(old)

    # Draft/publish state — submit-button name="action" carries the
    # admin's intent. Values: "draft" (force is_draft=True), "publish"
    # (force is_draft=False), or absent (preserve current state for
    # edits; default to active for new posts).
    _was_draft = (not creating) and post.is_draft
    action = (request.form.get("action") or "").strip()
    if action == "draft":
        post.is_draft = True
    elif action == "publish":
        post.is_draft = False
    elif creating:
        post.is_draft = False  # default: new posts are active

    # Draft → publish transition stamps `published_at` with the current
    # site-local datetime (naive — matches how form-entered values are
    # parsed by `_parse_post_dt` and how the display layer reads the
    # column), overriding whatever the admin had keyed into the form.
    # Matches the dedicated `post_publish` route's behaviour so the
    # "Published on …" line resets to "now" whether the admin clicked
    # the inline Publish button or the form's Publish submit. Stays
    # no-op when the post was already published or when the admin
    # saved without flipping draft status.
    from .timezone import now_local_naive as _now_local
    _site = _get_site_setting()
    if _was_draft and action == "publish":
        post.published_at = _now_local(_site)

    # Default published_at on first save when the admin didn't set
    # one — keeps every row sortable by posted date without forcing
    # the form to require it. Uses the same site-local-naive
    # convention so the auto-stamped value displays at the right
    # wall-clock time without a tz conversion at the display layer.
    if creating and post.published_at is None:
        post.published_at = _now_local(_site)

    if creating:
        db.session.add(post)
    else:
        # Log a redirect row whenever the public slug changed AND the
        # post was already publicly addressable on the way in. Drafts
        # and pending-review submissions have no public URL, so slug
        # edits inside those states don't need a redirect entry — the
        # admin can rename freely without polluting EntitySlugHistory.
        if (_was_public
                and _prev_public_slug
                and _prev_public_slug != post.public_slug):
            _record_slug_change("post", post.id, _prev_public_slug, post.public_slug)
    db.session.commit()
    from . import activity
    activity.log("post.create" if creating else "post.update",
                 entity_type="post", entity_id=post.id,
                 summary=(f"Created post “{post.title}”" if creating
                          else f"Updated post “{post.title}”"))
    if creating:
        flash(("Draft saved: " + post.title) if post.is_draft else ("Published: " + post.title), "success")
        return redirect(url_for("main.posts", show=("drafts" if post.is_draft else "active")))
    flash("Post saved", "success")
    return redirect(url_for("main.post_edit", pid=post.id))


@bp.route("/announcementsevents/<int:pid>/approve-pending", methods=["POST"])
@login_required
def post_approve_pending(pid):
    """Move a visitor-submitted post out of the holding tank. ``target``
    determines the destination: ``draft`` parks it for further editing
    before publishing; ``publish`` makes it live immediately. Either
    way, the pending-review flag clears."""
    _require_posts_enabled()
    post = db.session.get(Post, pid) or abort(404)
    post.is_pending_review = False
    target = (request.form.get("target") or "draft").strip().lower()
    if target == "publish":
        post.is_draft = False
        flash("Submission approved and published", "success")
    else:
        post.is_draft = True
        flash("Submission moved to drafts for further editing", "success")
    db.session.commit()
    return redirect(_safe_referrer() or url_for("main.post_edit", pid=post.id))


@bp.route("/announcementsevents/<int:pid>/publish", methods=["POST"])
@login_required
def post_publish(pid):
    """Transition a draft to active. Stamps `published_at` with the
    current UTC datetime whenever the post was actually a draft on the
    way in — that's when "Published on …" should reset to "now",
    regardless of whatever date the admin had keyed into the form for
    back-dating. No-op (no timestamp bump) if the post was already
    published."""
    _require_posts_enabled()
    post = db.session.get(Post, pid) or abort(404)
    if post.is_draft:
        from .timezone import now_local_naive as _now_local
        post.published_at = _now_local(_get_site_setting())
    post.is_draft = False
    db.session.commit()
    flash("Published", "success")
    return redirect(_safe_referrer() or url_for("main.posts"))


@bp.route("/announcementsevents/<int:pid>/unpublish", methods=["POST"])
@login_required
def post_unpublish(pid):
    """Move a published post back to drafts. No-op if already a draft."""
    _require_posts_enabled()
    post = db.session.get(Post, pid) or abort(404)
    post.is_draft = True
    db.session.commit()
    flash("Moved to drafts", "success")
    return redirect(_safe_referrer() or url_for("main.posts", show="drafts"))


@bp.route("/announcementsevents/<int:pid>/archive", methods=["POST"])
@login_required
def post_archive(pid):
    _require_posts_enabled()
    post = db.session.get(Post, pid) or abort(404)
    post.is_archived = True
    db.session.commit()
    flash("Archived", "success")
    return redirect(_safe_referrer() or url_for("main.posts"))


@bp.route("/announcementsevents/<int:pid>/unarchive", methods=["POST"])
@login_required
def post_unarchive(pid):
    _require_posts_enabled()
    post = db.session.get(Post, pid) or abort(404)
    post.is_archived = False
    db.session.commit()
    flash("Restored", "success")
    return redirect(_safe_referrer() or url_for("main.posts"))


@bp.route("/announcementsevents/<int:pid>/delete", methods=["POST"])
@login_required
def post_delete(pid):
    _require_posts_enabled()
    post = db.session.get(Post, pid) or abort(404)
    from . import activity
    activity.log("post.delete", entity_type="post", entity_id=post.id,
                 summary=f"Deleted post “{post.title}”")
    # Clear the featured-image reference BEFORE the cleanup check so the
    # post being deleted doesn't count itself as a referrer. If another
    # post (e.g. one created by Duplicate) still points at the same
    # stored filename, the helper sees it and keeps the file.
    old_image = post.featured_image_filename
    # Snapshot inline /pub/ image stored filenames BEFORE the delete so
    # we still have the body text to scan. The cleanup helper runs
    # AFTER commit so its reference-count scan doesn't still see this
    # row's body holding the same /pub/<filename>.
    body_inline_stored = _collect_body_inline_stored(post.body)
    post.featured_image_filename = None
    if old_image:
        _cleanup_retired_asset(old_image)
    db.session.delete(post)
    db.session.commit()
    for s in body_inline_stored:
        _cleanup_retired_asset(s)
    flash("Post deleted", "success")
    return redirect(url_for("main.posts"))


@bp.route("/announcementsevents/bulk", methods=["POST"])
@login_required
def post_bulk():
    """Apply a single state change to many posts at once. Form fields:

      action  — one of archive | unarchive | draft | publish | delete
      ids     — repeated ``ids`` field, one per checked row

    Posts whose ids don't resolve are silently skipped so a stale form
    (e.g. someone deleted a post in another tab) doesn't error out the
    whole batch. Image cleanup runs once for delete actions, after the
    rows are removed, so a duplicate sharing the same stored file
    keeps the asset alive."""
    _require_posts_enabled()
    action = (request.form.get("action") or "").strip().lower()
    if action not in ("archive", "unarchive", "draft", "publish", "delete"):
        flash("Unknown bulk action", "danger")
        return redirect(_safe_referrer() or url_for("main.posts"))

    raw_ids = request.form.getlist("ids")
    pids = []
    for v in raw_ids:
        try:
            pids.append(int(v))
        except (TypeError, ValueError):
            continue
    if not pids:
        flash("No posts selected", "warning")
        return redirect(_safe_referrer() or url_for("main.posts"))

    rows = Post.query.filter(Post.id.in_(pids)).all()
    if not rows:
        flash("No posts matched the selection", "warning")
        return redirect(_safe_referrer() or url_for("main.posts"))

    from . import activity
    n = len(rows)
    label = {"archive": "archived", "unarchive": "restored",
             "draft": "moved to drafts", "publish": "published",
             "delete": "deleted"}[action]

    if action == "delete":
        # Delete: clear image refs first so the cleanup helper sees the
        # post is no longer pointing at the stored file before it
        # checks for residual referrers. Cleanup runs after commit so
        # one delete doesn't strand the asset on the filesystem when a
        # sibling row in the same batch shares the file.
        retired_assets = []
        retired_inline = []
        for p in rows:
            if p.featured_image_filename:
                retired_assets.append(p.featured_image_filename)
                p.featured_image_filename = None
            # Inline /pub/ images in the post body. Snapshot before
            # delete so the post-commit cleanup pass sees the same
            # files; per-batch dedupe happens inside the helper via
            # the body LIKE-scan on sibling rows still in flight.
            retired_inline.extend(_collect_body_inline_stored(p.body))
        for p in rows:
            db.session.delete(p)
        db.session.commit()
        for asset in retired_assets:
            _cleanup_retired_asset(asset)
        for asset in retired_inline:
            _cleanup_retired_asset(asset)
    else:
        for p in rows:
            if action == "archive":
                p.is_archived = True
            elif action == "unarchive":
                p.is_archived = False
            elif action == "draft":
                p.is_draft = True
            elif action == "publish":
                p.is_draft = False
                p.is_archived = False
                p.is_pending_review = False
        db.session.commit()

    activity.log(f"post.bulk_{action}", entity_type="post",
                 summary=f"Bulk {label} {n} post{'s' if n != 1 else ''}")
    flash(f"{n} post{'s' if n != 1 else ''} {label}", "success")
    return redirect(_safe_referrer() or url_for("main.posts"))


@bp.route("/announcementsevents/<int:pid>/duplicate", methods=["POST"])
@login_required
def post_duplicate(pid):
    """Clone a post into a Draft. Title gets a "(copy)" suffix; the
    duplicate is always un-archived AND a draft so the admin can re-
    tune dates and click Publish when ready, without the copy showing
    up on the public site or in the active list. The featured-image
    filename is shared (uploads are content-addressed, so two rows
    pointing at the same stored file is fine and the cleanup helper
    sees the reference)."""
    _require_posts_enabled()
    src = db.session.get(Post, pid) or abort(404)
    copy = Post(
        title=(src.title or "Untitled")[:240] + " (copy)",
        summary=src.summary,
        body=src.body,
        featured_image_filename=src.featured_image_filename,
        is_announcement=src.is_announcement,
        is_event=src.is_event,
        event_starts_at=src.event_starts_at,
        event_ends_at=src.event_ends_at,
        is_online=src.is_online,
        location_name=src.location_name,
        location_address=src.location_address,
        google_maps_url=src.google_maps_url,
        website_url=src.website_url,
        website_label=src.website_label,
        zoom_meeting_id=src.zoom_meeting_id,
        zoom_passcode=src.zoom_passcode,
        zoom_url=src.zoom_url,
        contact_name=src.contact_name,
        contact_phone=src.contact_phone,
        contact_email=src.contact_email,
        is_draft=True,
        is_archived=False,
        created_by=getattr(current_user, "id", None),
    )
    db.session.add(copy)
    db.session.commit()
    flash(f"Draft created: {copy.title}", "success")
    return redirect(url_for("main.posts", show="drafts"))


# Back-compat redirects: existing bookmarks / external links to
# /tspro/posts and /tspro/posts/<rest> 301 to the new
# /tspro/announcementsevents location. Query string is preserved.
@bp.route("/posts", defaults={"rest": ""})
@bp.route("/posts/<path:rest>")
def posts_legacy_redirect(rest):
    qs = ("?" + request.query_string.decode("utf-8")) if request.query_string else ""
    target = url_for("main.posts") + (("/" + rest) if rest else "") + qs
    return redirect(target, code=301)


@public_bp.route("/post-image/<int:pid>")
def post_featured_image(pid):
    """Serve a post's featured image. Public so the public web frontend
    can render link previews even before a visitor signs in."""
    p = db.session.get(Post, pid)
    if not p or not p.featured_image_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], p.featured_image_filename)


# ---------------------------------------------------------------------------
# Stories — recovery story long-form posts.
# ---------------------------------------------------------------------------
@bp.route("/stories")
@login_required
def stories():
    _require_stories_enabled()
    show = (request.args.get("show") or "active").strip()
    sort = (request.args.get("sort") or "posted_desc").strip()
    q = Story.query
    if show == "archived":
        q = q.filter(Story.is_archived.is_(True))
    elif show == "drafts":
        q = q.filter(Story.is_draft.is_(True), Story.is_archived.is_(False))
    else:
        show = "active"
        q = q.filter(Story.is_archived.is_(False), Story.is_draft.is_(False))
    if sort == "posted_asc":
        q = q.order_by(db.func.coalesce(Story.published_at, Story.created_at).asc())
    elif sort == "title_asc":
        q = q.order_by(Story.title.asc())
    elif sort == "title_desc":
        q = q.order_by(Story.title.desc())
    elif sort == "author_asc":
        q = q.order_by(Story.author_name.asc().nulls_last(), Story.title.asc())
    elif sort == "story_date_asc":
        q = q.order_by(Story.story_date.asc().nulls_last(), Story.updated_at.desc())
    elif sort == "story_date_desc":
        q = q.order_by(Story.story_date.desc().nulls_last(), Story.updated_at.desc())
    elif sort == "updated_desc":
        q = q.order_by(Story.updated_at.desc())
    else:
        sort = "posted_desc"
        q = q.order_by(db.func.coalesce(Story.published_at, Story.created_at).desc())
    items = q.all()
    return render_template("stories.html", stories=items, show=show, sort=sort)


def _story_embed():
    """True when the current request is rendering / submitting from
    inside the new-story modal iframe. Carried via ``?embed=1`` on the
    URL or ``embed=1`` in the form body."""
    return (request.args.get("embed") == "1"
            or request.form.get("embed") == "1")


def _story_embed_kwargs():
    """Spread into ``url_for(...)`` so post-save redirects keep the
    iframe in chromeless mode."""
    return {"embed": 1} if _story_embed() else {}


@bp.route("/stories/new")
@login_required
def story_new():
    _require_stories_enabled()
    return render_template("story_edit.html", story=None, embed=_story_embed())


@bp.route("/stories/<int:sid>")
@login_required
def story_edit(sid):
    _require_stories_enabled()
    story = db.session.get(Story, sid) or abort(404)
    return render_template("story_edit.html", story=story, embed=_story_embed())


@bp.route("/stories/save", methods=["POST"])
@login_required
def story_save():
    """Create or update a story. Mirrors ``post_save`` shape — empty
    ``story_id`` → create, set → update."""
    _require_stories_enabled()
    sid_raw = (request.form.get("story_id") or "").strip()
    if sid_raw:
        story = db.session.get(Story, int(sid_raw)) or abort(404)
        creating = False
    else:
        story = Story(created_by=getattr(current_user, "id", None))
        creating = True

    _prev_public_slug = story.public_slug if not creating else None

    title = (request.form.get("title") or "").strip()[:255]
    if not title:
        flash("Title is required", "danger")
        return redirect(_safe_referrer() or url_for("main.story_new", **_story_embed_kwargs()))
    story.title = title

    explicit_slug = None
    if current_user.is_authenticated and current_user.can_edit_frontend():
        explicit_slug = _normalize_slug(request.form.get("slug"))

    title_slug = _normalize_slug(story.title)
    base = explicit_slug or title_slug
    unique = _unique_story_slug(base, exclude_id=story.id if not creating else None)
    if explicit_slug:
        story.slug = unique
        if explicit_slug != unique:
            flash(f"URL already taken — saved as “{unique}”.", "info")
    else:
        story.slug = None if unique == title_slug else unique

    story.summary = (request.form.get("summary") or "").strip() or None
    story.body = (request.form.get("body") or "").strip() or None
    story.author_name = (request.form.get("author_name") or "").strip()[:120] or None
    story.author_bio = (request.form.get("author_bio") or "").strip() or None
    story.sobriety_date = _parse_date_only(request.form.get("sobriety_date"))
    story.story_date = _parse_date_only(request.form.get("story_date"))
    story.is_featured = request.form.get("is_featured") == "1"
    if "published_at" in request.form:
        story.published_at = _parse_post_dt(request.form.get("published_at"))

    if request.form.get("clear_featured_image") == "1":
        old = story.featured_image_filename
        story.featured_image_filename = None
        _cleanup_retired_asset(old)
    uploaded = request.files.get("featured_image")
    if uploaded and uploaded.filename:
        old = story.featured_image_filename
        stored, _original = _save_upload(uploaded)
        story.featured_image_filename = stored
        if old and old != stored:
            _cleanup_retired_asset(old)

    action = (request.form.get("action") or "").strip()
    if action == "draft":
        story.is_draft = True
    elif action == "publish":
        story.is_draft = False
    elif creating:
        story.is_draft = False

    if creating and story.published_at is None:
        # Site-local naive — same convention as Post.published_at and
        # the form's `_parse_post_dt`, so the auto-stamp shows at the
        # right wall-clock time without a tz conversion at display.
        from .timezone import now_local_naive as _now_local
        story.published_at = _now_local(_get_site_setting())

    if creating:
        db.session.add(story)
    else:
        if _prev_public_slug and _prev_public_slug != story.public_slug:
            _record_slug_change("story", story.id, _prev_public_slug, story.public_slug)
    db.session.commit()
    from . import activity
    activity.log("story.create" if creating else "story.update",
                 entity_type="story", entity_id=story.id,
                 summary=(f"Created story “{story.title}”" if creating
                          else f"Updated story “{story.title}”"))
    if creating:
        flash(("Draft saved: " + story.title) if story.is_draft else ("Published: " + story.title), "success")
        # In embed mode (iframe-hosted New-story modal), redirect into
        # the edit screen so the admin can keep iterating without
        # losing the modal context. The "Cancel" button (which becomes
        # a Close button in embed mode) postMessages the parent to
        # close + reload the stories list.
        if _story_embed():
            return redirect(url_for("main.story_edit", sid=story.id, embed=1))
        return redirect(url_for("main.stories", show=("drafts" if story.is_draft else "active")))
    flash("Story saved", "success")
    return redirect(url_for("main.story_edit", sid=story.id, **_story_embed_kwargs()))


@bp.route("/stories/<int:sid>/publish", methods=["POST"])
@login_required
def story_publish(sid):
    _require_stories_enabled()
    story = db.session.get(Story, sid) or abort(404)
    story.is_draft = False
    db.session.commit()
    flash("Published", "success")
    if _story_embed():
        return redirect(url_for("main.story_edit", sid=sid, embed=1))
    return redirect(_safe_referrer() or url_for("main.stories"))


@bp.route("/stories/<int:sid>/unpublish", methods=["POST"])
@login_required
def story_unpublish(sid):
    _require_stories_enabled()
    story = db.session.get(Story, sid) or abort(404)
    story.is_draft = True
    db.session.commit()
    flash("Moved to drafts", "success")
    if _story_embed():
        return redirect(url_for("main.story_edit", sid=sid, embed=1))
    return redirect(_safe_referrer() or url_for("main.stories", show="drafts"))


@bp.route("/stories/<int:sid>/archive", methods=["POST"])
@login_required
def story_archive(sid):
    _require_stories_enabled()
    story = db.session.get(Story, sid) or abort(404)
    story.is_archived = True
    db.session.commit()
    flash("Archived", "success")
    if _story_embed():
        return redirect(url_for("main.story_edit", sid=sid, embed=1))
    return redirect(_safe_referrer() or url_for("main.stories"))


@bp.route("/stories/<int:sid>/unarchive", methods=["POST"])
@login_required
def story_unarchive(sid):
    _require_stories_enabled()
    story = db.session.get(Story, sid) or abort(404)
    story.is_archived = False
    db.session.commit()
    flash("Restored", "success")
    if _story_embed():
        return redirect(url_for("main.story_edit", sid=sid, embed=1))
    return redirect(_safe_referrer() or url_for("main.stories"))


@bp.route("/stories/<int:sid>/delete", methods=["POST"])
@login_required
def story_delete(sid):
    _require_stories_enabled()
    story = db.session.get(Story, sid) or abort(404)
    from . import activity
    activity.log("story.delete", entity_type="story", entity_id=story.id,
                 summary=f"Deleted story “{story.title}”")
    old_image = story.featured_image_filename
    body_inline_stored = _collect_body_inline_stored(story.body)
    story.featured_image_filename = None
    if old_image:
        _cleanup_retired_asset(old_image)
    db.session.delete(story)
    db.session.commit()
    for s in body_inline_stored:
        _cleanup_retired_asset(s)
    flash("Story deleted", "success")
    # When deleting from inside the new-story modal, render a tiny
    # auto-close stub that postMessages the parent so the modal goes
    # away and the underlying stories list refreshes (the deleted row
    # disappears).
    if _story_embed():
        return render_template("story_modal_close.html", message="Story deleted")
    return redirect(url_for("main.stories"))


@bp.route("/stories/bulk", methods=["POST"])
@login_required
def story_bulk():
    """Apply a single state change to many stories at once. Form fields:

      action  — one of archive | unarchive | draft | publish | delete
      ids     — repeated ``ids`` field, one per checked row

    Stories whose ids don't resolve are silently skipped so a stale
    form (e.g. someone deleted a story in another tab) doesn't error
    out the whole batch. Image cleanup runs once for delete actions,
    after the rows are removed."""
    _require_stories_enabled()
    action = (request.form.get("action") or "").strip().lower()
    if action not in ("archive", "unarchive", "draft", "publish", "delete"):
        flash("Unknown bulk action", "danger")
        return redirect(_safe_referrer() or url_for("main.stories"))

    raw_ids = request.form.getlist("ids")
    sids = []
    for v in raw_ids:
        try:
            sids.append(int(v))
        except (TypeError, ValueError):
            continue
    if not sids:
        flash("No stories selected", "warning")
        return redirect(_safe_referrer() or url_for("main.stories"))

    rows = Story.query.filter(Story.id.in_(sids)).all()
    if not rows:
        flash("No stories matched the selection", "warning")
        return redirect(_safe_referrer() or url_for("main.stories"))

    from . import activity
    n = len(rows)
    label = {"archive": "archived", "unarchive": "restored",
             "draft": "moved to drafts", "publish": "published",
             "delete": "deleted"}[action]

    if action == "delete":
        # Snapshot every asset path BEFORE the rows are removed so the
        # post-commit cleanup pass has the full set to walk. Image
        # references are cleared first so `_cleanup_retired_asset`'s
        # residual-reference check sees the row no longer points at
        # the file.
        retired_assets = []
        retired_inline = []
        for s in rows:
            if s.featured_image_filename:
                retired_assets.append(s.featured_image_filename)
                s.featured_image_filename = None
            retired_inline.extend(_collect_body_inline_stored(s.body))
        for s in rows:
            db.session.delete(s)
        db.session.commit()
        for asset in retired_assets:
            _cleanup_retired_asset(asset)
        for asset in retired_inline:
            _cleanup_retired_asset(asset)
    else:
        for s in rows:
            if action == "archive":
                s.is_archived = True
            elif action == "unarchive":
                s.is_archived = False
            elif action == "draft":
                s.is_draft = True
            elif action == "publish":
                s.is_draft = False
                s.is_archived = False
        db.session.commit()

    activity.log(f"story.bulk_{action}", entity_type="story",
                 summary=f"Bulk {label} {n} stor{'ies' if n != 1 else 'y'}")
    flash(f"{n} stor{'ies' if n != 1 else 'y'} {label}", "success")
    return redirect(_safe_referrer() or url_for("main.stories"))


@public_bp.route("/story-image/<int:sid>")
def story_featured_image(sid):
    """Serve a story's featured image. Public so the public web frontend
    can render the image on /stories and /stories/<slug> without auth.

    Optional ``?thumb=<size>`` query param (sizes in
    ``thumbnails.ALLOWED_SIZES``) returns a fitted-into-<size>x<size>
    thumbnail instead, generated lazily on first request and cached
    next to the source. Lets the admin list + public list templates
    avoid loading multi-MB hero images for postage-stamp tiles."""
    st = db.session.get(Story, sid)
    if not st or not st.featured_image_filename:
        abort(404)
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    thumb_arg = (request.args.get("thumb") or "").strip()
    if thumb_arg:
        from . import thumbnails
        try:
            size = int(thumb_arg)
        except ValueError:
            size = None
        if size and size in thumbnails.ALLOWED_SIZES:
            thumb_name = thumbnails.ensure_thumb(st.featured_image_filename, size,
                                                 upload_dir=upload_dir)
            if thumb_name:
                resp = send_from_directory(upload_dir, thumb_name)
                # 1-day public cache — thumbs are content-addressed by
                # the (uuid-prefixed) source filename so a content
                # change rolls the URL anyway.
                resp.headers["Cache-Control"] = "public, max-age=86400"
                return resp
    return send_from_directory(upload_dir, st.featured_image_filename)


@public_bp.route("/meeting-logo/<int:mid>")
def public_meeting_logo(mid):
    """Serve a meeting's uploaded logo to anonymous visitors so the public
    meeting detail page can show it. Mirrors post_featured_image."""
    m = db.session.get(Meeting, mid)
    if not m or not m.logo_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], m.logo_filename)


# ---------------------------------------------------------------------------
# Blog — long-form editorial posts with categories + tags. The same
# data table can serve many distinct frontend "blogs" by filtering
# the page-block on category/tag, which lets a fellowship host one
# blog per committee or group without parallel data tables.
# ---------------------------------------------------------------------------
def _estimate_reading_minutes(text):
    """Rough reading-time estimate. ~225 words per minute is the canonical
    number for English prose; we round up so a one-line post still
    reads as "1 min". Returns None on empty input so the column can
    stay NULL."""
    if not text:
        return None
    word_count = len(re.findall(r"\b\w+\b", text))
    if word_count <= 0:
        return None
    return max(1, (word_count + 224) // 225)


# Block types the visual blog-body editor knows how to render. The
# save handler drops unknown types so a tampered form post can't
# slip an arbitrary block schema into storage. Keep in sync with
# the JS palette in `static/js/post_body_editor.js` AND the public
# render macro in `templates/_blog_blocks.html`.
_BLOG_BLOCK_TYPES = {
    "paragraph", "heading", "image", "button", "list",
    "quote", "callout", "separator", "video", "code",
    "section",
}


def _sanitize_blog_body_blocks(raw):
    """Normalize the JSON payload submitted by the visual block editor.
    Returns a JSON string ready for storage (or NULL when the input
    is empty / malformed). Strips unknown block types, coerces field
    types, caps string lengths, and limits nesting so a malicious
    form post can't smuggle arbitrary HTML or oversized payloads.

    The editor always submits a JSON array; the per-block ``data``
    dict is shaped by ``renderBlock()`` in post_body_editor.js."""
    import json
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, list):
        return None
    out = _sanitize_blog_block_list(parsed, depth=0)
    if not out:
        return None
    return json.dumps(out, ensure_ascii=False)


def _sanitize_blog_block_list(items, depth):
    """Walk a list of `{type, data}` block dicts, drop unknown types,
    coerce each block's data through `_sanitize_blog_block_data`, and
    return the cleaned list. Hard caps:
      * 200 blocks per list
      * 1 level of nesting (the Section block carries its own
        children, but a Section can't contain another Section).
    Both caps protect the JSON column from forged or runaway payloads."""
    if not isinstance(items, list):
        return []
    out = []
    for entry in items[:200]:
        if not isinstance(entry, dict):
            continue
        t = entry.get("type")
        if t not in _BLOG_BLOCK_TYPES:
            continue
        # Disallow nested sections beyond depth 1 — keeps the schema
        # shallow and the editor predictable.
        if t == "section" and depth >= 1:
            continue
        d = entry.get("data") if isinstance(entry.get("data"), dict) else {}
        clean = _sanitize_blog_block_data(t, d, depth=depth)
        out.append({"type": t, "data": clean})
    return out


def _sanitize_blog_block_data(t, d, depth=0):
    """Per-type field coercion for the visual block editor. Each branch
    cherry-picks the fields it cares about so a forged payload can't
    smuggle extra keys into storage. Length caps are generous but
    bounded; rich-text fields (`md`) ride through the existing
    bleach-allowlist markdown filter on the render side, so storing
    raw markdown here is safe.

    ``depth`` lets the Section branch recursively sanitize its
    children with a depth +1 so nested sections are dropped."""
    def s(v, cap=10000):
        if v is None:
            return ""
        return str(v)[:cap]
    def margin_rem(v, default):
        # Margin inputs are numeric rem values. Coerce to float,
        # clamp to a sensible range, and round to 2 dp so we don't
        # persist 3.0000000001 noise from input rounding.
        try:
            n = float(v)
        except (TypeError, ValueError):
            return default
        if n < 0:
            n = 0
        elif n > 20:
            n = 20
        return round(n, 2)
    if t == "paragraph":
        return {"md": s(d.get("md"), 20000)}
    if t == "heading":
        try:
            lvl = int(d.get("level") or 2)
        except (TypeError, ValueError):
            lvl = 2
        lvl = lvl if lvl in (2, 3, 4) else 2
        return {"level": lvl, "text": s(d.get("text"), 400)}
    if t == "image":
        try:
            w = int(d.get("width_pct") or 100)
        except (TypeError, ValueError):
            w = 100
        w = max(20, min(100, w))
        align = (d.get("align") or "center").lower()
        if align not in ("left", "center", "right"):
            align = "center"
        # Box-shadow intensity. Empty string means no shadow; the
        # four named tiers (sm/md/lg/xl) match the recipes already
        # used by the page-builder image block in `_blocks.html`
        # so a writer who knows one knows the other.
        shadow = (d.get("shadow") or "").lower()
        if shadow not in ("", "sm", "md", "lg", "xl"):
            shadow = ""
        return {
            "src": s(d.get("src"), 1000),
            "alt": s(d.get("alt"), 400),
            "caption": s(d.get("caption"), 600),
            "align": align,
            "width_pct": w,
            "shadow": shadow,
            # Per-image vertical spacing — defaults to 1.5rem to
            # preserve the longstanding `.bb-image { margin: 1.5rem
            # auto }` CSS default, so existing posts keep their
            # familiar spacing until the writer dials it. Shares the
            # same `margin_rem` clamp the Section block uses.
            "margin_top": margin_rem(d.get("margin_top"), 1.5),
            "margin_bottom": margin_rem(d.get("margin_bottom"), 1.5),
        }
    if t == "button":
        style = (d.get("style") or "primary").lower()
        if style not in ("primary", "secondary"):
            style = "primary"
        align = (d.get("align") or "left").lower()
        if align not in ("left", "center", "right"):
            align = "left"
        return {
            "label": s(d.get("label"), 200) or "Click here",
            "url": s(d.get("url"), 1000) or "#",
            "style": style,
            "align": align,
            "new_tab": bool(d.get("new_tab")),
        }
    if t == "list":
        items = d.get("items") if isinstance(d.get("items"), list) else []
        clean_items = []
        for item in items[:200]:
            clean_items.append(s(item, 1000))
        return {"ordered": bool(d.get("ordered")), "items": clean_items}
    if t == "quote":
        return {"text": s(d.get("text"), 4000),
                "author": s(d.get("author"), 200)}
    if t == "callout":
        variant = (d.get("variant") or "info").lower()
        if variant not in ("info", "warn", "success", "danger"):
            variant = "info"
        return {"variant": variant,
                "title": s(d.get("title"), 200),
                "md": s(d.get("md"), 8000)}
    if t == "separator":
        return {}
    if t == "video":
        return {"url": s(d.get("url"), 1000),
                "caption": s(d.get("caption"), 400)}
    if t == "code":
        return {"lang": s(d.get("lang"), 40),
                "code": s(d.get("code"), 20000)}
    if t == "section":
        # Container block. Stores top + bottom margin (in rem) and a
        # recursive child block list. Inner sections are stripped by
        # the depth gate in `_sanitize_blog_block_list`.
        return {
            "margin_top": margin_rem(d.get("margin_top"), 3),
            "margin_bottom": margin_rem(d.get("margin_bottom"), 3),
            "blocks": _sanitize_blog_block_list(
                d.get("blocks") if isinstance(d.get("blocks"), list) else [],
                depth=depth + 1),
        }
    return {}


def _blog_blocks_to_plain_text(blocks):
    """Best-effort plain-text projection of the block list. Used as the
    word-count source for the auto reading-time estimate. Skips block
    types that don't carry prose (image / separator / video URL)."""
    if not blocks:
        return ""
    bits = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        d = b.get("data") or {}
        if t == "paragraph":
            bits.append(str(d.get("md") or ""))
        elif t == "heading":
            bits.append(str(d.get("text") or ""))
        elif t == "list":
            for it in (d.get("items") or []):
                bits.append(str(it))
        elif t == "quote":
            bits.append(str(d.get("text") or ""))
            bits.append(str(d.get("author") or ""))
        elif t == "callout":
            bits.append(str(d.get("title") or ""))
            bits.append(str(d.get("md") or ""))
        elif t == "code":
            bits.append(str(d.get("code") or ""))
        elif t == "image":
            bits.append(str(d.get("caption") or ""))
            bits.append(str(d.get("alt") or ""))
        elif t == "section":
            # Recurse into the section's children so prose inside a
            # section contributes to the reading-time estimate.
            bits.append(_blog_blocks_to_plain_text(d.get("blocks") or []))
    return " ".join(filter(None, bits))


def _resolve_blog_category_ids(form):
    """Pull selected category ids out of the multi-checkbox form. Filters
    out anything that doesn't resolve to an existing row so a stale
    deleted id doesn't error the save."""
    raw = form.getlist("category_ids") if hasattr(form, "getlist") else []
    out = []
    for v in raw:
        try:
            cid = int(v)
        except (TypeError, ValueError):
            continue
        if BlogCategory.query.get(cid):
            out.append(cid)
    return out


def _resolve_blog_tag_assignments(form):
    """Resolve tag assignments from the form. Supports two inputs:
    a multi-select of existing tag ids (``tag_ids``) AND a free-text
    field of comma-separated names (``tag_names_new``). New names are
    auto-created with a unique slug. Returns a list of BlogTag rows
    (existing + newly-added). Caller still has to commit."""
    raw_ids = form.getlist("tag_ids") if hasattr(form, "getlist") else []
    rows = []
    seen = set()
    for v in raw_ids:
        try:
            tid = int(v)
        except (TypeError, ValueError):
            continue
        t = BlogTag.query.get(tid)
        if t and t.id not in seen:
            seen.add(t.id)
            rows.append(t)
    new_names = (form.get("tag_names_new") or "").strip()
    if new_names:
        for raw_name in new_names.split(","):
            name = raw_name.strip()[:80]
            if not name:
                continue
            existing = BlogTag.query.filter(db.func.lower(BlogTag.name) == name.lower()).first()
            if existing:
                if existing.id not in seen:
                    seen.add(existing.id)
                    rows.append(existing)
                continue
            slug = _unique_blog_taxonomy_slug(BlogTag, _normalize_slug(name) or name.lower())
            tag = BlogTag(name=name, slug=slug)
            db.session.add(tag)
            db.session.flush()
            seen.add(tag.id)
            rows.append(tag)
    return rows


@bp.route("/blog")
@login_required
def blog_index():
    _require_blog_enabled()
    show = (request.args.get("show") or "active").strip()
    sort = (request.args.get("sort") or "published_desc").strip()
    cat_id = (request.args.get("category") or "").strip()
    tag_id = (request.args.get("tag") or "").strip()
    q_text = (request.args.get("q") or "").strip()
    q = BlogPost.query
    if show == "archived":
        q = q.filter(BlogPost.is_archived.is_(True))
    elif show == "drafts":
        q = q.filter(BlogPost.is_draft.is_(True), BlogPost.is_archived.is_(False))
    elif show == "featured":
        q = q.filter(BlogPost.is_featured.is_(True),
                     BlogPost.is_archived.is_(False),
                     BlogPost.is_draft.is_(False))
    else:
        show = "active"
        q = q.filter(BlogPost.is_archived.is_(False), BlogPost.is_draft.is_(False))
    # Category / tag filters.
    if cat_id.isdigit():
        q = q.filter(BlogPost.categories.any(BlogCategory.id == int(cat_id)))
    if tag_id.isdigit():
        q = q.filter(BlogPost.tags.any(BlogTag.id == int(tag_id)))
    # Title / summary search — small dataset, basic ILIKE is enough.
    if q_text:
        like = f"%{q_text}%"
        q = q.filter(db.or_(BlogPost.title.ilike(like),
                            BlogPost.summary.ilike(like),
                            BlogPost.author_name.ilike(like)))
    # Sort modes.
    if sort == "published_asc":
        q = q.order_by(BlogPost.is_pinned.desc(),
                       BlogPost.published_at.asc().nulls_last(),
                       BlogPost.created_at.asc())
    elif sort == "title_asc":
        q = q.order_by(BlogPost.is_pinned.desc(), BlogPost.title.asc())
    elif sort == "title_desc":
        q = q.order_by(BlogPost.is_pinned.desc(), BlogPost.title.desc())
    elif sort == "updated_desc":
        q = q.order_by(BlogPost.is_pinned.desc(), BlogPost.updated_at.desc())
    elif sort == "author_asc":
        q = q.order_by(BlogPost.is_pinned.desc(),
                       BlogPost.author_name.asc().nulls_last(),
                       BlogPost.published_at.desc().nulls_last())
    else:  # published_desc
        sort = "published_desc"
        q = q.order_by(BlogPost.is_pinned.desc(),
                       BlogPost.published_at.desc().nulls_last(),
                       BlogPost.created_at.desc())
    items = q.all()
    categories = BlogCategory.query.order_by(BlogCategory.position, BlogCategory.name).all()
    tags = BlogTag.query.order_by(BlogTag.name).all()
    counts = {
        "active": BlogPost.query.filter(BlogPost.is_archived.is_(False),
                                         BlogPost.is_draft.is_(False)).count(),
        "drafts": BlogPost.query.filter(BlogPost.is_draft.is_(True),
                                         BlogPost.is_archived.is_(False)).count(),
        "archived": BlogPost.query.filter(BlogPost.is_archived.is_(True)).count(),
        "featured": BlogPost.query.filter(BlogPost.is_featured.is_(True),
                                           BlogPost.is_archived.is_(False),
                                           BlogPost.is_draft.is_(False)).count(),
    }
    return render_template("blog_list.html", posts=items, show=show, sort=sort,
                           categories=categories, tags=tags,
                           selected_cat=cat_id, selected_tag=tag_id, q_text=q_text,
                           counts=counts)


def _blog_author_choices():
    """Intergroup officers — the public-facing roster managed from
    Settings → Global — surfaced as the author picker on the blog
    edit page. We pull `name` (falling back to `role` when the
    officer row hasn't been given a name yet) and ignore empty
    entries so the dropdown doesn't carry blank options.

    The picker stores the resolved name string in `BlogPost.author_name`
    so the public templates keep rendering the byline as text —
    decoupled from the officer row's id, which means renaming the
    officer later won't retroactively change historical posts'
    bylines."""
    seen = set()
    out = []
    rows = (IntergroupOfficer.query
            .order_by(IntergroupOfficer.sort_order, IntergroupOfficer.role)
            .all())
    for o in rows:
        name = (o.name or o.role or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "role": o.role or ""})
    return out


@bp.route("/blog/new")
@login_required
def blog_new():
    _require_blog_enabled()
    categories = BlogCategory.query.order_by(BlogCategory.position, BlogCategory.name).all()
    tags = BlogTag.query.order_by(BlogTag.name).all()
    return render_template("blog_edit.html", post=None,
                           categories=categories, tags=tags,
                           author_choices=_blog_author_choices())


@bp.route("/blog/<int:bid>")
@login_required
def blog_edit(bid):
    _require_blog_enabled()
    post = db.session.get(BlogPost, bid) or abort(404)
    categories = BlogCategory.query.order_by(BlogCategory.position, BlogCategory.name).all()
    tags = BlogTag.query.order_by(BlogTag.name).all()
    return render_template("blog_edit.html", post=post,
                           categories=categories, tags=tags,
                           author_choices=_blog_author_choices())


@bp.route("/blog/save", methods=["POST"])
@login_required
def blog_save():
    """Create or update a blog post. ``post_id`` empty → create, set →
    update. Mirrors ``story_save`` shape."""
    _require_blog_enabled()
    pid_raw = (request.form.get("post_id") or "").strip()
    if pid_raw:
        post = db.session.get(BlogPost, int(pid_raw)) or abort(404)
        creating = False
    else:
        post = BlogPost(created_by=getattr(current_user, "id", None))
        creating = True

    _prev_public_slug = post.public_slug if not creating else None

    title = (request.form.get("title") or "").strip()[:255]
    if not title:
        flash("Title is required", "danger")
        return redirect(_safe_referrer() or url_for("main.blog_new"))
    post.title = title

    explicit_slug = None
    if current_user.is_authenticated and current_user.can_edit_frontend():
        explicit_slug = _normalize_slug(request.form.get("slug"))

    title_slug = _normalize_slug(post.title)
    base = explicit_slug or title_slug
    unique = _unique_blog_slug(base, exclude_id=post.id if not creating else None)
    if explicit_slug:
        post.slug = unique
        if explicit_slug != unique:
            flash(f"URL already taken — saved as “{unique}”.", "info")
    else:
        post.slug = None if unique == title_slug else unique

    post.summary = (request.form.get("summary") or "").strip() or None
    post.body = (request.form.get("body") or "").strip() or None
    # Drag-and-drop block editor payload — saved verbatim when the form
    # carries a JSON-list value. The JS editor always submits a JSON
    # array (possibly empty); `_sanitize_blog_body_blocks` strips
    # unknown block types, coerces fields, and re-serialises so a
    # malicious form post can't smuggle arbitrary HTML into storage.
    blocks_raw = (request.form.get("body_blocks_json") or "").strip()
    if blocks_raw:
        post.body_blocks_json = _sanitize_blog_body_blocks(blocks_raw)
    else:
        post.body_blocks_json = None
    post.author_name = (request.form.get("author_name") or "").strip()[:120] or None
    # author_bio is no longer surfaced in the editor — legacy values
    # on existing posts are preserved (the column stays on the
    # model) but the form never overwrites them.
    post.published_at = _parse_post_dt(request.form.get("published_at"))
    post.is_featured = request.form.get("is_featured") == "1"
    post.is_pinned = request.form.get("is_pinned") == "1"

    rm_raw = (request.form.get("reading_minutes") or "").strip()
    if rm_raw.isdigit():
        post.reading_minutes = max(1, min(999, int(rm_raw)))
    else:
        # Estimate from blocks first (they're the source of truth for
        # newly-edited posts); fall back to the legacy markdown body
        # for posts that haven't been converted yet.
        est_source = _blog_blocks_to_plain_text(post.body_blocks) or (post.body or "")
        post.reading_minutes = _estimate_reading_minutes(est_source)

    if request.form.get("clear_featured_image") == "1":
        old = post.featured_image_filename
        post.featured_image_filename = None
        _cleanup_retired_asset(old)
    uploaded = request.files.get("featured_image")
    if uploaded and uploaded.filename:
        # Fresh upload — wins over any library pick on the same submit.
        # The "Browse library" JS clears the file input on pick (and
        # vice-versa) so a single save round-trip only carries one of
        # the two, but if both happen to arrive together the upload
        # is the more recent intent.
        old = post.featured_image_filename
        stored, _original = _save_upload(uploaded)
        post.featured_image_filename = stored
        if old and old != stored:
            _cleanup_retired_asset(old)
    else:
        # Library pick — the writer clicked Browse, picked a tile,
        # and the JS stamped the MediaItem id into the hidden field.
        # Look up the row and reuse its already-stored filename so we
        # don't duplicate the file on disk.
        media_id_raw = (request.form.get("featured_image_media_id") or "").strip()
        if media_id_raw.isdigit():
            m = db.session.get(MediaItem, int(media_id_raw))
            if m and m.stored_filename:
                old = post.featured_image_filename
                post.featured_image_filename = m.stored_filename
                if old and old != m.stored_filename:
                    _cleanup_retired_asset(old)

    # Category + tag relations — must flush the post first when creating
    # so the M2M tables have a real id to reference.
    if creating:
        db.session.add(post)
        db.session.flush()
    cat_ids = _resolve_blog_category_ids(request.form)
    post.categories = BlogCategory.query.filter(BlogCategory.id.in_(cat_ids)).all() if cat_ids else []
    post.tags = _resolve_blog_tag_assignments(request.form)

    action = (request.form.get("action") or "").strip()
    if action == "draft":
        post.is_draft = True
    elif action == "publish":
        post.is_draft = False
        if post.published_at is None:
            post.published_at = datetime.utcnow()
    elif creating:
        post.is_draft = False
        if post.published_at is None:
            post.published_at = datetime.utcnow()

    if not creating:
        if _prev_public_slug and _prev_public_slug != post.public_slug:
            _record_slug_change("blog", post.id, _prev_public_slug, post.public_slug)
    db.session.commit()
    from . import activity
    activity.log("blog.create" if creating else "blog.update",
                 entity_type="blog", entity_id=post.id,
                 summary=(f"Created blog post “{post.title}”" if creating
                          else f"Updated blog post “{post.title}”"))
    if creating:
        flash(("Draft saved: " + post.title) if post.is_draft else ("Published: " + post.title), "success")
        return redirect(url_for("main.blog_index", show=("drafts" if post.is_draft else "active")))
    flash("Post saved", "success")
    return redirect(url_for("main.blog_edit", bid=post.id))


@bp.route("/blog/<int:bid>/publish", methods=["POST"])
@login_required
def blog_publish(bid):
    _require_blog_enabled()
    post = db.session.get(BlogPost, bid) or abort(404)
    post.is_draft = False
    if post.published_at is None:
        post.published_at = datetime.utcnow()
    db.session.commit()
    flash("Published", "success")
    return redirect(_safe_referrer() or url_for("main.blog_index"))


@bp.route("/blog/<int:bid>/unpublish", methods=["POST"])
@login_required
def blog_unpublish(bid):
    _require_blog_enabled()
    post = db.session.get(BlogPost, bid) or abort(404)
    post.is_draft = True
    db.session.commit()
    flash("Moved to drafts", "success")
    return redirect(_safe_referrer() or url_for("main.blog_index", show="drafts"))


@bp.route("/blog/<int:bid>/archive", methods=["POST"])
@login_required
def blog_archive(bid):
    _require_blog_enabled()
    post = db.session.get(BlogPost, bid) or abort(404)
    post.is_archived = True
    db.session.commit()
    flash("Archived", "success")
    return redirect(_safe_referrer() or url_for("main.blog_index"))


@bp.route("/blog/<int:bid>/unarchive", methods=["POST"])
@login_required
def blog_unarchive(bid):
    _require_blog_enabled()
    post = db.session.get(BlogPost, bid) or abort(404)
    post.is_archived = False
    db.session.commit()
    flash("Restored", "success")
    return redirect(_safe_referrer() or url_for("main.blog_index"))


@bp.route("/blog/<int:bid>/duplicate", methods=["POST"])
@login_required
def blog_duplicate(bid):
    """Clone a blog post into a Draft. Title gets a "(copy)" suffix; the
    duplicate is a draft so the admin can re-tune it before publishing.
    Categories + tags carry over."""
    _require_blog_enabled()
    src = db.session.get(BlogPost, bid) or abort(404)
    copy = BlogPost(
        title=(src.title or "Untitled")[:240] + " (copy)",
        summary=src.summary,
        body=src.body,
        featured_image_filename=src.featured_image_filename,
        author_name=src.author_name,
        author_bio=src.author_bio,
        is_featured=False,
        is_pinned=False,
        is_draft=True,
        is_archived=False,
        reading_minutes=src.reading_minutes,
        created_by=getattr(current_user, "id", None),
    )
    db.session.add(copy)
    db.session.flush()
    copy.categories = list(src.categories)
    copy.tags = list(src.tags)
    db.session.commit()
    flash("Duplicated as draft", "success")
    return redirect(url_for("main.blog_edit", bid=copy.id))


@bp.route("/blog/<int:bid>/delete", methods=["POST"])
@login_required
def blog_delete(bid):
    _require_blog_enabled()
    post = db.session.get(BlogPost, bid) or abort(404)
    from . import activity
    activity.log("blog.delete", entity_type="blog", entity_id=post.id,
                 summary=f"Deleted blog post “{post.title}”")
    old_image = post.featured_image_filename
    body_inline_stored = _collect_body_inline_stored(post.body)
    post.featured_image_filename = None
    if old_image:
        _cleanup_retired_asset(old_image)
    db.session.delete(post)
    db.session.commit()
    for s in body_inline_stored:
        _cleanup_retired_asset(s)
    flash("Post deleted", "success")
    return redirect(url_for("main.blog_index"))


@bp.route("/blog/bulk", methods=["POST"])
@login_required
def blog_bulk():
    """Apply a single state change to many blog posts at once. Form
    fields:

      action    — archive | unarchive | draft | publish | delete
                | feature | unfeature | pin | unpin
                | add_category | remove_category | replace_categories
                | add_tag | remove_tag
      ids       — repeated ``ids`` field, one per checked row
      category_id — int (required for *_category actions)
      tag_id      — int (required for *_tag actions)

    Posts whose ids don't resolve are silently skipped so a stale
    form (e.g. someone deleted a post in another tab) doesn't error
    out the whole batch."""
    _require_blog_enabled()
    action = (request.form.get("action") or "").strip().lower()
    valid = {"archive", "unarchive", "draft", "publish", "delete",
             "feature", "unfeature", "pin", "unpin",
             "add_category", "remove_category", "replace_categories",
             "add_tag", "remove_tag"}
    if action not in valid:
        flash("Unknown bulk action", "danger")
        return redirect(_safe_referrer() or url_for("main.blog_index"))

    raw_ids = request.form.getlist("ids")
    pids = []
    for v in raw_ids:
        try:
            pids.append(int(v))
        except (TypeError, ValueError):
            continue
    if not pids:
        flash("No posts selected", "warning")
        return redirect(_safe_referrer() or url_for("main.blog_index"))

    rows = BlogPost.query.filter(BlogPost.id.in_(pids)).all()
    if not rows:
        flash("No posts matched the selection", "warning")
        return redirect(_safe_referrer() or url_for("main.blog_index"))

    n = len(rows)
    label = ""

    if action == "delete":
        retired_assets = []
        retired_inline = []
        for p in rows:
            if p.featured_image_filename:
                retired_assets.append(p.featured_image_filename)
                p.featured_image_filename = None
            retired_inline.extend(_collect_body_inline_stored(p.body))
        for p in rows:
            db.session.delete(p)
        db.session.commit()
        for asset in retired_assets:
            _cleanup_retired_asset(asset)
        for asset in retired_inline:
            _cleanup_retired_asset(asset)
        label = "deleted"
    elif action in ("add_category", "remove_category", "replace_categories"):
        try:
            cid = int(request.form.get("category_id") or 0)
        except (TypeError, ValueError):
            cid = 0
        cat = db.session.get(BlogCategory, cid) if cid else None
        if cat is None:
            flash("Pick a category to apply.", "warning")
            return redirect(_safe_referrer() or url_for("main.blog_index"))
        for p in rows:
            if action == "add_category":
                if cat not in p.categories:
                    p.categories.append(cat)
            elif action == "remove_category":
                if cat in p.categories:
                    p.categories.remove(cat)
            else:  # replace_categories
                p.categories = [cat]
        db.session.commit()
        label = {
            "add_category": f"tagged with “{cat.name}”",
            "remove_category": f"untagged from “{cat.name}”",
            "replace_categories": f"category set to “{cat.name}”",
        }[action]
    elif action in ("add_tag", "remove_tag"):
        try:
            tid = int(request.form.get("tag_id") or 0)
        except (TypeError, ValueError):
            tid = 0
        tag = db.session.get(BlogTag, tid) if tid else None
        if tag is None:
            flash("Pick a tag to apply.", "warning")
            return redirect(_safe_referrer() or url_for("main.blog_index"))
        for p in rows:
            if action == "add_tag":
                if tag not in p.tags:
                    p.tags.append(tag)
            else:
                if tag in p.tags:
                    p.tags.remove(tag)
        db.session.commit()
        label = (f"tagged #{tag.name}" if action == "add_tag"
                 else f"untagged from #{tag.name}")
    else:
        for p in rows:
            if action == "archive":
                p.is_archived = True
            elif action == "unarchive":
                p.is_archived = False
            elif action == "draft":
                p.is_draft = True
            elif action == "publish":
                p.is_draft = False
                p.is_archived = False
                if p.published_at is None:
                    p.published_at = datetime.utcnow()
            elif action == "feature":
                p.is_featured = True
            elif action == "unfeature":
                p.is_featured = False
            elif action == "pin":
                p.is_pinned = True
            elif action == "unpin":
                p.is_pinned = False
        db.session.commit()
        label = {"archive": "archived", "unarchive": "restored",
                 "draft": "moved to drafts", "publish": "published",
                 "feature": "marked featured", "unfeature": "unfeatured",
                 "pin": "pinned", "unpin": "unpinned"}[action]

    from . import activity
    activity.log(f"blog.bulk_{action}", entity_type="blog",
                 summary=f"Bulk {action}: {n} post{'s' if n != 1 else ''} {label}")
    flash(f"{n} post{'s' if n != 1 else ''} {label}", "success")
    return redirect(_safe_referrer() or url_for("main.blog_index"))


# ─── Categories ──────────────────────────────────────────────────────
@bp.route("/blog/categories")
@login_required
def blog_categories():
    _require_blog_enabled()
    categories = BlogCategory.query.order_by(BlogCategory.position, BlogCategory.name).all()
    # Posts-per-category (active + drafts, excluding archived) so the
    # admin can see at a glance which categories are in use.
    counts = {}
    for c in categories:
        counts[c.id] = (BlogPost.query
                        .filter(BlogPost.is_archived.is_(False))
                        .filter(BlogPost.categories.any(BlogCategory.id == c.id))
                        .count())
    return render_template("blog_categories.html", categories=categories, counts=counts)


@bp.route("/blog/categories/save", methods=["POST"])
@login_required
def blog_category_save():
    _require_blog_enabled()
    cid_raw = (request.form.get("category_id") or "").strip()
    if cid_raw:
        cat = db.session.get(BlogCategory, int(cid_raw)) or abort(404)
        creating = False
    else:
        cat = BlogCategory()
        creating = True
    name = (request.form.get("name") or "").strip()[:120]
    if not name:
        flash("Category name is required", "danger")
        return redirect(url_for("main.blog_categories"))
    cat.name = name
    explicit_slug = _normalize_slug(request.form.get("slug"))
    base = explicit_slug or _normalize_slug(name)
    cat.slug = _unique_blog_taxonomy_slug(BlogCategory, base,
                                           exclude_id=cat.id if not creating else None)
    cat.description = (request.form.get("description") or "").strip() or None
    cat.color = (request.form.get("color") or "").strip()[:16] or None
    pos_raw = (request.form.get("position") or "").strip()
    if pos_raw.lstrip("-").isdigit():
        cat.position = int(pos_raw)
    if creating:
        db.session.add(cat)
    db.session.commit()
    flash("Category saved", "success")
    return redirect(url_for("main.blog_categories"))


@bp.route("/blog/tags/quick-add", methods=["POST"])
@login_required
def blog_tag_quick_add():
    """JSON endpoint that mints a fresh `BlogTag` from a single name
    and returns the new row's id/name/slug. Powers the inline
    "Add new tag" affordance on the blog-post edit sidebar so writers
    can tag a post under a brand-new label without leaving the
    editor. Idempotent by name — calling twice with the same name
    just returns the existing row instead of creating a duplicate."""
    _require_blog_enabled()
    name = (request.form.get("name") or "").strip()[:80]
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    existing = (BlogTag.query
                .filter(db.func.lower(BlogTag.name) == name.lower())
                .first())
    if existing:
        return jsonify({"ok": True, "tag": {
            "id": existing.id, "name": existing.name,
            "slug": existing.slug,
        }, "deduped": True})
    slug = _unique_blog_taxonomy_slug(BlogTag,
                                       _normalize_slug(name) or name.lower())
    tag = BlogTag(name=name, slug=slug)
    db.session.add(tag)
    db.session.commit()
    return jsonify({"ok": True, "tag": {
        "id": tag.id, "name": tag.name, "slug": tag.slug,
    }, "deduped": False})


@bp.route("/blog/categories/quick-add", methods=["POST"])
@login_required
def blog_category_quick_add():
    """JSON endpoint that creates a fresh `BlogCategory` from just a
    name and returns the new row's id/name/slug/color. Powers the
    inline "Add new category" affordance on the blog-post edit
    sidebar so writers can file a post under a brand-new category
    without leaving the editor. Idempotent by name — if a category
    with the same casefold name already exists, we return that
    row instead of creating a duplicate."""
    _require_blog_enabled()
    name = (request.form.get("name") or "").strip()[:120]
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    existing = (BlogCategory.query
                .filter(db.func.lower(BlogCategory.name) == name.lower())
                .first())
    if existing:
        return jsonify({"ok": True, "category": {
            "id": existing.id, "name": existing.name,
            "slug": existing.slug, "color": existing.color or "",
        }, "deduped": True})
    slug = _unique_blog_taxonomy_slug(BlogCategory,
                                       _normalize_slug(name) or name.lower())
    cat = BlogCategory(name=name, slug=slug)
    db.session.add(cat)
    db.session.commit()
    return jsonify({"ok": True, "category": {
        "id": cat.id, "name": cat.name,
        "slug": cat.slug, "color": cat.color or "",
    }, "deduped": False})


@bp.route("/blog/categories/<int:cid>/delete", methods=["POST"])
@login_required
def blog_category_delete(cid):
    _require_blog_enabled()
    cat = db.session.get(BlogCategory, cid) or abort(404)
    db.session.delete(cat)
    db.session.commit()
    flash("Category deleted", "success")
    return redirect(url_for("main.blog_categories"))


# ─── Tags ────────────────────────────────────────────────────────────
@bp.route("/blog/tags")
@login_required
def blog_tags():
    _require_blog_enabled()
    tags = BlogTag.query.order_by(BlogTag.name).all()
    counts = {}
    for t in tags:
        counts[t.id] = (BlogPost.query
                        .filter(BlogPost.is_archived.is_(False))
                        .filter(BlogPost.tags.any(BlogTag.id == t.id))
                        .count())
    return render_template("blog_tags.html", tags=tags, counts=counts)


@bp.route("/blog/tags/save", methods=["POST"])
@login_required
def blog_tag_save():
    _require_blog_enabled()
    tid_raw = (request.form.get("tag_id") or "").strip()
    if tid_raw:
        tag = db.session.get(BlogTag, int(tid_raw)) or abort(404)
        creating = False
    else:
        tag = BlogTag()
        creating = True
    name = (request.form.get("name") or "").strip()[:80]
    if not name:
        flash("Tag name is required", "danger")
        return redirect(url_for("main.blog_tags"))
    tag.name = name
    explicit_slug = _normalize_slug(request.form.get("slug"))
    base = explicit_slug or _normalize_slug(name)
    tag.slug = _unique_blog_taxonomy_slug(BlogTag, base,
                                           exclude_id=tag.id if not creating else None)
    if creating:
        db.session.add(tag)
    db.session.commit()
    flash("Tag saved", "success")
    return redirect(url_for("main.blog_tags"))


@bp.route("/blog/tags/<int:tid>/delete", methods=["POST"])
@login_required
def blog_tag_delete(tid):
    _require_blog_enabled()
    tag = db.session.get(BlogTag, tid) or abort(404)
    db.session.delete(tag)
    db.session.commit()
    flash("Tag deleted", "success")
    return redirect(url_for("main.blog_tags"))


@public_bp.route("/blog-image/<int:bid>")
def blog_post_featured_image(bid):
    """Serve a blog post's featured image. Public so the frontend can
    render the image without auth. Same ``?thumb=<size>`` semantics as
    ``story_featured_image`` for postage-stamp tiles in lists."""
    post = db.session.get(BlogPost, bid)
    if not post or not post.featured_image_filename:
        abort(404)
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    thumb_arg = (request.args.get("thumb") or "").strip()
    if thumb_arg:
        from . import thumbnails
        try:
            size = int(thumb_arg)
        except ValueError:
            size = None
        if size and size in thumbnails.ALLOWED_SIZES:
            thumb_name = thumbnails.ensure_thumb(post.featured_image_filename, size,
                                                  upload_dir=upload_dir)
            if thumb_name:
                resp = send_from_directory(upload_dir, thumb_name)
                resp.headers["Cache-Control"] = "public, max-age=86400"
                return resp
    return send_from_directory(upload_dir, post.featured_image_filename)


# ---------------------------------------------------------------------------
# Visitor metrics — admin-only analytics for the public frontend. Logged-in
# users (anyone signed in to the admin portal) are excluded from the
# recorded events upstream, so these queries are purely "real visitors".
# See ``app/visitor_metrics.py`` for the recording hook and aggregators.
# ---------------------------------------------------------------------------

# Allowed window sizes for the metrics page. Anything else falls back to
# the default (30 days) so a hand-crafted query-string can't push the
# window absurdly wide and run an expensive scan.
_METRICS_WINDOWS = (7, 14, 30, 90)


def _resolve_metrics_window(arg):
    try:
        n = int(arg or 30)
    except (ValueError, TypeError):
        return 30
    return n if n in _METRICS_WINDOWS else 30


@bp.route("/frontend/metrics")
@admin_required
def visitor_metrics_page():
    """Admin visitor-metrics dashboard. Lifetime + window summary,
    daily time-series, hour-of-day heat, plus top paths / referrers /
    devices / browsers / OS. The page reads all data straight from
    ``app/visitor_metrics.py``'s aggregators — keeping the route thin
    so the heavy lifting is testable in isolation."""
    from . import visitor_metrics as vm
    window = _resolve_metrics_window(request.args.get("window"))
    return render_template(
        "visitor_metrics.html",
        window=window,
        windows=_METRICS_WINDOWS,
        summary=vm.summary(days=window),
        daily=vm.daily_series(days=window),
        hourly=vm.hourly_distribution(days=min(window, 30)),
        top_paths=vm.top_paths(days=window, limit=10),
        top_referrers=vm.top_referrers(days=window, limit=10),
        devices=vm.device_breakdown(days=window),
        browsers=vm.browser_breakdown(days=window),
        os_breakdown=vm.os_breakdown(days=window),
    )


@bp.route("/frontend/api/visitor-metrics/summary")
@admin_required
def api_visitor_metrics_summary():
    """JSON endpoint backing the dashboard widget's poll. Returns the
    same summary numbers + a compact sparkline series so the widget
    can refresh without re-rendering the whole admin index. Kept
    lightweight on purpose — heavy aggregations live behind the full
    /tspro/metrics page."""
    from . import visitor_metrics as vm
    return jsonify(
        summary=vm.summary(days=30),
        sparkline=vm.sparkline_views(days=14),
    )


