# SPDX-License-Identifier: AGPL-3.0-or-later
import time
from collections import defaultdict, deque
from threading import Lock
from urllib.parse import urlparse, urljoin
from flask import Blueprint, render_template, redirect, url_for, request, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from .models import db, User, SiteSetting, ROLES
from .crypto import decrypt

bp = Blueprint("auth", __name__, url_prefix="/auth")

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# Simple in-memory login rate limiter. Not distributed across processes;
# adequate for a single gunicorn instance handling a small fellowship portal.
_LOGIN_WINDOW_SECONDS = 900   # 15 minutes
_LOGIN_MAX_FAILURES = 10
_login_failures = defaultdict(deque)
_login_lock = Lock()


def _login_rate_limit_hit(ip):
    """Return (blocked, retry_after_seconds). Non-destructive read."""
    now = time.time()
    with _login_lock:
        q = _login_failures.get(ip)
        if not q:
            return False, 0
        while q and q[0] < now - _LOGIN_WINDOW_SECONDS:
            q.popleft()
        if len(q) >= _LOGIN_MAX_FAILURES:
            return True, int(q[0] + _LOGIN_WINDOW_SECONDS - now)
    return False, 0


def _record_login_failure(ip):
    now = time.time()
    with _login_lock:
        q = _login_failures[ip]
        while q and q[0] < now - _LOGIN_WINDOW_SECONDS:
            q.popleft()
        q.append(now)


def _clear_login_failures(ip):
    with _login_lock:
        _login_failures.pop(ip, None)


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
        blocked, retry = _login_rate_limit_hit(ip)
        if blocked:
            flash(f"Too many failed attempts. Try again in {max(retry, 1) // 60 + 1} minutes.",
                  "danger")
            return render_template("login.html"), 429
        if site and site.turnstile_enabled:
            token = request.form.get("cf-turnstile-response", "")
            ok, err = _verify_turnstile(site, token, request.remote_addr)
            if not ok:
                _record_login_failure(ip)
                flash(err, "danger")
                return render_template("login.html")
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            _clear_login_failures(ip)
            session.permanent = True
            login_user(user, remember=True)
            next_url = request.args.get("next") or request.form.get("next")
            if next_url and _is_safe_url(next_url):
                return redirect(next_url)
            return redirect(url_for("main.index"))
        _record_login_failure(ip)
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
    return render_template("users.html", users=User.query.order_by(User.username).all(), roles=ROLES)


@bp.route("/users/create", methods=["POST"])
@login_required
def users_create():
    if not current_user.is_admin():
        return redirect(url_for("main.index"))
    username = request.form["username"].strip()
    email = request.form["email"].strip()
    password = request.form["password"]
    role = request.form.get("role", "viewer")
    if role not in ROLES:
        role = "viewer"
    if User.query.filter((User.username == username) | (User.email == email)).first():
        flash("Username or email already exists", "danger")
        return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))
    u = User(username=username, email=email,
             password_hash=generate_password_hash(password), role=role)
    db.session.add(u)
    db.session.commit()
    flash(f"User {username} created", "success")
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
    if new_email and new_email != u.email:
        clash = User.query.filter(User.email == new_email, User.id != u.id).first()
        if clash:
            flash(f"Email {new_email} is already in use", "danger")
            return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))
        u.email = new_email
    new_pw = request.form.get("password", "").strip()
    if new_pw:
        u.password_hash = generate_password_hash(new_pw)
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
