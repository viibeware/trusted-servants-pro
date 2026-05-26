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
import re as _re


# Default content used when a block hasn't been customized yet.
DEFAULTS = {
    "features": {
        "heading":    "What we offer",
        "subheading": "Everything a fellowship needs to stay connected and welcoming.",
        "items": [
            {"icon": "calendar", "icon_color": "", "icon_size": "",
             "title": "Live schedule",
             "body":  "Every meeting, every day. In-person, online, and hybrid options across the entire region — kept up to date by trusted servants.",
             "href":  "", "open_in_new_tab": False},
            {"icon": "users", "icon_color": "", "icon_size": "",
             "title": "Welcoming fellowship",
             "body":  "The only requirement is a desire to stop using. No dues, no fees — we're entirely self-supported by our own contributions.",
             "href":  "", "open_in_new_tab": False},
            {"icon": "phone", "icon_color": "", "icon_size": "",
             "title": "24/7 helpline",
             "body":  "Confidential, free support whenever you need it. Speak to someone who's been there and made it through.",
             "href":  "", "open_in_new_tab": False},
        ],
    },
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
         "answer":   "Never. Many newcomers attend their first several meetings without saying a word. The only requirement is a desire to stop using.",
         "icon": "message-circle-question", "icon_size": ""},
        {"question": "Is there a cost?",
         "answer":   "No dues, no fees. The fellowship is entirely self-supported through voluntary contributions from members — typically a dollar or two passed in a basket.",
         "icon": "wallet", "icon_size": ""},
        {"question": "Will anyone know I was there?",
         "answer":   "Anonymity is the spiritual foundation of the program. What's said in the room stays in the room.",
         "icon": "shield", "icon_size": ""},
        {"question": "What if I can't get to an in-person meeting?",
         "answer":   "We host online and hybrid meetings on Zoom every day. Check the meetings list for current times and links.",
         "icon": "video", "icon_size": ""},
    ],
    "inclusion": {
        "heading":    "All Are Welcome",
        "body":       "The only requirement for membership is a desire to stop using. Whoever you are — wherever you come from — there's a seat for you in this fellowship. <strong>You belong here.</strong>",
        "tags":       ["LGBTQIA+", "All races", "All faiths", "All ages", "All abilities", "All genders", "All backgrounds"],
        "icon":       "heart-handshake",
        "icon_color": "",
        "icon_size":  "",
        "link_label": "",
        "link_url":   "",
        "alignment":  "center",
    },
    "quick_links": [
        {"icon": "◈", "title": "Meetings",          "body": "Find an in-person, online, or hybrid meeting that fits your schedule.", "href": "#meetings"},
        {"icon": "◉", "title": "About Us",          "body": "Learn who we are, what we stand for, and how we serve the fellowship.", "href": "#about"},
        {"icon": "◎", "title": "Get Help",          "body": "Connect with someone today. We're here to answer the call, 24/7.",     "href": "#contact"},
        {"icon": "◊", "title": "Trusted Servants",  "body": "Portal sign-in for meeting hosts, intergroup members, and volunteers.", "href": "/login"},
    ],
}


def site_blocks(site):
    """Return a dict of {block_type: content} for a SiteSetting row.
    Uses DEFAULTS for any block the admin hasn't customized. Also
    surfaces `_meetings` and `_events` settings dicts stored alongside
    the content keys in the same JSON column. Whether a block renders
    on the public page is now driven entirely by the active layout's
    block sequence — there's no separate visibility map. Removing a
    block from the layout is the way to hide it; adding it back brings
    it back with its previously-saved content intact."""
    raw = (site.frontend_blocks_json if site else None) or ""
    try:
        stored = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        stored = {}
    out = {}
    for k, default in DEFAULTS.items():
        v = stored.get(k)
        if k == "features":
            out[k] = _normalize_features(v, default)
        elif k == "faq":
            out[k] = _normalize_faq(v, default)
        else:
            out[k] = v if v else default
    out["_meetings"] = {**MEETINGS_DEFAULTS, **(stored.get("_meetings") or {})}
    out["_events"] = {**EVENTS_DEFAULTS, **(stored.get("_events") or {})}
    return out


_FEATURE_ITEM_FIELDS = ("icon", "icon_color", "icon_size", "title", "body",
                        "href", "open_in_new_tab",
                        "button_label", "button_style")
_FEATURE_BUTTON_STYLES = ("primary", "ghost")


def _normalize_features(v, default):
    """Coerce stored features content into the canonical dict shape.
    The legacy shape was a bare list of card dicts; the new shape is
    ``{heading, subheading, cta_*, items: [...]}``. We accept either
    so old saved data keeps rendering after the upgrade."""
    if not v:
        return default
    if isinstance(v, list):
        return {"heading":     default["heading"],
                "subheading":  default["subheading"],
                "cta_label":   "",
                "cta_url":     "",
                "cta_style":   "primary",
                "cta_new_tab": False,
                "items":       [_coerce_feature_item(it) for it in v if isinstance(it, dict)]}
    if isinstance(v, dict):
        items = v.get("items")
        if not isinstance(items, list):
            items = default["items"]
        cta_style = (v.get("cta_style") or "").strip().lower()
        if cta_style not in _FEATURE_BUTTON_STYLES:
            cta_style = "primary"
        return {
            "heading":     v.get("heading",    default["heading"]),
            "subheading":  v.get("subheading", default["subheading"]),
            "cta_label":   v.get("cta_label", "") or "",
            "cta_url":     v.get("cta_url", "") or "",
            "cta_style":   cta_style,
            "cta_new_tab": bool(v.get("cta_new_tab")),
            "items":       [_coerce_feature_item(it) for it in items if isinstance(it, dict)],
        }
    return default


def _coerce_feature_item(it):
    """Ensure every feature item has all expected keys (defaults to empty)."""
    out = {f: "" for f in _FEATURE_ITEM_FIELDS}
    out["open_in_new_tab"] = False
    for f in _FEATURE_ITEM_FIELDS:
        if f in it:
            out[f] = it[f]
    out["open_in_new_tab"] = bool(out.get("open_in_new_tab"))
    bs = (out.get("button_style") or "").strip().lower()
    out["button_style"] = bs if bs in _FEATURE_BUTTON_STYLES else "primary"
    return out


_FAQ_ITEM_FIELDS = ("question", "answer", "icon", "icon_size")


def _normalize_faq(v, default):
    """Coerce stored FAQ content into the canonical list shape.
    Each item is {question, answer, icon, icon_size}. The legacy shape
    {question, answer} is auto-upgraded with empty icon/size on read."""
    if not v:
        return default
    if isinstance(v, list):
        return [_coerce_faq_item(it) for it in v if isinstance(it, dict)]
    return default


def _coerce_faq_item(it):
    out = {f: "" for f in _FAQ_ITEM_FIELDS}
    for f in _FAQ_ITEM_FIELDS:
        if f in it:
            out[f] = it[f]
    return out


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
    from .models import db, Meeting, MeetingSchedule, SiteSetting
    from .timezone import now_in

    s = {**MEETINGS_DEFAULTS, **(meetings_settings or {})}
    mode = s.get("filter") or "upcoming_today"
    cap = max(1, int(s.get("max_count") or 6))

    # Resolve "now" in the configured site timezone so "today" matches the
    # fellowship's wall clock instead of the host's locale.
    now = now_in(SiteSetting.query.first())
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
    from .timezone import now_local_naive
    from .models import Post, SiteSetting

    if site is None:
        site = SiteSetting.query.first()
    if not site or not getattr(site, "posts_enabled", True):
        return []

    s = {**EVENTS_DEFAULTS, **(events_settings or {})}
    cap = max(1, int(s.get("max_count") or 6))
    # Site-local: ``event_ends_at`` is naive site-local (admin-typed),
    # so "is this past?" must compare against the same wall clock or
    # events disappear / linger by the UTC offset.
    now = now_local_naive(site)

    rows = (Post.query
            .filter(Post.is_event.is_(True),
                    Post.is_archived.is_(False),
                    Post.is_draft.is_(False),
                    Post.is_pending_review.is_(False))
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
FEATURES_MAX_CARDS = 6


def parse_features(form):
    """Read the features editor's structured fields out of the request form.
    Returns the canonical dict ``{heading, subheading, items: [...]}``.
    Cards are read in submission order via the ``feature_card_present``
    marker; empty cards (no title and no body) are dropped, and the list
    is capped at ``FEATURES_MAX_CARDS``."""
    heading = (form.get("features_heading") or "").strip()
    subheading = (form.get("features_subheading") or "").strip()
    items = []
    for raw_idx in form.getlist("feature_card_present"):
        try:
            i = int(raw_idx)
        except (TypeError, ValueError):
            continue
        title = (form.get(f"feature_card_{i}_title") or "").strip()
        body  = (form.get(f"feature_card_{i}_body")  or "").strip()
        icon  = (form.get(f"feature_card_{i}_icon")  or "").strip()
        if not (title or body or icon):
            continue
        items.append({
            "icon":            icon,
            "icon_color":      (form.get(f"feature_card_{i}_icon_color") or "").strip(),
            "icon_size":       (form.get(f"feature_card_{i}_icon_size")  or "").strip(),
            "title":           title,
            "body":            body,
            "href":            (form.get(f"feature_card_{i}_href") or "").strip(),
            "open_in_new_tab": form.get(f"feature_card_{i}_new_tab") == "1",
        })
        if len(items) >= FEATURES_MAX_CARDS:
            break
    return {"heading": heading, "subheading": subheading, "items": items}


def parse_stats(text):        return _parse_lines_pipe(text, ["num", "label"])
def format_stats(items):      return _format_lines_pipe(items, ["num", "label"])
def parse_testimonials(text): return _parse_lines_pipe(text, ["quote", "attribution"])
def format_testimonials(items): return _format_lines_pipe(items, ["quote", "attribution"])
FAQ_MAX_ITEMS = 20


def parse_faq(form):
    """Read the FAQ editor's structured fields out of the request form.
    Returns the canonical list of {question, answer, icon, icon_size}.
    Items are read in submission order via the ``faq_item_present`` marker;
    empty items (no question and no answer) are dropped, and the list is
    capped at ``FAQ_MAX_ITEMS``."""
    items = []
    for raw_idx in form.getlist("faq_item_present"):
        try:
            i = int(raw_idx)
        except (TypeError, ValueError):
            continue
        question = (form.get(f"faq_item_{i}_question") or "").strip()
        answer   = (form.get(f"faq_item_{i}_answer")   or "").strip()
        icon     = (form.get(f"faq_item_{i}_icon")     or "").strip()
        if not (question or answer):
            continue
        raw_size = (form.get(f"faq_item_{i}_icon_size") or "").strip()
        try:
            size_int = int(raw_size) if raw_size else 0
        except (TypeError, ValueError):
            size_int = 0
        size = str(size_int) if 12 <= size_int <= 200 else ""
        items.append({
            "question":  question,
            "answer":    answer,
            "icon":      icon,
            "icon_size": size,
        })
        if len(items) >= FAQ_MAX_ITEMS:
            break
    return items
def format_faq(items):        return _format_lines_pipe(items, ["question", "answer"])
def parse_quick_links(text):  return _parse_lines_pipe(text, ["icon", "title", "body", "href"])
def format_quick_links(items): return _format_lines_pipe(items, ["icon", "title", "body", "href"])


def parse_inclusion(form):
    """Read the inclusion-statement editor's structured fields out of the
    request form. Returns a flat dict with heading, body (HTML allowed via
    the safe_html filter on render), an optional list of welcome chips
    (one per textarea line), an icon ref + size from the icon picker, and
    an optional CTA link (label + URL). Alignment is left|center|right."""
    raw_tags = (form.get("inclusion_tags") or "").splitlines()
    tags = [t.strip() for t in raw_tags if t.strip()]
    align = (form.get("inclusion_alignment") or "center").strip().lower()
    if align not in {"left", "center", "right"}:
        align = "center"
    # Accept #abcdef or #abc; reject anything else so we can't smuggle CSS
    # through the inline style attribute. Empty = let the theme accent apply.
    raw_color = (form.get("inclusion_icon_color") or "").strip()
    color = raw_color if _re.match(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", raw_color) else ""
    raw_size = (form.get("inclusion_icon_size") or "").strip()
    try:
        size_int = int(raw_size) if raw_size else 0
    except (TypeError, ValueError):
        size_int = 0
    size = str(size_int) if 12 <= size_int <= 200 else ""
    return {
        "heading":    (form.get("inclusion_heading") or "").strip(),
        "body":       (form.get("inclusion_body") or "").strip(),
        "tags":       tags,
        "icon":       (form.get("inclusion_icon") or "").strip(),
        "icon_color": color,
        "icon_size":  size,
        "link_label": (form.get("inclusion_link_label") or "").strip(),
        "link_url":   (form.get("inclusion_link_url") or "").strip(),
        "alignment":  align,
    }


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


# ─── Footer content layer ─────────────────────────────────────────────────
# Stored in SiteSetting.frontend_footer_blocks_json. Schema:
#
#   {
#     "brand": {"show": true, "show_logo": true, "tagline": "..."},
#     "columns": [
#       {"title": "Get involved",
#        "links": [{"label": "Meetings", "url": "/meetings",
#                   "open_in_new_tab": false}, ...]},
#       ...
#     ],
#     "social": [{"icon": "instagram", "label": "Instagram",
#                 "url": "https://..."}, ...],
#     "secondary_nav": [{"label": "Privacy", "url": "/privacy"}, ...],
#     "copyright": "© {year} {site_name}. All rights reserved."
#   }
#
# Footer templates read this dict via `footer_content(site)` below; missing
# keys fall back to FOOTER_DEFAULTS so a fresh install still renders well.

FOOTER_DEFAULTS = {
    "brand": {
        # Logo source: 'header' uses the public-site header logo
        # (`site.frontend_logo_filename`); 'custom' uses the dedicated
        # `site.frontend_brand_logo_filename` admins upload from the
        # Brand modal on the Footer admin. When neither file is present,
        # the brand block falls back to the text site name.
        "logo_source": "header",
        "logo_width":  180,
        "tagline":     "",
    },
    "columns": [
        {"title": "Fellowship",
         "links": [
             {"label": "Meetings",      "url": "#meetings",      "open_in_new_tab": False},
             {"label": "About us",      "url": "#about",         "open_in_new_tab": False},
             {"label": "Get help",      "url": "#contact",       "open_in_new_tab": False},
         ]},
        {"title": "Resources",
         "links": [
             {"label": "Helpline",      "url": "tel:+18556384373", "open_in_new_tab": False},
             {"label": "Find a meeting", "url": "/meetings",      "open_in_new_tab": False},
             {"label": "Sign in",        "url": "/tspro/auth/login", "open_in_new_tab": False},
         ]},
    ],
    "social": [],
    "secondary_nav": [
        {"label": "Privacy", "url": "#"},
        {"label": "Terms",   "url": "#"},
    ],
    "copyright": "© {year} {site_name}. All rights reserved.",
    # Block-specific content for the meeting_locations footer block —
    # rendered as a card grid (3-4 columns) when placed in a layout.
    "meeting_locations": {
        "heading": "Search Meeting Locations",
        # Predefined-location IDs from the `Location` table — admin
        # checks them off in the footer modal; the public render
        # expands each ID to a card before falling through to `items`
        # (the manually-authored custom entries below).
        "predefined_ids": [],
        "items": [
            {"name": "TRIANGLE CLUB",
             "address": "1638 R St NW\nWashington, DC 20009",
             "note": "with the \"red door\"",
             "url": "https://triangleclub.org/"},
            {"name": "DUPONT CIRCLE CLUB",
             "address": "1623 Connecticut Avenue, NW\nWashington, DC 20009",
             "note": "second floor",
             "url": "http://www.dupontcircleclub.org/"},
            {"name": "EMMANUEL EPISCOPAL CHURCH",
             "address": "811 Cathedral Street\nBaltimore, MD 21201",
             "note": "enter on W. Read Street",
             "url": ""},
            {"name": "IN OTHER CITIES",
             "address": "World-wide CMA meeting search",
             "note": "crystalmeth.org →",
             "url": "https://www.crystalmeth.org/"},
        ],
    },
    # Block-specific content for the contact_section footer block —
    # rendered as a 2-pane row of contact panels.
    "contact_section": {
        "panes": [
            {"heading": "Contact Us",
             "body":    "For general inquiries, [contact us](https://www.crystalmeth.org/contact-help/)."},
            {"heading": "Meetings",
             "body":    "We have in-person, online and hybrid meetings 7 days a week. See our [Meetings page](#meetings) for more information."},
        ],
    },
    # Background generator — mirrors the hero's full menu (solid /
    # gradient / frosty / sinewave / image) plus an optional particle
    # overlay. The render macro reads from this dict and emits the
    # matching `.fe-footer-bg-<style>` markup. Reuses the hero's CSS +
    # JS effects (blob animation, particle canvas, sinewave gradient).
    "bg": {
        "style":            "solid",   # solid | gradient | frosty | sinewave
        "color":            "",        # solid color OR gradient stop 1
        "color_2":          "",        # gradient stop 2
        "gradient_angle":   180,
        "hue":              225,       # frosty primary hue
        "hue_2":            170,       # frosty accent hue
        "blur":             80,        # frosty blob blur (px)
        "opacity":          45,        # frosty blob opacity (0-100)
        "randomize":        False,        # frosty: re-randomise hues on load
        "sinewave_colors":  ["#16c2ba", "#1883d5", "#5a1ce5"],
        "sinewave_wave":    None,          # None = default wave; dict = stored randomised
        "sinewave_randomize_colors": False,  # re-pick palette on every page load
        "sinewave_randomize_wave":   False,  # re-pick wave shape on every page load
        "particle_enabled": False,
        "particle_effect":  "stars",
        "particle_speed":   100,
        "particle_size":    100,
    },
}


_FOOTER_LINK_FIELDS = ("label", "url", "open_in_new_tab")


def _coerce_footer_link(it, with_new_tab=True):
    out = {"label": "", "url": ""}
    if with_new_tab:
        out["open_in_new_tab"] = False
    if not isinstance(it, dict):
        return out
    out["label"] = (it.get("label") or "").strip()
    out["url"]   = (it.get("url")   or "").strip()
    if with_new_tab:
        out["open_in_new_tab"] = bool(it.get("open_in_new_tab"))
    return out


def _coerce_footer_column(c):
    if not isinstance(c, dict):
        c = {}
    return {
        "title": (c.get("title") or "").strip(),
        "links": [_coerce_footer_link(l) for l in (c.get("links") or []) if isinstance(l, dict)],
    }


def _coerce_footer_social(s):
    if not isinstance(s, dict):
        s = {}
    return {
        "icon":  (s.get("icon")  or "").strip(),
        "label": (s.get("label") or "").strip(),
        "url":   (s.get("url")   or "").strip(),
    }


def _coerce_footer_location(it):
    """Canonical custom-location shape. Mirrors the `Location` model's
    fieldset (street/city/state/zip + maps + website + notes) so the
    footer admin's "Custom locations" form has the same controls as
    Settings → Meeting Locations. Backward-compat: legacy `url` field
    is promoted to `website_url` when the latter is empty so existing
    saves survive the rename without losing their card-link data."""
    if not isinstance(it, dict):
        it = {}
    website_url = (it.get("website_url") or "").strip()
    if not website_url:
        website_url = (it.get("url") or "").strip()
    return {
        "name":        (it.get("name") or "").strip(),
        "street":      (it.get("street") or "").strip(),
        "city":        (it.get("city") or "").strip(),
        "state":       (it.get("state") or "").strip(),
        "zip_code":    (it.get("zip_code") or "").strip(),
        # Legacy single-line address — kept for rows that pre-date the
        # split fields. Render-side falls back to it via address_lines.
        "address":     (it.get("address") or "").strip(),
        "note":        (it.get("note") or "").strip(),
        "maps_url":    (it.get("maps_url") or "").strip(),
        "website_url": website_url,
        "icon":        (it.get("icon") or "").strip(),
    }


def _coerce_footer_contact_pane(it):
    if not isinstance(it, dict):
        it = {}
    return {
        "heading": (it.get("heading") or "").strip(),
        "body":    (it.get("body") or "").strip(),
    }


def _normalize_footer(stored):
    """Coerce stored footer JSON into the canonical shape, falling back to
    FOOTER_DEFAULTS for any missing or malformed branch. Returns a fresh
    dict so callers can mutate without touching the defaults."""
    if not isinstance(stored, dict):
        stored = {}
    brand_in = stored.get("brand") if isinstance(stored.get("brand"), dict) else {}
    raw_src = (brand_in.get("logo_source") or "").strip().lower()
    logo_source = raw_src if raw_src in ("header", "custom") else FOOTER_DEFAULTS["brand"]["logo_source"]
    try:
        logo_width = int(brand_in.get("logo_width") or FOOTER_DEFAULTS["brand"]["logo_width"])
    except (TypeError, ValueError):
        logo_width = FOOTER_DEFAULTS["brand"]["logo_width"]
    logo_width = max(40, min(logo_width, 600))
    brand = {
        "logo_source": logo_source,
        "logo_width":  logo_width,
        "tagline":     (brand_in.get("tagline") or "").strip(),
    }
    cols_in = stored.get("columns")
    if isinstance(cols_in, list):
        columns = [_coerce_footer_column(c) for c in cols_in]
    else:
        columns = [dict(c, links=list(c["links"])) for c in FOOTER_DEFAULTS["columns"]]
    social_in = stored.get("social")
    social = [_coerce_footer_social(s) for s in social_in] if isinstance(social_in, list) else []
    nav_in = stored.get("secondary_nav")
    if isinstance(nav_in, list):
        secondary_nav = [_coerce_footer_link(l, with_new_tab=False) for l in nav_in]
    else:
        secondary_nav = list(FOOTER_DEFAULTS["secondary_nav"])
    copyright_str = stored.get("copyright")
    if not isinstance(copyright_str, str) or not copyright_str.strip():
        copyright_str = FOOTER_DEFAULTS["copyright"]
    # Meeting locations block content
    locs_in = stored.get("meeting_locations") if isinstance(stored.get("meeting_locations"), dict) else None
    if locs_in:
        loc_items = locs_in.get("items")
        loc_items = [_coerce_footer_location(i) for i in loc_items] if isinstance(loc_items, list) else []
        # Predefined IDs reference rows in the Location table — coerce
        # to a clean list of positive ints, dropping noise / dupes.
        raw_ids = locs_in.get("predefined_ids")
        predefined_ids = []
        if isinstance(raw_ids, list):
            seen = set()
            for v in raw_ids:
                try:
                    n = int(v)
                except (TypeError, ValueError):
                    continue
                if n > 0 and n not in seen:
                    seen.add(n); predefined_ids.append(n)
        meeting_locations = {
            "heading": (locs_in.get("heading") or "").strip() or FOOTER_DEFAULTS["meeting_locations"]["heading"],
            "predefined_ids": predefined_ids,
            "items":   loc_items,
        }
    else:
        d = FOOTER_DEFAULTS["meeting_locations"]
        meeting_locations = {"heading": d["heading"],
                             "predefined_ids": list(d.get("predefined_ids") or []),
                             "items": [dict(i) for i in d["items"]]}
    # Contact section block content
    cs_in = stored.get("contact_section") if isinstance(stored.get("contact_section"), dict) else None
    if cs_in:
        panes = cs_in.get("panes")
        panes = [_coerce_footer_contact_pane(p) for p in panes] if isinstance(panes, list) else []
        contact_section = {"panes": panes}
    else:
        contact_section = {"panes": [dict(p) for p in FOOTER_DEFAULTS["contact_section"]["panes"]]}
    return {
        "brand": brand,
        "columns": columns,
        "social": social,
        "secondary_nav": secondary_nav,
        "copyright": copyright_str,
        "meeting_locations": meeting_locations,
        "contact_section": contact_section,
        "bg": _normalize_footer_bg(stored.get("bg")),
    }


_FOOTER_BG_STYLES = {"solid", "gradient", "frosty", "sinewave"}
_FOOTER_BG_HEX_RE = _re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _coerce_hex(v, fallback=""):
    v = (v or "").strip()
    return v if _FOOTER_BG_HEX_RE.match(v) else fallback


def _coerce_int(v, lo, hi, fallback):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return fallback
    return max(lo, min(n, hi))


def _normalize_footer_bg(stored):
    """Coerce stored bg dict into the canonical shape, dropping invalid
    values back to the FOOTER_DEFAULTS. Hex colors are validated
    against #rrggbb / #rgb; integers clamped to sensible ranges."""
    d = FOOTER_DEFAULTS["bg"]
    if not isinstance(stored, dict):
        return {**d, "sinewave_colors": list(d["sinewave_colors"])}
    style = (stored.get("style") or "").strip().lower()
    if style not in _FOOTER_BG_STYLES:
        style = d["style"]
    sw = stored.get("sinewave_colors")
    sw_colors = []
    if isinstance(sw, list):
        for c in sw[:6]:
            hx = _coerce_hex(c if isinstance(c, str) else "")
            if hx:
                sw_colors.append(hx)
    if not sw_colors:
        sw_colors = list(d["sinewave_colors"])
    # Wave shape — five floats clamped to sensible ranges. Passing
    # None/missing/invalid leaves it unset so the public painter falls
    # back to the canonical wave.
    sw_wave = None
    raw_wave = stored.get("sinewave_wave")
    if isinstance(raw_wave, dict):
        try:
            sw_wave = {
                "f1Mul": max(0.1, min(float(raw_wave.get("f1Mul", 1.0)), 6.0)),
                "f2Mul": max(0.1, min(float(raw_wave.get("f2Mul", 2.3)), 8.0)),
                "amp1":  max(0.0, min(float(raw_wave.get("amp1",  0.18)), 0.5)),
                "amp2":  max(0.0, min(float(raw_wave.get("amp2",  0.09)), 0.4)),
                "phase": float(raw_wave.get("phase", 1.2)) % (2 * 3.141592653589793),
            }
        except (TypeError, ValueError):
            sw_wave = None
    return {
        "style":            style,
        "color":            _coerce_hex(stored.get("color")),
        "color_2":          _coerce_hex(stored.get("color_2")),
        "gradient_angle":   _coerce_int(stored.get("gradient_angle"), 0, 360, d["gradient_angle"]),
        "hue":              _coerce_int(stored.get("hue"),    0, 360, d["hue"]),
        "hue_2":            _coerce_int(stored.get("hue_2"),  0, 360, d["hue_2"]),
        "blur":             _coerce_int(stored.get("blur"),   0, 200, d["blur"]),
        "opacity":          _coerce_int(stored.get("opacity"), 0, 100, d["opacity"]),
        "randomize":        bool(stored.get("randomize")),
        "sinewave_colors":  sw_colors,
        "sinewave_wave":    sw_wave,
        # Independent per-load randomise flags. Legacy
        # `sinewave_randomize` (single combined toggle) is honoured as a
        # fallback so existing rows don't lose their setting on first
        # read after the schema split.
        "sinewave_randomize_colors": bool(
            stored.get("sinewave_randomize_colors",
                       stored.get("sinewave_randomize", False))),
        "sinewave_randomize_wave": bool(
            stored.get("sinewave_randomize_wave",
                       stored.get("sinewave_randomize", False))),
        "particle_enabled": bool(stored.get("particle_enabled")),
        "particle_effect":  (stored.get("particle_effect") or d["particle_effect"]).strip(),
        "particle_speed":   _coerce_int(stored.get("particle_speed"), 10, 400, d["particle_speed"]),
        "particle_size":    _coerce_int(stored.get("particle_size"),  10, 400, d["particle_size"]),
    }


def footer_content(site):
    """Return the canonical footer content dict for a SiteSetting row.
    Reads the JSON column, normalizes, falls back to FOOTER_DEFAULTS."""
    raw = (site.frontend_footer_blocks_json if site else None) or ""
    try:
        stored = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        stored = {}
    return _normalize_footer(stored)


# ---------------------------------------------------------------------------
# Footer ⇄ blocks-list converters.
#
# The footer is migrating from a fixed content dict (one slot per block
# type) + a separate CustomLayout for the block order, to a single
# ordered ``blocks_json`` list edited with the same builder pages use.
# These two functions are the lossless bridge:
#   • ``footer_blocks_from_content`` turns the canonical content dict into
#     the page-style sections/blocks list (one section, footer blocks in a
#     sensible default order) — used by the one-time migration.
#   • ``footer_content_from_blocks`` collapses an edited blocks list back
#     into the canonical content dict — used by the public render (which
#     reuses the existing footer templates/partials) and as a legacy
#     fallback. Multiple blocks of the same type collapse last-wins; the
#     dict only has one slot per type, so single-slot legacy footers
#     round-trip exactly.
# Footer-level background (`bg`) is page-chrome styling, not a block, so it
# rides on the content dict / SiteSetting and is untouched here.
# ---------------------------------------------------------------------------

# Default order footer blocks land in when migrating a legacy footer.
FOOTER_BLOCK_ORDER = ("brand", "link_columns", "social_row", "secondary_nav",
                      "meeting_locations", "contact_section", "copyright")


def _footer_uid():
    import uuid as _uuid
    return _uuid.uuid4().hex[:8]


def _footer_block_data_from_content(block_type, content):
    """The per-block ``data`` dict for one footer block type, pulled from
    the canonical content dict."""
    if block_type == "brand":
        return dict(content["brand"])
    if block_type == "link_columns":
        return {"columns": [dict(c, links=list(c.get("links") or []))
                            for c in content["columns"]]}
    if block_type == "social_row":
        return {"items": [dict(s) for s in content["social"]]}
    if block_type == "secondary_nav":
        return {"links": [dict(l) for l in content["secondary_nav"]]}
    if block_type == "copyright":
        return {"text": content["copyright"]}
    if block_type == "meeting_locations":
        ml = content["meeting_locations"]
        return {"heading": ml["heading"],
                "predefined_ids": list(ml.get("predefined_ids") or []),
                "items": [dict(i) for i in ml.get("items") or []]}
    if block_type == "contact_section":
        return {"panes": [dict(p) for p in content["contact_section"].get("panes") or []]}
    # Static / chrome-only blocks carry no editable content.
    return {}


def footer_blocks_from_content(content, *, order=FOOTER_BLOCK_ORDER):
    """Canonical footer content dict → page-style sections list.
    Returns ``[{id, title, blocks:[{id, type, data}]}]`` with one section
    holding the footer blocks in ``order``."""
    content = _normalize_footer(content if isinstance(content, dict) else {})
    blocks = []
    for t in order:
        blocks.append({"id": _footer_uid(), "type": t,
                       "data": _footer_block_data_from_content(t, content)})
    return [{"id": _footer_uid(), "title": "", "blocks": blocks}]


def _iter_footer_blocks(sections):
    """Yield every leaf block dict across a footer sections list,
    descending into multi-column ``container`` blocks (which carry their
    columns as ``data.columns`` = list of block-lists)."""
    for sec in (sections or []):
        if not isinstance(sec, dict):
            continue
        for b in (sec.get("blocks") or []):
            if not isinstance(b, dict):
                continue
            if b.get("type") == "container":
                d = b.get("data") or {}
                for col in (d.get("columns") or []):
                    for inner in (col or []):
                        if isinstance(inner, dict):
                            yield inner
                for inner in (d.get("blocks") or []):  # legacy flat form
                    if isinstance(inner, dict):
                        yield inner
            else:
                yield b


def _footer_block(block_type, content):
    """One footer block dict ({id, type, data})."""
    return {"id": _footer_uid(), "type": block_type,
            "data": _footer_block_data_from_content(block_type, content)}


def footer_layout_to_blocks(layout_rows, content):
    """Combine a footer LAYOUT (``CustomLayout.blocks_json`` rows, or a
    prebuilt's preview rows — each ``{type:'row', cols, columns:[[{type}]]}``)
    with the content dict into an editable page-style blocks list.

    Multi-column rows become a ``container`` block carrying explicit
    ``data.columns``; single-block rows stay top-level. Result is one
    section: ``[{id, title:'', blocks:[…]}]``."""
    content = _normalize_footer(content if isinstance(content, dict) else {})
    out_blocks = []
    for row in (layout_rows or []):
        if not isinstance(row, dict):
            continue
        cols = row.get("columns") or []
        # Normalise a flat single-column row (no explicit columns) too.
        if not cols and row.get("blocks"):
            cols = [row.get("blocks")]
        # 1 column with exactly 1 block → emit it top-level (cleanest tree).
        flat = [b for col in cols for b in (col or []) if isinstance(b, dict)]
        if len(cols) <= 1 and len(flat) == 1:
            out_blocks.append(_footer_block(flat[0].get("type"), content))
            continue
        if len(cols) <= 1:
            # Single column, multiple blocks → still top-level stack.
            for b in flat:
                out_blocks.append(_footer_block(b.get("type"), content))
            continue
        # Multi-column row → a container with explicit columns.
        col_blocks = [[_footer_block(b.get("type"), content)
                       for b in (col or []) if isinstance(b, dict)]
                      for col in cols]
        out_blocks.append({"id": _footer_uid(), "type": "container",
                           "data": {"cols": len(cols), "columns": col_blocks}})
    return [{"id": _footer_uid(), "title": "", "blocks": out_blocks}]


def footer_blocks_to_layout_rows(sections):
    """Reverse of ``footer_layout_to_blocks`` — collapse an edited footer
    blocks list into ``CustomLayout``-style rows of block *types*
    (content lives in the dict, produced by ``footer_content_from_blocks``).
    Each top-level non-container block → a 1-column row; each container →
    a multi-column row preserving its columns."""
    rows = []
    for sec in (sections or []):
        if not isinstance(sec, dict):
            continue
        for b in (sec.get("blocks") or []):
            if not isinstance(b, dict):
                continue
            if b.get("type") == "container":
                d = b.get("data") or {}
                cols = d.get("columns")
                if not cols and d.get("blocks"):
                    cols = [d.get("blocks")]
                columns = [[{"type": inner.get("type")}
                            for inner in (col or []) if isinstance(inner, dict)]
                           for col in (cols or [])]
                rows.append({"type": "row", "cols": max(1, len(columns)),
                             "columns": columns})
            else:
                rows.append({"type": "row", "cols": 1,
                             "columns": [[{"type": b.get("type")}]]})
    return rows


def footer_content_from_blocks(sections, *, base=None):
    """Collapse an edited footer blocks list back into the canonical
    content dict, starting from ``base`` (defaults preserved for any type
    not present as a block). Multiples collapse last-wins. ``bg`` is
    carried through from ``base`` untouched."""
    content = _normalize_footer(base if isinstance(base, dict) else {})
    for b in _iter_footer_blocks(sections):
        t = b.get("type")
        d = b.get("data") if isinstance(b.get("data"), dict) else {}
        if t == "brand":
            content["brand"] = dict(d)
        elif t == "link_columns":
            content["columns"] = list(d.get("columns") or [])
        elif t == "social_row":
            content["social"] = list(d.get("items") or [])
        elif t == "secondary_nav":
            content["secondary_nav"] = list(d.get("links") or [])
        elif t == "copyright":
            content["copyright"] = d.get("text") or content["copyright"]
        elif t == "meeting_locations":
            content["meeting_locations"] = {
                "heading": d.get("heading") or content["meeting_locations"]["heading"],
                "predefined_ids": list(d.get("predefined_ids") or []),
                "items": list(d.get("items") or []),
            }
        elif t == "contact_section":
            content["contact_section"] = {"panes": list(d.get("panes") or [])}
    # Re-normalise so coercion/limits apply uniformly to the merged dict.
    return _normalize_footer(content)


FOOTER_MAX_COLUMNS  = 6
FOOTER_MAX_LINKS    = 12
FOOTER_MAX_SOCIAL   = 10
FOOTER_MAX_SECONDARY = 8
FOOTER_MAX_LOCATIONS = 12
FOOTER_MAX_CONTACT_PANES = 4


def parse_footer(form, existing=None):
    """Read the structured footer admin form into the canonical dict.
    Each editor section carries its own `footer_<section>_present`
    hidden marker; sections whose marker is missing (e.g. their card
    was hidden because the active layout doesn't use that block) fall
    back to the `existing` dict so the data isn't wiped on save. Empty
    rows are dropped; per-section caps prevent runaway growth."""
    existing = existing or {}

    # ── Brand ──
    if "footer_brand_present" in form:
        raw_src = (form.get("footer_brand_logo_source") or "").strip().lower()
        if raw_src not in ("header", "custom"):
            raw_src = FOOTER_DEFAULTS["brand"]["logo_source"]
        try:
            width = int(form.get("footer_brand_logo_width") or FOOTER_DEFAULTS["brand"]["logo_width"])
        except (TypeError, ValueError):
            width = FOOTER_DEFAULTS["brand"]["logo_width"]
        width = max(40, min(width, 600))
        brand = {
            "logo_source": raw_src,
            "logo_width":  width,
            "tagline":     (form.get("footer_brand_tagline") or "").strip(),
        }
    else:
        brand = existing.get("brand") or dict(FOOTER_DEFAULTS["brand"])

    # ── Columns ── section marker: `footer_cols_section_present`. Row
    # markers (`footer_col_present=<idx>`) drive enumeration; without
    # the section marker we keep whatever was previously saved.
    if "footer_cols_section_present" in form:
        columns = []
        for raw_idx in form.getlist("footer_col_present"):
            try:
                i = int(raw_idx)
            except (TypeError, ValueError):
                continue
            title = (form.get(f"footer_col_{i}_title") or "").strip()
            links = []
            for raw_lidx in form.getlist(f"footer_col_{i}_link_present"):
                try:
                    j = int(raw_lidx)
                except (TypeError, ValueError):
                    continue
                label = (form.get(f"footer_col_{i}_link_{j}_label") or "").strip()
                url   = (form.get(f"footer_col_{i}_link_{j}_url")   or "").strip()
                if not (label or url):
                    continue
                links.append({
                    "label": label,
                    "url":   url,
                    "open_in_new_tab": form.get(f"footer_col_{i}_link_{j}_new_tab") == "1",
                })
                if len(links) >= FOOTER_MAX_LINKS:
                    break
            if not (title or links):
                continue
            columns.append({"title": title, "links": links})
            if len(columns) >= FOOTER_MAX_COLUMNS:
                break
    else:
        columns = existing.get("columns") or []

    # ── Social row ──
    if "footer_social_section_present" in form:
        social = []
        for raw_idx in form.getlist("footer_social_present"):
            try:
                i = int(raw_idx)
            except (TypeError, ValueError):
                continue
            icon  = (form.get(f"footer_social_{i}_icon")  or "").strip()
            label = (form.get(f"footer_social_{i}_label") or "").strip()
            url   = (form.get(f"footer_social_{i}_url")   or "").strip()
            if not (icon or url):
                continue
            social.append({"icon": icon, "label": label, "url": url})
            if len(social) >= FOOTER_MAX_SOCIAL:
                break
    else:
        social = existing.get("social") or []

    # ── Secondary nav ──
    if "footer_secnav_section_present" in form:
        secondary_nav = []
        for raw_idx in form.getlist("footer_nav_present"):
            try:
                i = int(raw_idx)
            except (TypeError, ValueError):
                continue
            label = (form.get(f"footer_nav_{i}_label") or "").strip()
            url   = (form.get(f"footer_nav_{i}_url")   or "").strip()
            if not (label or url):
                continue
            secondary_nav.append({"label": label, "url": url})
            if len(secondary_nav) >= FOOTER_MAX_SECONDARY:
                break
    else:
        secondary_nav = existing.get("secondary_nav") or []

    # ── Meeting locations ──
    if "footer_loc_section_present" in form:
        locations = []
        for raw_idx in form.getlist("footer_loc_present"):
            try:
                i = int(raw_idx)
            except (TypeError, ValueError):
                continue
            name        = (form.get(f"footer_loc_{i}_name")        or "").strip()
            street      = (form.get(f"footer_loc_{i}_street")      or "").strip()
            city        = (form.get(f"footer_loc_{i}_city")        or "").strip()
            state       = (form.get(f"footer_loc_{i}_state")       or "").strip()
            zip_code    = (form.get(f"footer_loc_{i}_zip_code")    or "").strip()
            note        = (form.get(f"footer_loc_{i}_note")        or "").strip()
            website_url = (form.get(f"footer_loc_{i}_website_url") or "").strip()
            maps_url    = (form.get(f"footer_loc_{i}_maps_url")    or "").strip()
            icon        = (form.get(f"footer_loc_{i}_icon")        or "").strip()
            # Sync the legacy `address` column from the split fields so
            # any callers reading `it.address` still see the canonical
            # string. Falls back to a posted `_address` value when the
            # admin form isn't in split-fields mode (legacy saves).
            csz_line = ", ".join(p for p in [city, " ".join(p for p in [state, zip_code] if p)] if p) \
                       if (city or state or zip_code) else ""
            address_lines_acc = [p for p in [street, csz_line] if p]
            address = "\n".join(address_lines_acc) if address_lines_acc \
                      else (form.get(f"footer_loc_{i}_address") or "").strip()
            if not (name or street or city or address):
                continue
            locations.append({"name": name, "street": street, "city": city,
                              "state": state, "zip_code": zip_code,
                              "address": address, "note": note,
                              "website_url": website_url,
                              "maps_url": maps_url, "icon": icon})
            if len(locations) >= FOOTER_MAX_LOCATIONS:
                break
        # Predefined Location IDs — checkbox list emits each checked
        # row as `footer_loc_predefined_id` with the integer PK as the
        # value. Drop noise + dupes; cap at FOOTER_MAX_LOCATIONS so a
        # giant Location table doesn't overrun the footer.
        predefined_ids = []
        seen = set()
        for raw in form.getlist("footer_loc_predefined_id"):
            try:
                n = int(raw)
            except (TypeError, ValueError):
                continue
            if n > 0 and n not in seen:
                seen.add(n); predefined_ids.append(n)
            if len(predefined_ids) >= FOOTER_MAX_LOCATIONS:
                break
        meeting_locations = {
            "heading": (form.get("footer_loc_heading") or "").strip()
                       or FOOTER_DEFAULTS["meeting_locations"]["heading"],
            "predefined_ids": predefined_ids,
            "items":   locations,
        }
    else:
        meeting_locations = existing.get("meeting_locations") \
                            or {"heading": FOOTER_DEFAULTS["meeting_locations"]["heading"],
                                "predefined_ids": [], "items": []}

    # ── Contact section panes ──
    if "footer_contact_section_present" in form:
        contact_panes = []
        for raw_idx in form.getlist("footer_contact_present"):
            try:
                i = int(raw_idx)
            except (TypeError, ValueError):
                continue
            heading = (form.get(f"footer_contact_{i}_heading") or "").strip()
            body    = (form.get(f"footer_contact_{i}_body")    or "").strip()
            if not (heading or body):
                continue
            contact_panes.append({"heading": heading, "body": body})
            if len(contact_panes) >= FOOTER_MAX_CONTACT_PANES:
                break
        contact_section = {"panes": contact_panes}
    else:
        contact_section = existing.get("contact_section") or {"panes": []}

    # ── Copyright ──
    if "footer_copyright_present" in form:
        copyright_str = (form.get("footer_copyright") or "").strip() \
                        or FOOTER_DEFAULTS["copyright"]
    else:
        copyright_str = existing.get("copyright") or FOOTER_DEFAULTS["copyright"]

    # ── Background (style + per-style settings + particle overlay) ──
    if "footer_bg_section_present" in form:
        # Sinewave palette — four discrete colour pickers
        # `footer_bg_sinewave_c1` … `c4`. Empty / non-hex slots drop out
        # so the public footer falls back to the default teal→blue→purple
        # when no valid colours are stored. Legacy comma-separated
        # `footer_bg_sinewave_colors` field is still honoured for posts
        # from older form caches.
        sw_list = []
        for i in range(1, 5):
            c = (form.get(f"footer_bg_sinewave_c{i}") or "").strip()
            if c and _coerce_hex(c):
                sw_list.append(c)
        if not sw_list:
            sw_raw = (form.get("footer_bg_sinewave_colors") or "").strip()
            if sw_raw:
                try:
                    import json as _json_local
                    parsed = _json_local.loads(sw_raw)
                    if isinstance(parsed, list):
                        sw_list = [str(c) for c in parsed]
                except (ValueError, TypeError):
                    sw_list = [c.strip() for c in sw_raw.split(",") if c.strip()]
        # Wave-shape JSON — emitted by the admin's Randomize button as a
        # `{f1Mul, f2Mul, amp1, amp2, phase}` blob. Empty / invalid →
        # fall back to the canonical wave on the public painter.
        sw_wave = None
        raw_wave = (form.get("footer_bg_sinewave_wave") or "").strip()
        if raw_wave:
            try:
                import json as _json_local
                parsed_wave = _json_local.loads(raw_wave)
                if isinstance(parsed_wave, dict):
                    sw_wave = parsed_wave
            except (ValueError, TypeError):
                sw_wave = None
        bg = _normalize_footer_bg({
            "style":            form.get("footer_bg_style"),
            "color":            form.get("footer_bg_color"),
            "color_2":          form.get("footer_bg_color_2"),
            "gradient_angle":   form.get("footer_bg_gradient_angle"),
            "hue":              form.get("footer_bg_hue"),
            "hue_2":            form.get("footer_bg_hue_2"),
            "blur":             form.get("footer_bg_blur"),
            "opacity":          form.get("footer_bg_opacity"),
            "randomize":        form.get("footer_bg_randomize") == "1",
            "sinewave_colors":  sw_list,
            "sinewave_wave":    sw_wave,
            "sinewave_randomize_colors": form.get("footer_bg_sinewave_randomize_colors") == "1",
            "sinewave_randomize_wave":   form.get("footer_bg_sinewave_randomize_wave") == "1",
            "particle_enabled": form.get("footer_bg_particle_enabled") == "1",
            "particle_effect":  form.get("footer_bg_particle_effect"),
            "particle_speed":   form.get("footer_bg_particle_speed"),
            "particle_size":    form.get("footer_bg_particle_size"),
        })
    else:
        bg = existing.get("bg") or _normalize_footer_bg(None)

    return {
        "brand": brand,
        "columns": columns,
        "social": social,
        "secondary_nav": secondary_nav,
        "copyright": copyright_str,
        "meeting_locations": meeting_locations,
        "contact_section": contact_section,
        "bg": bg,
    }
