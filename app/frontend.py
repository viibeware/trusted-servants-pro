# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public-facing frontend blueprint.

When `SiteSetting.frontend_enabled` is True, requests to the root URL serve
a marketing/content homepage instead of bouncing straight to the login
screen. When the toggle is off, the root URL redirects to the admin login.

Admin pages remain at /tspro/* and the authenticated dashboard is at /tspro/.
"""
from flask import Blueprint, render_template, redirect, url_for, abort, request
from flask_login import current_user
from .models import SiteSetting, Meeting, FrontendNavItem, Post

bp = Blueprint("frontend", __name__)

# ---------------------------------------------------------------------------
# Template library — ships layout presets for the major public-site regions.
# Each entry defines a template key, a display name, a description, and the
# Jinja partial path to include in frontend/base.html. Adding a new header
# layout is just a matter of dropping a template file into templates/frontend/
# headers/ and appending to HEADER_TEMPLATES.
#
# Settings (width mode, logo, nav, alert bars) are shared across every
# template so picking a new layout never wipes your content.
# ---------------------------------------------------------------------------
HEADER_TEMPLATES = [
    {
        "key": "classic",
        "name": "Classic",
        "description": "Sticky glassy header with a logo on the left and nav on the right. The first header we built — fluid opacity on scroll, Inter/Fraunces typography.",
        "partial": "frontend/headers/classic.html",
    },
    {
        "key": "recovery-blue",
        "name": "Recovery Blue",
        "description": "Fellowship-style two-row layout: a blue utility strip on top (helpline + hyperlist link), wide logotype on the left of the main row, and a row of primary nav links on the right. White-on-white with a soft hairline divider.",
        "partial": "frontend/headers/recovery-blue.html",
    },
]

# Each prebuilt footer's "shape" expressed as a synthetic block list, used
# only by the layout-picker modal to render the stacked colour-chip preview
# next to each card. The actual render still goes through the Jinja file
# named in the corresponding FOOTER_TEMPLATES entry — these chips are pure
# decoration so the picker modal can show what each prebuilt looks like
# at-a-glance.
_FOOTER_PREBUILT_PREVIEWS = {
    "classic":      [{"type": "brand"}, {"type": "link_columns"}, {"type": "copyright"},
                     {"type": "secondary_nav"}, {"type": "social_row"}],
    "minimal":      [{"type": "copyright"}, {"type": "secondary_nav"}],
    "stacked":      [{"type": "brand"}, {"type": "link_columns"}, {"type": "social_row"},
                     {"type": "copyright"}],
    "mega":         [{"type": "brand"}, {"type": "link_columns"}, {"type": "link_columns"},
                     {"type": "copyright"}, {"type": "secondary_nav"}],
}


# Drag-drop palette for the structure-layout builder when building a
# *footer* layout. Each entry surfaces in the builder's library column;
# admins drag them onto the canvas. Render-side, each block type maps to
# a partial under frontend/footers/blocks/.
FOOTER_BLOCK_CATALOG = [
    {"key": "brand",         "name": "Brand",          "icon": "star",
     "desc": "Logo + site name + tagline. Reads from the Brand block on the Footer admin."},
    {"key": "link_columns",  "name": "Link columns",   "icon": "layout-grid",
     "desc": "All admin-defined link columns rendered as a responsive grid."},
    {"key": "social_row",    "name": "Social icons",   "icon": "share-2",
     "desc": "The admin's social icon row (instagram, facebook, etc.)."},
    {"key": "secondary_nav", "name": "Secondary nav",  "icon": "list",
     "desc": "Inline links — privacy, terms, cookies, etc."},
    {"key": "copyright",     "name": "Copyright",      "icon": "copyright",
     "desc": "The copyright line. {year} / {site_name} placeholders supported."},
    {"key": "meeting_locations", "name": "Meeting locations", "icon": "map-pin",
     "desc": "Card grid of physical meeting addresses. Heading + list editable on the Footer admin."},
    {"key": "contact_section", "name": "Contact section",   "icon": "mail",
     "desc": "1-4 panes side-by-side, each with a heading + Markdown body."},
    {"key": "divider",       "name": "Divider",        "icon": "minus",
     "desc": "Thin horizontal hairline separator between sections."},
    {"key": "spacer",        "name": "Spacer",         "icon": "move-vertical",
     "desc": "Vertical breathing room between adjacent blocks."},
    {"key": "powered_by",    "name": "Powered by",     "icon": "github",
     "desc": "Static \"Powered by Trusted Servants Pro\" attribution linking the project's GitHub."},
    {"key": "admin_login",   "name": "Admin login",    "icon": "log-in",
     "desc": "Pill-style link to the admin sign-in page. Authenticated users get redirected straight to the dashboard."},
]


def all_footer_layouts():
    """Return a unified list of footer layouts for the picker: hardcoded
    FOOTER_TEMPLATES prebuilts wrapped to look like CustomLayout rows,
    followed by user-created CustomLayout rows of kind='footer'. Both
    duck-type the same `key`/`name`/`description`/`blocks_json`/`is_prebuilt`
    attributes the layout-picker macro reads."""
    import json as _json
    from types import SimpleNamespace
    from .models import CustomLayout
    out = []
    for t in FOOTER_TEMPLATES:
        out.append(SimpleNamespace(
            key=t["key"], name=t["name"], description=t["description"],
            blocks_json=_json.dumps(_FOOTER_PREBUILT_PREVIEWS.get(t["key"], [])),
            is_prebuilt=True,
        ))
    customs = (CustomLayout.query
               .filter_by(kind="footer")
               .order_by(CustomLayout.created_at)
               .all())
    out.extend(customs)
    return out


FOOTER_TEMPLATES = [
    {
        "key": "classic",
        "name": "Classic",
        "description": "Three-column: brand on the left, link columns in the middle, copyright on the right. Bottom row carries a thin secondary nav (privacy / terms) + the social icon row when set.",
        "partial": "frontend/footers/classic.html",
    },
    {
        "key": "minimal",
        "name": "Minimal",
        "description": "Single-line footer — copyright on the left, a row of inline secondary nav links on the right. No brand, no columns. Quietest possible footing.",
        "partial": "frontend/footers/minimal.html",
    },
    {
        "key": "stacked",
        "name": "Stacked",
        "description": "Centered stack: brand + tagline at the top, link columns below in a centred grid, social icon row, copyright at the bottom. Spacious and brand-forward.",
        "partial": "frontend/footers/stacked.html",
    },
    {
        "key": "mega",
        "name": "Mega",
        "description": "Four-column wall: brand + tagline + social row in the first column, three link columns to the right. Bottom row carries copyright + secondary nav. Best for sites with lots of pages to surface.",
        "partial": "frontend/footers/mega.html",
    },
    # Recovery Blue used to live here as a hardcoded Jinja partial. It's
    # now seeded at boot as a CustomLayout(kind='footer', is_prebuilt=False)
    # so admins can rearrange its block sequence in the drag-drop builder.
    # The seeded layout's content is editable through the Meeting Locations
    # + Contact Section editors on the Footer admin page.
]

MEGAMENU_TEMPLATES = [
    {
        "key": "classic",
        "name": "Classic",
        "description": "Compact card-style dropdown: centered white panel with a soft shadow and subtle dividers between columns. Uses an inline arrow glyph after each link, no full-width color wash.",
        "partial": "frontend/megamenus/classic.html",
    },
    {
        "key": "recovery-blue",
        "name": "Recovery Blue",
        "description": "Full-width colored panel: bold bg color with rounded bottom corners, animated chevrons, and a hover-slide effect on each link.",
        "partial": "frontend/megamenus/recovery-blue.html",
    },
]

THEMES = [
    {
        "key": "classic",
        "name": "Classic",
        "description": "Our original — animated-blob hero, glassy header, Inter + Fraunces typography. Light, modern, web-default. Picking this theme cascades to every section's layout.",
    },
    {
        "key": "recovery-blue",
        "name": "Recovery Blue",
        "description": "Fellowship-style — blue utility strip, two-row header with wide logotype, fellowship-style copy, full-width mega menus. Picking this theme cascades to every section's layout.",
    },
]

HOMEPAGE_TEMPLATES = [
    {
        "key": "classic",
        "name": "Classic",
        "description": "Animated-blob hero, 4 quick-link cards, upcoming-meetings grid, about pillars, dark contact CTA. Our original homepage.",
        "partial": "frontend/homepages/classic.html",
    },
    {
        "key": "recovery-blue",
        "name": "Recovery Blue",
        "description": "Fellowship hero with a serving-area statement, a Meetings / Literature / Fellowship three-up, Today's Meetings preview, and CTAs.",
        "partial": "frontend/homepages/recovery-blue.html",
    },
]

# ---------------------------------------------------------------------------
# Reusable templates for entity-detail pages. Unlike layouts (which apply to
# a single page slug like the homepage), these are picked once and apply to
# every meeting / every event detail page rendered from dynamic data. The
# admin "Templates" section drives selection.
# ---------------------------------------------------------------------------
MEETING_TEMPLATES = [
    {
        "key": "classic",
        "name": "Classic",
        "description": "Two-column card grid with schedule, location, and Zoom side-by-side. Balanced and familiar — matches the original site.",
        "partial": "frontend/meetings/classic.html",
    },
    {
        "key": "card_stack",
        "name": "Card Stack",
        "description": "Gradient hero banner with a big primary action card up top — pulls the join/directions CTA above the fold. Mobile-first, single column.",
        "partial": "frontend/meetings/card_stack.html",
    },
    {
        "key": "magazine",
        "name": "Magazine",
        "description": "Editorial: serif headline, hairline rule, long-form description on the left, sticky meta sidebar (schedule / location / Zoom) on the right.",
        "partial": "frontend/meetings/magazine.html",
    },
    {
        "key": "minimal",
        "name": "Minimal",
        "description": "Spare and typography-driven. No cards — just generous whitespace, an eyebrow label, the meeting name, and a simple labeled list of details.",
        "partial": "frontend/meetings/minimal.html",
    },
]

# Layouts for the public /meetings LIST page (every active meeting,
# all info inline). Picked once and applies to the whole list — visitors
# can filter/search within the chosen layout. Detail-page links remain
# available for permalinks but visitors no longer have to click through
# to see schedule / location / Zoom info.
MEETINGS_LIST_TEMPLATES = [
    {
        "key": "sidebar",
        "name": "Sidebar",
        "description": "Sticky day-filter rail on the left with live counts; expanded meeting cards on the right showing every schedule, address, and Zoom link inline. The rail collapses to a horizontal pill row on mobile.",
        "partial": "frontend/meetings_list/sidebar.html",
    },
    {
        "key": "directory",
        "name": "Directory",
        "description": "Sticky toolbar with a live search box, day chips, and meeting-type filter; below it a dense single-column directory of meeting rows with all info side-by-side. Reads like an org directory page.",
        "partial": "frontend/meetings_list/directory.html",
    },
    {
        "key": "weekboard",
        "name": "Week board",
        "description": "Seven vertical columns (Mon–Sun) with each meeting placed under every day it runs, sorted by start time. Dense, at-a-glance overview. On mobile the columns become a horizontal swipe deck so fellowships with crowded schedules stay scannable.",
        "partial": "frontend/meetings_list/weekboard.html",
    },
]


# Default content for the "Pro Tips" accordion at the bottom of the
# /meetings page. The admin can override any field via the JSON blob
# stored on `SiteSetting.frontend_meetings_list_protips_json`; missing
# fields fall back to these values, which mirror the kinds of guidance
# fellowships post to help newcomers get the most out of an online
# meeting (mic etiquette, Zoom basics, what to expect, etc.).
MEETINGS_LIST_PROTIPS_DEFAULTS = {
    "enabled": True,
    "heading": "Pro Tips",
    "subheading": "for a great online meeting",
    "icon": "lightbulb",
    "icon_color": "",
    "bg_color": "",
    "items": [
        {
            "icon": "wifi", "icon_size": "",
            "question": "Use a stable internet connection",
            "answer": "Wired Ethernet is best; strong Wi-Fi works too. Avoid joining from a moving vehicle — drop-outs disrupt the flow of the meeting and make it hard for others to hear shares.",
        },
        {
            "icon": "headphones", "icon_size": "",
            "question": "Wear headphones to prevent echo",
            "answer": "When several attendees are in the same room or running speakers + a mic at once, audio loops back into the call as a delayed echo. Headphones (any kind) eliminate it instantly.",
        },
        {
            "icon": "mic-off", "icon_size": "",
            "question": "Mute when you're not speaking",
            "answer": "Background noise — typing, dogs, traffic, fans — broadcasts to the whole meeting. Most clients show a *push-to-talk* shortcut (hold **Space** in Zoom) so you can quickly speak up without leaving yourself muted.",
        },
        {
            "icon": "video", "icon_size": "",
            "question": "Turn your camera on if you can",
            "answer": "Faces help the room feel like a meeting instead of a phone call. If your space isn't camera-ready, that's fine — but consider using a plain virtual background or just your name.",
        },
        {
            "icon": "user", "icon_size": "",
            "question": "Use a recognisable display name",
            "answer": "First name + last initial works well (e.g. *Alex M*). It helps the chair acknowledge you and keeps the participant list scannable for trusted servants on door duty.",
        },
        {
            "icon": "shield", "icon_size": "",
            "question": "Don't share Zoom links publicly",
            "answer": "Meeting IDs and passcodes are for fellowship members. Posting them on public social media invites disruption. Share the meeting page URL instead — newcomers can copy the credentials there.",
        },
        {
            "icon": "clock", "icon_size": "",
            "question": "Arrive a few minutes early",
            "answer": "The waiting room (when used) opens shortly before the start time. Joining 5 minutes early lets the host admit you, gives you a moment to greet others, and keeps the meeting itself on schedule.",
        },
        {
            "icon": "help-circle", "icon_size": "",
            "question": "Having technical trouble?",
            "answer": "Try leaving and rejoining the meeting first — it resolves most audio/video issues. If you can't get in at all, check the meeting page for an updated Zoom link or reach out via the contact info on the home page.",
        },
    ],
}


def meetings_list_protips_resolved(site):
    """Merge the admin-saved Pro Tips JSON onto the defaults so missing
    fields always have a sensible value. Returns the canonical dict the
    template expects: enabled, heading, subheading, icon, icon_color,
    bg_color, items[]. Items each carry: icon, icon_size, question,
    answer. Empty / unparseable JSON falls back wholesale to defaults."""
    import json as _json
    out = {**MEETINGS_LIST_PROTIPS_DEFAULTS,
           "items": [dict(it) for it in MEETINGS_LIST_PROTIPS_DEFAULTS["items"]]}
    raw = (site.frontend_meetings_list_protips_json
           if site and site.frontend_meetings_list_protips_json else None)
    if not raw:
        return out
    try:
        cfg = _json.loads(raw)
    except (ValueError, TypeError):
        return out
    if not isinstance(cfg, dict):
        return out
    for k in ("enabled",):
        if k in cfg:
            out[k] = bool(cfg.get(k))
    for k in ("heading", "subheading", "icon", "icon_color", "bg_color"):
        if k in cfg and isinstance(cfg.get(k), str):
            out[k] = cfg[k].strip()
    items_raw = cfg.get("items")
    if isinstance(items_raw, list):
        items = []
        for raw_item in items_raw:
            if not isinstance(raw_item, dict):
                continue
            q = (raw_item.get("question") or "").strip()
            a = (raw_item.get("answer") or "").strip()
            if not (q or a):
                continue
            ic = (raw_item.get("icon") or "").strip()
            ic_size = str(raw_item.get("icon_size") or "").strip()
            items.append({
                "question":  q,
                "answer":    a,
                "icon":      ic,
                "icon_size": ic_size,
            })
        out["items"] = items
    return out


# Layouts for the public /events LIST page (every upcoming event).
# Picked once and applies to the whole list — visitors can browse the
# full event queue in whichever shape the admin chose. Each template
# shares the same upcoming-events data fetched via filtered_events().
EVENTS_LIST_TEMPLATES = [
    {
        "key": "cards",
        "name": "Cards",
        "description": "Vertical stack of event cards — date block on the left, image thumbnail (when present) in the middle, title + summary + meta on the right. Reads top-to-bottom in chronological order. The most flexible default.",
        "partial": "frontend/events_list/cards.html",
    },
    {
        "key": "calendar",
        "name": "Calendar",
        "description": "Month-grid calendar with event chips on the days they occur, plus an inline list of every event in the visible month below the grid. Prev/next buttons step through months without leaving the page.",
        "partial": "frontend/events_list/calendar.html",
    },
    {
        "key": "timeline",
        "name": "Timeline",
        "description": "Vertical timeline with each event placed as a node on a central spine, alternating left/right cards. Big calendar-style date blocks anchor each entry. Editorial feel.",
        "partial": "frontend/events_list/timeline.html",
    },
    {
        # Internal key stays "magazine" so existing saved selections
        # keep working without a data migration; the label visitors +
        # admins see is "Overview".
        "key": "magazine",
        "name": "Overview",
        "description": "Featured-first overview: the next upcoming event renders as a hero with its cover image, then a 3-up grid of subsequent events below. Pulls the eye to what's next while keeping later events scannable.",
        "partial": "frontend/events_list/magazine.html",
    },
    {
        "key": "omni",
        "name": "Omni",
        "description": "All four views in one — a tab switcher at the top lets visitors flip between Overview, Cards, Calendar, and Timeline on the fly. The chosen view persists in their browser via localStorage, so returning visitors land on whichever style they preferred.",
        "partial": "frontend/events_list/omni.html",
    },
]


# Templates shipped for the public /announcements page. Each entry is a
# selectable layout in the admin Templates panel. Currently a single
# omni layout (Cards + GSR Summary), but the catalog is wired so future
# announcement layouts can be added without touching the route or admin
# page — drop a partial in templates/frontend/announcements_list/ and
# append an entry here.
ANNOUNCEMENTS_LIST_TEMPLATES = [
    {
        "key": "omni",
        "name": "Omni",
        "description": "Two views in one — a tab switcher at the top lets visitors flip between full announcement Cards and a paper-styled GSR Summary (titles + summaries set in Libre Baskerville). A separate Archive pill on the right links to /announcements/archive.",
        "partial": "frontend/announcements_list/omni.html",
    },
]


# Layouts for the public /printlist page. Single entry today, but the
# catalog shape mirrors the other pickers so a second printable layout
# can be added without restructuring the admin form.
PRINTLIST_TEMPLATES = [
    {
        "key": "classic",
        "name": "Classic",
        "description": "Branded two-column schedule with day-banded sections. Renders a 2-page letter-size PDF by default; legal is a one-click switch.",
        "partial": "frontend/printlist.html",
    },
]


# Layouts for the public /library page (Literature Library — every
# public-marked Library + its public-marked items). Single layout
# today; mirrors the Archive page's sidebar-rail-with-filters chrome
# so the two pages read as siblings.
LITERATURE_LIBRARY_TEMPLATES = [
    {
        "key": "classic",
        "name": "Classic",
        "description": "Sticky sidebar rail with live search and per-library filter pills, over a stack of library sections — each one listing its public-marked items as compact cards. Mirrors the Archive page's chrome and palette.",
        "partial": "frontend/literature_library.html",
    },
]


EVENT_TEMPLATES = [
    {
        "key": "classic",
        "name": "Classic",
        "description": "Featured image up top, type chips, summary, then a clean two-column grid of When / Where / Zoom / Website / Contact cards.",
        "partial": "frontend/events/classic.html",
    },
    {
        "key": "poster",
        "name": "Poster",
        "description": "Full-bleed featured image as a darkened backdrop with the title overlaid, then a stylized ticket card with the date block, key details, and CTAs.",
        "partial": "frontend/events/poster.html",
    },
    {
        "key": "timeline",
        "name": "Timeline",
        "description": "Big calendar-style date block on the left (month / day stacked), event content beside it. Reads like a marked-up date in a journal.",
        "partial": "frontend/events/timeline.html",
    },
    {
        "key": "minimal",
        "name": "Minimal",
        "description": "Centered, no images, no chips. A thin date line, a serif title, the body text, and a compact labeled detail block. Maximum focus on the writing.",
        "partial": "frontend/events/minimal.html",
    },
]


def _template_meta(templates, key):
    for t in templates:
        if t["key"] == key:
            return t
    return templates[0]


# ---------------------------------------------------------------------------
# Per-template appearance overrides.
#
# Stored as a JSON blob on SiteSetting.frontend_template_settings_json keyed
# by content-type then template key. Each leaf is a dict with:
#   bg            — hex color (page background) or "" to fall through to the
#                   site's design tokens
#   heading_font  — font key from app.fonts (inter / fraunces / custom:N)
#                   or "" for theme default
#   body_font     — same shape as heading_font
#   heading_size  — int percent scale (default 100)
#   body_size     — int percent scale (default 100)
#
# Resolves at render time into a CSS-vars string injected onto the template's
# top-level <section> via inline style. Each template's CSS reads those vars
# (--tpl-bg, --tpl-heading-font, --tpl-body-font, --tpl-heading-scale,
# --tpl-body-scale) with the page-level design tokens as fallback — so when
# a value is empty the template falls through to the global Design page.
# ---------------------------------------------------------------------------

import re as _re_tpl
_HEX_RE_TPL = _re_tpl.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def template_settings(site, kind, key):
    """Return the saved per-template overrides as a dict, with sane defaults
    for any missing keys. Never raises — bad/missing JSON returns the
    all-defaults dict so the page still renders.

    ``heading_size`` / ``body_size`` are absolute font sizes in *rem*.
    A value of ``0`` means "no override" (the template falls through to its
    own responsive default). Valid range is 0.5–4.0 rem."""
    import json
    defaults = {"bg": "", "heading_font": "", "body_font": "",
                "heading_size": 0.0, "body_size": 0.0}
    raw = (site.frontend_template_settings_json if site else None) or ""
    if not raw:
        return defaults
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return defaults
    leaf = ((data.get(kind) or {}).get(key)) or {}
    out = dict(defaults)
    if isinstance(leaf.get("bg"), str) and _HEX_RE_TPL.match(leaf["bg"]):
        out["bg"] = leaf["bg"]
    if isinstance(leaf.get("heading_font"), str):
        out["heading_font"] = leaf["heading_font"].strip()
    if isinstance(leaf.get("body_font"), str):
        out["body_font"] = leaf["body_font"].strip()
    for k in ("heading_size", "body_size"):
        try:
            v = float(leaf.get(k))
            if 0.5 <= v <= 4.0:
                out[k] = round(v, 1)
        except (TypeError, ValueError):
            pass
    return out


def _fluid_clamp(rem, abs_floor, min_vp=320, max_vp=1200):
    """Convert a desktop-intent rem override into a mobile-aware
    ``clamp(min, calc(offset + slope*vw), max)`` expression that
    interpolates linearly between ``min_vp`` (mobile floor) and
    ``max_vp`` (the admin's intended desktop size).

    Result for a 4rem override with 1.25rem floor over the default
    320–1200px range::

        clamp(2rem, calc(1.273rem + 3.64vw), 4rem)

    At 320px viewport: ≈2rem (the floor).
    At 768px viewport: ≈3.02rem.
    At 1200px viewport and beyond: 4rem (the max, capped).

    When the override value is small enough that the floor would meet
    or exceed it, the expression collapses to a plain rem constant —
    no scaling needed."""
    floor = max(abs_floor, round(rem * 0.5, 2))
    floor = min(rem, floor)
    if floor >= rem:
        return f"{rem:.2f}rem".rstrip("0").rstrip(".")
    diff_px = (rem - floor) * 16
    span_px = max_vp - min_vp
    slope_vw = round(diff_px / span_px * 100, 2)        # vw units
    offset_px = floor * 16 - (diff_px / span_px) * min_vp
    offset_rem = round(offset_px / 16, 3)
    return (f"clamp({floor:g}rem, "
            f"calc({offset_rem}rem + {slope_vw}vw), "
            f"{rem:.2f}rem)".replace(".00rem)", "rem)"))


def template_css_vars(settings):
    """Inline ``style=""`` value for the template's top-level section.
    Empty/default values are skipped so the template falls through to the
    page-level design tokens / template responsive defaults.

    Heading and body size overrides are emitted as ``clamp()`` expressions
    so the admin-chosen rem value behaves as the *desktop* size and shrinks
    on narrow viewports — matching the responsive behavior of each
    template's built-in defaults."""
    from .fonts import font_stack
    parts = []
    if settings.get("bg"):
        parts.append(f"--tpl-bg: {settings['bg']};")
    if settings.get("heading_font"):
        parts.append(f"--tpl-heading-font: {font_stack(settings['heading_font'])};")
    if settings.get("body_font"):
        parts.append(f"--tpl-body-font: {font_stack(settings['body_font'])};")
    hs = settings.get("heading_size") or 0
    if hs:
        parts.append(f"--tpl-heading-size: {_fluid_clamp(hs, 1.25)};")
    bs = settings.get("body_size") or 0
    if bs:
        parts.append(f"--tpl-body-size: {_fluid_clamp(bs, 1.0)};")
    return " ".join(parts)


def _site():
    return SiteSetting.query.first()


def _frontend_context(site):
    """Shared context values for every frontend page."""
    header_tpl = _template_meta(
        HEADER_TEMPLATES,
        (site.frontend_header_template if site else None) or "classic",
    )
    # Resolve footer layout the same way as homepage: a CustomLayout row
    # of kind="footer" wins (drag-drop creations); otherwise fall back to
    # the hardcoded FOOTER_TEMPLATES prebuilts.
    import json as _json_footer
    from .models import CustomLayout as _CL
    footer_key = (site.frontend_footer_template if site else None) or "classic"
    footer_blocks = None
    footer_partial = None
    fcl = _CL.query.filter_by(key=footer_key, kind="footer").first()
    if fcl:
        try:
            footer_blocks = _json_footer.loads(fcl.blocks_json or "[]")
        except (ValueError, TypeError):
            footer_blocks = []
        footer_partial = "frontend/footers/_custom.html"
    else:
        footer_tpl = _template_meta(FOOTER_TEMPLATES, footer_key)
        footer_partial = footer_tpl["partial"]
        footer_key = footer_tpl["key"]
    # Resolve homepage layout: prefer a CustomLayout matching the stored
    # key (covers seeded pre-built presets AND drag-drop creations); fall
    # back to the legacy hardcoded HOMEPAGE_TEMPLATES list.
    import json
    from .models import CustomLayout
    homepage_key = (site.frontend_homepage_template if site else None) or "classic"
    homepage_blocks = None
    homepage_partial = None
    cl = CustomLayout.query.filter_by(key=homepage_key, kind="homepage").first()
    if cl:
        try:
            homepage_blocks = json.loads(cl.blocks_json or "[]")
        except (ValueError, TypeError):
            homepage_blocks = []
        homepage_partial = "frontend/homepages/_custom.html"
    else:
        homepage_tpl = _template_meta(HOMEPAGE_TEMPLATES, homepage_key)
        homepage_partial = homepage_tpl["partial"]
        homepage_key = homepage_tpl["key"]
    megamenu_tpl = _template_meta(
        MEGAMENU_TEMPLATES,
        (site.frontend_megamenu_template if site else None) or "recovery-blue",
    )
    nav_items = (FrontendNavItem.query
                 .order_by(FrontendNavItem.position, FrontendNavItem.id)
                 .all())
    from .blocks import site_blocks, filtered_meetings, filtered_events
    from .utility_bar import utility_bar_context, current_live_meeting
    block_content = site_blocks(site)
    meetings_groups = filtered_meetings(block_content.get("_meetings"))
    events_list = filtered_events(block_content.get("_events"), site=site)
    utility_bar = utility_bar_context(site)
    live_meeting = current_live_meeting(site) if utility_bar["show_live"] else None
    return {
        "site": site,
        "utility_bar": utility_bar,
        "live_meeting": live_meeting,
        "header_template_partial": header_tpl["partial"],
        "header_template_key": header_tpl["key"],
        "footer_template_partial": footer_partial,
        "footer_template_key": footer_key,
        "footer_blocks": footer_blocks,
        "homepage_template_partial": homepage_partial,
        "homepage_template_key": homepage_key,
        "homepage_blocks": homepage_blocks,
        "block_content": block_content,
        "meetings_groups": meetings_groups,
        "events_list": events_list,
        "megamenu_template_partial": megamenu_tpl["partial"],
        "megamenu_template_key": megamenu_tpl["key"],
        "nav_items": nav_items,
        "frontend_title": (site.frontend_title if site else None) or "Trusted Servants",
        "frontend_tagline": (site.frontend_tagline if site else None)
            or "A recovery fellowship portal.",
        "frontend_hero_heading": (site.frontend_hero_heading if site else None)
            or "You are not alone.",
        "frontend_hero_subheading": (site.frontend_hero_subheading if site else None)
            or "Find meetings, connect with your community, and take the next step in your recovery journey.",
        "frontend_about_heading": (site.frontend_about_heading if site else None)
            or "About the Fellowship",
        "frontend_about_body": (site.frontend_about_body if site else None) or "",
        "frontend_contact_heading": (site.frontend_contact_heading if site else None)
            or "Need Help Right Now?",
        "frontend_contact_body": (site.frontend_contact_body if site else None) or "",
        "frontend_footer_text": (site.frontend_footer_text if site else None) or "",
    }


def _frontend_gate(site):
    """Shared gating logic: return None when access is allowed, or a
    response (redirect / 404) when the visitor isn't allowed to see the
    public frontend.

    Module disabled OR frontend_enabled off:
      - signed-in visitors → /tspro dashboard (they're already in;
        bouncing them to login or showing 404 is confusing).
      - anonymous visitors → /tspro login.
    Module on but frontend_enabled off and the visitor IS a frontend
    editor → fall through to render the preview-mode frontend.
    """
    if not site or not site.frontend_module_enabled:
        if current_user.is_authenticated:
            return redirect(url_for("main.index"))
        return redirect(url_for("auth.login"))
    if not site.frontend_enabled:
        if current_user.is_authenticated and current_user.can_edit_frontend():
            return None  # admin/editor preview
        if current_user.is_authenticated:
            return redirect(url_for("main.index"))
        return redirect(url_for("auth.login"))
    return None


def _post_in_archive(post):
    """True when the post is in the unified /archive — either explicitly
    archived OR an event whose end-time has already passed (in case the
    auto-archive sweep hasn't run yet). Detail pages use this to flip
    the back-link to "Archive" instead of the live list."""
    if not post:
        return False
    if post.is_archived:
        return True
    if post.is_event:
        from datetime import datetime
        ref = post.event_ends_at or post.event_starts_at
        if ref and ref < datetime.utcnow():
            return True
    return False


def _post_url(post):
    """Canonical public URL for an event/announcement post. Returns
    ``/archive/<slug>`` for posts that live in the unified archive
    (matches `_post_in_archive`); otherwise the live ``/event/<slug>``
    or ``/announcement/<slug>`` URL. Returns "" when there is no slug
    to route to."""
    if not post:
        return ""
    from .colors import slugify
    slug = getattr(post, "public_slug", None) or slugify(post.title or "")
    if not slug:
        return ""
    if _post_in_archive(post):
        return url_for("frontend.archive_detail", slug=slug)
    if getattr(post, "is_event", False):
        return url_for("frontend.event_detail", slug=slug)
    return url_for("frontend.announcement_detail", slug=slug)


@bp.route("/")
def index():
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    # Preview a handful of the soonest-starting meetings for the homepage.
    meetings = (Meeting.query
                .filter(Meeting.archived_at.is_(None))
                .order_by(Meeting.name)
                .limit(6).all())
    from .models import FrontendHeroButton
    hero_buttons = FrontendHeroButton.query.order_by(FrontendHeroButton.position).all()
    ctx = _frontend_context(site)
    return render_template("frontend/index.html", meetings=meetings,
                           hero_buttons=hero_buttons, **ctx)


@bp.route("/meetings/<slug>")
def meeting_detail(slug):
    """Public meeting detail page — name, description, alert, full
    schedule, location, and Zoom credentials. The slug is the meeting's
    title with any non-alphanumeric run collapsed to a hyphen. If two
    active meetings share the same slug, the lower-id (first-created) one
    wins; admins can rename to disambiguate."""
    from .colors import slugify
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    candidates = (Meeting.query
                  .filter(Meeting.archived_at.is_(None))
                  .order_by(Meeting.id)
                  .all())
    # First-pass match against the entity's *current* effective slug.
    m = next((mt for mt in candidates if mt.public_slug == slug), None)
    if m is None:
        # Stale URL — look up the slug-change history and 301-redirect to
        # the current canonical slug if we can match it. Pinned to active
        # (non-archived) meetings only.
        from .models import EntitySlugHistory
        hist = (EntitySlugHistory.query
                .filter_by(entity_type="meeting", old_slug=slug)
                .order_by(EntitySlugHistory.changed_at.desc())
                .first())
        if hist:
            target = next((mt for mt in candidates if mt.id == hist.entity_id), None)
            if target:
                return redirect(url_for("frontend.meeting_detail",
                                        slug=target.public_slug), code=301)
        abort(404)
    ctx = _frontend_context(site)
    tpl = _template_meta(MEETING_TEMPLATES,
                         (site.frontend_meeting_template if site else None) or "classic")
    tpl_style = template_css_vars(template_settings(site, "meeting", tpl["key"]))
    # Resolve the meeting's free-text location to a saved Location row
    # so the public templates can render the full split address (name /
    # street / city/state/zip on separate lines) instead of a single
    # joined string. Custom locations that don't match any saved row
    # leave `meeting_location_record` as None and the templates fall
    # through to the legacy single-line render.
    location_record = None
    loc_norm = (m.location or "").strip().lower()
    if loc_norm:
        from .models import Location
        for _l in Location.query.all():
            if _l.name and _l.name.strip().lower() == loc_norm:
                location_record = _l
                break
    return render_template(tpl["partial"], meeting=m, tpl_style=tpl_style,
                           meeting_location_record=location_record, **ctx)


@bp.route("/meeting/<slug>", endpoint="meeting_detail_legacy")
def meeting_detail_legacy(slug):
    """Back-compat: 1.7.4 and earlier served meeting detail at
    ``/meeting/<slug>`` (singular). 301-redirect to the canonical
    plural-form URL so existing bookmarks keep working."""
    return redirect(url_for("frontend.meeting_detail", slug=slug), code=301)


@bp.route("/meeting/<slug>/<path:resource>", endpoint="meeting_resource_legacy")
def meeting_resource_legacy(slug, resource):
    """Back-compat alias for the singular pre-1.7.5 file URLs."""
    return redirect(url_for("frontend.meeting_resource",
                            slug=slug, resource=resource), code=301)


@bp.route("/meetings/<slug>/<path:resource>")
def meeting_resource(slug, resource):
    """Resolve a public file or reading attached to a meeting via its
    pretty URL — e.g. ``/meetings/daily-zoom-round-up/opening-statement.pdf``.

    The route looks up the meeting by slug first (same logic as
    ``meeting_detail``), then matches ``resource`` against the meeting's
    public files (``MeetingFile.public_visible=True``) and any
    ``meeting.public_library_items`` by their respective ``url_slug`` properties.
    Files take precedence over readings on slug collision.

    The legacy singular-form ``/meeting/<slug>/<resource>`` URL is wired
    elsewhere as a 301-redirect alias so old bookmarks survive."""
    from flask import send_from_directory, current_app
    from .colors import slugify
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    candidates = (Meeting.query
                  .filter(Meeting.archived_at.is_(None))
                  .order_by(Meeting.id)
                  .all())
    m = next((mt for mt in candidates if mt.public_slug == slug), None)
    if m is None:
        # Old slug — redirect to the current /meetings/<new>/<resource> URL
        # so bookmarked file links keep working after a slug rename.
        from .models import EntitySlugHistory
        hist = (EntitySlugHistory.query
                .filter_by(entity_type="meeting", old_slug=slug)
                .order_by(EntitySlugHistory.changed_at.desc())
                .first())
        if hist:
            target = next((mt for mt in candidates if mt.id == hist.entity_id), None)
            if target:
                return redirect(url_for("frontend.meeting_resource",
                                        slug=target.public_slug,
                                        resource=resource), code=301)
        abort(404)

    # Files first, then readings — first match by url_slug wins.
    for f in m.public_files():
        if f.url_slug == resource:
            if f.category in ("readings", "scripts") and f.body:
                return render_template("reading_view.html", title=f.title,
                                       body=f.body,
                                       back_url=url_for("frontend.meeting_detail", slug=slug))
            if f.url:
                return redirect(f.url)
            if f.stored_filename:
                return send_from_directory(
                    current_app.config["UPLOAD_FOLDER"],
                    f.stored_filename, as_attachment=False,
                    download_name=f.original_filename or f.stored_filename)
            abort(404)

    for r in m.public_library_items:
        if r.url_slug == resource:
            if r.body:
                return render_template("reading_view.html", title=r.title,
                                       body=r.body,
                                       back_url=url_for("frontend.meeting_detail", slug=slug))
            if r.url:
                return redirect(r.url)
            if r.stored_filename:
                return send_from_directory(
                    current_app.config["UPLOAD_FOLDER"],
                    r.stored_filename, as_attachment=False,
                    download_name=r.original_filename or r.stored_filename)
            abort(404)

    abort(404)


@bp.route("/meetings")
def meetings_list():
    """Public list of every active meeting, all info inline. The chosen
    layout (sidebar / directory / weekboard, picked on the admin's
    Templates page and stored on SiteSetting.frontend_meetings_list_template)
    decides how the list is presented; each layout shares the same data —
    every active Meeting eagerly loaded with its schedules — so client-side
    filtering can run without follow-up requests."""
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    ctx = _frontend_context(site)
    # Fetch every active meeting, schedules included, in one round-trip.
    # `joinedload` materializes the schedule list with the parent so each
    # template can iterate `m.schedules` without triggering N+1 queries.
    # Sort by the earliest start time across all of a meeting's schedules
    # so the default (no filter) ordering is "morning meetings first" —
    # the templates re-sort by per-day start time when a day filter is
    # picked client-side. Meetings without any schedules sink to the end.
    from sqlalchemy.orm import joinedload
    meetings = (Meeting.query
                .options(joinedload(Meeting.schedules))
                .filter(Meeting.archived_at.is_(None))
                .all())
    def _earliest_start(m):
        times = [s.start_time for s in m.schedules if s.start_time]
        return (min(times) if times else "99:99", (m.name or "").lower())
    meetings.sort(key=_earliest_start)

    # Build a Mon..Sun bucketed view: each (schedule, meeting) pair sorted
    # chronologically by start time within its day. A meeting that runs on
    # multiple days shows up in each of those buckets so the sidebar layout
    # can render day-grouped sections (Monday's meetings, Tuesday's, etc.).
    _day_labels = ["Monday", "Tuesday", "Wednesday", "Thursday",
                   "Friday", "Saturday", "Sunday"]
    day_buckets = [{"day": i, "label": _day_labels[i], "items": []}
                   for i in range(7)]
    for m in meetings:
        for s in m.schedules:
            if 0 <= s.day_of_week < 7:
                day_buckets[s.day_of_week]["items"].append({"schedule": s, "meeting": m})
    for bucket in day_buckets:
        bucket["items"].sort(key=lambda it: ((it["schedule"].start_time or "99:99"),
                                             (it["meeting"].name or "").lower()))

    # Build a per-meeting search blob attached to every bucket item.
    # Centralises the natural-language tokens (type aliases, full +
    # short day names, 12-hour time strings, bare-hour shortcuts like
    # "7pm", and morning/afternoon/evening/night period buckets) so
    # the client-side live search just splits the query on whitespace
    # and looks for each token as a substring.
    _DAY_FULL = ["monday", "tuesday", "wednesday", "thursday",
                 "friday", "saturday", "sunday"]
    _TYPE_ALIASES = {
        "in_person": ["in person", "in-person", "inperson"],
        "online":    ["online", "zoom", "virtual"],
        "hybrid":    ["hybrid", "online", "zoom", "in person"],
    }
    import re as _re_search
    # Strip set deliberately excludes `:` and `-` so time strings like
    # `7:00` and aliases like `in-person` survive intact. Anything in
    # this character class is replaced with an empty string.
    _PUNCT_STRIP_RE = _re_search.compile(r"[‘’'?!.,;\"“”()\[\]{}]")

    def _build_search_blob(m):
        parts = []
        if m.name:
            parts.append(m.name.lower())
        if m.location:
            parts.append(m.location.lower())
        parts.extend(_TYPE_ALIASES.get(m.meeting_type, []))
        for s in m.schedules:
            if 0 <= (s.day_of_week or 0) < 7:
                full = _DAY_FULL[s.day_of_week]
                parts.append(full)
                parts.append(full[:3])
            if s.start_time:
                try:
                    hh, mm = s.start_time.split(":")
                    h, mn = int(hh), int(mm)
                    h12 = h % 12 if h % 12 != 0 else 12
                    ampm = "am" if h < 12 else "pm"
                    parts.append("%d:%02d %s" % (h12, mn, ampm))
                    if mn == 0:
                        parts.append("%d%s" % (h12, ampm))
                    if h < 5 or h >= 22:
                        parts.append("late night")
                    elif h < 12:
                        parts.append("morning")
                    elif h == 12:
                        parts.append("noon")
                    elif h < 17:
                        parts.append("afternoon")
                    elif h < 21:
                        parts.append("evening")
                    else:
                        parts.append("night")
                except (ValueError, TypeError):
                    pass
        # Concatenate parts then strip text punctuation (apostrophes,
        # question marks, etc.) so a meeting called "What's the T?"
        # matches queries `what's` / `whats` / `what` interchangeably.
        # Time colons + the "in-person" hyphen are intentionally NOT
        # stripped — those are meaningful tokens. The matching strip
        # set in the client-side `tokens()` mirrors this list.
        joined = " ".join(parts)
        return _PUNCT_STRIP_RE.sub("", joined)
    _blobs = {m.id: _build_search_blob(m) for m in meetings}
    for bucket in day_buckets:
        for item in bucket["items"]:
            item["search_blob"] = _blobs.get(item["meeting"].id, "")
    # Display order is Sun → Sat (US calendar convention) even though the
    # underlying day_of_week enum stays 0=Mon..6=Sun. The `day` field on
    # each bucket carries the canonical number so JS day filters keep
    # working regardless of display sequence.
    day_buckets = [day_buckets[6]] + day_buckets[:6]

    # Today's day-of-week in the SITE's configured timezone (not the
    # visitor's browser locale) so the page lands on whatever the
    # fellowship considers "today". Falls back to the system clock when
    # no SiteSetting row exists yet.
    from .timezone import now_in
    current_day = now_in(site).weekday()  # 0=Mon..6=Sun

    tpl = _template_meta(MEETINGS_LIST_TEMPLATES,
                         (site.frontend_meetings_list_template if site else None) or "sidebar")
    width_mode = (site.frontend_meetings_list_width_mode if site else None) or "boxed"
    if width_mode not in ("boxed", "full"):
        width_mode = "boxed"
    try:
        pad_pct = int(site.frontend_meetings_list_padding_pct) if site else 5
    except (TypeError, ValueError):
        pad_pct = 5
    pad_pct = max(0, min(20, pad_pct))
    try:
        max_width = int(site.frontend_meetings_list_max_width) if site else 1160
    except (TypeError, ValueError):
        max_width = 1160
    max_width = max(640, min(2400, max_width))
    list_heading = (site.frontend_meetings_list_heading if site else None) or ""
    list_subheading = (site.frontend_meetings_list_subheading if site else None) or ""
    list_protips = meetings_list_protips_resolved(site)
    return render_template("frontend/meetings_list.html",
                           list_partial=tpl["partial"],
                           list_template_key=tpl["key"],
                           list_width_mode=width_mode,
                           list_max_width=max_width,
                           list_padding_pct=pad_pct,
                           list_current_day=current_day,
                           list_heading=list_heading,
                           list_subheading=list_subheading,
                           list_protips=list_protips,
                           all_meetings=meetings,
                           meetings_by_day=day_buckets,
                           **ctx)


@bp.route("/hyperlist")
def hyperlist():
    """Accessibility-first plain-HTML index of every active meeting.

    Renders WITHOUT the site header, footer, utility bar, or any other
    chrome — visitors with screen readers or visual impairments land on
    a page whose entire content is meeting information, organised under
    one ``<h1>`` and a clean ``<h2>`` per day. The template ships its
    own minimal stylesheet (no frontend.css, no app.css, no JS frameworks)
    so AT users get a single small payload with no animations, no sticky
    overlays, and no third-party fonts to wait on.

    Same data shape as ``meetings_list``: every active meeting, eagerly
    loaded with its schedules, then bucketed Monday → Sunday and sorted
    by start time within each day. The current live meeting (if any) is
    surfaced at the top via a ``role="status"`` region so AT users hear
    the "now meeting" announcement on page load.
    """
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    from sqlalchemy.orm import joinedload
    from .utility_bar import current_live_meeting
    from .timezone import now_in
    from .models import Location
    meetings = (Meeting.query
                .options(joinedload(Meeting.schedules))
                .filter(Meeting.archived_at.is_(None))
                .all())
    # Preload every Location row keyed by normalised name (lowercased,
    # stripped) so the per-meeting address resolution is a single dict
    # lookup. Matches the case-insensitive trimmed-match contract the
    # meeting_detail route uses.
    location_by_name = {}
    for _l in Location.query.all():
        if _l.name:
            location_by_name[_l.name.strip().lower()] = _l
    _day_labels = ["Monday", "Tuesday", "Wednesday", "Thursday",
                   "Friday", "Saturday", "Sunday"]
    day_buckets = [{"day": i, "label": _day_labels[i], "items": []}
                   for i in range(7)]
    for m in meetings:
        loc_norm = (m.location or "").strip().lower()
        loc_rec = location_by_name.get(loc_norm) if loc_norm else None
        for s in m.schedules:
            if 0 <= s.day_of_week < 7:
                day_buckets[s.day_of_week]["items"].append(
                    {"schedule": s, "meeting": m, "location_record": loc_rec})
    for bucket in day_buckets:
        bucket["items"].sort(key=lambda it: ((it["schedule"].start_time or "99:99"),
                                             (it["meeting"].name or "").lower()))
    today_dow = now_in(site).weekday()
    live = current_live_meeting(site)
    return render_template("frontend/hyperlist.html",
                           site=site,
                           meetings_by_day=day_buckets,
                           total_meetings=len(meetings),
                           today_dow=today_dow,
                           live_meeting=live,
                           frontend_title=(site.frontend_title if site else None)
                                          or "Trusted Servants")


@bp.route("/printlist")
@bp.route("/printlist.pdf", endpoint="printlist_pdf")
def printlist():
    """Branded, print-optimized meeting schedule.

    Two endpoints, one render path:
      * ``/printlist``     — the on-screen view; carries Print + Download
                             buttons that the print stylesheet hides.
      * ``/printlist.pdf`` — the same HTML rendered to PDF via WeasyPrint
                             and returned as a download.

    Layout target: 2 letter-sized pages. A two-column flow inside each
    @page brings ~30 meetings into ~2 pages without crowding. Brand
    palette pulls from the active utility-bar bg colour with sensible
    print-friendly fallbacks; logo (if set) lands top-left of the
    header band.
    """
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    from sqlalchemy.orm import joinedload
    from .models import Location
    meetings = (Meeting.query
                .options(joinedload(Meeting.schedules))
                .filter(Meeting.archived_at.is_(None))
                .all())
    location_by_name = {}
    for _l in Location.query.all():
        if _l.name:
            location_by_name[_l.name.strip().lower()] = _l
    _day_labels = ["Monday", "Tuesday", "Wednesday", "Thursday",
                   "Friday", "Saturday", "Sunday"]
    day_buckets = [{"day": i, "label": _day_labels[i], "items": []}
                   for i in range(7)]
    for m in meetings:
        loc_norm = (m.location or "").strip().lower()
        loc_rec = location_by_name.get(loc_norm) if loc_norm else None
        for s in m.schedules:
            if 0 <= s.day_of_week < 7:
                day_buckets[s.day_of_week]["items"].append(
                    {"schedule": s, "meeting": m, "location_record": loc_rec})
    for bucket in day_buckets:
        bucket["items"].sort(key=lambda it: ((it["schedule"].start_time or "99:99"),
                                             (it["meeting"].name or "").lower()))
    # Display order Sun → Sat (US calendar convention). The underlying
    # day_of_week enum stays 0=Mon..6=Sun; we just rotate the buckets
    # so Sunday renders first. Matches the meetings_list ordering.
    day_buckets = [day_buckets[6]] + day_buckets[:6]
    from datetime import datetime
    from .timezone import now_in
    generated_at = now_in(site)
    site_title = (site.frontend_title if site else None) or "Trusted Servants"
    tagline = (site.frontend_tagline if site else None) or ""
    subheading = (site.frontend_printlist_subheading if site else None) or ""
    website = (site.frontend_printlist_website if site else None) or ""
    page_size = (site.frontend_printlist_page_size if site else None) or "letter"
    if page_size not in ("letter", "legal"):
        page_size = "letter"
    is_pdf = request.endpoint == "frontend.printlist_pdf"
    html = render_template("frontend/printlist.html",
                           site=site,
                           meetings_by_day=day_buckets,
                           total_meetings=len(meetings),
                           generated_at=generated_at,
                           frontend_title=site_title,
                           frontend_tagline=tagline,
                           printlist_subheading=subheading,
                           printlist_website=website,
                           printlist_page_size=page_size,
                           is_pdf=is_pdf)
    if not is_pdf:
        return html
    # PDF render path. base_url lets WeasyPrint resolve site-relative
    # URLs in the rendered HTML — the logo at /site-branding/frontend-logo
    # comes through this way, as does the favicon. write_pdf returns
    # raw bytes; we wrap them in a Flask response with the correct
    # Content-Disposition so browsers download instead of inline-rendering.
    from weasyprint import HTML
    from flask import current_app, request as _req
    pdf_bytes = HTML(string=html, base_url=_req.url_root).write_pdf()
    safe_title = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_"
                         for c in site_title).strip() or "meetings"
    filename = f"{safe_title} - Meeting Schedule.pdf"
    resp = current_app.make_response(pdf_bytes)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@bp.route("/library")
def literature_library():
    """Public Literature Library page.

    Every ``Library`` row flagged ``public_visible=True`` becomes a
    section; within each section every ``LibraryItem`` whose
    ``public_visible`` is also True renders as a card with whatever
    surface the item carries (uploaded file, external URL, or
    pasted-body lightbox). Libraries with no surfaceable items after
    the filter are dropped so visitors don't see empty headings.

    Page chrome mirrors ``/archive`` — same sidebar rail with live
    search + filter pills (libraries instead of years), same palette,
    same width admin (boxed/full + max-width + padding pulls from the
    Events list settings). The search blob covers the item title,
    library name, file name, and category tags so a query for
    "anonymity" hits any item whose body or category mentions it.
    """
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    ctx = _frontend_context(site)
    from .models import Library, LibraryItem
    libs = (Library.query
            .filter(Library.public_visible.is_(True))
            .order_by(Library.name)
            .all())
    library_buckets = []
    total_items = 0
    for lib in libs:
        # Library.items is a dynamic relationship — materialise with
        # .all() and apply the per-item public flag in Python so this
        # path doesn't issue a second SELECT per item.
        items = [it for it in lib.items.all() if it.public_visible]
        if not items:
            continue
        library_buckets.append({
            "id": lib.id,
            "name": lib.name,
            "description": lib.description,
            "items": items,
        })
        total_items += len(items)

    # Per-item search blob — covers title, library name, file name,
    # and category tags so a single query hits across surfaces. Same
    # punctuation strip as the meetings sidebar so apostrophes /
    # quotes / commas don't break matches.
    import re as _re_search
    _PUNCT_STRIP_RE = _re_search.compile(r"[‘’'?!.,;\"“”()\[\]{}]")

    def _item_blob(it, lib_name):
        parts = [it.title.lower() if it.title else "", lib_name.lower() if lib_name else ""]
        if it.original_filename:
            parts.append(it.original_filename.lower())
        if it.url:
            parts.append(it.url.lower())
        for c in (it.categories or []):
            parts.append(c.name.lower())
        return _PUNCT_STRIP_RE.sub("", " ".join(p for p in parts if p))

    search_blobs = {}
    for bucket in library_buckets:
        for it in bucket["items"]:
            search_blobs[it.id] = _item_blob(it, bucket["name"])

    # Reuse the events-list width / padding admin settings — same shell
    # as the archive page so the literature library inherits the same
    # horizontal geometry without yet another set of admin controls.
    width_mode = (site.frontend_events_list_width_mode if site else None) or "boxed"
    if width_mode not in ("boxed", "full"):
        width_mode = "boxed"
    try:
        max_width = int(site.frontend_events_list_max_width) if site else 1160
    except (TypeError, ValueError):
        max_width = 1160
    max_width = max(640, min(2400, max_width))
    try:
        pad_pct = int(site.frontend_events_list_padding_pct) if site else 5
    except (TypeError, ValueError):
        pad_pct = 5
    pad_pct = max(0, min(20, pad_pct))

    return render_template("frontend/literature_library.html",
                           list_width_mode=width_mode,
                           list_max_width=max_width,
                           list_padding_pct=pad_pct,
                           library_buckets=library_buckets,
                           total_items=total_items,
                           search_blobs=search_blobs,
                           **ctx)


@bp.route("/events")
def events_list():
    """Public list of every upcoming event. Linked from the homepage
    Upcoming Events block via the "See all events" CTA. Uses the same
    Post query the homepage block does, but with a high cap so visitors
    can browse the full upcoming queue."""
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "posts_enabled", True):
        abort(404)
    ctx = _frontend_context(site)
    from .blocks import filtered_events
    all_events = filtered_events({"max_count": 500}, site=site)
    tpl = _template_meta(EVENTS_LIST_TEMPLATES,
                         (site.frontend_events_list_template if site else None) or "cards")
    width_mode = (site.frontend_events_list_width_mode if site else None) or "boxed"
    if width_mode not in ("boxed", "full"):
        width_mode = "boxed"
    try:
        max_width = int(site.frontend_events_list_max_width) if site else 1160
    except (TypeError, ValueError):
        max_width = 1160
    max_width = max(640, min(2400, max_width))
    try:
        pad_pct = int(site.frontend_events_list_padding_pct) if site else 5
    except (TypeError, ValueError):
        pad_pct = 5
    pad_pct = max(0, min(20, pad_pct))
    list_heading = (site.frontend_events_list_heading if site else None) or ""
    list_subheading = (site.frontend_events_list_subheading if site else None) or ""
    return render_template("frontend/events_list.html",
                           list_partial=tpl["partial"],
                           list_template_key=tpl["key"],
                           list_width_mode=width_mode,
                           list_max_width=max_width,
                           list_padding_pct=pad_pct,
                           list_heading=list_heading,
                           list_subheading=list_subheading,
                           all_events=all_events,
                           **ctx)


@bp.route("/archive")
def archive():
    """Unified public archive of past announcements + events. The rail
    has a search input, type checkboxes (Events / Announcements), and
    year buckets; the main column shows year-grouped cards mixing both
    kinds. Past events = ended OR explicitly archived (auto-sweep
    doesn't always run before a visitor lands). Past announcements =
    explicitly archived. Replaces the older /events/archive +
    /announcements/archive routes — both now 301 here."""
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "posts_enabled", True):
        abort(404)
    ctx = _frontend_context(site)

    from datetime import datetime
    now = datetime.utcnow()

    # Past events: ended OR is_archived. Skip the ones with no date.
    event_rows = (Post.query
                  .filter(Post.is_event.is_(True),
                          Post.is_draft.is_(False))
                  .order_by(Post.event_starts_at.desc().nulls_last())
                  .all())
    past_events = []
    for p in event_rows:
        ref_end = p.event_ends_at or p.event_starts_at
        if ref_end is None:
            continue
        if p.is_archived or ref_end < now:
            past_events.append(p)

    # Archived announcements (excludes anything also tagged is_event so
    # mixed posts only appear once, on the events side).
    ann_rows = (Post.query
                .filter(Post.is_announcement.is_(True),
                        Post.is_event.is_(False),
                        Post.is_archived.is_(True),
                        Post.is_draft.is_(False))
                .order_by(Post.created_at.desc())
                .all())

    # Combined items list: each carries kind + sort_at + year so the
    # template can render the right card partial and the year buckets
    # mix both kinds in date order.
    items = []
    for p in past_events:
        items.append({
            "kind": "event",
            "post": p,
            "sort_at": p.event_starts_at,
            "year": p.event_starts_at.year,
        })
    for p in ann_rows:
        if not p.created_at:
            continue
        items.append({
            "kind": "announcement",
            "post": p,
            "sort_at": p.created_at,
            "year": p.created_at.year,
        })
    items.sort(key=lambda x: x["sort_at"], reverse=True)

    # Year buckets, newest first.
    from collections import OrderedDict
    year_buckets_map = OrderedDict()
    for it in items:
        year_buckets_map.setdefault(it["year"], []).append(it)
    year_buckets = [{"year": y, "items": its}
                    for y, its in year_buckets_map.items()]

    # Per-post search blob — same punctuation strip as the meetings
    # sidebar so apostrophes / quotes / commas don't break matches.
    # Built once per post and keyed by Post.id (unique across both
    # kinds since they share the post table).
    import re as _re_search
    _PUNCT_STRIP_RE = _re_search.compile(r"[‘’'?!.,;\"“”()\[\]{}]")

    def _archive_search_blob(it):
        p = it["post"]
        parts = []
        if p.title:
            parts.append(p.title.lower())
        if p.summary:
            parts.append(p.summary.lower())
        if it["kind"] == "event":
            if p.location_name:
                parts.append(p.location_name.lower())
            if p.is_online:
                parts.extend(["online", "zoom", "virtual"])
        d = it["sort_at"]
        if d:
            parts.append(d.strftime('%B').lower())
            parts.append(d.strftime('%b').lower())
            parts.append(d.strftime('%A').lower())
            parts.append(d.strftime('%a').lower())
            parts.append(str(d.year))
        # Type token so a search for "announcement" or "event" hits.
        parts.append(it["kind"])
        return _PUNCT_STRIP_RE.sub("", " ".join(parts))

    blobs = {it["post"].id: _archive_search_blob(it) for it in items}

    # Type counts for the rail checkboxes.
    counts = {
        "event": sum(1 for it in items if it["kind"] == "event"),
        "announcement": sum(1 for it in items if it["kind"] == "announcement"),
    }

    # Reuse the events-list width / padding admin settings — the archive
    # is the visual successor to /events/archive so it inherits the
    # same horizontal geometry.
    width_mode = (site.frontend_events_list_width_mode if site else None) or "boxed"
    if width_mode not in ("boxed", "full"):
        width_mode = "boxed"
    try:
        max_width = int(site.frontend_events_list_max_width) if site else 1160
    except (TypeError, ValueError):
        max_width = 1160
    max_width = max(640, min(2400, max_width))
    try:
        pad_pct = int(site.frontend_events_list_padding_pct) if site else 5
    except (TypeError, ValueError):
        pad_pct = 5
    pad_pct = max(0, min(20, pad_pct))

    return render_template("frontend/archive.html",
                           list_width_mode=width_mode,
                           list_max_width=max_width,
                           list_padding_pct=pad_pct,
                           archive_items=items,
                           year_buckets=year_buckets,
                           search_blobs=blobs,
                           archive_counts=counts,
                           **ctx)


@bp.route("/events/archive")
def events_archive():
    """Legacy redirect — the events archive merged into /archive. Kept
    as a 301 so external links + the old omni Archive pill don't
    break."""
    return redirect(url_for("frontend.archive"), code=301)


@bp.route("/archive/<slug>")
def archive_detail(slug):
    """Public detail page for archived events + announcements. Posts
    that live in the unified /archive (events that have ended OR posts
    flagged is_archived) get their canonical URL here so the path
    matches what the archive index links to. An active post hit via
    this route 301s to its live URL — keeps a single canonical URL
    per post even if the lifecycle flag flips."""
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "posts_enabled", True):
        abort(404)
    candidates = (Post.query
                  .filter(Post.is_draft.is_(False))
                  .order_by(Post.id)
                  .all())
    candidates = [p for p in candidates if p.is_event or p.is_announcement]
    post = next((p for p in candidates if p.public_slug == slug), None)
    if post is None:
        from .models import EntitySlugHistory
        hist = (EntitySlugHistory.query
                .filter_by(entity_type="post", old_slug=slug)
                .order_by(EntitySlugHistory.changed_at.desc())
                .first())
        if hist:
            target = next((p for p in candidates if p.id == hist.entity_id), None)
            if target:
                return redirect(_post_url(target), code=301)
        abort(404)
    if not _post_in_archive(post):
        return redirect(_post_url(post), code=301)
    ctx = _frontend_context(site)
    tpl = _template_meta(EVENT_TEMPLATES,
                         (site.frontend_event_template if site else None) or "classic")
    tpl_style = template_css_vars(template_settings(site, "event", tpl["key"]))
    return render_template(tpl["partial"], event=post, tpl_style=tpl_style,
                           is_in_archive=True, **ctx)


@bp.route("/announcements")
def announcements_list():
    """Public list of every active announcement. Layout is picked from
    ANNOUNCEMENTS_LIST_TEMPLATES via the admin Templates panel — currently
    a single omni layout (Cards + GSR Summary) with a separate Archive
    pill linking to /announcements/archive."""
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "posts_enabled", True):
        abort(404)
    ctx = _frontend_context(site)

    rows = (Post.query
            .filter(Post.is_announcement.is_(True),
                    Post.is_archived.is_(False),
                    Post.is_draft.is_(False))
            .order_by(Post.created_at.desc())
            .all())

    tpl = _template_meta(ANNOUNCEMENTS_LIST_TEMPLATES,
                         (site.frontend_announcements_list_template if site else None) or "omni")
    width_mode = (site.frontend_announcements_list_width_mode if site else None) or "boxed"
    if width_mode not in ("boxed", "full"):
        width_mode = "boxed"
    try:
        max_width = int(site.frontend_announcements_list_max_width) if site else 1160
    except (TypeError, ValueError):
        max_width = 1160
    max_width = max(640, min(2400, max_width))
    try:
        pad_pct = int(site.frontend_announcements_list_padding_pct) if site else 5
    except (TypeError, ValueError):
        pad_pct = 5
    pad_pct = max(0, min(20, pad_pct))
    list_heading = (site.frontend_announcements_list_heading if site else None) or ""
    list_subheading = (site.frontend_announcements_list_subheading if site else None) or ""

    return render_template("frontend/announcements_list.html",
                           list_partial=tpl["partial"],
                           list_template_key=tpl["key"],
                           list_width_mode=width_mode,
                           list_max_width=max_width,
                           list_padding_pct=pad_pct,
                           list_heading=list_heading,
                           list_subheading=list_subheading,
                           all_announcements=rows,
                           **ctx)


@bp.route("/announcements/archive")
def announcements_archive():
    """Legacy redirect — the announcements archive merged into /archive.
    Kept as a 301 so external links + the old omni Archive pill don't
    break."""
    return redirect(url_for("frontend.archive"), code=301)


@bp.route("/api/search-index")
def api_search_index():
    """JSON feed for the frontend-wide search modal: every active
    meeting + upcoming event flattened into search-blob form. Cached
    one-shot per page load on the client (modal fetches once on first
    open)."""
    from flask import jsonify
    from .search import build_search_index
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    return jsonify({"items": build_search_index(site)})


@bp.route("/event/<slug>")
def event_detail(slug):
    """Public event detail page — featured image, schedule, location,
    online/Zoom info, contact, and full body. The slug is the event
    title with non-alphanumerics collapsed to hyphens. Drafts are not
    viewable. Archived events stay reachable but 301 to
    /archive/<slug> so the canonical URL matches where the post
    surfaces in the unified archive index."""
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "posts_enabled", True):
        abort(404)
    candidates = (Post.query
                  .filter(Post.is_event.is_(True),
                          Post.is_draft.is_(False))
                  .order_by(Post.id)
                  .all())
    ev = next((p for p in candidates if p.public_slug == slug), None)
    if ev is None:
        from .models import EntitySlugHistory
        hist = (EntitySlugHistory.query
                .filter_by(entity_type="post", old_slug=slug)
                .order_by(EntitySlugHistory.changed_at.desc())
                .first())
        if hist:
            target = next((p for p in candidates if p.id == hist.entity_id), None)
            if target:
                return redirect(_post_url(target), code=301)
        abort(404)
    if _post_in_archive(ev):
        return redirect(url_for("frontend.archive_detail",
                                slug=ev.public_slug or slug), code=301)
    ctx = _frontend_context(site)
    tpl = _template_meta(EVENT_TEMPLATES,
                         (site.frontend_event_template if site else None) or "classic")
    tpl_style = template_css_vars(template_settings(site, "event", tpl["key"]))
    return render_template(tpl["partial"], event=ev, tpl_style=tpl_style,
                           is_in_archive=False, **ctx)


@bp.route("/announcement/<slug>")
def announcement_detail(slug):
    """Public announcement detail page. Reuses the EVENT_TEMPLATES
    catalog (classic/poster/minimal/timeline) so the admin's chosen
    detail template renders both pure announcements and events. Pure
    announcements simply have no event_starts_at / location / Zoom —
    the detail templates already gate those panels behind `{% if %}`
    checks so they collapse gracefully."""
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "posts_enabled", True):
        abort(404)
    candidates = (Post.query
                  .filter(Post.is_announcement.is_(True),
                          Post.is_draft.is_(False))
                  .order_by(Post.id)
                  .all())
    ann = next((p for p in candidates if p.public_slug == slug), None)
    if ann is None:
        from .models import EntitySlugHistory
        hist = (EntitySlugHistory.query
                .filter_by(entity_type="post", old_slug=slug)
                .order_by(EntitySlugHistory.changed_at.desc())
                .first())
        if hist:
            target = next((p for p in candidates if p.id == hist.entity_id), None)
            if target:
                return redirect(_post_url(target), code=301)
        abort(404)
    if _post_in_archive(ann):
        return redirect(url_for("frontend.archive_detail",
                                slug=ann.public_slug or slug), code=301)
    ctx = _frontend_context(site)
    tpl = _template_meta(EVENT_TEMPLATES,
                         (site.frontend_event_template if site else None) or "classic")
    tpl_style = template_css_vars(template_settings(site, "event", tpl["key"]))
    # Pass the post in as `event` so the existing event-detail templates
    # (which all reference `event.*`) render unchanged.
    return render_template(tpl["partial"], event=ann, tpl_style=tpl_style,
                           is_in_archive=False, **ctx)
