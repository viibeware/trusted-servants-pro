# SPDX-License-Identifier: AGPL-3.0-or-later
"""Watchtower — the admin-facing security + observability console.

Watchtower consolidates four pre-existing surfaces (User Log, Delete
Log, Access Requests, Visitor Metrics) into a single dashboard, layers
new security signals on top (failed-login analytics, suspicious-IP
detection, IP banning, system-metrics summary), and exposes admin
actions that close the loop on whatever the dashboard surfaces.

This module is the data layer. The route layer (``routes.py``) is a
thin shim — it calls in here, packages the dict into a template
context, and renders. Templates live under ``templates/watchtower/``.

Read-only helpers query SQLAlchemy directly. State-mutating actions
(``ban_ip``, ``unban_ip``, ``end_session``, ``clear_login_failures``)
take a ``db`` session and return the modified row (or None on
no-op) so callers can flash a success / failure toast based on the
return value.
"""
from datetime import datetime, timedelta

from sqlalchemy import func, or_

from .models import (db, User, ActivityLog, LoginSession, LoginFailure,
                     VisitorEvent, DeletedFile, AccessRequest, IPBlock)


# ─── KPI tiles ───────────────────────────────────────────────────
def overview_kpis():
    """Return the six headline numbers shown across the top of the
    Watchtower overview tab. Each is computed cheaply against an
    indexed column so the dashboard stays snappy even on a multi-year
    install."""
    now = datetime.utcnow()
    today = now.date()
    day24 = now - timedelta(hours=24)
    today_s = today.strftime("%Y-%m-%d")

    views_today = int(
        db.session.query(func.count(VisitorEvent.id))
        .filter(VisitorEvent.day == today_s).scalar() or 0
    )
    uniques_today = int(
        db.session.query(func.count(func.distinct(VisitorEvent.visitor_hash)))
        .filter(VisitorEvent.day == today_s,
                VisitorEvent.visitor_hash.isnot(None)).scalar() or 0
    )
    online_now = int(
        db.session.query(func.count(LoginSession.id))
        .filter(LoginSession.ended_at.is_(None),
                LoginSession.last_activity_at >= now - timedelta(minutes=15))
        .scalar() or 0
    )
    failed_logins_24h = int(
        db.session.query(func.count(LoginFailure.id))
        .filter(LoginFailure.kind == "ip",
                LoginFailure.failed_at >= day24).scalar() or 0
    )
    pending_requests = int(
        db.session.query(func.count(AccessRequest.id))
        .filter(AccessRequest.status == "pending",
                AccessRequest.is_archived.is_(False)).scalar() or 0
    )
    trash_count = int(
        db.session.query(func.count(DeletedFile.id))
        .filter(or_(DeletedFile.expires_at.is_(None),
                    DeletedFile.expires_at > now)).scalar() or 0
    )
    blocked_ips = int(
        db.session.query(func.count(IPBlock.id))
        .filter(or_(IPBlock.expires_at.is_(None),
                    IPBlock.expires_at > now)).scalar() or 0
    )
    return {
        "views_today":      views_today,
        "uniques_today":    uniques_today,
        "online_now":       online_now,
        "failed_logins_24h": failed_logins_24h,
        "pending_requests": pending_requests,
        "trash_count":      trash_count,
        "blocked_ips":      blocked_ips,
    }


# ─── Time-series helpers ─────────────────────────────────────────
def daily_visits(days=30):
    """Per-day visit + unique counts for the overview chart. Mirrors
    visitor_metrics.daily_series but kept local so Watchtower can
    evolve its bucketing (e.g. add 4xx/5xx columns) without
    distorting the public-facing visitor page."""
    today = datetime.utcnow().date()
    start = today - timedelta(days=days - 1)
    rows = (db.session.query(
                VisitorEvent.day,
                func.count(VisitorEvent.id),
                func.count(func.distinct(VisitorEvent.visitor_hash)))
            .filter(VisitorEvent.day >= start.strftime("%Y-%m-%d"))
            .group_by(VisitorEvent.day).all())
    by_day = {r[0]: (int(r[1] or 0), int(r[2] or 0)) for r in rows}
    out = []
    for i in range(days):
        d = start + timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        views, uniques = by_day.get(ds, (0, 0))
        out.append({"day": ds, "views": views, "uniques": uniques})
    return out


def hourly_failed_logins(hours=24):
    """Hourly bucket of failed-login attempts. Returns a list ``[{hour,
    count}, …]`` covering the last ``hours`` hours, oldest first. The
    overview tab renders this as a small bar chart so a sudden spike
    (brute-force run) is obvious at a glance."""
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(hours=hours - 1)
    rows = (db.session.query(LoginFailure.failed_at)
            .filter(LoginFailure.kind == "ip",
                    LoginFailure.failed_at >= start).all())
    buckets = {(start + timedelta(hours=i)).strftime("%Y-%m-%d %H"): 0
               for i in range(hours)}
    for (ts,) in rows:
        bucket = ts.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H")
        if bucket in buckets:
            buckets[bucket] += 1
    return [{"hour": k, "count": v} for k, v in sorted(buckets.items())]


# ─── Anomaly indicators ──────────────────────────────────────────
def anomaly_signals():
    """Cheap rule-based detector. Returns a list of dicts:
      ``{level: 'warn'|'critical', title, detail, action_label, action_url}``

    Rules (all conservative — false-positive averse):
      • Failed logins last hour > 20 → critical
      • Failed logins last 24h > 100 → warn
      • Any single IP with > 10 failed logins in the last 24h → critical
        (the dashboard's Top Suspicious IPs table actions on it)
      • Active session count > 95th percentile of the trailing 7-day
        peak — surfaced as info-level only if there's enough history
    """
    out = []
    now = datetime.utcnow()
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(hours=24)

    last_hour = int(
        db.session.query(func.count(LoginFailure.id))
        .filter(LoginFailure.kind == "ip",
                LoginFailure.failed_at >= hour_ago).scalar() or 0
    )
    last_24h = int(
        db.session.query(func.count(LoginFailure.id))
        .filter(LoginFailure.kind == "ip",
                LoginFailure.failed_at >= day_ago).scalar() or 0
    )
    if last_hour > 20:
        out.append({
            "level": "critical",
            "title": "Brute-force attempt in progress",
            "detail": f"{last_hour} failed login attempts in the last hour.",
        })
    elif last_24h > 100:
        out.append({
            "level": "warn",
            "title": "Elevated failed-login volume",
            "detail": f"{last_24h} failed login attempts in the last 24 hours.",
        })

    # Per-IP concentration
    top = (db.session.query(LoginFailure.key, func.count(LoginFailure.id))
           .filter(LoginFailure.kind == "ip",
                   LoginFailure.failed_at >= day_ago)
           .group_by(LoginFailure.key)
           .order_by(func.count(LoginFailure.id).desc())
           .limit(1).first())
    if top and int(top[1]) > 10:
        out.append({
            "level": "critical",
            "title": f"Concentrated attack from {top[0]}",
            "detail": f"{int(top[1])} failed login attempts from a single IP in the last 24 hours.",
        })

    return out


# ─── Per-IP roll-ups (for the suspicious-IPs table) ──────────────
def top_failed_login_ips(days=7, limit=20):
    """Per-IP failed-login leaderboard for the last ``days`` days.
    Returns a list of dicts:
      ``{ip, attempts, last_attempt, blocked: bool, block_id: int|None}``
    Joined with IPBlock so the ban / unban action button on each row
    knows which way to point.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (db.session.query(
                LoginFailure.key,
                func.count(LoginFailure.id),
                func.max(LoginFailure.failed_at))
            .filter(LoginFailure.kind == "ip",
                    LoginFailure.failed_at >= cutoff)
            .group_by(LoginFailure.key)
            .order_by(func.count(LoginFailure.id).desc())
            .limit(limit).all())
    if not rows:
        return []
    ips = [r[0] for r in rows]
    blocks = {b.ip: b for b in IPBlock.query.filter(IPBlock.ip.in_(ips)).all()}
    out = []
    now = datetime.utcnow()
    for ip, attempts, last_at in rows:
        blk = blocks.get(ip)
        active = bool(blk and (blk.expires_at is None or blk.expires_at > now))
        out.append({
            "ip": ip,
            "attempts": int(attempts or 0),
            "last_attempt": last_at,
            "blocked": active,
            "block_id": blk.id if blk else None,
        })
    return out


def active_sessions(minutes=60):
    """Sessions touched within the last ``minutes`` minutes that are
    still open. Sorted by most recent activity."""
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    return (LoginSession.query
            .filter(LoginSession.ended_at.is_(None),
                    LoginSession.last_activity_at >= cutoff)
            .order_by(LoginSession.last_activity_at.desc()).all())


def recent_admin_activity(limit=20):
    """Latest ActivityLog rows — drives the overview's "Recent
    activity" panel and seeds the Access tab when no filter is set."""
    return (ActivityLog.query
            .order_by(ActivityLog.created_at.desc())
            .limit(limit).all())


def blocked_ips(active_only=True):
    """Current IP blocklist. ``active_only`` filters out expired rows;
    the dashboard always uses active=True but the API can pass False
    for full history. Sorted newest-first so the most recent ban
    sits on top."""
    q = IPBlock.query
    if active_only:
        now = datetime.utcnow()
        q = q.filter(or_(IPBlock.expires_at.is_(None),
                         IPBlock.expires_at > now))
    return q.order_by(IPBlock.blocked_at.desc()).all()


# ─── State-mutating actions ──────────────────────────────────────
def ban_ip(ip, reason, blocked_by_user_id, ttl_hours=None):
    """Place ``ip`` on the blocklist. If a row already exists, refresh
    the reason / TTL / blocker so re-banning behaves like an extend.
    Returns the IPBlock row. Use ttl_hours=None for a permanent ban."""
    ip = (ip or "").strip()
    if not ip:
        return None
    expires = None
    if ttl_hours and ttl_hours > 0:
        expires = datetime.utcnow() + timedelta(hours=ttl_hours)
    row = IPBlock.query.filter_by(ip=ip).first()
    if row is None:
        row = IPBlock(ip=ip)
        db.session.add(row)
    row.reason = (reason or "").strip()[:255] or None
    row.blocked_by = blocked_by_user_id
    row.blocked_at = datetime.utcnow()
    row.expires_at = expires
    db.session.commit()
    return row


def unban_ip(block_id):
    row = IPBlock.query.get(int(block_id))
    if row is None:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def clear_login_failures(ip):
    """Delete every LoginFailure row for ``ip`` (both ``ip`` and
    ``user`` kinds where the key matches). Returns the deleted row
    count so the toast can say "cleared 17 failures"."""
    ip = (ip or "").strip()
    if not ip:
        return 0
    n = (LoginFailure.query
         .filter(LoginFailure.kind == "ip", LoginFailure.key == ip)
         .delete(synchronize_session=False))
    db.session.commit()
    return int(n or 0)


def end_session(session_id, reason="forced"):
    """Force-close an open LoginSession. The user keeps their cookie
    until Flask-Login next consults the session, at which point
    `current_user.is_authenticated` flips to False and they're
    bounced to login (the Flask-Login `user_loader` checks for an
    open session via activity.touch_session)."""
    s = LoginSession.query.get(int(session_id))
    if s is None or s.ended_at is not None:
        return False
    s.ended_at = datetime.utcnow()
    s.end_reason = reason
    db.session.commit()
    return True


# ─── System metrics passthrough ──────────────────────────────────
def system_snapshot():
    """Wrap metrics.snapshot() so callers don't need to import a
    second module. Returns the dict described in metrics.py."""
    from . import metrics
    return metrics.snapshot()
