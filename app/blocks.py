# SPDX-License-Identifier: AGPL-3.0-or-later
"""Helpers for the homepage block-content store.

A single JSON column on SiteSetting (`frontend_blocks_json`) holds the
admin-edited copy for every block type. Each block partial reads from
``site_blocks(site)[block_type]`` with a sensible default fallback.

The pipe-delimited textarea format used in the admin (``token | token``)
keeps the editor compact while still letting authors compose 3+ items
per block without juggling raw JSON.
"""
import json


# Default content used when a block hasn't been customized yet.
DEFAULTS = {
    "features": [
        {"icon": "calendar",  "title": "Live schedule",
         "body": "Every meeting, every day. In-person, online, and hybrid options across the entire region — kept up to date by trusted servants."},
        {"icon": "users",     "title": "Welcoming fellowship",
         "body": "The only requirement is a desire to stop using. No dues, no fees — we're entirely self-supported by our own contributions."},
        {"icon": "phone",     "title": "24/7 helpline",
         "body": "Confidential, free support whenever you need it. Speak to someone who's been there and made it through."},
    ],
    "cta": {
        "heading": "You don't have to do this alone.",
        "body":    "Find a meeting today, or call our helpline 24/7. Whatever step is next, we're here for it.",
        "primary_label":   "Find a Meeting",
        "primary_url":     "#meetings",
        "secondary_label": "Need Help Now?",
        "secondary_url":   "#contact",
    },
    "stats": [
        {"num": "7",    "label": "Days a week"},
        {"num": "24/7", "label": "Helpline coverage"},
        {"num": "3",    "label": "Meeting formats"},
        {"num": "$0",   "label": "Dues & fees"},
    ],
    "testimonials": [
        {"quote": "My first meeting felt like coming home. I haven't missed one since.",
         "attribution": "Member, four years sober"},
        {"quote": "The hotline picked up at 2 a.m. on the worst night of my life. Someone was there. It saved me.",
         "attribution": "Newcomer, six months in"},
        {"quote": "Service work changed my recovery. There's always somewhere to plug in.",
         "attribution": "Trusted servant, GSR"},
    ],
    "faq": [
        {"question": "Do I have to share?",
         "answer":   "Never. Many newcomers attend their first several meetings without saying a word. The only requirement is a desire to stop using."},
        {"question": "Is there a cost?",
         "answer":   "No dues, no fees. The fellowship is entirely self-supported through voluntary contributions from members — typically a dollar or two passed in a basket."},
        {"question": "Will anyone know I was there?",
         "answer":   "Anonymity is the spiritual foundation of the program. What's said in the room stays in the room."},
        {"question": "What if I can't get to an in-person meeting?",
         "answer":   "We host online and hybrid meetings on Zoom every day. Check the meetings list for current times and links."},
    ],
    "quick_links": [
        {"icon": "◈", "title": "Meetings",          "body": "Find an in-person, online, or hybrid meeting that fits your schedule.", "href": "#meetings"},
        {"icon": "◉", "title": "About Us",          "body": "Learn who we are, what we stand for, and how we serve the fellowship.", "href": "#about"},
        {"icon": "◎", "title": "Get Help",          "body": "Connect with someone today. We're here to answer the call, 24/7.",     "href": "#contact"},
        {"icon": "◊", "title": "Trusted Servants",  "body": "Portal sign-in for meeting hosts, intergroup members, and volunteers.", "href": "/login"},
    ],
}


def site_blocks(site):
    """Return a dict of {block_type: content} for a SiteSetting row.
    Uses DEFAULTS for any block the admin hasn't customized.
    Also surfaces a `_visibility` map (block_type → bool, default True)
    and a `_meetings` settings dict; both are stored alongside the
    content keys in the same JSON column."""
    raw = (site.frontend_blocks_json if site else None) or ""
    try:
        stored = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        stored = {}
    out = {}
    for k, default in DEFAULTS.items():
        v = stored.get(k)
        out[k] = v if v else default
    out["_visibility"] = stored.get("_visibility") or {}
    out["_meetings"] = {**MEETINGS_DEFAULTS, **(stored.get("_meetings") or {})}
    out["_events"] = {**EVENTS_DEFAULTS, **(stored.get("_events") or {})}
    return out


def is_block_visible(block_content, block_type):
    """A block is visible unless explicitly disabled in `_visibility`."""
    if not block_content:
        return True
    return bool(block_content.get("_visibility", {}).get(block_type, True))


# Day-of-week labels used in the grouped-by-day meeting view.
_DOW_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def filtered_meetings(meetings_settings):
    """Resolve the meetings list for the public hero meetings block.

    Returns a list of dicts:
      [{"label": "<day or empty>", "items":
          [{"meeting": <Meeting>, "schedule": <MeetingSchedule>,
            "day_label": "<dow>", "is_today": bool}, ...]}, ...]

    The structure carries optional day-grouping baked in, so the template
    just iterates groups → items without further branching."""
    from datetime import datetime, timedelta
    from .models import db, Meeting, MeetingSchedule

    s = {**MEETINGS_DEFAULTS, **(meetings_settings or {})}
    mode = s.get("filter") or "upcoming_today"
    cap = max(1, int(s.get("max_count") or 6))

    now = datetime.now()
    today_dow = now.weekday()        # 0 = Monday
    now_hhmm = now.strftime("%H:%M")

    # Active (not archived) meetings → all their schedules.
    rows = (db.session.query(MeetingSchedule, Meeting)
            .join(Meeting, Meeting.id == MeetingSchedule.meeting_id)
            .filter(Meeting.archived_at.is_(None))
            .order_by(MeetingSchedule.day_of_week, MeetingSchedule.start_time, Meeting.name)
            .all())

    # Compute candidate (dow_offset, schedule, meeting) where dow_offset is
    # how many days from today the schedule next occurs (0..6).
    expanded = []
    for sch, m in rows:
        offset = (sch.day_of_week - today_dow) % 7
        # Same-day "upcoming" filter: drop schedules that already started.
        if offset == 0 and mode in ("upcoming_today", "next_24h"):
            if (sch.start_time or "") < now_hhmm:
                continue
        expanded.append((offset, sch, m))

    # Apply mode-specific filtering.
    if mode in ("today_all", "upcoming_today"):
        expanded = [t for t in expanded if t[0] == 0]
    elif mode == "next_24h":
        # today + tomorrow's morning (offset 1 only really matters as
        # "happens within 24h"; we approximate by including all of
        # tomorrow's schedules earlier than now's HH:MM).
        expanded = [t for t in expanded
                    if t[0] == 0 or (t[0] == 1 and (t[1].start_time or "") < now_hhmm)]
    elif mode == "next_7_days":
        pass  # all 7 offsets are kept
    elif mode == "this_week":
        # Mon..Sun of the current calendar week. offset 0..(6 - today_dow).
        days_left = 6 - today_dow
        expanded = [t for t in expanded if t[0] <= days_left]
    elif mode == "all":
        # No date filter — show every active meeting once, picking its
        # next upcoming schedule.
        seen = set()
        deduped = []
        for offset, sch, m in expanded:
            if m.id in seen:
                continue
            seen.add(m.id); deduped.append((offset, sch, m))
        expanded = deduped

    # Sort chronologically within the filtered window.
    expanded.sort(key=lambda t: (t[0], t[1].start_time or "", t[2].name or ""))
    expanded = expanded[:cap]

    # Build groups (one group per offset when group_by_day is on; one
    # combined group otherwise).
    items = []
    for offset, sch, m in expanded:
        items.append({
            "meeting": m,
            "schedule": sch,
            "day_label": _DOW_NAMES[(today_dow + offset) % 7],
            "is_today": offset == 0,
        })

    if s.get("group_by_day"):
        groups = {}
        order = []
        for it in items:
            label = "Today" if it["is_today"] else it["day_label"]
            if label not in groups:
                groups[label] = []; order.append(label)
            groups[label].append(it)
        return [{"label": k, "items": groups[k]} for k in order]
    return [{"label": "", "items": items}]


# Defaults for the configurable meetings list block.
MEETINGS_DEFAULTS = {
    "filter":          "upcoming_today",   # today_all | upcoming_today | next_24h | next_7_days | this_week | all
    "max_count":       6,
    "group_by_day":    False,
    "show_type_chip":  True,
    "show_schedule":   True,
    "show_first_n":    3,                  # how many schedule lines to render per card
    "empty_message":   "No meetings scheduled — check back soon.",
    "animation":       "fade",             # fade | slide | none
    "stagger_ms":      60,
    "heading":         "Upcoming Meetings",
    "intro":           "A quick look at what's on the schedule. Sign in to the portal for full details, host accounts, and one-tap Zoom links.",
}


# Defaults for the configurable upcoming-events block.
EVENTS_DEFAULTS = {
    "max_count":       6,
    "heading":         "Upcoming Events",
    "intro":           "",
    "empty_message":   "No upcoming events — check back soon.",
    "animation":       "fade",     # fade | slide | none
    "stagger_ms":      60,
    "show_image":      True,
    "show_summary":    True,
    "show_location":   True,
}


def filtered_events(events_settings, site=None):
    """Resolve the upcoming-events list for the public events block.

    Returns a list of Post rows (each ``is_event=True``) ordered by
    ``event_starts_at`` ascending. Past events drop off automatically
    (the auto-archive sweep marks them archived; this filter also
    excludes any whose end-time is already past, in case the sweep
    hasn't run yet).

    When the Posts module is disabled site-wide, returns an empty
    list — the public events block effectively disappears.
    """
    from datetime import datetime
    from .models import Post, SiteSetting

    if site is None:
        site = SiteSetting.query.first()
    if not site or not getattr(site, "posts_enabled", True):
        return []

    s = {**EVENTS_DEFAULTS, **(events_settings or {})}
    cap = max(1, int(s.get("max_count") or 6))
    now = datetime.utcnow()

    rows = (Post.query
            .filter(Post.is_event.is_(True),
                    Post.is_archived.is_(False),
                    Post.is_draft.is_(False))
            .order_by(Post.event_starts_at.asc().nulls_last())
            .all())
    out = []
    for p in rows:
        # Drop events that have fully ended (or whose date is unset).
        ref_end = p.event_ends_at or p.event_starts_at
        if ref_end is None or ref_end < now:
            continue
        out.append(p)
        if len(out) >= cap:
            break
    return out


# ── Pipe-delimited text-area parsers / formatters ──────────────────────
# The admin form serializes each block's content as a small block of text
# with one item per line and ``|`` separating fields. These helpers do the
# round-trip so the editor is friendly for non-technical users.

def _parse_lines_pipe(text, fields):
    """Parse "a | b | c" lines into a list of dicts keyed by `fields`.
    Empty/short lines are skipped. Trims whitespace on every cell."""
    items = []
    for raw in (text or "").splitlines():
        cells = [p.strip() for p in raw.split("|")]
        # Skip lines that don't have at least the first field populated.
        if not cells or not cells[0]:
            continue
        item = {}
        for i, f in enumerate(fields):
            item[f] = cells[i] if i < len(cells) else ""
        items.append(item)
    return items


def _format_lines_pipe(items, fields):
    return "\n".join(" | ".join((it.get(f) or "") for f in fields) for it in (items or []))


# Per-block (de)serializers. Keys here drive what the admin form posts.
def parse_features(text):     return _parse_lines_pipe(text, ["icon", "title", "body"])
def format_features(items):   return _format_lines_pipe(items, ["icon", "title", "body"])
def parse_stats(text):        return _parse_lines_pipe(text, ["num", "label"])
def format_stats(items):      return _format_lines_pipe(items, ["num", "label"])
def parse_testimonials(text): return _parse_lines_pipe(text, ["quote", "attribution"])
def format_testimonials(items): return _format_lines_pipe(items, ["quote", "attribution"])
def parse_faq(text):          return _parse_lines_pipe(text, ["question", "answer"])
def format_faq(items):        return _format_lines_pipe(items, ["question", "answer"])
def parse_quick_links(text):  return _parse_lines_pipe(text, ["icon", "title", "body", "href"])
def format_quick_links(items): return _format_lines_pipe(items, ["icon", "title", "body", "href"])


def parse_cta(form):
    """CTA is a flat object — read the six discrete fields directly from
    the request form rather than a single textarea."""
    return {
        "heading":         (form.get("block_cta_heading") or "").strip(),
        "body":            (form.get("block_cta_body") or "").strip(),
        "primary_label":   (form.get("block_cta_primary_label") or "").strip(),
        "primary_url":     (form.get("block_cta_primary_url") or "").strip(),
        "secondary_label": (form.get("block_cta_secondary_label") or "").strip(),
        "secondary_url":   (form.get("block_cta_secondary_url") or "").strip(),
    }
