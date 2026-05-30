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
from .models import (db, User, Meeting, MeetingFile, MeetingSchedule, MeetingScheduleChange, MeetingLibrary, CustomIcon, CustomFont, CustomLayout, FrontendHeroButton,
                     Post, Story, BlogPost, BlogCategory, BlogTag,
                     ZoomAccount, ZoomOtpEmail, Location, Library, LibraryItem,
                     LibraryCategory, MediaItem, NavLink, SiteSetting,
                     IntergroupAccount, IntergroupOfficer, AccessRequest, ContactSubmission, RecoveryContact, log_recovery_contact, PasswordResetToken,
                     FrontendNavItem, UrlRedirect, EntitySlugHistory, Page,
                     FrontendNavColumn, FrontendNavLink, FILE_CATEGORIES,
                     DAYS_OF_WEEK, INTERGROUP_LIBRARY_NAMES,
                     BackupTarget, BackupRun, BACKUP_KINDS,
                     TrustedServantSubscriber, TrustedServantBlast,
                     CustomForm, FormSubmission)

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
    # The base-key field is the config_field minus the `_config_json`
    # suffix (e.g. bg_dynbg_config_json → bg_dynamic_key). Used to scope
    # per-preset knob validation. Falls back to a couple of known names.
    _preset_key = (form.get("bg_dynamic_key")
                   or form.get(config_field.replace("_dynbg_config_json", "_dynamic_key"))
                   or None)
    # Per-preset knobs arrive as one JSON blob (dot size/gap, line
    # angle/thickness, …). Parse defensively — a tampered / malformed
    # value collapses to {} and encode_config drops it.
    _knobs_raw = form.get(f"{config_field}__knobs")
    try:
        _knobs = _json.loads(_knobs_raw) if _knobs_raw else None
        if not isinstance(_knobs, dict):
            _knobs = None
    except (ValueError, TypeError):
        _knobs = None
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
        # Pastel-strength slider (0-100). 0 = off; higher values
        # increasingly soften the palette in light mode. encode_config
        # normalises the raw form value via normalize_pastel_strength
        # (also accepts legacy '1' booleans → full strength) and drops
        # the field entirely when 0 so the JSON stays minimal.
        pastel_light=form.get(f"{config_field}__pastel_light"),
        # Per-preset knobs, validated + default-dropped against the
        # active preset's spec inside encode_config.
        knobs=_knobs, preset_key=_preset_key,
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
from . import imgcache

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
    locked_accounts_count = 0
    pending_posts_count = 0
    pending_stories_count = 0
    pending_recovery_contacts_count = 0
    recovery_contacts_abuse_count = 0
    try:
        if current_user.is_authenticated and current_user.is_admin():
            pending_access_count = AccessRequest.query.filter_by(
                status="pending", is_archived=False).count()
            unread_contact_count = ContactSubmission.query.filter_by(
                is_read=False, is_archived=False).count()
            # Locked-accounts count drives the second chip on the
            # Watchtower quicknav button. One query against
            # LoginFailure aggregated by username — small table,
            # cheap to compute per-request for admin viewers only.
            try:
                from .auth import currently_locked_usernames
                locked_accounts_count = len(currently_locked_usernames())
            except Exception:
                locked_accounts_count = 0
            # Flagged Recovery Contacts update/removal requests (rate-limited
            # 2nd updates + owner-disavowed requests) drive a red attention
            # chip on the Watchtower quicknav so admins catch abuse fast.
            try:
                from . import watchtower as _wt
                recovery_contacts_abuse_count = _wt.recovery_contact_abuse_count()
            except Exception:
                recovery_contacts_abuse_count = 0
        # Pending Announcements/Events submissions chip. Shown to anyone
        # who can act on the holding tank — same gate the Posts route
        # uses to enable the "approve" action. Computed outside the
        # admin-only block so editors see the chip too.
        if (current_user.is_authenticated
                and getattr(current_user, "can_edit", lambda: False)()
                and site and getattr(site, "posts_enabled", False)):
            pending_posts_count = Post.query.filter(
                Post.is_pending_review.is_(True),
                Post.is_archived.is_(False)).count()
        # Pending Stories submissions chip. Same shape as the posts
        # chip — gated by editor role + the stories module being on.
        if (current_user.is_authenticated
                and getattr(current_user, "can_edit", lambda: False)()
                and site and getattr(site, "stories_enabled", False)):
            pending_stories_count = Story.query.filter(
                Story.is_pending_review.is_(True),
                Story.is_archived.is_(False)).count()
        # Pending Recovery Contacts entries chip. Gated by the module's own
        # admin role (who can approve entries) rather than the editor
        # gate, since the Recovery Contacts section defaults to admin-tier.
        if (current_user.is_authenticated
                and site and getattr(site, "recovery_contacts_enabled", False)):
            from .permissions import user_meets_role
            if user_meets_role(current_user,
                               getattr(site, "recovery_contacts_required_role", "admin") or "admin"):
                pending_recovery_contacts_count = RecoveryContact.query.filter_by(approved=False).count()
    except Exception:
        pending_access_count = 0
        unread_contact_count = 0
        locked_accounts_count = 0
        pending_posts_count = 0
        pending_stories_count = 0
        pending_recovery_contacts_count = 0
        recovery_contacts_abuse_count = 0
    try:
        otp = _get_otp_email()
    except Exception:
        otp = None
    # Notifications Center chip — uncleared count for the current user.
    # Read-only; derived from the same attention sources as the badges
    # above (see app/notifications.py).
    notifications_count = 0
    try:
        if current_user.is_authenticated:
            from . import notifications as _notif
            notifications_count = _notif.unread_count(current_user)
    except Exception:
        notifications_count = 0
    return {"CATEGORY_LABELS": CATEGORY_LABELS, "FILE_CATEGORIES": FILE_CATEGORIES,
            "DAYS_OF_WEEK": DAYS_OF_WEEK, "site": site, "nav_links": nav_links,
            "pending_access_count": pending_access_count,
            "unread_contact_count": unread_contact_count,
            "locked_accounts_count": locked_accounts_count,
            "pending_posts_count": pending_posts_count,
            "pending_stories_count": pending_stories_count,
            "pending_recovery_contacts_count": pending_recovery_contacts_count,
            "recovery_contacts_abuse_count": recovery_contacts_abuse_count,
            "notifications_count": notifications_count, "otp": otp}


DASHBOARD_WIDGET_KEYS = ("server-metrics", "visitor-metrics", "currently-online", "backups", "trusted-servants", "release-notes", "meetings", "libraries", "files", "access-requests", "forms", "deletions")

# Legacy widget keys that have been merged into newer widgets. The
# dashboard order loader maps these forward so a user who has the old
# key saved in ``dash_order_json`` doesn't lose their position on the
# grid when the widget gets folded in. (``contact-form`` → ``forms``
# happened when the contact-form widget was absorbed into the unified
# Forms widget that surfaces every form on the site.)
_DASHBOARD_WIDGET_ALIASES = {"contact-form": "forms"}

# Web Frontend overview tab widget keys. Same shape as the main
# dashboard — kebab-case slugs that map to ``fe_dash_show_<snake>``
# columns on User and feed the per-user draggable widget grid on
# /tspro/frontend/. Default order is the order an operator would
# scan the overview top-down: status pill, visitor numbers, then
# section shortcuts in roughly the order they appear in the FE
# subnav.
FE_DASHBOARD_WIDGET_KEYS = ("fe-status", "fe-visitor-metrics", "fe-pages",
                            "fe-redirects", "fe-navigation", "fe-forms",
                            "fe-branding", "fe-header-footer")

ONLINE_WINDOW = timedelta(minutes=5)
# Idle window — users seen between ONLINE_WINDOW and IDLE_WINDOW are
# kept in the live "Currently online" list but rendered greyed-out with
# a "no activity in Xm" label. Beyond IDLE_WINDOW they drop off
# entirely. Lets the admin keep visibility on who was recently in the
# portal without conflating them with people actively working in it
# right now.
IDLE_WINDOW = timedelta(hours=1)
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
    if endpoint == "static":
        return
    # Skip background-polled `/api/*` endpoints regardless of which
    # blueprint they live on. Without this, a public tab left open
    # pins the user's last_path to the polled URL (notably
    # `frontend.api_live_meeting`, hit every 30s by the utility bar)
    # which keeps `last_seen_at` warm forever — they show up as
    # "persistently online on /api/live-meeting" in the Currently
    # Online widget. Match by request.path so future API endpoints
    # on any blueprint inherit the skip automatically.
    if request.path.startswith("/api/"):
        return
    if endpoint.startswith("main.api_"):
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
    """Return ``(active_count, users)`` for the live widget.

    ``users`` is every account seen within IDLE_WINDOW (1 hour),
    newest-first. ``active_count`` is the subset within ONLINE_WINDOW
    (5 minutes) — what the widget header / dashboard tile reports as
    "currently online", since idle users are technically still on
    the list but visibly distinct in the UI.
    """
    now = datetime.utcnow()
    active_cutoff = now - ONLINE_WINDOW
    idle_cutoff = now - IDLE_WINDOW
    users = (User.query
             .filter(User.last_seen_at.isnot(None))
             .filter(User.last_seen_at >= idle_cutoff)
             .order_by(User.last_seen_at.desc())
             .all())
    active_count = sum(1 for u in users if u.last_seen_at >= active_cutoff)
    return active_count, users


def _dashboard_order(user):
    import json
    saved = []
    if user and user.dash_order_json:
        try:
            parsed = json.loads(user.dash_order_json)
            if isinstance(parsed, list):
                seen_aliased = set()
                for k in parsed:
                    if not isinstance(k, str):
                        continue
                    # Forward legacy widget keys to their replacement so a
                    # saved order from before a widget merge still places
                    # the new widget where the user put the old one.
                    k = _DASHBOARD_WIDGET_ALIASES.get(k, k)
                    if k in DASHBOARD_WIDGET_KEYS and k not in seen_aliased:
                        seen_aliased.add(k)
                        saved.append(k)
        except (ValueError, TypeError):
            saved = []
    seen = set(saved)
    return saved + [k for k in DASHBOARD_WIDGET_KEYS if k not in seen]


def _forms_widget_data():
    """Aggregate every form the operator might need to action into a
    single ordered list for the dashboard Forms widget.

    Each row carries the form's display name, an icon, the link to
    its admin surface, a lifetime submission count, and an
    ``attention`` count for items that haven't been actioned yet
    (unread contact messages, pending event/announcement
    submissions, pending story submissions). Built-in forms
    (Submission, Story, Contact) each have their own dedicated
    landing surface — the row deep-links to *that* surface, not the
    generic Form Submissions index, so clicking through always lands
    where the work actually happens. Custom forms keep using the
    Form Submissions index since they have no dedicated holding
    tank.

    Returns ``(rows, total_attention, total_submissions)``. The rows
    are sorted attention-first so anything needing review floats to
    the top of the widget."""
    from datetime import timedelta as _td
    s = _get_site_setting()
    rows = []
    now = datetime.utcnow()
    week_cutoff = now - _td(days=7)
    # Submission form — events / announcements holding tank. The row
    # deep-links to the Posts admin's Pending tab where the admin can
    # approve / edit / reject each submission inline.
    if s and getattr(s, "posts_enabled", False):
        pending = (Post.query
                   .filter(Post.is_pending_review.is_(True),
                           Post.is_archived.is_(False)).count())
        recent_pending = (Post.query
                          .filter(Post.is_pending_review.is_(True),
                                  Post.is_archived.is_(False),
                                  Post.submitted_at.isnot(None))
                          .order_by(Post.submitted_at.desc()).first())
        last_at = recent_pending.submitted_at if recent_pending else None
        rows.append({
            "key": "submission",
            "name": "Announcements/Events Form",
            "subtitle": "Visitor submissions",
            "icon": "send",
            "url": url_for("main.posts", show="pending"),
            "attention": pending,
            "attention_label": "pending review",
            "total": (Post.query
                      .filter(Post.is_pending_review.isnot(None))
                      .filter(Post.submitted_at.isnot(None)).count()),
            "last_at": last_at,
            "enabled": bool(getattr(s, "submission_form_enabled", True)),
        })
    # Story submission form — recovery story holding tank. Same
    # shape as the events/announcements row above but pointing at
    # the Stories admin's Pending tab. Gated on the stories module
    # being on so the row doesn't dangle a link to a disabled
    # surface.
    if s and getattr(s, "stories_enabled", False):
        pending = (Story.query
                   .filter(Story.is_pending_review.is_(True),
                           Story.is_archived.is_(False)).count())
        recent_pending = (Story.query
                          .filter(Story.is_pending_review.is_(True),
                                  Story.is_archived.is_(False),
                                  Story.submitted_at.isnot(None))
                          .order_by(Story.submitted_at.desc()).first())
        last_at = recent_pending.submitted_at if recent_pending else None
        rows.append({
            "key": "story",
            "name": "Story Submission Form",
            "subtitle": "Recovery stories",
            "icon": "book-open",
            "url": url_for("main.stories", show="pending"),
            "attention": pending,
            "attention_label": "pending review",
            "total": (Story.query
                      .filter(Story.submitted_at.isnot(None)).count()),
            "last_at": last_at,
            "enabled": bool(getattr(s, "story_form_enabled", True)),
        })
    # Contact form — always listed once SiteSetting exists, since the
    # contact page is portal-wide and not module-gated.
    if s is not None:
        unread = ContactSubmission.query.filter_by(
            is_read=False, is_archived=False).count()
        total = ContactSubmission.query.count()
        last = (ContactSubmission.query
                .order_by(ContactSubmission.created_at.desc()).first())
        rows.append({
            "key": "contact",
            "name": "Contact Form",
            "subtitle": "Visitor messages",
            "icon": "mail",
            "url": url_for("main.contact_form"),
            "attention": unread,
            "attention_label": "unread",
            "total": total,
            "last_at": last.created_at if last else None,
            "enabled": bool(getattr(s, "contact_form_enabled", True)),
        })
    # Recovery Contacts — directory entries awaiting approval. Only listed when
    # the module is enabled; attention = entries still pending review.
    if s is not None and getattr(s, "recovery_contacts_enabled", False):
        pending = RecoveryContact.query.filter_by(approved=False).count()
        total = RecoveryContact.query.count()
        last = (RecoveryContact.query
                .order_by(RecoveryContact.created_at.desc()).first())
        rows.append({
            "key": "recovery_contacts",
            "name": "Recovery Contacts",
            "subtitle": "Directory entries",
            "icon": "phone",
            "url": url_for("main.recovery_contacts"),
            "attention": pending,
            "attention_label": "pending review",
            "total": total,
            "last_at": last.created_at if last else None,
            "enabled": True,
        })
    # Every CustomForm row. New custom forms surface here automatically;
    # the link routes through the form-submissions index pre-filtered to
    # that form so the operator lands directly on its submissions.
    try:
        custom_forms = CustomForm.query.order_by(CustomForm.title).all()
    except Exception:  # noqa: BLE001
        custom_forms = []
    for cf in custom_forms:
        total = (FormSubmission.query
                 .filter_by(form_id=cf.id).count())
        # FormSubmission has no read/unread state, so "attention" for
        # custom forms means submissions in the last 7 days — a soft
        # cue that there's recent traffic the operator may not have
        # looked at yet. Lifetime total still shows alongside.
        recent = (FormSubmission.query
                  .filter(FormSubmission.form_id == cf.id,
                          FormSubmission.created_at >= week_cutoff).count())
        last = (FormSubmission.query
                .filter_by(form_id=cf.id)
                .order_by(FormSubmission.created_at.desc()).first())
        rows.append({
            "key": f"custom:{cf.id}",
            "name": cf.title or cf.slug,
            "subtitle": "Custom form",
            "icon": "file-text",
            "url": url_for("main.frontend_form_submissions", form=cf.id),
            "attention": recent,
            "attention_label": "new this week",
            "total": total,
            "last_at": last.created_at if last else None,
            "enabled": bool(cf.enabled),
        })
    total_attention = sum(r["attention"] for r in rows)
    total_submissions = sum(r["total"] for r in rows)
    # Attention-first sort with most recent activity as the tiebreaker
    # so the widget reads top-down as a to-do list.
    rows.sort(key=lambda r: (-r["attention"],
                             -(r["last_at"].timestamp() if r["last_at"] else 0),
                             r["name"].lower()))
    return rows, total_attention, total_submissions


def _fe_dashboard_order(user):
    """Per-user order of widgets on the Web Frontend overview tab.
    Same shape as ``_dashboard_order`` — saved keys (from
    ``fe_dash_order_json``) first, then any widgets the user hasn't
    explicitly placed yet (newly-added widgets, or first-visit users)
    appended in the default order so they show up rather than
    silently being hidden."""
    import json
    saved = []
    if user and user.fe_dash_order_json:
        try:
            parsed = json.loads(user.fe_dash_order_json)
            if isinstance(parsed, list):
                saved = [k for k in parsed if k in FE_DASHBOARD_WIDGET_KEYS]
        except (ValueError, TypeError):
            saved = []
    seen = set(saved)
    return saved + [k for k in FE_DASHBOARD_WIDGET_KEYS if k not in seen]


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
    online_count = 0
    online_users = []
    locked_accounts = []
    recent_deletions = []
    visitor_summary = None
    visitor_sparkline = []
    backup_summary = None
    backup_recent_runs = []
    # Trusted Servants widget state — visible to every signed-in user
    # (admin or not) until they've added themselves to the list. The
    # template hides the card entirely once a subscription row exists,
    # so the widget self-retires after the user has joined.
    site = _get_site_setting()
    trusted_servants_enabled = bool(site and getattr(site, "trusted_servants_enabled", False))
    trusted_servants_subscription = None
    if trusted_servants_enabled:
        try:
            trusted_servants_subscription = (TrustedServantSubscriber.query
                                             .filter_by(user_id=current_user.id)
                                             .first())
        except Exception:  # noqa: BLE001
            trusted_servants_subscription = None
    if current_user.is_admin():
        access_requests = (AccessRequest.query
                           .filter_by(status="pending", is_archived=False)
                           .order_by(AccessRequest.created_at.desc())
                           .limit(6).all())
        # _online_users() now returns the full idle-window list
        # (1 hour) with active_count counting just the within-5-min
        # subset. The dashboard's server-metrics tile tooltip lists
        # only the active users so the count and the names match.
        # Drop the viewing admin too — they don't need to see their
        # own name in the tooltip, and the count should reflect
        # *other* people on the portal.
        _active_count, _online_full = _online_users()
        active_cutoff = datetime.utcnow() - ONLINE_WINDOW
        online_users = [u for u in _online_full
                        if u.id != current_user.id and u.last_seen_at >= active_cutoff]
        online_count = len(online_users)
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
        # Off-site backups widget — counts targets by status, the most
        # recent successful run, and the next scheduled run so the
        # admin sees backup health at a glance. The full management
        # surface lives in the backups-modal on click.
        try:
            targets_all = BackupTarget.query.order_by(BackupTarget.created_at.desc()).all()
            ok_count = sum(1 for t in targets_all if t.last_status == "ok")
            failed_count = sum(1 for t in targets_all if t.last_status == "failed")
            never_count = sum(1 for t in targets_all if (t.last_status or "never_run") == "never_run")
            paused_count = sum(1 for t in targets_all if not t.enabled)
            enabled_targets = [t for t in targets_all if t.enabled and t.next_run_at]
            next_run = min((t.next_run_at for t in enabled_targets), default=None)
            last_ok_run = (BackupRun.query
                           .filter_by(status="ok")
                           .order_by(BackupRun.finished_at.desc())
                           .first())
            backup_summary = {
                "total": len(targets_all),
                "ok": ok_count,
                "failed": failed_count,
                "never": never_count,
                "paused": paused_count,
                "next_run_at": next_run,
                "last_ok_at": last_ok_run.finished_at if last_ok_run else None,
                "last_ok_target": last_ok_run.target.name if (last_ok_run and last_ok_run.target) else None,
            }
            backup_recent_runs = (BackupRun.query
                                  .order_by(BackupRun.started_at.desc())
                                  .limit(4).all())
        except Exception:  # noqa: BLE001
            backup_summary = None
            backup_recent_runs = []
    # Forms widget aggregates every form on the system (legacy
    # submission + contact forms plus any CustomForm rows). Admin-only:
    # the rest of the portal already gates per-form admin pages to
    # admins, so the widget mirrors that.
    forms_widget_rows = []
    forms_widget_attention = 0
    forms_widget_total = 0
    if current_user.is_admin():
        try:
            forms_widget_rows, forms_widget_attention, forms_widget_total = _forms_widget_data()
        except Exception:  # noqa: BLE001
            forms_widget_rows, forms_widget_attention, forms_widget_total = [], 0, 0
    dashboard_order = _dashboard_order(current_user)
    return render_template("index.html", meetings=meetings, libraries=libraries,
                           recent_files=recent_files, access_requests=access_requests,
                           online_count=online_count, online_users=online_users,
                           locked_accounts=locked_accounts,
                           recent_deletions=recent_deletions,
                           visitor_summary=visitor_summary,
                           visitor_sparkline=visitor_sparkline,
                           backup_summary=backup_summary,
                           backup_recent_runs=backup_recent_runs,
                           trusted_servants_enabled=trusted_servants_enabled,
                           trusted_servants_subscription=trusted_servants_subscription,
                           forms_widget_rows=forms_widget_rows,
                           forms_widget_attention=forms_widget_attention,
                           forms_widget_total=forms_widget_total,
                           dashboard_order=dashboard_order)


@bp.route("/dashboard/customize", methods=["POST"])
@login_required
def dashboard_customize():
    current_user.dash_show_stats = request.form.get("dash_show_stats") == "1"
    current_user.dash_show_meetings = request.form.get("dash_show_meetings") == "1"
    current_user.dash_show_libraries = request.form.get("dash_show_libraries") == "1"
    current_user.dash_show_files = request.form.get("dash_show_files") == "1"
    current_user.dash_show_server_metrics = request.form.get("dash_show_server_metrics") == "1"
    current_user.dash_show_trusted_servants = request.form.get("dash_show_trusted_servants") == "1"
    current_user.dash_show_release_notes = request.form.get("dash_show_release_notes") == "1"
    if current_user.is_admin():
        current_user.dash_show_access_requests = request.form.get("dash_show_access_requests") == "1"
        current_user.dash_show_forms = request.form.get("dash_show_forms") == "1"
        current_user.dash_show_deletions = request.form.get("dash_show_deletions") == "1"
        current_user.dash_show_currently_online = request.form.get("dash_show_currently_online") == "1"
        current_user.dash_show_visitor_metrics = request.form.get("dash_show_visitor_metrics") == "1"
        current_user.dash_show_backups = request.form.get("dash_show_backups") == "1"
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
    _full_count, users = _online_users()
    # Drop the viewing admin from the list — they already know they're
    # signed in, and surfacing their own row inflates the count + adds
    # noise. Recompute the active count AFTER the filter so the header
    # tally matches what's visible.
    users = [u for u in users if u.id != current_user.id]
    active_cutoff = datetime.utcnow() - ONLINE_WINDOW
    count = sum(1 for u in users if u.last_seen_at >= active_cutoff)
    return jsonify(count=count, users=[
        {"id": u.id,
         "username": u.username,
         "role": u.role,
         "last_seen_at": u.last_seen_at.isoformat() + "Z" if u.last_seen_at else None,
         "last_endpoint": u.last_endpoint or "",
         "last_path": u.last_path or "",
         "location_label": _endpoint_label(u.last_endpoint, u.last_path),
         "is_self": False,  # filtered out above; kept for client back-compat
         # is_idle = on the list (within IDLE_WINDOW) but past
         # ONLINE_WINDOW. Widget greys these out + shows
         # "no activity in Xm" instead of the active "Xs ago" stamp.
         "is_idle": u.last_seen_at < active_cutoff}
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
    "main.wp_import_fields":   "WordPress importer · Fields",
    "main.wp_import_dry_run":  "WordPress importer · Preview",
    "main.media":              "File browser",
    "main.locations":          "Meeting locations",
    "main.watchtower":         "Watchtower",
    "main.watchtower_visitors": "Watchtower · Visitors",
    "main.watchtower_access":  "Watchtower · Access",
    "main.watchtower_deletes": "Watchtower · Deletes",
    "main.watchtower_requests": "Watchtower · Requests",
    "main.watchtower_not_found": "Watchtower · 404s",
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
        if not isinstance(key, str):
            continue
        key = _DASHBOARD_WIDGET_ALIASES.get(key, key)
        if key in DASHBOARD_WIDGET_KEYS and key not in seen:
            cleaned.append(key); seen.add(key)
    current_user.dash_order_json = json.dumps(cleaned)
    db.session.commit()
    return jsonify(ok=True, order=cleaned)


# --- Notifications Center ---

@bp.route("/notifications")
@login_required
def notifications_list():
    """HTML fragment for the notifications modal body — the current
    user's uncleared notifications, newest first. Pruned on read so
    dismissals for resolved items don't linger."""
    from . import notifications as notif
    return render_template("_notifications_list.html",
                           items=notif.active(current_user, prune=True))


@bp.route("/notifications/clear", methods=["POST"])
@login_required
def notifications_clear():
    """Clear one notification by its stable key. Returns the new
    uncleared count so the sidebar chip can update live."""
    from . import notifications as notif
    payload = request.get_json(silent=True) or {}
    key = payload.get("key")
    if not key:
        return jsonify(ok=False, error="missing key"), 400
    notif.dismiss(current_user, key)
    return jsonify(ok=True, count=notif.unread_count(current_user))


@bp.route("/notifications/clear-all", methods=["POST"])
@login_required
def notifications_clear_all():
    """Clear every active notification for the current user."""
    from . import notifications as notif
    cleared = notif.dismiss_all(current_user)
    return jsonify(ok=True, cleared=cleared,
                   count=notif.unread_count(current_user))


# --- Meetings ---

@bp.route("/meetings")
@login_required
def meetings():
    _expire_meeting_alerts()
    _apply_meeting_schedule_changes()
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


def _apply_meeting_schedule_changes():
    """Idempotent sweep that activates any pending schedule swaps that
    have reached their ``effective_date``. For each matching
    ``MeetingScheduleChange`` row:

      1. Delete the parent meeting's existing ``MeetingSchedule``
         rows.
      2. Materialise new ``MeetingSchedule`` rows from
         ``schedules_json``.
      3. Delete the change row itself.

    The "effective" comparison uses the *site-local* date — same
    convention the admin types when scheduling the change — so a
    change set for "Aug 15" goes live at the start of Aug 15 in the
    fellowship's timezone regardless of where the server lives.

    Safe to call on every meeting-related request; the query is a
    cheap index lookup and exits without writes when nothing's due."""
    from .timezone import now_local_naive
    import json as _json
    today = now_local_naive(_get_site_setting()).date()
    due = (MeetingScheduleChange.query
           .filter(MeetingScheduleChange.effective_date <= today)
           .all())
    if not due:
        return
    changed = False
    for chg in due:
        m = chg.meeting
        if m is None:
            # Orphaned (parent meeting was deleted before activation).
            db.session.delete(chg)
            changed = True
            continue
        try:
            entries = _json.loads(chg.schedules_json or "[]")
        except (ValueError, TypeError):
            entries = []
        # Wipe the current schedule set and rebuild from the stored
        # change payload. Loaded as MeetingSchedule rows (not raw SQL
        # delete) so SQLAlchemy's cascade + identity-map stays
        # consistent for any code still holding references.
        for s in list(m.schedules):
            db.session.delete(s)
        for e in entries:
            if not isinstance(e, dict):
                continue
            day = e.get("day")
            start_time = (e.get("start_time") or "").strip()
            if day is None or not start_time:
                continue
            duration = e.get("duration") or 60
            opens_time = (e.get("opens_time") or None)
            zacct = e.get("zoom_account_id")
            db.session.add(MeetingSchedule(
                meeting_id=m.id,
                day_of_week=int(day),
                start_time=start_time,
                duration_minutes=int(duration),
                opens_time=opens_time,
                zoom_account_id=zacct if zacct else None,
            ))
        db.session.delete(chg)
        changed = True
    if changed:
        try:
            db.session.commit()
        except Exception:  # noqa: BLE001
            db.session.rollback()


def _expire_meeting_alerts():
    """Idempotent sweep that clears any expired public alert messages
    on Meeting rows. When ``public_alert_expires_at`` is set and has
    passed in the site's local timezone, the message AND the expiry
    are both wiped so the alert disappears from public AND admin
    views without an admin having to clean it up. Safe to call on
    every request that surfaces meeting alerts."""
    from .timezone import now_local_naive
    cutoff = now_local_naive(_get_site_setting())
    q = Meeting.query.filter(Meeting.public_alert_expires_at.isnot(None),
                             Meeting.public_alert_expires_at <= cutoff)
    changed = False
    for m in q.all():
        m.public_alert_message = None
        m.public_alert_expires_at = None
        changed = True
    if changed:
        try:
            db.session.commit()
        except Exception:  # noqa: BLE001
            db.session.rollback()


def _apply_meeting_form(m, form, schedules, files=None):
    # Capture the previous effective slug *before* mutating name/slug so
    # the history row can record the URL the public site used to serve.
    _prev_public_slug = m.public_slug if m.id else None

    m.name = form["name"].strip()
    m.description = form.get("description", "").strip()
    m.alert_message = form.get("alert_message", "").strip() or None
    m.public_alert_message = form.get("public_alert_message", "").strip() or None
    # Public-alert expiration. Only honored when the admin checks the
    # "Expires" toggle AND types a datetime; otherwise the column is
    # cleared so the alert sticks until manually edited. Blank message
    # + an expiry doesn't make sense, so wipe the expiry when the
    # message itself is gone.
    if not m.public_alert_message:
        m.public_alert_expires_at = None
    elif form.get("public_alert_expires_enabled") == "1":
        m.public_alert_expires_at = _parse_post_dt(
            form.get("public_alert_expires_at"))
    else:
        m.public_alert_expires_at = None

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


def _resolve_meeting_location(meeting, locations):
    """Match a meeting's free-text ``location`` string to a saved Location
    row and produce an "Open in Maps" URL.

    Tolerant of minor typos (e.g. "Triange Club" → "Triangle Club"): an
    exact normalized-name match wins; otherwise the closest name by
    difflib ratio above a high threshold (0.86) is accepted so a
    one-character slip still resolves while genuinely different names
    don't. Returns ``(location_record_or_None, maps_url_or_None)``."""
    import difflib
    from urllib.parse import quote_plus
    raw = (meeting.location or "").strip()
    if not raw:
        return None, None
    norm = raw.lower()
    record = next((l for l in locations if l.name and l.name.strip().lower() == norm), None)
    if record is None and locations:
        best, best_ratio = None, 0.0
        for l in locations:
            if not l.name:
                continue
            r = difflib.SequenceMatcher(None, norm, l.name.strip().lower()).ratio()
            if r > best_ratio:
                best, best_ratio = l, r
        if best_ratio >= 0.86:
            record = best
    # Maps URL: an explicit one on the record wins; otherwise build a
    # Google Maps search from the best address text available.
    if record and record.maps_url:
        maps_url = record.maps_url
    else:
        query = (" ".join([record.name or ""] + record.address_lines())
                 if record else raw).strip()
        maps_url = ("https://www.google.com/maps/search/?api=1&query=" + quote_plus(query)
                    if query else None)
    return record, maps_url


@bp.route("/meetings/<slug>")
@login_required
def meeting_detail(slug):
    _expire_meeting_alerts()
    _apply_meeting_schedule_changes()
    m = _resolve_meeting_by_slug(slug) or abort(404)
    all_libraries = Library.query.order_by(Library.name).all()
    zoom_accounts = ZoomAccount.query.order_by(ZoomAccount.name).all()
    locations = Location.query.order_by(Location.name).all()
    location_record, location_maps_url = _resolve_meeting_location(m, locations)
    zoom_password = decrypt(m.zoom_account.password_enc) if m.zoom_account else ""
    otp_email = ZoomOtpEmail.query.first()
    return render_template("meeting_detail.html", meeting=m,
                           all_libraries=all_libraries, zoom_accounts=zoom_accounts,
                           locations=locations, zoom_account_password=zoom_password,
                           location_record=location_record, location_maps_url=location_maps_url,
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


@bp.route("/meetings/<slug>/schedule-changes/new", methods=["POST"])
@editor_required
def meeting_schedule_change_new(slug):
    """Queue a future schedule swap for the named meeting.

    Reuses ``_parse_schedule_form`` so the inline form inside the
    meeting edit modal can post the same ``schedule_day`` /
    ``schedule_time`` / ``schedule_end`` / ``schedule_opens`` fields
    the main edit form uses, just prefixed with ``change_``. The
    handler stores the parsed list of entries as JSON on a
    ``MeetingScheduleChange`` row plus the effective date the admin
    typed. Until that date arrives the meeting keeps showing its
    current schedules; once reached, ``_apply_meeting_schedule_changes``
    swaps them in and deletes the change row."""
    import json as _json
    m = _resolve_meeting_by_slug(slug) or abort(404)
    effective_raw = (request.form.get("change_effective_date") or "").strip()
    try:
        eff_date = datetime.strptime(effective_raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        flash("Pick a valid effective date for the schedule change.", "danger")
        return redirect(_safe_referrer() or url_for("main.meeting_detail", slug=m.public_slug))
    # Re-map the change_* form fields into the names _parse_schedule_form
    # expects, then feed the existing parser so the new schedule is
    # validated against the same conflict / format rules the live edit
    # path runs.
    from werkzeug.datastructures import MultiDict
    sub_form = MultiDict()
    sub_form["meeting_type"] = m.meeting_type or "in_person"
    if m.zoom_account_id:
        sub_form["zoom_account_id"] = str(m.zoom_account_id)
    for k_src, k_dst in (("change_schedule_day", "schedule_day"),
                          ("change_schedule_time", "schedule_time"),
                          ("change_schedule_end", "schedule_end"),
                          ("change_schedule_opens", "schedule_opens")):
        for v in request.form.getlist(k_src):
            sub_form.add(k_dst, v)
    entries, err = _parse_schedule_form(sub_form, meeting_id=m.id)
    if err:
        flash(err, "danger")
        return redirect(_safe_referrer() or url_for("main.meeting_detail", slug=m.public_slug))
    if not entries:
        flash("Add at least one day + start time to the future schedule.", "danger")
        return redirect(_safe_referrer() or url_for("main.meeting_detail", slug=m.public_slug))
    note = (request.form.get("change_note") or "").strip()[:500] or None
    chg = MeetingScheduleChange(
        meeting_id=m.id,
        effective_date=eff_date,
        note=note,
        schedules_json=_json.dumps(entries),
        created_by=current_user.id if current_user.is_authenticated else None,
    )
    db.session.add(chg)
    db.session.commit()
    from . import activity
    activity.log("meeting.schedule_change.create",
                 entity_type="meeting", entity_id=m.id,
                 summary=f"Queued schedule change for “{m.name}” effective {eff_date.isoformat()}")
    flash(f"Schedule change saved — goes live on {eff_date.strftime('%b %-d, %Y')}.", "success")
    return redirect(_safe_referrer() or url_for("main.meeting_detail", slug=m.public_slug))


@bp.route("/meetings/<slug>/schedule-changes/<int:cid>/delete", methods=["POST"])
@editor_required
def meeting_schedule_change_delete(slug, cid):
    """Cancel a pending schedule swap before it activates."""
    m = _resolve_meeting_by_slug(slug) or abort(404)
    chg = db.session.get(MeetingScheduleChange, cid)
    if not chg or chg.meeting_id != m.id:
        abort(404)
    eff = chg.effective_date.isoformat() if chg.effective_date else "?"
    db.session.delete(chg)
    db.session.commit()
    from . import activity
    activity.log("meeting.schedule_change.delete",
                 entity_type="meeting", entity_id=m.id,
                 summary=f"Cancelled schedule change for “{m.name}” effective {eff}")
    flash("Schedule change cancelled.", "success")
    return redirect(_safe_referrer() or url_for("main.meeting_detail", slug=m.public_slug))


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
    # IMAP mailbox settings — let the guided launcher pull codes directly.
    # Guarded by a sentinel so a POST from a form that doesn't carry the
    # IMAP inputs (e.g. the legacy standalone /otp-email page) leaves the
    # stored IMAP config untouched instead of silently wiping it.
    if request.form.get("has_imap_fields") == "1":
        otp.imap_host = request.form.get("imap_host", "").strip() or None
        port_raw = request.form.get("imap_port", "").strip()
        otp.imap_port = int(port_raw) if port_raw.isdigit() else None
        otp.imap_ssl = request.form.get("imap_ssl") == "1"
        otp.imap_username = request.form.get("imap_username", "").strip() or None
        otp.imap_mailbox = request.form.get("imap_mailbox", "").strip() or None
        imap_pw = request.form.get("imap_password", "")
        if imap_pw:
            otp.imap_password_enc = encrypt(imap_pw)
        if request.form.get("clear_imap_password") == "1":
            otp.imap_password_enc = None
    db.session.commit()
    flash("OTP email settings updated", "success")
    return redirect(url_for("main.zoom_accounts",
                            **({"embed": "1"} if request.values.get("embed") == "1" else {})))


@bp.route("/otp-email/fetch-code")
@login_required
def otp_email_fetch_code():
    """Log into the OTP inbox over IMAP and return the freshest Zoom code.

    Backs the guided Zoom launcher's Step 2 "Retrieve code" button. Any
    authenticated user who can view a meeting may pull a code — the same
    audience already sees the inbox credentials on the detail page. Codes
    older than 10 minutes are never returned (see otp_fetch)."""
    from .otp_fetch import fetch_latest_code
    otp = ZoomOtpEmail.query.first()
    result = fetch_latest_code(otp, max_age_minutes=10)
    if not result.get("ok"):
        return jsonify({"ok": False, "error": result.get("error", "Could not retrieve a code.")})
    sent_at = result["sent_at"]  # aware UTC
    site = _get_site_setting()
    try:
        from .timezone import site_timezone
        local = sent_at.astimezone(site_timezone(site))
    except Exception:
        local = sent_at
    age = result["age_seconds"]
    if age < 60:
        age_label = f"{age}s ago"
    else:
        age_label = f"{age // 60} min ago"
    return jsonify({
        "ok": True,
        "code": result["code"],
        "sent_at": local.strftime("%-I:%M:%S %p"),
        "sent_date": local.strftime("%b %-d"),
        "age_label": age_label,
        "age_seconds": age,
    })


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
        "trusted_servants":  "trusted_servants_required_role",
        "recovery_contacts":        "recovery_contacts_required_role",
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


@bp.route("/settings/trusted-servants-toggle", methods=["POST"])
@admin_required
def trusted_servants_toggle():
    s = _get_site_setting()
    s.trusted_servants_enabled = request.form.get("trusted_servants_enabled") == "1"
    db.session.commit()
    flash("Trusted Servants Email List " + ("enabled" if s.trusted_servants_enabled else "disabled"), "success")
    return redirect(_safe_referrer() or url_for("main.index"))


def _require_trusted_servants_admin():
    """Gate the admin-facing Trusted Servants management surface. Module
    must be enabled AND the user must clear the admin-tunable role gate
    (defaults to ``admin``). The dashboard-widget user subscribe routes
    don't go through this — every signed-in user can submit their own
    contact info regardless of the role gate, since the gate only
    governs who can SEE the roster + send blasts."""
    from .permissions import user_meets_role
    s = _get_site_setting()
    if not s.trusted_servants_enabled:
        abort(404)
    if not user_meets_role(current_user, s.trusted_servants_required_role or "admin"):
        abort(404)


# ---------------------------------------------------------------------------
# Trusted Servants Email List — admin management surface.
# One row per signed-in user who self-subscribed via the dashboard
# widget (or who an admin added manually). Admins manage the roster
# here, send mass emails to the list, and review send history.
# ---------------------------------------------------------------------------
@bp.route("/email-list")
@login_required
def trusted_servants_list():
    _require_trusted_servants_admin()
    subs = (TrustedServantSubscriber.query
            .order_by(TrustedServantSubscriber.name.asc())
            .all())
    blasts = (TrustedServantBlast.query
              .order_by(TrustedServantBlast.started_at.desc())
              .limit(25).all())
    return render_template("trusted_servants_list.html",
                           subscribers=subs, blasts=blasts)


@bp.route("/email-list/<int:sid>/delete", methods=["POST"])
@login_required
def trusted_servants_delete(sid):
    _require_trusted_servants_admin()
    sub = db.session.get(TrustedServantSubscriber, sid) or abort(404)
    name = sub.name
    db.session.delete(sub)
    db.session.commit()
    flash(f"Removed {name} from the Trusted Servants list.", "info")
    return redirect(url_for("main.trusted_servants_list"))


# ---------------------------------------------------------------------------
# Recovery Contacts — admin management surface.
# Public visitors submit name + phone/email via /contactlist; rows arrive
# unapproved and stay hidden from the public directory until an admin
# approves them here. Each approved row has per-field display toggles so
# the admin controls whether the phone, the email, or both are shown.
# ---------------------------------------------------------------------------
@bp.route("/settings/recovery-contacts-toggle", methods=["POST"])
@admin_required
def recovery_contacts_toggle():
    s = _get_site_setting()
    s.recovery_contacts_enabled = request.form.get("recovery_contacts_enabled") == "1"
    db.session.commit()
    flash("Recovery Contacts " + ("enabled" if s.recovery_contacts_enabled else "disabled"), "success")
    return redirect(_safe_referrer() or url_for("main.index"))


def _require_recovery_contacts_admin():
    """Gate the Recovery Contacts admin surface. Module must be enabled AND the
    user must clear the admin-tunable role gate (defaults to ``admin``).
    The public /contactlist submit route doesn't go through this — any
    visitor can submit an entry; this gate only governs who can review,
    approve, and remove entries."""
    from .permissions import user_meets_role
    s = _get_site_setting()
    if not getattr(s, "recovery_contacts_enabled", False):
        abort(404)
    if not user_meets_role(current_user, getattr(s, "recovery_contacts_required_role", "admin") or "admin"):
        abort(404)


@bp.route("/recovery-contacts")
@login_required
def recovery_contacts():
    _require_recovery_contacts_admin()
    from .models import RecoveryContactLog, RecoveryContactAbuse
    s = _get_site_setting()
    pending = (RecoveryContact.query.filter_by(approved=False)
               .order_by(RecoveryContact.created_at.desc()).all())
    approved = (RecoveryContact.query.filter_by(approved=True)
                .order_by(RecoveryContact.name.asc()).all())
    logs = (RecoveryContactLog.query
            .order_by(RecoveryContactLog.created_at.desc(), RecoveryContactLog.id.desc())
            .limit(60).all())
    # Per-listing abuse flags (unresolved) so the published table can mark
    # records that drew malicious update/removal requests. Maps entry_id →
    # {"kinds": set, "count": n} — the listing's own lock state is read off
    # the row's ``requests_locked_until``.
    abuse_by_entry = {}
    try:
        for a in (RecoveryContactAbuse.query
                  .filter(RecoveryContactAbuse.resolved.is_(False),
                          RecoveryContactAbuse.entry_id.isnot(None)).all()):
            slot = abuse_by_entry.setdefault(a.entry_id, {"kinds": set(), "count": 0})
            slot["kinds"].add(a.kind)
            slot["count"] += int(a.attempt_count or 1)
    except Exception:  # noqa: BLE001
        abuse_by_entry = {}
    return render_template("recovery_contacts.html", site=s,
                           pending=pending, approved=approved, logs=logs,
                           abuse_by_entry=abuse_by_entry, now=datetime.utcnow())


@bp.route("/recovery-contacts/add", methods=["POST"])
@login_required
def recovery_contacts_manual_add():
    """Admin-entered Recovery Contacts entry. Unlike public submissions, a
    manually-added entry is published immediately (approved=True) — the
    admin is entering trusted info directly, so there's no review step.
    Requires a name plus at least one contact method."""
    _require_recovery_contacts_admin()
    name = (request.form.get("name") or "").strip()[:200]
    email = (request.form.get("email") or "").strip()[:255] or None
    phone = (request.form.get("phone") or "").strip()[:64] or None
    if not name:
        flash("A name is required.", "danger")
        return redirect(url_for("main.recovery_contacts"))
    if not email and not phone:
        flash("Add a phone number, an email, or both.", "danger")
        return redirect(url_for("main.recovery_contacts"))
    e = RecoveryContact(
        name=name, email=email, phone=phone,
        show_phone=request.form.get("show_phone") == "1",
        show_email=request.form.get("show_email") == "1",
        available_to_sponsor=request.form.get("available_to_sponsor") == "1",
        contact_enabled=request.form.get("contact_enabled") == "1",
        note=(request.form.get("note") or "").strip() or None,
        approved=True, approved_at=datetime.utcnow(),
    )
    db.session.add(e)
    db.session.commit()
    log_recovery_contact("manual_add", "Added manually by admin",
                         entry_name=name, actor=f"admin: {current_user.username}")
    flash(f"Added {name} to Recovery Contacts.", "success")
    return redirect(url_for("main.recovery_contacts"))


@bp.route("/recovery-contacts/<int:eid>/approve", methods=["POST"])
@login_required
def recovery_contacts_approve(eid):
    _require_recovery_contacts_admin()
    e = db.session.get(RecoveryContact, eid) or abort(404)
    e.approved = True
    e.approved_at = datetime.utcnow()
    db.session.commit()
    log_recovery_contact("approved", "Approved and published by admin",
                         entry_name=e.name, actor=f"admin: {current_user.username}")
    flash(f"Approved {e.name} — now visible on the public Recovery Contacts page.", "success")
    return redirect(url_for("main.recovery_contacts"))


@bp.route("/recovery-contacts/<int:eid>/apply-update", methods=["POST"])
@login_required
def recovery_contacts_apply_update(eid):
    """Apply a pending 'update my entry' submission onto the existing
    entry it matched: overwrite the existing (approved) row's fields with
    the submitted values, keep it published, and delete the submission.
    No-op with a warning when the submission isn't matched to anything."""
    _require_recovery_contacts_admin()
    sub = db.session.get(RecoveryContact, eid) or abort(404)
    target = sub.matched_entry
    if target is None:
        flash("That submission isn't matched to an existing entry — approve it as a new entry instead.", "danger")
        return redirect(url_for("main.recovery_contacts"))
    target.name = sub.name
    target.phone = sub.phone
    target.email = sub.email
    target.show_phone = sub.show_phone
    target.show_email = sub.show_email
    target.available_to_sponsor = sub.available_to_sponsor
    target.contact_enabled = sub.contact_enabled
    target.approved = True
    target.approved_at = datetime.utcnow()
    db.session.delete(sub)
    db.session.commit()
    log_recovery_contact("update_applied", "Update applied to the listing by admin",
                         entry_name=target.name, actor=f"admin: {current_user.username}")
    flash(f"Updated {target.name} from the submission.", "success")
    return redirect(url_for("main.recovery_contacts"))


@bp.route("/recovery-contacts/<int:eid>/apply-removal", methods=["POST"])
@login_required
def recovery_contacts_apply_removal(eid):
    """Action a pending 'Remove me from the list' request: delete the
    matched (published) entry and the request row. If the request never
    matched an entry, this just clears the request."""
    _require_recovery_contacts_admin()
    sub = db.session.get(RecoveryContact, eid) or abort(404)
    sub_name = sub.name
    target = sub.matched_entry
    db.session.delete(sub)
    if target is not None:
        name = target.name
        # Clear any other requests pointing at this entry so nothing dangles.
        RecoveryContact.query.filter_by(matched_entry_id=target.id).update(
            {"matched_entry_id": None})
        db.session.delete(target)
        db.session.commit()
        log_recovery_contact("removal_applied", "Removed from the list by admin (removal request)",
                             entry_name=name, actor=f"admin: {current_user.username}")
        flash(f"Removed {name} from the list per their request.", "success")
    else:
        db.session.commit()
        log_recovery_contact("dismissed", "Removal request dismissed by admin (no matching entry)",
                             entry_name=sub_name, actor=f"admin: {current_user.username}")
        flash("Dismissed the removal request — no matching entry was found.", "info")
    return redirect(url_for("main.recovery_contacts"))


@bp.route("/recovery-contacts/<int:eid>/unapprove", methods=["POST"])
@login_required
def recovery_contacts_unapprove(eid):
    _require_recovery_contacts_admin()
    e = db.session.get(RecoveryContact, eid) or abort(404)
    e.approved = False
    e.approved_at = None
    db.session.commit()
    log_recovery_contact("unapproved", "Moved back to pending by admin",
                         entry_name=e.name, actor=f"admin: {current_user.username}")
    flash(f"Moved {e.name} back to pending review.", "info")
    return redirect(url_for("main.recovery_contacts"))


@bp.route("/recovery-contacts/<int:eid>/visibility", methods=["POST"])
@login_required
def recovery_contacts_visibility(eid):
    """One-click per-field display toggle from the admin list. ``field``
    (in the URL) is 'phone' or 'email'; the checkbox submits value=1 when
    on and nothing when off, so an absent value reads as hidden."""
    _require_recovery_contacts_admin()
    e = db.session.get(RecoveryContact, eid) or abort(404)
    field = (request.form.get("field") or "").strip()
    on = request.form.get("value") == "1"
    if field == "phone":
        e.show_phone = on
    elif field == "email":
        e.show_email = on
    db.session.commit()
    if field in ("phone", "email"):
        log_recovery_contact("visibility",
                             f"Set {field} {'shown' if on else 'hidden'} by admin",
                             entry_name=e.name, actor=f"admin: {current_user.username}")
    return redirect(url_for("main.recovery_contacts"))


@bp.route("/recovery-contacts/<int:eid>/update", methods=["POST"])
@login_required
def recovery_contacts_update(eid):
    _require_recovery_contacts_admin()
    e = db.session.get(RecoveryContact, eid) or abort(404)
    name = (request.form.get("name") or "").strip()[:200]
    if name:
        e.name = name
    e.email = (request.form.get("email") or "").strip()[:255] or None
    e.phone = (request.form.get("phone") or "").strip()[:64] or None
    e.show_phone = request.form.get("show_phone") == "1"
    e.show_email = request.form.get("show_email") == "1"
    e.available_to_sponsor = request.form.get("available_to_sponsor") == "1"
    e.contact_enabled = request.form.get("contact_enabled") == "1"
    e.note = (request.form.get("note") or "").strip() or None
    db.session.commit()
    log_recovery_contact("edited", "Edited by admin",
                         entry_name=e.name, actor=f"admin: {current_user.username}")
    flash(f"Updated {e.name}.", "success")
    return redirect(url_for("main.recovery_contacts"))


@bp.route("/recovery-contacts/<int:eid>/delete", methods=["POST"])
@login_required
def recovery_contacts_delete(eid):
    _require_recovery_contacts_admin()
    e = db.session.get(RecoveryContact, eid) or abort(404)
    name = e.name
    # Clear any pending update-submissions that pointed at this entry so
    # they don't dangle (SQLite doesn't enforce the ON DELETE SET NULL).
    RecoveryContact.query.filter_by(matched_entry_id=e.id).update(
        {"matched_entry_id": None})
    db.session.delete(e)
    db.session.commit()
    log_recovery_contact("deleted", "Deleted by admin",
                         entry_name=name, actor=f"admin: {current_user.username}")
    flash(f"Removed {name} from Recovery Contacts.", "info")
    return redirect(url_for("main.recovery_contacts"))


@bp.route("/email-list/blast")
@login_required
def trusted_servants_blast_compose():
    _require_trusted_servants_admin()
    # The subscriber rows themselves are listed (not just counted) so
    # the compose page can render a checkbox list under the "Pick which"
    # subscribers granular mode — same shape as MeetingLibrary's per-
    # reading selection. Intergroup-members + app-users stay as bare
    # counts (their granular controls are a follow-up if asked for).
    subscribers = (TrustedServantSubscriber.query
                   .order_by(TrustedServantSubscriber.name.asc()).all())
    ig_count = User.query.filter(User.role == "intergroup_member").count()
    app_count = User.query.filter(
        User.role.notin_(("admin", "intergroup_member"))
    ).count()
    return render_template("trusted_servants_blast.html",
                           subscribers=subscribers,
                           subscriber_count=len(subscribers),
                           intergroup_count=ig_count,
                           app_user_count=app_count)


@bp.route("/email-list/blast", methods=["POST"])
@login_required
def trusted_servants_blast_send():
    """Send a one-message-per-recipient blast.

    Three potential audience groups, controlled by the compose page's
    mode + per-group toggles (same shape as MeetingLibrary's
    ``all`` / ``granular`` mode):

      • **Full list mode** (``audience_mode=all``) — fans out to every
        subscriber + every intergroup member + every non-admin app user.
      • **Granular mode** (``audience_mode=granular``) — only includes
        the groups whose toggle is checked. Subscribers default on; the
        other two default off so an admin who explicitly picks granular
        but forgets to tick anything still gets the historical "send
        to subscribers" behaviour.

    The combined recipient list is deduped by lowercased email so a
    single person who appears in two groups (e.g. on the list AND has
    an intergroup-member account) only gets one copy. Synchronous SMTP
    loop, one message per recipient — failures don't abort the loop;
    each is tried independently and counted into the BlastRun row.
    """
    from datetime import datetime as _dt
    import markdown as _md_lib
    from .mail import send_mail
    _require_trusted_servants_admin()
    s = _get_site_setting()
    subject = (request.form.get("subject") or "").strip()
    body_md = (request.form.get("body") or "").strip()
    if not subject:
        flash("Subject is required.", "danger")
        return redirect(url_for("main.trusted_servants_blast_compose"))
    if not body_md:
        flash("Message body is required.", "danger")
        return redirect(url_for("main.trusted_servants_blast_compose"))

    mode = (request.form.get("audience_mode") or "granular").strip().lower()
    if mode not in ("all", "granular"):
        mode = "granular"
    if mode == "all":
        include_subs = include_ig = include_app = True
        subs_mode = "all"
    else:
        include_subs = request.form.get("include_subscribers") == "1"
        include_ig = request.form.get("include_intergroup") == "1"
        include_app = request.form.get("include_app_users") == "1"
        # Within the subscribers group, the admin can further pick a
        # specific subset via the "Pick which subscribers" radio — same
        # all/granular shape MeetingLibrary uses per-meeting. Granular
        # mode reads the checkbox list of ``subscriber_ids`` and only
        # sends to those rows.
        subs_mode = (request.form.get("subscribers_mode") or "all").strip().lower()
        if subs_mode not in ("all", "granular"):
            subs_mode = "all"

    # Granular subscriber-id whitelist. ``request.form.getlist`` returns
    # every checked value of the same name; we coerce to ints and drop
    # anything malformed so a tampered POST can only pick known rows.
    selected_sub_ids = set()
    if include_subs and subs_mode == "granular":
        for raw in request.form.getlist("subscriber_ids"):
            try:
                selected_sub_ids.add(int(raw))
            except (TypeError, ValueError):
                continue

    # Build the combined recipient list. Tuple shape (name_for_token,
    # email) so the {name} personalization works uniformly for every
    # group regardless of which row supplied it.
    recipients = []
    seen = set()

    def _add(name, email):
        if not email:
            return
        key = email.strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        recipients.append((name or email, email))

    if include_subs:
        q = TrustedServantSubscriber.query.order_by(TrustedServantSubscriber.name.asc())
        if subs_mode == "granular":
            if not selected_sub_ids:
                # The admin picked granular but didn't tick anyone —
                # surface the error rather than silently sending zero
                # from the subscribers group.
                flash(
                    "Pick at least one subscriber, or switch the subscribers "
                    "mode to All before sending.",
                    "danger")
                return redirect(url_for("main.trusted_servants_blast_compose"))
            q = q.filter(TrustedServantSubscriber.id.in_(selected_sub_ids))
        for sub in q.all():
            _add(sub.name, sub.email)
    if include_ig:
        for u in (User.query.filter(User.role == "intergroup_member")
                  .order_by(User.username.asc()).all()):
            _add(u.name or u.username, u.email)
    if include_app:
        for u in (User.query
                  .filter(User.role.notin_(("admin", "intergroup_member")))
                  .order_by(User.username.asc()).all()):
            _add(u.name or u.username, u.email)

    if not recipients:
        flash(
            "No one is in the audience you picked — turn on at least one group "
            "(or pick Full list) before sending.",
            "danger")
        return redirect(url_for("main.trusted_servants_blast_compose"))

    blast = TrustedServantBlast(
        sent_by_user_id=current_user.id,
        subject=subject[:500],
        body_md=body_md,
        recipient_count=len(recipients),
        started_at=_dt.utcnow(),
    )
    db.session.add(blast)
    db.session.commit()

    sent = 0
    failed = 0
    body_html = _md_lib.markdown(body_md, extensions=["extra", "nl2br"])
    for name, email in recipients:
        # Personalize the first-line greeting if the body opens with a
        # `{name}` token. Admins who don't use the token just get an
        # un-replaced body — opt-in personalization, no surprises.
        text_body = body_md.replace("{name}", name)
        html_body = body_html.replace("{name}", name)
        try:
            ok, _err = send_mail(s, email, subject, text_body, body_html=html_body)
            if ok:
                sent += 1
            else:
                failed += 1
        except Exception:  # noqa: BLE001
            current_app.logger.exception(
                "trusted_servants_blast: send to %s failed", email)
            failed += 1

    blast.sent_count = sent
    blast.failed_count = failed
    blast.finished_at = _dt.utcnow()
    db.session.commit()

    if sent and not failed:
        flash(f"Sent the update to {sent} subscriber{'s' if sent != 1 else ''}.", "success")
    elif sent and failed:
        flash(f"Sent to {sent} of {sent + failed}. {failed} failed — check the server log.", "warning")
    else:
        flash(f"All {failed} sends failed. Check SMTP settings on the Domain / Email tab.", "danger")
    return redirect(url_for("main.trusted_servants_list"))


# ---------------------------------------------------------------------------
# Trusted Servants Email List — self-service routes called from the
# dashboard widget. Authenticated users only; no role gate (the
# required-role setting only governs the admin side).
# ---------------------------------------------------------------------------
@bp.route("/email-list/subscribe", methods=["POST"])
@login_required
def trusted_servants_subscribe():
    """Upsert the current user's subscription. Hit by the dashboard
    widget's form; creates a new row if the user hasn't subscribed yet,
    updates the existing row otherwise (one subscription per user is
    enforced by the unique constraint on ``user_id``).
    """
    s = _get_site_setting()
    if not s.trusted_servants_enabled:
        abort(404)
    name = (request.form.get("name") or "").strip()[:120]
    phone = (request.form.get("phone") or "").strip()[:64]
    email = (request.form.get("email") or "").strip()[:255]
    if not name:
        flash("Your name is required to join the list.", "danger")
        return redirect(_safe_referrer() or url_for("main.index"))
    if not email:
        flash("An email address is required to join the list.", "danger")
        return redirect(_safe_referrer() or url_for("main.index"))

    sub = TrustedServantSubscriber.query.filter_by(user_id=current_user.id).first()
    if sub is None:
        sub = TrustedServantSubscriber(user_id=current_user.id)
        db.session.add(sub)
        action = "joined"
    else:
        action = "updated"
    sub.name = name
    sub.phone = phone or None
    sub.email = email
    db.session.commit()
    flash("You've " + ("joined" if action == "joined" else "updated your details on")
          + " the Trusted Servants Email List.", "success")
    return redirect(_safe_referrer() or url_for("main.index"))


@bp.route("/email-list/unsubscribe", methods=["POST"])
@login_required
def trusted_servants_unsubscribe():
    """Remove the current user from the list. The admin keeps no
    archived copy — once the user clicks unsubscribe, the row is gone."""
    sub = TrustedServantSubscriber.query.filter_by(user_id=current_user.id).first()
    if sub is not None:
        db.session.delete(sub)
        db.session.commit()
    flash("You've been removed from the Trusted Servants Email List.", "info")
    return redirect(_safe_referrer() or url_for("main.index"))


@bp.route("/email-list/manual-add", methods=["POST"])
@login_required
def trusted_servants_manual_add():
    """Admin-only path that adds an external contact to the list.

    Unlike the self-subscribe route, the row created here has
    ``user_id = NULL`` — the entry isn't tied to any portal account
    and the only way to edit / remove it is via this admin surface.
    Used for trusted servants who don't have (or don't want) a portal
    login but still belong on the contact roster.
    """
    _require_trusted_servants_admin()
    name = (request.form.get("name") or "").strip()[:120]
    phone = (request.form.get("phone") or "").strip()[:64]
    email = (request.form.get("email") or "").strip()[:255]
    notes = (request.form.get("notes") or "").strip() or None
    if not name:
        flash("Name is required.", "danger")
        return redirect(url_for("main.trusted_servants_list"))
    if not email:
        flash("Email is required.", "danger")
        return redirect(url_for("main.trusted_servants_list"))
    sub = TrustedServantSubscriber(
        user_id=None,
        name=name,
        phone=phone or None,
        email=email,
        notes=notes,
    )
    db.session.add(sub)
    db.session.commit()
    flash(f"Added {name} to the email list.", "success")
    return redirect(url_for("main.trusted_servants_list"))


_TS_IMPORT_MAX_ROWS = 5000
_TS_IMPORT_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _ts_import_stash_dir():
    """Per-install temp folder for half-finished CSV imports. Mirrors
    the wp_importer.stash pattern: a small JSON file per token, purged
    after 24h."""
    upload = current_app.config["UPLOAD_FOLDER"].rstrip("/")
    data_dir = os.path.dirname(upload)
    path = os.path.join(data_dir, "ts_import")
    os.makedirs(path, exist_ok=True)
    return path


def _ts_import_stash_save(token, payload):
    p = os.path.join(_ts_import_stash_dir(), f"{token}.json")
    with open(p, "w") as f:
        json.dump(payload, f)


def _ts_import_stash_load(token):
    if not token or not _TS_IMPORT_TOKEN_RE.match(token):
        return None
    p = os.path.join(_ts_import_stash_dir(), f"{token}.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except (ValueError, OSError):
        return None


def _ts_import_stash_delete(token):
    if not token or not _TS_IMPORT_TOKEN_RE.match(token):
        return
    p = os.path.join(_ts_import_stash_dir(), f"{token}.json")
    if os.path.isfile(p):
        try:
            os.unlink(p)
        except OSError:
            pass


def _ts_import_stash_purge_old(max_age_seconds=86400):
    """Drop stash files older than 24h. Called opportunistically when
    the import modal POSTs, so abandoned imports don't accumulate."""
    d = _ts_import_stash_dir()
    cutoff = time.time() - max_age_seconds
    try:
        for name in os.listdir(d):
            if not name.endswith(".json"):
                continue
            full = os.path.join(d, name)
            try:
                if os.path.getmtime(full) < cutoff:
                    os.unlink(full)
            except OSError:
                pass
    except OSError:
        pass


def _ts_norm_header(h):
    """Header → lowercase-no-punct slug for fuzzy matching."""
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


_TS_NAME_ALIASES = {"name", "fullname", "displayname", "contactname", "subscribername"}
_TS_FIRST_ALIASES = {"firstname", "givenname", "first"}
_TS_LAST_ALIASES = {"lastname", "surname", "familyname", "last"}
_TS_EMAIL_ALIASES = {"email", "emailaddress", "mail", "mailaddress", "contactemail", "emailid"}
_TS_PHONE_ALIASES = {"phone", "phonenumber", "mobile", "mobilenumber", "cell", "cellnumber",
                     "tel", "telephone", "contactphone", "phonenum"}


def _ts_auto_map(headers):
    """Build the auto-detected column mapping for a list of headers.

    Returns a dict with keys ``name``, ``first``, ``last``, ``email``,
    ``phone``; values are column indices (int) or None when no header
    in the CSV looks like that field. The admin can override any of
    these on the preview page before committing.
    """
    out = {"name": None, "first": None, "last": None, "email": None, "phone": None}
    for idx, h in enumerate(headers):
        key = _ts_norm_header(h)
        if out["name"] is None and key in _TS_NAME_ALIASES:
            out["name"] = idx
        elif out["first"] is None and key in _TS_FIRST_ALIASES:
            out["first"] = idx
        elif out["last"] is None and key in _TS_LAST_ALIASES:
            out["last"] = idx
        elif out["email"] is None and key in _TS_EMAIL_ALIASES:
            out["email"] = idx
        elif out["phone"] is None and key in _TS_PHONE_ALIASES:
            out["phone"] = idx
    return out


def _ts_apply_mapping(rows, mapping, existing_emails):
    """Walk the parsed CSV rows under ``mapping`` and split them into
    actionable buckets. Returns a dict with the same shape for both
    preview and confirm:

        {"valid": [(name, email, phone), …],
         "skipped_blank": int,
         "skipped_missing": int,
         "skipped_duplicate": int}

    Email duplicates are detected against ``existing_emails`` (set of
    lowercased addresses already in the DB) and against earlier rows
    in the same CSV.
    """
    valid = []
    skipped_blank = 0
    skipped_missing = 0
    skipped_duplicate = 0
    seen_in_csv = set()
    name_col = mapping.get("name")
    first_col = mapping.get("first")
    last_col = mapping.get("last")
    email_col = mapping.get("email")
    phone_col = mapping.get("phone")
    if email_col is None:
        return {"valid": [], "skipped_blank": 0, "skipped_missing": len(rows),
                "skipped_duplicate": 0}

    def cell(row, idx):
        return (row[idx].strip() if idx is not None and 0 <= idx < len(row) else "")

    for row in rows:
        if not row or not any((c or "").strip() for c in row):
            skipped_blank += 1
            continue
        if name_col is not None:
            name = cell(row, name_col)
        else:
            parts = [p for p in (cell(row, first_col), cell(row, last_col)) if p]
            name = " ".join(parts)
        email = cell(row, email_col)
        phone = cell(row, phone_col)
        if not name or not email:
            skipped_missing += 1
            continue
        if "@" not in email or "." not in email.split("@", 1)[1]:
            skipped_missing += 1
            continue
        el = email.lower()
        if el in existing_emails or el in seen_in_csv:
            skipped_duplicate += 1
            continue
        seen_in_csv.add(el)
        valid.append((name[:120], email[:255], (phone[:64] or None)))
    return {"valid": valid, "skipped_blank": skipped_blank,
            "skipped_missing": skipped_missing,
            "skipped_duplicate": skipped_duplicate}


def _ts_import_embed():
    """True when the import wizard is being rendered inside the modal
    iframe (?embed=1 or embed=1 in the POST body). Each wizard step
    threads this through every redirect / form-action / postMessage
    so the modal stays open from upload all the way through done."""
    return (request.args.get("embed") == "1"
            or request.form.get("embed") == "1")


def _ts_import_embed_kwargs():
    """Spread into url_for(...) to preserve embed mode."""
    return {"embed": 1} if _ts_import_embed() else {}


@bp.route("/email-list/import", methods=["GET"])
@login_required
def trusted_servants_import_start():
    """Step 1 — render the upload form. Always rendered inside the
    iframe modal in embed mode; the non-embed path falls back to the
    plain list page in case someone hits the URL directly."""
    _require_trusted_servants_admin()
    embed = _ts_import_embed()
    if not embed:
        return redirect(url_for("main.trusted_servants_list"))
    return render_template("trusted_servants_import_start.html",
                           embed=embed,
                           active_step=1)


@bp.route("/email-list/import", methods=["POST"])
@login_required
def trusted_servants_import():
    """Step 1 POST — parse the upload, stash the rows, and redirect
    to the preview step where the admin reviews the auto-detected
    column mapping + a sample of what would be imported. Nothing is
    written to the subscriber table on this step."""
    import csv as _csv
    import io as _io
    import secrets as _secrets
    _require_trusted_servants_admin()
    _ts_import_stash_purge_old()
    embed = _ts_import_embed()
    def _bail(msg):
        flash(msg, "danger")
        if embed:
            return redirect(url_for("main.trusted_servants_import_start", embed=1))
        return redirect(url_for("main.trusted_servants_list"))

    upload = request.files.get("csv")
    if not upload or not upload.filename:
        return _bail("Choose a CSV file to import.")

    raw = upload.read()
    if not raw:
        return _bail("The CSV file is empty.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="replace")

    sample = text[:4096]
    try:
        dialect = _csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except _csv.Error:
        class _Default(_csv.excel):
            delimiter = ","
        dialect = _Default

    reader = _csv.reader(_io.StringIO(text), dialect=dialect)
    all_rows = list(reader)
    if not all_rows:
        return _bail("The CSV file is empty.")
    headers = [h.strip() for h in all_rows[0]]
    data_rows = all_rows[1:_TS_IMPORT_MAX_ROWS + 1]
    truncated = len(all_rows[1:]) > _TS_IMPORT_MAX_ROWS

    token = _secrets.token_urlsafe(18)
    _ts_import_stash_save(token, {
        "filename": upload.filename,
        "headers": headers,
        "rows": data_rows,
        "truncated": truncated,
    })
    return redirect(url_for("main.trusted_servants_import_preview",
                            token=token, **_ts_import_embed_kwargs()))


@bp.route("/email-list/import/preview")
@login_required
def trusted_servants_import_preview():
    """Step 2 of the CSV import — render the dry-run preview. Shows
    the auto-detected (or admin-overridden) column mapping, the count
    of valid / skipped rows that mapping would produce, and the first
    handful of valid rows so the admin can sanity-check before
    committing.
    """
    _require_trusted_servants_admin()
    embed = _ts_import_embed()
    token = (request.args.get("token") or "").strip()
    stash = _ts_import_stash_load(token)
    if stash is None:
        flash("Import session expired — re-upload the CSV.", "danger")
        if embed:
            return redirect(url_for("main.trusted_servants_import_start", embed=1))
        return redirect(url_for("main.trusted_servants_list"))

    headers = stash.get("headers") or []
    rows = stash.get("rows") or []

    # Form-driven mapping overrides win over auto-detection. Treat
    # an empty / non-integer value as "(none)" so the admin can drop a
    # column the auto-detector picked.
    def _col_param(key):
        raw = request.args.get(key)
        if raw is None or raw == "" or raw == "-1":
            return None
        try:
            v = int(raw)
        except ValueError:
            return None
        if 0 <= v < len(headers):
            return v
        return None

    auto = _ts_auto_map(headers)
    has_override = any(request.args.get(k) is not None
                       for k in ("name_col", "first_col", "last_col", "email_col", "phone_col"))
    if has_override:
        mapping = {
            "name":  _col_param("name_col"),
            "first": _col_param("first_col"),
            "last":  _col_param("last_col"),
            "email": _col_param("email_col"),
            "phone": _col_param("phone_col"),
        }
    else:
        mapping = auto

    existing = {(e or "").strip().lower()
                for (e,) in db.session.query(TrustedServantSubscriber.email).all()}
    result = _ts_apply_mapping(rows, mapping, existing)

    return render_template("trusted_servants_import_preview.html",
                           token=token,
                           filename=stash.get("filename") or "uploaded.csv",
                           headers=headers,
                           mapping=mapping,
                           auto=auto,
                           total_rows=len(rows),
                           valid=result["valid"],
                           skipped_blank=result["skipped_blank"],
                           skipped_missing=result["skipped_missing"],
                           skipped_duplicate=result["skipped_duplicate"],
                           truncated=stash.get("truncated", False),
                           embed=embed,
                           active_step=2)


@bp.route("/email-list/import/confirm", methods=["POST"])
@login_required
def trusted_servants_import_confirm():
    """Step 3 — commit the rows the preview showed. The admin's chosen
    mapping comes back as form data; we re-apply it to the stashed
    rows server-side (never trust the preview's row list — recomputing
    is the only way to be sure the user's mapping change actually
    matches what we're about to write)."""
    _require_trusted_servants_admin()
    embed = _ts_import_embed()
    token = (request.form.get("token") or "").strip()
    stash = _ts_import_stash_load(token)
    if stash is None:
        flash("Import session expired — re-upload the CSV.", "danger")
        if embed:
            return redirect(url_for("main.trusted_servants_import_start", embed=1))
        return redirect(url_for("main.trusted_servants_list"))

    def _col_form(key):
        raw = request.form.get(key)
        if raw is None or raw == "" or raw == "-1":
            return None
        try:
            v = int(raw)
        except ValueError:
            return None
        return v if 0 <= v < len(stash.get("headers") or []) else None

    mapping = {
        "name":  _col_form("name_col"),
        "first": _col_form("first_col"),
        "last":  _col_form("last_col"),
        "email": _col_form("email_col"),
        "phone": _col_form("phone_col"),
    }
    if mapping["email"] is None:
        flash("Pick an email column before importing.", "danger")
        return redirect(url_for("main.trusted_servants_import_preview",
                                token=token, **_ts_import_embed_kwargs()))
    if mapping["name"] is None and mapping["first"] is None and mapping["last"] is None:
        flash("Pick a name column (or a First Name + Last Name pair) before importing.", "danger")
        return redirect(url_for("main.trusted_servants_import_preview",
                                token=token, **_ts_import_embed_kwargs()))

    existing = {(e or "").strip().lower()
                for (e,) in db.session.query(TrustedServantSubscriber.email).all()}
    result = _ts_apply_mapping(stash.get("rows") or [], mapping, existing)

    for (name, email, phone) in result["valid"]:
        db.session.add(TrustedServantSubscriber(
            user_id=None,
            name=name,
            email=email,
            phone=phone,
        ))
    db.session.commit()
    _ts_import_stash_delete(token)

    added = len(result["valid"])
    if embed:
        # Wizard finale — render the done template inside the iframe so
        # the modal can show "X added" and postMessage the parent to
        # close + reload. No redirect: the parent (the list page) is
        # the one that reloads, not the iframe.
        return render_template("trusted_servants_import_done.html",
                               embed=True,
                               active_step=3,
                               outcome="ok",
                               added=added,
                               skipped_duplicate=result["skipped_duplicate"],
                               skipped_missing=result["skipped_missing"],
                               skipped_blank=result["skipped_blank"])
    bits = [f"Imported {added}"]
    if result["skipped_duplicate"]:
        bits.append(f"skipped {result['skipped_duplicate']} duplicate{'s' if result['skipped_duplicate'] != 1 else ''}")
    if result["skipped_missing"]:
        bits.append(f"skipped {result['skipped_missing']} row{'s' if result['skipped_missing'] != 1 else ''} missing name or email")
    if result["skipped_blank"]:
        bits.append(f"skipped {result['skipped_blank']} blank row{'s' if result['skipped_blank'] != 1 else ''}")
    flash(" — ".join(bits) + ".", "success" if added else "info")
    return redirect(url_for("main.trusted_servants_list"))


@bp.route("/email-list/import/cancel", methods=["POST"])
@login_required
def trusted_servants_import_cancel():
    """Bin a stashed import without committing anything. Reachable
    from the Cancel button on the preview page."""
    _require_trusted_servants_admin()
    embed = _ts_import_embed()
    token = (request.form.get("token") or "").strip()
    _ts_import_stash_delete(token)
    if embed:
        # Render the done template in cancel variant so the wizard's
        # parent closes the modal cleanly. No flash — the parent didn't
        # actually receive an action it needs surfaced.
        return render_template("trusted_servants_import_done.html",
                               embed=True,
                               active_step=3,
                               outcome="cancel",
                               added=0,
                               skipped_duplicate=0,
                               skipped_missing=0,
                               skipped_blank=0)
    flash("Import cancelled — nothing was added.", "info")
    return redirect(url_for("main.trusted_servants_list"))


@bp.route("/email-list/<int:sid>/edit", methods=["POST"])
@login_required
def trusted_servants_edit(sid):
    """Admin edit path — works for both user-linked rows (the user can
    still self-edit via the dashboard widget) and manual entries. The
    user-id binding is never touched here; only contact fields move."""
    _require_trusted_servants_admin()
    sub = db.session.get(TrustedServantSubscriber, sid) or abort(404)
    name = (request.form.get("name") or "").strip()[:120]
    phone = (request.form.get("phone") or "").strip()[:64]
    email = (request.form.get("email") or "").strip()[:255]
    notes = (request.form.get("notes") or "").strip() or None
    if not name or not email:
        flash("Name and email are required.", "danger")
        return redirect(url_for("main.trusted_servants_list"))
    sub.name = name
    sub.phone = phone or None
    sub.email = email
    sub.notes = notes
    db.session.commit()
    flash(f"Updated {name}.", "success")
    return redirect(url_for("main.trusted_servants_list"))


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


@bp.route("/settings/export", methods=["GET", "POST"])
@admin_required
def data_export():
    """Full-portal export.

    GET serves a plain ``.zip`` (legacy path / scripted callers). POST
    accepts an optional ``passphrase`` field; when non-empty the bundle
    is stream-encrypted with AES-256-GCM (key derived via PBKDF2-HMAC-
    SHA256 from the passphrase) and the download is ``.zip.enc``. The
    passphrase rides in the POST body, never the URL, so it can't leak
    via referrer / server logs / browser history. The encrypted format
    is documented in ``app/bundle_crypto.py``.
    """
    from flask import send_file
    from .backup import build_export_archive
    from .bundle_crypto import encrypt_file, EXT as _ENC_EXT

    passphrase = (request.form.get("passphrase") or "").strip() if request.method == "POST" else ""

    zip_path, archive_name, _size = build_export_archive(current_app._get_current_object())

    if not passphrase:
        response = send_file(zip_path, mimetype="application/zip",
                             as_attachment=True, download_name=archive_name)
        @response.call_on_close
        def _cleanup():
            try: os.unlink(zip_path)
            except OSError: pass
        return response

    enc_path = zip_path + _ENC_EXT
    try:
        encrypt_file(zip_path, enc_path, passphrase)
    finally:
        try: os.unlink(zip_path)
        except OSError: pass
    response = send_file(enc_path, mimetype="application/octet-stream",
                         as_attachment=True, download_name=archive_name + _ENC_EXT)
    @response.call_on_close
    def _cleanup_enc():
        try: os.unlink(enc_path)
        except OSError: pass
    return response


# Chunked-upload support for restore bundles larger than the proxy in
# front of us is willing to forward in a single request (Cloudflare's
# free plan caps request bodies at 100 MiB). The browser slices the file
# into ~90 MiB chunks, POSTs each to ``/settings/import/chunk``, then
# POSTs ``/settings/import/finalize`` to trigger the actual import. The
# direct-upload ``/settings/import`` route is kept as a no-JS fallback.
import re as _re
_UPLOAD_ID_RE = _re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _safe_upload_id(s):
    return bool(s and _UPLOAD_ID_RE.match(s))


def _chunk_staging_root():
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    data_dir = os.path.dirname(upload_dir.rstrip("/"))
    root = os.path.join(data_dir, "import-chunks")
    os.makedirs(root, exist_ok=True)
    return root


def _cleanup_stale_chunk_dirs(max_age_seconds=24 * 60 * 60):
    """Remove abandoned chunk-staging dirs (browser closed mid-upload,
    user navigated away, etc.) so they don't accumulate on disk."""
    import shutil as _shutil
    import time as _time
    cutoff = _time.time() - max_age_seconds
    root = _chunk_staging_root()
    try:
        for name in os.listdir(root):
            d = os.path.join(root, name)
            try:
                if os.path.getmtime(d) < cutoff:
                    _shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
    except OSError:
        pass


def _decrypt_if_encrypted(zip_path, passphrase):
    """If ``zip_path`` looks like a tsp-encrypted bundle, decrypt it
    under ``passphrase`` to a new tempfile and return the new path.
    Otherwise return ``zip_path`` unchanged. Caller is responsible for
    unlinking the returned path (which may equal ``zip_path``).

    Returns ``(path, decrypted: bool, error_msg: str | None)``. On
    decrypt failure ``path`` is None and ``error_msg`` carries a
    user-friendly explanation the caller flashes + redirects on.
    """
    import tempfile
    from .bundle_crypto import is_encrypted, decrypt_file, BundleDecryptError

    if not is_encrypted(zip_path):
        if passphrase:
            # Operator typed a passphrase but the bundle isn't encrypted
            # — proceeding anyway is safe, but warn so they catch
            # mismatched bundles before they overwrite the destination.
            flash("Passphrase ignored — uploaded bundle is not encrypted.", "warning")
        return zip_path, False, None
    if not passphrase:
        return None, False, ("This bundle is encrypted — supply the decryption "
                             "passphrase in the Import form and retry.")
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    data_dir = os.path.dirname(upload_dir.rstrip("/"))
    decrypted = tempfile.NamedTemporaryFile(
        prefix="tsp-import-decrypted-", suffix=".zip", delete=False, dir=data_dir)
    decrypted.close()
    try:
        decrypt_file(zip_path, decrypted.name, passphrase)
    except BundleDecryptError as exc:
        try: os.unlink(decrypted.name)
        except OSError: pass
        return None, False, str(exc)
    return decrypted.name, True, None


def _perform_data_import(zip_path):
    """Apply a full-portal import from a zip already saved on disk.
    Returns ``(ok: bool, redirect_url: str)``. Used by both the
    direct-upload ``data_import`` route and the chunked-upload
    ``data_import_finalize`` route so the import logic stays single-
    sourced. Flashes status messages; caller just follows the redirect.
    """
    import json, shutil, tempfile, zipfile
    from datetime import datetime

    upload_dir = current_app.config["UPLOAD_FOLDER"]
    data_dir = os.path.dirname(upload_dir.rstrip("/"))
    db_path = os.path.join(data_dir, "tsp.db")

    staging = tempfile.mkdtemp(prefix="tsp-import-", dir=data_dir)
    try:
        try:
            with zipfile.ZipFile(zip_path) as z:
                names = z.namelist()
                if "tsp.db" not in names or "manifest.json" not in names:
                    flash("Archive is missing tsp.db or manifest.json — not a valid export", "danger")
                    return False, _safe_referrer() or url_for("main.index")
                for n in names:
                    if n.startswith("/") or ".." in n.split("/"):
                        flash(f"Archive contains unsafe path: {n}", "danger")
                        return False, _safe_referrer() or url_for("main.index")
                try:
                    manifest = json.loads(z.read("manifest.json").decode("utf-8"))
                    if manifest.get("app") not in ("trusted-servants-pro", "trusted-servants-portal"):
                        flash("Archive manifest does not identify a Trusted Servants Pro export", "danger")
                        return False, _safe_referrer() or url_for("main.index")
                except (ValueError, UnicodeDecodeError):
                    flash("Archive manifest.json is invalid", "danger")
                    return False, _safe_referrer() or url_for("main.index")
                extract_dir = os.path.join(staging, "extracted")
                os.makedirs(extract_dir, exist_ok=True)
                z.extractall(extract_dir)
        except zipfile.BadZipFile:
            flash("File is not a valid zip archive", "danger")
            return False, _safe_referrer() or url_for("main.index")

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

        # Domain-bound state safety sweep. Turnstile sitekey/secret are
        # registered against the source's hostname at Cloudflare; carrying
        # them into a different host locks the admin out — the widget fails
        # to issue a token and ``_verify_turnstile`` rejects every login
        # attempt BEFORE password check. Disable when the destination's host
        # differs from the manifest's source_host (or when either side is
        # unknown). Pre-format_version-2 bundles have no source_host hint,
        # so default to scrubbing — same-host re-imports cost the admin one
        # toggle flip; cross-host imports are unlocked. Sitekey + secret are
        # preserved so a same-host operator can flip the toggle back without
        # re-entering credentials.
        from .models import SiteSetting, LoginFailure
        src_host = manifest.get("source_host") if isinstance(manifest, dict) else None
        dst_host = request.host if request else None
        host_changed = (not src_host) or (not dst_host) or (src_host != dst_host)
        ss = SiteSetting.query.first()
        if ss and ss.turnstile_enabled and host_changed:
            ss.turnstile_enabled = False
            db.session.commit()
            flash(
                f"Turnstile was enabled at the source"
                f"{f' ({src_host})' if src_host else ''} but disabled here "
                f"to prevent a login lockout — the sitekey is bound to the "
                f"source's domain. Re-enable from Settings → Security after "
                f"verifying the sitekey matches this host"
                f"{f' ({dst_host})' if dst_host else ''}.",
                "warning",
            )

        # Wipe any rate-limit lockouts the admin may have accumulated
        # bouncing off Turnstile (or other pre-restore login churn) so
        # they can sign back in immediately on the new install.
        LoginFailure.query.delete()
        db.session.commit()

        # Gunicorn worker recycle. We just swapped the SQLite file under
        # the running process — `db.engine.dispose()` cleared THIS worker's
        # pool, but sibling sync workers still hold connection handles to
        # the pre-restore file (Linux keeps the moved file readable through
        # the open fd), so requests routed to them after this point serve
        # stale rows / 404 on uploaded media intermittently depending on
        # which worker gunicorn picks. SIGHUP to the master triggers a
        # graceful recycle — new workers spawn against the restored file
        # before the old ones exit, and the current worker finishes
        # serving the redirect below before honouring the shutdown signal.
        # Guarded by a parent-cmdline check so this is a no-op under
        # `python run.py` (debug, single process) — sending SIGHUP to bash
        # would close the terminal.
        try:
            import signal as _signal
            ppid = os.getppid()
            if ppid > 1:
                with open(f"/proc/{ppid}/cmdline", "rb") as _f:
                    _ppid_cmd = _f.read().decode("utf-8", errors="ignore")
            else:
                # PID-1 is the gunicorn master itself (the Docker case).
                with open("/proc/1/cmdline", "rb") as _f:
                    _ppid_cmd = _f.read().decode("utf-8", errors="ignore")
                ppid = 1
            if "gunicorn" in _ppid_cmd:
                os.kill(ppid, _signal.SIGHUP)
        except (OSError, FileNotFoundError):
            pass

        flash(f"Import complete. Previous data backed up to {os.path.basename(backup_dir)}/ in the data directory. You will be signed out.", "success")
        return True, url_for("auth.logout")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


@bp.route("/settings/import", methods=["POST"])
@admin_required
def data_import():
    """Direct single-POST upload — no-JS fallback. Subject to the proxy's
    request-body cap (Cloudflare free = 100 MiB) and our own
    ``MAX_CONTENT_LENGTH``. The browser-side JS in base.html intercepts
    the form and uses the chunked-upload pair below instead so this
    route only handles the no-JS case or scripted clients."""
    import tempfile
    f = request.files.get("archive")
    if not f or not f.filename:
        flash("Choose an export archive (.zip) to import", "danger")
        return redirect(_safe_referrer() or url_for("main.index"))
    if request.form.get("confirm") != "REPLACE":
        flash('Type REPLACE in the confirmation box to proceed — import overwrites all data', "danger")
        return redirect(_safe_referrer() or url_for("main.index"))

    passphrase = (request.form.get("passphrase") or "").strip()

    upload_dir = current_app.config["UPLOAD_FOLDER"]
    data_dir = os.path.dirname(upload_dir.rstrip("/"))
    tmp_zip = tempfile.NamedTemporaryFile(
        prefix="tsp-import-direct-", suffix=".zip", delete=False, dir=data_dir)
    tmp_zip.close()
    decrypted_path = None
    try:
        f.save(tmp_zip.name)
        import_path, was_decrypted, err = _decrypt_if_encrypted(tmp_zip.name, passphrase)
        if err:
            flash(err, "danger")
            return redirect(_safe_referrer() or url_for("main.index"))
        if was_decrypted:
            decrypted_path = import_path
        _ok, target = _perform_data_import(import_path)
        return redirect(target)
    finally:
        try: os.unlink(tmp_zip.name)
        except OSError: pass
        if decrypted_path:
            try: os.unlink(decrypted_path)
            except OSError: pass


@bp.route("/settings/import/chunk", methods=["POST"])
@admin_required
def data_import_chunk():
    """Receive one chunk of a multi-part bundle upload. The browser
    slices the .zip into ~90 MiB chunks (under Cloudflare's 100 MiB cap)
    and POSTs each here keyed by a per-upload UUID. Chunks land at
    ``<data_dir>/import-chunks/<upload_id>/<chunk_index:08d>.bin`` so
    finalize can concat them in order."""
    upload_id = (request.form.get("upload_id") or "").strip().lower()
    if not _safe_upload_id(upload_id):
        return jsonify(error="invalid upload_id"), 400
    try:
        chunk_index = int(request.form.get("chunk_index", ""))
        total_chunks = int(request.form.get("total_chunks", ""))
    except ValueError:
        return jsonify(error="bad chunk metadata"), 400
    if chunk_index < 0 or total_chunks < 1 or chunk_index >= total_chunks:
        return jsonify(error="chunk index out of range"), 400
    chunk = request.files.get("chunk")
    if not chunk:
        return jsonify(error="no chunk file"), 400

    _cleanup_stale_chunk_dirs()
    staging = os.path.join(_chunk_staging_root(), upload_id)
    os.makedirs(staging, exist_ok=True)
    chunk_path = os.path.join(staging, f"{chunk_index:08d}.bin")
    chunk.save(chunk_path)
    return jsonify(ok=True, chunk_index=chunk_index, total_chunks=total_chunks)


@bp.route("/settings/import/finalize", methods=["POST"])
@admin_required
def data_import_finalize():
    """Assemble the chunks deposited under the given ``upload_id`` into
    a single .zip on disk and hand it to ``_perform_data_import``. Same
    REPLACE confirmation gate as the direct route; same redirect to
    ``auth.logout`` on success (post-import flash + worker recycle live
    in the shared helper)."""
    import shutil, tempfile
    upload_id = (request.form.get("upload_id") or "").strip().lower()
    if not _safe_upload_id(upload_id):
        flash("Invalid upload session — please retry the upload", "danger")
        return redirect(_safe_referrer() or url_for("main.index"))
    if request.form.get("confirm") != "REPLACE":
        flash('Type REPLACE in the confirmation box to proceed — import overwrites all data', "danger")
        return redirect(_safe_referrer() or url_for("main.index"))

    staging = os.path.join(_chunk_staging_root(), upload_id)
    if not os.path.isdir(staging):
        flash("Upload session not found — please retry the upload", "danger")
        return redirect(_safe_referrer() or url_for("main.index"))

    chunks = sorted(n for n in os.listdir(staging) if n.endswith(".bin"))
    try:
        expected = int(request.form.get("expected_chunks", "0"))
    except ValueError:
        expected = 0
    if expected and len(chunks) != expected:
        shutil.rmtree(staging, ignore_errors=True)
        flash(
            f"Upload incomplete — expected {expected} chunks but only "
            f"{len(chunks)} arrived. Please retry.", "danger")
        return redirect(_safe_referrer() or url_for("main.index"))

    passphrase = (request.form.get("passphrase") or "").strip()

    upload_dir = current_app.config["UPLOAD_FOLDER"]
    data_dir = os.path.dirname(upload_dir.rstrip("/"))
    tmp_zip = tempfile.NamedTemporaryFile(
        prefix="tsp-import-chunked-", suffix=".zip", delete=False, dir=data_dir)
    try:
        for name in chunks:
            with open(os.path.join(staging, name), "rb") as src:
                while True:
                    block = src.read(8 * 1024 * 1024)
                    if not block:
                        break
                    tmp_zip.write(block)
    finally:
        tmp_zip.close()

    decrypted_path = None
    try:
        import_path, was_decrypted, err = _decrypt_if_encrypted(tmp_zip.name, passphrase)
        if err:
            flash(err, "danger")
            return redirect(_safe_referrer() or url_for("main.index"))
        if was_decrypted:
            decrypted_path = import_path
        _ok, target = _perform_data_import(import_path)
        return redirect(target)
    finally:
        try: os.unlink(tmp_zip.name)
        except OSError: pass
        if decrypted_path:
            try: os.unlink(decrypted_path)
            except OSError: pass
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
        plus typography overrides plus per-page Open Graph overrides
        (title / description / image) ride along; layout_key is preserved
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
            # Per-page Open Graph overrides (social-share card). Empty
            # values fall back to the site-wide frontend_og_* defaults
            # at render time. og_image_filename is also collected as an
            # asset below so the image ships with the bundle.
            "og_title": p.og_title,
            "og_description": p.og_description,
            "og_image_filename": p.og_image_filename,
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
            # Editorial publication timestamp (drives the public
            # "posted on" stamp via Story.display_posted). Preserved so
            # imported stories keep their original date instead of
            # resetting to the import time.
            "published_at": st.published_at.isoformat() if st.published_at else None,
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
        if p.get("og_image_filename"):
            asset_refs.add(p["og_image_filename"])
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

    # Every collected ref is kept here regardless of whether it matches
    # a MediaItem row — the export-route zip step is the real filter: it
    # only writes names that exist on disk (``if os.path.isfile``), so
    # regex false-positives (a bare 32-hex coincidence inside a non-asset
    # string, with no matching file) are silently skipped at write time
    # and never ship. Keeping non-MediaItem refs here is deliberate so
    # pre-MediaItem uploads (older installs whose files were never
    # indexed) still ride along; the import-side backfill re-indexes them.
    # Net effect: ``final_assets`` may list more names than the bundle
    # actually contains, but it never omits a real referenced file.
    known_media = {m.stored_filename: m for m in MediaItem.query.all()}
    final_assets = set(asset_refs)

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
        "kind": "frontend", "format_version": 5,
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
# Off-site backups — 5-step setup wizard + list / restore / history.
# Archive payload comes from app.backup.build_export_archive (DB + uploads
# + zoom.key). Backends in app.backup_backends. Scheduler in
# app.backup_scheduler runs due jobs once a minute.
# ---------------------------------------------------------------------------

SCHEDULE_PRESETS = {
    "hourly": ("0 * * * *", "Top of every hour"),
    "daily-3am": ("0 3 * * *", "Every day at 03:00 UTC"),
    "daily-noon": ("0 12 * * *", "Every day at 12:00 UTC"),
    "weekly-sun": ("0 3 * * 0", "Every Sunday at 03:00 UTC"),
    "monthly": ("0 3 1 * *", "First of the month at 03:00 UTC"),
}


def _backup_embed():
    """True when the wizard request came in via the modal iframe."""
    return (request.args.get("embed") == "1"
            or request.form.get("embed") == "1")


def _backup_embed_kwargs():
    """Spread into url_for(...) inside wizard redirects so embed mode survives."""
    return {"embed": 1} if _backup_embed() else {}


def _validate_cron(expr):
    """Returns None if ok, else an error string. Used at form-validate time."""
    try:
        from croniter import croniter
        croniter(expr)
        return None
    except Exception as e:  # noqa: BLE001
        return f"Not a valid cron expression: {e}"


def _exchange_dropbox_auth_code(app_key, app_secret, auth_code):
    """Exchange a Dropbox one-time authorization code for a long-lived
    refresh token. Returns ``(refresh_token, None)`` on success or
    ``(None, error_message)`` on failure — caller flashes the error and
    rejects the form. The Dropbox SDK provides a higher-level
    ``DropboxOAuth2FlowNoRedirect`` helper, but a raw POST is enough
    here and keeps the dependency surface tight."""
    if not (app_key and app_secret and auth_code):
        return None, "App key, app secret, and authorization code are all required."
    import requests
    try:
        resp = requests.post(
            "https://api.dropboxapi.com/oauth2/token",
            data={
                "code": auth_code,
                "grant_type": "authorization_code",
                "client_id": app_key,
                "client_secret": app_secret,
            },
            timeout=15,
        )
    except requests.RequestException as e:
        return None, f"Couldn't reach Dropbox to exchange the code: {e}"
    try:
        body = resp.json()
    except ValueError:
        return None, f"Dropbox returned a non-JSON response ({resp.status_code})."
    if resp.status_code != 200:
        err = body.get("error_description") or body.get("error") or f"HTTP {resp.status_code}"
        # Map the common cases to actionable copy.
        if "invalid_grant" in str(err).lower() or "expired" in str(err).lower() or "code" in str(err).lower():
            err = (f"Dropbox rejected the authorization code ({err}). "
                   f"Codes are single-use and expire quickly — open the "
                   f"authorization page again, allow access, and paste the "
                   f"fresh code.")
        elif "invalid_client" in str(err).lower():
            err = (f"Dropbox rejected the app credentials ({err}). "
                   f"Double-check the App key and App secret from your "
                   f"app's Settings tab.")
        return None, f"Dropbox auth-code exchange failed: {err}"
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        return None, ("Dropbox didn't return a refresh token. Make sure "
                      "the authorization URL included "
                      "`token_access_type=offline` — use the "
                      "auto-generated button above the code field "
                      "rather than a hand-crafted URL.")
    return refresh_token, None


@bp.route("/settings/backups")
@admin_required
def backups_list():
    targets = BackupTarget.query.order_by(BackupTarget.created_at.desc()).all()
    recent = (BackupRun.query
              .order_by(BackupRun.started_at.desc())
              .limit(20).all())
    return render_template("backups_list.html",
                           targets=targets,
                           recent_runs=recent,
                           embed=_backup_embed())


@bp.route("/settings/backups/new")
@admin_required
def backups_new():
    """Step 1 — pick a backend kind. Creates a stub BackupTarget so the
    wizard has somewhere to write each step's data; the stub is left
    disabled until the wizard completes."""
    return render_template("backups_wizard_step1.html",
                           kinds=BACKUP_KINDS,
                           embed=_backup_embed())


@bp.route("/settings/backups/new", methods=["POST"])
@admin_required
def backups_new_post():
    kind = (request.form.get("kind") or "").strip()
    name = (request.form.get("name") or "").strip() or f"New {kind.upper()} backup"
    if kind not in BACKUP_KINDS:
        flash("Pick a destination type to continue.", "danger")
        return redirect(url_for("main.backups_new", **_backup_embed_kwargs()))
    t = BackupTarget(name=name, kind=kind, enabled=False,
                     remote_path="/" if kind == "dropbox" else "/backups/tsp",
                     schedule_cron="0 3 * * *",
                     retain_count=14,
                     use_tls=True)
    db.session.add(t)
    db.session.commit()
    return redirect(url_for("main.backups_wizard", target_id=t.id, step=2,
                            **_backup_embed_kwargs()))


@bp.route("/settings/backups/<int:target_id>/wizard/<int:step>")
@admin_required
def backups_wizard(target_id, step):
    t = db.session.get(BackupTarget, target_id) or abort(404)
    embed = _backup_embed()
    if step == 2:
        return render_template("backups_wizard_step2.html", t=t, embed=embed)
    if step == 3:
        return render_template("backups_wizard_step3.html", t=t,
                               presets=SCHEDULE_PRESETS, embed=embed)
    if step == 4:
        return render_template("backups_wizard_step4.html", t=t, embed=embed)
    if step == 5:
        return render_template("backups_wizard_step5.html", t=t,
                               presets=SCHEDULE_PRESETS, embed=embed)
    abort(404)


@bp.route("/settings/backups/<int:target_id>/wizard/2", methods=["POST"])
@admin_required
def backups_wizard_step2_post(target_id):
    """Connection details. Kind-specific fields, all credential columns
    are Fernet-encrypted via app.crypto.encrypt before save."""
    t = db.session.get(BackupTarget, target_id) or abort(404)
    t.name = (request.form.get("name") or t.name).strip()
    t.host = (request.form.get("host") or "").strip() or None
    port_raw = (request.form.get("port") or "").strip()
    t.port = int(port_raw) if port_raw.isdigit() else None
    t.username = (request.form.get("username") or "").strip() or None
    t.remote_path = (request.form.get("remote_path") or "/").strip() or "/"

    if t.kind == "ftp":
        t.use_tls = (request.form.get("use_tls") == "1")
        password = request.form.get("password") or ""
        if password:
            t.password_enc = encrypt(password)
    elif t.kind == "sftp":
        password = request.form.get("password") or ""
        if password:
            t.password_enc = encrypt(password)
        key_file = request.files.get("private_key")
        key_text = (request.form.get("private_key_text") or "").strip()
        if key_file and key_file.filename:
            try:
                key_text = key_file.read().decode("utf-8", errors="replace")
            except Exception:
                key_text = ""
        if key_text:
            t.private_key_enc = encrypt(key_text)
    elif t.kind == "dropbox":
        # Dropbox refresh-token flow. The wizard collects three things:
        # app_key (public client id), app_secret (encrypted at rest),
        # and an optional one-time authorization code which we exchange
        # for a refresh token here. Legacy oauth_token field still
        # accepted so a paste-the-access-token workflow keeps working
        # for back-compat, but is no longer surfaced in the UI.
        new_app_key = (request.form.get("app_key") or "").strip()
        if new_app_key:
            t.app_key = new_app_key
        new_app_secret = (request.form.get("app_secret") or "").strip()
        if new_app_secret:
            t.app_secret_enc = encrypt(new_app_secret)
        auth_code = (request.form.get("auth_code") or "").strip()
        if auth_code:
            secret_plain = (new_app_secret
                            or (decrypt(t.app_secret_enc) if t.app_secret_enc else None))
            refresh, err = _exchange_dropbox_auth_code(
                t.app_key, secret_plain, auth_code)
            if err:
                flash(err, "danger")
                return redirect(url_for("main.backups_wizard",
                                        target_id=t.id, step=2,
                                        **_backup_embed_kwargs()))
            t.refresh_token_enc = encrypt(refresh)
            # Refresh token supersedes any legacy short-lived access
            # token — clear it so DropboxBackend doesn't fall back.
            t.oauth_token_enc = None
        legacy_token = (request.form.get("oauth_token") or "").strip()
        if legacy_token:
            t.oauth_token_enc = encrypt(legacy_token)

    db.session.commit()
    return redirect(url_for("main.backups_wizard", target_id=t.id, step=3,
                            **_backup_embed_kwargs()))


@bp.route("/settings/backups/<int:target_id>/wizard/3", methods=["POST"])
@admin_required
def backups_wizard_step3_post(target_id):
    """Schedule + retention."""
    t = db.session.get(BackupTarget, target_id) or abort(404)
    preset = request.form.get("schedule_preset") or ""
    custom = (request.form.get("schedule_cron") or "").strip()
    if preset in SCHEDULE_PRESETS:
        t.schedule_cron = SCHEDULE_PRESETS[preset][0]
    elif custom:
        err = _validate_cron(custom)
        if err:
            flash(err, "danger")
            return redirect(url_for("main.backups_wizard", target_id=t.id, step=3,
                                    **_backup_embed_kwargs()))
        t.schedule_cron = custom
    retain_raw = (request.form.get("retain_count") or "14").strip()
    try:
        t.retain_count = max(1, min(365, int(retain_raw)))
    except ValueError:
        t.retain_count = 14
    db.session.commit()
    return redirect(url_for("main.backups_wizard", target_id=t.id, step=4,
                            **_backup_embed_kwargs()))


@bp.route("/settings/backups/<int:target_id>/wizard/4", methods=["POST"])
@admin_required
def backups_wizard_step4_post(target_id):
    """Encryption-at-rest opt-in."""
    t = db.session.get(BackupTarget, target_id) or abort(404)
    want = (request.form.get("encrypt_archive") == "1")
    if want:
        passphrase = request.form.get("passphrase") or ""
        confirm = request.form.get("passphrase_confirm") or ""
        if not passphrase or len(passphrase) < 8:
            flash("Passphrase must be at least 8 characters.", "danger")
            return redirect(url_for("main.backups_wizard", target_id=t.id, step=4,
                                    **_backup_embed_kwargs()))
        if passphrase != confirm:
            flash("Passphrases don't match.", "danger")
            return redirect(url_for("main.backups_wizard", target_id=t.id, step=4,
                                    **_backup_embed_kwargs()))
        if not request.form.get("ack_saved"):
            flash("Please confirm you've saved the passphrase — there's no recovery.", "danger")
            return redirect(url_for("main.backups_wizard", target_id=t.id, step=4,
                                    **_backup_embed_kwargs()))
        t.encrypt_archive = True
        t.archive_passphrase_enc = encrypt(passphrase)
    else:
        t.encrypt_archive = False
        t.archive_passphrase_enc = None
    db.session.commit()
    return redirect(url_for("main.backups_wizard", target_id=t.id, step=5,
                            **_backup_embed_kwargs()))


@bp.route("/settings/backups/<int:target_id>/wizard/5", methods=["POST"])
@admin_required
def backups_wizard_step5_post(target_id):
    """Finalize. Enables the target, seeds next_run_at, optionally fires
    a first run synchronously so the admin sees ok/fail before leaving
    the wizard.

    In embed mode we render a tiny "done" template that postMessages the
    parent to close the modal + refresh, so the user doesn't see a
    redirect cascade inside the iframe.
    """
    from .backup_scheduler import compute_next_run, run_target
    t = db.session.get(BackupTarget, target_id) or abort(404)
    t.enabled = True
    t.next_run_at = compute_next_run(t.schedule_cron)
    db.session.commit()
    success = True
    detail = None
    if request.form.get("run_now") == "1":
        run = run_target(current_app._get_current_object(), t.id, triggered_by="manual")
        if run and run.status == "ok":
            detail = f"Backup saved to {t.name}."
        else:
            success = False
            detail = (run.error_message if run else None) or "unknown error"
    else:
        # Render next_run_at in the site's configured tz so the
        # confirmation matches the wall clock the rest of the admin
        # uses. ``next_run_at`` is naive-UTC per scheduler convention;
        # attach tz, convert, format with %Z so the abbreviation
        # ("PDT" / "EST" / etc.) sits on the end instead of "UTC".
        from datetime import timezone as _tz
        from .timezone import site_timezone as _stz
        _site = _get_site_setting()
        _aware = t.next_run_at.replace(tzinfo=_tz.utc) if t.next_run_at and t.next_run_at.tzinfo is None else t.next_run_at
        _stamp = _aware.astimezone(_stz(_site)).strftime("%Y-%m-%d %H:%M %Z") if _aware else "(unscheduled)"
        detail = f"Backup target '{t.name}' is set up — next run {_stamp}."

    if _backup_embed():
        return render_template("backups_wizard_done.html",
                               t=t, success=success, detail=detail, embed=True)
    flash(detail, "success" if success else "danger")
    return redirect(url_for("main.backups_list"))


@bp.route("/settings/backups/<int:target_id>/edit", methods=["GET"])
@admin_required
def backups_edit(target_id):
    """Single-page edit for an already-configured target. Combines the
    three editable wizard panels (connection, schedule, encryption) on
    one form so the admin doesn't have to walk through the whole
    add-target chain to flip one field. ``kind`` is read-only — switching
    backends mid-life would orphan the existing remote archives."""
    t = db.session.get(BackupTarget, target_id) or abort(404)
    return render_template("backups_edit.html", t=t,
                           presets=SCHEDULE_PRESETS,
                           embed=_backup_embed())


@bp.route("/settings/backups/<int:target_id>/edit", methods=["POST"])
@admin_required
def backups_edit_post(target_id):
    """Consolidated save for the edit page. Mirrors the step 2/3/4 POST
    handlers but stays on the same row + redirects back to the list
    (no run-now, no enable-flip, no wizard chain). Schedule changes
    re-seed ``next_run_at`` if the target is currently enabled so the
    new cron takes effect on the next scheduler tick rather than the
    next save / restart."""
    from .backup_scheduler import compute_next_run
    t = db.session.get(BackupTarget, target_id) or abort(404)

    # ── Connection (same field-write pattern as step 2) ──
    t.name = (request.form.get("name") or t.name).strip()
    t.host = (request.form.get("host") or "").strip() or None
    port_raw = (request.form.get("port") or "").strip()
    t.port = int(port_raw) if port_raw.isdigit() else None
    t.username = (request.form.get("username") or "").strip() or None
    t.remote_path = (request.form.get("remote_path") or "/").strip() or "/"

    if t.kind == "ftp":
        t.use_tls = (request.form.get("use_tls") == "1")
        password = request.form.get("password") or ""
        if password:
            t.password_enc = encrypt(password)
    elif t.kind == "sftp":
        password = request.form.get("password") or ""
        if password:
            t.password_enc = encrypt(password)
        key_file = request.files.get("private_key")
        key_text = (request.form.get("private_key_text") or "").strip()
        if key_file and key_file.filename:
            try:
                key_text = key_file.read().decode("utf-8", errors="replace")
            except Exception:
                key_text = ""
        if key_text:
            t.private_key_enc = encrypt(key_text)
    elif t.kind == "dropbox":
        # Mirror of the wizard step 2 Dropbox flow — see comments there.
        # Pulls app_key / app_secret / auth_code from the form; when an
        # auth_code is present we exchange it for a refresh token.
        new_app_key = (request.form.get("app_key") or "").strip()
        if new_app_key:
            t.app_key = new_app_key
        new_app_secret = (request.form.get("app_secret") or "").strip()
        if new_app_secret:
            t.app_secret_enc = encrypt(new_app_secret)
        auth_code = (request.form.get("auth_code") or "").strip()
        if auth_code:
            secret_plain = (new_app_secret
                            or (decrypt(t.app_secret_enc) if t.app_secret_enc else None))
            refresh, err = _exchange_dropbox_auth_code(
                t.app_key, secret_plain, auth_code)
            if err:
                flash(err, "danger")
                return redirect(url_for("main.backups_edit", target_id=t.id,
                                        **_backup_embed_kwargs()))
            t.refresh_token_enc = encrypt(refresh)
            t.oauth_token_enc = None
        legacy_token = (request.form.get("oauth_token") or "").strip()
        if legacy_token:
            t.oauth_token_enc = encrypt(legacy_token)

    # ── Schedule (same as step 3) ──
    preset = request.form.get("schedule_preset") or ""
    custom = (request.form.get("schedule_cron") or "").strip()
    if preset in SCHEDULE_PRESETS:
        t.schedule_cron = SCHEDULE_PRESETS[preset][0]
    elif custom:
        err = _validate_cron(custom)
        if err:
            flash(err, "danger")
            return redirect(url_for("main.backups_edit", target_id=t.id,
                                    **_backup_embed_kwargs()))
        t.schedule_cron = custom
    retain_raw = (request.form.get("retain_count") or "14").strip()
    try:
        t.retain_count = max(1, min(365, int(retain_raw)))
    except ValueError:
        t.retain_count = 14

    # ── Encryption (same as step 4) ──
    # Three meaningful submit shapes: leave-as-is (encrypt_archive
    # unchanged, no passphrase typed), rotate-passphrase (encrypt_archive
    # already on + new passphrase typed), enable-or-disable. The
    # wizard's step-4 ack_saved gate only kicks in when a new passphrase
    # is being set — toggling an already-stored passphrase off doesn't
    # need re-acknowledgement.
    want_encrypt = (request.form.get("encrypt_archive") == "1")
    new_passphrase = request.form.get("passphrase") or ""
    confirm = request.form.get("passphrase_confirm") or ""
    if want_encrypt:
        # Setting encryption ON (or rotating an existing passphrase).
        # Allow leaving the passphrase blank to keep the current one
        # when encryption is already on; require it on first turn-on.
        if new_passphrase or not t.archive_passphrase_enc:
            if not new_passphrase or len(new_passphrase) < 8:
                flash("Passphrase must be at least 8 characters.", "danger")
                return redirect(url_for("main.backups_edit", target_id=t.id,
                                        **_backup_embed_kwargs()))
            if new_passphrase != confirm:
                flash("Passphrases don't match.", "danger")
                return redirect(url_for("main.backups_edit", target_id=t.id,
                                        **_backup_embed_kwargs()))
            if not request.form.get("ack_saved"):
                flash("Please confirm you've saved the passphrase — there's no recovery.", "danger")
                return redirect(url_for("main.backups_edit", target_id=t.id,
                                        **_backup_embed_kwargs()))
            t.archive_passphrase_enc = encrypt(new_passphrase)
        t.encrypt_archive = True
    else:
        # Turning encryption OFF — drop the stored passphrase too so we
        # don't keep an unused secret on disk.
        t.encrypt_archive = False
        t.archive_passphrase_enc = None

    # Re-seed next_run_at when the schedule has changed AND the target is
    # currently enabled — otherwise the new cron only takes effect on the
    # next scheduler restart / first natural tick that crosses the saved
    # next_run_at. Cheap to always recompute.
    if t.enabled:
        t.next_run_at = compute_next_run(t.schedule_cron)

    db.session.commit()
    flash(f"Updated '{t.name}'.", "success")
    return redirect(url_for("main.backups_list", **_backup_embed_kwargs()))


@bp.route("/settings/backups/<int:target_id>/test", methods=["POST"])
@admin_required
def backups_test(target_id):
    """Round-trip a 1-byte sentinel file to the backend so we surface
    auth/path failures before the user advances the wizard."""
    from .backup_backends import make_backend, BackendError
    t = db.session.get(BackupTarget, target_id) or abort(404)
    backend = None
    try:
        backend = make_backend(t)
        backend.open()
        sentinel_name = f"{__import__('app.backup', fromlist=['EXPORT_PREFIX']).EXPORT_PREFIX}probe.zip"
        import tempfile as _tempfile
        with _tempfile.NamedTemporaryFile(prefix="tsp-probe-", suffix=".zip", delete=False) as tmp:
            tmp.write(b"x")
            tmp_path = tmp.name
        try:
            backend.put(tmp_path, sentinel_name)
            backend.delete(sentinel_name)
        finally:
            try: os.unlink(tmp_path)
            except OSError: pass
        return jsonify({"ok": True, "message": "Connection ok — wrote and removed a probe file."})
    except BackendError as e:
        return jsonify({"ok": False, "message": str(e)}), 200
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "message": f"{type(e).__name__}: {e}"}), 200
    finally:
        if backend is not None:
            try: backend.close()
            except Exception: pass


@bp.route("/settings/backups/<int:target_id>/run-now", methods=["POST"])
@admin_required
def backups_run_now(target_id):
    """Manual one-off run. Synchronous so the result lands in the
    flash before the redirect — backups are small enough (~MB to low
    hundreds of MB) that doing this inside a request is fine."""
    from .backup_scheduler import run_target
    t = db.session.get(BackupTarget, target_id) or abort(404)
    run = run_target(current_app._get_current_object(), t.id, triggered_by="manual")
    if run and run.status == "ok":
        flash(f"Backup uploaded to {t.name} ({(run.bytes_uploaded or 0) // 1024} KB).", "success")
    else:
        err = (run.error_message if run else None) or "unknown error"
        flash(f"Backup to {t.name} failed: {err}", "danger")
    return redirect(_safe_referrer() or url_for("main.backups_list"))


@bp.route("/settings/backups/<int:target_id>/enable", methods=["POST"])
@admin_required
def backups_toggle(target_id):
    from .backup_scheduler import compute_next_run
    t = db.session.get(BackupTarget, target_id) or abort(404)
    t.enabled = not t.enabled
    if t.enabled and not t.next_run_at:
        t.next_run_at = compute_next_run(t.schedule_cron)
    db.session.commit()
    flash(f"'{t.name}' is now {'enabled' if t.enabled else 'paused'}.", "success")
    return redirect(_safe_referrer() or url_for("main.backups_list"))


@bp.route("/settings/backups/<int:target_id>/delete", methods=["POST"])
@admin_required
def backups_delete(target_id):
    t = db.session.get(BackupTarget, target_id) or abort(404)
    name = t.name
    db.session.delete(t)
    db.session.commit()
    flash(f"Removed backup target '{name}'. Existing remote files were left intact.", "info")
    return redirect(url_for("main.backups_list", **_backup_embed_kwargs()))


@bp.route("/settings/backups/<int:target_id>/runs")
@admin_required
def backups_runs(target_id):
    t = db.session.get(BackupTarget, target_id) or abort(404)
    runs = (BackupRun.query.filter_by(target_id=t.id)
            .order_by(BackupRun.started_at.desc())
            .limit(200).all())
    return render_template("backups_runs.html", t=t, runs=runs,
                           embed=_backup_embed())


@bp.route("/settings/backups/<int:target_id>/restore")
@admin_required
def backups_restore(target_id):
    """List remote archives so the admin can pull one back and restore."""
    from .backup_backends import make_backend, BackendError
    t = db.session.get(BackupTarget, target_id) or abort(404)
    files, error = [], None
    backend = None
    try:
        backend = make_backend(t)
        backend.open()
        files = backend.list()
    except BackendError as e:
        error = str(e)
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
    finally:
        if backend is not None:
            try: backend.close()
            except Exception: pass
    return render_template("backups_restore.html", t=t, files=files, error=error,
                           embed=_backup_embed())


@bp.route("/settings/backups/<int:target_id>/restore", methods=["POST"])
@admin_required
def backups_restore_post(target_id):
    """Pull a chosen remote archive, decrypt if needed, then hand the
    resulting zip back to the existing import flow.

    The existing data_import() route consumes ``request.files['archive']``
    — rather than rebuild it here, we redirect with a flash explaining
    that the user should upload the freshly-downloaded archive via the
    existing 'Import data' form. That's a smaller surface than two
    parallel import implementations.
    """
    from .backup_backends import make_backend, BackendError
    from .backup import decrypt_archive_file
    from flask import send_file
    import tempfile as _tempfile

    t = db.session.get(BackupTarget, target_id) or abort(404)
    remote_name = (request.form.get("archive") or "").strip()
    if not remote_name:
        flash("Pick an archive to download.", "danger")
        return redirect(url_for("main.backups_restore", target_id=t.id, **_backup_embed_kwargs()))

    passphrase = request.form.get("passphrase") or ""
    tmp = _tempfile.NamedTemporaryFile(prefix="tsp-restore-", suffix=".bin", delete=False)
    tmp.close()
    backend = None
    try:
        backend = make_backend(t)
        backend.open()
        backend.put  # noqa — sanity ref so static analysis doesn't gripe about unused
        backend.fetch(remote_name, tmp.name)
    except BackendError as e:
        try: os.unlink(tmp.name)
        except OSError: pass
        flash(f"Could not download {remote_name}: {e}", "danger")
        return redirect(url_for("main.backups_restore", target_id=t.id, **_backup_embed_kwargs()))
    finally:
        if backend is not None:
            try: backend.close()
            except Exception: pass

    out_path = tmp.name
    out_name = remote_name
    if remote_name.endswith(".enc"):
        if not passphrase:
            try: os.unlink(tmp.name)
            except OSError: pass
            flash("This archive is encrypted — enter the passphrase to download it decrypted.", "danger")
            return redirect(url_for("main.backups_restore", target_id=t.id, **_backup_embed_kwargs()))
        try:
            out_path = decrypt_archive_file(tmp.name, passphrase)
            out_name = remote_name[:-4]  # drop .enc
        except ValueError as e:
            try: os.unlink(tmp.name)
            except OSError: pass
            flash(f"Decryption failed: {e}", "danger")
            return redirect(url_for("main.backups_restore", target_id=t.id, **_backup_embed_kwargs()))
        finally:
            try: os.unlink(tmp.name)
            except OSError: pass

    response = send_file(out_path, mimetype="application/zip",
                         as_attachment=True, download_name=out_name)

    @response.call_on_close
    def _cleanup():
        try: os.unlink(out_path)
        except OSError: pass
    return response


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
    # The import commits in chunks, so post count is no longer the limit —
    # but the single fetch is ceilinged so the connect request can't run
    # forever. Warn only when we actually hit that ceiling.
    if len(posts) >= wp_importer.MAX_FETCH_POSTS:
        flash(f"This site has at least {wp_importer.MAX_FETCH_POSTS:,} posts — fetched the "
              f"newest {len(posts):,}. To bring in older posts beyond that, narrow the set "
              "on the WordPress side (e.g. by date) and run the wizard again.", "warning")
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
        return redirect(url_for("main.wp_import_fields", token=token, **_wp_embed_kwargs()))

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


def _wp_site_key(stash):
    """Stable key for the reusable field-mapping profile. REST imports key
    by host; CSV uploads share one ``csv`` profile."""
    if (stash or {}).get("source") == "rest":
        from urllib.parse import urlparse
        url = (stash.get("site_url") or "").strip()
        host = (urlparse(url).netloc or url).lower().strip()
        return ("rest:" + host) if host else None
    return "csv"


def _wp_load_field_profile(stash):
    """Last saved ``{target: {dest: wp_key}}`` mapping for this site, or
    None."""
    key = _wp_site_key(stash)
    if not key:
        return None
    from .models import WpFieldMapping
    row = WpFieldMapping.query.filter_by(site_key=key).first()
    if not row or not row.mapping_json:
        return None
    import json
    try:
        data = json.loads(row.mapping_json)
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


def _wp_save_field_profile(stash, field_mapping):
    """Persist the field mapping as the site's reusable profile."""
    key = _wp_site_key(stash)
    if not key:
        return
    import json
    from .models import db, WpFieldMapping
    row = WpFieldMapping.query.filter_by(site_key=key).first()
    if not row:
        row = WpFieldMapping(site_key=key)
        db.session.add(row)
    row.mapping_json = json.dumps(field_mapping or {})
    db.session.commit()


@bp.route("/settings/wp-import/<token>/fields", methods=["GET", "POST"])
@admin_required
def wp_import_fields(token):
    """Step 3 — map the WordPress custom fields discovered on the source
    onto each target post type's destination fields. Auto-fills smart
    defaults (saved per-site profile, else field-name detection); the
    admin can override every one. Skipped automatically when the source
    exposes no custom fields or nothing is routed anywhere mappable."""
    from . import wp_importer
    stash = wp_importer.stash_load(token)
    if not stash:
        flash("That import wizard session has expired. Start over.", "warning")
        return redirect(url_for("main.wp_import_start", **_wp_embed_kwargs()))

    mapping = stash.get("mapping") or {}
    in_use = set(mapping.values())
    targets = [t for t in wp_importer.TARGETS
               if t != "skip" and t in in_use and wp_importer.TARGET_FIELDS.get(t)]
    discovered = wp_importer.discover_fields(stash.get("posts") or [])

    if request.method == "POST":
        fm = {}
        valid_keys = {f["key"] for f in discovered}
        for t in targets:
            tm = {}
            for f in wp_importer.TARGET_FIELDS.get(t) or []:
                val = (request.form.get(f"map:{t}:{f['key']}") or "").strip()
                # Only accept a real discovered field; "" = leave unmapped.
                if val and val in valid_keys:
                    tm[f["key"]] = val
            fm[t] = tm
        stash["field_mapping"] = fm
        wp_importer.stash_save(token, stash)
        _wp_save_field_profile(stash, fm)
        return redirect(url_for("main.wp_import_dry_run", token=token, **_wp_embed_kwargs()))

    # GET — nothing to map ⇒ skip straight to the dry run.
    if not discovered or not targets:
        return redirect(url_for("main.wp_import_dry_run", token=token, **_wp_embed_kwargs()))

    # Current mapping precedence: this wizard's saved choice → the site's
    # saved profile → auto-suggested defaults from field-name detection.
    current = stash.get("field_mapping")
    profile_used = False
    if not current:
        current = _wp_load_field_profile(stash)
        profile_used = bool(current)
    if not current:
        current = wp_importer.suggest_mapping(stash.get("posts") or [], targets)
    return render_template("wp_import_fields.html", token=token, stash=stash,
                           targets=targets,
                           target_labels=wp_importer.TARGET_LABELS,
                           target_fields=wp_importer.TARGET_FIELDS,
                           discovered=discovered,
                           current=current,
                           profile_used=profile_used,
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

    chunk_size = wp_importer.COMMIT_CHUNK_SIZE
    total_actions = len(actions)

    if request.method == "POST":
        # Two POST shapes:
        #   • First commit — carries the IMPORT confirmation + per-row
        #     archive checkboxes from the dry-run form.
        #   • Continue chunk — carries ``continue_chunk=1`` from the
        #     auto-advancing progress page (no confirm / checkboxes).
        is_continue = request.form.get("continue_chunk") == "1"
        if not is_continue:
            # Per-row archive overrides ride along on the dry-run form,
            # named ``archive:<post_key>`` and validated against real,
            # non-skip post keys so a tampered form can't smuggle flags.
            valid_keys = {a["post"]["key"] for a in actions if a["target"] != "skip"}
            sel = set()
            for raw in request.form.keys():
                if raw.startswith("archive:"):
                    k = raw[len("archive:"):]
                    if k in valid_keys:
                        sel.add(k)
            stash["archive_keys"] = sorted(sel)
            # Reset the commit cursor + accumulators for a fresh run.
            stash["commit_cursor"] = 0
            stash["commit_counts"] = {}
            stash["commit_warnings"] = []
            stash["commit_rows"] = []
            wp_importer.stash_save(token, stash)
            if request.form.get("confirm") != "IMPORT":
                flash("Type IMPORT in the confirmation field to proceed.", "warning")
                return redirect(url_for("main.wp_import_dry_run", token=token, **_wp_embed_kwargs()))

        archive_keys = set(stash.get("archive_keys") or [])

        def _img_cb(url):
            # Returns ``(stored_filename, original_filename)`` so both
            # the featured-image apply step (uses stored) and the
            # inline-image rewriter (uses original to build /pub/<…>)
            # can share one callback.
            return wp_importer._download_image_full(
                url, uploaded_by=getattr(current_user, "id", None))

        # Commit ONE chunk of the plan this request, so large sites can't
        # blow the request timeout on image downloads. Slug uniqueness
        # stays correct across chunks because apply_plan re-reads existing
        # rows (incl. ones committed by earlier chunks) each call.
        cursor = int(stash.get("commit_cursor") or 0)
        chunk = actions[cursor:cursor + chunk_size]
        result = wp_importer.apply_plan(
            chunk, dry_run=False, image_cb=_img_cb,
            created_by=getattr(current_user, "id", None),
            category_meta=stash.get("category_meta") or {},
            tag_meta=stash.get("tag_meta") or {},
            archive_keys=archive_keys,
            field_mapping=stash.get("field_mapping"),
        )
        # Accumulate running totals across chunks.
        acc = stash.get("commit_counts") or {}
        for k, v in result["counts"].items():
            acc[k] = acc.get(k, 0) + v
        stash["commit_counts"] = acc
        warns = (stash.get("commit_warnings") or []) + result.get("warnings", [])
        stash["commit_warnings"] = warns[:200]
        # Keep up to 400 row details for the done-page table (single-chunk
        # imports show every row; large ones show the first 400).
        acc_rows = stash.get("commit_rows") or []
        if len(acc_rows) < 400:
            acc_rows = acc_rows + result.get("rows", [])
        stash["commit_rows"] = acc_rows[:400]
        cursor += len(chunk)
        stash["commit_cursor"] = cursor

        if cursor < total_actions:
            wp_importer.stash_save(token, stash)
            return render_template("wp_import_progress.html",
                                   token=token, done=cursor, total=total_actions,
                                   counts=acc, embed=_wp_embed())

        # All chunks done — log, clean up, show the summary.
        from . import activity
        activity.log("wp_import.commit", entity_type="wp_import",
                     summary=(f"Imported {acc.get('stories', 0)} stor{'y' if acc.get('stories', 0) == 1 else 'ies'}, "
                              f"{acc.get('announcements', 0)} announcement(s), "
                              f"{acc.get('events', 0)} event(s), "
                              f"{acc.get('blog', 0)} blog post(s) from "
                              f"{stash.get('source','?')}"))
        wp_importer.stash_delete(token)
        result_final = {"counts": acc, "rows": acc_rows[:400], "warnings": warns}
        return render_template("wp_import_done.html", result=result_final,
                               source=stash.get("source"),
                               embed=_wp_embed())

    archive_keys = set(stash.get("archive_keys") or [])
    posts_for_check = stash.get("posts") or []
    # Skip the per-post inline-image BeautifulSoup count on large previews
    # — it's the slow part and the real total is reported during import.
    big_preview = len(posts_for_check) > 400
    preview = wp_importer.apply_plan(
        actions, dry_run=True,
        category_meta=stash.get("category_meta") or {},
        tag_meta=stash.get("tag_meta") or {},
        archive_keys=archive_keys,
        field_mapping=stash.get("field_mapping"),
        count_inline=not big_preview,
    )
    stale_acf_stash = (
        (stash.get("source") == "rest")
        and bool(posts_for_check)
        and not any(p.get("acf") for p in posts_for_check)
    )
    import math
    will_chunk = total_actions > chunk_size
    batches = max(1, math.ceil(total_actions / chunk_size)) if chunk_size else 1
    return render_template("wp_import_dry_run.html",
                           token=token, stash=stash,
                           actions=actions, preview=preview,
                           archive_keys=archive_keys,
                           target_labels=wp_importer.TARGET_LABELS,
                           stale_acf_stash=stale_acf_stash,
                           will_chunk=will_chunk, batches=batches,
                           import_total=total_actions, chunk_size=chunk_size,
                           inline_count_skipped=big_preview,
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
        "format_version": 5,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "content_filename": "frontend.json",
        "assets_dir": "assets/",
        "note": ("Scoped frontend bundle (v5). Includes every "
                 "look-and-feel SiteSetting column (frontend_, footer_, "
                 "utility_bar_, header_alert_, hero_, mega_, "
                 "submission_form_, contact_form_; recipient *_to "
                 "columns excluded as deployment routing), the homepage "
                 "designation (resolved through page slug for "
                 "portability), nav, hero buttons, custom layouts "
                 "(homepage / footer / page), custom fonts, custom "
                 "icons, content pages (full schema including the "
                 "per-page spacing controls pad_top / pad_bottom / "
                 "pad_x / section_gap / block_margin_y and the per-page "
                 "Open Graph title / description / image overrides), "
                 "intergroup officers, stories (with publication "
                 "timestamp), posts (drafts and archives "
                 "included; pending submissions skipped), post slug "
                 "history, MediaItem catalog, plus every uploaded "
                 "file referenced from any of the above. Import via "
                 "the Data tab on another install to overlay the "
                 "public site without touching users, meetings, or "
                 "libraries. Older bundles (v3 / v4) still import — the "
                 "newer spacing / OG columns fall back to Page defaults "
                 "and the homepage stays whatever the destination's "
                 "auto-seed wrote."),
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
                    # Per-page Open Graph overrides (v5+ bundles). Absent
                    # in older bundles → None, which falls back to the
                    # site-wide frontend_og_* defaults at render time.
                    og_title=(p.get("og_title") or None),
                    og_description=(p.get("og_description") or None),
                    og_image_filename=(p.get("og_image_filename") or None),
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
        from datetime import date as _date, datetime as _dt
        def _parse_date(v):
            if not v: return None
            try: return _date.fromisoformat(v)
            except (TypeError, ValueError): return None
        def _parse_dt(v):
            if not v: return None
            try: return _dt.fromisoformat(v)
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
                    published_at=_parse_dt(st.get("published_at")),
                ))

        # 12. Posts — preserve source ids so the slug_history entries
        # ride along with the right entity_id. Pending submissions
        # were already filtered out on the export side. (_parse_dt / _dt
        # are defined in the Stories section above.)
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


@bp.route("/frontend/autohide-sidebar-save", methods=["POST"])
@admin_required
def frontend_autohide_sidebar_save():
    """Per-user pref — collapse the outer app sidebar to a hamburger
    while the user is inside /frontend/… Saves to User.fe_admin_autohide_sidebar
    (default True). Body.fe-admin-autohide on every Web Frontend page
    drives the existing mobile-hide CSS at all viewport widths when on."""
    current_user.fe_admin_autohide_sidebar = (
        request.form.get("fe_admin_autohide_sidebar") == "1")
    db.session.commit()
    flash("Sidebar auto-hide " + ("enabled" if current_user.fe_admin_autohide_sidebar else "disabled"), "success")
    return redirect(_safe_referrer() or url_for("main.frontend_dashboard"))


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
    # Independent dark-mode colours.
    bgd = (request.form.get("frontend_mega_bg_color_dark") or "").strip()
    fgd = (request.form.get("frontend_mega_text_color_dark") or "").strip()
    if _HEX.fullmatch(bgd): s.frontend_mega_bg_color_dark = bgd
    if _HEX.fullmatch(fgd): s.frontend_mega_text_color_dark = fgd
    try:
        bl = int(request.form.get("frontend_mega_radius_bl") or 18)
        br = int(request.form.get("frontend_mega_radius_br") or 18)
    except ValueError:
        bl, br = 18, 18
    s.frontend_mega_radius_bl = max(0, min(bl, 60))
    s.frontend_mega_radius_br = max(0, min(br, 60))
    # Optional dynamic background for the mega-menu panel (same dynbg picker
    # used by the hero / pages). normalize() gates the key against the catalog;
    # _dynbg_config_from_form bundles the overlay + colours + flags into JSON.
    from . import dynbg as _dynbg
    s.frontend_mega_bg_dynamic_key = _dynbg.normalize(request.form.get("frontend_mega_bg_dynamic_key"))
    s.frontend_mega_bg_dynbg_config_json = _dynbg_config_from_form(
        request.form, "frontend_mega_bg_dynbg_config_json")
    s.frontend_mega_bg_dynbg_dark = request.form.get("frontend_mega_bg_dynbg_dark") == "1"
    try:
        blend = int(request.form.get("frontend_mega_bg_dynbg_blend") or 100)
    except ValueError:
        blend = 100
    s.frontend_mega_bg_dynbg_blend = max(0, min(blend, 100))
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
    imgcache.note_image_change()  # bust cached icon URLs
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
    """Web Frontend overview tab. Same dashboard-widget pattern as the
    home dashboard: a draggable grid of section widgets, each gated by
    a ``fe_dash_show_<slug>`` user pref. Per-user order persisted in
    ``fe_dash_order_json`` and drained back into ``_fe_dashboard_order``.
    Visitor-metrics widget reuses the summary aggregator that backs the
    full /tspro/frontend/metrics page so the numbers match."""
    from . import visitor_metrics as _vm
    from .forms_registry import all_forms as _all_forms

    s = _get_site_setting()
    fe_order = _fe_dashboard_order(current_user)

    # Visitor metrics — same 30-day window the dedicated metrics page
    # defaults to, so the operator who's used to those numbers doesn't
    # see a different scale here. Wrap in try/except so an empty
    # VisitorEvent table or a transient DB hiccup doesn't 500 the
    # overview page.
    vm_window = 30
    try:
        vm_summary = _vm.summary(days=vm_window)
        vm_daily = _vm.daily_series(days=vm_window)
    except Exception:  # noqa: BLE001 — widget data is best-effort
        vm_summary = None
        vm_daily = []

    # Section data — kept thin so the overview render stays fast.
    recent_pages = (Page.query.order_by(Page.updated_at.desc()).limit(6).all())
    pages_count = Page.query.count()
    redirects_count = UrlRedirect.query.count()
    recent_redirects = (UrlRedirect.query
                        .order_by(UrlRedirect.created_at.desc()).limit(5).all())
    nav_count = FrontendNavItem.query.count()
    fe_forms = _all_forms()

    return render_template("frontend_dashboard.html",
                           site=s,
                           fe_dashboard_order=fe_order,
                           fe_widget_keys=FE_DASHBOARD_WIDGET_KEYS,
                           vm_window=vm_window,
                           vm_summary=vm_summary,
                           vm_daily=vm_daily,
                           recent_pages=recent_pages,
                           pages_count=pages_count,
                           redirects_count=redirects_count,
                           recent_redirects=recent_redirects,
                           nav_count=nav_count,
                           fe_forms=fe_forms)


@bp.route("/frontend/customize", methods=["POST"])
@admin_required
def fe_dashboard_customize():
    """Save the per-user Web Frontend widget visibility toggles. Same
    shape as ``dashboard_customize`` — each checkbox value=1 → True,
    missing → False."""
    for slug in FE_DASHBOARD_WIDGET_KEYS:
        col = "fe_dash_show_" + slug.replace("fe-", "").replace("-", "_")
        setattr(current_user, col, request.form.get(col) == "1")
    db.session.commit()
    flash("Web Frontend overview updated", "success")
    return redirect(url_for("main.frontend_dashboard"))


@bp.route("/frontend/order", methods=["POST"])
@admin_required
def fe_dashboard_order_save():
    """JSON POST from the drag-reorder JS — same protocol as
    ``dashboard_order_save``: ``{"order": ["fe-status", …]}``. Unknown
    keys filtered, duplicates dropped; the result is stored as a JSON
    array on ``User.fe_dash_order_json``."""
    import json
    payload = request.get_json(silent=True) or {}
    order = payload.get("order") or []
    cleaned, seen = [], set()
    for key in order:
        if isinstance(key, str) and key in FE_DASHBOARD_WIDGET_KEYS and key not in seen:
            cleaned.append(key); seen.add(key)
    current_user.fe_dash_order_json = json.dumps(cleaned)
    db.session.commit()
    return jsonify(ok=True, order=cleaned)


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
    """Forms index — two lists.

    The first lists the **built-in** forms from ``forms_registry`` (the
    legacy events/announcements Submission Form and the standalone
    Contact Form). Each registry entry declares an ``enabled_setting``
    column; the index reads its current value off SiteSetting and
    exposes an inline toggle.

    The second lists **custom forms** authored from the admin UI —
    rows in the ``custom_form`` table. Each custom form has its own
    builder page (Phase 2) and its own public URL ``/<slug>``."""
    from .forms_registry import all_forms
    s = _get_site_setting()
    forms = []
    for f in all_forms():
        enabled = True
        col = f.get("enabled_setting")
        if col:
            enabled = bool(getattr(s, col, True))
        forms.append({**f, "enabled": enabled})
    custom_forms = CustomForm.query.order_by(CustomForm.created_at.desc()).all()
    return render_template("frontend_forms.html",
                           site=s, forms=forms, custom_forms=custom_forms)


# Routes/slugs we refuse to let a CustomForm claim. Mirrors the same
# set Page.slug uniqueness already protects against — adding a new
# top-level public route should also update this list (cheap to keep
# in sync, since the page builder already references the same names).
_RESERVED_FORM_SLUGS = {
    "tspro", "static", "auth", "login", "logout", "pub", "site-branding",
    "request-access", "contact", "siteindex", "submissionform",
    "meetings", "events", "library", "stories", "blog", "announcements",
    "page-og-image", "page-content", "frontend",
}

# Field types the form builder allows. Anything else in incoming blocks
# JSON gets coerced to "text" so a poked-with-curl payload can't store
# a renderer the public template doesn't know about.
_FORM_FIELD_TYPES = {"text", "email", "phone", "textarea",
                     "select", "radio", "checkboxes", "file"}
_FORM_FIELD_TYPES_WITH_OPTIONS = {"select", "radio", "checkboxes"}


def _name_from_label(label, existing_names=()):
    """snake_case slug from a label, used as the form-field name.
    Reserved characters and runs of underscores collapsed; appends
    ``_2``, ``_3``, … on collision against ``existing_names`` so two
    fields with identical labels don't clobber each other on submit."""
    out = []
    for ch in (label or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_", "."):
            out.append("_")
    base = "".join(out).strip("_")
    while "__" in base:
        base = base.replace("__", "_")
    base = base[:60] or "field"
    if base not in existing_names:
        return base
    n = 2
    while f"{base}_{n}" in existing_names:
        n += 1
    return f"{base}_{n}"


def _parse_form_fields(form):
    """Pull the field-builder's submitted shape out of a Flask form
    object and produce the canonical blocks_json payload — a list of
    field dicts. The builder serializes its state via parallel-array
    inputs keyed by ``field_<idx>_<attr>``; this helper walks the
    indices in submission order so reorders survive the round-trip.

    Returns a Python list (caller json.dumps it onto the model).
    """
    import json as _json
    fields = []
    used_names = set()
    # The builder also posts a hidden ordering input "field_order" with
    # comma-separated indices so client-side reorders persist; fall back
    # to numeric ordering of the field_<idx>_type keys if that's absent.
    order_raw = (form.get("field_order") or "").strip()
    if order_raw:
        indices = []
        for tok in order_raw.split(","):
            tok = tok.strip()
            if tok.isdigit():
                indices.append(int(tok))
    else:
        indices = []
        for key in form.keys():
            if key.startswith("field_") and key.endswith("_type"):
                try:
                    indices.append(int(key.split("_", 2)[1]))
                except (IndexError, ValueError):
                    continue
        indices.sort()

    for idx in indices:
        ftype = (form.get(f"field_{idx}_type") or "").strip().lower()
        if ftype not in _FORM_FIELD_TYPES:
            ftype = "text"
        label = (form.get(f"field_{idx}_label") or "").strip()[:200]
        if not label:
            continue
        # Name: prefer the user-supplied value, fall back to derived
        # from label, fall back to ``field_<idx>`` so we never lose
        # the column on submit.
        manual_name = (form.get(f"field_{idx}_name") or "").strip()[:80]
        if manual_name:
            name = manual_name.lower().replace(" ", "_")
            # Ensure uniqueness even when the operator manually typed
            # a colliding name — quietly suffix.
            if name in used_names:
                n = 2
                while f"{name}_{n}" in used_names:
                    n += 1
                name = f"{name}_{n}"
        else:
            name = _name_from_label(label, used_names)
        used_names.add(name)
        placeholder = (form.get(f"field_{idx}_placeholder") or "").strip()[:200]
        # Help-text ceiling is generous (2000 chars) so the checkboxes
        # variant's markdown body has room. Non-checkbox inputs cap at
        # maxlength=500 client-side; this server cap kicks in only for
        # the multi-line checkboxes variant and as a hard upper bound
        # against curl-crafted payloads.
        helptext = (form.get(f"field_{idx}_help") or "").strip()[:2000]
        required = (form.get(f"field_{idx}_required") == "1")
        block = {
            "id": f"f-{idx}",
            "type": ftype,
            "name": name,
            "label": label,
            "required": required,
        }
        if placeholder:
            block["placeholder"] = placeholder
        if helptext:
            block["help"] = helptext
        if ftype in _FORM_FIELD_TYPES_WITH_OPTIONS:
            opts_raw = form.get(f"field_{idx}_options") or ""
            opts = [o.strip()[:200] for o in opts_raw.splitlines() if o.strip()]
            block["options"] = opts[:50]  # hard ceiling per field
        if ftype == "file":
            # Accepted file types — comma-separated list of MIME
            # types or extensions (e.g. ``.pdf,.doc,image/*``). The
            # HTML5 ``accept`` attribute drives client-side picker
            # filtering; the server-side handler enforces the same
            # list on submit so a tampered POST can't smuggle a
            # disallowed type through.
            accept = (form.get(f"field_{idx}_accept") or "").strip()[:500]
            if accept:
                block["accept"] = accept
        fields.append(block)

    return fields


def _load_form_fields(cf):
    """Decode CustomForm.blocks_json into a list of field dicts (or
    empty list when unset / malformed). Trust nothing — strip any
    field whose ``type`` isn't in the allowlist, in case a downgrade
    rolled the schema back through this row."""
    return _decode_blocks_json(cf.blocks_json or "")


def _decode_blocks_json(raw):
    """Shared blocks_json → field-list decoder. Reused by CustomForm
    and the three built-in module forms whose blocks_json columns
    live on SiteSetting."""
    import json as _json
    if not raw:
        return []
    try:
        data = _json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") not in _FORM_FIELD_TYPES:
            continue
        out.append(entry)
    return out


_MODULE_FORM_DEFAULT_SLUGS = {
    "submission_form_slug": "submissionform",
    "story_form_slug": "storyform",
    "contact_form_slug": "contact",
}


def _normalise_module_form_slug(raw, exclude_attr=None):
    """Sanitise a user-typed module-form slug and reject it when it
    would collide with another reserved or already-claimed slug.

    Returns the cleaned slug (lowercase, ``[a-z0-9-]`` only) or
    None when blank / rejected. Collisions are flashed via Flask's
    flash so the admin sees why the value didn't save, but the
    rest of the settings still persist.

    Saving the canonical built-in slug for the same column (e.g.
    typing ``submissionform`` into the Announcements/Events form's
    URL field) round-trips to None, so the DB doesn't accumulate
    redundant overrides — the built-in route handles those paths
    natively and the catch-all only kicks in for *different*
    slugs.

    ``exclude_attr`` names the SiteSetting column the caller is
    saving into so we don't conflict against the very value we're
    about to overwrite — e.g. saving ``submission_form_slug`` =
    ``story-submit`` shouldn't reject itself just because it
    previously held the same value."""
    cleaned = _slugify_form_title((raw or "").strip().lower())
    if not cleaned:
        return None
    # The canonical default round-trips to None — no alias needed,
    # the built-in route serves that path natively.
    if cleaned == _MODULE_FORM_DEFAULT_SLUGS.get(exclude_attr):
        return None
    # Reserved against the rest of the routing table.
    if cleaned in _RESERVED_FORM_SLUGS:
        flash(f"'{cleaned}' is a reserved URL — slug unchanged.", "danger")
        return _peek_existing_module_form_slug(exclude_attr)
    # Conflict against existing Pages / CustomForms.
    if Page.query.filter_by(slug=cleaned).first():
        flash(f"'{cleaned}' is taken by a Page — slug unchanged.", "danger")
        return _peek_existing_module_form_slug(exclude_attr)
    if CustomForm.query.filter_by(slug=cleaned).first():
        flash(f"'{cleaned}' is taken by a custom form — slug unchanged.", "danger")
        return _peek_existing_module_form_slug(exclude_attr)
    # Conflict against the OTHER module-form slugs. (Skipping the
    # one we're about to overwrite ourselves via ``exclude_attr``.)
    s = _get_site_setting()
    for attr in ("submission_form_slug", "story_form_slug", "contact_form_slug"):
        if attr == exclude_attr:
            continue
        if (getattr(s, attr, None) or "").strip().lower() == cleaned:
            flash(f"'{cleaned}' is taken by another module form — slug unchanged.", "danger")
            return _peek_existing_module_form_slug(exclude_attr)
    return cleaned


def _peek_existing_module_form_slug(attr):
    """Return the previously-stored value of a module-form slug
    column so the conflict-guard helper can restore it when the new
    value is rejected."""
    if not attr:
        return None
    try:
        s = _get_site_setting()
        return getattr(s, attr, None) or None
    except Exception:  # noqa: BLE001
        return None


def _default_submission_form_blocks():
    """Default field set for the Announcements/Events submission form
    — mirrors the hardcoded fields the public template currently
    renders so admins land on the existing layout in the builder
    and customize from there."""
    return [
        {"id": "f-0", "type": "text", "name": "title", "label": "Title", "required": True,
         "placeholder": "e.g. Spring serenity workshop"},
        {"id": "f-1", "type": "textarea", "name": "summary", "label": "Summary",
         "required": False, "placeholder": "Short blurb shown in link previews"},
        {"id": "f-2", "type": "textarea", "name": "body", "label": "Description",
         "required": False, "placeholder": "Full details — Markdown supported"},
        {"id": "f-3", "type": "text", "name": "event_starts_at", "label": "Event starts",
         "required": False, "placeholder": "YYYY-MM-DDTHH:MM"},
        {"id": "f-4", "type": "text", "name": "event_ends_at", "label": "Event ends",
         "required": False, "placeholder": "YYYY-MM-DDTHH:MM"},
        {"id": "f-5", "type": "text", "name": "location_name", "label": "Location name",
         "required": False, "placeholder": "Community Center · Hall B"},
        {"id": "f-6", "type": "text", "name": "location_address", "label": "Address",
         "required": False},
        {"id": "f-7", "type": "text", "name": "website_url", "label": "Event website URL",
         "required": False, "placeholder": "https://example.org"},
        {"id": "f-8", "type": "file", "name": "featured_image", "label": "Featured image",
         "required": False, "help": "PNG, JPG, or WebP — optional."},
        {"id": "f-9", "type": "text", "name": "submitter_name", "label": "Your name",
         "required": True},
        {"id": "f-10", "type": "email", "name": "submitter_email", "label": "Your email",
         "required": True},
        {"id": "f-11", "type": "phone", "name": "submitter_phone", "label": "Your phone",
         "required": False},
        {"id": "f-12", "type": "textarea", "name": "submitter_notes",
         "label": "Notes for the admin", "required": False},
    ]


def _default_story_form_blocks():
    """Default field set for the Story Submission Form — matches
    the original "Story Submission Form" custom form layout
    (Name + Email + Story + File Upload + Accept Terms)."""
    return [
        {"id": "f-0", "type": "text", "name": "submitter_name", "label": "Name",
         "required": True, "placeholder": "Name"},
        {"id": "f-1", "type": "email", "name": "submitter_email", "label": "Email",
         "required": False},
        {"id": "f-2", "type": "textarea", "name": "body", "label": "Story",
         "required": True, "placeholder": "Type/Paste your story here"},
        {"id": "f-3", "type": "file", "name": "attachment", "label": "File Upload",
         "required": False, "placeholder": "Upload a file (PDF, DOC)",
         "help": "If your story is in a file, optionally upload it here instead of pasting it"},
        {"id": "f-4", "type": "checkboxes", "name": "accept_terms",
         "label": "Accept Terms", "required": True,
         "placeholder": "Please read and accept the terms below:",
         "help": "",
         "options": ["I accept the terms below"]},
    ]


def _default_contact_form_blocks():
    """Default field set for the Contact Form — mirrors the existing
    hardcoded fields on /contact (name, email, optional subject /
    phone, and message)."""
    return [
        {"id": "f-0", "type": "text", "name": "name", "label": "Your name",
         "required": True},
        {"id": "f-1", "type": "email", "name": "email", "label": "Email",
         "required": True},
        {"id": "f-2", "type": "text", "name": "subject", "label": "Subject",
         "required": False},
        {"id": "f-3", "type": "phone", "name": "phone", "label": "Phone",
         "required": False},
        {"id": "f-4", "type": "textarea", "name": "message", "label": "Message",
         "required": True, "placeholder": "How can we help?"},
    ]


def _resolve_module_form_fields(saved_raw, default_factory):
    """Return the field list to feed the builder on a module form's
    settings page. Saved overrides win when present; otherwise the
    module's default blocks load so the admin sees the form's
    current shape in the editor and can tweak from there."""
    saved = _decode_blocks_json(saved_raw)
    return saved if saved else default_factory()


def _slugify_form_title(title):
    """Lowercase + hyphen-separated slug from a title. Strips characters
    outside ``[a-z0-9-]`` and collapses runs of dashes. Mirrors the
    slug derivation Pages already uses so the two namespaces feel
    consistent — this is the slug an operator gets if they leave the
    slug field blank on create."""
    out = []
    for ch in (title or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("-")
    s = "".join(out).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s[:120] or "form"


@bp.route("/frontend/forms/custom/new", methods=["POST"])
@admin_required
def frontend_custom_form_new():
    """Create a CustomForm stub with placeholder title + slug and drop
    the operator straight onto its edit page. The previous variant
    asked for title + slug inline on the index — the new flow gives
    the builder a single zero-input "+ Add form" button and treats
    naming + URL as the first thing to do on the edit page, alongside
    field building.

    The stub starts disabled so the placeholder URL doesn't get
    surfaced to the public before the operator has filled in fields.
    Slug is auto-suffixed (``untitled-form``, ``untitled-form-2``, …)
    so two quick clicks don't collide on the slug uniqueness index."""
    base_slug = "untitled-form"
    slug = base_slug
    suffix = 2
    while CustomForm.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    title = "Untitled form" if slug == base_slug else f"Untitled form {suffix - 1}"
    cf = CustomForm(slug=slug, title=title, enabled=False)
    db.session.add(cf)
    db.session.commit()
    return redirect(url_for("main.frontend_custom_form_edit", form_id=cf.id))


@bp.route("/frontend/forms/custom/<int:form_id>/edit", methods=["GET", "POST"])
@admin_required
def frontend_custom_form_edit(form_id):
    """Phase 1 stub for the custom-form edit page. Round-trips title,
    slug, recipients, thank-you message, and redirect URL so the
    operator can verify the row exists and basic settings persist.
    Phase 2 layers the drag-and-drop field builder on top of this same
    page."""
    cf = db.session.get(CustomForm, form_id) or abort(404)
    if request.method == "POST":
        cf.title = (request.form.get("title") or cf.title).strip()
        new_slug = _slugify_form_title((request.form.get("slug") or cf.slug).strip().lower())
        if new_slug != cf.slug:
            # Re-run conflict guard on slug change.
            if (new_slug in _RESERVED_FORM_SLUGS
                    or Page.query.filter_by(slug=new_slug).first()
                    or CustomForm.query.filter(CustomForm.slug == new_slug,
                                                CustomForm.id != cf.id).first()):
                flash(f"'{new_slug}' is taken or reserved — slug unchanged.", "danger")
            else:
                cf.slug = new_slug
        cf.description = (request.form.get("description") or "").strip() or None
        cf.recipients_csv = (request.form.get("recipients_csv") or "").strip() or None
        cf.redirect_url = (request.form.get("redirect_url") or "").strip() or None
        cf.thank_you_message = (request.form.get("thank_you_message") or "").strip() or None
        cf.enabled = request.form.get("enabled") == "1"
        # Field builder payload — the page's JS serialises into
        # ``field_<idx>_<attr>`` inputs + a ``field_order`` index list.
        # We always rebuild blocks_json from the incoming form so an
        # empty builder cleanly clears the previous fields.
        import json as _json
        fields = _parse_form_fields(request.form)
        cf.blocks_json = _json.dumps(fields) if fields else None
        db.session.commit()
        flash("Form settings saved.", "success")
        return redirect(url_for("main.frontend_custom_form_edit", form_id=cf.id))
    return render_template("frontend_custom_form_edit.html",
                           form=cf,
                           fields=_load_form_fields(cf),
                           field_types=sorted(_FORM_FIELD_TYPES))


def _summarise_form_submission(sub):
    """Build a per-row preview dict for the Form Submissions list.

    Walks the parent CustomForm's blocks_json to find the right fields
    by type + name heuristics (rather than guessing from the payload
    alone, which has snake_case field-names not labels). Returns:

      display_name — best guess at the submitter (name-type fields,
                     then email local-part, then "Anonymous"). Drives
                     the row's avatar initial + bold title.
      email        — the first email-field value, when present;
                     surfaces as a click-to-mail mailto link.
      phone        — first phone-field value, used as secondary contact.
      headline     — a short snippet from a subject / message / textarea
                     field. Long values are trimmed to ~140 chars.
      field_count  — how many fields the submitter actually answered
                     (non-empty values), used for the "N fields" badge.
      file_count   — number of file attachments (drives the paperclip
                     pill).
    """
    import json as _json
    try:
        payload = _json.loads(sub.payload_json or "{}")
    except (ValueError, TypeError):
        payload = {}
    fvals = payload.get("fields") or {}
    files = payload.get("files") or {}

    cf = sub.form
    blocks = []
    if cf and cf.blocks_json:
        try:
            blocks = _json.loads(cf.blocks_json)
        except (ValueError, TypeError):
            blocks = []
    if not isinstance(blocks, list):
        blocks = []

    # Heuristic match on the field NAME (which is auto-derived from
    # the operator's label via _name_from_label, so "Your Name" →
    # "your_name", "Full name" → "full_name", etc.). Compose a list of
    # name substrings to look for in priority order.
    NAME_HINTS = ("full_name", "your_name", "submitter_name", "name", "contact_name")
    PHONE_HINTS = ("phone", "tel", "mobile")
    SUBJECT_HINTS = ("subject", "title", "topic")
    BODY_HINTS = ("message", "comments", "body", "details", "description", "notes")

    def _first_by(types=None, name_hints=()):
        """First field in declared order whose type is in ``types`` (when set)
        and whose name CONTAINS one of ``name_hints`` (when set). Returns
        the (block, value) pair, or (None, None)."""
        for block in blocks:
            if not isinstance(block, dict):
                continue
            bn = (block.get("name") or "").lower()
            if not bn:
                continue
            if types and block.get("type") not in types:
                continue
            if name_hints and not any(h in bn for h in name_hints):
                continue
            val = fvals.get(bn)
            if val:
                return block, val
        return None, None

    # display_name resolution order:
    # 1. text field with "name" in the slug
    # 2. local part of any email field
    # 3. "Anonymous"
    _, name_val = _first_by(types={"text"}, name_hints=NAME_HINTS)
    _, email_val = _first_by(types={"email"})
    _, phone_val = _first_by(types={"text", "phone"}, name_hints=PHONE_HINTS)

    if name_val:
        display_name = str(name_val).strip()
    elif email_val:
        display_name = str(email_val).split("@", 1)[0]
    else:
        display_name = "Anonymous"

    # headline: prefer subject-like field, then textarea body-like field,
    # then any textarea.
    _, headline = _first_by(types={"text", "textarea"}, name_hints=SUBJECT_HINTS)
    if not headline:
        _, headline = _first_by(types={"textarea"}, name_hints=BODY_HINTS)
    if not headline:
        _, headline = _first_by(types={"textarea"})
    if headline:
        headline = str(headline).strip().replace("\n", " ")
        if len(headline) > 140:
            headline = headline[:137].rstrip() + "…"

    # Field count: count non-empty payload values, including
    # checkbox arrays (one entry is "answered", empty arrays aren't).
    answered = 0
    for v in fvals.values():
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            if v: answered += 1
        elif str(v).strip():
            answered += 1

    return {
        "display_name": display_name,
        "email": str(email_val).strip() if email_val else None,
        "phone": str(phone_val).strip() if phone_val else None,
        "headline": headline,
        "field_count": answered,
        "file_count": len(files),
    }


@bp.route("/frontend/forms/submissions")
@admin_required
def frontend_form_submissions():
    """List of every FormSubmission across every CustomForm, newest
    first. Filterable by form via ``?form=<id>``. Per-submission row
    surfaces the submitter's name (or email local-part / "Anonymous"
    when no name field exists), inline contact links, a short
    headline from the first subject/textarea field, and badges for
    field count + file-attachment count."""
    form_id_raw = (request.args.get("form") or "").strip()
    form_id = int(form_id_raw) if form_id_raw.isdigit() else None
    q = FormSubmission.query
    if form_id is not None:
        q = q.filter_by(form_id=form_id)
    submissions = q.order_by(FormSubmission.created_at.desc()).limit(200).all()
    forms = CustomForm.query.order_by(CustomForm.title).all()
    # Pre-compute per-row preview dicts so the template stays declarative
    # (no payload JSON parsing in Jinja). Mapping by id keeps the lookup
    # cheap inside the loop.
    previews = {sub.id: _summarise_form_submission(sub) for sub in submissions}
    return render_template("frontend_form_submissions.html",
                           submissions=submissions,
                           previews=previews,
                           forms=forms,
                           selected_form_id=form_id)


@bp.route("/frontend/forms/submissions/<int:sub_id>")
@admin_required
def frontend_form_submission_detail(sub_id):
    """Per-submission detail view. Pairs each value in the submission's
    payload with the field label from the form's blocks_json (since
    submitter never saw the raw field names — labels are what the
    operator authored)."""
    import json as _json
    sub = db.session.get(FormSubmission, sub_id) or abort(404)
    cf = sub.form
    fields = _load_form_fields(cf) if cf else []
    label_for = {f["name"]: f["label"] for f in fields if isinstance(f, dict) and "name" in f}
    try:
        payload = _json.loads(sub.payload_json or "{}")
    except (ValueError, TypeError):
        payload = {}
    return render_template("frontend_form_submission_detail.html",
                           sub=sub, cf=cf, fields=fields,
                           payload=payload, label_for=label_for)


@bp.route("/frontend/forms/submissions/<int:sub_id>/delete", methods=["POST"])
@admin_required
def frontend_form_submission_delete(sub_id):
    sub = db.session.get(FormSubmission, sub_id) or abort(404)
    form_id = sub.form_id
    db.session.delete(sub)
    db.session.commit()
    flash("Submission deleted.", "success")
    return redirect(url_for("main.frontend_form_submissions", form=form_id))


@bp.route("/frontend/forms/submissions/<int:sub_id>/import-to-stories", methods=["POST"])
@admin_required
def frontend_form_submission_import_to_story(sub_id):
    """Promote a legacy ``FormSubmission`` row into a pending-review
    ``Story`` row so it lands in the Stories admin's Pending tab.

    Used to migrate existing story submissions that came in through
    the old CustomForm → FormSubmission pipeline before the dedicated
    /storyform route shipped. Walks the parent CustomForm's
    ``blocks_json`` to pick out title / summary / body / author /
    submitter contact fields by name+type heuristics (same logic
    ``_summarise_form_submission`` uses for list previews), copies
    them onto a new Story row with ``is_pending_review=True``, and
    deletes the FormSubmission so it doesn't double-track.

    Any file uploads attached to the submission ride along: the first
    image-typed file becomes the story's featured image, the first
    non-image file becomes the submission attachment for download.
    The on-disk files themselves aren't copied — both Story and
    FormSubmission storage live under the same ``UPLOAD_FOLDER``,
    so we just hand off the stored filename to the Story row.
    """
    import json as _json
    sub = db.session.get(FormSubmission, sub_id) or abort(404)
    try:
        payload = _json.loads(sub.payload_json or "{}")
    except (ValueError, TypeError):
        payload = {}
    fvals = payload.get("fields") or {}
    files = payload.get("files") or {}

    cf = sub.form
    blocks = []
    if cf and cf.blocks_json:
        try:
            blocks = _json.loads(cf.blocks_json)
        except (ValueError, TypeError):
            blocks = []
    if not isinstance(blocks, list):
        blocks = []

    # Field name heuristics — mirrors _summarise_form_submission's hint
    # lists so the import picks the same "obvious" fields the list
    # preview already calls out.
    TITLE_HINTS = ("title", "subject", "headline", "story_title")
    SUMMARY_HINTS = ("summary", "blurb", "excerpt", "headline")
    BODY_HINTS = ("body", "story", "message", "content", "details", "narrative")
    NAME_HINTS = ("full_name", "your_name", "submitter_name", "name")
    AUTHOR_HINTS = ("author", "byline", "pen_name", "display_name")
    PHONE_HINTS = ("phone", "tel", "mobile")
    NOTES_HINTS = ("notes", "comments", "for_editor")

    def _first(types=None, name_hints=()):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            bn = (block.get("name") or "").lower()
            if not bn:
                continue
            if types and block.get("type") not in types:
                continue
            if name_hints and not any(h in bn for h in name_hints):
                continue
            val = fvals.get(bn)
            if val:
                return val
        return None

    def _coerce(val):
        if val is None:
            return None
        if isinstance(val, (list, tuple)):
            return ", ".join(str(x) for x in val if x)
        return str(val).strip() or None

    title = _coerce(_first(name_hints=TITLE_HINTS)) or "Imported story submission"
    # Body falls back to the longest text-area value in the payload
    # so submissions whose form named its main field "your_story" or
    # "tell_us_more" still get something useful. The same fallback
    # logic is used by the list-preview headline picker, but here we
    # take the whole value instead of a truncated snippet.
    body = _coerce(_first(types={"textarea"}, name_hints=BODY_HINTS))
    if not body:
        # Pick the longest textarea answer across the whole payload as
        # a last resort. Sorted by length descending so the most
        # substantial answer wins.
        ta_vals = []
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "textarea":
                continue
            bn = (block.get("name") or "").lower()
            v = fvals.get(bn)
            if v and isinstance(v, str):
                ta_vals.append(v)
        if ta_vals:
            body = max(ta_vals, key=len).strip() or None

    summary = _coerce(_first(name_hints=SUMMARY_HINTS))
    author_name = _coerce(_first(name_hints=AUTHOR_HINTS))
    submitter_name = _coerce(_first(types={"text"}, name_hints=NAME_HINTS)) \
        or author_name
    submitter_email = _coerce(_first(types={"email"}))
    submitter_phone = _coerce(_first(name_hints=PHONE_HINTS))
    submitter_notes = _coerce(_first(name_hints=NOTES_HINTS))

    # Walk the uploaded files block by block so the first image-typed
    # file becomes the featured image and the first non-image file
    # becomes the downloadable attachment. The stored file lives on
    # disk under UPLOAD_FOLDER; we hand its stored name to the Story
    # row directly so admin downloads stay a straight send_from_dir.
    IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
    featured = None
    attachment = None
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "file":
            continue
        bn = (block.get("name") or "").lower()
        info = files.get(bn) or {}
        stored = (info.get("stored") or "").strip()
        original = (info.get("original") or "").strip()
        if not stored:
            continue
        ext = ("." + stored.rsplit(".", 1)[-1].lower()) if "." in stored else ""
        if ext in IMAGE_EXTS and featured is None:
            featured = stored
        elif attachment is None:
            attachment = (stored, original)
    # Also consider any extra files (block-less) in payload.files.
    for bn, info in files.items():
        if not isinstance(info, dict):
            continue
        stored = (info.get("stored") or "").strip()
        original = (info.get("original") or "").strip()
        if not stored:
            continue
        ext = ("." + stored.rsplit(".", 1)[-1].lower()) if "." in stored else ""
        if ext in IMAGE_EXTS and featured is None:
            featured = stored
        elif attachment is None:
            attachment = (stored, original)

    s = Story()
    s.title = title[:255]
    s.summary = (summary or "")[:2000] or None
    s.body = body or None
    s.author_name = (author_name or "")[:120] or None
    s.is_draft = False
    s.is_archived = False
    s.is_pending_review = True
    s.submitter_name = (submitter_name or "")[:120] or None
    s.submitter_email = (submitter_email or "")[:255] or None
    s.submitter_phone = (submitter_phone or "")[:64] or None
    s.submitter_notes = (submitter_notes or "")[:4000] or None
    # Preserve the original submission timestamp so the admin sees
    # *when* this came in, not when it was imported.
    s.submitted_at = sub.created_at
    if featured:
        s.featured_image_filename = featured
    if attachment:
        stored, original = attachment
        s.submission_attachment_filename = stored
        s.submission_attachment_original = original[:500] if original else stored

    db.session.add(s)
    # Drop the FormSubmission so it doesn't double-track. The on-disk
    # files survive because they're now referenced by the Story row.
    form_id = sub.form_id
    db.session.delete(sub)
    db.session.commit()

    from . import activity
    activity.log("story.import_from_form_submission",
                 entity_type="story", entity_id=s.id,
                 summary=f"Imported story submission “{s.title}” from form #{form_id}")
    flash("Submission imported to the Stories holding tank. Review and edit before publishing.", "success")
    return redirect(url_for("main.stories", show="pending"))


@bp.route("/frontend/forms/custom/<int:form_id>/delete", methods=["POST"])
@admin_required
def frontend_custom_form_delete(form_id):
    cf = db.session.get(CustomForm, form_id) or abort(404)
    title = cf.title
    db.session.delete(cf)
    db.session.commit()
    flash(f"Form '{title}' deleted.", "success")
    return redirect(url_for("main.frontend_forms"))


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
        s.submission_form_slug = _normalise_module_form_slug(
            request.form.get("submission_form_slug"), exclude_attr="submission_form_slug")
        # Field builder — same shape CustomForm uses. When the
        # admin hasn't touched the builder we leave the column NULL
        # so the public form falls back to its built-in defaults.
        import json as _json
        fields = _parse_form_fields(request.form)
        s.submission_form_blocks_json = _json.dumps(fields) if fields else None
        db.session.commit()
        flash("Announcements/Events form settings saved", "success")
        return redirect(url_for("main.frontend_form_submission"))
    return render_template("frontend_form_submission.html", site=s,
                           form_fields=_resolve_module_form_fields(
                               s.submission_form_blocks_json,
                               _default_submission_form_blocks),
                           field_types=sorted(_FORM_FIELD_TYPES))


@bp.route("/frontend/forms/story", methods=["GET", "POST"])
@admin_required
def frontend_form_story():
    """Settings page for the public Story Submission Form. Mirrors
    the Submission Form settings page — toggle, recipient list, copy
    overrides, submit button label."""
    s = _get_site_setting()
    if request.method == "POST":
        s.story_form_enabled = request.form.get("story_form_enabled") == "1"
        s.story_form_to = (request.form.get("story_form_to") or "").strip()[:500] or None
        s.story_form_heading = (request.form.get("story_form_heading") or "").strip()[:200] or None
        s.story_form_subheading = (request.form.get("story_form_subheading") or "").strip()[:500] or None
        s.story_form_intro = (request.form.get("story_form_intro") or "").strip() or None
        s.story_form_success_message = (request.form.get("story_form_success_message") or "").strip()[:500] or None
        s.story_form_submit_label = (request.form.get("story_form_submit_label") or "").strip()[:100] or None
        # Per-field label / placeholder / help overrides — admins can
        # tweak the wording of each field without touching templates.
        s.story_form_name_label = (request.form.get("story_form_name_label") or "").strip()[:120] or None
        s.story_form_email_label = (request.form.get("story_form_email_label") or "").strip()[:120] or None
        s.story_form_email_required = request.form.get("story_form_email_required") == "1"
        s.story_form_story_label = (request.form.get("story_form_story_label") or "").strip()[:120] or None
        s.story_form_story_placeholder = (request.form.get("story_form_story_placeholder") or "").strip()[:200] or None
        s.story_form_file_label = (request.form.get("story_form_file_label") or "").strip()[:120] or None
        s.story_form_file_help = (request.form.get("story_form_file_help") or "").strip() or None
        s.story_form_terms_label = (request.form.get("story_form_terms_label") or "").strip()[:120] or None
        s.story_form_terms_intro = (request.form.get("story_form_terms_intro") or "").strip()[:200] or None
        s.story_form_terms_text = (request.form.get("story_form_terms_text") or "").strip() or None
        s.story_form_terms_checkbox_label = (request.form.get("story_form_terms_checkbox_label") or "").strip()[:200] or None
        s.story_form_slug = _normalise_module_form_slug(
            request.form.get("story_form_slug"), exclude_attr="story_form_slug")
        import json as _json
        fields = _parse_form_fields(request.form)
        s.story_form_blocks_json = _json.dumps(fields) if fields else None
        db.session.commit()
        flash("Story form settings saved", "success")
        return redirect(url_for("main.frontend_form_story"))
    return render_template("frontend_form_story.html", site=s,
                           form_fields=_resolve_module_form_fields(
                               s.story_form_blocks_json,
                               _default_story_form_blocks),
                           field_types=sorted(_FORM_FIELD_TYPES))


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
        s.contact_form_slug = _normalise_module_form_slug(
            request.form.get("contact_form_slug"), exclude_attr="contact_form_slug")
        import json as _json
        fields = _parse_form_fields(request.form)
        s.contact_form_blocks_json = _json.dumps(fields) if fields else None
        db.session.commit()
        flash("Contact form settings saved", "success")
        return redirect(url_for("main.frontend_form_contact"))
    return render_template("frontend_form_contact.html", site=s,
                           form_fields=_resolve_module_form_fields(
                               s.contact_form_blocks_json,
                               _default_contact_form_blocks),
                           field_types=sorted(_FORM_FIELD_TYPES))


@bp.route("/frontend/forms/recovery-contacts", methods=["GET", "POST"])
@admin_required
def frontend_form_recovery_contacts():
    """Settings page for the public Recovery Contacts form. GET renders the
    config form; POST persists the form-mechanic recovery_contacts_*
    SiteSetting columns (visibility, admin alerts + recipient, submit-button
    label, and the success message). Page look-and-feel — heading /
    subheading / intro and container width — lives on the Templates page
    (``frontend_recovery_contacts_template_save``) next to every other page
    template, so it's intentionally NOT written here (saving this form must
    not clobber those values). The entries themselves are reviewed/approved
    on the dedicated Recovery Contacts admin section
    (``main.recovery_contacts``) — this page is configuration only."""
    s = _get_site_setting()
    if request.method == "POST":
        s.recovery_contacts_enabled = request.form.get("recovery_contacts_enabled") == "1"
        s.recovery_contacts_email_alerts = request.form.get("recovery_contacts_email_alerts") == "1"
        s.recovery_contacts_removal_alerts = request.form.get("recovery_contacts_removal_alerts") == "1"
        s.recovery_contacts_to = (request.form.get("recovery_contacts_to") or "").strip()[:500] or None
        s.recovery_contacts_submit_label = (request.form.get("recovery_contacts_submit_label") or "").strip()[:100] or None
        s.recovery_contacts_success_message = (request.form.get("recovery_contacts_success_message") or "").strip()[:500] or None
        db.session.commit()
        flash("Recovery Contacts settings saved", "success")
        return redirect(url_for("main.frontend_form_recovery_contacts"))
    return render_template("frontend_form_recovery_contacts.html", site=s)


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


@bp.route("/frontend/recovery-contacts-template/save", methods=["POST"])
@admin_required
def frontend_recovery_contacts_template_save():
    """Persist the page-level look-and-feel for the public Recovery
    Contacts page (/contactlist): heading / subheading / Markdown intro
    plus the container-width controls. Mirrors
    ``frontend_contact_template_save`` — the Forms admin keeps the
    form-mechanic settings (visibility, alerts, recipient, submit label,
    success message, bot protection); this surface is purely about how
    the page looks, so it lives next to every other page template."""
    s = _get_site_setting()
    s.recovery_contacts_heading = (request.form.get("recovery_contacts_heading") or "").strip()[:200] or None
    s.recovery_contacts_subheading = (request.form.get("recovery_contacts_subheading") or "").strip()[:500] or None
    s.recovery_contacts_intro = (request.form.get("recovery_contacts_intro") or "").strip() or None
    # Container-width controls — same shape/bounds as the contact +
    # list endpoints. Width mode falls through to the model default on
    # an out-of-range value; numeric inputs clamp to the schema bounds.
    width = (request.form.get("recovery_contacts_width_mode") or "").strip()
    if width in ("boxed", "full"):
        s.recovery_contacts_width_mode = width
    if "recovery_contacts_max_width" in request.form:
        try:
            max_w = int(request.form.get("recovery_contacts_max_width") or 1160)
        except ValueError:
            max_w = 1160
        s.recovery_contacts_max_width = max(640, min(2400, max_w))
    if "recovery_contacts_padding_pct" in request.form:
        try:
            pad = int(request.form.get("recovery_contacts_padding_pct") or 5)
        except ValueError:
            pad = 5
        s.recovery_contacts_padding_pct = max(0, min(20, pad))
    db.session.commit()
    flash("Recovery Contacts page saved", "success")
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


def _normalize_redirect_pair(src, tgt):
    """Shared validation for both the full Redirects admin page and the
    inline Watchtower 404s modal. Returns ``(src, tgt, error)`` where
    ``error`` is ``None`` on success or a user-facing message on
    failure. Wildcard rules: source may end in ``/*`` (matches any
    path under that prefix and lands them all on the literal target);
    ``*`` is not allowed anywhere else in either field."""
    src = (src or "").strip()
    tgt = (tgt or "").strip()
    if not src or not tgt:
        return src, tgt, "Both source and target are required."
    if not src.startswith("/"):
        src = "/" + src
    src = src[:2000]
    tgt = tgt[:2000]
    # Wildcard validation. The only place `*` is allowed is the very
    # end of the source as `/*`. No wildcards in the target — every
    # match lands on the literal URL.
    if "*" in tgt:
        return src, tgt, "Wildcards (*) aren't allowed in the target."
    is_wild = src.endswith("/*")
    if "*" in src and not is_wild:
        return src, tgt, ("Wildcard must be a trailing /*, e.g. "
                          "/swag/* — * isn't allowed elsewhere.")
    if is_wild:
        prefix = src[:-2]  # strip "/*"
        if not prefix or prefix == "":
            return src, tgt, "Wildcard needs at least one path segment, e.g. /swag/*."
        # A target that falls under the wildcard prefix would create
        # an infinite redirect loop (every retry re-matches).
        if tgt == prefix or tgt.startswith(prefix + "/"):
            return src, tgt, (f"Target falls under the wildcard prefix "
                              f"({prefix}/) — that would loop forever.")
    if src == tgt:
        return src, tgt, "Source and target can't be the same path."
    return src, tgt, None


@bp.route("/frontend/redirects/save", methods=["POST"])
@admin_required
def frontend_redirects_save():
    """Create OR update a redirect. The presence of `redirect_id`
    decides which path: empty → create, set → update by id."""
    rid_raw = (request.form.get("redirect_id") or "").strip()
    src, tgt, err = _normalize_redirect_pair(
        request.form.get("source_path"), request.form.get("target_path"))
    if err:
        flash(err, "danger")
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


# ── Web Frontend → Caching ────────────────────────────────────────────
# Cache-lifetime presets offered in the panel (label, seconds). Custom
# values from a tampered POST are clamped, not trusted.
_CACHE_TTL_PRESETS = (
    ("1 hour", 3600),
    ("6 hours", 21600),
    ("12 hours", 43200),
    ("1 day", 86400),
    ("7 days", 604800),
    ("30 days", 2592000),
    ("1 year", 31536000),
)
_CACHE_TTL_MIN = 60
_CACHE_TTL_MAX = 31536000


def _coerce_ttl(raw, default):
    """Parse a max-age form value to a sane integer second count."""
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(_CACHE_TTL_MIN, min(_CACHE_TTL_MAX, v))


def _fmt_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


@bp.route("/frontend/caching")
@admin_required
def frontend_caching():
    """Frontend asset caching control panel. See app/imgcache.py."""
    s = _get_site_setting()
    thumb_count, thumb_bytes = imgcache.thumb_stats()
    return render_template(
        "frontend_caching.html", site=s,
        ttl_presets=_CACHE_TTL_PRESETS,
        thumb_count=thumb_count,
        thumb_size=_fmt_bytes(thumb_bytes),
        static_token=imgcache.static_token(),
    )


@bp.route("/frontend/caching/save", methods=["POST"])
@admin_required
def frontend_caching_save():
    """Persist caching toggles/lifetimes. Booleans default off when their
    checkbox is absent from the POST."""
    s = _get_site_setting()
    s.media_cache_enabled = request.form.get("media_cache_enabled") == "1"
    s.media_cache_immutable = request.form.get("media_cache_immutable") == "1"
    s.media_cache_static_assets = request.form.get("media_cache_static_assets") == "1"
    s.media_cache_autobump = request.form.get("media_cache_autobump") == "1"
    s.media_cache_max_age = _coerce_ttl(
        request.form.get("media_cache_max_age"), s.media_cache_max_age or 604800)
    s.media_cache_static_max_age = _coerce_ttl(
        request.form.get("media_cache_static_max_age"), s.media_cache_static_max_age or 2592000)
    db.session.commit()
    imgcache.invalidate()
    flash("Caching settings saved", "success")
    return redirect(url_for("main.frontend_caching"))


@bp.route("/frontend/caching/clear", methods=["POST"])
@admin_required
def frontend_caching_clear():
    """Force every visitor to refetch images now by advancing the bust
    token (a new ?v= on every image URL)."""
    imgcache.clear_cache()
    flash("Image cache cleared — visitors will refetch images on their next visit.", "success")
    return redirect(url_for("main.frontend_caching"))


@bp.route("/frontend/caching/thumbnails/clear", methods=["POST"])
@admin_required
def frontend_caching_thumbnails_clear():
    """Delete generated thumbnail files from disk; they regenerate lazily
    on the next request."""
    removed = imgcache.clear_thumbnails()
    flash(f"Cleared {removed} generated thumbnail file{'' if removed == 1 else 's'}.", "success")
    return redirect(url_for("main.frontend_caching"))


# ── Cookie & privacy compliance ───────────────────────────────────────

_COOKIE_MODES = ("notice", "consent", "strict")
_COOKIE_POSITIONS = ("bottom-bar", "bottom-left", "bottom-right", "modal")


@bp.route("/frontend/cookie-compliance")
@admin_required
def frontend_cookie_compliance():
    """Admin page for the cookie + privacy compliance banner. Lets the
    admin enable the module, pick a prompt mode, customise the banner
    copy + position, link a privacy policy (existing Page OR external
    URL), and one-click apply a regional preset (GDPR / CCPA / generic).
    See ``app/cookie_compliance.py`` for region inference + presets +
    starter policy templates."""
    from . import cookie_compliance as cc
    s = _get_site_setting()
    pages = (Page.query.filter(Page.is_published.is_(True))
             .order_by(Page.title.asc()).all())
    return render_template(
        "frontend_cookie_compliance.html",
        site=s, pages=pages,
        presets=cc.REGION_PRESETS,
        policy_templates=[{"key": k, "label": v[1]}
                          for k, v in cc.POLICY_TEMPLATES.items()],
        modes=_COOKIE_MODES,
        positions=_COOKIE_POSITIONS,
    )


@bp.route("/frontend/cookie-compliance/save", methods=["POST"])
@admin_required
def frontend_cookie_compliance_save():
    """Persist the cookie-compliance settings. Booleans default off when
    their checkbox is absent from the POST. Enum fields are validated
    against the small whitelists above; anything else falls back to the
    current value so a bad form post can't poison the DB."""
    s = _get_site_setting()
    s.cookie_compliance_enabled = request.form.get("cookie_compliance_enabled") == "1"
    mode = (request.form.get("cookie_compliance_mode") or "").strip()
    if mode in _COOKIE_MODES:
        s.cookie_compliance_mode = mode
    s.cookie_compliance_auto_region = request.form.get("cookie_compliance_auto_region") == "1"
    pos = (request.form.get("cookie_compliance_position") or "").strip()
    if pos in _COOKIE_POSITIONS:
        s.cookie_compliance_position = pos
    s.cookie_compliance_title = (request.form.get("cookie_compliance_title") or "").strip()[:200] or None
    s.cookie_compliance_body = (request.form.get("cookie_compliance_body") or "").strip() or None
    s.cookie_compliance_accept_label = (request.form.get("cookie_compliance_accept_label") or "").strip()[:60] or None
    s.cookie_compliance_reject_label = (request.form.get("cookie_compliance_reject_label") or "").strip()[:60] or None
    s.cookie_compliance_more_label = (request.form.get("cookie_compliance_more_label") or "").strip()[:60] or None
    # Privacy policy linkage: either pick an existing Page or paste an
    # external URL. We allow both stored simultaneously (admin might want
    # to switch back) but the banner prefers the internal Page when both
    # are set — internal links survive site moves better.
    page_id_raw = (request.form.get("cookie_compliance_policy_page_id") or "").strip()
    if page_id_raw:
        try:
            pid = int(page_id_raw)
            if Page.query.get(pid):
                s.cookie_compliance_policy_page_id = pid
        except ValueError:
            pass
    else:
        s.cookie_compliance_policy_page_id = None
    ext = (request.form.get("cookie_compliance_policy_external_url") or "").strip()
    s.cookie_compliance_policy_external_url = ext[:500] or None
    # Remember-days. Clamp to sane range — 0 disables persistence (banner
    # re-prompts every page load, useful for testing); 730 (2 years) is
    # the upper limit most regulators consider acceptable.
    try:
        days = int(request.form.get("cookie_compliance_remember_days") or "365")
    except ValueError:
        days = 365
    s.cookie_compliance_remember_days = max(0, min(730, days))
    db.session.commit()
    flash("Cookie compliance settings saved.", "success")
    return redirect(url_for("main.frontend_cookie_compliance"))


@bp.route("/frontend/cookie-compliance/apply-preset", methods=["POST"])
@admin_required
def frontend_cookie_compliance_apply_preset():
    """Stamp one of the region presets onto the current settings (mode,
    auto-region flag, banner copy, position). Doesn't touch the
    enabled flag or the policy linkage — those are intentional choices
    the admin makes separately. Always followed by a hand-edit so the
    admin can tailor wording to their own voice."""
    from . import cookie_compliance as cc
    key = (request.form.get("preset") or "").strip()
    try:
        preset = cc.get_preset(key)
    except KeyError:
        flash("Unknown preset.", "danger")
        return redirect(url_for("main.frontend_cookie_compliance"))
    s = _get_site_setting()
    for col, val in preset["settings"].items():
        setattr(s, col, val)
    db.session.commit()
    flash(f"Applied preset: {preset['label']}. Review the copy and click Save.", "success")
    return redirect(url_for("main.frontend_cookie_compliance"))


@bp.route("/frontend/cookie-compliance/generate-policy", methods=["POST"])
@admin_required
def frontend_cookie_compliance_generate_policy():
    """Create a new Page seeded with one of the starter policy templates
    and link it as the site's privacy policy. The admin will want to
    edit the placeholders (organisation name, contact email, retention
    periods) afterwards — the flash message says so."""
    from . import cookie_compliance as cc
    key = (request.form.get("template") or "").strip()
    if key not in cc.POLICY_TEMPLATES:
        flash("Unknown policy template.", "danger")
        return redirect(url_for("main.frontend_cookie_compliance"))
    s = _get_site_setting()
    site_name = (s.frontend_title or "").strip() or None
    title, slug_seed, blocks_json = cc.generate_policy(key, site_name=site_name)
    # Slug uniqueness — bump with -2, -3, ... until no Page owns it.
    base_slug = _normalize_slug(slug_seed) or "privacy-policy"
    slug = base_slug
    n = 2
    while Page.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{n}"
        n += 1
    page = Page(
        slug=slug,
        title=title,
        blocks_json=blocks_json,
        is_published=True,
        is_private=False,
    )
    db.session.add(page)
    db.session.flush()  # get page.id without losing the txn
    s.cookie_compliance_policy_page_id = page.id
    db.session.commit()
    flash(
        f"Generated starter policy page “{title}” (/{slug}) and linked "
        "it as your privacy policy. Open it from Pages to fill in the "
        "placeholders (organisation name, contact email, retention "
        "periods).", "success")
    return redirect(url_for("main.frontend_page_edit", page_id=page.id))


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
    # Rows for the inline structure builder. A custom layout supplies its
    # own rows; a prebuilt is seeded as a vertical stack of its blocks so
    # the footer is always editable inline (the admin re-columns as they
    # like; saving turns a prebuilt into an editable custom layout).
    if active_rows:
        footer_rows = active_rows
    else:
        footer_rows = [{"type": "row", "cols": 1, "columns": [[{"type": t}]]}
                       for t in (active_block_order or [])]
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
                           footer_rows=footer_rows,
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
                           SUBMISSION_FORM_TEMPLATES,
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
    submission_form_key = (s.frontend_submission_form_template if s else None) or "classic"
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
                           # Recovery Contacts mirrors Contact: a single
                           # rendering ('default' key) that still gets a
                           # customize panel for UI uniformity, plus its own
                           # page-level heading + container-width controls.
                           recovery_contacts_active_settings=template_settings(s, "recovery_contacts", "default"),
                           site_index_templates=_by_name(SITE_INDEX_TEMPLATES),
                           site_index_active_key=site_index_key,
                           site_index_active_settings=template_settings(s, "site_index", site_index_key),
                           fellowships_list_templates=_by_name(FELLOWSHIPS_LIST_TEMPLATES),
                           fellowships_list_active_key=fellowships_list_key,
                           fellowships_list_active_settings=template_settings(s, "fellowships_list", fellowships_list_key),
                           submission_form_templates=_by_name(SUBMISSION_FORM_TEMPLATES),
                           submission_form_active_key=submission_form_key,
                           submission_form_active_settings=template_settings(s, "submission_form", submission_form_key),
                           # Form picker for the stories-list "Submit a story"
                           # CTA. Combines registry forms (events
                           # submission, contact) with admin-authored
                           # CustomForm rows so the operator picks from a
                           # single dropdown. Each entry has ``value`` (the
                           # identifier stored on SiteSetting) and
                           # ``label`` (visible name in the dropdown).
                           form_picker_options=_form_picker_options(),
                           font_options=all_fonts())


def _form_picker_options():
    """Combined list of every form an admin can link to from the public
    site. Used by the stories-list submit-CTA dropdown today; future
    surfaces (events list, etc.) can reuse the same shape."""
    from .forms_registry import all_forms as _all_forms
    out = []
    for f in _all_forms():
        out.append({
            "value": f["key"],
            "label": f["name"],
            "group": "Built-in",
        })
    for cf in CustomForm.query.order_by(CustomForm.title).all():
        out.append({
            "value": f"custom:{cf.id}",
            "label": cf.title + (" (disabled)" if not cf.enabled else ""),
            "group": "Custom",
        })
    return out


# Every kind that frontend_template_settings_save accepts. Each must
# resolve a catalog (or a one-key sentinel like printlist_default) so
# the form's `key` URL segment can be validated. Keeping this in one
# place means adding a future section is a single edit.
_TEMPLATE_KINDS = ("meeting", "event", "story", "blog_post",
                   "meetings_list", "events_list",
                   "announcements_list", "archive",
                   "stories_list", "blog_list",
                   "literature_library", "printlist", "contact",
                   "recovery_contacts",
                   "site_index", "fellowships_list", "submission_form")


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
                            FELLOWSHIPS_LIST_TEMPLATES, SUBMISSION_FORM_TEMPLATES)
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
        "submission_form": SUBMISSION_FORM_TEMPLATES,
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
    elif kind == "recovery_contacts":
        if key != "default":
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
    # Per-preset knobs arrive as one JSON blob; parse defensively.
    import json as _json
    _knobs_raw = request.form.get("bg_dynbg_config_json__knobs")
    try:
        _knobs = _json.loads(_knobs_raw) if _knobs_raw else None
        if not isinstance(_knobs, dict):
            _knobs = None
    except (ValueError, TypeError):
        _knobs = None
    dynbg_cfg = _dynbg.encode_config(
        overlay_key=request.form.get("bg_dynbg_config_json__overlay"),
        colors=[request.form.get(f"bg_dynbg_config_json__c{i}") for i in (1, 2, 3)],
        scope=request.form.get("bg_dynbg_config_json__scope"),
        noise_size=request.form.get("bg_dynbg_config_json__noise_size"),
        noise_intensity=request.form.get("bg_dynbg_config_json__noise_intensity"),
        randomize_colors=request.form.get("bg_dynbg_config_json__randomize_colors") == "1",
        randomize_positions=request.form.get("bg_dynbg_config_json__randomize_positions") == "1",
        animate=False if request.form.get("bg_dynbg_config_json__animate_off") == "1" else True,
        # Strength slider 0-100; encode_config normalises legacy
        # booleans + clamps the int. Raw value passed through here.
        pastel_light=request.form.get("bg_dynbg_config_json__pastel_light"),
        knobs=_knobs, preset_key=dyn_key,
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
    if dynbg_cfg.get("pastel_light"):
        # Persist as the int strength (0-100). decode_config returns
        # an int; legacy True values previously stored here keep
        # behaving as full-strength because normalize_pastel_strength
        # at the consumer side coerces ``True`` → 100.
        leaf["bg_dynbg_pastel_light"] = dynbg_cfg["pastel_light"]
    if dynbg_cfg.get("knobs"):
        leaf["bg_dynbg_knobs"] = dynbg_cfg["knobs"]
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
    # Per-card body preview — applies to the announcements list cards
    # (controls `Post.body` display) and the events list cards
    # (controls `Post.body` display, distinct from the always-shown
    # `Post.summary`). Two modes:
    #   • full      — render the entire body via markdown_block.
    #   • truncated — slice the raw body to `card_body_max_chars`
    #                 (clamped 50..2000) before rendering.
    # Both keys only persist when the admin actively chose them so a
    # missing-leaf surface still picks up the template-default render
    # path in the card partial.
    if kind in ("announcements_list", "events_list"):
        body_mode = (request.form.get("card_body_mode") or "").strip().lower()
        if body_mode in ("full", "truncated"):
            leaf["card_body_mode"] = body_mode
            if body_mode == "truncated":
                try:
                    chars = int(request.form.get("card_body_max_chars") or 200)
                except (TypeError, ValueError):
                    chars = 200
                leaf["card_body_max_chars"] = max(50, min(chars, 2000))
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
    if "frontend_stories_list_submit_form" in request.form:
        # Identifier validation: registry key OR ``custom:<id>`` where
        # the id matches an existing CustomForm row. Anything else (an
        # operator-edited curl payload, a stale dropdown value pointing
        # at a deleted form) is normalised back to NULL so the renderer
        # hides the button cleanly.
        from .forms_registry import form_by_key as _form_by_key
        raw = (request.form.get("frontend_stories_list_submit_form") or "").strip()
        valid = None
        if raw.startswith("custom:"):
            try:
                cf_id = int(raw.split(":", 1)[1])
                if CustomForm.query.get(cf_id):
                    valid = f"custom:{cf_id}"
            except (ValueError, IndexError):
                valid = None
        elif raw and _form_by_key(raw):
            valid = raw
        s.frontend_stories_list_submit_form = valid
    if "frontend_stories_list_submit_label" in request.form:
        label = (request.form.get("frontend_stories_list_submit_label") or "").strip()
        s.frontend_stories_list_submit_label = label[:100] or None
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


@bp.route("/frontend/submission-form-template", methods=["POST"])
@admin_required
def frontend_submission_form_template_save():
    """Persist the /submissionform layout choice, container width,
    and standalone dynbg config from the admin Templates page. Heading,
    subheading, intro copy, and form behaviour (allowed types, success
    message, submit label) are managed on Forms admin, not here — this
    endpoint only owns the appearance dimensions."""
    from .frontend import SUBMISSION_FORM_TEMPLATES
    s = _get_site_setting()
    if "frontend_submission_form_template" in request.form:
        key = (request.form.get("frontend_submission_form_template") or "").strip()
        if key in {t["key"] for t in SUBMISSION_FORM_TEMPLATES}:
            s.frontend_submission_form_template = key
    width = (request.form.get("frontend_submission_form_width_mode") or "").strip()
    if width in ("boxed", "full"):
        s.frontend_submission_form_width_mode = width
    if "frontend_submission_form_max_width" in request.form:
        try:
            max_w = int(request.form.get("frontend_submission_form_max_width") or 720)
        except ValueError:
            max_w = 720
        s.frontend_submission_form_max_width = max(480, min(2400, max_w))
    if "frontend_submission_form_padding_pct" in request.form:
        try:
            pad = int(request.form.get("frontend_submission_form_padding_pct") or 5)
        except ValueError:
            pad = 5
        s.frontend_submission_form_padding_pct = max(0, min(20, pad))
    if "frontend_submission_form_bg_dynamic_key" in request.form:
        from . import dynbg as _dynbg
        s.frontend_submission_form_bg_dynamic_key = _dynbg.normalize(
            request.form.get("frontend_submission_form_bg_dynamic_key"))
        s.frontend_submission_form_bg_dynbg_config_json = _dynbg_config_from_form(
            request.form, "frontend_submission_form_bg_dynbg_config_json")
    db.session.commit()
    flash("Submission form layout saved", "success")
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
    "powered_by", "admin_login", "privacy_links",
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
    """Apply a visual theme, with per-theme state persistence.

    Form fields:
      • ``frontend_theme`` — the theme to apply (defaults to the current one,
        so the modal can also re-apply a mode to the active theme).
      • ``restore_mode`` — ``last`` (default) restores the chosen theme's last
        saved state; ``default`` applies its built-in defaults.

    State model: switching AWAY from a theme snapshots its appearance fields
    so it can be returned to later; the current theme is also snapshotted the
    first time the switcher is ever used, so its look is never unrecoverable.
    Restoring a theme that was never customised falls back to its built-in
    defaults (so one theme's overrides never bleed into another).

    Cascades the chosen key to the header + mega-menu, and to the footer /
    homepage only when the theme ships a matching layout. Non-destructive:
    only appearance fields are touched — page/popup ``blocks_json`` and footer
    content are never changed.
    """
    from .frontend import (THEMES, THEME_DEFAULT_MODE,
                           FOOTER_TEMPLATES, HOMEPAGE_TEMPLATES,
                           load_theme_states, save_theme_states,
                           snapshot_theme_state, apply_theme_state,
                           reset_theme_state)
    from .models import CustomLayout
    s = _get_site_setting()
    cur = s.frontend_theme or "classic"
    key = (request.form.get("frontend_theme") or "").strip()
    if key not in {t["key"] for t in THEMES}:
        key = cur
    restore_mode = (request.form.get("restore_mode") or "last").strip()
    if restore_mode not in ("last", "default"):
        restore_mode = "last"
    states = load_theme_states(s)
    switching = (key != cur)

    # Always remember the theme we're leaving (and capture the very first
    # theme we touch) so a "Return to last saved state" later has something
    # to come back to — and a Reset is always undoable.
    if switching or cur not in states:
        states[cur] = snapshot_theme_state(s)

    if switching:
        s.frontend_theme = key
        s.frontend_header_template = key
        s.frontend_megamenu_template = key
        footer_keys = {t["key"] for t in FOOTER_TEMPLATES} | {
            cl.key for cl in CustomLayout.query.filter_by(kind="footer").all()}
        if key in footer_keys:
            s.frontend_footer_template = key
        homepage_keys = {t["key"] for t in HOMEPAGE_TEMPLATES} | {
            cl.key for cl in CustomLayout.query.filter_by(kind="homepage").all()}
        if key in homepage_keys:
            s.frontend_homepage_template = key
        if key in THEME_DEFAULT_MODE:
            s.frontend_default_theme = THEME_DEFAULT_MODE[key]

    if restore_mode == "default":
        reset_theme_state(s, key)
        flash(f"“{key}” applied with built-in defaults", "success")
    else:  # "last"
        if key in states:
            apply_theme_state(s, states[key])
            flash(f"“{key}” restored to its last saved state", "success")
        else:
            # Never visited → start from defaults so no other theme's
            # overrides bleed in.
            reset_theme_state(s, key)
            flash(f"Theme set to “{key}”", "success")
    save_theme_states(s, states)
    db.session.commit()
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
        cell_lengths = d.get("cell_lengths")
        if (isinstance(cell_lengths, list)
                and len(cell_lengths) == n_cols
                and all(isinstance(x, int) and x >= 0 for x in cell_lengths)
                and sum(cell_lengths) == len(kids)):
            # Cell-aware — kids are stored concatenated by cell with
            # explicit per-cell counts. Restore each cell exactly so an
            # unequal split (e.g. 2 left + 3 right) survives the round
            # trip. The public renderer uses the same `cell_lengths` to
            # wrap each cell's children in a flex-column sub-wrapper.
            cursor = 0
            for ci, n in enumerate(cell_lengths):
                for child in kids[cursor:cursor + n]:
                    node = _block_node(child)
                    if node is not None:
                        cells[ci].append(node)
                cursor += n
        else:
            # Legacy / equal-bucket — round-robin distribution mirrors
            # CSS grid's default `grid-auto-flow: row` (item i lands in
            # column `i mod n_cols`), so 6 items in a 3-col grid stack
            # as col0:[0,3], col1:[1,4], col2:[2,5] in the editor instead
            # of dumping everything past the column count into the last
            # cell. Flex containers (n_cols=1) land every child in the
            # single cell preserving source order.
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
    # Pending-draft overlay — when the page has a stashed `draft_json`,
    # the edit screen loads from it instead of the published columns so
    # the admin picks up their in-progress changes. The page object is
    # detached from the session before applying overrides so autoflushes
    # during the rest of this view (e.g. layout lookups) can't
    # accidentally persist the draft values to the live row.
    draft_active = False
    draft_saved_at = None
    if page.draft_json and page.is_published:
        try:
            draft_data = _json.loads(page.draft_json)
        except (ValueError, TypeError):
            draft_data = None
        if isinstance(draft_data, dict):
            draft_saved_at = page.draft_saved_at
            db.session.expunge(page)
            for key, val in draft_data.items():
                if hasattr(page, key):
                    try: setattr(page, key, val)
                    except Exception: pass
            draft_active = True
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
                           faq_modal_vals=faq_modal_vals,
                           draft_active=draft_active,
                           draft_saved_at=draft_saved_at)


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


# Columns captured in a PageRevision snapshot. Listed explicitly so a
# future Page schema change doesn't accidentally start capturing
# server-internal fields (`id`, `created_at`, `updated_at`, the draft
# columns themselves). Restore walks this list and `setattr`s each key
# present in the saved snapshot back onto the page, so adding a column
# here is the only step needed to extend revision coverage to new
# fields.
_PAGE_SNAPSHOT_FIELDS = (
    "title", "slug", "template",
    "is_published", "is_private",
    "blocks_json",
    "bg_mode", "bg_tile_scale", "bg_dynamic_key",
    "bg_dynbg_config_json",
    "bg_color", "bg_color_dark", "bg_color_dark_mode",
    "bg_image_filename",
    "width_mode", "max_width", "full_padding_pct",
    "pad_top", "pad_bottom", "pad_x", "section_gap", "block_margin_y",
    "heading_color", "subheading_color",
    "heading_font", "subheading_font", "heading_align",
    "og_title", "og_description", "og_image_filename",
    "layout_key",
)


def _page_snapshot_from_row(page):
    """Build a snapshot dict from a Page row's current column values.
    Used by the publish branch of `frontend_page_save` to record what
    was just written to the live row. Mirrors the shape `draft_json`
    uses so `restore` can deserialise it into the draft slot."""
    return {f: getattr(page, f, None) for f in _PAGE_SNAPSHOT_FIELDS}


def _record_page_revision(page, action, snapshot):
    """Append a PageRevision row for this save and trim history past
    the per-page cap. Called at the bottom of both the draft branch
    and the publish branch of `frontend_page_save`. Trim keeps the
    most recent `_PAGE_REVISION_LIMIT` entries; older rows are deleted
    in the same transaction so history doesn't grow without bound on a
    page edited many times a day."""
    import json as _json
    from .models import PageRevision
    rev = PageRevision(
        page_id=page.id,
        action=action,
        snapshot_json=_json.dumps(snapshot),
        created_by_id=(current_user.id
                       if current_user.is_authenticated else None),
    )
    db.session.add(rev)
    # Trim — drop everything past the cap. Subquery picks the ids to
    # delete in one round-trip so we don't load all rows into memory.
    # The newly-added `rev` hasn't been flushed yet, so it can't be
    # selected here; that's fine because the new row never lands in
    # the "older than cap" bucket on the same insert.
    overflow = (PageRevision.query
                .filter_by(page_id=page.id)
                .order_by(PageRevision.created_at.desc())
                .offset(_PAGE_REVISION_LIMIT)
                .all())
    for r in overflow:
        db.session.delete(r)


_PAGE_REVISION_LIMIT = 50


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

    # `save_action` controls whether this submit goes live (writes to
    # the published columns) or stashes a pending draft for an already-
    # published page. Driven by a hidden field the editor's `Save as
    # draft` button flips before submit; defaults to publish so older
    # callers / API submits behave exactly as they did before the
    # feature shipped. Draft saves only make sense for an existing,
    # published page — new pages and unpublished pages always go to
    # the live columns.
    save_action = (request.form.get("save_action") or "publish").strip().lower()
    if save_action not in ("publish", "draft"):
        save_action = "publish"

    if page_id:
        page = Page.query.get_or_404(int(page_id))
    else:
        page = Page()
        save_action = "publish"
    if save_action == "draft" and (not page.is_published or page.id is None):
        # Draft only meaningful for published pages with an id; degrade
        # silently to a normal publish so the admin doesn't lose work.
        save_action = "publish"

    # ── Draft branch ─────────────────────────────────────────────────
    # Build a typed snapshot of every form-derived value and stash it
    # in `page.draft_json`. The live columns are NOT touched, so the
    # public site keeps rendering the published row. Slug uniqueness
    # is skipped here — it gets enforced when the draft is eventually
    # published. File uploads (bg_image / og_image) still land on disk
    # because the file is needed when the draft is published; only
    # the column references are deferred.
    if save_action == "draft":
        from . import dynbg as _dynbg
        # Background image — write to disk if uploaded, capture filename.
        # `bg_image_filename` only enters the snapshot when the admin
        # actually changed it (clear or upload), so a draft that only
        # tweaks text doesn't have to mention bg_image and won't clobber
        # the live bg on publish.
        bg_filename_change = None  # (changed?, value)
        if request.form.get("clear_bg") == "1":
            bg_filename_change = (True, None)
        bg_upload = request.files.get("bg_image")
        if bg_upload and bg_upload.filename:
            ext = (bg_upload.filename.rsplit(".", 1)[-1].lower()
                   if "." in bg_upload.filename else "")
            if ext not in PAGE_BG_EXTS:
                flash(f"Unsupported background type .{ext}. Allowed: "
                      f"{', '.join(sorted(PAGE_BG_EXTS))}.", "danger")
                return redirect(_safe_referrer() or url_for("main.frontend_pages"))
            safe = secure_filename(bg_upload.filename) or f"page-bg.{ext}"
            stored = f"{_uuid4().hex}_{safe}"
            bg_upload.save(_os.path.join(current_app.config["UPLOAD_FOLDER"], stored))
            bg_filename_change = (True, stored)
        # OG image — same pattern.
        og_filename_change = None
        if request.form.get("og_present") == "1":
            if request.form.get("clear_og_image") == "1":
                og_filename_change = (True, None)
            og_upload = request.files.get("og_image")
            if og_upload and og_upload.filename:
                stored_og, _orig = _save_upload(og_upload)
                og_filename_change = (True, stored_og)
        # bg_color trio — only when the present-marker is set.
        bg_color_overrides = None
        if request.form.get("bg_color_present") == "1":
            import re as _bgc_re
            from .design import DESIGN_FIELDS_BY_KEY as _DFK
            _hex = _bgc_re.compile(r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")
            _tok = _bgc_re.compile(r"^token:([a-z0-9_]+)$", _bgc_re.IGNORECASE)
            def _coerce_bg(v):
                v = (v or "").strip()
                if not v: return None
                m = _tok.match(v)
                if m:
                    key = m.group(1); f = _DFK.get(key)
                    if f and f.get("kind") == "color": return "token:" + key
                    return None
                return v if _hex.match(v) else None
            dm = (request.form.get("bg_color_dark_mode") or "same").strip().lower()
            if dm not in ("same", "auto", "manual"): dm = "same"
            bg_color_overrides = {
                "bg_color": _coerce_bg(request.form.get("bg_color")),
                "bg_color_dark": _coerce_bg(request.form.get("bg_color_dark")),
                "bg_color_dark_mode": dm,
            }
        # Assemble the snapshot. Only fields the admin explicitly
        # interacted with land in the dict — the load path uses
        # `dict.get(key, page.<column>)` so absent keys fall through to
        # the published value.
        snapshot = {
            "title": title, "slug": slug, "template": tmpl,
            "is_published": is_published, "is_private": bool(is_private),
            "bg_mode": bg_mode, "bg_tile_scale": bg_tile_scale,
            "bg_dynamic_key": _dynbg.normalize(request.form.get("bg_dynamic_key")),
            "bg_dynbg_config_json": _dynbg_config_from_form(
                request.form, "bg_dynbg_config_json"),
            "width_mode": width_mode, "max_width": max_width,
            "full_padding_pct": full_padding_pct,
            "pad_top": pad_top, "pad_bottom": pad_bottom, "pad_x": pad_x,
            "section_gap": section_gap, "block_margin_y": block_margin_y,
        }
        if blocks_json_to_save is not None:
            snapshot["blocks_json"] = blocks_json_to_save
        if bg_filename_change is not None:
            snapshot["bg_image_filename"] = bg_filename_change[1]
        if bg_color_overrides is not None:
            snapshot.update(bg_color_overrides)
        if has_heading_color:    snapshot["heading_color"]    = heading_color
        if has_subheading_color: snapshot["subheading_color"] = subheading_color
        if has_heading_font:     snapshot["heading_font"]     = heading_font
        if has_subheading_font:  snapshot["subheading_font"]  = subheading_font
        if has_heading_align:    snapshot["heading_align"]    = heading_align
        if request.form.get("og_present") == "1":
            snapshot["og_title"] = (
                (request.form.get("og_title") or "").strip()[:200] or None)
            snapshot["og_description"] = (
                (request.form.get("og_description") or "").strip() or None)
            if og_filename_change is not None:
                snapshot["og_image_filename"] = og_filename_change[1]
        from datetime import datetime as _dt_now
        page.draft_json = _json.dumps(snapshot)
        page.draft_saved_at = _dt_now.utcnow()
        # The draft snapshot IS the saved state — record it on the
        # revision log so the admin can restore this exact draft later
        # even after Publishing or overwriting it with a newer draft.
        _record_page_revision(page, "draft", snapshot)
        db.session.commit()
        flash(f"Draft saved for “{page.title}”", "success")
        return redirect(url_for("main.frontend_page_edit", page_id=page.id))

    # ── Publish branch (the existing live-write flow) ─────────────────
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
        imgcache.note_image_change()  # bust cached page-bg URL
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

    # Publish supersedes any stashed draft — clear the snapshot + its
    # timestamp so the editor opens against the freshly-published live
    # values on the next load. The orphaned upload (if the admin had
    # uploaded a draft bg / og image and is now publishing different
    # content) sits on disk; the daily cleanup pass picks it up via
    # the orphan scan, same as any other un-referenced upload.
    page.draft_json = None
    page.draft_saved_at = None
    # Record this publish state on the revision log so the admin can
    # roll back later. Captured from the page row's column values
    # after the writes above so the snapshot matches what was actually
    # persisted (including any sanitisation / clamping the route did
    # on the way in). Skipped for brand-new pages whose `page.id` is
    # None until the upcoming commit assigns it — we record the first
    # revision on the NEXT save instead.
    if page.id is not None:
        _record_page_revision(page, "publish", _page_snapshot_from_row(page))
    db.session.commit()
    flash(f"Page “{title}” saved", "success")
    return redirect(url_for("main.frontend_page_edit", page_id=page.id))


@bp.route("/frontend/pages/<int:page_id>/revisions", methods=["GET"])
@admin_required
def frontend_page_revisions(page_id):
    """Return the page's revision history as JSON for the editor's
    History modal. Newest-first, capped at `_PAGE_REVISION_LIMIT`.
    Each entry carries the id, action, ISO timestamp, and author
    username so the modal can render a scannable list without doing
    extra round-trips."""
    from .models import Page, PageRevision
    page = Page.query.get_or_404(page_id)
    revs = (PageRevision.query
            .filter_by(page_id=page.id)
            .order_by(PageRevision.created_at.desc())
            .limit(_PAGE_REVISION_LIMIT)
            .all())
    out = []
    for r in revs:
        out.append({
            "id": r.id,
            "action": r.action,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "created_by": (r.user.username if r.user else None),
        })
    return jsonify({"revisions": out, "current_draft_active": bool(page.draft_json)})


@bp.route("/frontend/pages/<int:page_id>/revisions/<int:rev_id>/restore",
           methods=["POST"])
@admin_required
def frontend_page_revision_restore(page_id, rev_id):
    """Restore a past revision INTO the page's draft slot for review.
    Non-destructive — the live row is untouched until the admin clicks
    Publish on the editor. The restore itself counts as a save and is
    logged as its own revision (action='draft') so the move is part of
    the history trail too — admins can see exactly when and from which
    older revision a rollback was kicked off."""
    import json as _json
    from datetime import datetime as _dt_now
    from .models import Page, PageRevision
    page = Page.query.get_or_404(page_id)
    rev = PageRevision.query.get_or_404(rev_id)
    if rev.page_id != page.id:
        abort(404)
    try:
        snapshot = _json.loads(rev.snapshot_json)
    except (ValueError, TypeError):
        flash("That revision's snapshot is unreadable — cannot restore.", "danger")
        return redirect(url_for("main.frontend_page_edit", page_id=page.id))
    if not isinstance(snapshot, dict):
        flash("That revision is malformed — cannot restore.", "danger")
        return redirect(url_for("main.frontend_page_edit", page_id=page.id))
    page.draft_json = rev.snapshot_json
    page.draft_saved_at = _dt_now.utcnow()
    _record_page_revision(page, "draft", snapshot)
    db.session.commit()
    flash(f"Restored revision from "
          f"{rev.created_at.strftime('%b %d, %Y %I:%M %p')} UTC as a draft. "
          f"Review and Publish to apply.", "success")
    return redirect(url_for("main.frontend_page_edit", page_id=page.id))


@bp.route("/frontend/pages/<int:page_id>/discard-draft", methods=["POST"])
@admin_required
def frontend_page_discard_draft(page_id):
    """Drop any pending draft on a published page, reverting the editor
    to the live values. The live row is untouched; this just clears the
    `draft_json` / `draft_saved_at` columns so the next edit-screen load
    populates from the published columns. Uploaded draft assets (bg /
    og images that only ever existed in the snapshot) are left on disk —
    the daily orphan-cleanup pass collects them."""
    from .models import Page
    page = Page.query.get_or_404(page_id)
    had_draft = page.draft_json is not None
    page.draft_json = None
    page.draft_saved_at = None
    db.session.commit()
    if had_draft:
        flash(f"Draft discarded for “{page.title}”", "success")
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


# ── Popups ──────────────────────────────────────────────────────────
# Site-wide modal popups, authored with the same page-builder block
# editor and triggered from ``#name`` anchor selectors on the public
# frontend. See models.Popup + templates/frontend/_popups.html.
POPUP_SHADOWS = ("none", "sm", "md", "lg", "xl")
POPUP_POSITIONS = ("center", "top", "bottom")
POPUP_HEIGHT_MODES = ("auto", "fixed")

# Block types the popup editor exposes in its palette. Restricted to the
# page-builder blocks that have a fully inline editor in block_editor.js
# — the homepage-section blocks (hero / meetings / events / features /
# faq) are configured through the page editor's dedicated modals, which
# the popup editor deliberately doesn't host.
_POPUP_ALLOWED_BLOCK_TYPES = [
    "paragraph", "heading", "image", "button", "container",
    "list", "callout", "code", "separator", "icon", "video",
]

# Palette tiles offered in the popup builder's floating "Add block" FAB.
# Same drag-and-drop palette the page builder uses (`structure_block_palette`)
# — includes the layout helpers (`split` / `split3` two- and three-panel
# rows, which page_structure.js expands into containers) on top of the
# inline-editable content blocks above. Excludes the homepage-section
# blocks (hero / meetings / events / features / faq), wiki TOC, lottie,
# and the data-bound officer / library / blog blocks.
_POPUP_PALETTE_KEYS = [
    "split", "split3", "container", "heading", "paragraph",
    "image", "icon", "button", "list", "callout", "video", "code", "separator",
]

# Reserved popup handles that would collide with the trigger JS / hash
# conventions, kept clear so a popup name can't shadow them.
_POPUP_RESERVED_NAMES = {"popup", "open", "close"}


def _popup_unique_name(name, exclude_id=None):
    """Resolve ``name`` to a slug that's unique across popups (and not in
    the reserved set), suffix-bumping (``-2``, ``-3``…) on collision."""
    from .models import Popup
    base = _slugify_page(name)
    candidate = base
    n = 2
    with db.session.no_autoflush:
        while True:
            clash = (Popup.query
                     .filter(Popup.name == candidate,
                             Popup.id != (exclude_id or -1))
                     .first())
            if not clash and candidate not in _POPUP_RESERVED_NAMES:
                return candidate
            candidate = f"{base}-{n}"
            n += 1


@bp.route("/frontend/popups")
@admin_required
def frontend_popups():
    from .models import Popup
    s = _get_site_setting()
    popups = Popup.query.order_by(Popup.title.asc()).all()
    return render_template("frontend_popups.html", site=s, popups=popups)


@bp.route("/frontend/popups/create", methods=["POST"])
@admin_required
def frontend_popup_create():
    """Mint a new popup from the New-popup modal (name + optional handle
    + initial status) and drop straight into its editor. The full block
    + chrome editor lives on the edit screen."""
    import json as _json
    from .models import Popup
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("Popup name required", "danger")
        return redirect(url_for("main.frontend_popups"))
    # Handle defaults to a slug of the title when the admin leaves it blank.
    name = _popup_unique_name(request.form.get("name") or title)
    raw_status = (request.form.get("status") or "enabled").strip().lower()
    is_enabled = raw_status != "disabled"
    # Seed one empty-titled section so the inline editor opens clean (no
    # stray "New Section" heading) and ready for the admin to drop blocks.
    seed = _json.dumps([{"id": _uuid_short(), "title": "", "blocks": []}])
    popup = Popup(title=title, name=name, blocks_json=seed, is_enabled=is_enabled)
    db.session.add(popup)
    db.session.commit()
    return redirect(url_for("main.frontend_popup_edit", popup_id=popup.id))


@bp.route("/frontend/popups/<int:popup_id>/edit")
@admin_required
def frontend_popup_edit(popup_id):
    import json as _json
    from .models import Popup
    s = _get_site_setting()
    popup = Popup.query.get_or_404(popup_id)
    # Reuse the page builder's structure-card visualisation: a draggable
    # tree of block pills + per-pill hover previews, driven by the shared
    # page_structure.js. _page_active_tree only reads `.blocks_json`, so a
    # Popup feeds it directly (popups never carry orphan bins).
    tree_data = _page_active_tree(popup)
    try:
        _sections = _json.loads(popup.blocks_json or "[]") or []
    except (ValueError, TypeError):
        _sections = []
    block_previews = {}
    block_payloads = {}
    for bid, b in _walk_blocks_by_id(_sections):
        block_previews[bid] = _block_preview(b)
        block_payloads[bid] = b
    popup_catalog = [c for c in _PAGE_BLOCK_CATALOG if c["key"] in _POPUP_PALETTE_KEYS]
    return render_template("frontend_popup_edit.html", site=s, popup=popup,
                           blocks_json=popup.blocks_json or "[]",
                           popup_allowed_block_types=_POPUP_ALLOWED_BLOCK_TYPES,
                           popup_block_catalog=popup_catalog,
                           active_layout_tree=tree_data["tree"],
                           active_layout_orphans=tree_data["orphans"],
                           block_previews=block_previews,
                           block_payloads=block_payloads)


@bp.route("/frontend/popups/save", methods=["POST"])
@admin_required
def frontend_popup_save():
    """Persist a popup's block content + chrome settings. Mirrors
    ``frontend_page_save``: blocks_json is only overwritten when the
    editor serialised a value, and every clamp keeps tampered POSTs in
    range."""
    import json as _json
    import re as _re
    from .models import Popup
    popup_id = (request.form.get("popup_id") or "").strip()
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("Popup name is required", "danger")
        return redirect(_safe_referrer() or url_for("main.frontend_popups"))

    raw_blocks = request.form.get("blocks_json")
    blocks_to_save = None
    if raw_blocks is not None and raw_blocks.strip() != "":
        try:
            _json.loads(raw_blocks)
            blocks_to_save = raw_blocks
        except (ValueError, TypeError):
            flash("Invalid blocks JSON", "danger")
            return redirect(_safe_referrer() or url_for("main.frontend_popups"))

    def _clamp(field, default, lo, hi):
        try:
            v = int(request.form.get(field) or default)
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    width = _clamp("width", 480, 200, 1200)
    max_width_pct = _clamp("max_width_pct", 92, 30, 100)
    height = _clamp("height", 420, 120, 2000)
    padding = _clamp("padding", 32, 0, 160)
    border_radius = _clamp("border_radius", 16, 0, 80)
    overlay_opacity = _clamp("overlay_opacity", 60, 0, 100)
    auto_open_delay = _clamp("auto_open_delay", 0, 0, 60000)

    height_mode = (request.form.get("height_mode") or "auto").strip().lower()
    if height_mode not in POPUP_HEIGHT_MODES:
        height_mode = "auto"
    shadow = (request.form.get("shadow") or "xl").strip().lower()
    if shadow not in POPUP_SHADOWS:
        shadow = "xl"
    position = (request.form.get("position") or "center").strip().lower()
    if position not in POPUP_POSITIONS:
        position = "center"

    _hex = _re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

    def _color(value, default):
        value = (value or "").strip()
        return value if _hex.match(value) else default

    bg_color = _color(request.form.get("bg_color"), "#ffffff")
    raw_dark = (request.form.get("bg_color_dark") or "").strip()
    bg_color_dark = raw_dark if _hex.match(raw_dark) else None
    overlay_color = _color(request.form.get("overlay_color"), "#0f172a")

    if popup_id:
        popup = Popup.query.get_or_404(int(popup_id))
    else:
        popup = Popup()
        db.session.add(popup)

    popup.title = title
    popup.name = _popup_unique_name(request.form.get("name") or title,
                                    exclude_id=popup.id)
    if blocks_to_save is not None:
        popup.blocks_json = blocks_to_save
    elif popup.blocks_json is None:
        popup.blocks_json = "[]"

    raw_status = (request.form.get("status") or "").strip().lower()
    if raw_status in ("enabled", "disabled"):
        popup.is_enabled = raw_status == "enabled"
    else:
        popup.is_enabled = request.form.get("is_enabled") == "1"

    popup.width = width
    popup.max_width_pct = max_width_pct
    popup.height_mode = height_mode
    popup.height = height
    popup.padding = padding
    popup.bg_color = bg_color
    popup.bg_color_dark = bg_color_dark
    popup.border_radius = border_radius
    popup.shadow = shadow
    popup.overlay_enabled = request.form.get("overlay_enabled") == "1"
    popup.overlay_color = overlay_color
    popup.overlay_opacity = overlay_opacity
    popup.position = position
    popup.show_desktop = request.form.get("show_desktop") == "1"
    popup.show_mobile = request.form.get("show_mobile") == "1"
    popup.mobile_full_width = request.form.get("mobile_full_width") == "1"
    popup.close_on_overlay = request.form.get("close_on_overlay") == "1"
    popup.show_close_button = request.form.get("show_close_button") == "1"
    popup.auto_open = request.form.get("auto_open") == "1"
    popup.auto_open_delay = auto_open_delay

    db.session.commit()
    flash(f"Popup “{title}” saved", "success")
    return redirect(url_for("main.frontend_popup_edit", popup_id=popup.id))


@bp.route("/frontend/popups/<int:popup_id>/status", methods=["POST"])
@admin_required
def frontend_popup_status(popup_id):
    """Quick enable/disable toggle from the list / editor without a full
    form round-trip."""
    from .models import Popup
    popup = Popup.query.get_or_404(popup_id)
    status = (request.form.get("status") or "").strip().lower()
    if status not in ("enabled", "disabled"):
        flash("Unknown status", "danger")
        return redirect(_safe_referrer() or url_for("main.frontend_popups"))
    popup.is_enabled = status == "enabled"
    db.session.commit()
    return redirect(_safe_referrer()
                    or url_for("main.frontend_popup_edit", popup_id=popup.id))


@bp.route("/frontend/popups/<int:popup_id>/delete", methods=["POST"])
@admin_required
def frontend_popup_delete(popup_id):
    from .models import Popup
    popup = Popup.query.get_or_404(popup_id)
    title = popup.title
    db.session.delete(popup)
    db.session.commit()
    flash(f"Popup “{title}” deleted", "success")
    return redirect(url_for("main.frontend_popups"))


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
            imgcache.note_image_change()  # bust cached brand-logo URL
    # Structured content — only update if the form-level marker is
    # present. parse_footer is given the existing content so any section
    # whose editor card was hidden (because the active layout doesn't
    # use that block) preserves its saved values instead of being wiped.
    if "footer_blocks_present" in request.form:
        from .blocks import footer_content
        existing = footer_content(s)
        content = parse_footer(request.form, existing=existing)
        s.frontend_footer_blocks_json = _json.dumps(content)
    # Footer arrangement from the inline structure builder → a footer
    # CustomLayout (rows/columns of block types). The public render reads
    # this layout + the content dict above, so the two stay decoupled.
    raw_layout = request.form.get("footer_layout_json")
    if raw_layout is not None:
        try:
            rows = _json.loads(raw_layout)
        except (ValueError, TypeError):
            rows = None
        if isinstance(rows, list):
            rows = _normalize_footer_blocks(rows)
            active_key = (s.frontend_footer_template or "classic")
            cl = CustomLayout.query.filter_by(key=active_key, kind="footer").first()
            if cl is None:
                # Active layout is a prebuilt — promote to an editable
                # custom layout the inline builder owns going forward.
                cl = CustomLayout.query.filter_by(key="footer-custom", kind="footer").first()
                if cl is None:
                    cl = CustomLayout(key="footer-custom", kind="footer",
                                      name="Custom footer", is_prebuilt=False)
                    db.session.add(cl)
                s.frontend_footer_template = "footer-custom"
            cl.blocks_json = _json.dumps(rows)
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
def reading_thumbnail(rid):
    r = db.session.get(LibraryItem, rid) or abort(404)
    if not r.thumbnail_filename:
        abort(404)
    # Public visitors get the thumbnail only when the library + item are
    # both flagged public — matches the gate used by the Literature
    # Library page (frontend.literature_library) and public page blocks
    # that reference these thumbs. Authenticated portal users see every
    # thumb regardless of visibility.
    if not current_user.is_authenticated:
        if not (r.public_visible and r.library and r.library.public_visible):
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
    # Advance the frontend image cache-bust token so returning visitors
    # pick up the new/replaced image immediately (committed with the
    # caller's transaction). No-op for non-images and when autobump is off.
    if ext in imgcache.IMAGE_EXTENSIONS:
        imgcache.note_image_change()
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
    # Post gallery references — the column stores a JSON list of
    # stored filenames so a straight equality query doesn't work.
    # LIKE-scan against the JSON blob; this is rare enough (only
    # triggered on retire) that the table-scan cost doesn't show
    # up in latency budgets. Wrap the needle in quotes so a longer
    # filename that *contains* the stored name as a substring
    # doesn't generate a false positive.
    gallery_token = '"' + stored.replace('"', '\\"') + '"'
    gallery_refs = Post.query.filter(
        Post.gallery_json.contains(gallery_token)).count()
    if gallery_refs > 0:
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
    # Multi-select picker mode — surfaces a checkbox on every item +
    # a fixed bottom bar with the running count and a "Done — add N"
    # button that posts a batch ``media-selected-batch`` message back
    # to the parent. Only meaningful when ``picker=1``.
    picker_multi = picker and request.args.get("multi") == "1"
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
        render_template("media.html", items=items, q=q, picker=picker,
                        picker_multi=picker_multi, view=view,
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
        rc_abuse=wt.recovery_contact_abuse(active_only=True, limit=50),
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
    # We pre-compute both views + uniques sets so the client-side
    # metric toggle (Unique visitors ⇄ Hits) can flip instantly
    # without a round-trip. Rendering both sides server-side is cheap
    # — these are small lists. Browser + OS breakdowns were folded in
    # when /tspro/frontend/metrics was retired and its donuts moved
    # here.
    hourly_days = min(30, window)
    return render_template(
        "watchtower/visitors.html",
        active_tab="visitors",
        window=window,
        hr_days=hourly_days,
        windows=(7, 14, 30, 60, 90, 180, 365),
        summary=vm.summary(days=window),
        daily=vm.daily_series(days=window),
        hourly_views=vm.hourly_distribution(days=hourly_days, metric="views"),
        hourly_uniques=vm.hourly_distribution(days=hourly_days, metric="uniques"),
        # Big enough pool that the client-side "Show 30 more" expand
        # rarely runs out without paying for another round-trip.
        top_paths_views=vm.top_paths(days=window, limit=300, metric="views"),
        top_paths_uniques=vm.top_paths(days=window, limit=300, metric="uniques"),
        top_referrers_views=vm.top_referrers(days=window, limit=300, metric="views"),
        top_referrers_uniques=vm.top_referrers(days=window, limit=300, metric="uniques"),
        devices_views=vm.device_breakdown(days=window, metric="views"),
        devices_uniques=vm.device_breakdown(days=window, metric="uniques"),
        browsers_views=vm.browser_breakdown(days=window, metric="views"),
        browsers_uniques=vm.browser_breakdown(days=window, metric="uniques"),
        os_views=vm.os_breakdown(days=window, metric="views"),
        os_uniques=vm.os_breakdown(days=window, metric="uniques"),
    )


@bp.route("/watchtower/visitors.csv")
@admin_required
def watchtower_visitors_csv():
    """Comprehensive visitor-metrics export. Returns a single CSV
    grouped into labelled sections (Summary / Daily series / Hour of
    day / Top paths / Top referrers / Devices / Browsers / Operating
    systems) so an admin can drop it into Excel or Sheets and have
    every chart's underlying data without screen-scraping.

    Each breakdown carries BOTH `views` and `unique_visitors` columns
    so the spreadsheet user can sort/filter on whichever metric they
    prefer. Rows are unioned across the two rankings — a path that
    only appears in the hits-by-views top list still gets a row with
    its (smaller) unique-visitor count and vice versa.

    Window honors the standard `?window=N` param the visitors page
    uses; pool size for the top lists is capped at 300 to match the
    inline expandable lists' depth."""
    from . import visitor_metrics as vm
    from flask import make_response
    import csv as _csv
    from io import StringIO

    try:
        window = max(7, min(365, int(request.args.get("window", 30))))
    except (TypeError, ValueError):
        window = 30
    hr_days = min(30, window)

    s = vm.summary(days=window)
    daily = vm.daily_series(days=window)
    hourly_v = vm.hourly_distribution(days=hr_days, metric="views")
    hourly_u = vm.hourly_distribution(days=hr_days, metric="uniques")

    def _merge(views_rows, uniques_rows):
        """Union two ranked breakdowns into one label -> {views, uniques}
        mapping, sorted by views desc with uniques as the tiebreaker.
        Preserves every label that appeared in either ranking."""
        m = {}
        for r in views_rows:
            m.setdefault(r["label"], {"views": 0, "uniques": 0})["views"] = r["count"]
        for r in uniques_rows:
            m.setdefault(r["label"], {"views": 0, "uniques": 0})["uniques"] = r["count"]
        return sorted(m.items(),
                      key=lambda kv: (-kv[1]["views"], -kv[1]["uniques"], kv[0]))

    paths     = _merge(vm.top_paths(days=window, limit=300, metric="views"),
                       vm.top_paths(days=window, limit=300, metric="uniques"))
    referrers = _merge(vm.top_referrers(days=window, limit=300, metric="views"),
                       vm.top_referrers(days=window, limit=300, metric="uniques"))
    devices   = _merge(vm.device_breakdown(days=window, metric="views"),
                       vm.device_breakdown(days=window, metric="uniques"))
    browsers  = _merge(vm.browser_breakdown(days=window, metric="views"),
                       vm.browser_breakdown(days=window, metric="uniques"))
    oses      = _merge(vm.os_breakdown(days=window, metric="views"),
                       vm.os_breakdown(days=window, metric="uniques"))

    buf = StringIO()
    w = _csv.writer(buf)
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # File-level preamble. Comment-style first row keeps the file
    # human-readable; spreadsheet importers treat it as a single cell
    # in column A which is fine for context.
    w.writerow([f"# Visitor metrics — last {window} days — exported {now_str}"])
    w.writerow([])

    # ── Summary ────────────────────────────────────────────────────
    w.writerow(["## Summary"])
    w.writerow(["metric", "value"])
    for key, label in (
            ("views_today",     "Views today"),
            ("views_yesterday", "Views yesterday"),
            ("views_7d",        "Views (last 7d)"),
            ("views_30d",       "Views (last 30d)"),
            ("views_window",    f"Views (last {window}d)"),
            ("uniques_today",   "Unique visitors today"),
            ("uniques_7d",      "Unique visitors (last 7d)"),
            ("uniques_30d",     "Unique visitors (last 30d)"),
            ("uniques_window",  f"Unique visitors (last {window}d)"),
            ("total_views",     "Total views (lifetime)")):
        w.writerow([label, s.get(key, 0)])
    if s.get("first_seen_at"):
        w.writerow(["First seen at", s["first_seen_at"].strftime("%Y-%m-%d %H:%M UTC")])
    w.writerow([])

    # ── Daily series ───────────────────────────────────────────────
    w.writerow(["## Daily series"])
    w.writerow(["day", "views", "unique_visitors"])
    for d in daily:
        w.writerow([d["day"], d["views"], d["uniques"]])
    w.writerow([])

    # ── Hour of day ────────────────────────────────────────────────
    w.writerow([f"## Hour of day (UTC, last {hr_days}d)"])
    w.writerow(["hour", "views", "unique_visitors"])
    uniques_by_hour = {r["hour"]: r["count"] for r in hourly_u}
    for r in hourly_v:
        w.writerow([f"{r['hour']:02d}", r["count"], uniques_by_hour.get(r["hour"], 0)])
    w.writerow([])

    def _write_breakdown(section_label, label_col, rows):
        w.writerow([section_label])
        w.writerow([label_col, "views", "unique_visitors"])
        for label, counts in rows:
            w.writerow([label, counts["views"], counts["uniques"]])
        w.writerow([])

    _write_breakdown("## Top paths",     "path",     paths)
    _write_breakdown("## Top referrers", "referrer", referrers)
    _write_breakdown("## Devices",       "device",   devices)
    _write_breakdown("## Browsers",      "browser",  browsers)
    _write_breakdown("## Operating systems", "os",   oses)

    filename = f"visitor-metrics-{window}d-{datetime.utcnow().strftime('%Y%m%d')}.csv"
    resp = make_response(buf.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    # Don't cache — the underlying data changes every page view.
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/watchtower/not-found")
@admin_required
def watchtower_not_found():
    """404 tracker tab — the public-site URLs visitors hit that resolved
    to nothing (unmatched routes + handlers that aborted 404). Surfaces
    broken inbound links and dead pages so an admin can redirect or fix
    them. Admin (/tspro) 404s are never logged here."""
    from . import watchtower as wt
    try:
        window = max(7, min(365, int(request.args.get("window", 30))))
    except (TypeError, ValueError):
        window = 30
    # Resolve which of the 404'd paths shown on this page are *already*
    # covered by an existing redirect (exact OR wildcard) so the row
    # can render an "already redirected" chip instead of the create
    # button. Same priority as the runtime handler: exact wins, then
    # longest-prefix wildcard.
    all_redirects = UrlRedirect.query.with_entities(
        UrlRedirect.source_path, UrlRedirect.target_path).all()
    exact_map = {r.source_path: r.target_path
                 for r in all_redirects if not r.source_path.endswith("/*")}
    wild_rules = sorted(
        [(r.source_path[:-1], r.target_path)  # keep trailing "/"
         for r in all_redirects if r.source_path.endswith("/*")],
        key=lambda x: -len(x[0]))

    def _resolve(path):
        if path in exact_map:
            return exact_map[path]
        for prefix, target in wild_rules:
            if path == prefix[:-1] or path.startswith(prefix):
                return target
        return None

    # Fetch a generous pool so the admin can keep clicking "Show 30
    # more" client-side without paying another round-trip. 300 covers
    # any realistic 404 backlog while staying cheap to render.
    top_paths = wt.top_missing_paths(days=window, limit=300)
    recent = wt.recent_404s(limit=100)
    paths_on_page = (
        {r["label"] for r in top_paths} | {e.path for e in recent}
    )
    existing_redirects = {p: _resolve(p) for p in paths_on_page if _resolve(p)}

    # Active block set for the IPs that appear in `recent`, so the
    # table can render "Blocked" instead of a Block button for already-
    # banned IPs. One indexed query against IPBlock per page load.
    recent_ips = {e.ip for e in recent if e.ip}
    blocked_ips = set()
    if recent_ips:
        from .models import IPBlock as _IPBlock
        now_ = datetime.utcnow()
        blocked_ips = {b.ip for b in _IPBlock.query
                       .filter(_IPBlock.ip.in_(recent_ips))
                       .filter((_IPBlock.expires_at.is_(None)) |
                               (_IPBlock.expires_at > now_)).all()}

    return render_template(
        "watchtower/not_found.html",
        active_tab="not-found",
        window=window,
        windows=(7, 14, 30, 60, 90, 180, 365),
        summary=wt.not_found_summary(days=window),
        daily=wt.not_found_daily(days=window),
        top_paths=top_paths,
        top_referrers=wt.top_404_referrers(days=window, limit=300),
        recent=recent,
        existing_redirects=existing_redirects,
        blocked_ips=blocked_ips,
    )


@bp.route("/watchtower/not-found/clear", methods=["POST"])
@admin_required
def watchtower_not_found_clear():
    """Wipe the entire 404 log."""
    from . import watchtower as wt
    n = wt.clear_404s()
    flash(f"Cleared {n} logged 404{'' if n == 1 else 's'}.", "success")
    return redirect(url_for("main.watchtower_not_found"))


@bp.route("/watchtower/not-found/redirect", methods=["POST"])
@admin_required
def watchtower_not_found_create_redirect():
    """Inline create-redirect endpoint for the 404s tab. Accepts JSON
    `{source_path, target_path}` and returns JSON so the modal can save
    without taking the admin off the page. Mirrors the validation in
    `frontend_redirects_save` (normalize leading slash, length cap,
    loop check, uniqueness)."""
    payload = request.get_json(silent=True) or request.form
    src, tgt, err = _normalize_redirect_pair(
        payload.get("source_path"), payload.get("target_path"))
    if err:
        return jsonify(ok=False, error=err), 400
    existing = UrlRedirect.query.filter_by(source_path=src).first()
    if existing:
        return jsonify(ok=False,
                       error=f"A redirect already exists for {src} → {existing.target_path}.",
                       existing_target=existing.target_path), 409
    row = UrlRedirect(source_path=src, target_path=tgt)
    db.session.add(row)
    db.session.commit()
    return jsonify(ok=True, id=row.id, source_path=src, target_path=tgt,
                   is_wildcard=src.endswith("/*"))


@bp.route("/watchtower/not-found/path-ips")
@admin_required
def watchtower_not_found_path_ips():
    """Return an HTML fragment listing the distinct source IPs hitting
    a given 404 path in the current window, with per-IP hit counts +
    last-seen + a Block / Blocked button. The Watchtower 404s template
    fetches this fragment when the admin clicks an expand chevron on a
    Top missing URL row, and injects the response inline.

    Fragment (not full page) so it can drop straight into the parent
    `<li>` without iframes or JSON-to-DOM glue. CSRF protection isn't
    needed — this is a GET that reads only."""
    from . import watchtower as wt
    path = (request.args.get("path") or "").strip()
    if not path:
        return ("", 400)
    try:
        window = max(7, min(365, int(request.args.get("window", 30))))
    except (TypeError, ValueError):
        window = 30
    ips = wt.not_found_ips_for_path(path, days=window, limit=25)
    return render_template("watchtower/_not_found_ips.html",
                           path=path, ips=ips, window=window)


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


@bp.route("/watchtower/rc-abuse/<int:aid>/resolve", methods=["POST"])
@admin_required
def watchtower_rc_abuse_resolve(aid):
    """Mark a flagged Recovery Contacts update/removal request handled so it
    drops off the overview panel and the attention chip."""
    from . import watchtower as wt, activity
    ok = wt.resolve_rc_abuse(aid, current_user.id)
    if ok:
        activity.log("watchtower.rc_abuse_resolve",
                     entity_type="recovery_contact_abuse", entity_id=aid,
                     summary="Resolved a flagged Recovery Contacts request")
        flash("Marked the flagged request as handled.", "success")
    else:
        flash("That flag was already cleared.", "info")
    return redirect(request.form.get("return_url") or url_for("main.watchtower"))


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
    before today AND any active announcement whose admin-set
    ``announcement_auto_archive_at`` has passed. Drafts are skipped —
    admins can sit on a draft indefinitely without it disappearing
    into the archive. Idempotent — safe to call on every list view.

    Both cutoffs are computed in the site's configured timezone so
    "today" and "now" mean what the admin sees on their wall clock,
    not what the server happens to read in UTC. ``event_ends_at`` and
    ``announcement_auto_archive_at`` are both parsed naive from the
    HTML5 ``datetime-local`` input the admin types into, i.e. stored
    as naive-site-local; comparing them against a naive-site-local
    cutoff keeps the wall-clock semantics intact.

    Two separate cutoffs:
      • Events compare to *midnight today site-local* — events
        ending yesterday-or-earlier (in the fellowship's tz)
        disappear at the start of today.
      • Announcements compare to *now site-local* — admins set the
        auto-archive deadline as a wall-clock time, so the value
        goes live the moment that wall-clock arrives in the
        fellowship's timezone.
    """
    from .timezone import now_local_naive
    site = _get_site_setting()
    now_local = now_local_naive(site)
    event_cutoff = datetime.combine(now_local.date(), datetime.min.time())
    announce_cutoff = now_local
    q = Post.query.filter(
        Post.is_archived.is_(False), Post.is_draft.is_(False),
    )
    changed = False
    for p in q.all():
        # Event arm — keep the legacy behaviour: an event whose end
        # was before midnight today (i.e. ended yesterday or earlier)
        # auto-archives. An event with no end falls back to start.
        if p.is_event:
            ref = p.event_ends_at or p.event_starts_at
            if ref and ref < event_cutoff:
                p.is_archived = True
                changed = True
                continue
        # Announcement arm — only applies when the admin opted in by
        # setting ``announcement_auto_archive_at``. Compared against
        # the site-local wall clock so the cutoff matches what the
        # admin typed into the form input.
        if p.is_announcement and p.announcement_auto_archive_at:
            if p.announcement_auto_archive_at <= announce_cutoff:
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
    # Sort resolution order: explicit ?sort= wins, then the user's
    # remembered cookie, then the per-tab default. Default for the
    # main tabs is ``posted_desc`` (newest at top by Posted date);
    # the pending tab keeps ``submitted_desc`` so the freshest
    # submission sits up top. Any saved sort the route doesn't
    # recognise is dropped to the default downstream.
    sort = (request.args.get("sort")
            or request.cookies.get("view-posts-sort")
            or "").strip()
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
    # submissions on top, every other tab shows by posted date
    # (newest first) so the most recent activity reads first.
    # Admin can override via the column-header click which sets
    # ?sort=… directly; their choice is persisted to the
    # ``view-posts-sort`` cookie at the bottom of the handler so
    # the same sort sticks across reloads.
    default_sort = "submitted_desc" if show == "pending" else "posted_desc"
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
    resp = current_app.make_response(
        render_template("posts.html", posts=items, show=show, kind=kind,
                        sort=sort, page=page, per_page=per_page,
                        total=total, total_pages=total_pages,
                        pending_count=pending_count))
    # Remember the user's chosen sort so the next visit lands on
    # the same order. Skip persistence on the pending tab — its
    # ``submitted_desc`` default is contextual to that view and
    # shouldn't bleed onto the regular tabs.
    if show != "pending":
        resp.set_cookie("view-posts-sort", sort,
                        max_age=60*60*24*365, samesite="Lax")
    return resp


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
    # Announcement-only auto-archive deadline. Only honored when the
    # post is tagged as an announcement AND the admin enabled the
    # toggle. Otherwise the column is wiped so a post that loses its
    # announcement tag doesn't keep ticking toward a stale deadline.
    if (post.is_announcement
            and request.form.get("announcement_auto_archive_enabled") == "1"):
        post.announcement_auto_archive_at = _parse_post_dt(
            request.form.get("announcement_auto_archive_at"))
    else:
        post.announcement_auto_archive_at = None
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

    # Multi-row Links section. Each row submits as parallel
    # ``link_url[]``, ``link_label[]``, plus an indexed
    # ``link_new_tab_<idx>`` checkbox (HTML checkboxes that aren't
    # ticked simply don't post — using indices lets the server keep
    # row-to-checkbox alignment even when some checkboxes are off).
    # Empty URL rows are dropped so a removed/blank entry doesn't
    # produce an orphan link.
    import json as _json
    _urls = request.form.getlist("link_url")
    _labels = request.form.getlist("link_label")
    _styles = request.form.getlist("link_style")
    _links = []
    for i, raw_url in enumerate(_urls):
        url = (raw_url or "").strip()[:500]
        if not url:
            continue
        label = (_labels[i] if i < len(_labels) else "").strip()[:120] or None
        new_tab = (request.form.get(f"link_new_tab_{i}") == "1")
        # Button style — defaults to primary so links typed without
        # touching the dropdown still render as a solid CTA.
        style = (_styles[i] if i < len(_styles) else "").strip().lower()
        if style not in ("primary", "secondary"):
            style = "primary"
        _links.append({"url": url, "label": label,
                       "new_tab": new_tab, "style": style})
    post.links_json = _json.dumps(_links) if _links else None
    # Keep the legacy single-pair columns in sync with the first
    # link so import scripts + older code paths still surface
    # *something* sensible. Set to NULL when there are no links so
    # the legacy fallback inside ``event_links`` doesn't resurrect a
    # stale single link after the admin clears the list.
    if _links:
        post.website_url = _links[0]["url"]
        post.website_label = _links[0]["label"]
    else:
        post.website_url = None
        post.website_label = None

    post.zoom_meeting_id = (request.form.get("zoom_meeting_id") or "").strip()[:64] or None
    post.zoom_passcode = (request.form.get("zoom_passcode") or "").strip()[:128] or None
    post.zoom_url = (request.form.get("zoom_url") or "").strip()[:500] or None

    post.contact_name = (request.form.get("contact_name") or "").strip()[:120] or None
    post.contact_phone = (request.form.get("contact_phone") or "").strip()[:64] or None
    post.contact_email = (request.form.get("contact_email") or "").strip()[:255] or None

    # Featured image — same upload/clear semantics as the OG image,
    # plus a File-Browser pick that resolves a posted ``MediaItem.id``
    # back to its stored filename. Priority order:
    #   1. Explicit "Remove current image" checkbox wins (clear intent).
    #   2. New upload — admin attached a fresh file.
    #   3. File Browser pick — admin selected an existing media row.
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
    else:
        picked_raw = (request.form.get("featured_image_media_id") or "").strip()
        if picked_raw.isdigit():
            m = db.session.get(MediaItem, int(picked_raw))
            if m and m.stored_filename:
                old = post.featured_image_filename
                post.featured_image_filename = m.stored_filename
                # The picked file lives in MediaItem and is shared with
                # other rows — never clean it up here. Only retire the
                # *previous* asset if it isn't the freshly-picked one.
                if old and old != m.stored_filename:
                    _cleanup_retired_asset(old)

    # Gallery — up to 6 images. The editor submits three parallel
    # streams:
    #   gallery_existing[] — stored filenames to keep, in the
    #                        admin's chosen order (drag-reordered).
    #   gallery_upload[]   — new file uploads to append.
    #   gallery_media_id[] — MediaItem ids picked from the File
    #                        Browser modal to append.
    # We rebuild the gallery list from scratch every save: the
    # admin's "existing" list represents the kept-after-edits state,
    # so anything removed from it goes through ``_cleanup_retired_
    # asset`` to retire orphaned files. Hard cap at 10 enforced both
    # server-side here and by the client UI.
    import json as _gjson
    prev_gallery = set(post.gallery_filenames)
    kept_existing = []
    for raw in request.form.getlist("gallery_existing"):
        name = (raw or "").strip()
        if not name:
            continue
        if name in prev_gallery and name not in kept_existing:
            kept_existing.append(name)
    new_files = []
    for upload in request.files.getlist("gallery_upload"):
        if not upload or not upload.filename:
            continue
        if len(kept_existing) + len(new_files) >= 6:
            break
        try:
            stored, _orig = _save_upload(upload)
        except Exception:  # noqa: BLE001
            continue
        new_files.append(stored)
    picked_files = []
    for raw in request.form.getlist("gallery_media_id"):
        token = (raw or "").strip()
        if not token.isdigit():
            continue
        if len(kept_existing) + len(new_files) + len(picked_files) >= 6:
            break
        m = db.session.get(MediaItem, int(token))
        if m and m.stored_filename:
            picked_files.append(m.stored_filename)
    new_gallery = kept_existing + new_files + picked_files
    new_gallery = new_gallery[:6]
    # Retire removed images — anything that was in the prior list
    # but isn't in the new list. ``_cleanup_retired_asset`` is
    # reference-counted so shared images survive automatically.
    for stale in prev_gallery - set(new_gallery):
        _cleanup_retired_asset(stale)
    post.gallery_json = _gjson.dumps(new_gallery) if new_gallery else None

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
    old_gallery = list(post.gallery_filenames)
    # Snapshot inline /pub/ image stored filenames BEFORE the delete so
    # we still have the body text to scan. The cleanup helper runs
    # AFTER commit so its reference-count scan doesn't still see this
    # row's body holding the same /pub/<filename>.
    body_inline_stored = _collect_body_inline_stored(post.body)
    post.featured_image_filename = None
    post.gallery_json = None
    if old_image:
        _cleanup_retired_asset(old_image)
    db.session.delete(post)
    db.session.commit()
    for s in body_inline_stored:
        _cleanup_retired_asset(s)
    # Retire each gallery image. Reference-counted so shared
    # images still in another post's gallery survive automatically.
    for g in old_gallery:
        _cleanup_retired_asset(g)
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


@public_bp.route("/post-gallery-image/<int:pid>/<int:idx>")
def post_gallery_image(pid, idx):
    """Serve the ``idx``-th image of a post's gallery. Public so the
    frontend renders gallery thumbnails / lightbox full-size images
    without authentication.

    Supports ``?thumb=<size>`` for postage-stamp tiles — same
    contract the featured-image / story-image routes use. Without
    the param, the full-resolution source is returned. The ``idx``
    is the position in the gallery list (0-based) so renames /
    deletions inside the array shift indices, but the public URL
    shape stays simple."""
    p = db.session.get(Post, pid)
    if not p:
        abort(404)
    filenames = p.gallery_filenames
    if idx < 0 or idx >= len(filenames):
        abort(404)
    stored = filenames[idx]
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    thumb_arg = (request.args.get("thumb") or "").strip()
    if thumb_arg:
        from . import thumbnails
        try:
            size = int(thumb_arg)
        except ValueError:
            size = None
        if size and size in thumbnails.ALLOWED_SIZES:
            thumb_name = thumbnails.ensure_thumb(stored, size, upload_dir=upload_dir)
            if thumb_name:
                resp = send_from_directory(upload_dir, thumb_name)
                resp.headers["Cache-Control"] = "public, max-age=86400"
                return resp
    return send_from_directory(upload_dir, stored)


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
        q = q.filter(Story.is_archived.is_(True),
                     Story.is_pending_review.is_(False))
    elif show == "drafts":
        q = q.filter(Story.is_draft.is_(True),
                     Story.is_archived.is_(False),
                     Story.is_pending_review.is_(False))
    elif show == "pending":
        # Holding tank for visitor submissions awaiting admin review.
        q = q.filter(Story.is_pending_review.is_(True),
                     Story.is_archived.is_(False))
    else:
        show = "active"
        q = q.filter(Story.is_archived.is_(False),
                     Story.is_draft.is_(False),
                     Story.is_pending_review.is_(False))
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
    pending_count = (Story.query
                     .filter(Story.is_pending_review.is_(True),
                             Story.is_archived.is_(False)).count())
    return render_template("stories.html", stories=items, show=show, sort=sort,
                           pending_count=pending_count)


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

    # Saving a pending-review submission always clears that flag —
    # the admin is taking action on it (draft or publish). The
    # ``submission_*`` fields are preserved so the audit trail of who
    # submitted it survives the approval.
    if story.is_pending_review:
        story.is_pending_review = False

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
    old_attachment = story.submission_attachment_filename
    body_inline_stored = _collect_body_inline_stored(story.body)
    story.featured_image_filename = None
    story.submission_attachment_filename = None
    if old_image:
        _cleanup_retired_asset(old_image)
    if old_attachment:
        # Submission attachments are admin-only artifacts — they
        # never get referenced elsewhere, so a straight unlink is
        # enough. _cleanup_retired_asset's reference check would also
        # work, but the path isn't indexed in MediaItem, so we skip
        # the round-trip.
        try:
            import os
            target = os.path.join(current_app.config["UPLOAD_FOLDER"], old_attachment)
            if os.path.isfile(target):
                os.remove(target)
        except OSError:
            pass
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


@bp.route("/stories/<int:sid>/approve-pending", methods=["POST"])
@login_required
def story_approve_pending(sid):
    """Flip a pending-review story into a regular draft so the admin
    can edit it normally. Same pattern Post uses for its own holding
    tank — the submission's ``submitter_*`` fields are preserved on
    the row as the audit trail. The admin lands on the story-edit
    page so they can pick up where the submitter left off."""
    _require_stories_enabled()
    story = db.session.get(Story, sid) or abort(404)
    if not story.is_pending_review:
        return redirect(_safe_referrer() or url_for("main.stories"))
    story.is_pending_review = False
    story.is_draft = True
    db.session.commit()
    from . import activity
    activity.log("story.approve_pending", entity_type="story", entity_id=story.id,
                 summary=f"Approved submission “{story.title}” to draft")
    flash("Submission moved to drafts. Edit the story below before publishing.", "success")
    return redirect(url_for("main.story_edit", sid=story.id))


@bp.route("/stories/<int:sid>/attachment")
@login_required
def story_submission_attachment(sid):
    """Stream the submitter's uploaded attachment back to the admin.
    Lives under the gated ``/stories/...`` namespace so only signed-in
    users with the stories module can pull these files — the public
    ``/pub/...`` route doesn't index them. Filename in the
    Content-Disposition header is the submitter's original filename
    (sanitised on save) so the download arrives with a recognisable
    name even though the on-disk file is UUID-prefixed."""
    _require_stories_enabled()
    story = db.session.get(Story, sid) or abort(404)
    stored = story.submission_attachment_filename
    if not stored:
        abort(404)
    import os
    target = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
    if not os.path.isfile(target):
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"], stored,
        as_attachment=True,
        download_name=story.submission_attachment_original or stored,
    )


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
    """Legacy redirect — the standalone Web Frontend Visitor Metrics
    page was folded into the Watchtower Visitors tab so all traffic
    insight lives in one place. The query string carries through so
    bookmarked `?window=...` links keep working."""
    qs = request.query_string.decode() if request.query_string else ""
    target = url_for("main.watchtower_visitors")
    if qs:
        target = f"{target}?{qs}"
    return redirect(target, code=301)


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


