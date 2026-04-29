# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin
from flask import Blueprint, render_template, redirect, url_for, request, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash
from .models import db, User, SiteSetting, LoginFailure, ROLES
from .crypto import decrypt

bp = Blueprint("auth", __name__, url_prefix="/tspro/auth")

# Friendly labels for the user-facing role <select> options. Keys map 1-1
# to the strings stored in ``User.role`` (see models.ROLES); raw keys still
# serve as a fallback when an unknown role appears.
ROLE_LABELS = {
    "admin":             "Admin",
    "editor":            "Editor",
    "frontend_editor":   "Frontend editor",
    "intergroup_member": "Intergroup member",
    "viewer":            "Viewer",
}

# Plain-text bullet list of capabilities included in the welcome email
# sent to a freshly-created user. Each role's list is fully expanded —
# inherited capabilities are repeated rather than abbreviated as
# "Inherits every Editor capability above" — so the recipient can see
# the complete picture of what their role unlocks without having to
# cross-reference another role's bullets. Order follows: positives
# (what you can do) first, then restrictions (what you can't).
_VIEWER_BASE = [
    "View meetings, libraries, readings, and uploaded files.",
    "View Zoom accounts and the calendar.",
    "Customize your own dashboard widgets and order.",
]

_EDITOR_BASE = _VIEWER_BASE + [
    "Create, edit, and reorder meetings, locations, schedules, and Zoom accounts.",
    "Create, edit, and reorder libraries and the readings/files inside them.",
    "Upload media and manage file attachments on meetings.",
]

ROLE_PERMISSIONS = {
    "admin": [
        "Full access to every feature in the portal.",
        "View meetings, libraries, readings, uploaded files, Zoom accounts, and the calendar.",
        "Create, edit, reorder, and delete meetings, locations, schedules, and Zoom accounts.",
        "Create, edit, reorder, and delete libraries and the readings inside them — any uploader, any library.",
        "Upload media and manage file attachments on meetings.",
        "Edit the Web Frontend module: header, footer, homepage builder, navigation, mega menus, alert bars, theme/design tokens.",
        "Toggle public visibility of the Web Frontend.",
        "Edit the Intergroup Documents and Intergroup Minutes libraries.",
        "Read and edit the Intergroup Email Accounts page.",
        "Manage users, access requests, modules, site settings, and security.",
        "Import and export the full data archive (database + uploads).",
        "Customize your own dashboard widgets and order.",
    ],
    "editor": _EDITOR_BASE + [
        "Library files: may rename, edit, or delete only those whose uploader was an editor-tier user (Editor / Frontend Editor / Intergroup Member). Admin-uploaded and legacy library files are protected; this restriction does not apply to files attached to meetings.",
        "Cannot reach Settings, Users, the Web Frontend module, or the Intergroup Email Accounts page.",
        "Cannot edit the Intergroup Documents or Intergroup Minutes libraries (admin / Intergroup-Member only).",
    ],
    "frontend_editor": _EDITOR_BASE + [
        "Edit the Web Frontend module: header, footer, homepage builder, navigation, mega menus, alert bars, theme/design tokens.",
        "Toggle public visibility of the Web Frontend.",
        "Library files: may rename, edit, or delete only those whose uploader was an editor-tier user (Editor / Frontend Editor / Intergroup Member). Admin-uploaded and legacy library files are protected; this restriction does not apply to files attached to meetings.",
        "Cannot reach Settings, Users, or the Intergroup Email Accounts page.",
        "Cannot edit the Intergroup Documents or Intergroup Minutes libraries.",
    ],
    "intergroup_member": _EDITOR_BASE + [
        "Edit access to the Intergroup Documents and Intergroup Minutes libraries — regular Editors and Frontend Editors cannot edit those.",
        "May delete any library file regardless of who uploaded it.",
        "Cannot edit the Web Frontend module.",
        "Cannot reach Settings, Users, or the Intergroup Email Accounts page (admin-only).",
    ],
    "viewer": _VIEWER_BASE + [
        "Read-only access across the portal.",
        "Cannot edit, upload, or reach admin areas.",
    ],
}


def _send_welcome_email(user, plaintext_password):
    """Send a freshly-created user their login credentials + a plain-
    English breakdown of what their role can do. Returns ``(ok, err)``
    matching the ``mail.send_mail`` contract; silently no-ops (with an
    informative reason) when SMTP isn't configured or the user has no
    email on file."""
    from .mail import send_mail
    site = SiteSetting.query.first()
    if not site or not site.smtp_host or not site.smtp_from_email:
        return False, "SMTP is not configured"
    if not user.email:
        return False, "User has no email address"

    role_label = ROLE_LABELS.get(user.role, user.role)
    perms = ROLE_PERMISSIONS.get(user.role, [])
    portal_name = (site.smtp_from_name or "Trusted Servants Pro").strip() or "Trusted Servants Pro"
    # Prefer the admin-configured canonical URL so the email body never
    # surfaces a Docker bridge IP / internal hostname. Falls back to the
    # request-context URL builder when no override is set.
    from .routes import _public_url_for
    login_url = _public_url_for("auth.login")

    lines = [
        f"Hello {user.username},",
        "",
        f"An account has been created for you on {portal_name}.",
        "",
        "Your sign-in details:",
        f"  Username: {user.username}",
        f"  Email:    {user.email}",
        f"  Password: {plaintext_password}",
        f"  Role:     {role_label}",
        "",
        f"Sign in at: {login_url}",
        "",
        f"What your {role_label} role can do:",
    ]
    for p in perms:
        lines.append(f"  • {p}")
    lines += [
        "",
        "If you did not expect this email, please ignore it or let an administrator know.",
        "",
        "— Trusted Servants Pro",
    ]
    body = "\n".join(lines)
    return send_mail(site, user.email,
                     f"Your {portal_name} account",
                     body)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# DB-backed login rate limiter. Rows persist across gunicorn workers and
# across restarts, so lockouts surface consistently in the Users panel and
# the dashboard widget regardless of which worker saw the failed attempts.
# Tracked on two dimensions: the client IP, and the submitted username
# (lowercased). Either bucket over threshold locks further attempts; this
# blocks distributed brute-forcing that a pure IP-based limiter would miss.
_LOGIN_WINDOW_SECONDS = 900   # 15 minutes
_LOGIN_MAX_FAILURES_IP = 5
_LOGIN_MAX_FAILURES_USER = 5
# Back-compat alias used by user-facing helpers (user_is_locked, etc.).
_LOGIN_MAX_FAILURES = _LOGIN_MAX_FAILURES_USER


def _cutoff():
    return datetime.utcnow() - timedelta(seconds=_LOGIN_WINDOW_SECONDS)


def _failures_in_window(kind, key):
    """Return the list of failed_at timestamps (oldest first) within the window."""
    rows = (db.session.query(LoginFailure.failed_at)
            .filter(LoginFailure.kind == kind, LoginFailure.key == key,
                    LoginFailure.failed_at >= _cutoff())
            .order_by(LoginFailure.failed_at.asc())
            .all())
    return [r[0] for r in rows]


def _prune_stale():
    """Delete old rows outside the window. Runs lazily on each failure write."""
    try:
        (LoginFailure.query
         .filter(LoginFailure.failed_at < _cutoff())
         .delete(synchronize_session=False))
    except Exception:
        db.session.rollback()


def _login_rate_limit_hit(ip, username=None):
    """Return (blocked, retry_after_seconds). Non-destructive read."""
    ip_times = _failures_in_window("ip", ip) if ip else []
    if len(ip_times) >= _LOGIN_MAX_FAILURES_IP:
        retry = int((ip_times[0] + timedelta(seconds=_LOGIN_WINDOW_SECONDS)
                     - datetime.utcnow()).total_seconds())
        return True, max(retry, 0)
    if username:
        u_times = _failures_in_window("user", username.lower())
        if len(u_times) >= _LOGIN_MAX_FAILURES_USER:
            retry = int((u_times[0] + timedelta(seconds=_LOGIN_WINDOW_SECONDS)
                         - datetime.utcnow()).total_seconds())
            return True, max(retry, 0)
    return False, 0


def _record_login_failure(ip, username=None):
    now = datetime.utcnow()
    if ip:
        db.session.add(LoginFailure(kind="ip", key=ip, failed_at=now))
    if username:
        db.session.add(LoginFailure(kind="user", key=username.lower(), failed_at=now))
    _prune_stale()
    db.session.commit()


def _clear_login_failures(ip=None, username=None):
    q = LoginFailure.query
    if ip is not None and username:
        q = q.filter(
            ((LoginFailure.kind == "ip") & (LoginFailure.key == ip))
            | ((LoginFailure.kind == "user") & (LoginFailure.key == username.lower()))
        )
    elif ip is not None:
        q = q.filter(LoginFailure.kind == "ip", LoginFailure.key == ip)
    elif username:
        q = q.filter(LoginFailure.kind == "user", LoginFailure.key == username.lower())
    else:
        return
    q.delete(synchronize_session=False)
    db.session.commit()


def user_is_locked(username):
    """True if a user's failure bucket is over threshold within the window."""
    if not username:
        return False
    return len(_failures_in_window("user", username.lower())) >= _LOGIN_MAX_FAILURES


def user_lockout_expires_in(username):
    """Seconds until the user's lockout expires, or 0 if not locked."""
    if not username:
        return 0
    times = _failures_in_window("user", username.lower())
    if len(times) < _LOGIN_MAX_FAILURES:
        return 0
    retry = int((times[0] + timedelta(seconds=_LOGIN_WINDOW_SECONDS)
                 - datetime.utcnow()).total_seconds())
    return max(retry, 0)


def clear_user_lockout(username):
    if not username:
        return
    (LoginFailure.query
     .filter(LoginFailure.kind == "user", LoginFailure.key == username.lower())
     .delete(synchronize_session=False))
    db.session.commit()


def currently_locked_usernames():
    """Set of lowercased usernames currently over threshold. One query."""
    rows = (db.session.query(LoginFailure.key)
            .filter(LoginFailure.kind == "user",
                    LoginFailure.failed_at >= _cutoff())
            .group_by(LoginFailure.key)
            .having(func.count(LoginFailure.id) >= _LOGIN_MAX_FAILURES)
            .all())
    return {r[0] for r in rows}


def _is_safe_url(target):
    """Allow only same-host relative redirects for ?next=."""
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return (test_url.scheme in ("http", "https")
            and ref_url.netloc == test_url.netloc)


def _verify_turnstile(site, token, remote_ip):
    """Returns (ok, error_message). Fails closed on any failure."""
    import requests
    secret = decrypt(site.turnstile_secret_key_enc) if site.turnstile_secret_key_enc else ""
    if not secret:
        return False, "Turnstile is enabled but no secret key is configured"
    if not token:
        return False, "Please complete the security check"
    try:
        resp = requests.post(
            TURNSTILE_VERIFY_URL,
            data={"secret": secret, "response": token, "remoteip": remote_ip or ""},
            timeout=5,
        )
        data = resp.json()
    except Exception as exc:
        current_app.logger.warning("Turnstile verify failed: %s", exc)
        return False, "Security check failed — please try again"
    if data.get("success"):
        return True, None
    return False, "Security check failed — please try again"


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    site = SiteSetting.query.first()
    ip = request.remote_addr or "unknown"
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        # Look up the user early so we can exempt admin accounts from the
        # per-username lockout. IP-based lockout still applies to everyone.
        user = User.query.filter(func.lower(User.username) == username.lower()).first()
        lockout_username = None if (user and user.is_admin()) else username
        blocked, retry = _login_rate_limit_hit(ip, lockout_username)
        if blocked:
            flash(f"Too many failed attempts. Try again in {max(retry, 1) // 60 + 1} minutes.",
                  "danger")
            return render_template("login.html"), 429
        if site and site.turnstile_enabled:
            token = request.form.get("cf-turnstile-response", "")
            ok, err = _verify_turnstile(site, token, request.remote_addr)
            if not ok:
                _record_login_failure(ip, lockout_username)
                flash(err, "danger")
                return render_template("login.html")
        if user and check_password_hash(user.password_hash, password):
            _clear_login_failures(ip=ip, username=user.username)
            session.permanent = True
            login_user(user, remember=True)
            next_url = request.args.get("next") or request.form.get("next")
            if next_url and _is_safe_url(next_url):
                return redirect(next_url)
            return redirect(url_for("main.index"))
        _record_login_failure(ip, lockout_username)
        flash("Invalid credentials", "danger")
    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@bp.route("/users")
@login_required
def users():
    if not current_user.is_admin():
        flash("Admins only", "danger")
        return redirect(url_for("main.index"))
    user_list = User.query.order_by(User.username).all()
    lockouts = {
        u.id: user_lockout_expires_in(u.username)
        for u in user_list if user_is_locked(u.username)
    }
    return render_template("users.html", users=user_list, roles=ROLES,
                           role_labels=ROLE_LABELS, lockouts=lockouts)


@bp.route("/users/<int:uid>/unlock", methods=["POST"])
@login_required
def users_unlock(uid):
    if not current_user.is_admin():
        return redirect(url_for("main.index"))
    u = db.session.get(User, uid)
    if u:
        clear_user_lockout(u.username)
        flash(f"Login lockout cleared for {u.username}", "success")
    return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))


@bp.route("/users/create", methods=["POST"])
@login_required
def users_create():
    if not current_user.is_admin():
        return redirect(url_for("main.index"))
    username = request.form["username"].strip()
    email = request.form["email"].strip()
    password = request.form["password"]
    phone = (request.form.get("phone") or "").strip() or None
    role = request.form.get("role", "viewer")
    if role not in ROLES:
        role = "viewer"
    if User.query.filter(
        (func.lower(User.username) == username.lower())
        | (func.lower(User.email) == email.lower())
    ).first():
        flash("Username or email already exists", "danger")
        return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))
    u = User(username=username, email=email, phone=phone,
             password_hash=generate_password_hash(password), role=role)
    db.session.add(u)
    db.session.commit()
    flash(f"User {username} created", "success")

    # Optional welcome email. Defaults to opt-in via the form checkbox;
    # falls back to the success path silently when SMTP isn't configured
    # or sending fails — the admin keeps the credentials they typed in
    # the form either way, so a missed email doesn't block account use.
    if request.form.get("send_welcome_email") == "1":
        ok, err = _send_welcome_email(u, password)
        if ok:
            flash(f"Welcome email sent to {u.email}", "success")
        else:
            flash(f"User created but welcome email failed: {err}", "warning")

    return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))


@bp.route("/users/<int:uid>/update", methods=["POST"])
@login_required
def users_update(uid):
    if not current_user.is_admin():
        return redirect(url_for("main.index"))
    u = db.session.get(User, uid)
    if not u:
        flash("User not found", "danger")
        return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))
    new_role = request.form.get("role")
    if new_role in ROLES:
        u.role = new_role
    new_email = request.form.get("email", "").strip()
    if new_email and new_email.lower() != (u.email or "").lower():
        clash = User.query.filter(
            func.lower(User.email) == new_email.lower(),
            User.id != u.id,
        ).first()
        if clash:
            flash(f"Email {new_email} is already in use", "danger")
            return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))
        u.email = new_email
    new_pw = request.form.get("password", "").strip()
    if new_pw:
        u.password_hash = generate_password_hash(new_pw)
    # Phone is optional and editable on every user-row save. The form
    # always submits the field (possibly blank), so a missing key here
    # is treated as "no change" rather than "clear" — an admin can clear
    # by submitting the field empty since "" → None below.
    if "phone" in request.form:
        u.phone = (request.form.get("phone") or "").strip() or None
    db.session.commit()
    flash("User updated", "success")
    return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))


@bp.route("/users/<int:uid>/delete", methods=["POST"])
@login_required
def users_delete(uid):
    if not current_user.is_admin():
        return redirect(url_for("main.index"))
    if uid == current_user.id:
        flash("Cannot delete yourself", "danger")
        return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))
    u = db.session.get(User, uid)
    if u:
        db.session.delete(u)
        db.session.commit()
        flash("User deleted", "success")
    return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))
