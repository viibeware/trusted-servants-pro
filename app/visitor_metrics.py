# SPDX-License-Identifier: AGPL-3.0-or-later
"""Visitor metrics — anonymous frontend-page-view tracking + aggregation.

This module owns three concerns:

  1. **Recording** — a Flask `before_request` hook on the frontend
     blueprint that inserts one `VisitorEvent` row per real human page
     view. Logged-in users, bots, asset requests, and prefetches are
     dropped before insert.
  2. **Parsing** — small, dependency-free `User-Agent` heuristics that
     classify each visit into device / browser / OS families. We could
     pull in `ua-parser` but a 30-line lookup table keeps the metrics
     box self-contained.
  3. **Aggregation** — the queries that drive the admin metrics page
     and dashboard widget (totals, daily series, top paths, etc.).

Privacy: no IP, no User-Agent string, no Referer URL are persisted.
Each row carries a daily-rotating one-way hash of (IP, UA, salt) for
unique-visitor approximation; the salt rotates at UTC midnight so
the hash isn't a stable identifier across days. See
``models.VisitorEvent`` for the column-level commentary.
"""
import hashlib
import re
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import current_app, request
from flask_login import current_user
from sqlalchemy import func

from .models import db, VisitorEvent, NotFoundEvent


# Patterns matched against the lowercased UA string. The first hit wins,
# so order matters — Edge identifies itself with "edg/" but also includes
# "chrome" in its UA, so Edge has to come before Chrome.
_BROWSER_PATTERNS = (
    ("Edge",    re.compile(r"\bedg(e|a|ios)?/")),
    ("Opera",   re.compile(r"\b(opera|opr/)")),
    ("Vivaldi", re.compile(r"\bvivaldi/")),
    ("Brave",   re.compile(r"\bbrave/")),
    ("Firefox", re.compile(r"\bfirefox/")),
    ("Chrome",  re.compile(r"\bchrom(e|ium)/")),
    ("Safari",  re.compile(r"\bsafari/")),
    ("IE",      re.compile(r"\b(msie|trident/)")),
)

_OS_PATTERNS = (
    ("iOS",     re.compile(r"\b(iphone|ipad|ipod)\b")),
    ("Android", re.compile(r"\bandroid\b")),
    ("macOS",   re.compile(r"\b(macintosh|mac os x)\b")),
    ("Windows", re.compile(r"\bwindows\b")),
    ("Linux",   re.compile(r"\blinux\b")),
    ("ChromeOS", re.compile(r"\bcros\b")),
)

# Substrings that mark a UA as a crawler/bot. Cheap, conservative — the
# point is to keep obvious automation out of the metrics, not to be a
# bot-detection product. Anything not matched here that looks botty in
# the metrics page can be added later without a migration.
_BOT_TOKENS = (
    "bot", "spider", "crawler", "slurp", "bingpreview", "facebookexternalhit",
    "facebot", "twitterbot", "linkedinbot", "embedly", "quora link preview",
    "discordbot", "telegrambot", "whatsapp", "applebot", "yandex", "baiduspider",
    "duckduckbot", "ahrefsbot", "semrushbot", "mj12bot", "petalbot", "headlesschrome",
    "lighthouse", "pingdom", "uptimerobot", "monitoring", "feedfetcher",
    "google-pagespeed", "chrome-lighthouse", "axios", "python-requests", "curl/",
    "wget/", "go-http-client", "okhttp", "node-fetch",
)

# Path extensions / prefixes that always indicate a sub-resource the page
# being viewed is loading (favicons, images, JS, fonts, etc.). These get
# dropped before the row is inserted so /meetings doesn't get credit for
# every <img> it ships.
_ASSET_EXTS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".ico",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp4", ".webm", ".mp3", ".ogg", ".m4a", ".pdf", ".zip",
    ".json", ".xml", ".txt", ".map",
)
_ASSET_PREFIXES = ("/static/", "/pub/", "/site-branding/", "/favicon")

# Reusable SQL clause: exclude background data/poll rows under /api/ (e.g.
# the utility bar's /api/live-meeting poller) from EVERY metric. New hits
# are dropped at record time (see _should_skip), but rows logged before
# that skip existed are still in the table — applying this clause to every
# aggregation keeps them from skewing totals, daily series, uniques, and
# the device/browser/OS/referrer/path/hour breakdowns. (`notlike` treats a
# NULL path as non-matching, but record_visit always stores at least "/".)
_NO_API = VisitorEvent.path.notlike("/api/%")


def _parse_ua(ua):
    """Return (device, browser, os) for a UA string. Each field falls
    back to a generic label when nothing matched, so the metrics page
    always has something to bucket on."""
    if not ua:
        return "other", "Other", "Other"
    lower = ua.lower()
    if any(tok in lower for tok in _BOT_TOKENS):
        return "bot", "Bot", "Bot"
    # Device class — order matters: tablets are mobile-ish so we check
    # the tablet markers first, then phone markers, then fall through to
    # desktop. iPad in modern Safari masquerades as a Mac, so we use the
    # touch-event flag as the tiebreaker.
    if "ipad" in lower or "tablet" in lower or ("android" in lower and "mobile" not in lower):
        device = "tablet"
    elif "iphone" in lower or "ipod" in lower or "mobile" in lower or "android" in lower:
        device = "mobile"
    else:
        device = "desktop"
    browser = "Other"
    for name, pat in _BROWSER_PATTERNS:
        if pat.search(lower):
            browser = name
            break
    os_name = "Other"
    for name, pat in _OS_PATTERNS:
        if pat.search(lower):
            os_name = name
            break
    return device, browser, os_name


def _client_ip():
    """Return the visitor's IP. ProxyFix in create_app() already rewrites
    request.remote_addr from X-Forwarded-For when configured trusted hops
    match, so we read it directly. The hash function uses this; we never
    persist the raw value."""
    return request.remote_addr or ""


def _daily_salt():
    """Per-UTC-day salt seeded off TSP_SECRET_KEY. Rotates at midnight UTC
    so the same (IP, UA) pair hashes to a stable value within a day and a
    different value the next day."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    secret = current_app.config.get("SECRET_KEY", "")
    return f"{secret}|{today}".encode("utf-8")


def _visitor_hash(ip, ua):
    """Daily-rotating one-way hash of (IP, UA). Used to estimate unique
    visitors without persisting either input."""
    h = hashlib.blake2b(digest_size=16)
    h.update(_daily_salt())
    h.update(b"|")
    h.update((ip or "").encode("utf-8"))
    h.update(b"|")
    h.update((ua or "").encode("utf-8"))
    return h.hexdigest()


def _referrer_host(referrer):
    """Pull the (scheme://host) origin out of a Referer header value,
    returning None when the referrer is empty or points back at our own
    host (self-traffic shouldn't appear as a referral source).
    """
    if not referrer:
        return None
    try:
        parsed = urlparse(referrer)
    except ValueError:
        return None
    if not parsed.netloc:
        return None
    own_host = (request.host or "").split(":", 1)[0].lower()
    ref_host = parsed.netloc.split(":", 1)[0].lower()
    if ref_host == own_host:
        return None
    return ref_host[:255]


def _should_skip(path, method, ua):
    """Filter that drops a request before it ever becomes a VisitorEvent.

    Returns True for asset fetches, non-GET requests, prefetches, and
    obvious bot UAs. The recording hook calls this before any other
    work, so dropped requests cost ~one regex pass + a startswith().
    """
    if method != "GET":
        return True
    lower_path = path.lower()
    if lower_path.startswith(_ASSET_PREFIXES):
        return True
    if lower_path.endswith(_ASSET_EXTS):
        return True
    # Background data/poll endpoints (e.g. the utility bar's
    # /api/live-meeting poller, which every public visitor fires every
    # 30s) are machine requests, not page views — never count them, or
    # they'd dominate the top-paths list. Mirrors the same /api skip the
    # online-users tracker applies.
    if lower_path.startswith("/api/"):
        return True
    # Browser prefetch / prerender hints — Chrome/Edge ship these with a
    # `Sec-Purpose: prefetch` header. We don't want to count link
    # previews as visits.
    sec_purpose = (request.headers.get("Sec-Purpose") or "").lower()
    if "prefetch" in sec_purpose or "prerender" in sec_purpose:
        return True
    purpose = (request.headers.get("Purpose") or "").lower()
    if purpose == "prefetch":
        return True
    if not ua:
        return True
    lower_ua = ua.lower()
    if any(tok in lower_ua for tok in _BOT_TOKENS):
        return True
    return False


def record_visit():
    """Flask before_request hook. Inserts a VisitorEvent row when the
    request represents a real human page view on the public frontend.

    Defensive at every step: any exception is swallowed (visitor
    tracking must never break the page render). DB writes are committed
    in their own transaction so the recording hook can't pollute a
    request's own session work.
    """
    try:
        if getattr(current_user, "is_authenticated", False):
            return
        # Respect the frontend gate. When the public site is disabled
        # (`frontend_module_enabled` off, or `frontend_enabled` off for
        # everyone but admin/editor previews), the route handlers
        # redirect every request to /tspro/auth/login. But this hook
        # runs as a blueprint `before_request`, which fires BEFORE the
        # route handler — so without this check we'd record one
        # VisitorEvent per scanner/crawler hit even though the visitor
        # never actually saw a page. Mirrors the precondition in
        # `app/frontend.py::_frontend_gate`.
        from .models import SiteSetting
        site = SiteSetting.query.first()
        if not site or not site.frontend_module_enabled or not site.frontend_enabled:
            return
        path = request.path or "/"
        ua = request.headers.get("User-Agent") or ""
        if _should_skip(path, request.method, ua):
            return
        endpoint = request.endpoint or ""
        # Belt-and-suspenders: the hook is mounted on the frontend
        # blueprint only, but guard anyway so a future cross-blueprint
        # wire-up can't accidentally start recording admin traffic.
        if endpoint and not endpoint.startswith("frontend."):
            return
        device, browser, os_name = _parse_ua(ua)
        if device == "bot":
            return
        now = datetime.utcnow()
        ev = VisitorEvent(
            created_at=now,
            day=now.strftime("%Y-%m-%d"),
            path=path[:500],
            endpoint=(endpoint or None) and endpoint[:128],
            referrer_host=_referrer_host(request.headers.get("Referer")),
            device=device,
            browser=browser,
            os=os_name,
            visitor_hash=_visitor_hash(_client_ip(), ua),
        )
        db.session.add(ev)
        db.session.commit()
    except Exception:  # noqa: BLE001
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass


def record_404(path=None):
    """Log one ``NotFoundEvent`` for a public-site 404.

    Called from the global 404 errorhandler once it has decided the
    request is a public-frontend 404 (not an admin ``/tspro`` path, and
    the public frontend is enabled). We still apply the same
    asset/bot/non-GET filter as ``record_visit`` so the table tracks real
    visitor navigations, and we keep the *full* referrer (the page that
    linked to the dead URL) which is the whole point of the tab.

    Fully defensive: any failure is swallowed so a logging hiccup can
    never turn a visitor's 404 page into a 500.
    """
    try:
        # Visitor 404s only — a signed-in admin/editor clicking a dead
        # link (including from the Watchtower 404s tab itself) shouldn't
        # pollute the log. Mirrors record_visit's authenticated skip.
        if getattr(current_user, "is_authenticated", False):
            return
        path = path or request.path or "/"
        ua = request.headers.get("User-Agent") or ""
        if _should_skip(path, request.method, ua):
            return
        device, browser, os_name = _parse_ua(ua)
        if device == "bot":
            return
        referrer = request.headers.get("Referer") or None
        now = datetime.utcnow()
        ev = NotFoundEvent(
            created_at=now,
            day=now.strftime("%Y-%m-%d"),
            path=path[:500],
            referrer=referrer[:500] if referrer else None,
            referrer_host=_referrer_host(referrer),
            device=device,
            browser=browser,
            os=os_name,
            visitor_hash=_visitor_hash(_client_ip(), ua),
            # 404 events DO persist the IP (unlike regular visit events)
            # so Watchtower can show "who's hitting this dead URL" and
            # offer a one-click block. Same abuse-investigation use case
            # as LoginFailure.ip / ActivityLog.ip.
            ip=_client_ip()[:45] or None,
        )
        db.session.add(ev)
        db.session.commit()
    except Exception:  # noqa: BLE001
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Aggregation helpers used by the admin metrics page + dashboard widget.
# ---------------------------------------------------------------------------

def _date_range(days):
    """Inclusive list of UTC date strings (YYYY-MM-DD) covering the last
    ``days`` days, oldest first. Used to backfill zero-buckets so the
    time-series chart has continuous coverage even on slow days."""
    today = datetime.utcnow().date()
    return [(today - timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(days - 1, -1, -1)]


def summary(days=30):
    """Top-line numbers for the metrics page header + dashboard widget.

    Returns a dict with:
      - views_today / views_yesterday / views_7d / views_30d
      - uniques_today / uniques_7d / uniques_30d (distinct visitor_hashes)
      - total_views (lifetime row count)
      - first_seen_at (timestamp of oldest row, None if empty)
    """
    today = datetime.utcnow().date()
    today_s = today.strftime("%Y-%m-%d")
    yesterday_s = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    cutoff_7d = (today - timedelta(days=6)).strftime("%Y-%m-%d")
    cutoff_30d = (today - timedelta(days=29)).strftime("%Y-%m-%d")
    cutoff_window = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    def _views_in(day_from, day_to=None):
        q = db.session.query(func.count(VisitorEvent.id)).filter(_NO_API)
        if day_to is None:
            q = q.filter(VisitorEvent.day == day_from)
        else:
            q = q.filter(VisitorEvent.day >= day_from,
                         VisitorEvent.day <= day_to)
        return int(q.scalar() or 0)

    def _uniques_in(day_from, day_to=None):
        q = (db.session.query(func.count(func.distinct(VisitorEvent.visitor_hash)))
             .filter(_NO_API))
        if day_to is None:
            q = q.filter(VisitorEvent.day == day_from)
        else:
            q = q.filter(VisitorEvent.day >= day_from,
                         VisitorEvent.day <= day_to)
        q = q.filter(VisitorEvent.visitor_hash.isnot(None))
        return int(q.scalar() or 0)

    total_views = int(db.session.query(func.count(VisitorEvent.id))
                      .filter(_NO_API).scalar() or 0)
    first_row = (db.session.query(VisitorEvent.created_at)
                 .filter(_NO_API)
                 .order_by(VisitorEvent.created_at.asc()).first())
    first_seen_at = first_row[0] if first_row else None

    return {
        "views_today":     _views_in(today_s),
        "views_yesterday": _views_in(yesterday_s),
        "views_7d":        _views_in(cutoff_7d, today_s),
        "views_30d":       _views_in(cutoff_30d, today_s),
        "views_window":    _views_in(cutoff_window, today_s),
        "uniques_today":   _uniques_in(today_s),
        "uniques_7d":      _uniques_in(cutoff_7d, today_s),
        "uniques_30d":     _uniques_in(cutoff_30d, today_s),
        "uniques_window":  _uniques_in(cutoff_window, today_s),
        "total_views":     total_views,
        "first_seen_at":   first_seen_at,
    }


def daily_series(days=30):
    """Per-day visit + unique-visitor counts for the time-series chart.

    Returns a list of dicts ``[{day, views, uniques}, ...]`` covering the
    last ``days`` days, oldest first. Days with no traffic are emitted
    with zero counts so the chart line stays continuous.
    """
    today = datetime.utcnow().date()
    cutoff = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    views_by_day = dict(
        db.session.query(VisitorEvent.day, func.count(VisitorEvent.id))
        .filter(VisitorEvent.day >= cutoff)
        .filter(_NO_API)
        .group_by(VisitorEvent.day).all()
    )
    uniques_by_day = dict(
        db.session.query(VisitorEvent.day,
                         func.count(func.distinct(VisitorEvent.visitor_hash)))
        .filter(VisitorEvent.day >= cutoff)
        .filter(_NO_API)
        .filter(VisitorEvent.visitor_hash.isnot(None))
        .group_by(VisitorEvent.day).all()
    )
    out = []
    for d in _date_range(days):
        out.append({
            "day":     d,
            "views":   int(views_by_day.get(d, 0)),
            "uniques": int(uniques_by_day.get(d, 0)),
        })
    return out


def _count_expr(metric):
    """SQLAlchemy expression for the chosen metric.

    - "views": every recorded hit counts (`COUNT(*)`)
    - "uniques": distinct daily-rotating visitor_hashes (approximate
      unique-visitor count; rows with NULL hash are excluded by the
      caller so the count isn't inflated by un-hashable requests)
    """
    if metric == "uniques":
        return func.count(func.distinct(VisitorEvent.visitor_hash))
    return func.count(VisitorEvent.id)


def hourly_distribution(days=14, metric="views"):
    """Hits or unique visitors per hour-of-day across the window.
    Returns a list of 24 dicts ``[{hour, count}, ...]`` covering 0..23.
    The metrics page uses this for the 24-bar "when do people visit"
    chart. Pass ``metric="uniques"`` to count distinct visitors per
    hour instead of every hit.

    SQLite stores `created_at` as text; we slice the hour with `strftime`
    so the rollup runs server-side without pulling rows into Python.
    """
    today = datetime.utcnow().date()
    cutoff = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    q = (db.session.query(
            func.strftime("%H", VisitorEvent.created_at).label("hour"),
            _count_expr(metric))
         .filter(VisitorEvent.day >= cutoff)
         .filter(_NO_API))
    if metric == "uniques":
        q = q.filter(VisitorEvent.visitor_hash.isnot(None))
    rows = q.group_by("hour").all()
    by_hour = {int(h): int(c) for h, c in rows if h is not None}
    return [{"hour": h, "count": by_hour.get(h, 0)} for h in range(24)]


def _top_n(column, days, limit, metric="views", label_for_none="(unknown)"):
    """Generic top-N grouped count over the last ``days`` days. The
    caller passes the column to group on; we return a list of dicts
    ``[{label, count}, ...]`` ordered by count desc. NULLs surface as
    ``label_for_none`` so the chart legend never has blank bars.

    ``metric="uniques"`` counts distinct visitors per bucket instead of
    raw hits (and drops rows with no visitor_hash so the metric isn't
    inflated)."""
    today = datetime.utcnow().date()
    cutoff = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    cnt = _count_expr(metric)
    q = (db.session.query(column, cnt)
         .filter(VisitorEvent.day >= cutoff)
         .filter(_NO_API))
    if metric == "uniques":
        q = q.filter(VisitorEvent.visitor_hash.isnot(None))
    rows = (q.group_by(column).order_by(cnt.desc()).limit(limit).all())
    return [{"label": (v or label_for_none), "count": int(c)} for v, c in rows]


def top_paths(days=30, limit=10, metric="views"):
    """Most-visited paths in the window.

    metric="views"   — every page load counts.
    metric="uniques" — counts distinct visitors per path (more useful
                       when comparing reach across pages because it
                       isn't skewed by a single visitor reloading).

    Background data endpoints under ``/api/`` (e.g. the utility bar's
    ``/api/live-meeting`` poller) are excluded from the list — they're
    machine polls, not page views. New hits are already dropped at record
    time (see ``_should_skip``); this filter also hides any historical
    ``/api/*`` rows logged before that skip existed."""
    today = datetime.utcnow().date()
    cutoff = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    cnt = _count_expr(metric)
    q = (db.session.query(VisitorEvent.path, cnt)
         .filter(VisitorEvent.day >= cutoff)
         .filter(_NO_API))
    if metric == "uniques":
        q = q.filter(VisitorEvent.visitor_hash.isnot(None))
    rows = (q.group_by(VisitorEvent.path).order_by(cnt.desc()).limit(limit).all())
    return [{"label": (v or "/"), "count": int(c)} for v, c in rows]


def top_referrers(days=30, limit=10, metric="views"):
    """Top referring hosts in the window (None hash → 'Direct').
    See ``top_paths`` for the metric semantics."""
    today = datetime.utcnow().date()
    cutoff = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    cnt = _count_expr(metric)
    q = (db.session.query(VisitorEvent.referrer_host, cnt)
         .filter(VisitorEvent.day >= cutoff)
         .filter(_NO_API))
    if metric == "uniques":
        q = q.filter(VisitorEvent.visitor_hash.isnot(None))
    rows = (q.group_by(VisitorEvent.referrer_host)
             .order_by(cnt.desc()).limit(limit).all())
    return [{"label": v or "Direct", "count": int(c)} for v, c in rows]


def device_breakdown(days=30, metric="views"):
    """Counts per device class for the donut chart."""
    return _top_n(VisitorEvent.device, days, 8, metric=metric, label_for_none="other")


def browser_breakdown(days=30, metric="views"):
    """Counts per browser family for the donut chart."""
    return _top_n(VisitorEvent.browser, days, 8, metric=metric)


def os_breakdown(days=30, metric="views"):
    """Counts per OS family for the donut chart."""
    return _top_n(VisitorEvent.os, days, 8, metric=metric)


def sparkline_views(days=14, metric="uniques"):
    """Compact daily series for the dashboard widget. Returns a plain
    list of ints (oldest first) — the widget's SVG sparkline only
    needs the magnitudes, not the day labels. Defaults to unique
    visitors (the more meaningful number for "how many real people");
    pass ``metric="views"`` for the legacy hit-count shape."""
    key = "uniques" if metric == "uniques" else "views"
    return [d[key] for d in daily_series(days=days)]
