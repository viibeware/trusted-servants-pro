# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import os
import time
import uuid
from functools import wraps
from flask import (Blueprint, render_template, redirect, url_for, request,
                   flash, send_from_directory, abort, current_app, jsonify)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from .models import (db, User, Meeting, MeetingFile, MeetingSchedule, MeetingLibrary, CustomIcon, CustomFont, CustomLayout, FrontendHeroButton,
                     Post, ZoomAccount, ZoomOtpEmail, Location, Library, Reading,
                     LibraryCategory, MediaItem, NavLink, SiteSetting,
                     IntergroupAccount, AccessRequest, FrontendNavItem,
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


def editor_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.can_edit():
            flash("You don't have permission to do that", "danger")
            return redirect(request.referrer or url_for("main.index"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.is_admin():
            flash("Admins only", "danger")
            return redirect(request.referrer or url_for("main.index"))
        return f(*args, **kwargs)
    return wrapper


def frontend_editor_required(f):
    """Admins and frontend_editor role can reach Web Frontend editor routes."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.can_edit_frontend():
            flash("You don't have permission to edit the web frontend", "danger")
            return redirect(request.referrer or url_for("main.index"))
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
        return redirect(request.referrer or url_for("main.index"))
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
    try:
        if current_user.is_authenticated and current_user.is_admin():
            pending_access_count = AccessRequest.query.filter_by(
                status="pending", is_archived=False).count()
    except Exception:
        pending_access_count = 0
    try:
        otp = _get_otp_email()
    except Exception:
        otp = None
    return {"CATEGORY_LABELS": CATEGORY_LABELS, "FILE_CATEGORIES": FILE_CATEGORIES,
            "DAYS_OF_WEEK": DAYS_OF_WEEK, "site": site, "nav_links": nav_links,
            "pending_access_count": pending_access_count, "otp": otp}


DASHBOARD_WIDGET_KEYS = ("server-metrics", "meetings", "libraries", "files", "access-requests")

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


@bp.before_app_request
def _track_last_seen():
    """Throttled last_seen_at update for the authenticated user."""
    if not getattr(current_user, "is_authenticated", False):
        return
    now = datetime.utcnow()
    last = getattr(current_user, "last_seen_at", None)
    if last is not None and (now - last) < LAST_SEEN_THROTTLE:
        return
    try:
        current_user.last_seen_at = now
        db.session.commit()
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
    online_count = 0
    online_users = []
    locked_accounts = []
    if current_user.is_admin():
        access_requests = (AccessRequest.query
                           .filter_by(status="pending", is_archived=False)
                           .order_by(AccessRequest.created_at.desc())
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
    dashboard_order = _dashboard_order(current_user)
    return render_template("index.html", meetings=meetings, libraries=libraries,
                           recent_files=recent_files, access_requests=access_requests,
                           online_count=online_count, online_users=online_users,
                           locked_accounts=locked_accounts,
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
    db.session.commit()
    flash("Dashboard updated", "success")
    return redirect(url_for("main.index"))


@bp.route("/api/server-metrics")
@editor_required
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
        {"username": u.username, "role": u.role,
         "last_seen_at": u.last_seen_at.isoformat() + "Z" if u.last_seen_at else None}
        for u in users
    ])


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
    archived_count = Meeting.query.filter(Meeting.archived_at.isnot(None)).count()
    resp = current_app.make_response(
        render_template("meetings.html", meetings=items,
                        zoom_accounts=zoom_accounts, locations=locations,
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
    selected_readings = []
    public_readings = []
    for lid in ids:
        lib = db.session.get(Library, lid)
        if not lib:
            continue
        mode = form.get(f"library_mode_{lid}", "all")
        if mode not in ("all", "granular"):
            mode = "all"
        m.library_assocs.append(MeetingLibrary(library=lib, mode=mode))
        if mode == "granular":
            rids = form.getlist(f"library_readings_{lid}", type=int)
            if rids:
                selected_readings.extend(
                    Reading.query.filter(Reading.id.in_(rids),
                                         Reading.library_id == lid).all()
                )
        # Per-library, per-reading public-frontend visibility (independent of
        # the granular-mode selection above — admins may want to surface a
        # reading on the public page even if the meeting is in "all" mode).
        prids = form.getlist(f"library_public_readings_{lid}", type=int)
        if prids:
            public_readings.extend(
                Reading.query.filter(Reading.id.in_(prids),
                                     Reading.library_id == lid).all()
            )
    m.selected_readings = selected_readings
    m.public_readings = public_readings


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
@editor_required
def meeting_new():
    schedules, err = _parse_schedule_form(request.form)
    if err:
        flash(err, "danger")
        return redirect(url_for("main.meetings"))
    m = Meeting(name=request.form["name"].strip())
    _apply_meeting_form(m, request.form, schedules, request.files)
    db.session.add(m)
    db.session.commit()
    flash("Meeting created", "success")
    return redirect(url_for("main.meeting_detail", mid=m.id))


@bp.route("/meetings/<int:mid>")
@login_required
def meeting_detail(mid):
    m = db.session.get(Meeting, mid) or abort(404)
    all_libraries = Library.query.order_by(Library.name).all()
    zoom_accounts = ZoomAccount.query.order_by(ZoomAccount.name).all()
    locations = Location.query.order_by(Location.name).all()
    zoom_password = decrypt(m.zoom_account.password_enc) if m.zoom_account else ""
    otp_email = ZoomOtpEmail.query.first()
    return render_template("meeting_detail.html", meeting=m,
                           all_libraries=all_libraries, zoom_accounts=zoom_accounts,
                           locations=locations, zoom_account_password=zoom_password,
                           otp_email=otp_email)


@bp.route("/meetings/<int:mid>/edit", methods=["POST"])
@editor_required
def meeting_edit(mid):
    m = db.session.get(Meeting, mid) or abort(404)
    schedules, err = _parse_schedule_form(request.form, meeting_id=mid)
    if err:
        flash(err, "danger")
        return redirect(request.referrer or url_for("main.meeting_detail", mid=mid))
    _apply_meeting_form(m, request.form, schedules, request.files)
    if "library_ids" in request.form:
        _apply_library_selections(m, request.form)
    db.session.commit()
    flash("Meeting updated", "success")
    return redirect(url_for("main.meeting_detail", mid=m.id))


@bp.route("/meetings/<int:mid>.json")
@login_required
def meeting_json(mid):
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


@bp.route("/meetings/<int:mid>/delete", methods=["POST"])
@editor_required
def meeting_delete(mid):
    m = db.session.get(Meeting, mid) or abort(404)
    db.session.delete(m)
    db.session.commit()
    flash("Meeting deleted", "success")
    return redirect(url_for("main.meetings"))


@bp.route("/meetings/<int:mid>/archive", methods=["POST"])
@admin_required
def meeting_archive(mid):
    from datetime import datetime
    m = db.session.get(Meeting, mid) or abort(404)
    m.archived_at = datetime.utcnow()
    db.session.commit()
    flash(f"Archived “{m.name}”", "success")
    return redirect(url_for("main.meetings"))


@bp.route("/meetings/<int:mid>/unarchive", methods=["POST"])
@admin_required
def meeting_unarchive(mid):
    m = db.session.get(Meeting, mid) or abort(404)
    m.archived_at = None
    db.session.commit()
    flash(f"Restored “{m.name}”", "success")
    return redirect(url_for("main.meetings", show="archived"))


@bp.route("/meetings/<int:mid>/libraries", methods=["POST"])
@editor_required
def meeting_libraries(mid):
    m = db.session.get(Meeting, mid) or abort(404)
    ids = request.form.getlist("library_ids", type=int)
    m.libraries = Library.query.filter(Library.id.in_(ids)).all() if ids else []
    db.session.commit()
    flash("Libraries updated for meeting", "success")
    return redirect(url_for("main.meeting_detail", mid=m.id))


# --- Locations ---

@bp.route("/locations")
@login_required
def locations():
    if not current_user.is_admin():
        flash("Admins only", "danger")
        return redirect(url_for("main.index"))
    items = Location.query.order_by(Location.name).all()
    return render_template("locations.html", locations=items)


@bp.route("/locations/new", methods=["POST"])
@admin_required
def location_new():
    name = request.form["name"].strip()
    ltype = request.form.get("location_type", "in_person")
    if ltype not in ("in_person", "online"):
        ltype = "in_person"
    address = request.form.get("address", "").strip() or None
    maps_url = request.form.get("maps_url", "").strip() or None
    if ltype == "online":
        address = None
        maps_url = None
    if not name:
        flash("Name required", "danger")
    elif Location.query.filter_by(name=name).first():
        flash("Location already exists", "danger")
    else:
        db.session.add(Location(name=name, location_type=ltype,
                                address=address, maps_url=maps_url))
        db.session.commit()
        flash("Location added", "success")
    return redirect(url_for("main.locations", **({"embed": "1"} if request.values.get("embed") == "1" else {})))


@bp.route("/locations/<int:lid>/edit", methods=["POST"])
@admin_required
def location_edit(lid):
    loc = db.session.get(Location, lid) or abort(404)
    loc.name = request.form["name"].strip()
    ltype = request.form.get("location_type", "in_person")
    if ltype not in ("in_person", "online"):
        ltype = "in_person"
    loc.location_type = ltype
    if ltype == "online":
        loc.address = None
        loc.maps_url = None
    else:
        loc.address = request.form.get("address", "").strip() or None
        loc.maps_url = request.form.get("maps_url", "").strip() or None
    db.session.commit()
    flash("Location updated", "success")
    return redirect(url_for("main.locations", **({"embed": "1"} if request.values.get("embed") == "1" else {})))


@bp.route("/locations/<int:lid>/delete", methods=["POST"])
@admin_required
def location_delete(lid):
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
    return redirect(request.referrer or url_for("main.nav_links"))


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
    return redirect(request.referrer or url_for("main.index"))


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
    return redirect(request.referrer or url_for("main.index"))


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


@bp.route("/intergroup")
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


@bp.route("/intergroup/edit", methods=["GET", "POST"])
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
    return redirect(request.referrer or url_for("main.index"))


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
        from .sidebar import _INTERGROUP_CATALOG  # noqa: WPS437
        valid_intergroup = {it["key"] for it in _INTERGROUP_CATALOG}
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
    return redirect(request.referrer or url_for("main.index"))


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
        "frontend_module":   "frontend_module_required_role",
    }
    col = columns.get(module)
    if col and role in ROLE_TIER_KEYS:
        setattr(s, col, role)
        db.session.commit()
        flash("Module access saved", "success")
    return redirect(request.referrer or url_for("main.index"))


@bp.route("/settings/posts-toggle", methods=["POST"])
@admin_required
def posts_toggle():
    s = _get_site_setting()
    s.posts_enabled = request.form.get("posts_enabled") == "1"
    db.session.commit()
    flash("Announcements & Events " + ("enabled" if s.posts_enabled else "disabled"), "success")
    return redirect(request.referrer or url_for("main.index"))


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
        return redirect(request.referrer or url_for("main.index"))
    if request.form.get("confirm") != "REPLACE":
        flash('Type REPLACE in the confirmation box to proceed — import overwrites all data', "danger")
        return redirect(request.referrer or url_for("main.index"))

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
                    return redirect(request.referrer or url_for("main.index"))
                for n in names:
                    if n.startswith("/") or ".." in n.split("/"):
                        flash(f"Archive contains unsafe path: {n}", "danger")
                        return redirect(request.referrer or url_for("main.index"))
                try:
                    manifest = json.loads(z.read("manifest.json").decode("utf-8"))
                    if manifest.get("app") not in ("trusted-servants-pro", "trusted-servants-portal"):
                        flash("Archive manifest does not identify a Trusted Servants Pro export", "danger")
                        return redirect(request.referrer or url_for("main.index"))
                except (ValueError, UnicodeDecodeError):
                    flash("Archive manifest.json is invalid", "danger")
                    return redirect(request.referrer or url_for("main.index"))
                extract_dir = os.path.join(staging, "extracted")
                os.makedirs(extract_dir, exist_ok=True)
                z.extractall(extract_dir)
        except zipfile.BadZipFile:
            flash("File is not a valid zip archive", "danger")
            return redirect(request.referrer or url_for("main.index"))

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
_FRONTEND_SETTING_KEYS = (
    # Core content
    "frontend_enabled", "frontend_title", "frontend_tagline",
    "frontend_hero_heading", "frontend_hero_subheading",
    "frontend_about_heading", "frontend_about_body",
    "frontend_contact_heading", "frontend_contact_body",
    "frontend_footer_text",
    # Layout / templates
    "frontend_header_width_mode", "frontend_header_max_width",
    "frontend_header_padding_pct", "frontend_header_height",
    "frontend_header_template", "frontend_footer_template",
    "frontend_homepage_template", "frontend_megamenu_template",
    "frontend_meeting_template", "frontend_event_template",
    # Mega menu styling
    "frontend_mega_bg_color", "frontend_mega_text_color",
    "frontend_mega_radius_bl", "frontend_mega_radius_br",
    # Logos
    "frontend_logo_filename", "frontend_logo_width",
    "footer_logo_filename", "footer_logo_url", "footer_logo_width",
    # Alerts (frontend-only)
    "top_alert_enabled", "top_alert_message",
    "top_alert_bg_color", "top_alert_text_color",
    "top_alert_icon", "top_alert_icon_position",
    "header_alert_enabled", "header_alert_message",
    "header_alert_bg_color", "header_alert_text_color",
    "header_alert_icon", "header_alert_icon_position",
    # Social sharing — public-facing (frontend OG, distinct from backend og_*)
    "frontend_og_enabled", "frontend_og_title",
    "frontend_og_description", "frontend_og_image_filename",
)

# Setting keys that point at an uploaded filename. These drive asset bundling.
_FRONTEND_ASSET_KEYS = (
    "frontend_logo_filename", "footer_logo_filename", "frontend_og_image_filename",
    "frontend_favicon_filename",
)


def _frontend_export_payload():
    from .models import SiteSetting
    s = _get_site_setting()
    settings = {k: getattr(s, k, None) for k in _FRONTEND_SETTING_KEYS}
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
                    "override_color": bool(l.override_color),
                    "custom_color": l.custom_color,
                    "button_style": l.button_style,
                    "open_in_new_tab": bool(l.open_in_new_tab),
                })
            cols.append({
                "position": c.position, "heading": c.heading, "links": links,
            })
        nav_items.append({
            "position": it.position, "style": it.style, "label": it.label,
            "line1": it.line1, "line2": it.line2, "url": it.url,
            "has_megamenu": bool(it.has_megamenu),
            "open_in_new_tab": bool(it.open_in_new_tab),
            "columns": cols,
        })
    assets = sorted({fn for fn in (settings.get(k) for k in _FRONTEND_ASSET_KEYS) if fn})
    return {
        "kind": "frontend", "format_version": 1,
        "settings": settings, "nav_items": nav_items,
        "assets": list(assets),
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


@bp.route("/settings/wp-import-posts", methods=["POST"])
@admin_required
def data_wp_import_posts():
    """Import a WP All Export "Posts" CSV into a Library as Readings.

    The export ships one row per post; we filter by category, take the
    title, and download the post's primary attachment (when the export
    populated ``Attachment URL``) into uploads. The resulting Reading
    holds the post title and links to the freshly-stored file.

    Use case: pulling the legacy "Intergroup Minutes" archive from
    DCCMA's WP into the new portal without manually re-uploading each
    monthly minutes document."""
    import csv as _csv
    import io
    import requests

    f = request.files.get("csv")
    if not f or not f.filename:
        flash("Please choose a CSV file to import.", "danger")
        return redirect(request.referrer or url_for("main.index"))

    library_name = (request.form.get("library_name") or "").strip()[:200]
    category_filter = (request.form.get("category_filter") or "").strip()
    if not library_name or not category_filter:
        flash("Library name and category filter are both required.", "danger")
        return redirect(request.referrer or url_for("main.index"))

    # Decode CSV (handle BOM)
    try:
        raw = f.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            raw = f.read().decode("latin-1")
        except UnicodeDecodeError:
            flash("Could not decode the CSV — expected UTF-8.", "danger")
            return redirect(request.referrer or url_for("main.index"))
    reader = _csv.DictReader(io.StringIO(raw))

    # Find or create the destination library.
    lib = Library.query.filter_by(name=library_name).first()
    if not lib:
        lib = Library(name=library_name)
        db.session.add(lib)
        db.session.flush()

    existing_titles = {r.title.strip() for r in lib.readings}
    next_position = (db.session.query(db.func.max(Reading.position))
                     .filter_by(library_id=lib.id).scalar() or 0) + 1

    imported = 0
    skipped_no_url = 0
    skipped_dup = 0
    download_failed = 0

    for row in reader:
        cats = (row.get("Categories") or "").strip()
        if category_filter.lower() not in cats.lower():
            continue
        title = (row.get("Title") or "").strip()
        if not title:
            continue
        if title in existing_titles:
            skipped_dup += 1
            continue
        url = (row.get("Attachment URL") or "").strip()
        original_name = (row.get("Attachment Filename") or "").strip()
        stored = None
        original = None
        if url:
            try:
                resp = requests.get(url, timeout=30, stream=True,
                                    headers={"User-Agent": "tspro-wp-importer/1.0"})
                resp.raise_for_status()
                data = resp.content
            except Exception:
                download_failed += 1
                continue
            # Pick a sensible original filename. Prefer the WP-supplied
            # one; fall back to the URL's basename.
            if not original_name:
                from urllib.parse import urlparse, unquote
                original_name = unquote(os.path.basename(urlparse(url).path)) or "minutes"
            ext = os.path.splitext(original_name)[1].lower()
            if ext in BLOCKED_UPLOAD_EXTENSIONS:
                download_failed += 1
                continue
            # Dedup by content hash via the existing MediaItem table.
            h = hashlib.sha256(data).hexdigest()
            media = MediaItem.query.filter_by(content_hash=h).first()
            if media:
                stored = media.stored_filename
                original = media.original_filename
            else:
                stored = f"{uuid.uuid4().hex}{ext}"
                with open(os.path.join(current_app.config["UPLOAD_FOLDER"], stored), "wb") as out:
                    out.write(data)
                m = MediaItem(stored_filename=stored,
                              original_filename=secure_filename(original_name),
                              content_hash=h, size_bytes=len(data),
                              mime_type=resp.headers.get("Content-Type"),
                              uploaded_by=getattr(current_user, "id", None))
                db.session.add(m)
                db.session.flush()
                original = m.original_filename
        else:
            skipped_no_url += 1
            continue

        r = Reading(
            library_id=lib.id,
            title=title,
            stored_filename=stored,
            original_filename=original,
            position=next_position,
            created_by=current_user.id,
        )
        db.session.add(r)
        existing_titles.add(title)
        next_position += 1
        imported += 1

    db.session.commit()

    parts = [f"Imported {imported} reading{'s' if imported != 1 else ''} into '{lib.name}'."]
    if skipped_dup:
        parts.append(f"{skipped_dup} skipped (title already in library).")
    if skipped_no_url:
        parts.append(f"{skipped_no_url} skipped (no Attachment URL in CSV).")
    if download_failed:
        parts.append(f"{download_failed} skipped (download failed or unsupported file type).")
    flash(" ".join(parts), "success" if imported else "info")
    return redirect(request.referrer or url_for("main.library_detail", lid=lib.id))


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
    return redirect(request.referrer or url_for("main.index"))


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
        "format_version": 1,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "content_filename": "frontend.json",
        "assets_dir": "assets/",
        "note": "Scoped frontend bundle. Import via the Data tab on another install to overlay frontend content, navigation, and assets without touching users, meetings, or libraries.",
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
        return redirect(request.referrer or url_for("main.index"))
    if request.form.get("confirm") != "REPLACE":
        flash('Type REPLACE in the confirmation box to overwrite frontend content', "danger")
        return redirect(request.referrer or url_for("main.index"))

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
                        return redirect(request.referrer or url_for("main.index"))
                if "frontend.json" not in names or "manifest.json" not in names:
                    flash("Archive is missing frontend.json or manifest.json — not a valid frontend bundle", "danger")
                    return redirect(request.referrer or url_for("main.index"))
                try:
                    manifest = json.loads(z.read("manifest.json").decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    flash("Archive manifest.json is invalid", "danger")
                    return redirect(request.referrer or url_for("main.index"))
                if manifest.get("app") not in ("trusted-servants-pro", "trusted-servants-portal"):
                    flash("Archive manifest does not identify a Trusted Servants Pro export", "danger")
                    return redirect(request.referrer or url_for("main.index"))
                if manifest.get("kind") != "frontend":
                    flash("This looks like a full archive, not a frontend bundle. Use the Import &amp; Replace form instead.", "danger")
                    return redirect(request.referrer or url_for("main.index"))
                try:
                    payload = json.loads(z.read("frontend.json").decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    flash("Archive frontend.json is invalid", "danger")
                    return redirect(request.referrer or url_for("main.index"))
                extract_dir = os.path.join(staging, "extracted")
                os.makedirs(extract_dir, exist_ok=True)
                z.extractall(extract_dir)
        except zipfile.BadZipFile:
            flash("File is not a valid zip archive", "danger")
            return redirect(request.referrer or url_for("main.index"))

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
        s = _get_site_setting()
        incoming = payload.get("settings") or {}
        for key in _FRONTEND_SETTING_KEYS:
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
                    _lsz = (nl.get("link_size") or "").strip().lower() or None
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
                        override_color=bool(nl.get("override_color")),
                        custom_color=_sanitize_icon_color(nl.get("custom_color")),
                        button_style=(nl.get("button_style") or "pill"),
                        open_in_new_tab=bool(nl.get("open_in_new_tab")),
                    )
                    db.session.add(link)

        db.session.commit()

        from . import _backfill_media
        _backfill_media(current_app)

        flash("Frontend bundle imported — content, navigation, and assets are in place.", "success")
        return redirect(request.referrer or url_for("main.frontend_dashboard"))
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
    return redirect(request.referrer or url_for("main.index"))


@bp.route("/settings/intergroup-toggle", methods=["POST"])
@admin_required
def intergroup_toggle():
    s = _get_site_setting()
    s.intergroup_enabled = request.form.get("intergroup_enabled") == "1"
    db.session.commit()
    flash("Intergroup page " + ("enabled" if s.intergroup_enabled else "disabled"), "success")
    return redirect(request.referrer or url_for("main.index"))


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
    return redirect(request.referrer or url_for("main.index"))


@public_bp.route("/site-branding/footer-logo")
def site_footer_logo():
    s = _get_site_setting()
    if not s.footer_logo_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], s.footer_logo_filename)


_HERO_BG_STYLES = {"frosty", "solid", "gradient", "image", "sinewave", "video"}
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


@bp.route("/frontend/save", methods=["POST"])
@frontend_editor_required
def frontend_save():
    """Save homepage text content (branding, about, contact, block content).
    Hero options are saved by frontend_hero_save. Public toggle state and
    footer text are handled by frontend_toggle / frontend_footer_save."""
    import json as _json
    from .blocks import (site_blocks, parse_features, parse_stats,
                         parse_testimonials, parse_faq, parse_quick_links,
                         parse_cta)
    s = _get_site_setting()
    for col in ("frontend_title",
                "frontend_about_heading", "frontend_contact_heading"):
        setattr(s, col, (request.form.get(col) or "").strip() or None)
    for col in ("frontend_about_body", "frontend_contact_body"):
        setattr(s, col, (request.form.get(col) or "").strip() or None)

    # Block content. Only update keys that arrived in this submission so
    # editors hidden by the active layout's block list aren't blanked out.
    blocks = site_blocks(s)  # current values, including defaults
    if "block_features" in request.form:
        blocks["features"] = parse_features(request.form.get("block_features"))
    if "block_stats" in request.form:
        blocks["stats"] = parse_stats(request.form.get("block_stats"))
    if "block_testimonials" in request.form:
        blocks["testimonials"] = parse_testimonials(request.form.get("block_testimonials"))
    if "block_faq" in request.form:
        blocks["faq"] = parse_faq(request.form.get("block_faq"))
    if "block_quick_links" in request.form:
        blocks["quick_links"] = parse_quick_links(request.form.get("block_quick_links"))
    if "block_cta_heading" in request.form:
        blocks["cta"] = parse_cta(request.form)

    # Per-block visibility toggles. The form posts `block_visible_<type>`
    # only for blocks the active layout actually renders — we read those
    # and merge into the existing visibility map, so toggling on layout A
    # doesn't blank out layout B's settings.
    vis = dict(blocks.get("_visibility") or {})
    # Drop any stray "present" marker from earlier saves that got mis-stored
    # as a real block-visibility entry.
    vis.pop("present", None)
    for key in list(request.form.keys()):
        if key == "block_visible_present":
            continue  # this is the multi-valued marker, not a real toggle
        if key.startswith("block_visible_"):
            vis[key[len("block_visible_"):]] = (request.form.get(key) == "1")
    # If a block editor was rendered but its checkbox is absent (i.e. user
    # unticked it), the form simply omits the key — checkboxes don't post
    # when unchecked. So we also need to inspect the form's "visibility
    # editors present" marker. The homepage admin form posts a hidden
    # `block_visible_present` for every block that has a toggle; we use
    # that to detect "absent because unchecked" vs "absent because the
    # block isn't on this page".
    present = set((request.form.getlist("block_visible_present") or []))
    for bt in present:
        if "block_visible_" + bt not in request.form:
            vis[bt] = False
    blocks["_visibility"] = vis

    # Meetings settings (only updated when the meetings editor was on the
    # form, signaled by a meetings_filter field).
    if "meetings_filter" in request.form:
        ms = dict(blocks.get("_meetings") or {})
        f = (request.form.get("meetings_filter") or "upcoming_today").strip()
        if f in {"today_all","upcoming_today","next_24h","next_7_days","this_week","all"}:
            ms["filter"] = f
        ms["heading"] = (request.form.get("meetings_heading") or "").strip() or "Upcoming Meetings"
        ms["intro"] = (request.form.get("meetings_intro") or "").strip()
        ms["empty_message"] = (request.form.get("meetings_empty_message") or "").strip() or "No meetings scheduled — check back soon."
        try: ms["max_count"] = max(1, min(30, int(request.form.get("meetings_max_count", 6))))
        except (TypeError, ValueError): ms["max_count"] = 6
        try: ms["show_first_n"] = max(1, min(7, int(request.form.get("meetings_show_first_n", 3))))
        except (TypeError, ValueError): ms["show_first_n"] = 3
        try: ms["stagger_ms"] = max(0, min(200, int(request.form.get("meetings_stagger_ms", 60))))
        except (TypeError, ValueError): ms["stagger_ms"] = 60
        a = (request.form.get("meetings_animation") or "fade").strip()
        ms["animation"] = a if a in {"fade","slide","none"} else "fade"
        ms["group_by_day"] = request.form.get("meetings_group_by_day") == "1"
        ms["show_type_chip"] = request.form.get("meetings_show_type_chip") == "1"
        ms["show_schedule"] = request.form.get("meetings_show_schedule") == "1"
        blocks["_meetings"] = ms

    # Events block settings — persisted under _events similar to _meetings.
    # The presence of an `events_heading` field signals the events editor
    # was on the form; we read every related field together so partial
    # writes don't blank out unsaved sub-fields.
    if "events_heading" in request.form:
        es = dict(blocks.get("_events") or {})
        es["heading"] = (request.form.get("events_heading") or "").strip() or "Upcoming Events"
        es["intro"] = (request.form.get("events_intro") or "").strip()
        es["empty_message"] = (request.form.get("events_empty_message") or "").strip() or "No upcoming events — check back soon."
        try: es["max_count"] = max(1, min(24, int(request.form.get("events_max_count", 6))))
        except (TypeError, ValueError): es["max_count"] = 6
        try: es["stagger_ms"] = max(0, min(200, int(request.form.get("events_stagger_ms", 60))))
        except (TypeError, ValueError): es["stagger_ms"] = 60
        a = (request.form.get("events_animation") or "fade").strip()
        es["animation"] = a if a in {"fade","slide","none"} else "fade"
        es["show_image"] = request.form.get("events_show_image") == "1"
        es["show_summary"] = request.form.get("events_show_summary") == "1"
        es["show_location"] = request.form.get("events_show_location") == "1"
        blocks["_events"] = es

    s.frontend_blocks_json = _json.dumps(blocks)

    # Two-panel split settings live on each split block in the active
    # layout's blocks_json. We mutate the CustomLayout row in place.
    # Form fields are scoped by split index ("split_0_width",
    # "split_1_padding", ...) so multiple splits in one layout each
    # get their own settings.
    present_indices = set()
    for raw in request.form.getlist("split_present") or []:
        try: present_indices.add(int(raw))
        except (TypeError, ValueError): pass
    if present_indices:
        active_key = (s.frontend_homepage_template or "classic")
        layout = CustomLayout.query.filter_by(key=active_key, kind="homepage").first()
        if layout and not layout.is_prebuilt:
            try:
                seq = _json.loads(layout.blocks_json or "[]") or []
            except (ValueError, TypeError):
                seq = []
            split_idx = 0
            for b in seq:
                if not (isinstance(b, dict) and b.get("type") == "split"):
                    continue
                if split_idx in present_indices:
                    def _set_spacing(key, form_key):
                        v = (request.form.get(form_key) or "").strip().lower()
                        if v in _SPLIT_VALID_SPACING: b[key] = v
                    w = (request.form.get(f"split_{split_idx}_width") or "").strip().lower()
                    if w in _SPLIT_VALID_WIDTHS: b["width"] = w
                    _set_spacing("padding",    f"split_{split_idx}_padding")
                    _set_spacing("gap",        f"split_{split_idx}_gap")
                    _set_spacing("gap_top",    f"split_{split_idx}_gap_top")
                    _set_spacing("gap_bottom", f"split_{split_idx}_gap_bottom")
                    def _set_bg(json_key, form_prefix):
                        if request.form.get(f"{form_prefix}_enabled") == "1":
                            v = (request.form.get(form_prefix) or "").strip()
                            if v and _SPLIT_HEX_RE.match(v):
                                b[json_key] = v
                            else:
                                b.pop(json_key, None)
                        else:
                            b.pop(json_key, None)
                    _set_bg("bg_color",       f"split_{split_idx}_bg_color")
                    _set_bg("bg_color_left",  f"split_{split_idx}_bg_color_left")
                    _set_bg("bg_color_right", f"split_{split_idx}_bg_color_right")
                    if request.form.get(f"split_{split_idx}_bg_dark_mode") == "1":
                        b["bg_dark_mode"] = True
                    else:
                        b.pop("bg_dark_mode", None)
                    # Legacy `margin` field is no longer written; remove
                    # it on first save so the JSON stays clean.
                    b.pop("margin", None)
                split_idx += 1
            layout.blocks_json = _json.dumps(seq)

    db.session.commit()
    flash("Homepage content saved", "success")
    return redirect(url_for("main.frontend_homepage"))


@bp.route("/frontend/hero/save", methods=["POST"])
@frontend_editor_required
def frontend_hero_save():
    """Save all hero options (text, typography, background, image)."""
    s = _get_site_setting()
    for col in ("frontend_hero_heading", "frontend_hero_subheading", "frontend_tagline"):
        setattr(s, col, (request.form.get(col) or "").strip() or None)
    s.frontend_tagline_enabled = request.form.get("frontend_tagline_enabled") == "1"

    # Heading typography
    font = (request.form.get("frontend_hero_heading_font") or "fraunces").strip().lower()
    s.frontend_hero_heading_font = font if font in _HERO_HEADING_FONTS else "fraunces"
    s.frontend_hero_heading_size = _clamp_int(request.form.get("frontend_hero_heading_size"), 50, 200, 100)
    s.frontend_hero_heading_grad_start = _sanitize_icon_color(request.form.get("frontend_hero_heading_grad_start"))
    s.frontend_hero_heading_grad_end = _sanitize_icon_color(request.form.get("frontend_hero_heading_grad_end"))
    if request.form.get("reset_heading_colors") == "1":
        s.frontend_hero_heading_grad_start = None
        s.frontend_hero_heading_grad_end = None
    s.frontend_hero_text_dynamic = request.form.get("frontend_hero_text_dynamic") == "1"

    # Hero background generator
    bg_style = (request.form.get("frontend_hero_bg_style") or "frosty").strip().lower()
    s.frontend_hero_bg_style = bg_style if bg_style in _HERO_BG_STYLES else "frosty"
    s.frontend_hero_bg_color = _sanitize_icon_color(request.form.get("frontend_hero_bg_color"))
    s.frontend_hero_bg_color_2 = _sanitize_icon_color(request.form.get("frontend_hero_bg_color_2"))
    s.frontend_hero_bg_gradient_angle = _clamp_int(request.form.get("frontend_hero_bg_gradient_angle"), 0, 360, 180)
    s.frontend_hero_bg_hue = _clamp_int(request.form.get("frontend_hero_bg_hue"), 0, 360, 225)
    s.frontend_hero_bg_hue_2 = _clamp_int(request.form.get("frontend_hero_bg_hue_2"), 0, 360, 170)
    s.frontend_hero_bg_blur = _clamp_int(request.form.get("frontend_hero_bg_blur"), 0, 200, 80)
    s.frontend_hero_bg_opacity = _clamp_int(request.form.get("frontend_hero_bg_opacity"), 0, 100, 45)
    s.frontend_hero_bg_randomize = request.form.get("frontend_hero_bg_randomize") == "1"

    # Hero background image
    mode = (request.form.get("frontend_hero_bg_image_mode") or "cover").strip().lower()
    s.frontend_hero_bg_image_mode = mode if mode in _HERO_IMAGE_MODES else "cover"
    s.frontend_hero_bg_image_scale = _clamp_int(request.form.get("frontend_hero_bg_image_scale"), 10, 400, 100)

    # Sinewave: 1–4 hex colors → JSON list. If none valid, store NULL so the
    # frontend falls back to the default teal→blue→purple palette.
    import json as _json
    sw_colors = []
    for i in range(1, 5):
        c = (request.form.get(f"frontend_hero_sinewave_c{i}") or "").strip()
        if _HEX_COLOR_RE.match(c):
            sw_colors.append(c)
    s.frontend_hero_sinewave_colors = _json.dumps(sw_colors) if sw_colors else None

    # Hero background video (muted autoplay loop, object-fit: cover)
    s.frontend_hero_bg_video_mode = "loop"
    try:
        vsp = int(request.form.get("frontend_hero_bg_video_speed") or 100)
    except (TypeError, ValueError):
        vsp = 100
    s.frontend_hero_bg_video_speed = vsp if vsp in _HERO_VIDEO_SPEEDS else 100
    if request.form.get("clear_hero_bg_video") == "1":
        old_v = s.frontend_hero_bg_video_filename
        s.frontend_hero_bg_video_filename = None
        _cleanup_retired_asset(old_v)
    uploaded_v = request.files.get("frontend_hero_bg_video")
    if uploaded_v and uploaded_v.filename:
        old_v = s.frontend_hero_bg_video_filename
        stored, _original = _save_upload(uploaded_v)
        s.frontend_hero_bg_video_filename = stored
        if old_v and old_v != stored:
            _cleanup_retired_asset(old_v)

    # Particle overlay (works with any bg style)
    s.frontend_hero_particle_enabled = request.form.get("frontend_hero_particle_enabled") == "1"
    eff = (request.form.get("frontend_hero_particle_effect") or "stars").strip().lower()
    s.frontend_hero_particle_effect = eff if eff in _HERO_PARTICLE_EFFECTS else "stars"
    s.frontend_hero_particle_speed = _clamp_int(request.form.get("frontend_hero_particle_speed"), 10, 300, 100)
    s.frontend_hero_particle_size = _clamp_int(request.form.get("frontend_hero_particle_size"), 25, 400, 100)
    if request.form.get("clear_hero_bg_image") == "1":
        old = s.frontend_hero_bg_image_filename
        s.frontend_hero_bg_image_filename = None
        _cleanup_retired_asset(old)
    uploaded = request.files.get("frontend_hero_bg_image")
    if uploaded and uploaded.filename:
        old = s.frontend_hero_bg_image_filename
        stored, _original = _save_upload(uploaded)
        s.frontend_hero_bg_image_filename = stored
        if old and old != stored:
            _cleanup_retired_asset(old)

    db.session.commit()
    flash("Hero saved", "success")
    return redirect(url_for("main.frontend_homepage"))


# ---- Hero buttons (CRUD) ----
def _apply_hero_button_form(btn, form):
    btn.label = (form.get("label") or "").strip() or btn.label or "Button"
    btn.url = (form.get("url") or "").strip() or None
    style = (form.get("style") or "primary").strip().lower()
    btn.style = style if style in _HERO_BUTTON_STYLES else "primary"
    btn.custom_bg_color = _sanitize_icon_color(form.get("custom_bg_color"))
    btn.custom_text_color = _sanitize_icon_color(form.get("custom_text_color"))
    btn.icon_before = _sanitize_icon_name(form.get("icon_before"))
    btn.icon_after = _sanitize_icon_name(form.get("icon_after"))
    btn.icon_before_color = _sanitize_icon_color(form.get("icon_before_color"))
    btn.icon_after_color = _sanitize_icon_color(form.get("icon_after_color"))
    btn.icon_before_size = _sanitize_icon_size(form.get("icon_before_size"))
    btn.icon_after_size = _sanitize_icon_size(form.get("icon_after_size"))
    btn.open_in_new_tab = form.get("open_in_new_tab") == "1"


@bp.route("/frontend/hero-button/new", methods=["POST"])
@frontend_editor_required
def frontend_hero_button_new():
    max_pos = db.session.query(db.func.coalesce(db.func.max(FrontendHeroButton.position), -1)).scalar() + 1
    btn = FrontendHeroButton(label="New button", position=max_pos)
    _apply_hero_button_form(btn, request.form)
    db.session.add(btn)
    db.session.commit()
    return redirect(url_for("main.frontend_homepage"))


@bp.route("/frontend/hero-button/<int:bid>/edit", methods=["POST"])
@frontend_editor_required
def frontend_hero_button_edit(bid):
    btn = db.session.get(FrontendHeroButton, bid) or abort(404)
    _apply_hero_button_form(btn, request.form)
    db.session.commit()
    return redirect(url_for("main.frontend_homepage"))


@bp.route("/frontend/hero-button/<int:bid>/delete", methods=["POST"])
@frontend_editor_required
def frontend_hero_button_delete(bid):
    btn = db.session.get(FrontendHeroButton, bid) or abort(404)
    db.session.delete(btn)
    db.session.commit()
    return redirect(url_for("main.frontend_homepage"))


@bp.route("/frontend/hero-buttons/reorder", methods=["POST"])
@frontend_editor_required
def frontend_hero_buttons_reorder():
    payload = request.get_json(silent=True) or {}
    valid = {b.id for b in FrontendHeroButton.query.all()}
    for pos, bid in enumerate(payload.get("order") or []):
        try:
            bid_int = int(bid)
        except (TypeError, ValueError):
            continue
        if bid_int not in valid:
            continue
        btn = db.session.get(FrontendHeroButton, bid_int)
        if btn:
            btn.position = pos
    db.session.commit()
    return jsonify(ok=True)


@public_bp.route("/site-branding/hero-bg")
def site_hero_bg_image():
    s = SiteSetting.query.first()
    if not s or not s.frontend_hero_bg_image_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"],
                               s.frontend_hero_bg_image_filename)


@public_bp.route("/site-branding/hero-bg-video")
def site_hero_bg_video():
    s = SiteSetting.query.first()
    if not s or not s.frontend_hero_bg_video_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"],
                               s.frontend_hero_bg_video_filename)


@bp.route("/frontend/toggle", methods=["POST"])
@frontend_editor_required
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
    return redirect(request.referrer or url_for("main.index"))


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


@bp.route("/frontend/top-alert-save", methods=["POST"])
@frontend_editor_required
def frontend_top_alert_save():
    s = _get_site_setting()
    _apply_alert_form(s, request.form, "top")
    db.session.commit()
    flash("Top alert bar saved", "success")
    return redirect(url_for("main.frontend_header"))


@bp.route("/frontend/header-alert-save", methods=["POST"])
@frontend_editor_required
def frontend_header_alert_save():
    s = _get_site_setting()
    _apply_alert_form(s, request.form, "header")
    db.session.commit()
    flash("Under-header alert bar saved", "success")
    return redirect(url_for("main.frontend_header"))


@bp.route("/frontend/logo-save", methods=["POST"])
@frontend_editor_required
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
@frontend_editor_required
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
@frontend_editor_required
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
    db.session.commit()
    flash("Mega menu appearance saved", "success")
    return redirect(url_for("main.frontend_navigation"))


def _apply_nav_item_form(item, form):
    style = (form.get("style") or "text").strip()
    item.style = style if style in ("text", "button", "button-rounded", "two-line") else "text"
    item.url = (form.get("url") or "").strip() or None
    item.has_megamenu = form.get("has_megamenu") == "1"
    item.open_in_new_tab = form.get("open_in_new_tab") == "1"
    if item.style == "two-line":
        item.line1 = (form.get("line1") or "").strip() or None
        item.line2 = (form.get("line2") or "").strip() or None
        item.label = item.line1 or item.line2
    else:
        item.label = (form.get("label") or "").strip() or None
        item.line1 = item.line2 = None


@bp.route("/frontend/nav-item/new", methods=["POST"])
@frontend_editor_required
def frontend_nav_item_new():
    max_pos = db.session.query(db.func.max(FrontendNavItem.position)).scalar() or 0
    item = FrontendNavItem(position=max_pos + 1)
    _apply_nav_item_form(item, request.form)
    db.session.add(item)
    db.session.commit()
    flash("Nav item added", "success")
    return redirect(url_for("main.frontend_navigation"))


@bp.route("/frontend/nav-item/<int:nid>/edit", methods=["POST"])
@frontend_editor_required
def frontend_nav_item_edit(nid):
    item = db.session.get(FrontendNavItem, nid) or abort(404)
    _apply_nav_item_form(item, request.form)
    db.session.commit()
    flash("Nav item updated", "success")
    return redirect(request.referrer or url_for("main.frontend_header"))


@bp.route("/frontend/nav-item/<int:nid>/delete", methods=["POST"])
@frontend_editor_required
def frontend_nav_item_delete(nid):
    item = db.session.get(FrontendNavItem, nid) or abort(404)
    db.session.delete(item)
    db.session.commit()
    flash("Nav item deleted", "success")
    return redirect(url_for("main.frontend_navigation"))


@bp.route("/frontend/nav-items/reorder", methods=["POST"])
@frontend_editor_required
def frontend_nav_item_reorder():
    payload = request.get_json(silent=True) or {}
    for pos, iid in enumerate(payload.get("order") or []):
        row = db.session.get(FrontendNavItem, int(iid)) if str(iid).isdigit() else None
        if row:
            row.position = pos
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/frontend/nav-item/<int:nid>/megamenu")
@frontend_editor_required
def frontend_nav_megamenu(nid):
    item = db.session.get(FrontendNavItem, nid) or abort(404)
    return render_template("frontend_nav_megamenu.html", item=item, site=_get_site_setting())


# ---- Columns ----
@bp.route("/frontend/nav-item/<int:nid>/column/new", methods=["POST"])
@frontend_editor_required
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
@frontend_editor_required
def frontend_nav_column_edit(cid):
    col = db.session.get(FrontendNavColumn, cid) or abort(404)
    col.heading = (request.form.get("heading") or "").strip() or None
    db.session.commit()
    return redirect(url_for("main.frontend_nav_megamenu", nid=col.nav_item_id))


@bp.route("/frontend/nav-column/<int:cid>/delete", methods=["POST"])
@frontend_editor_required
def frontend_nav_column_delete(cid):
    col = db.session.get(FrontendNavColumn, cid) or abort(404)
    nid = col.nav_item_id
    db.session.delete(col)
    db.session.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True)
    return redirect(url_for("main.frontend_nav_megamenu", nid=nid))


@bp.route("/frontend/nav-item/<int:nid>/columns/reorder", methods=["POST"])
@frontend_editor_required
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
_NAV_BLOCK_KINDS = {"link", "title", "button", "section", "search"}
_NAV_BUTTON_STYLES = {"pill", "rounded"}
_NAV_LINK_SIZES = {"small", "large"}
_NAV_DEFAULT_LABEL = {
    "link": "New link", "title": "Section title",
    "button": "Call to action", "section": "Group heading",
    "search": "Search…",
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
        sz = (form.get("link_size") or "").strip().lower()
        link.link_size = sz if sz in _NAV_LINK_SIZES else None
        link.override_color = form.get("override_color") == "1"
        link.custom_color = _sanitize_icon_color(form.get("custom_color")) if link.override_color else None
    else:
        link.link_size = None
        link.override_color = False
        link.custom_color = None
    if link.kind == "button":
        bs = (form.get("button_style") or "pill").strip()
        link.button_style = bs if bs in _NAV_BUTTON_STYLES else "pill"
    else:
        link.button_style = "pill"


@bp.route("/frontend/nav-column/<int:cid>/link/new", methods=["POST"])
@frontend_editor_required
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
@frontend_editor_required
def frontend_nav_link_edit(lid):
    link = db.session.get(FrontendNavLink, lid) or abort(404)
    _apply_nav_link_form(link, request.form)
    db.session.commit()
    return redirect(url_for("main.frontend_nav_megamenu", nid=link.column.nav_item_id))


@bp.route("/frontend/nav-link/<int:lid>/delete", methods=["POST"])
@frontend_editor_required
def frontend_nav_link_delete(lid):
    link = db.session.get(FrontendNavLink, lid) or abort(404)
    nid = link.column.nav_item_id
    db.session.delete(link)
    db.session.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True)
    return redirect(url_for("main.frontend_nav_megamenu", nid=nid))


@bp.route("/frontend/nav/<int:nid>/megamenu/save-all", methods=["POST"])
@frontend_editor_required
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
@frontend_editor_required
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


def _custom_icon_json(ci):
    return {
        "id": ci.id, "name": ci.name, "mime_type": ci.mime_type,
        "url": f"/pub/icon/{ci.id}",
        "ref": f"custom:{ci.id}",
    }


@bp.route("/frontend/custom-icons.json")
@frontend_editor_required
def frontend_custom_icons_list():
    rows = CustomIcon.query.order_by(CustomIcon.created_at.desc()).all()
    return jsonify(icons=[_custom_icon_json(ci) for ci in rows])


@bp.route("/frontend/custom-icon/upload", methods=["POST"])
@frontend_editor_required
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
@frontend_editor_required
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
@frontend_editor_required
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
@frontend_editor_required
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
@frontend_editor_required
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
@frontend_editor_required
def frontend_dashboard():
    s = _get_site_setting()
    return render_template("frontend_dashboard.html", site=s)


@bp.route("/frontend/branding")
@frontend_editor_required
def frontend_branding():
    s = _get_site_setting()
    return render_template("frontend_branding.html", site=s)


@bp.route("/frontend/fonts-icons")
@frontend_editor_required
def frontend_fonts_icons():
    s = _get_site_setting()
    custom_icons = CustomIcon.query.order_by(CustomIcon.created_at.desc()).all()
    custom_fonts = CustomFont.query.order_by(CustomFont.created_at.desc()).all()
    return render_template("frontend_fonts_icons.html",
                           site=s, custom_icons=custom_icons, custom_fonts=custom_fonts)


@bp.route("/frontend/404")
@frontend_editor_required
def frontend_404():
    """Customize the public 404 page (heading, subheading, CTA, illustration).
    Sensible defaults render when fields are blank — see frontend/404.html."""
    s = _get_site_setting()
    return render_template("frontend_404.html", site=s)


@bp.route("/frontend/404/save", methods=["POST"])
@frontend_editor_required
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
@frontend_editor_required
def frontend_design():
    """Site-wide design tokens (colors, spacing, buttons, links, text).
    Theme provides defaults; this page lets the admin override any
    subset. Empty inputs fall through to the theme default."""
    s = _get_site_setting()
    return render_template("frontend_design.html", site=s)


@bp.route("/frontend/design/save", methods=["POST"])
@frontend_editor_required
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


@bp.route("/frontend/design/reset", methods=["POST"])
@frontend_editor_required
def frontend_design_reset():
    """Clear every override so the active theme's defaults take over."""
    s = _get_site_setting()
    s.frontend_design_json = None
    db.session.commit()
    flash("Design reset to theme defaults", "success")
    return redirect(url_for("main.frontend_design"))


@bp.route("/frontend/fonts-icons/save", methods=["POST"])
@frontend_editor_required
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
@frontend_editor_required
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
    db.session.commit()
    flash("Branding saved", "success")
    return redirect(url_for("main.frontend_branding"))


@bp.route("/frontend/header")
@frontend_editor_required
def frontend_header():
    from .frontend import HEADER_TEMPLATES
    s = _get_site_setting()
    return render_template("frontend_header.html", site=s,
                           header_templates=HEADER_TEMPLATES)


@bp.route("/frontend/navigation")
@frontend_editor_required
def frontend_navigation():
    from .frontend import MEGAMENU_TEMPLATES
    s = _get_site_setting()
    nav_items = FrontendNavItem.query.order_by(FrontendNavItem.position,
                                               FrontendNavItem.id).all()
    return render_template("frontend_navigation.html", site=s, nav_items=nav_items,
                           megamenu_templates=MEGAMENU_TEMPLATES)


@bp.route("/frontend/megamenu-template", methods=["POST"])
@frontend_editor_required
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
@frontend_editor_required
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


@bp.route("/frontend/footer")
@frontend_editor_required
def frontend_footer():
    from .frontend import FOOTER_TEMPLATES
    s = _get_site_setting()
    return render_template("frontend_footer.html", site=s,
                           footer_templates=FOOTER_TEMPLATES)


@bp.route("/frontend/footer-template", methods=["POST"])
@frontend_editor_required
def frontend_footer_template_save():
    from .frontend import FOOTER_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_footer_template") or "").strip()
    if key in {t["key"] for t in FOOTER_TEMPLATES}:
        s.frontend_footer_template = key
        db.session.commit()
        flash(f"Footer template set to {key}", "success")
    return redirect(url_for("main.frontend_footer"))


_HOMEPAGE_BLOCK_CATALOG = [
    {"key": "hero",         "name": "Hero",          "icon": "panel-top",   "desc": "Headline, subheading, and call-to-action buttons. Required as the first block on most layouts."},
    {"key": "split",        "name": "Two-panel row", "icon": "columns",     "desc": "Full-width row with two side-by-side drop zones. Drag any other block into either panel."},
    {"key": "quick_links",  "name": "Quick links",   "icon": "layout-grid", "desc": "Four navigation cards for the most-used destinations."},
    {"key": "features",     "name": "Features",      "icon": "star",        "desc": "Three-up feature columns with icons and short copy."},
    {"key": "stats",        "name": "Stats",         "icon": "bar-chart",   "desc": "Number-driven metrics row for credibility cues."},
    {"key": "testimonials", "name": "Testimonials",  "icon": "message-circle", "desc": "Member quotes — adds social proof."},
    {"key": "cta",          "name": "Call to action","icon": "megaphone",   "desc": "Bold full-width banner with primary + ghost buttons."},
    {"key": "meetings",     "name": "Meetings list", "icon": "calendar",    "desc": "Live meetings preview pulled from the admin database. Filter + animation are configured under the meetings card."},
    {"key": "events",       "name": "Upcoming Events","icon": "calendar",   "desc": "Stacked rows for upcoming events from the Announcements & Events module. Past events drop off automatically."},
    {"key": "about",        "name": "About",         "icon": "info",        "desc": "About-the-fellowship copy with the three numbered pillars."},
    {"key": "faq",          "name": "FAQ",           "icon": "help-circle", "desc": "Accordion list of common newcomer questions."},
    {"key": "contact",      "name": "Contact",       "icon": "phone",       "desc": "Contact-and-help section, optionally including the PIC card."},
]


@bp.route("/frontend/homepage")
@frontend_editor_required
def frontend_homepage():
    from .frontend import HOMEPAGE_TEMPLATES
    from .blocks import (site_blocks,
                         format_features, format_stats, format_testimonials,
                         format_faq, format_quick_links)
    import json as _json
    s = _get_site_setting()
    hero_buttons = FrontendHeroButton.query.order_by(FrontendHeroButton.position).all()
    homepage_layouts = (CustomLayout.query
                        .filter_by(kind="homepage")
                        .order_by(CustomLayout.is_prebuilt.desc(), CustomLayout.created_at)
                        .all())
    # Resolve which block-editors to render based on the active layout.
    # Walk into split blocks so editors for blocks nested in a split get
    # rendered too — otherwise the admin shows nothing while the public
    # site is happily rendering them.
    active_key = (s.frontend_homepage_template if s else None) or "classic"
    active_layout = next((l for l in homepage_layouts if l.key == active_key), None)
    active_layout_seq = []
    active_layout_blocks = []
    active_layout_splits = []   # list of {index, width, margin, padding, left:[types], right:[types]}
    if active_layout:
        try:
            active_layout_seq = _json.loads(active_layout.blocks_json or "[]") or []
        except (ValueError, TypeError):
            active_layout_seq = []
    def _walk_types(seq, out):
        for b in (seq or []):
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if not t:
                continue
            out.append(t)
            if t == "split":
                _walk_types(b.get("left") or [], out)
                _walk_types(b.get("right") or [], out)
    _walk_types(active_layout_seq, active_layout_blocks)
    # Record each split in document order so the admin can render a
    # visualization + settings card per split.
    split_idx = 0
    for b in active_layout_seq:
        if isinstance(b, dict) and b.get("type") == "split":
            # Legacy `margin` migrates into both top + bottom gap on
            # read, so older saved layouts pick up the new fields
            # automatically without the admin having to re-set them.
            legacy_m = (b.get("margin") or "").strip().lower()
            gt = (b.get("gap_top") or legacy_m or "none")
            gb = (b.get("gap_bottom") or legacy_m or "none")
            active_layout_splits.append({
                "index":          split_idx,
                "width":          (b.get("width") or "boxed"),
                "padding":        (b.get("padding") or "default"),
                "gap":            (b.get("gap") or "none"),
                "gap_top":        gt,
                "gap_bottom":     gb,
                "bg_color":       (b.get("bg_color") or ""),
                "bg_color_left":  (b.get("bg_color_left") or ""),
                "bg_color_right": (b.get("bg_color_right") or ""),
                "bg_dark_mode":   bool(b.get("bg_dark_mode")),
                "left":  [bb.get("type") for bb in (b.get("left") or [])
                          if isinstance(bb, dict) and bb.get("type")],
                "right": [bb.get("type") for bb in (b.get("right") or [])
                          if isinstance(bb, dict) and bb.get("type")],
            })
            split_idx += 1
    block_content = site_blocks(s)
    block_text = {
        "features":     format_features(block_content.get("features")),
        "stats":        format_stats(block_content.get("stats")),
        "testimonials": format_testimonials(block_content.get("testimonials")),
        "faq":          format_faq(block_content.get("faq")),
        "quick_links":  format_quick_links(block_content.get("quick_links")),
    }
    return render_template("frontend_homepage.html", site=s,
                           homepage_templates=HOMEPAGE_TEMPLATES,
                           homepage_layouts=homepage_layouts,
                           homepage_block_catalog=_HOMEPAGE_BLOCK_CATALOG,
                           active_layout_blocks=active_layout_blocks,
                           active_layout_splits=active_layout_splits,
                           active_layout_key=active_key,
                           block_content=block_content,
                           block_text=block_text,
                           hero_buttons=hero_buttons)


@bp.route("/frontend/homepage-template", methods=["POST"])
@frontend_editor_required
def frontend_homepage_template_save():
    from .frontend import HOMEPAGE_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_homepage_template") or "").strip()
    legacy = {t["key"] for t in HOMEPAGE_TEMPLATES}
    custom = {l.key for l in CustomLayout.query.filter_by(kind="homepage").all()}
    if key in (legacy | custom):
        s.frontend_homepage_template = key
        db.session.commit()
        flash(f"Homepage layout set to {key}", "success")
    return redirect(url_for("main.frontend_homepage"))


# ---------------------------------------------------------------------------
# Templates admin — single page that hosts pickers for every reusable
# entity-detail template (Meeting Detail, Event Detail, and any future
# content types). Different from layouts: a layout is a block sequence
# bound to a specific page slug, while a template here applies to every
# page rendered for a content type.
# ---------------------------------------------------------------------------
@bp.route("/frontend/templates")
@frontend_editor_required
def frontend_templates():
    from .frontend import MEETING_TEMPLATES, EVENT_TEMPLATES, template_settings
    from .fonts import all_fonts
    s = _get_site_setting()
    meeting_key = (s.frontend_meeting_template if s else None) or "classic"
    event_key = (s.frontend_event_template if s else None) or "classic"
    return render_template("frontend_templates.html", site=s,
                           meeting_templates=MEETING_TEMPLATES,
                           event_templates=EVENT_TEMPLATES,
                           meeting_active_settings=template_settings(s, "meeting", meeting_key),
                           event_active_settings=template_settings(s, "event", event_key),
                           font_options=all_fonts())


_TEMPLATE_KINDS = ("meeting", "event")


@bp.route("/frontend/template-settings/<kind>/<key>", methods=["POST"])
@frontend_editor_required
def frontend_template_settings_save(kind, key):
    """Persist per-template appearance overrides (background, font choices,
    size scales) into SiteSetting.frontend_template_settings_json. Empty or
    default values are stripped so the template falls through to the site's
    design tokens."""
    import json as _json
    import re as _re
    from .frontend import MEETING_TEMPLATES, EVENT_TEMPLATES
    from .fonts import font_by_key
    if kind not in _TEMPLATE_KINDS:
        abort(404)
    catalog = MEETING_TEMPLATES if kind == "meeting" else EVENT_TEMPLATES
    if key not in {t["key"] for t in catalog}:
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
@frontend_editor_required
def frontend_meeting_template_save():
    from .frontend import MEETING_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_meeting_template") or "").strip()
    if key in {t["key"] for t in MEETING_TEMPLATES}:
        s.frontend_meeting_template = key
        db.session.commit()
        flash(f"Meeting template set to {key}", "success")
    return redirect(url_for("main.frontend_templates"))


@bp.route("/frontend/event-template", methods=["POST"])
@frontend_editor_required
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
    "features", "cta", "stats", "testimonials", "faq", "split",
}


_SPLIT_VALID_WIDTHS = {"boxed", "full"}
_SPLIT_VALID_SPACING = {"none", "tight", "default", "loose"}
_SPLIT_HEX_RE = _re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _normalize_blocks(raw_list):
    """Recursively walk a list of {type,...} dicts from the builder.
    Drops unknown block types. For 'split' blocks, recurses into
    `left` / `right` AND round-trips the split's spacing + appearance
    settings (width, padding, top/bottom gap, inner gap, bg color) so
    editing the layout structure in the builder doesn't blow them away.
    The legacy `margin` field — which used to control top + bottom gap
    together — is migrated into `gap_top` + `gap_bottom` on read so old
    layouts upgrade transparently."""
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
        if t not in _CUSTOM_LAYOUT_BLOCK_TYPES:
            continue
        if t == "split":
            norm = {
                "type": "split",
                "left":  _normalize_blocks(left or []),
                "right": _normalize_blocks(right or []),
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
                if bg and _SPLIT_HEX_RE.match(bg): norm["bg_color"] = bg
                bg_l = (b.get("bg_color_left") or "").strip()
                bg_r = (b.get("bg_color_right") or "").strip()
                if bg_l and _SPLIT_HEX_RE.match(bg_l): norm["bg_color_left"] = bg_l
                if bg_r and _SPLIT_HEX_RE.match(bg_r): norm["bg_color_right"] = bg_r
                if b.get("bg_dark_mode"): norm["bg_dark_mode"] = True
            out.append(norm)
        else:
            out.append({"type": t})
    return out


@bp.route("/frontend/custom-layout/save", methods=["POST"])
@frontend_editor_required
def frontend_custom_layout_save():
    """Persist a user-created layout from the drag-and-drop builder.
    Returns JSON {ok, key, layout} so the picker can re-render and
    auto-select the new entry."""
    import json as _json
    payload = request.get_json(silent=True) or {}
    blocks = _normalize_blocks(payload.get("blocks") or [])
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
        kind="homepage", is_prebuilt=False,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify(ok=True, key=row.key, name=row.name)


@bp.route("/frontend/custom-layout/<key>/update", methods=["POST"])
@frontend_editor_required
def frontend_custom_layout_update(key):
    """Replace a custom layout's name + blocks. Pre-built layouts seeded
    via _seed_custom_layouts are read-only — admins can clone them by
    using "Custom layout" in the picker but not edit the originals."""
    import json as _json
    row = CustomLayout.query.filter_by(key=key).first() or abort(404)
    if row.is_prebuilt:
        return jsonify(ok=False, error="Built-in layouts can't be edited"), 400
    payload = request.get_json(silent=True) or {}
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
@frontend_editor_required
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
    db.session.delete(row)
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/frontend/theme-save", methods=["POST"])
@frontend_editor_required
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
    return redirect(request.referrer or url_for("main.frontend_dashboard"))


@bp.route("/frontend/pages")
@frontend_editor_required
def frontend_pages():
    s = _get_site_setting()
    return render_template("frontend_pages.html", site=s)


@bp.route("/frontend/footer-save", methods=["POST"])
@frontend_editor_required
def frontend_footer_save():
    s = _get_site_setting()
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
    return redirect(request.referrer or url_for("main.index"))


# --- Files ---

@bp.route("/meetings/<int:mid>/files/new", methods=["GET", "POST"])
@editor_required
def file_new(mid):
    m = db.session.get(Meeting, mid) or abort(404)
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
        return redirect(url_for("main.meeting_detail", mid=m.id) + f"#{category}")
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
        return redirect(url_for("main.meeting_detail", mid=f.meeting_id) + f"#{f.category}")
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


@bp.route("/meetings/<int:mid>/files/reorder", methods=["POST"])
@editor_required
def meeting_files_reorder(mid):
    m = db.session.get(Meeting, mid) or abort(404)
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
    mid = f.meeting_id
    cat = f.category
    _delete_upload(f.stored_filename)
    db.session.delete(f)
    db.session.commit()
    flash("File deleted", "success")
    return redirect(url_for("main.meeting_detail", mid=mid) + f"#{cat}")


@bp.route("/files/<int:fid>/view")
@login_required
def file_view(fid):
    f = db.session.get(MeetingFile, fid) or abort(404)
    if f.category in ("readings", "scripts") and f.body:
        return render_template("reading_view.html", title=f.title, body=f.body,
                               back_url=url_for("main.meeting_detail", mid=f.meeting_id))
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
        items.sort(key=lambda l: (l.readings.count(), l.name.lower()))
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
@editor_required
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
        flash("Library created", "success")
        return redirect(url_for("main.library_detail", lid=lib.id))
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
        flash("Intergroup library created", "success")
        return redirect(url_for("main.library_detail", lid=lib.id))
    return render_template("library_form.html", library=None, intergroup_create=True)


@bp.route("/libraries/<int:lid>")
@login_required
def library_detail(lid):
    lib = db.session.get(Library, lid) or abort(404)
    # Intergroup libraries have a canonical slug-based URL under
    # /tspro/intergroup/<slug>. Redirect id-based hits there so the
    # browser address bar shows the human-readable URL even when the
    # request originated from an internal url_for(main.library_detail).
    if lib.is_intergroup:
        from .colors import slugify
        return redirect(url_for("main.intergroup_library_detail",
                                slug=slugify(lib.name)), code=301)
    return render_template("library_detail.html", library=lib)


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


@bp.route("/libraries/<int:lid>/edit", methods=["GET", "POST"])
@login_required
def library_edit(lid):
    lib = db.session.get(Library, lid) or abort(404)
    deny = _require_can_edit_library(lib)
    if deny is not None:
        return deny
    if request.method == "POST":
        # Renaming an Intergroup library is admin-only — non-admins
        # could otherwise rename the row to escape the gate it sits
        # behind. The is_intergroup flag itself is admin-only too.
        new_name = request.form["name"].strip()
        if (lib.is_intergroup
                and new_name != lib.name
                and not current_user.is_admin()):
            flash("Only admins can rename Intergroup libraries", "danger")
            return redirect(url_for("main.library_detail", lid=lib.id))
        lib.name = new_name
        lib.description = request.form.get("description", "").strip()
        lib.alert_message = request.form.get("alert_message", "").strip() or None
        # Admin-only: respect the checkbox when the form rendered it
        # (signalled by ``is_intergroup_present``). The hidden marker
        # lets us distinguish "admin unchecked the box" from "non-admin
        # form didn't render the field at all".
        if current_user.is_admin() and request.form.get("is_intergroup_present") == "1":
            lib.is_intergroup = request.form.get("is_intergroup") == "1"
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
        flash("Library updated", "success")
        return redirect(url_for("main.library_detail", lid=lib.id))
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


@bp.route("/libraries/<int:lid>/delete", methods=["POST"])
@admin_required
def library_delete(lid):
    lib = db.session.get(Library, lid) or abort(404)
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
    mode = (form.get("content_mode") or "").strip()
    # Only write body when the paste panel was active (mode=paste), or when
    # the form doesn't carry a mode flag (legacy submissions).
    if mode == "paste" or not mode:
        r.body = form.get("body", "").strip()
    if mode == "upload":
        # Switched explicitly to upload mode — clear any prior body.
        r.body = ""
    r.url = form.get("url", "").strip() or None
    uploaded = files.get("file")
    media_id = (form.get("media_id") or "").strip()
    if uploaded and uploaded.filename:
        r.stored_filename, r.original_filename = _save_upload(uploaded)
    elif media_id:
        m = db.session.get(MediaItem, int(media_id)) if media_id.isdigit() else None
        if m:
            r.stored_filename, r.original_filename = m.stored_filename, m.original_filename
    if form.get("remove_file") == "1" and r.stored_filename:
        r.stored_filename = None
        r.original_filename = None
    # Switching to paste mode implicitly clears any existing file so a single
    # reading doesn't carry both body and file simultaneously.
    if mode == "paste" and r.stored_filename:
        r.stored_filename = None
        r.original_filename = None
    thumb = files.get("thumbnail")
    if thumb and thumb.filename:
        r.thumbnail_filename, _ = _save_upload(thumb)
    if form.get("remove_thumbnail") == "1" and r.thumbnail_filename:
        r.thumbnail_filename = None


@bp.route("/libraries/<int:lid>/readings/new", methods=["GET", "POST"])
@login_required
def reading_new(lid):
    lib = db.session.get(Library, lid) or abort(404)
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
            return redirect(url_for("main.library_detail", lid=lib.id))
        r = Reading(library_id=lib.id, title=request.form["title"].strip(),
                    created_by=current_user.id)
        _apply_reading_form(r, request.form, request.files)
        if picker_present:
            r.categories = cats
        db.session.add(r)
        db.session.commit()
        flash("Item added to library", "success")
        return redirect(url_for("main.library_detail", lid=lib.id))
    return render_template("reading_form.html", library=lib, reading=None)


@bp.route("/readings/<int:rid>")
@login_required
def reading_view(rid):
    r = db.session.get(Reading, rid) or abort(404)
    if r.body:
        return render_template("reading_view.html", reading=r,
                               back_url=url_for("main.library_detail", lid=r.library_id))
    if r.url:
        return redirect(r.url)
    if r.stored_filename:
        return redirect(url_for("main.reading_download", rid=rid))
    return render_template("reading_view.html", reading=r,
                           back_url=url_for("main.library_detail", lid=r.library_id))


@bp.route("/readings/<int:rid>/download")
@login_required
def reading_download(rid):
    r = db.session.get(Reading, rid) or abort(404)
    if not r.stored_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"],
                               r.stored_filename, as_attachment=False,
                               download_name=r.original_filename or r.stored_filename)


@bp.route("/readings/<int:rid>/content")
@login_required
def reading_content(rid):
    """Return the reading's body rendered to HTML (bleached)."""
    r = db.session.get(Reading, rid) or abort(404)
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
    r = db.session.get(Reading, rid) or abort(404)
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
    """Render a markdown snippet to bleached HTML for the editor preview."""
    if not current_user.can_use_editor_tools():
        return jsonify(error="forbidden"), 403
    from flask import render_template_string
    body = request.form.get("body") or request.get_json(silent=True, force=False) or {}
    if isinstance(body, dict):
        body = body.get("body", "")
    html = str(render_template_string("{{ body|markdown }}", body=body))
    return jsonify(html=html)


@bp.route("/readings/<int:rid>/thumbnail")
@login_required
def reading_thumbnail(rid):
    r = db.session.get(Reading, rid) or abort(404)
    if not r.thumbnail_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], r.thumbnail_filename)


@bp.route("/readings/<int:rid>/edit", methods=["GET", "POST"])
@login_required
def reading_edit(rid):
    r = db.session.get(Reading, rid) or abort(404)
    deny = _require_can_edit_library(r.library)
    if deny is not None:
        return deny
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
            return redirect(url_for("main.library_detail", lid=r.library_id))
        _apply_reading_form(r, request.form, request.files)
        if picker_present:
            r.categories = cats
        db.session.commit()
        flash("Item updated", "success")
        return redirect(url_for("main.library_detail", lid=r.library_id))
    return render_template("reading_form.html", library=r.library, reading=r)


def _library_browse_url(lib):
    """Canonical detail URL for a library — slug-based for Intergroup
    rows so the redirect lands at the human-readable URL, id-based for
    everything else. Used by routes that flash + redirect after a
    write operation."""
    if lib.is_intergroup:
        from .colors import slugify
        return url_for("main.intergroup_library_detail", slug=slugify(lib.name))
    return url_for("main.library_detail", lid=lib.id)


@bp.route("/libraries/<int:lid>/readings/bulk-categories", methods=["POST"])
@login_required
def library_readings_bulk_categories(lid):
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
    lib = db.session.get(Library, lid) or abort(404)
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
    readings = Reading.query.filter(
        Reading.library_id == lib.id,
        Reading.id.in_(rids),
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


@bp.route("/libraries/<int:lid>/readings/bulk-delete", methods=["POST"])
@login_required
def library_readings_bulk_delete(lid):
    """Delete a multi-select set of readings. Per-row authorization
    mirrors ``User.can_delete_reading`` (Editors can only delete rows
    whose creator was an editor-tier user; admin/intergroup_member
    free-and-clear within a library they can edit; frontend_editor
    and viewer can't delete at all). Stored files + thumbnails are
    cleaned up via ``_delete_upload`` before the DB row is removed.
    Skipped rows are silently filtered with a flash summary so the
    user sees when authorization scoped their action down."""
    lib = db.session.get(Library, lid) or abort(404)
    deny = _require_can_edit_library(lib)
    if deny is not None:
        return deny
    rids = set(request.form.getlist("reading_ids", type=int))
    if not rids:
        flash("Pick at least one file to delete.", "danger")
        return redirect(_library_browse_url(lib))
    readings = Reading.query.filter(
        Reading.library_id == lib.id,
        Reading.id.in_(rids),
    ).all()
    deleted = 0
    skipped = 0
    for r in readings:
        if not current_user.can_delete_reading(r):
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


@bp.route("/libraries/<int:lid>/readings/reorder", methods=["POST"])
@login_required
def library_readings_reorder(lid):
    lib = db.session.get(Library, lid) or abort(404)
    if not current_user.can_edit_library(lib):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    ids = data.get("order") or []
    if not isinstance(ids, list):
        return jsonify({"error": "invalid"}), 400
    readings = {r.id: r for r in lib.readings.all()}
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


@bp.route("/readings/<int:rid>/delete", methods=["POST"])
@login_required
def reading_delete(rid):
    r = db.session.get(Reading, rid) or abort(404)
    if not current_user.can_delete_reading(r):
        flash("You don't have permission to delete this file", "danger")
        return redirect(request.referrer
                        or url_for("main.library_detail", lid=r.library_id))
    lid = r.library_id
    if r.stored_filename:
        _delete_upload(r.stored_filename)
    if r.thumbnail_filename:
        _delete_upload(r.thumbnail_filename)
    db.session.delete(r)
    db.session.commit()
    flash("Item deleted", "success")
    return redirect(url_for("main.library_detail", lid=lid))


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


def _cleanup_retired_asset(stored):
    """Delete a file from disk and its MediaItem row, but only if nothing
    else in the system still references it (other SiteSetting columns,
    meetings, readings, meeting files, thumbnails). Safe to call with
    None or a filename that's already gone."""
    if not stored:
        return
    s = SiteSetting.query.first()
    if s and stored in (s.footer_logo_filename, s.frontend_logo_filename,
                        s.og_image_filename, s.frontend_og_image_filename,
                        s.frontend_favicon_filename,
                        s.frontend_404_image_filename):
        return  # still referenced by another interface asset
    refs = (MeetingFile.query.filter_by(stored_filename=stored).count()
            + Reading.query.filter_by(stored_filename=stored).count()
            + Reading.query.filter_by(thumbnail_filename=stored).count()
            + Meeting.query.filter_by(logo_filename=stored).count()
            + Post.query.filter_by(featured_image_filename=stored).count())
    if refs > 0:
        return
    _delete_upload(stored)
    MediaItem.query.filter_by(stored_filename=stored).delete()
    db.session.flush()


# --- Media browser ---

@bp.route("/files")
@login_required
def media_list():
    q = (request.args.get("q") or "").strip().lower()
    picker = request.args.get("picker") == "1"
    view = request.args.get("view") or request.cookies.get("view-media") or "table"
    sort = request.args.get("sort") or request.cookies.get("view-media-sort") or "uploaded"
    direction = request.args.get("dir") or request.cookies.get("view-media-dir") or "desc"
    items = MediaItem.query.all()
    hidden = _interface_stored_filenames()
    if hidden:
        items = [m for m in items if m.stored_filename not in hidden]
    if sort == "name":
        items.sort(key=lambda m: (m.original_filename or "").lower())
    elif sort == "type":
        items.sort(key=lambda m: (_media_type(m.original_filename), (m.original_filename or "").lower()))
    elif sort == "size":
        items.sort(key=lambda m: (m.size_bytes or 0))
    else:  # uploaded (created_at)
        items.sort(key=lambda m: (m.created_at or m.id))
    if direction == "desc":
        items.reverse()
    if q:
        items = [m for m in items if q in (m.original_filename or "").lower()]
    resp = current_app.make_response(
        render_template("media.html", items=items, q=q, picker=picker, view=view,
                        sort=sort, direction=direction, media_type=_media_type))
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
    h = hashlib.sha256(data).hexdigest()
    existing = MediaItem.query.filter_by(content_hash=h).first()
    if existing:
        return jsonify({"item": _media_json(existing), "deduped": True})
    original = secure_filename(uploaded.filename) or "upload"
    ext = os.path.splitext(original)[1]
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
            + Reading.query.filter_by(stored_filename=m.stored_filename).count()
            + Reading.query.filter_by(thumbnail_filename=m.stored_filename).count())
    if refs > 0:
        flash(f"Cannot delete — file is used by {refs} item(s)", "warning")
    else:
        _delete_upload(m.stored_filename)
        db.session.delete(m); db.session.commit()
        flash("File deleted", "success")
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
    return redirect(request.referrer or url_for("main.index"))


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
        return redirect(request.referrer or url_for("main.index"))
    s.turnstile_enabled = wants_enabled
    db.session.commit()
    flash("Login bot protection saved", "success")
    return redirect(request.referrer or url_for("main.index"))


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
        return redirect(request.referrer or url_for("main.index"))
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
    return redirect(request.referrer or url_for("main.index"))


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
        return redirect(request.referrer or url_for("main.index"))
    if not (s.smtp_host and s.smtp_from_email):
        msg = ("SMTP isn't configured yet. Enter SMTP host, port, security, "
               "and From-email above, click Save, then run the test.")
        if wants_json:
            return jsonify(ok=False, message=msg), 200
        flash(msg, "danger")
        return redirect(request.referrer or url_for("main.index"))
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
    return redirect(request.referrer or url_for("main.index"))


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


@bp.route("/access-requests")
@admin_required
def access_requests():
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
        # Active list: pending first (status='pending' > 'handled' alpha,
        # but we want pending visible at the top, so explicit ordering).
        items = q.order_by(AccessRequest.status.asc(),
                           AccessRequest.created_at.desc()).all()
    archived_count = AccessRequest.query.filter_by(is_archived=True).count()
    active_count = AccessRequest.query.filter_by(is_archived=False).count()
    resp = current_app.make_response(
        render_template("access_requests.html", items=items, view=view,
                        archived_count=archived_count, active_count=active_count)
    )
    # Defeat stale-HTML caching after the modal-driven Create User flow.
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@bp.route("/access-requests/<int:rid>/handled", methods=["POST"])
@admin_required
def access_request_handled(rid):
    from datetime import datetime
    r = db.session.get(AccessRequest, rid) or abort(404)
    r.status = "handled" if r.status == "pending" else "pending"
    r.handled_at = datetime.utcnow() if r.status == "handled" else None
    db.session.commit()
    return redirect(url_for("main.access_requests",
                            view=request.form.get("view") or "active"))


@bp.route("/access-requests/<int:rid>/archive", methods=["POST"])
@admin_required
def access_request_archive(rid):
    """Move a handled request into the archive view. Pending requests
    are auto-flipped to handled at the same time so the archived row
    has a coherent status. Reversible via ``access_request_unarchive``.
    """
    from datetime import datetime
    r = db.session.get(AccessRequest, rid) or abort(404)
    if r.status == "pending":
        r.status = "handled"
        r.handled_at = datetime.utcnow()
    r.is_archived = True
    r.archived_at = datetime.utcnow()
    db.session.commit()
    flash("Request archived", "success")
    return redirect(url_for("main.access_requests",
                            view=request.form.get("view") or "active"))


@bp.route("/access-requests/<int:rid>/unarchive", methods=["POST"])
@admin_required
def access_request_unarchive(rid):
    r = db.session.get(AccessRequest, rid) or abort(404)
    r.is_archived = False
    r.archived_at = None
    db.session.commit()
    flash("Request restored from archive", "success")
    return redirect(url_for("main.access_requests",
                            view=request.form.get("view") or "archived"))


@bp.route("/access-requests/<int:rid>/delete", methods=["POST"])
@admin_required
def access_request_delete(rid):
    r = db.session.get(AccessRequest, rid) or abort(404)
    db.session.delete(r)
    db.session.commit()
    flash("Request deleted", "success")
    return redirect(url_for("main.access_requests",
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


@bp.route("/posts")
@login_required
def posts():
    _require_posts_enabled()
    _auto_archive_events()
    show = (request.args.get("show") or "active").strip()
    kind = (request.args.get("kind") or "all").strip()
    q = Post.query
    if show == "archived":
        q = q.filter(Post.is_archived.is_(True))
    elif show == "drafts":
        q = q.filter(Post.is_draft.is_(True), Post.is_archived.is_(False))
    else:  # active
        q = q.filter(Post.is_archived.is_(False), Post.is_draft.is_(False))
    if kind == "events":
        q = q.filter(Post.is_event.is_(True))
    elif kind == "announcements":
        q = q.filter(Post.is_announcement.is_(True))
    # Newest first; events sort by event-start when set so upcoming reads top.
    items = q.order_by(Post.event_starts_at.desc().nulls_last(),
                       Post.updated_at.desc()).all()
    return render_template("posts.html", posts=items, show=show, kind=kind)


@bp.route("/posts/new")
@login_required
def post_new():
    _require_posts_enabled()
    return render_template("post_edit.html", post=None)


@bp.route("/posts/<int:pid>")
@login_required
def post_edit(pid):
    _require_posts_enabled()
    post = db.session.get(Post, pid) or abort(404)
    return render_template("post_edit.html", post=post)


@bp.route("/posts/save", methods=["POST"])
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

    # Capture the previous public slug before mutating title/slug — same
    # rationale as in _apply_meeting_form.
    _prev_public_slug = post.public_slug if not creating else None

    title = (request.form.get("title") or "").strip()[:255]
    if not title:
        flash("Title is required", "danger")
        return redirect(request.referrer or url_for("main.post_new"))
    post.title = title

    # Slug edits are gated to admins + frontend editors; all other users'
    # slug field is silently ignored.
    if current_user.is_authenticated and current_user.can_edit_frontend():
        post.slug = _normalize_slug(request.form.get("slug"))
    post.summary = (request.form.get("summary") or "").strip() or None
    post.body = (request.form.get("body") or "").strip() or None

    post.is_announcement = request.form.get("is_announcement") == "1"
    post.is_event = request.form.get("is_event") == "1"

    post.event_starts_at = _parse_post_dt(request.form.get("event_starts_at"))
    post.event_ends_at = _parse_post_dt(request.form.get("event_ends_at"))

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
    action = (request.form.get("action") or "").strip()
    if action == "draft":
        post.is_draft = True
    elif action == "publish":
        post.is_draft = False
    elif creating:
        post.is_draft = False  # default: new posts are active

    if creating:
        db.session.add(post)
    else:
        # Log a redirect row whenever the public slug changed.
        if _prev_public_slug and _prev_public_slug != post.public_slug:
            _record_slug_change("post", post.id, _prev_public_slug, post.public_slug)
    db.session.commit()
    if creating:
        flash(("Draft saved: " + post.title) if post.is_draft else ("Published: " + post.title), "success")
        return redirect(url_for("main.posts", show=("drafts" if post.is_draft else "active")))
    flash("Post saved", "success")
    return redirect(url_for("main.post_edit", pid=post.id))


@bp.route("/posts/<int:pid>/publish", methods=["POST"])
@login_required
def post_publish(pid):
    """Transition a draft to active. No-op if already published."""
    _require_posts_enabled()
    post = db.session.get(Post, pid) or abort(404)
    post.is_draft = False
    db.session.commit()
    flash("Published", "success")
    return redirect(request.referrer or url_for("main.posts"))


@bp.route("/posts/<int:pid>/unpublish", methods=["POST"])
@login_required
def post_unpublish(pid):
    """Move a published post back to drafts. No-op if already a draft."""
    _require_posts_enabled()
    post = db.session.get(Post, pid) or abort(404)
    post.is_draft = True
    db.session.commit()
    flash("Moved to drafts", "success")
    return redirect(request.referrer or url_for("main.posts", show="drafts"))


@bp.route("/posts/<int:pid>/archive", methods=["POST"])
@login_required
def post_archive(pid):
    _require_posts_enabled()
    post = db.session.get(Post, pid) or abort(404)
    post.is_archived = True
    db.session.commit()
    flash("Archived", "success")
    return redirect(request.referrer or url_for("main.posts"))


@bp.route("/posts/<int:pid>/unarchive", methods=["POST"])
@login_required
def post_unarchive(pid):
    _require_posts_enabled()
    post = db.session.get(Post, pid) or abort(404)
    post.is_archived = False
    db.session.commit()
    flash("Restored", "success")
    return redirect(request.referrer or url_for("main.posts"))


@bp.route("/posts/<int:pid>/delete", methods=["POST"])
@login_required
def post_delete(pid):
    _require_posts_enabled()
    post = db.session.get(Post, pid) or abort(404)
    # Clear the featured-image reference BEFORE the cleanup check so the
    # post being deleted doesn't count itself as a referrer. If another
    # post (e.g. one created by Duplicate) still points at the same
    # stored filename, the helper sees it and keeps the file.
    old_image = post.featured_image_filename
    post.featured_image_filename = None
    if old_image:
        _cleanup_retired_asset(old_image)
    db.session.delete(post)
    db.session.commit()
    flash("Post deleted", "success")
    return redirect(url_for("main.posts"))


@bp.route("/posts/<int:pid>/duplicate", methods=["POST"])
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


@public_bp.route("/post-image/<int:pid>")
def post_featured_image(pid):
    """Serve a post's featured image. Public so the public web frontend
    can render link previews even before a visitor signs in."""
    p = db.session.get(Post, pid)
    if not p or not p.featured_image_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], p.featured_image_filename)


@public_bp.route("/meeting-logo/<int:mid>")
def public_meeting_logo(mid):
    """Serve a meeting's uploaded logo to anonymous visitors so the public
    meeting detail page can show it. Mirrors post_featured_image."""
    m = db.session.get(Meeting, mid)
    if not m or not m.logo_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], m.logo_filename)


