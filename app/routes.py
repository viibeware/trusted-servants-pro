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
from .models import (db, User, Meeting, MeetingFile, MeetingSchedule, MeetingLibrary,
                     ZoomAccount, ZoomOtpEmail, Location, Library, Reading,
                     MediaItem, NavLink, SiteSetting, IntergroupAccount,
                     AccessRequest, FrontendNavItem, FrontendNavColumn,
                     FrontendNavLink, FILE_CATEGORIES, DAYS_OF_WEEK)

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
            pending_access_count = AccessRequest.query.filter_by(status="pending").count()
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
                           .filter_by(status="pending")
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
    from .version import __version__
    return jsonify(version=__version__)


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
    m.selected_readings = selected_readings


def _apply_meeting_form(m, form, schedules, files=None):
    m.name = form["name"].strip()
    m.description = form.get("description", "").strip()
    m.alert_message = form.get("alert_message", "").strip() or None
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
    return redirect(url_for("main.nav_links",
                            **({"embed": "1"} if request.values.get("embed") == "1" else {})))


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


@bp.route("/intergroup")
@login_required
def intergroup():
    s = _get_site_setting()
    if not s.intergroup_enabled:
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
    # Social sharing — public-facing
    "og_enabled", "og_title", "og_description", "og_image_filename",
)

# Setting keys that point at an uploaded filename. These drive asset bundling.
_FRONTEND_ASSET_KEYS = (
    "frontend_logo_filename", "footer_logo_filename", "og_image_filename",
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
                    "icon_after": l.icon_after, "button_style": l.button_style,
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
                    link = FrontendNavLink(
                        column_id=col.id,
                        position=int(nl.get("position") or 0),
                        kind=(nl.get("kind") or "link"),
                        label=(nl.get("label") or ""),
                        url=nl.get("url"),
                        icon_before=nl.get("icon_before"),
                        icon_after=nl.get("icon_after"),
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


@public_bp.route("/site-branding/footer-logo")
def site_footer_logo():
    s = _get_site_setting()
    if not s.footer_logo_filename:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], s.footer_logo_filename)


@bp.route("/frontend/save", methods=["POST"])
@frontend_editor_required
def frontend_save():
    """Save homepage content fields. Toggle state and footer text are handled
    by frontend_toggle / frontend_footer_save so this never clobbers them."""
    s = _get_site_setting()
    for col in ("frontend_title", "frontend_tagline", "frontend_hero_heading",
                "frontend_hero_subheading", "frontend_about_heading",
                "frontend_contact_heading"):
        setattr(s, col, (request.form.get(col) or "").strip() or None)
    for col in ("frontend_about_body", "frontend_contact_body"):
        setattr(s, col, (request.form.get(col) or "").strip() or None)
    db.session.commit()
    flash("Homepage content saved", "success")
    return redirect(url_for("main.frontend_homepage"))


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
        html = render_template("_nav_megacol.html", col=col, _icons=[])
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
_NAV_ICONS = {
    "", "info", "alert-triangle", "bell", "megaphone", "star", "heart",
    "calendar", "zap", "mail", "phone", "help-circle",
    "arrow-right", "file-text", "home", "panel-top", "panel-bottom", "layout-grid",
}
_NAV_BLOCK_KINDS = {"link", "title", "button", "section"}
_NAV_BUTTON_STYLES = {"pill", "rounded"}
_NAV_DEFAULT_LABEL = {
    "link": "New link", "title": "Section title",
    "button": "Call to action", "section": "Group heading",
}


def _apply_nav_link_form(link, form):
    kind = (form.get("kind") or link.kind or "link").strip()
    link.kind = kind if kind in _NAV_BLOCK_KINDS else "link"
    link.label = (form.get("label") or "").strip() or link.label
    if link.kind in ("link", "button"):
        link.url = (form.get("url") or "").strip() or None
        link.open_in_new_tab = form.get("open_in_new_tab") == "1"
        ib = (form.get("icon_before") or "").strip()
        ia = (form.get("icon_after") or "").strip()
        link.icon_before = ib if ib and ib in _NAV_ICONS else None
        link.icon_after = ia if ia and ia in _NAV_ICONS else None
    else:
        link.url = None
        link.open_in_new_tab = False
        link.icon_before = None
        link.icon_after = None
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
        icons = ["info", "alert-triangle", "bell", "megaphone", "star", "heart",
                 "calendar", "zap", "mail", "phone", "help-circle", "arrow-right",
                 "file-text", "home", "panel-top", "panel-bottom", "layout-grid"]
        html = render_template("_nav_megalink.html", link=link, _icons=icons)
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


@bp.route("/frontend/")
@frontend_editor_required
def frontend_dashboard():
    s = _get_site_setting()
    return render_template("frontend_dashboard.html", site=s)


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


@bp.route("/frontend/homepage")
@frontend_editor_required
def frontend_homepage():
    from .frontend import HOMEPAGE_TEMPLATES
    s = _get_site_setting()
    return render_template("frontend_homepage.html", site=s,
                           homepage_templates=HOMEPAGE_TEMPLATES)


@bp.route("/frontend/homepage-template", methods=["POST"])
@frontend_editor_required
def frontend_homepage_template_save():
    from .frontend import HOMEPAGE_TEMPLATES
    s = _get_site_setting()
    key = (request.form.get("frontend_homepage_template") or "").strip()
    if key in {t["key"] for t in HOMEPAGE_TEMPLATES}:
        s.frontend_homepage_template = key
        db.session.commit()
        flash(f"Homepage template set to {key}", "success")
    return redirect(url_for("main.frontend_homepage"))


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
        f = MeetingFile(
            meeting_id=m.id,
            category=category,
            title=request.form["title"].strip(),
            description=request.form.get("description", "").strip(),
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
        if f.category in ("readings", "scripts"):
            f.body = request.form.get("body", "").strip()
        _apply_file_upload(f, request.files.get("file"), request.form.get("media_id"))
        db.session.commit()
        flash("File updated", "success")
        return redirect(url_for("main.meeting_detail", mid=f.meeting_id) + f"#{f.category}")
    return render_template("file_form.html", meeting=f.meeting, category=f.category, file=f)


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
    items = Library.query.all()
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


@bp.route("/libraries/<int:lid>")
@login_required
def library_detail(lid):
    lib = db.session.get(Library, lid) or abort(404)
    return render_template("library_detail.html", library=lib)


@bp.route("/libraries/<int:lid>/edit", methods=["GET", "POST"])
@editor_required
def library_edit(lid):
    lib = db.session.get(Library, lid) or abort(404)
    if request.method == "POST":
        lib.name = request.form["name"].strip()
        lib.description = request.form.get("description", "").strip()
        lib.alert_message = request.form.get("alert_message", "").strip() or None
        db.session.commit()
        flash("Library updated", "success")
        return redirect(url_for("main.library_detail", lid=lib.id))
    return render_template("library_form.html", library=lib)


@bp.route("/libraries/<int:lid>/delete", methods=["POST"])
@admin_required
def library_delete(lid):
    lib = db.session.get(Library, lid) or abort(404)
    db.session.delete(lib)
    db.session.commit()
    flash("Library deleted", "success")
    return redirect(url_for("main.libraries"))


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
@editor_required
def reading_new(lid):
    lib = db.session.get(Library, lid) or abort(404)
    if request.method == "POST":
        r = Reading(library_id=lib.id, title=request.form["title"].strip())
        _apply_reading_form(r, request.form, request.files)
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
@editor_required
def markdown_preview():
    """Render a markdown snippet to bleached HTML for the editor preview."""
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
@editor_required
def reading_edit(rid):
    r = db.session.get(Reading, rid) or abort(404)
    if request.method == "POST":
        _apply_reading_form(r, request.form, request.files)
        db.session.commit()
        flash("Item updated", "success")
        return redirect(url_for("main.library_detail", lid=r.library_id))
    return render_template("reading_form.html", library=r.library, reading=r)


@bp.route("/libraries/<int:lid>/readings/reorder", methods=["POST"])
@editor_required
def library_readings_reorder(lid):
    lib = db.session.get(Library, lid) or abort(404)
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
@admin_required
def reading_delete(rid):
    r = db.session.get(Reading, rid) or abort(404)
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
    return names


def _cleanup_retired_asset(stored):
    """Delete a file from disk and its MediaItem row, but only if nothing
    else in the system still references it (other SiteSetting columns,
    meetings, readings, meeting files, thumbnails). Safe to call with
    None or a filename that's already gone."""
    if not stored:
        return
    s = SiteSetting.query.first()
    if s and stored in (s.footer_logo_filename, s.frontend_logo_filename, s.og_image_filename):
        return  # still referenced by another interface asset
    refs = (MeetingFile.query.filter_by(stored_filename=stored).count()
            + Reading.query.filter_by(stored_filename=stored).count()
            + Reading.query.filter_by(thumbnail_filename=stored).count()
            + Meeting.query.filter_by(logo_filename=stored).count())
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
    from .mail import send_mail, _recipients
    s = _get_site_setting()
    to_raw = (request.form.get("to") or "").strip() or s.access_request_to or s.smtp_from_email
    recipients = _recipients(to_raw)
    if not recipients:
        flash("Provide a test recipient", "danger")
        return redirect(request.referrer or url_for("main.index"))
    ok, err = send_mail(s, recipients,
                        "Trusted Servants Pro test email",
                        "This is a test message from Trusted Servants Pro. SMTP is configured correctly.")
    if ok:
        flash(f"Test email sent to {', '.join(recipients)}", "success")
    else:
        flash(f"Failed to send test email: {err}", "danger")
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
    import json
    items = AccessRequest.query.order_by(AccessRequest.status.asc(),
                                         AccessRequest.created_at.desc()).all()
    for r in items:
        try:
            r.roles = json.loads(r.roles_json or "[]")
        except (ValueError, TypeError):
            r.roles = []
    return render_template("access_requests.html", items=items)


@bp.route("/access-requests/<int:rid>/handled", methods=["POST"])
@admin_required
def access_request_handled(rid):
    from datetime import datetime
    r = db.session.get(AccessRequest, rid) or abort(404)
    r.status = "handled" if r.status == "pending" else "pending"
    r.handled_at = datetime.utcnow() if r.status == "handled" else None
    db.session.commit()
    return redirect(url_for("main.access_requests"))


@bp.route("/access-requests/<int:rid>/delete", methods=["POST"])
@admin_required
def access_request_delete(rid):
    r = db.session.get(AccessRequest, rid) or abort(404)
    db.session.delete(r)
    db.session.commit()
    flash("Request deleted", "success")
    return redirect(url_for("main.access_requests"))


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
