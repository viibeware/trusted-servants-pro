# SPDX-License-Identifier: AGPL-3.0-or-later
"""Notifications Center — derived, per-user attention feed.

Notifications are *derived* from live state, not stored as event rows:
each render walks the same attention sources the sidebar badges use
(pending access requests, locked accounts, unread contact messages,
submissions awaiting review) and turns each item into a notification
keyed by a stable string (``access_request:42``, ``locked_account:jdoe``,
``pending_post:17`` …). The only thing persisted is the user's
*dismissals* (``models.NotificationDismissal``).

This keeps the feature self-maintaining — there's no place an event can
be missed and no stored row that can drift from reality — while still
supporting "clear" + a live uncleared count:

  * ``active(user)``       — notification dicts the user hasn't dismissed.
  * ``unread_count(user)`` — how many of those there are (the chip).
  * ``dismiss``/``dismiss_all`` — record a clear.

Each source is gated by role so a user only ever sees notifications for
sections they can act on.
"""
from datetime import datetime

from flask import url_for
from sqlalchemy import func

from .models import (db, NotificationDismissal, AccessRequest,
                     ContactSubmission, Post, Story, RecoveryContact,
                     SiteSetting)


def _site():
    try:
        return SiteSetting.query.first()
    except Exception:  # noqa: BLE001
        return None


def _locked_usernames():
    try:
        from .auth import currently_locked_usernames
        return currently_locked_usernames()
    except Exception:  # noqa: BLE001
        return set()


def _items(user):
    """Every notification the user can currently see, before dismissal
    filtering. Returns a list of dicts: ``{key, category, icon, title,
    body, url, ts}`` (``ts`` may be None). Role-gated per source."""
    out = []
    if not user or not getattr(user, "is_authenticated", False):
        return out
    is_admin = user.is_admin()
    can_edit = user.can_edit()
    site = _site()

    if is_admin:
        for r in (AccessRequest.query
                  .filter_by(status="pending", is_archived=False)
                  .order_by(AccessRequest.created_at.desc()).all()):
            out.append({
                "key": f"access_request:{r.id}",
                "category": "Access requests",
                "icon": "user-plus",
                "title": f"Access request from {r.name}",
                "body": " · ".join(p for p in (r.email, r.meeting_name) if p),
                "url": url_for("main.watchtower_requests"),
                "ts": r.created_at,
            })
        for uname in sorted(_locked_usernames()):
            out.append({
                "key": f"locked_account:{uname}",
                "category": "Security",
                "icon": "lock",
                "title": f"Account locked: {uname}",
                "body": "Locked after too many failed sign-in attempts.",
                "url": url_for("main.watchtower_access"),
                "ts": None,
            })
        for c in (ContactSubmission.query
                  .filter_by(is_read=False, is_archived=False)
                  .order_by(ContactSubmission.created_at.desc()).all()):
            out.append({
                "key": f"contact_msg:{c.id}",
                "category": "Contact messages",
                "icon": "mail",
                "title": f"New message from {c.name}",
                "body": (c.subject or c.message or "").strip()[:140],
                "url": url_for("main.contact_form"),
                "ts": c.created_at,
            })
        # Low disk space — same derived source as the admin banner
        # (app/diskcheck.py). Stable key so a dismissal sticks until the
        # condition clears; the body re-derives each render so the figures
        # stay live. None below threshold → no notification.
        try:
            from flask import current_app
            from .diskcheck import disk_warning as _disk_warning
            dw = _disk_warning(current_app.config.get("DATA_DIR"))
        except Exception:  # noqa: BLE001 — never let a stat error break the feed
            dw = None
        if dw:
            out.append({
                "key": "disk_space:low",
                "category": "System",
                "icon": "hard-drive",
                "title": f"Low disk space — {dw['label']} {dw['percent']}% full",
                "body": (f"{dw['free_gb']} GB free of {dw['total_gb']} GB. "
                         "Free space before backups, uploads, or updates fail."),
                "url": url_for("main.backups_list"),
                "ts": None,
            })

    # Submissions awaiting review — visible to anyone who can act on the
    # holding tank (editors and up), matching the sidebar's pending chips.
    if can_edit and site and getattr(site, "posts_enabled", False):
        for p in (Post.query
                  .filter(Post.is_pending_review.is_(True),
                          Post.is_archived.is_(False))
                  .order_by(func.coalesce(Post.submitted_at,
                                          Post.created_at).desc()).all()):
            out.append({
                "key": f"pending_post:{p.id}",
                "category": "Submissions",
                "icon": "send",
                "title": f"Submission awaiting review: {p.title}",
                "body": (p.summary or "").strip()[:140],
                "url": url_for("main.posts", show="pending"),
                "ts": p.submitted_at or p.created_at,
            })
    if can_edit and site and getattr(site, "stories_enabled", False):
        for s in (Story.query
                  .filter(Story.is_pending_review.is_(True),
                          Story.is_archived.is_(False))
                  .order_by(func.coalesce(Story.submitted_at,
                                          Story.created_at).desc()).all()):
            out.append({
                "key": f"pending_story:{s.id}",
                "category": "Submissions",
                "icon": "book-open",
                "title": f"Story awaiting review: {s.title}",
                "body": (s.author_name or s.summary or "").strip()[:140],
                "url": url_for("main.stories", show="pending"),
                "ts": s.submitted_at or s.created_at,
            })
    # Pending Recovery Contacts submissions — same source + role gate as the
    # sidebar's pending chip (routes.py builds counts["pending_recovery_contacts"]
    # the same way). Unapproved rows include new listings plus self-service
    # update/removal requests; the verb in the title reflects which.
    if site and getattr(site, "recovery_contacts_enabled", False):
        try:
            from .permissions import user_meets_role
            allowed = user_meets_role(
                user, getattr(site, "recovery_contacts_required_role", "admin") or "admin")
        except Exception:  # noqa: BLE001
            allowed = False
        if allowed:
            for rc in (RecoveryContact.query
                       .filter_by(approved=False)
                       .order_by(RecoveryContact.created_at.desc()).all()):
                if rc.wants_removal:
                    verb, icon = "Removal request", "trash"
                elif rc.wants_update:
                    verb, icon = "Update request", "rotate-cw"
                else:
                    verb, icon = "New listing awaiting review", "user-plus"
                out.append({
                    "key": f"recovery_contact:{rc.id}",
                    "category": "Recovery Contacts",
                    "icon": icon,
                    "title": f"{verb}: {rc.name}",
                    "body": " · ".join(p for p in (rc.email, rc.phone) if p),
                    "url": url_for("main.recovery_contacts"),
                    "ts": rc.created_at,
                })
    return out


def dismissed_keys(user):
    if not user or not getattr(user, "is_authenticated", False):
        return set()
    rows = (db.session.query(NotificationDismissal.key)
            .filter(NotificationDismissal.user_id == user.id).all())
    return {r[0] for r in rows}


def active(user, prune=False):
    """Notification dicts the user hasn't dismissed, newest first.

    ``prune=True`` (used on the modal-open read) drops dismissals whose
    underlying item has resolved — keeping the table tidy and letting a
    recurring key surface again next time."""
    items = _items(user)
    keys = {it["key"] for it in items}
    dk = dismissed_keys(user)
    if prune and dk:
        stale = dk - keys
        if stale:
            (NotificationDismissal.query
             .filter(NotificationDismissal.user_id == user.id,
                     NotificationDismissal.key.in_(stale))
             .delete(synchronize_session=False))
            db.session.commit()
            dk -= stale
    out = [it for it in items if it["key"] not in dk]
    out.sort(key=lambda it: (it["ts"] is not None, it["ts"] or datetime.min),
             reverse=True)
    return out


def unread_count(user):
    """Number of uncleared notifications — drives the sidebar chip.
    Read-only (no prune) so it's safe to call from the context processor
    on every page render."""
    items = _items(user)
    if not items:
        return 0
    dk = dismissed_keys(user)
    if not dk:
        return len(items)
    return sum(1 for it in items if it["key"] not in dk)


def dismiss(user, key):
    """Record that ``key`` was cleared by ``user`` (idempotent)."""
    if not user or not getattr(user, "is_authenticated", False) or not key:
        return False
    key = str(key)[:128]
    if not (NotificationDismissal.query
            .filter_by(user_id=user.id, key=key).first()):
        db.session.add(NotificationDismissal(
            user_id=user.id, key=key, dismissed_at=datetime.utcnow()))
        db.session.commit()
    return True


def dismiss_all(user):
    """Clear every currently-active notification for ``user``. Returns
    how many were newly dismissed."""
    items = active(user)
    have = dismissed_keys(user)
    now = datetime.utcnow()
    n = 0
    for it in items:
        if it["key"] not in have:
            db.session.add(NotificationDismissal(
                user_id=user.id, key=it["key"][:128], dismissed_at=now))
            n += 1
    if n:
        db.session.commit()
    return n
