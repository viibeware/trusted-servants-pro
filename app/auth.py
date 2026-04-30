# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin
from flask import Blueprint, render_template, redirect, url_for, request, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash
from .models import db, User, SiteSetting, LoginFailure, PasswordResetToken, ROLES
from .crypto import decrypt

bp = Blueprint("auth", __name__, url_prefix="/tspro/auth")

# Friendly labels for the user-facing role <select> options. Keys map 1-1
# to the strings stored in ``User.role`` (see models.ROLES); raw keys still
# serve as a fallback when an unknown role appears.
ROLE_LABELS = {
    "admin":             "Admin",
    "editor":            "Editor",
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
    "Edit existing meetings, locations, schedules, and Zoom accounts (cannot create new meetings or delete existing ones — admin / Intergroup Member only).",
    "Add, edit, reorder, and delete files inside existing libraries (subject to per-row restrictions on library files).",
    "Cannot create new libraries or edit library settings (name, description, alert message) — admin / Intergroup Member only.",
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
        "Library files: may rename, edit, or delete only those whose uploader was another Editor. Admin-uploaded, Intergroup-Member-uploaded, and legacy library files are protected; this restriction does not apply to files attached to meetings.",
        "Cannot reach Settings, Users, the Web Frontend module, or the Intergroup Email Accounts page.",
        "Cannot edit Intergroup-flagged libraries (admin / Intergroup-Member only).",
    ],
    "intergroup_member": _EDITOR_BASE + [
        "Edit access to Intergroup-flagged libraries — regular Editors cannot edit those.",
        "May delete any library file regardless of who uploaded it.",
        "Cannot edit the Web Frontend module.",
        "Cannot reach Settings, Users, or the Intergroup Email Accounts page (admin-only).",
    ],
    "viewer": _VIEWER_BASE + [
        "Read-only access across the portal.",
        "Cannot edit, upload, or reach admin areas.",
    ],
}


PASSWORD_MIN_LENGTH = 12
PASSWORD_SYMBOLS = "!@#$%^&*?-_=+"
# Bedrock list of obvious-weak passwords that pass the character-class
# rules but should still be rejected. Keep the list short — the policy
# isn't a dictionary attack defender, just a "did you actually pick
# something deliberate" guardrail.
_WEAK_PASSWORDS = {
    "password", "password1", "password!", "password123",
    "letmein", "welcome", "welcome1", "qwerty",
    "admin", "administrator", "changeme", "trustedservants",
}


def validate_password_policy(pw, *, username=None, email=None):
    """Return ``(ok, errors)``. ``errors`` is a list of human-readable
    failures — empty when ``ok`` is True. Used by both the admin reset
    modal and the user-facing reset form so a single source of truth
    drives both server- and template-side hint rendering."""
    import string
    errors = []
    if not pw:
        return False, ["Password is required."]
    if len(pw) < PASSWORD_MIN_LENGTH:
        errors.append(f"Use at least {PASSWORD_MIN_LENGTH} characters.")
    if not any(c in string.ascii_lowercase for c in pw):
        errors.append("Add a lowercase letter.")
    if not any(c in string.ascii_uppercase for c in pw):
        errors.append("Add an uppercase letter.")
    if not any(c in string.digits for c in pw):
        errors.append("Add a digit.")
    if not any(c in PASSWORD_SYMBOLS for c in pw):
        errors.append(f"Add a symbol ({PASSWORD_SYMBOLS}).")
    low = pw.lower()
    if low in _WEAK_PASSWORDS:
        errors.append("This password is on the common-weak list — pick something else.")
    if username and username.lower() and username.lower() in low:
        errors.append("Password must not contain your username.")
    if email:
        local = email.split("@", 1)[0].lower()
        if local and len(local) >= 4 and local in low:
            errors.append("Password must not contain your email address.")
    return (not errors), errors


def _generate_password(length=16):
    """Generate a random password mixing uppercase, lowercase, digits, and
    symbols, with at least one character from each class guaranteed. Uses
    ``secrets`` for cryptographic quality and shuffles via ``SystemRandom``
    so the guaranteed-class characters aren't always at fixed positions.
    Symbol set is curated to characters that are safe to paste into a
    plain-text email and easy to type on most keyboards."""
    import secrets
    import string
    symbols = "!@#$%^&*?-_=+"
    classes = (string.ascii_lowercase, string.ascii_uppercase,
               string.digits, symbols)
    pool = "".join(classes)
    chars = [secrets.choice(c) for c in classes]
    chars += [secrets.choice(pool) for _ in range(max(length - len(classes), 0))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


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
            from . import activity
            activity.open_session(user)
            activity.log("login", user=user, summary=f"Signed in from {ip}")
            next_url = request.args.get("next") or request.form.get("next")
            if next_url and _is_safe_url(next_url):
                return redirect(next_url)
            return redirect(url_for("main.index"))
        _record_login_failure(ip, lockout_username)
        from . import activity
        # Log the failed attempt against the matched user when one
        # exists (so the User Log shows attempts even on accounts
        # that aren't currently signed in); fall back to a None
        # user_id when the username is unknown so we don't drop the
        # signal entirely.
        activity.log("login.failed",
                     user=user,
                     summary=(f"Failed sign-in attempt for '{username}' from {ip}"
                              if username else f"Failed sign-in from {ip}"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    from . import activity
    actor = current_user._get_current_object() if hasattr(current_user, "_get_current_object") else current_user
    activity.log("logout", user=actor, summary="Signed out")
    activity.close_session(actor, reason="logout")
    logout_user()
    return redirect(url_for("auth.login"))


# ---- Forgot / reset password (public) ---------------------------------------
# A two-step flow:
#   1. /forgot-password — user enters their email or username; we always
#      respond with the same generic success message regardless of match
#      (no account-enumeration). When a match is found AND SMTP is set
#      up, we generate a single-use token, persist its SHA-256 hash, and
#      email a /reset-password/<token> link.
#   2. /reset-password/<token> — token is validated (exists, unused, not
#      expired). Form: new password + confirm, with policy enforcement
#      identical to the admin reset modal. On success: hash the new
#      password, mark the token used, clear any active lockout, sign
#      the user in, and bounce to the dashboard.
RESET_TOKEN_TTL_HOURS = 1
# Per-IP / per-account rate limit for the request endpoint. Defends
# against someone spamming the form with random emails to trigger a
# wave of outbound mail. The window deliberately matches the login
# limiter's window so the constants stay coherent.
_RESET_REQUEST_MAX_PER_WINDOW = 5


def _hash_reset_token(token):
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _purge_stale_reset_tokens():
    """Drop expired or already-used tokens. Run lazily on token issue
    so the table doesn't grow unbounded; the volume is too low to
    justify a scheduled job."""
    cutoff = datetime.utcnow() - timedelta(days=7)
    try:
        (PasswordResetToken.query
         .filter((PasswordResetToken.expires_at < datetime.utcnow())
                 | (PasswordResetToken.used_at.isnot(None))
                 | (PasswordResetToken.created_at < cutoff))
         .delete(synchronize_session=False))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _send_reset_email(user, token):
    from .mail import send_mail
    site = SiteSetting.query.first()
    if not site or not site.smtp_host or not site.smtp_from_email:
        return False, "SMTP is not configured"
    if not user.email:
        return False, "User has no email address"
    from .routes import _public_url_for
    link = _public_url_for("auth.reset_password", token=token)
    portal_name = (site.smtp_from_name or "Trusted Servants Pro").strip() or "Trusted Servants Pro"
    body = (
        f"Hello {user.username},\n\n"
        f"Someone requested a password reset for your {portal_name} account. "
        f"If that was you, follow the link below to choose a new password. "
        f"The link is valid for {RESET_TOKEN_TTL_HOURS} hour"
        f"{'s' if RESET_TOKEN_TTL_HOURS != 1 else ''} and can only be used once.\n\n"
        f"  {link}\n\n"
        f"If you didn't request this, you can safely ignore this email — "
        f"your password will stay the same.\n\n"
        f"— Trusted Servants Pro"
    )
    return send_mail(site, user.email, f"Reset your {portal_name} password", body)


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        identifier = (request.form.get("identifier") or "").strip()
        if not identifier:
            flash("Enter the email or username on the account.", "danger")
            return render_template("forgot_password.html")

        # Look up by email OR username, case-insensitive on both. Always
        # show the same success copy regardless of match so the form
        # can't be used as an account enumerator.
        user = User.query.filter(
            (func.lower(User.email) == identifier.lower())
            | (func.lower(User.username) == identifier.lower())
        ).first()

        if user and getattr(user, "password_reset_allowed", True):
            _purge_stale_reset_tokens()
            import secrets as _secrets
            token = _secrets.token_urlsafe(32)
            row = PasswordResetToken(
                user_id=user.id,
                token_hash=_hash_reset_token(token),
                expires_at=datetime.utcnow() + timedelta(hours=RESET_TOKEN_TTL_HOURS),
                requested_ip=(request.remote_addr or "")[:64],
            )
            db.session.add(row)
            db.session.commit()
            from . import activity
            activity.log("password.forgot", user=user,
                         summary=f"Requested password reset (matched on '{identifier}')")
            ok, err = _send_reset_email(user, token)
            if not ok:
                # Surface the SMTP failure to server logs but never to the
                # browser — leaking "we tried to send to that address but
                # SMTP failed" still confirms the account exists. The user
                # sees the same generic success page either way.
                current_app.logger.warning(
                    "Password reset email failed for user_id=%s: %s", user.id, err)
        elif user:
            # Self-service reset disabled for this account. Log the
            # blocked attempt for the User Log audit, but render the
            # same generic success page so the form can't be used to
            # enumerate which accounts have the gate flipped off.
            from . import activity
            activity.log("password.forgot.blocked", user=user,
                         summary=(f"Forgot-password request blocked — "
                                  f"reset disabled on this account "
                                  f"(matched on '{identifier}')"))

        return render_template("forgot_password.html", submitted=True)
    return render_template("forgot_password.html")


def _lookup_reset_token(token):
    """Resolve a plaintext token from the URL to its DB row, or None.
    Centralises the hash + validity check so both GET and POST handlers
    can short-circuit on the same logic."""
    if not token or len(token) > 128:
        return None
    row = PasswordResetToken.query.filter_by(token_hash=_hash_reset_token(token)).first()
    if not row or not row.is_valid():
        return None
    return row


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        # Don't bind the new password to whoever happens to be logged in
        # on this browser — sign them out first so the reset truly applies
        # to the account named by the token.
        logout_user()
    row = _lookup_reset_token(token)
    if row is None:
        return render_template("reset_password.html",
                               token=token, invalid=True), 400
    user = db.session.get(User, row.user_id)
    if user is None:
        return render_template("reset_password.html",
                               token=token, invalid=True), 400

    if request.method == "POST":
        pw1 = request.form.get("password", "")
        pw2 = request.form.get("password_confirm", "")
        # Re-resolve the row inside the POST so a token used in another
        # tab in the same second can't double-spend.
        row = _lookup_reset_token(token)
        if row is None:
            return render_template("reset_password.html",
                                   token=token, invalid=True), 400
        errors = []
        if pw1 != pw2:
            errors.append("The two passwords don't match.")
        ok_pol, pol_errs = validate_password_policy(
            pw1, username=user.username, email=user.email)
        if not ok_pol:
            errors.extend(pol_errs)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("reset_password.html",
                                   token=token, user=user)

        user.password_hash = generate_password_hash(pw1)
        row.used_at = datetime.utcnow()
        # Invalidate any other live tokens on this account — once you've
        # successfully reset, every previously-issued link is moot.
        (PasswordResetToken.query
         .filter(PasswordResetToken.user_id == user.id,
                 PasswordResetToken.id != row.id,
                 PasswordResetToken.used_at.is_(None))
         .update({"used_at": datetime.utcnow()},
                 synchronize_session=False))
        db.session.commit()
        clear_user_lockout(user.username)
        session.permanent = True
        login_user(user, remember=True)
        from . import activity
        activity.open_session(user)
        activity.log("password.reset.self", user=user,
                     summary="Reset password via emailed link")
        flash("Password updated. You're signed in.", "success")
        return redirect(url_for("main.index"))

    return render_template("reset_password.html", token=token, user=user)


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
        from . import activity
        activity.log("user.unlock", entity_type="user", entity_id=u.id,
                     summary=f"Cleared login lockout for {u.username}")
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
    from . import activity
    activity.log("user.create", entity_type="user", entity_id=u.id,
                 summary=f"Created user {username} ({role})")
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
    new_username = request.form.get("username", "").strip()
    if new_username and new_username != u.username:
        if len(new_username) > 64:
            flash("Username must be 64 characters or fewer", "danger")
            return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))
        # Case-insensitive collision check — login lookup is also
        # case-insensitive, so two usernames that differ only in case
        # would collide at sign-in time even if SQLite considers them
        # distinct strings.
        clash = User.query.filter(
            func.lower(User.username) == new_username.lower(),
            User.id != u.id,
        ).first()
        if clash:
            flash(f"Username {new_username} is already in use", "danger")
            return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))
        u.username = new_username
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
    # Phone is optional and editable on every user-row save. The form
    # always submits the field (possibly blank), so a missing key here
    # is treated as "no change" rather than "clear" — an admin can clear
    # by submitting the field empty since "" → None below.
    if "phone" in request.form:
        u.phone = (request.form.get("phone") or "").strip() or None
    db.session.commit()
    from . import activity
    activity.log("user.update", entity_type="user", entity_id=u.id,
                 summary=f"Updated user {u.username} (role={u.role})")
    flash("User updated", "success")
    return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))


@bp.route("/users/<int:uid>/reset_password", methods=["POST"])
@login_required
def users_reset_password(uid):
    """Admin action: set a user's password to either a freshly-generated
    random string or an admin-supplied custom value, then resend the
    welcome email so the recipient knows what changed. Replaces the
    earlier "resend welcome" route."""
    if not current_user.is_admin():
        return redirect(url_for("main.index"))

    # Honor a same-host return_url so the modal can be invoked from
    # pages other than the Users panel (e.g. Access Requests). Falls
    # back to the Users panel — preserving the embed=1 hint when the
    # request came from inside the Settings iframe.
    def _bounce():
        ru = (request.form.get("return_url") or "").strip()
        if ru and _is_safe_url(ru):
            return redirect(ru)
        if request.form.get("embed") == "1":
            return redirect(url_for("auth.users", embed=1))
        return redirect(url_for("auth.users"))

    u = db.session.get(User, uid)
    if not u:
        flash("User not found", "danger")
        return _bounce()
    send_email = request.form.get("send_email", "1") == "1"
    if send_email and not u.email:
        flash(f"{u.username} has no email address on file — set one or use Save without emailing.", "warning")
        return _bounce()

    mode = request.form.get("mode", "generate")
    if mode == "custom":
        new_pw = request.form.get("password", "")
        ok_pol, errs = validate_password_policy(new_pw, username=u.username, email=u.email)
        if not ok_pol:
            flash("Password rejected: " + " ".join(errs), "danger")
            return _bounce()
    else:
        new_pw = _generate_password()

    if send_email:
        # Send first; only persist on success so an SMTP failure doesn't
        # silently invalidate the user's existing password and lock them
        # out of an account they were otherwise still using.
        ok, err = _send_welcome_email(u, new_pw)
        if not ok:
            flash(f"Could not send welcome email: {err} — password was not changed.", "danger")
            return _bounce()

    u.password_hash = generate_password_hash(new_pw)
    # Invalidate every live forgot-password token on this account — an
    # admin-driven reset supersedes any pending email link the user
    # may still have in their inbox, and the Access Requests page reads
    # exactly this signal to decide whether to surface a "pending reset"
    # row, so consuming the token here clears that row in one motion.
    (PasswordResetToken.query
     .filter(PasswordResetToken.user_id == u.id,
             PasswordResetToken.used_at.is_(None))
     .update({"used_at": datetime.utcnow()},
             synchronize_session=False))
    db.session.commit()
    # Clear any active lockout — the user is getting a fresh start.
    clear_user_lockout(u.username)
    from . import activity
    activity.log("password.reset.admin",
                 entity_type="user", entity_id=u.id,
                 summary=(f"Admin reset password for {u.username} "
                          f"(mode={mode}, email_sent={'yes' if send_email else 'no'})"))
    if send_email:
        flash(f"Password reset for {u.username}; welcome email sent to {u.email}.", "success")
    elif mode == "custom":
        flash(f"Password reset for {u.username}. No email was sent — share the new password with them through another channel.", "success")
    else:
        # Generated password without email is a footgun: the admin needs
        # to be told the value, since neither the user nor the database
        # holds it in plaintext anywhere else.
        flash(f"Password reset for {u.username}. No email was sent — the new password is: {new_pw}", "success")
    return _bounce()


@bp.route("/users/generate-password", methods=["POST"])
@login_required
def users_generate_password():
    """JSON endpoint used by the admin Reset Password modal to fetch a
    fresh random password for the "Generate" tab. Admin-only."""
    from flask import jsonify
    if not current_user.is_admin():
        return jsonify({"error": "forbidden"}), 403
    return jsonify({"password": _generate_password()})


@bp.route("/users/<int:uid>/reset-allowed", methods=["POST"])
@login_required
def users_set_reset_allowed(uid):
    """Toggle the per-user ``password_reset_allowed`` flag. Posted by
    the small switch on each row of Settings → Users. Returns JSON for
    the AJAX caller; falls back to a redirect for noscript form posts."""
    from flask import jsonify
    if not current_user.is_admin():
        return jsonify({"error": "forbidden"}), 403
    u = db.session.get(User, uid)
    if not u:
        return jsonify({"error": "not found"}), 404
    allowed = request.form.get("allowed") == "1"
    u.password_reset_allowed = allowed
    # When toggling reset OFF, invalidate any live tokens already in
    # the user's inbox — keeping them around would defeat the gate.
    if not allowed:
        (PasswordResetToken.query
         .filter(PasswordResetToken.user_id == u.id,
                 PasswordResetToken.used_at.is_(None))
         .update({"used_at": datetime.utcnow()},
                 synchronize_session=False))
    db.session.commit()
    from . import activity
    activity.log("user.reset_gate", entity_type="user", entity_id=u.id,
                 summary=(f"{'Enabled' if allowed else 'Disabled'} self-service "
                          f"password reset for {u.username}"))
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True, allowed=allowed)
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
        from . import activity
        # Log BEFORE the cascade nukes the row — entity_id stays valid
        # but the FK on activity_log uses ON DELETE SET NULL so rows
        # describing this user remain intact (and the username is in
        # the summary string for posterity).
        activity.log("user.delete", entity_type="user", entity_id=u.id,
                     summary=f"Deleted user {u.username}")
        db.session.delete(u)
        db.session.commit()
        flash("User deleted", "success")
    return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))
