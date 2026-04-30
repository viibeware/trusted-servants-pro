# SPDX-License-Identifier: AGPL-3.0-or-later
"""Activity + login-session logging helpers.

Centralised so write endpoints can drop in a single ``log()`` call
without worrying about the surrounding plumbing — request lookup,
exception swallowing, and source-IP / user-agent capture are all
handled here. Every call is best-effort: if the insert raises for any
reason (DB lock, schema drift on an old install, etc.) the exception
is swallowed and the originating action proceeds. Logging must never
block a save.
"""
from datetime import datetime, timedelta
from flask import has_request_context, request
from flask_login import current_user
from .models import db, ActivityLog, LoginSession


def _client_ip():
    if not has_request_context():
        return None
    return (request.remote_addr or "")[:64] or None


def _user_agent():
    if not has_request_context():
        return None
    ua = request.headers.get("User-Agent", "") or ""
    return ua[:500] or None


def _resolve_user_id(user=None):
    if user is not None:
        return getattr(user, "id", None)
    if not has_request_context():
        return None
    if current_user.is_authenticated:
        return current_user.id
    return None


def log(action, *, summary=None, entity_type=None, entity_id=None,
        user=None, commit=True):
    """Append one row to the activity log. Pass ``user`` to override
    the resolved current_user (useful for cases like "admin reset
    Bob's password" where the *subject* user differs from the *actor*
    — pass the actor; record the subject in summary/entity)."""
    try:
        row = ActivityLog(
            user_id=_resolve_user_id(user),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=(summary or "")[:500] or None,
            ip=_client_ip(),
            created_at=datetime.utcnow(),
        )
        db.session.add(row)
        if commit:
            db.session.commit()
    except Exception:
        db.session.rollback()


def open_session(user):
    """Record a login. Closes any prior open session for this user (a
    new sign-in from the same browser supersedes the old session row),
    then inserts a fresh row. Returns the new session id or None on
    failure."""
    try:
        # Close prior open sessions for the same user — a fresh login
        # replaces them. Use ``replaced`` rather than ``logout`` so the
        # admin can distinguish "they logged out cleanly" from "they
        # signed in again somewhere else."
        now = datetime.utcnow()
        (LoginSession.query
         .filter(LoginSession.user_id == user.id,
                 LoginSession.ended_at.is_(None))
         .update({"ended_at": now, "end_reason": "replaced"},
                 synchronize_session=False))
        row = LoginSession(
            user_id=user.id,
            ip=_client_ip(),
            user_agent=_user_agent(),
            started_at=now,
            last_activity_at=now,
        )
        db.session.add(row)
        db.session.commit()
        return row.id
    except Exception:
        db.session.rollback()
        return None


def close_session(user, *, reason="logout"):
    """Mark every open session for this user as ended."""
    try:
        now = datetime.utcnow()
        (LoginSession.query
         .filter(LoginSession.user_id == user.id,
                 LoginSession.ended_at.is_(None))
         .update({"ended_at": now, "end_reason": reason},
                 synchronize_session=False))
        db.session.commit()
    except Exception:
        db.session.rollback()


def touch_session(user):
    """Bump ``last_activity_at`` on the user's currently-open session.
    Cheap UPDATE — fire from a request hook or whenever you have an
    authenticated request and want to track session liveness."""
    try:
        (LoginSession.query
         .filter(LoginSession.user_id == user.id,
                 LoginSession.ended_at.is_(None))
         .update({"last_activity_at": datetime.utcnow()},
                 synchronize_session=False))
        db.session.commit()
    except Exception:
        db.session.rollback()


# ---- LibraryItem helpers --------------------------------------------------------

def recent_activity(user_id, since_days=None, limit=500):
    q = ActivityLog.query.filter_by(user_id=user_id)
    if since_days:
        q = q.filter(ActivityLog.created_at >= datetime.utcnow() - timedelta(days=since_days))
    return q.order_by(ActivityLog.created_at.desc()).limit(limit).all()


def recent_sessions(user_id, since_days=30, limit=100):
    q = LoginSession.query.filter_by(user_id=user_id)
    if since_days:
        q = q.filter(LoginSession.started_at >= datetime.utcnow() - timedelta(days=since_days))
    return q.order_by(LoginSession.started_at.desc()).limit(limit).all()


# Display labels keyed by the snake_case action verb. Unknown verbs
# are rendered with the verb itself + a neutral icon, so adding new
# instrumentation never crashes the User Log page.
ACTION_LABELS = {
    "login":                ("Signed in",                  "log-in"),
    "login.failed":         ("Failed sign-in",             "alert-triangle"),
    "logout":               ("Signed out",                 "log-out"),
    "password.reset.self":  ("Reset their own password",   "key"),
    "password.reset.admin": ("Admin reset password",       "key"),
    "password.forgot":      ("Requested password reset",   "mail"),
    "user.create":          ("Created user",               "user-plus"),
    "user.update":          ("Updated user",               "user-cog"),
    "user.delete":          ("Deleted user",               "user-minus"),
    "user.unlock":          ("Cleared lockout",            "unlock"),
    "settings.save":        ("Saved site settings",        "settings"),
    "settings.smtp":        ("Saved SMTP settings",        "mail"),
    "meeting.create":       ("Created meeting",            "plus"),
    "meeting.update":       ("Updated meeting",            "edit"),
    "meeting.delete":       ("Deleted meeting",            "trash"),
    "library.create":       ("Created library",            "plus"),
    "library.update":       ("Updated library",            "edit"),
    "library.delete":       ("Deleted library",            "trash"),
    "reading.create":       ("Added reading",              "file-plus"),
    "reading.update":       ("Updated reading",            "edit"),
    "reading.delete":       ("Deleted reading",            "trash"),
    "file.upload":          ("Uploaded file",              "upload"),
    "file.rename":          ("Renamed file",               "edit"),
    "file.delete":          ("Deleted file",               "trash"),
    "post.create":          ("Created post",               "plus"),
    "post.update":          ("Updated post",               "edit"),
    "post.delete":          ("Deleted post",               "trash"),
    "access_request.handle": ("Handled access request",    "check"),
    "access_request.archive": ("Archived access request",  "archive"),
    "access_request.delete":  ("Deleted access request",   "trash"),
}


def label_for(action):
    return ACTION_LABELS.get(action, (action.replace(".", " ").replace("_", " ").capitalize(), "circle"))
