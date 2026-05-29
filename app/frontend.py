# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public-facing frontend blueprint.

When `SiteSetting.frontend_enabled` is True, requests to the root URL serve
a marketing/content homepage instead of bouncing straight to the login
screen. When the toggle is off, the root URL redirects to the admin login.

Admin pages remain at /tspro/* and the authenticated dashboard is at /tspro/.
"""
import os
from flask import Blueprint, render_template, redirect, url_for, abort, request, current_app
from flask_login import current_user
from .models import SiteSetting, Meeting, FrontendNavItem, Post, Story, BlogPost, BlogCategory, BlogTag

bp = Blueprint("frontend", __name__)


@bp.before_request
def _record_visitor_event():
    """Anonymous visitor-metrics tap. Logs one VisitorEvent row per
    real human page view; logged-in users, bots, asset requests, and
    prefetches are dropped inside the recorder. The recorder is
    fully defensive — any failure is swallowed so a flaky write
    can't break the public site."""
    from . import visitor_metrics
    visitor_metrics.record_visit()


# ---------------------------------------------------------------------------
# Public-section registry.
#
# Every top-level template page on the public site (Home, Meetings,
# Hyperlist, Events, Archive, Announcements, Stories, Blog, Library,
# Print list, Submit form, Contact) registers itself here via the
# ``@public_section`` decorator below. /siteindex's Sections group
# iterates over this registry instead of a hardcoded list — so adding
# a new top-level page is just a matter of adding the decorator to the
# new route, and the sitemap picks it up automatically.
#
# Each entry pairs the route's endpoint with the same gate predicate
# the route itself uses for its 404, so the index never advertises a
# page that would 404.
# ---------------------------------------------------------------------------
_PUBLIC_SECTIONS = []


def public_section(title, gate=None):
    """Mark a frontend route as a top-level public section page.

    The route is auto-included in /siteindex's Sections group. ``gate``
    is a callable ``(site) -> bool`` mirroring the route's own enable
    check (so the index hides pages the route would 404 on). Defaults
    to always-on. Decorate BELOW ``@bp.route`` so the endpoint name
    is already bound by the time we record it.
    """
    def deco(fn):
        _PUBLIC_SECTIONS.append({
            "title": title,
            "endpoint": "frontend." + fn.__name__,
            "gate": gate or (lambda _site: True),
        })
        return fn
    return deco


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
    {
        "key": "modern-dark",
        "name": "Modern Dark",
        "description": "Glassy mission-control header — translucent dark bar that blurs the page behind it, wide logotype, primary nav with full-width mega menus, and a gradient call-to-action pill. Styled by the active theme.",
        "partial": "frontend/headers/themed.html",
    },
    {
        "key": "cyberpunk",
        "name": "Cyberpunk",
        "description": "Neon HUD header — near-black bar with a glowing cyan/magenta underline, monospace uppercase nav, and a sharp neon call-to-action. Styled by the active theme.",
        "partial": "frontend/headers/themed.html",
    },
    {
        "key": "sanctuary",
        "name": "Sanctuary",
        "description": "Warm cream header — soft sand bar with a hairline border, serif logotype, sage-green nav hovers, and a rounded sage call-to-action. Styled by the active theme.",
        "partial": "frontend/headers/themed.html",
    },
    {
        "key": "terminal",
        "name": "Terminal",
        "description": "A TUI status bar — near-black mono header with a phosphor-green underline, monospace nav, and a green command-style call-to-action. Styled by the active theme.",
        "partial": "frontend/headers/themed.html",
    },
    {
        "key": "neobrutal",
        "name": "Neobrutal",
        "description": "A bold neobrutalist bar — flat colour, thick black border, chunky Archivo Black logotype + nav, and a hard-shadowed call-to-action that presses on click. Styled by the active theme.",
        "partial": "frontend/headers/themed.html",
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
     "desc": "Static \"Powered by Trusted Servants Pro\" attribution linking to gettspro.com."},
    {"key": "admin_login",   "name": "Admin login",    "icon": "log-in",
     "desc": "Pill-style link to the admin sign-in page. Authenticated users get redirected straight to the dashboard."},
    {"key": "privacy_links", "name": "Privacy & cookies", "icon": "shield",
     "desc": "Privacy policy link + a \"Cookie settings\" button that re-prompts the cookie banner. Both pieces appear only when the matching feature is configured under Web Frontend → Cookie Compliance."},
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
    {
        "key": "modern-dark",
        "name": "Modern Dark",
        "description": "Full-width glass panel with a soft aurora wash, gradient hairline divider, and chevron-slide links. Styled by the active theme.",
        "partial": "frontend/megamenus/themed.html",
    },
    {
        "key": "cyberpunk",
        "name": "Cyberpunk",
        "description": "Full-width neon panel — near-black with a glowing grid, cyan section rules, and magenta hover states on monospace links. Styled by the active theme.",
        "partial": "frontend/megamenus/themed.html",
    },
    {
        "key": "sanctuary",
        "name": "Sanctuary",
        "description": "Full-width warm cream panel with a soft shadow, sage section rules, and gentle sage hover states. Styled by the active theme.",
        "partial": "frontend/megamenus/themed.html",
    },
    {
        "key": "terminal",
        "name": "Terminal",
        "description": "Full-width near-black panel with a phosphor-green rule, monospace links prefixed like command output, and a green hover state. Styled by the active theme.",
        "partial": "frontend/megamenus/themed.html",
    },
    {
        "key": "neobrutal",
        "name": "Neobrutal",
        "description": "Full-width flat-colour panel with a thick black border + hard offset shadow and chunky links that get a colour-block highlight on hover. Styled by the active theme.",
        "partial": "frontend/megamenus/themed.html",
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
    {
        "key": "modern-dark",
        "name": "Modern Dark",
        "description": "Mission-control aesthetic — deep-indigo canvas, animated aurora glow, film grain, teal→cyan gradient buttons, Fraunces display over Inter. Defaults to dark mode; the light/dark toggle still works. Cascades to every region.",
        "default_mode": "dark",
    },
    {
        "key": "cyberpunk",
        "name": "Cyberpunk",
        "description": "Neon-grid HUD — near-black canvas, scanlines + perspective grid, neon cyan/magenta, sharp zero-radius edges, corner-bracket cards, glitch monospace headings. Defaults to dark mode. Cascades to every region.",
        "default_mode": "dark",
    },
    {
        "key": "sanctuary",
        "name": "Sanctuary",
        "description": "Warm and calm — sand/cream canvas, sage-green + clay accents, Lora humanist-serif headings, soft rounded cards, airy editorial spacing. A grounded, supportive light theme. Defaults to light mode. Cascades to every region.",
        "default_mode": "light",
    },
    {
        "key": "terminal",
        "name": "Terminal",
        "description": "A utilitarian command line — near-black canvas, phosphor-green accents, all-monospace type, flat boxy panels with visible borders, zero radius, prompt-prefixed headings and a blinking cursor. Defaults to dark mode; the light toggle is a clean printout paper. Cascades to every region.",
        "default_mode": "dark",
    },
    {
        "key": "neobrutal",
        "name": "Neobrutal",
        "description": "Neobrutalism — colourful flat surfaces (yellow / pink / cyan), thick black borders, hard offset drop-shadows, chunky Archivo Black headings, and buttons that 'press' on click. Bold, high-contrast, playful. Defaults to light mode; the dark companion keeps the bright blocks on a near-black canvas. Cascades to every region.",
        "default_mode": "light",
    },
]

# Theme key → the visitor light/dark default that best fits the theme.
# `frontend_theme_save` applies this to `SiteSetting.frontend_default_theme`
# so a dark-by-design theme greets first-time visitors in dark mode (the
# visitor's own saved sun/moon choice still wins via localStorage). Themes
# absent from this map leave the admin's existing default untouched.
THEME_DEFAULT_MODE = {t["key"]: t["default_mode"] for t in THEMES if t.get("default_mode")}


# ---------------------------------------------------------------------------
# Per-theme saved state.
#
# Switching themes snapshots the OUTGOING theme's appearance fields into
# SiteSetting.frontend_theme_states_json (keyed by theme), then restores the
# INCOMING theme's saved snapshot — so returning to a theme brings back how it
# was left. A theme with no snapshot yet starts from its built-in defaults.
# The theme switcher modal also exposes an explicit Reset-to-default and
# Return-to-last-state for the active theme.
#
# THEME_STATE_FIELDS is deliberately just the "appearance" fields (design
# tokens, fonts, default mode, per-template settings, mega-menu colours) so a
# snapshot is small and a switch never disturbs CONTENT (pages, blocks, footer
# content all live in their own columns and are untouched).
# ---------------------------------------------------------------------------
THEME_STATE_FIELDS = [
    "frontend_design_json",
    "frontend_fonts_json",
    "frontend_default_theme",
    "frontend_template_settings_json",
    "frontend_mega_bg_color",
    "frontend_mega_text_color",
    "frontend_mega_radius_bl",
    "frontend_mega_radius_br",
    "frontend_mega_bg_dynamic_key",
    "frontend_mega_bg_dynbg_config_json",
    "frontend_mega_bg_dynbg_dark",
    "frontend_mega_bg_color_dark",
    "frontend_mega_text_color_dark",
    "frontend_mega_bg_dynbg_blend",
]


def load_theme_states(site):
    """Parse the per-theme state map; returns {} on missing/invalid JSON."""
    import json as _json
    try:
        return _json.loads(site.frontend_theme_states_json or "{}") or {}
    except (ValueError, TypeError):
        return {}


def save_theme_states(site, states):
    import json as _json
    site.frontend_theme_states_json = _json.dumps(states)


def snapshot_theme_state(site):
    """Capture the current appearance-field values as a dict."""
    return {f: getattr(site, f, None) for f in THEME_STATE_FIELDS}


def apply_theme_state(site, state):
    """Restore a previously-captured snapshot onto the SiteSetting."""
    if not isinstance(state, dict):
        return
    for f in THEME_STATE_FIELDS:
        if f in state:
            setattr(site, f, state[f])


def reset_theme_state(site, theme_key):
    """Clear a theme's customisations back to its built-in defaults: drop the
    override JSON blobs (so the design.py / fonts.py theme defaults take over),
    set the visitor default mode to the theme's preferred one, and restore the
    mega-menu colour columns to their model defaults."""
    site.frontend_design_json = None
    site.frontend_fonts_json = None
    site.frontend_template_settings_json = None
    site.frontend_default_theme = THEME_DEFAULT_MODE.get(theme_key, "system")
    site.frontend_mega_bg_color = "#0B5CFF"
    site.frontend_mega_text_color = "#ffffff"
    site.frontend_mega_radius_bl = 18
    site.frontend_mega_radius_br = 18
    site.frontend_mega_bg_dynamic_key = None
    site.frontend_mega_bg_dynbg_config_json = None
    site.frontend_mega_bg_dynbg_dark = False
    site.frontend_mega_bg_color_dark = None
    site.frontend_mega_text_color_dark = None
    site.frontend_mega_bg_dynbg_blend = 100

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


def meetings_list_sidebar_links_resolved(site):
    """Return the admin-curated custom links rendered in the Sidebar
    template's day-filter rail. Each link is normalised to:
       {label, url, link_type: "internal"|"external", open_in_new_tab}
    Empty / missing JSON returns an empty list — the public template
    skips the divider + section entirely when the list is empty."""
    import json as _json
    raw = (site.frontend_meetings_list_sidebar_links_json
           if site and site.frontend_meetings_list_sidebar_links_json else None)
    if not raw:
        return []
    try:
        items_raw = _json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(items_raw, list):
        return []
    out = []
    for raw_item in items_raw:
        if not isinstance(raw_item, dict):
            continue
        label = (raw_item.get("label") or "").strip()
        url = (raw_item.get("url") or "").strip()
        if not (label and url):
            continue
        link_type = (raw_item.get("link_type") or "internal").strip().lower()
        if link_type not in ("internal", "external"):
            link_type = "internal"
        out.append({
            "label":            label[:200],
            "url":              url[:600],
            "link_type":        link_type,
            "open_in_new_tab":  bool(raw_item.get("open_in_new_tab")),
        })
    return out


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


# Layouts for the public /archive page (unified past events + archived
# announcements). Each partial reads the same `archive_items` /
# `year_buckets` / `search_blobs` / `archive_counts` set the route
# emits, and each lays down the same data-attribute hooks
# (data-archive-rail, data-archive-search, data-archive-kind-toggle,
# data-archive-filter, data-archive-results, data-archive-year-section,
# data-archive-load-sentinel, data-archive-pagination) so the shared
# filter + pagination JS in archive.html works across every variant.
ARCHIVE_TEMPLATES = [
    {
        "key": "year-sidebar",
        "name": "Year Sidebar",
        "description": "Sticky filter rail on the left — live search, type checkboxes, year pills — paired with a card stack on the right grouped under year headings. Matches the sidebar chrome of the /meetings list. Best when visitors want to drill in by year.",
        "partial": "frontend/archive/year_sidebar.html",
    },
    {
        "key": "timeline",
        "name": "Timeline",
        "description": "Vertical timeline with a central spine; cards alternate left/right, with each year stamped as a marker along the spine. Compact filter strip at the top instead of a rail. Editorial, chronological feel.",
        "partial": "frontend/archive/timeline.html",
    },
    {
        "key": "compact-list",
        "name": "Compact List",
        "description": "Dense single-column list — one row per item with a date block, type chip, title and short summary inline. No thumbnails. Top filter strip with search + type chips + year pills. Best for fellowships with many archived items.",
        "partial": "frontend/archive/compact_list.html",
    },
    {
        "key": "magazine",
        "name": "Magazine",
        "description": "Newest item as a hero card with cover image, then remaining items as a 3-up grid of editorial cards. Top filter strip with search + type chips + year pills. Pulls the eye to the latest archived item.",
        "partial": "frontend/archive/magazine.html",
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


# Layouts for the public /fellowships page (the curated peer-fellowship
# index admins manage from Settings → Global). Each layout shares the
# same `fellowships` payload + `sort_options` + `country_buckets` set,
# so a new layout can be added by dropping a partial into
# frontend/fellowships/ and appending an entry here.
FELLOWSHIPS_LIST_TEMPLATES = [
    {
        "key": "sidebar",
        "name": "Sidebar",
        "description": "Sticky filter rail on the left (live search + Virtual/Regional toggle + per-country pills + sort selector) over a grouped card stack on the right. Default layout — mirrors the chrome of the Archive + Library pages.",
        "partial": "frontend/fellowships/sidebar.html",
    },
    {
        "key": "compact",
        "name": "Compact list",
        "description": "Top filter strip (search + chips + sort) over a dense single-column list — one row per fellowship with the country/region inline and the website link at the right edge. Best for sites with a long roster.",
        "partial": "frontend/fellowships/compact.html",
    },
]


# Layouts for the public /submissionform page (visitor-facing form that
# captures event / announcement submissions for admin review). Every
# variant shares the same shared form-body partial
# `frontend/_submission_form_body.html` and reads the same heading /
# subheading / intro strings off SiteSetting. Adding a new layout is one
# partial + one entry in this list.
SUBMISSION_FORM_TEMPLATES = [
    {
        "key": "classic",
        "name": "Classic",
        "description": "Centered single-column page with a heading, subheading, and a soft-shadowed card containing the form. Matches the look the submission form shipped with — safe default.",
        "partial": "frontend/submission/classic.html",
    },
    {
        "key": "minimal",
        "name": "Minimal",
        "description": "Borderless, no card chrome. Serif heading on a thin rule, the subheading + intro flow into the body, and the form fields sit directly on the page. Maximum focus on the writing.",
        "partial": "frontend/submission/minimal.html",
    },
    {
        "key": "split",
        "name": "Split",
        "description": "Two-column layout on desktop: the heading, subheading, and intro markdown sit on the left as a sticky rail; the form card stacks to the right. Collapses to a single column on narrow viewports.",
        "partial": "frontend/submission/split.html",
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


# Layouts for the public /stories LIST page (every published recovery
# story). Each layout shares the same `all_stories` list and applies a
# distinct visual treatment — paper-textured stacks, magazine grids,
# minimal type, etc. Drop a partial in frontend/stories_list/ and append
# an entry here to add a new option.
# Site Index — auto-populated /siteindex page that lists every public
# surface on the site. Two layout variants today; each is a self-
# contained partial under frontend/site_index/.
SITE_INDEX_TEMPLATES = [
    {
        "key": "grouped",
        "name": "Grouped",
        "description": "Sections by content type (Pages, Meetings, Events, Announcements, Stories, Library), each headed by a small eyebrow with a count chip. Cards within each group land alphabetically. The default — best when the site has a wide mix of content kinds.",
        "partial": "frontend/site_index/grouped.html",
    },
    {
        "key": "alphabet",
        "name": "Alphabet",
        "description": "Single A-Z list — every page from every kind merged into one alphabetical column with a tiny type-chip on each row. Best for sites that want a clean, table-of-contents feel without grouping.",
        "partial": "frontend/site_index/alphabet.html",
    },
]


STORIES_LIST_TEMPLATES = [
    {
        "key": "paper-stack",
        "name": "Paper Stack",
        "description": "Each story rendered as a creased index-card on a warm paper backdrop. Featured-image thumb on the left, serif title + byline + summary on the right. Soft drop shadow + subtle edge-fray for an organic, archive-of-letters feel.",
        "partial": "frontend/stories_list/paper-stack.html",
    },
    {
        "key": "ledger",
        "name": "Ledger",
        "description": "Hand-bound ledger book aesthetic — ruled cream paper sheet with each story as a numbered entry. Marginalia-style date block on the left, serif title + summary inline, hairline rules between rows. No images.",
        "partial": "frontend/stories_list/ledger.html",
    },
    {
        "key": "manuscript",
        "name": "Manuscript",
        "description": "Single column on textured cream stock with a drop-cap initial on each story preview, italic byline, and a small thumbnail floated right. Reads like a literary anthology table-of-contents.",
        "partial": "frontend/stories_list/manuscript.html",
    },
    {
        "key": "broadsheet",
        "name": "Broadsheet",
        "description": "Two-column newspaper-broadsheet layout on aged newsprint. Big serif headlines, small caps bylines, hairline column rule, and a hero story spanning the top. Optional featured image as a halftone-style thumbnail.",
        "partial": "frontend/stories_list/broadsheet.html",
    },
    {
        "key": "minimal-serif",
        "name": "Minimal Serif",
        "description": "Centered, generous white space, big serif titles stacked with fine-print bylines underneath. No images, no cards — just titles + summaries flowing down the page like a literary index.",
        "partial": "frontend/stories_list/minimal-serif.html",
    },
    {
        "key": "magazine",
        "name": "Magazine",
        "description": "Featured story as a hero with cover image; remaining stories as a 3-up grid of illustrated cards. Serif headlines, sans-serif bylines, modern editorial polish.",
        "partial": "frontend/stories_list/magazine.html",
    },
]


# Layouts for the public /blog index page. Selected via
# SiteSetting.frontend_blog_list_template; each maps to a partial in
# frontend/blog_list/<key>.html. Every layout receives the same set
# of variables so admins can switch between them freely.
BLOG_LIST_TEMPLATES = [
    {
        "key": "magazine",
        "name": "Magazine",
        "description": "Featured/newest post as a hero with cover image; remaining posts as a 3-up grid of editorial cards. Modern, polished, well-suited as a default editorial homepage.",
        "partial": "frontend/blog_list/magazine.html",
    },
    {
        "key": "cards",
        "name": "Cards",
        "description": "Uniform 3-up grid of editorial cards. No hero — every post gets equal visual weight. Modern, balanced, easy to skim.",
        "partial": "frontend/blog_list/cards.html",
    },
    {
        "key": "minimal",
        "name": "Minimal",
        "description": "Single-column, generous white space, image-light. Title + summary + meta line per entry. Reads like a personal journal index.",
        "partial": "frontend/blog_list/minimal.html",
    },
    {
        "key": "gazette",
        "name": "Gazette",
        "description": "Newspaper broadsheet aesthetic on aged newsprint. Big serif headlines, hairline column rules, masthead at top. Hero spans the top, three columns below. Image-light, text-forward.",
        "partial": "frontend/blog_list/gazette.html",
    },
    {
        "key": "mosaic",
        "name": "Mosaic",
        "description": "Masonry-style CSS-columns grid with mixed card heights, dense and image-forward. Tags surfaced as chips, gradient title. Modern, dynamic, lots of personality.",
        "partial": "frontend/blog_list/mosaic.html",
    },
    {
        "key": "sidebar",
        "name": "Sidebar",
        "description": "Main column of post cards on the left, sticky right-hand sidebar with categories + tag cloud. Classic blog architecture — best when you want filters always visible.",
        "partial": "frontend/blog_list/sidebar.html",
    },
]


# Layouts for the public /blog/<slug> DETAIL page. Each renders the
# same `post` row but emphasises a different reading experience.
BLOG_POST_TEMPLATES = [
    {
        "key": "modern",
        "name": "Modern",
        "description": "Centered post with a hero image, sans-serif title, drop-cap-free body, and an author card at the bottom. Modern editorial polish suitable for most posts.",
        "partial": "frontend/blog/modern.html",
    },
    {
        "key": "longform",
        "name": "Longform",
        "description": "Medium / Substack-style essay treatment. Centered serif body, narrow column, drop-cap on the opening paragraph, italicised dropped header. Designed for reading, not skimming.",
        "partial": "frontend/blog/longform.html",
    },
    {
        "key": "classic",
        "name": "Classic",
        "description": "Main content + sticky right-hand sidebar with related posts, categories. Resembles WordPress / Ghost defaults — familiar, navigation-heavy.",
        "partial": "frontend/blog/classic.html",
    },
    {
        "key": "cover",
        "name": "Cover",
        "description": "Full-bleed featured image with the title overlaid in a parallax-style hero. Below the fold: two-column body + sticky author card. Editorial flagship treatment for marquee posts.",
        "partial": "frontend/blog/cover.html",
    },
]


# Layouts for the public /stories/<slug> DETAIL page (a single recovery
# story). Each template renders the same `story` row but emphasises a
# different reading experience.
STORY_TEMPLATES = [
    {
        "key": "paper",
        "name": "Paper",
        "description": "Classic creased-paper sheet on a warm backdrop — serif title, byline italicised, drop-cap on the opening paragraph, and small wavy rule between the body and the author's note. Featured image rendered as a tipped-in plate above the title.",
        "partial": "frontend/stories/paper.html",
    },
    {
        "key": "letter",
        "name": "Letter",
        "description": "Reads like a hand-typed letter on textured stock — typewriter / serif title, an italic 'Dear reader,' opener line, the story body, and the author's signature byline at the bottom. No featured image; the focus is the writing.",
        "partial": "frontend/stories/letter.html",
    },
    {
        "key": "journal",
        "name": "Journal",
        "description": "Ruled-paper journal page with a margin date stamp on the left. Big serif title, ruled body lines, the sobriety date hand-stamped at the top, and a soft pencil-shading edge to the page.",
        "partial": "frontend/stories/journal.html",
    },
    {
        "key": "anthology",
        "name": "Anthology",
        "description": "Literary anthology layout — a small eyebrow line ('A Recovery Story · 2025'), a centered serif title, a thin rule, italic byline, and a single column of body copy. No image. Maximum focus on the story.",
        "partial": "frontend/stories/anthology.html",
    },
    {
        "key": "magazine",
        "name": "Magazine",
        "description": "Full-bleed featured image with the title overlaid, then a two-column reading layout below — body copy on the left, a sticky author card on the right with the byline, dates, and bio. Modern editorial chrome.",
        "partial": "frontend/stories/magazine.html",
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
    defaults = {"bg": "", "bg_dark": "", "bg_dark_mode": "same",
                "heading_font": "", "body_font": "",
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
    if isinstance(leaf.get("bg_dark"), str) and _HEX_RE_TPL.match(leaf["bg_dark"]):
        out["bg_dark"] = leaf["bg_dark"]
    if leaf.get("bg_dark_mode") in ("same", "auto", "manual"):
        out["bg_dark_mode"] = leaf["bg_dark_mode"]
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
    # Pass through every dynbg-related leaf key so the admin's
    # customize panel and the public-render shell can both read what
    # was saved. Earlier the function silently dropped these keys
    # (returning only the bg/font/size five), which made every save
    # via the new customize panel appear to "not stick" — the picker
    # opened the next time with an empty current value because
    # `settings.get('bg_dynamic_key')` always returned None even
    # after the JSON had recorded `aurora-blobs`.
    for k in ("bg_dynamic_key", "bg_dynbg_overlay", "bg_dynbg_colors",
              "bg_dynbg_overlay_scope", "bg_dynbg_overlay_size",
              "bg_dynbg_overlay_intensity", "bg_dynbg_randomize_colors",
              "bg_dynbg_randomize_positions", "bg_dynbg_animate",
              "bg_dynbg_pastel_light", "bg_dynbg_knobs",
              # Classic blog detail rail toggles — present only when
              # explicitly disabled, so a missing key means "show".
              "show_related_widget", "show_categories_widget",
              # Card body preview controls (announcements + events list
              # templates). Missing keys fall through to the per-list
              # default in the partial.
              "card_body_mode", "card_body_max_chars"):
        if k in leaf:
            out[k] = leaf[k]
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
    from .design import derive_dark_color
    parts = []
    bg = settings.get("bg")
    if bg:
        parts.append(f"--tpl-bg: {bg};")
        # Dark-mode variant. `bg_dark_mode` is 'same' (no override),
        # 'auto' (use the Design "Surface — Darkmode" token so the
        # template tracks the admin's site palette), or 'manual' (use
        # the admin-provided `bg_dark` hex; fall back to the token if
        # blank). Emitted as `--tpl-bg-dark`; the global rule under
        # `html[data-theme="dark"] [style*="--tpl-bg-dark"]` swaps
        # `--tpl-bg` to it so every consumer of the variable picks up
        # the dark colour automatically.
        bg_dm_mode = (settings.get("bg_dark_mode") or "same").strip()
        bg_dark_val = None
        if bg_dm_mode == "auto":
            bg_dark_val = "var(--fe-color-surface-dark)"
        elif bg_dm_mode == "manual":
            manual = (settings.get("bg_dark") or "").strip()
            bg_dark_val = manual or "var(--fe-color-surface-dark)"
        if bg_dark_val:
            parts.append(f"--tpl-bg-dark: {bg_dark_val};")
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


def _accept_matches(rule, file_storage):
    """Check whether an uploaded ``FileStorage`` satisfies an HTML5
    ``accept``-style rule (comma-separated list of extensions and / or
    MIME types). Mirrors the client-side behaviour built into the
    file picker so a tampered POST can't bypass the field's type
    restriction.

    Each token in ``rule`` is one of:

      • ``.ext`` — case-insensitive extension match against the
        uploaded filename's tail.
      • ``image/*`` — wildcard MIME-type match by main type.
      • ``application/pdf`` — exact MIME-type match.

    Empty rule string skips validation (anything goes). Returns True
    when *any* token in the rule matches the uploaded file.
    """
    if not rule:
        return True
    fname = (getattr(file_storage, "filename", None) or "").strip().lower()
    mime = (getattr(file_storage, "mimetype", None) or "").strip().lower()
    ext = ""
    if "." in fname:
        ext = "." + fname.rsplit(".", 1)[-1]
    for token in rule.split(","):
        token = token.strip().lower()
        if not token:
            continue
        if token.startswith("."):
            if ext == token:
                return True
        elif token.endswith("/*"):
            main = token[:-2]
            if main and mime.startswith(main + "/"):
                return True
        elif "/" in token:
            if mime == token:
                return True
        else:
            # Bare token without leading dot — treat as extension
            # for forgiving admin input (e.g. ``pdf`` vs ``.pdf``).
            if ext == "." + token:
                return True
    return False


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


@bp.context_processor
def _inject_popups():
    """Surface every enabled popup to all public-frontend templates so the
    site-wide ``frontend/_popups.html`` partial (included in
    ``frontend/base.html``) can render them. Cheap query against a small
    table; failures degrade to no popups rather than 500ing the page."""
    try:
        from .models import Popup
        popups = (Popup.query
                  .filter_by(is_enabled=True)
                  .order_by(Popup.id)
                  .all())
    except Exception:
        popups = []
    return {"popups": popups}


@bp.context_processor
def _inject_cookie_compliance():
    """Resolve the cookie-compliance state for the current visitor and
    surface it to every frontend template (the banner partial pulls
    from this). When the module is off, the resolved dict carries
    `enabled: False` and the partial renders nothing. Region inference
    runs per-request — never cached and never persisted."""
    try:
        from .models import SiteSetting, Page
        from . import cookie_compliance as cc
        site = SiteSetting.query.first()
        if not site or not getattr(site, "cookie_compliance_enabled", False):
            return {"cookie_compliance": {"enabled": False}}
        configured = getattr(site, "cookie_compliance_mode", "notice") or "notice"
        if getattr(site, "cookie_compliance_auto_region", True):
            effective = cc.infer_visitor_mode(request.headers, configured)
        else:
            effective = configured
        # Policy URL — internal Page wins over external URL when both set.
        policy_url = None
        if getattr(site, "cookie_compliance_policy_page_id", None):
            page = Page.query.get(site.cookie_compliance_policy_page_id)
            if page and page.is_published and not page.is_private:
                policy_url = "/" + page.slug
        if not policy_url and getattr(site, "cookie_compliance_policy_external_url", None):
            policy_url = site.cookie_compliance_policy_external_url
        return {"cookie_compliance": {
            "enabled": True,
            "mode": effective,
            "configured_mode": configured,
            "auto_region": getattr(site, "cookie_compliance_auto_region", True),
            "position": getattr(site, "cookie_compliance_position", "bottom-bar") or "bottom-bar",
            "title": getattr(site, "cookie_compliance_title", None) or "We use cookies",
            "body": getattr(site, "cookie_compliance_body", None) or (
                "This site uses cookies to function. With your permission "
                "we also use cookies to understand how the site is used."),
            "accept_label": getattr(site, "cookie_compliance_accept_label", None) or "Accept",
            "reject_label": getattr(site, "cookie_compliance_reject_label", None) or (
                "Reject non-essential" if effective != "notice" else ""),
            "more_label": getattr(site, "cookie_compliance_more_label", None) or "Privacy policy",
            "policy_url": policy_url,
            "remember_days": getattr(site, "cookie_compliance_remember_days", None) or 365,
        }}
    except Exception:
        return {"cookie_compliance": {"enabled": False}}


def _page_og(site, title=None, description=None, image_url=None):
    """Build the per-page Open Graph override context consumed by
    ``frontend/base.html``. Any arg left None / empty falls back to the
    site-wide ``frontend_og_*`` defaults set under Branding & SEO.

    Returns a dict ready to splat into ``render_template``::

        return render_template(..., **_page_og(site, title=m.title,
                                               image_url=...), **ctx)

    Callers pass an absolute URL for ``image_url`` (use ``_external=True``
    on ``url_for``) — crawlers like Slack / iMessage / Facebook reject
    relative paths and skip the preview when only a relative URL is
    advertised.

    ``description`` is collapsed to a single line and clipped to 280
    characters (a hair above Twitter's classic 200-char description
    sweet spot, comfortably under Facebook's 300-char hard ceiling).
    HTML / Markdown is stripped via the project's `safe_html` filter
    upstream of this call (callers may pass `.body` directly when they
    only have one content column to draw from — the clip below handles
    the unwrap)."""
    desc = (description or "").strip()
    if desc:
        # Collapse all whitespace runs to single spaces and drop
        # anything that looks like a leftover HTML tag — `summary`
        # columns are plain text but `body` columns may be Markdown
        # with embedded HTML and would otherwise emit angle-bracket
        # garbage to the link preview.
        import re as _re
        desc = _re.sub(r"<[^>]+>", " ", desc)
        desc = _re.sub(r"\s+", " ", desc).strip()
        if len(desc) > 280:
            desc = desc[:277].rstrip() + "…"
    return {
        "page_og_title": (title or "").strip() or None,
        "page_og_description": desc or None,
        "page_og_image_url": (image_url or "").strip() or None,
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
    the back-link to "Archive" instead of the live list.

    ``event_ends_at`` is stored naive site-local (parsed from the HTML5
    ``datetime-local`` input the admin types into), so "has it passed?"
    must compare against site-local now, not UTC — otherwise an event
    ending at 7 pm Pacific would look "passed" any time after 11 am UTC
    that day."""
    if not post:
        return False
    if post.is_archived:
        return True
    if post.is_event:
        from .timezone import now_local_naive
        from .models import SiteSetting
        ref = post.event_ends_at or post.event_starts_at
        if ref and ref < now_local_naive(SiteSetting.query.first()):
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


def _render_page(page, site, *, sections=None, preview=False, unsaved=False):
    """Single render path for a Page → ``frontend/page.html``.

    Used by the homepage (``index``), the public ``page_detail``, and the
    editor preview. When ``sections`` is None the page's saved
    ``blocks_json`` is parsed; the preview route passes its own
    ``sections`` (the unsaved editor blocks) and ``preview=True`` so the
    template shows the preview banner. Page-level settings (background,
    layout, SEO) always come from the saved row.
    """
    import json as _json
    if sections is None:
        sections = []
        if page.blocks_json:
            try:
                sections = _json.loads(page.blocks_json)
            except (ValueError, TypeError):
                sections = []
    toc_items = _collect_page_headings(sections)
    has_lottie = _sections_have_block_type(sections, "lottie")
    # Per-block data hydration (meetings / events) keyed by block id, so
    # the data-driven blocks stay live in the preview too.
    from .blocks import filtered_meetings, filtered_events
    pp_meetings_groups_by_id = {}
    pp_events_list_by_id = {}

    def _hydrate(blocks):
        for b in (blocks or []):
            if not isinstance(b, dict):
                continue
            bid = b.get("id") or ""
            t = b.get("type")
            d = b.get("data") or {}
            if t == "meetings" and bid:
                pp_meetings_groups_by_id[bid] = filtered_meetings(d)
            elif t == "events" and bid:
                pp_events_list_by_id[bid] = filtered_events(d, site=site)
            elif t == "container":
                _hydrate((d or {}).get("blocks") or [])
    for _sec in (sections or []):
        if isinstance(_sec, dict):
            _hydrate(_sec.get("blocks") or [])
    og = _page_og(site, title=page.og_title or page.title,
                  description=page.og_description,
                  image_url=(url_for("public.public_page_og_image", page_id=page.id, _external=True)
                             if page.og_image_filename else None))
    return render_template("frontend/page.html", page=page,
                           sections=sections, toc_items=toc_items,
                           has_lottie=has_lottie,
                           pp_meetings_groups_by_id=pp_meetings_groups_by_id,
                           pp_events_list_by_id=pp_events_list_by_id,
                           preview_mode=preview,
                           preview_unsaved=unsaved,
                           **og,
                           **_frontend_context(site))


@bp.route("/")
@public_section("Home")
def index():
    """Public `/` — renders whichever Page the admin designated as the
    homepage (`SiteSetting.homepage_page_id`). The auto-seed in
    `app/__init__.py::_seed_homepage_page` guarantees this column is
    populated on every install, so the legacy fallback (placeholder
    page when no homepage is set) should never fire in practice — it
    exists only to keep `/` 200-OK during the brief window before the
    seed runs on a fresh install.

    Reuses the same render pipeline as `page_detail` so the homepage
    is just a Page like any other (toolbar, blocks_json, layout
    presets, design-token vars, dynamic-bg picker, etc.). The Pages
    admin's "Make Homepage" action repoints this column to any other
    Page row.
    """
    import json as _json
    from .models import Page
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    page_id = site.homepage_page_id if site else None
    page = Page.query.get(page_id) if page_id else None
    if page is None:
        # No homepage configured (the seed hasn't run yet, the admin
        # cleared the column, or the page got hard-deleted before the
        # SET NULL FK could engage). Render a minimal placeholder so
        # the public root still serves something — the admin sees a
        # "no homepage" banner and is directed at the Pages admin.
        return render_template("frontend/page.html",
                               page=None, sections=[],
                               toc_items=[], has_lottie=False,
                               pp_meetings_groups_by_id={},
                               pp_events_list_by_id={},
                               homepage_missing=True,
                               **_frontend_context(site))
    return _render_page(page, site)


@bp.route("/meetings/<slug>")
def meeting_detail(slug):
    """Public meeting detail page — name, description, alert, full
    schedule, location, and Zoom credentials. The slug is the meeting's
    title with any non-alphanumeric run collapsed to a hyphen. If two
    active meetings share the same slug, the lower-id (first-created) one
    wins; admins can rename to disambiguate."""
    from .colors import slugify
    from .routes import _expire_meeting_alerts, _apply_meeting_schedule_changes
    _expire_meeting_alerts()
    _apply_meeting_schedule_changes()
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
    _tpl_settings = template_settings(site, "meeting", tpl["key"])
    tpl_style = template_css_vars(_tpl_settings)
    tpl_dynbg_key = _tpl_settings.get("bg_dynamic_key")
    tpl_dynbg_overlay = _tpl_settings.get("bg_dynbg_overlay")
    tpl_dynbg_colors = _tpl_settings.get("bg_dynbg_colors") or []
    # Full per-template dynbg config — carries the randomize
    # flags / scope / noise knobs / animate state alongside the
    # base key + overlay + palette so each entity-detail partial
    # has every dimension the apply-partial expects. Earlier
    # only key/overlay/colors were threaded through, so the
    # randomize / freeze-movement settings persisted in JSON
    # but never applied on the public render.
    tpl_dynbg_config = {
        "overlay": tpl_dynbg_overlay,
        "colors": tpl_dynbg_colors,
        "overlay_scope": _tpl_settings.get("bg_dynbg_overlay_scope"),
        "overlay_size": _tpl_settings.get("bg_dynbg_overlay_size"),
        "overlay_intensity": _tpl_settings.get("bg_dynbg_overlay_intensity"),
        "randomize_colors": _tpl_settings.get("bg_dynbg_randomize_colors", False),
        "randomize_positions": _tpl_settings.get("bg_dynbg_randomize_positions", False),
        "animate": _tpl_settings.get("bg_dynbg_animate", True),

        "pastel_light": _tpl_settings.get("bg_dynbg_pastel_light", False),
        "knobs": _tpl_settings.get("bg_dynbg_knobs", {}),
    }
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
    og = _page_og(site, title=m.name, description=m.description,
                  image_url=(url_for("public.public_meeting_logo", mid=m.id, _external=True)
                             if m.logo_filename else None))
    return render_template(tpl["partial"], meeting=m, tpl_style=tpl_style, tpl_dynbg_key=tpl_dynbg_key, tpl_dynbg_overlay=tpl_dynbg_overlay, tpl_dynbg_colors=tpl_dynbg_colors, tpl_dynbg_config=tpl_dynbg_config,
                           meeting_location_record=location_record, **og, **ctx)


@bp.route("/meetings/<slug>/calendar.ics")
def meeting_calendar_ics(slug):
    """One-tap "Add to Calendar" download for a meeting. Serves an
    RFC-5545 VCALENDAR with one weekly-recurring VEVENT per
    ``MeetingSchedule`` row. Same slug-resolution logic as
    ``meeting_detail`` (current slug → history → 404)."""
    from .colors import slugify  # noqa: F401  — keeps parity w/ detail route
    from .calendar_export import meeting_to_ics
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
        from .models import EntitySlugHistory
        hist = (EntitySlugHistory.query
                .filter_by(entity_type="meeting", old_slug=slug)
                .order_by(EntitySlugHistory.changed_at.desc())
                .first())
        if hist:
            target = next((mt for mt in candidates if mt.id == hist.entity_id), None)
            if target:
                return redirect(url_for("frontend.meeting_calendar_ics",
                                        slug=target.public_slug), code=301)
        abort(404)
    base = request.url_root or ""
    body = meeting_to_ics(m, site, base_url=base)
    # Filename derived from the slug so users see e.g. "tuesday-night.ics"
    # in their download tray instead of a generic "calendar.ics".
    fname = (m.public_slug or "meeting") + ".ics"
    # `mimetype="text/calendar"` lets Flask append a single `charset=utf-8`;
    # passing the charset in the mimetype string would double it.
    resp = current_app.response_class(body, mimetype="text/calendar")
    resp.headers["Content-Disposition"] = 'attachment; filename="' + fname + '"'
    # Don't cache — admins editing schedules expect the next download
    # to reflect the change immediately.
    resp.headers["Cache-Control"] = "no-store"
    return resp


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
@public_section("Meetings")
def meetings_list():
    """Public list of every active meeting, all info inline. The chosen
    layout (sidebar / directory / weekboard, picked on the admin's
    Templates page and stored on SiteSetting.frontend_meetings_list_template)
    decides how the list is presented; each layout shares the same data —
    every active Meeting eagerly loaded with its schedules — so client-side
    filtering can run without follow-up requests."""
    from .routes import _expire_meeting_alerts, _apply_meeting_schedule_changes
    _expire_meeting_alerts()
    _apply_meeting_schedule_changes()
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

    # Resolve each meeting's free-text location string against the saved
    # Location rows so the card can render a full split address (name +
    # street + city/state/zip) in the actions column for in-person /
    # hybrid meetings — same case-insensitive trimmed match the public
    # meeting-detail route uses, just batched across the whole list to
    # stay one DB round-trip. Custom locations that don't match any
    # saved row are absent from the dict; the template falls back to
    # the bare `m.location` string in that case.
    from .models import Location
    _loc_by_norm = {}
    for _l in Location.query.all():
        if _l.name:
            _loc_by_norm[_l.name.strip().lower()] = _l
    location_records = {}
    for m in meetings:
        if m.meeting_type in ("in_person", "hybrid") and m.location:
            rec = _loc_by_norm.get((m.location or "").strip().lower())
            if rec is not None:
                location_records[m.id] = rec
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
    list_sidebar_links = meetings_list_sidebar_links_resolved(site)
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
                           list_sidebar_links=list_sidebar_links,
                           all_meetings=meetings,
                           meetings_by_day=day_buckets,
                           meeting_locations=location_records,
                           **ctx)


@bp.route("/hyperlist")
@public_section("Hyperlist")
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
    # Rotate the bucket list so the week reads Sunday → Saturday.
    # `day_of_week` on the schedule rows stays the same 0=Mon..6=Sun
    # enum used everywhere else; we only reorder the rendered
    # sections. Matches the meetings_list ordering.
    day_buckets = [day_buckets[6]] + day_buckets[:6]
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


@bp.route("/storyform", methods=["GET"])
@public_section("Share your story",
                gate=lambda s: bool(getattr(s, "story_form_enabled", True)))
def story_submission_form():
    """Public form for submitting a recovery story. Lands a Story row
    in the holding tank (``is_pending_review=True``) when POSTed to
    ``/storyform/submit``. Visitors get a single self-contained page;
    admins themed-flow gets the story material into the existing
    Stories admin pending-review tab, same flow as the
    announcement / event submission pipeline.

    Honours the ``story_form_enabled`` SiteSetting toggle — when off,
    the page 404s and the CTA on the stories list hides itself.
    """
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "stories_enabled", False):
        abort(404)
    if not getattr(site, "story_form_enabled", True):
        abort(404)
    # When the admin set a custom slug, the canonical /storyform
    # bounces to /<custom-slug>. The page_detail catch-all invokes
    # this function directly with request.path == /<custom-slug>,
    # so the canonical-path check below only fires on direct
    # /storyform hits.
    _custom = (site.story_form_slug or "").strip()
    if _custom and request.path.rstrip("/") == "/storyform":
        return redirect(url_for("frontend.page_detail", slug=_custom))
    ctx = _frontend_context(site)
    # Reuse the shared Submission Form chrome — the same Classic /
    # Minimal / Split variants the events-submission form and every
    # CustomForm render through. Overrides the dispatcher's
    # default heading / subheading / intro with the story-form-
    # specific copy and points it at the story body partial so the
    # fields render correctly inside whichever variant the admin
    # picked.
    tpl = _template_meta(SUBMISSION_FORM_TEMPLATES,
                         (site.frontend_submission_form_template if site else None) or "classic")
    width_mode = (site.frontend_submission_form_width_mode if site else None) or "boxed"
    if width_mode not in ("boxed", "full"):
        width_mode = "boxed"
    try:
        max_width = int(site.frontend_submission_form_max_width) if site else 720
    except (TypeError, ValueError):
        max_width = 720
    max_width = max(480, min(2400, max_width))
    try:
        pad_pct = int(site.frontend_submission_form_padding_pct) if site else 5
    except (TypeError, ValueError):
        pad_pct = 5
    pad_pct = max(0, min(20, pad_pct))
    _tpl_settings = template_settings(site, "submission_form", tpl["key"])
    tpl_style = template_css_vars(_tpl_settings)
    return render_template(
        "frontend/submission.html",
        submission_partial=tpl["partial"],
        submission_template_key=tpl["key"],
        submission_width_mode=width_mode,
        submission_max_width=max_width,
        submission_padding_pct=pad_pct,
        tpl_style=tpl_style,
        heading_override=(site.story_form_heading if site else None) or "Share your story",
        # Pass an empty string (not None) when the admin hasn't set
        # a subheading — the dispatcher template treats "" as
        # "explicitly suppress" so the events-form default doesn't
        # bleed onto the story page.
        subheading_override=(site.story_form_subheading if site else None) or "",
        intro_override=(site.story_form_intro if site else None),
        form_body_partial="frontend/_story_form_body.html",
        **ctx,
    )


@bp.route("/storyform/submit", methods=["POST"])
def story_submission_submit():
    """Process a public story submission. Validates required fields,
    runs the Turnstile gate when enabled, saves any uploaded
    attachment to the upload folder, persists a Story row in the
    pending-review state, and emails the configured recipients.

    Mirrors ``/submissionform/submit`` for events/announcements but
    the persisted row lives in the ``story`` table so the existing
    Stories admin surfaces it for review instead of routing through
    Form Submissions."""
    from flask import flash, current_app
    from .auth import _verify_turnstile
    from .mail import send_mail
    from .models import Story
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "stories_enabled", False):
        abort(404)
    if not getattr(site, "story_form_enabled", True):
        abort(404)

    f = request.form
    submitter_name = (f.get("submitter_name") or "").strip()[:120]
    submitter_email = (f.get("submitter_email") or "").strip()[:255]
    body = (f.get("body") or "").strip()
    accepted = f.get("accept_terms") == "1"
    email_required = bool(getattr(site, "story_form_email_required", False))

    if not submitter_name:
        flash("Please include your name so we can follow up.", "danger")
        return redirect(url_for("frontend.story_submission_form"))
    if email_required and not submitter_email:
        flash("Please include your email so we can follow up.", "danger")
        return redirect(url_for("frontend.story_submission_form"))
    if not body and not (request.files.get("attachment") and request.files["attachment"].filename):
        # Body OR an attached file is required — either way the
        # admin needs something to read. Custom-form behaviour kept
        # the textarea required, but a file-only submission is a
        # reasonable accommodation for visitors who'd rather not
        # paste their story into a browser textarea.
        flash("Either paste your story or upload it as a file.", "danger")
        return redirect(url_for("frontend.story_submission_form"))
    if not accepted:
        flash("Please accept the terms before submitting.", "danger")
        return redirect(url_for("frontend.story_submission_form"))

    # Admin sets a real title during review; the form doesn't ask
    # for one (matches the custom form's layout). Default to the
    # submitter's name so the row reads as something coherent in
    # the pending-review list until the admin renames it.
    title = f"Story from {submitter_name}"[:255]

    if site.turnstile_enabled:
        token = f.get("cf-turnstile-response", "")
        ok, err = _verify_turnstile(site, token, request.remote_addr)
        if not ok:
            flash(err or "Security check failed — please try again.", "danger")
            return redirect(url_for("frontend.story_submission_form"))

    from datetime import datetime as _dt
    s = Story()
    s.title = title
    s.slug = None
    s.summary = None
    s.body = body or None
    # Author byline is set by the admin during review — the public
    # form intentionally doesn't ask for one (matches the custom
    # form's original layout).
    s.author_name = None
    s.is_draft = False
    s.is_archived = False
    s.is_pending_review = True
    s.submitter_name = submitter_name
    s.submitter_email = submitter_email or None
    s.submitter_phone = None
    s.submitter_notes = None
    s.submitted_at = _dt.utcnow()

    # Optional attachment — text document, audio recording, etc. The
    # admin downloads it from the pending-review row before editing
    # the draft. Same UPLOAD_FOLDER + UUID-prefix convention used
    # everywhere else; rejected silently when the request didn't ship
    # one. Size is bounded by ``TSP_MAX_UPLOAD_MB`` (Flask config).
    upload = request.files.get("attachment")
    if upload and upload.filename:
        from werkzeug.utils import secure_filename
        import os, uuid as _uuid
        original = secure_filename(upload.filename) or "attachment"
        ext = os.path.splitext(original)[1].lower()
        stored = f"{_uuid.uuid4().hex}{ext}"
        target = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
        try:
            upload.save(target)
            s.submission_attachment_filename = stored
            s.submission_attachment_original = original[:500]
        except (OSError, IOError):
            s.submission_attachment_filename = None
            s.submission_attachment_original = None

    from .models import db as _db
    _db.session.add(s)
    _db.session.commit()

    # Email the admins. Falls back to access_request_to / submission_to
    # if the dedicated ``story_form_to`` recipient list is blank, so
    # installs that haven't configured stories-specific recipients
    # still see incoming submissions. Reply-to is the submitter's
    # email so admins can respond directly.
    recipients = (getattr(site, "story_form_to", None)
                  or getattr(site, "submission_to", None)
                  or getattr(site, "access_request_to", None)
                  or "").strip()
    if site.smtp_host and recipients:
        submitter_line = f"{submitter_name}"
        if submitter_email:
            submitter_line += f" <{submitter_email}>"
        lines = [
            f"A new recovery story submission has come in via the "
            f"public {site.frontend_title or 'Trusted Servants'} site.",
            "",
        ]
        if submitter_email:
            lines += ["Reply directly to this email to reach the submitter.", ""]
        lines += [f"Submitter:  {submitter_line}"]
        if s.body:
            lines += ["", "Story:", s.body]
        if s.submission_attachment_original:
            lines += ["", f"Attachment: {s.submission_attachment_original} "
                          f"(download via the Stories admin)"]
        email_body = "\n".join(lines)
        try:
            send_mail(site, [r.strip() for r in recipients.split(",") if r.strip()],
                      f"[{site.frontend_title or 'Trusted Servants'}] "
                      f"New story submission — {title}",
                      email_body,
                      reply_to=submitter_email or None)
        except Exception:  # noqa: BLE001
            current_app.logger.exception("Story submission email failed")

    flash(getattr(site, "story_form_success_message", None)
          or "Thank you — your story has been submitted for review.",
          "success")
    return redirect(url_for("frontend.story_submission_form"))


@bp.route("/submissionform")
@public_section("Submit an event or announcement",
                gate=lambda s: bool(getattr(s, "submission_form_enabled", True)))
def submission_form():
    """Standalone submission form. Visitors fill out the form to submit
    an event or announcement for admin review. Same form body the
    global modal uses — both POST to ``/submissionform/submit`` so
    the two contexts always stay in sync.

    Honours the ``submission_form_enabled`` SiteSetting toggle: when
    off, the page returns a 404 (matches what other admin-controlled
    public surfaces do when their feature is disabled).

    Layout is picked from ``SUBMISSION_FORM_TEMPLATES`` via the admin
    Templates page (SiteSetting.frontend_submission_form_template).
    Each variant receives the same heading/subheading/intro payload +
    container width / padding knobs + per-template appearance overrides
    (font, size, background, dynbg) the other templated pages get.
    """
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "submission_form_enabled", True):
        abort(404)
    # When the admin set a custom slug for this form the canonical
    # ``/submissionform`` path is no longer the active URL — redirect
    # to the custom slug instead so the browser bar shows the
    # operator's chosen URL. The page_detail catch-all calls this
    # function directly (request.path == /<custom-slug>) so the
    # canonical-path check below only fires for direct
    # /submissionform hits.
    _custom = (site.submission_form_slug or "").strip()
    if _custom and request.path.rstrip("/") == "/submissionform":
        return redirect(url_for("frontend.page_detail", slug=_custom))
    ctx = _frontend_context(site)

    tpl = _template_meta(SUBMISSION_FORM_TEMPLATES,
                         (site.frontend_submission_form_template if site else None) or "classic")
    _tpl_settings = template_settings(site, "submission_form", tpl["key"])
    tpl_style = template_css_vars(_tpl_settings)
    tpl_dynbg_key = _tpl_settings.get("bg_dynamic_key") \
        or (site.frontend_submission_form_bg_dynamic_key if site else None)
    tpl_dynbg_config = {
        "overlay": _tpl_settings.get("bg_dynbg_overlay"),
        "colors": _tpl_settings.get("bg_dynbg_colors") or [],
        "overlay_scope": _tpl_settings.get("bg_dynbg_overlay_scope"),
        "overlay_size": _tpl_settings.get("bg_dynbg_overlay_size"),
        "overlay_intensity": _tpl_settings.get("bg_dynbg_overlay_intensity"),
        "randomize_colors": _tpl_settings.get("bg_dynbg_randomize_colors", False),
        "randomize_positions": _tpl_settings.get("bg_dynbg_randomize_positions", False),
        "animate": _tpl_settings.get("bg_dynbg_animate", True),
        "pastel_light": _tpl_settings.get("bg_dynbg_pastel_light", False),
        "knobs": _tpl_settings.get("bg_dynbg_knobs", {}),
    }
    width_mode = (site.frontend_submission_form_width_mode if site else None) or "boxed"
    if width_mode not in ("boxed", "full"):
        width_mode = "boxed"
    try:
        max_width = int(site.frontend_submission_form_max_width) if site else 720
    except (TypeError, ValueError):
        max_width = 720
    max_width = max(480, min(2400, max_width))
    try:
        pad_pct = int(site.frontend_submission_form_padding_pct) if site else 5
    except (TypeError, ValueError):
        pad_pct = 5
    pad_pct = max(0, min(20, pad_pct))

    return render_template("frontend/submission.html",
                           submission_partial=tpl["partial"],
                           submission_template_key=tpl["key"],
                           submission_width_mode=width_mode,
                           submission_max_width=max_width,
                           submission_padding_pct=pad_pct,
                           tpl_style=tpl_style,
                           tpl_dynbg_key=tpl_dynbg_key,
                           tpl_dynbg_config=tpl_dynbg_config,
                           **ctx)


@bp.route("/submissionform/submit", methods=["POST"])
def submission_submit():
    """Process a public submission. Validates required fields,
    verifies Turnstile when enabled, persists a Post row in the
    pending-review state, and emails the configured admin recipients.

    The Post is created with the same field shapes as a normal
    /tspro/announcementsevents/save call but with ``is_pending_review=
    True`` so the public site's existing draft/archive filters never
    show it. The admin's holding-tank tab on /tspro/announcementsevents
    surfaces it for review.
    """
    from flask import flash, current_app
    from .auth import _verify_turnstile
    from .mail import send_mail
    from .models import Post
    from .colors import slugify
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "posts_enabled", True):
        abort(404)
    if not getattr(site, "submission_form_enabled", True):
        abort(404)

    # Allowed-types gate. When the admin restricted the form to one
    # of announcements / events, force-set the matching flag and clear
    # the other so a tampered POST can't smuggle the disallowed type
    # through.
    allowed = (getattr(site, "submission_form_allowed_types", None) or "both").lower()

    f = request.form
    title = (f.get("title") or "").strip()[:255]
    if allowed == "announcements":
        is_announcement, is_event = True, False
    elif allowed == "events":
        is_announcement, is_event = False, True
    else:
        is_announcement = f.get("is_announcement") == "1"
        is_event = f.get("is_event") == "1"
    submitter_name = (f.get("submitter_name") or "").strip()[:120]
    submitter_email = (f.get("submitter_email") or "").strip()[:255]

    # Required fields. Title, at least one type, submitter contact.
    if not title:
        flash("A title is required.", "danger")
        return redirect(url_for("frontend.submission_form"))
    if not (is_announcement or is_event):
        flash("Pick at least one type — Announcement or Event.", "danger")
        return redirect(url_for("frontend.submission_form"))
    if not submitter_name or not submitter_email:
        flash("Please include your name and email so we can follow up.", "danger")
        return redirect(url_for("frontend.submission_form"))

    # Turnstile gate, when enabled.
    if site.turnstile_enabled:
        token = f.get("cf-turnstile-response", "")
        ok, err = _verify_turnstile(site, token, request.remote_addr)
        if not ok:
            flash(err or "Security check failed — please try again.", "danger")
            return redirect(url_for("frontend.submission_form"))

    # Build the Post row. Most fields mirror the admin save endpoint.
    from datetime import datetime as _dt
    def _parse_dt(raw):
        if not raw:
            return None
        try:
            return _dt.fromisoformat(raw.strip())
        except (TypeError, ValueError):
            return None

    p = Post()
    p.title = title
    # Slug is left NULL on submission — the admin chooses one when
    # publishing. Public render still won't see it (pending state).
    p.slug = None
    p.summary = (f.get("summary") or "").strip()[:2000] or None
    p.body = (f.get("body") or "").strip() or None
    p.is_announcement = is_announcement
    p.is_event = is_event
    p.event_starts_at = _parse_dt(f.get("event_starts_at"))
    p.event_ends_at = _parse_dt(f.get("event_ends_at"))
    p.is_online = f.get("is_online") == "1"
    p.location_name = (f.get("location_name") or "").strip()[:255] or None
    p.location_address = (f.get("location_address") or "").strip() or None
    p.google_maps_url = (f.get("google_maps_url") or "").strip()[:500] or None
    p.website_url = (f.get("website_url") or "").strip()[:500] or None
    p.website_label = (f.get("website_label") or "").strip()[:120] or None
    p.zoom_meeting_id = (f.get("zoom_meeting_id") or "").strip()[:64] or None
    p.zoom_passcode = (f.get("zoom_passcode") or "").strip()[:128] or None
    p.zoom_url = (f.get("zoom_url") or "").strip()[:500] or None
    p.contact_name = (f.get("contact_name") or "").strip()[:120] or None
    p.contact_phone = (f.get("contact_phone") or "").strip()[:64] or None
    p.contact_email = (f.get("contact_email") or "").strip()[:255] or None
    p.is_pending_review = True
    p.is_draft = False
    p.is_archived = False
    p.submitter_name = submitter_name
    p.submitter_email = submitter_email
    p.submitter_phone = (f.get("submitter_phone") or "").strip()[:64] or None
    p.submitter_notes = (f.get("submitter_notes") or "").strip()[:2000] or None
    p.submitted_at = _dt.utcnow()

    # Featured image upload (optional). Reuses the same pattern as the
    # admin post_save endpoint but inlined here so we don't have to
    # import the helper across blueprints. Anything that isn't an
    # accepted image type is silently ignored — public submitters
    # don't need surfaced upload errors.
    upload = request.files.get("featured_image")
    if upload and upload.filename:
        from werkzeug.utils import secure_filename
        import os, uuid as _uuid
        ext = os.path.splitext(upload.filename or "")[1].lower()
        if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            stored = f"{_uuid.uuid4().hex}{ext}"
            target = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
            try:
                upload.save(target)
                p.featured_image_filename = stored
            except (OSError, IOError):
                # File-system write failed — drop the image silently;
                # submission still proceeds without it.
                p.featured_image_filename = None

    from .models import db as _db
    _db.session.add(p)
    _db.session.commit()

    # Email notification to the configured recipients. Falls back to
    # access_request_to when submission_to is blank so installs that
    # already configured admin notifications get submissions routed
    # without separate setup. Body includes every populated field
    # from the submission so admins can review without first opening
    # the holding tank; the featured image (when one was uploaded)
    # rides along as an attachment.
    recipients = (site.submission_to or site.access_request_to or "").strip()
    if site.smtp_host and recipients:
        kind_label = " + ".join([k for k, v in
                                 (("Announcement", is_announcement),
                                  ("Event", is_event)) if v])
        section_break = ["", "─" * 60, ""]

        def _line(label, value):
            return f"{label:<14} {value}" if value else None

        def _section(heading, pairs):
            present = [p for p in pairs if p]
            if not present:
                return []
            return [heading] + ["-" * len(heading)] + present + [""]

        intro = [
            f"A new {kind_label.lower()} submission has come in via "
            f"the public {site.frontend_title or 'Trusted Servants'} site.",
            "",
            "Reply directly to this email to reach the submitter.",
            "",
        ]

        # Submitter details — always present (name + email required).
        submitter_section = _section("Submitter", [
            _line("Name:", submitter_name),
            _line("Email:", submitter_email),
            _line("Phone:", p.submitter_phone),
            (f"\nNotes from submitter:\n{p.submitter_notes}"
             if p.submitter_notes else None),
        ])

        # Headline + body. Falls through gracefully when summary /
        # body are blank (form allows them empty).
        content_section = _section("Submission", [
            _line("Title:", title),
            _line("Type:", kind_label),
            (f"\nSummary:\n{p.summary}" if p.summary else None),
            (f"\nFull content:\n{p.body}" if p.body else None),
            (f"\nFeatured image: {p.featured_image_filename} "
             f"(attached to this email)" if p.featured_image_filename else None),
        ])

        # Event-specific block — skipped when the post isn't tagged
        # as an event so an announcement-only submission email isn't
        # padded with empty event headers.
        event_pairs = []
        if is_event:
            event_pairs.append(_line(
                "Starts:",
                p.event_starts_at.strftime("%a %b %-d, %Y · %-I:%M %p")
                if p.event_starts_at else None))
            event_pairs.append(_line(
                "Ends:",
                p.event_ends_at.strftime("%a %b %-d, %Y · %-I:%M %p")
                if p.event_ends_at else None))
            event_pairs.append(_line(
                "Online:", "Yes" if p.is_online else "No"))
            event_pairs.append(_line("Location:", p.location_name))
            event_pairs.append(_line("Address:", p.location_address))
            event_pairs.append(_line("Maps URL:", p.google_maps_url))
            event_pairs.append(_line("Zoom ID:", p.zoom_meeting_id))
            event_pairs.append(_line("Zoom pass:", p.zoom_passcode))
            event_pairs.append(_line("Zoom URL:", p.zoom_url))
            event_pairs.append(_line("Website:", p.website_url))
            event_pairs.append(_line("Web label:", p.website_label))
        event_section = _section("Event details", event_pairs) if is_event else []

        # Public contact (event posts only — that's where these
        # fields are admin-visible too).
        contact_section = _section("Public contact (will be shown on the post)", [
            _line("Name:", p.contact_name),
            _line("Phone:", p.contact_phone),
            _line("Email:", p.contact_email),
        ]) if is_event else []

        review_url = url_for("main.post_edit", pid=p.id, _external=True)
        footer = [
            "─" * 60,
            f"Review, edit, approve, or reject in the holding tank:",
            f"  {review_url}",
        ]

        body = "\n".join(intro + submitter_section + content_section
                        + event_section + contact_section + footer)

        # Featured image rides along as an attachment when present.
        attachments = []
        if p.featured_image_filename:
            from flask import current_app as _ca
            stored = p.featured_image_filename
            path = os.path.join(_ca.config["UPLOAD_FOLDER"], stored)
            # Use a friendlier filename for the email — title +
            # original extension. Falls back to the stored name when
            # the title doesn't yield anything safe.
            ext = os.path.splitext(stored)[1].lower()
            safe = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_"
                           for c in (title or "")).strip()[:120]
            friendly = (safe + ext) if (safe and ext) else stored
            mime_guess = ({".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                           ".png": "image/png", ".gif": "image/gif",
                           ".webp": "image/webp"}).get(ext, "application/octet-stream")
            attachments.append({"path": path, "filename": friendly,
                                "mime_type": mime_guess})

        send_mail(site, recipients,
                  f"New {kind_label.lower()} submission: {title}",
                  body, attachments=attachments)
        # Mail failures are not surfaced to the visitor — the submission
        # is already persisted; the admin can find it in the holding
        # tank regardless of whether the notification email landed.

    success_msg = (getattr(site, "submission_form_success_message", None)
                   or "Thank you — your submission has been received and will be reviewed before publishing.")
    flash(success_msg, "success")
    return redirect(url_for("frontend.submission_form"))


@bp.route("/printlist")
@bp.route("/printlist.pdf", endpoint="printlist_pdf")
@public_section("Print list")
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
@public_section("Library")
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


@bp.route("/fellowships")
@public_section("Fellowships",
                gate=lambda s: bool(getattr(s, "frontend_fellowships_enabled", False)))
def fellowships_list():
    """Public Fellowships Index page.

    Renders the admin-curated list of peer recovery fellowships (Crystal
    Meth Anonymous, AA, NA, OA, etc.) the admin manages from Settings →
    Global. Each row carries a name, a Virtual / Regional flag, an
    optional country + state/region, and the fellowship's website URL.
    Page chrome mirrors /archive + /library: a sticky sidebar rail with
    live search, virtual/regional toggle checkboxes, per-country filter
    pills, and a sort selector; the main column groups cards under
    country headings (Virtual gets its own bucket) and renders each
    fellowship as a card with the website CTA.

    The 404 gate honours ``frontend_fellowships_enabled`` so the page
    behaves like every other admin-controlled public surface — toggling
    it off in the admin Templates panel hides the route, /siteindex
    entry, and search index entries in lockstep.
    """
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "frontend_fellowships_enabled", False):
        abort(404)
    ctx = _frontend_context(site)

    from datetime import datetime
    from .models import Fellowship
    rows = (Fellowship.query
            .order_by(Fellowship.sort_order, Fellowship.id)
            .all())

    # Pre-compute the country buckets (one bucket per country observed
    # in the data, plus a "Virtual" bucket for is_virtual rows). The
    # default sort order chosen by the admin decides which bucket
    # heading reads first; the sidebar's sort selector lets visitors
    # re-order on the fly via JS without re-querying the server.
    sort_mode = (site.frontend_fellowships_list_sort_mode if site else None) or "name-asc"
    if sort_mode not in ("name-asc", "name-desc", "country-asc",
                         "newest", "oldest"):
        sort_mode = "name-asc"

    # Map each fellowship to a {country -> bucket} structure for the
    # initial server-rendered layout. Virtual fellowships go under a
    # synthetic "Virtual" bucket so the sidebar's country pills and
    # the main column's section headings stay in sync.
    from collections import OrderedDict
    country_buckets_map = OrderedDict()

    def _country_label(f):
        if f.is_virtual:
            return "Virtual"
        return (f.country or "").strip() or "Other"

    # First-pass: collect rows sorted by initial sort.
    if sort_mode == "name-asc":
        rows.sort(key=lambda f: (f.name or "").lower())
    elif sort_mode == "name-desc":
        rows.sort(key=lambda f: (f.name or "").lower(), reverse=True)
    elif sort_mode == "country-asc":
        rows.sort(key=lambda f: (
            1 if f.is_virtual else 0,  # virtual to the end of country sort
            ((f.country or "").lower()),
            ((f.state_region or "").lower()),
            (f.name or "").lower(),
        ))
    elif sort_mode == "newest":
        rows.sort(key=lambda f: (f.created_at or datetime.min), reverse=True)
    elif sort_mode == "oldest":
        rows.sort(key=lambda f: (f.created_at or datetime.min))

    for f in rows:
        label = _country_label(f)
        country_buckets_map.setdefault(label, []).append(f)

    country_buckets = [{"country": k, "items": v}
                       for k, v in country_buckets_map.items()]

    # Per-row search blob — punctuation-stripped lowercase fragments
    # covering name, country, state/region, and URL host so a query
    # for "ireland" hits any Irish fellowship row and a query for
    # "anonymous" matches every Anonymous fellowship's name. Same
    # regex shape as every other client-side search blob on the site.
    import re as _re_search
    _PUNCT_STRIP_RE = _re_search.compile(r"[‘’'?!.,;\"“”()\[\]{}]")

    def _row_blob(f):
        bits = [
            (f.name or "").lower(),
            (f.country or "").lower(),
            (f.state_region or "").lower(),
            "virtual online" if f.is_virtual else "regional",
        ]
        if f.url:
            bits.append(f.url.lower())
        return _PUNCT_STRIP_RE.sub("", " ".join(b for b in bits if b))

    search_blobs = {f.id: _row_blob(f) for f in rows}

    tpl = _template_meta(FELLOWSHIPS_LIST_TEMPLATES,
                         (site.frontend_fellowships_list_template if site else None) or "sidebar")
    _tpl_settings = template_settings(site, "fellowships_list", tpl["key"])
    tpl_style = template_css_vars(_tpl_settings)
    tpl_dynbg_key = _tpl_settings.get("bg_dynamic_key") \
        or (site.frontend_fellowships_list_bg_dynamic_key if site else None)
    tpl_dynbg_config = {
        "overlay": _tpl_settings.get("bg_dynbg_overlay"),
        "colors": _tpl_settings.get("bg_dynbg_colors") or [],
        "overlay_scope": _tpl_settings.get("bg_dynbg_overlay_scope"),
        "overlay_size": _tpl_settings.get("bg_dynbg_overlay_size"),
        "overlay_intensity": _tpl_settings.get("bg_dynbg_overlay_intensity"),
        "randomize_colors": _tpl_settings.get("bg_dynbg_randomize_colors", False),
        "randomize_positions": _tpl_settings.get("bg_dynbg_randomize_positions", False),
        "animate": _tpl_settings.get("bg_dynbg_animate", True),

        "pastel_light": _tpl_settings.get("bg_dynbg_pastel_light", False),
        "knobs": _tpl_settings.get("bg_dynbg_knobs", {}),
    }

    width_mode = (site.frontend_fellowships_list_width_mode if site else None) or "boxed"
    if width_mode not in ("boxed", "full"):
        width_mode = "boxed"
    try:
        max_width = int(site.frontend_fellowships_list_max_width) if site else 1160
    except (TypeError, ValueError):
        max_width = 1160
    max_width = max(640, min(2400, max_width))
    try:
        pad_pct = int(site.frontend_fellowships_list_padding_pct) if site else 5
    except (TypeError, ValueError):
        pad_pct = 5
    pad_pct = max(0, min(20, pad_pct))

    heading = (site.frontend_fellowships_list_heading if site else None) or "Fellowships"
    subheading = (site.frontend_fellowships_list_subheading if site else None) \
        or "Sister recovery fellowships, with links to their own pages."

    # Total counts for the rail (per-pill counts come straight off the
    # bucket lists). `virtual_count` and `regional_count` drive the
    # type-toggle checkbox labels in the rail.
    virtual_count = sum(1 for f in rows if f.is_virtual)
    regional_count = len(rows) - virtual_count

    return render_template("frontend/fellowships_list.html",
                           fellowships=rows,
                           country_buckets=country_buckets,
                           search_blobs=search_blobs,
                           sort_mode=sort_mode,
                           heading=heading,
                           subheading=subheading,
                           list_partial=tpl["partial"],
                           list_template_key=tpl["key"],
                           list_width_mode=width_mode,
                           list_max_width=max_width,
                           list_padding_pct=pad_pct,
                           tpl_style=tpl_style,
                           tpl_dynbg_key=tpl_dynbg_key,
                           tpl_dynbg_config=tpl_dynbg_config,
                           virtual_count=virtual_count,
                           regional_count=regional_count,
                           **ctx)


@bp.route("/events")
@public_section("Events", gate=lambda s: bool(getattr(s, "posts_enabled", True)))
def events_list():
    """Public list of every upcoming event. Linked from the homepage
    Upcoming Events block via the "See all events" CTA. Uses the same
    Post query the homepage block does, but with a high cap so visitors
    can browse the full upcoming queue."""
    from .routes import _auto_archive_events
    _auto_archive_events()
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "posts_enabled", True):
        abort(404)
    ctx = _frontend_context(site)
    # Direct query (not the shared `filtered_events` helper, which
    # orders by `event_starts_at` ascending for the homepage block).
    # The /events list sorts by post order — newest published at the
    # top — to match the announcements list behaviour and surface
    # recent additions first regardless of when each event runs.
    # Past events still drop off so the public list stays "upcoming
    # only"; /archive is the home for ended events.
    from .timezone import now_local_naive
    from sqlalchemy import func as _sql_func
    # event_ends_at is naive site-local — compare in the same frame
    # so events drop off at midnight local, not at midnight UTC.
    _now = now_local_naive(site)
    _rows = (Post.query
             .filter(Post.is_event.is_(True),
                     Post.is_archived.is_(False),
                     Post.is_draft.is_(False),
                     Post.is_pending_review.is_(False))
             .order_by(_sql_func.coalesce(Post.published_at,
                                          Post.created_at).desc())
             .all())
    all_events = []
    for p in _rows:
        ref_end = p.event_ends_at or p.event_starts_at
        if ref_end is None or ref_end < _now:
            continue
        all_events.append(p)
        if len(all_events) >= 500:
            break
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
@public_section("Archive", gate=lambda s: bool(getattr(s, "posts_enabled", True)))
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

    from .timezone import now_local_naive
    # event_ends_at is naive site-local — see _auto_archive_events
    # for the canonical writeup.
    now = now_local_naive(site)

    # Past events: ended OR is_archived. Skip the ones with no date.
    event_rows = (Post.query
                  .filter(Post.is_event.is_(True),
                          Post.is_draft.is_(False),
                          Post.is_pending_review.is_(False))
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
                        Post.is_draft.is_(False),
                          Post.is_pending_review.is_(False))
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
        # Prefer the admin-set / WP-imported publish timestamp so
        # backdated + bulk-imported posts bucket under the year they
        # were originally published, not the year the row was inserted.
        # Falls back to created_at when published_at is NULL so legacy
        # rows still surface a date.
        ts = p.published_at or p.created_at
        if not ts:
            continue
        items.append({
            "kind": "announcement",
            "post": p,
            "sort_at": ts,
            "year": ts.year,
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

    # Pagination strategy + initial page size. Two modes:
    #   - 'infinite' (default): reveal page_size cards on load, JS shows
    #     another page_size each time the visitor scrolls to the end.
    #   - 'numbered': page_size at a time with numbered page links at
    #     the bottom of the results column.
    # The work happens client-side so the existing search / year /
    # type filters can keep adjusting the visible set live without a
    # round-trip.
    pagination_mode = (site.frontend_archive_pagination_mode if site else None) or "infinite"
    if pagination_mode not in ("infinite", "numbered"):
        pagination_mode = "infinite"
    try:
        page_size = int(site.frontend_archive_page_size) if site else 20
    except (TypeError, ValueError):
        page_size = 20
    page_size = max(1, min(200, page_size))

    # Pick the layout partial. Falls back to the catalog's first entry
    # (year-sidebar) when a stored key was removed from ARCHIVE_TEMPLATES.
    tpl = _template_meta(ARCHIVE_TEMPLATES,
                         (site.frontend_archive_template if site else None) or "year-sidebar")

    return render_template("frontend/archive.html",
                           list_partial=tpl["partial"],
                           list_template_key=tpl["key"],
                           list_width_mode=width_mode,
                           list_max_width=max_width,
                           list_padding_pct=pad_pct,
                           archive_items=items,
                           year_buckets=year_buckets,
                           search_blobs=blobs,
                           archive_counts=counts,
                           archive_pagination_mode=pagination_mode,
                           archive_page_size=page_size,
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
                  .filter(Post.is_draft.is_(False),
                          Post.is_pending_review.is_(False))
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
    _tpl_settings = template_settings(site, "event", tpl["key"])
    tpl_style = template_css_vars(_tpl_settings)
    tpl_dynbg_key = _tpl_settings.get("bg_dynamic_key")
    tpl_dynbg_overlay = _tpl_settings.get("bg_dynbg_overlay")
    tpl_dynbg_colors = _tpl_settings.get("bg_dynbg_colors") or []
    # Full per-template dynbg config — carries the randomize
    # flags / scope / noise knobs / animate state alongside the
    # base key + overlay + palette so each entity-detail partial
    # has every dimension the apply-partial expects. Earlier
    # only key/overlay/colors were threaded through, so the
    # randomize / freeze-movement settings persisted in JSON
    # but never applied on the public render.
    tpl_dynbg_config = {
        "overlay": tpl_dynbg_overlay,
        "colors": tpl_dynbg_colors,
        "overlay_scope": _tpl_settings.get("bg_dynbg_overlay_scope"),
        "overlay_size": _tpl_settings.get("bg_dynbg_overlay_size"),
        "overlay_intensity": _tpl_settings.get("bg_dynbg_overlay_intensity"),
        "randomize_colors": _tpl_settings.get("bg_dynbg_randomize_colors", False),
        "randomize_positions": _tpl_settings.get("bg_dynbg_randomize_positions", False),
        "animate": _tpl_settings.get("bg_dynbg_animate", True),

        "pastel_light": _tpl_settings.get("bg_dynbg_pastel_light", False),
        "knobs": _tpl_settings.get("bg_dynbg_knobs", {}),
    }
    og = _page_og(site, title=post.title,
                  description=post.summary or post.body,
                  image_url=(url_for("public.post_featured_image", pid=post.id, _external=True)
                             if post.featured_image_filename else None))
    return render_template(tpl["partial"], event=post, tpl_style=tpl_style, tpl_dynbg_key=tpl_dynbg_key, tpl_dynbg_overlay=tpl_dynbg_overlay, tpl_dynbg_colors=tpl_dynbg_colors, tpl_dynbg_config=tpl_dynbg_config,
                           is_in_archive=True, **og, **ctx)


def _active_announcements():
    """Active announcements (non-archived, published, approved), newest
    first. Shared by the /announcements list and the GSR-summary fragment
    so both surfaces show exactly the same set.

    Newest-first by post order. ``display_posted`` prefers the admin-set
    ``published_at`` over the auto ``created_at``, so the SQL sort mirrors
    that priority via ``coalesce`` — back-dated posts surface in the right
    slot, and rows with NULL ``published_at`` (legacy imports) still sort
    sensibly via their creation time.
    """
    from sqlalchemy import func as _sql_func
    return (Post.query
            .filter(Post.is_announcement.is_(True),
                    Post.is_archived.is_(False),
                    Post.is_draft.is_(False),
                    Post.is_pending_review.is_(False))
            .order_by(_sql_func.coalesce(Post.published_at,
                                         Post.created_at).desc())
            .all())


@bp.route("/announcements/gsr-summary")
def announcements_gsr_summary():
    """HTML fragment: just the GSR Summary "paper", reusing the exact
    partial the /announcements page renders. Powers the GSR modal opened
    by the utility-bar GSR button on any page — the button is global but
    the announcement data only lives here, so the modal fetches this
    fragment on demand. Not a navigable section (no @public_section); the
    static path is matched ahead of any dynamic /announcements/<slug>."""
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "posts_enabled", True):
        abort(404)
    return render_template("frontend/_gsr_summary.html",
                           all_announcements=_active_announcements())


@bp.route("/announcements")
@public_section("Announcements", gate=lambda s: bool(getattr(s, "posts_enabled", True)))
def announcements_list():
    """Public list of every active announcement. Layout is picked from
    ANNOUNCEMENTS_LIST_TEMPLATES via the admin Templates panel — currently
    a single omni layout (Cards + GSR Summary) with a separate Archive
    pill linking to /announcements/archive."""
    from .routes import _auto_archive_events
    _auto_archive_events()
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "posts_enabled", True):
        abort(404)
    ctx = _frontend_context(site)

    rows = _active_announcements()

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


def _resolve_form_link(identifier):
    """Turn a stored form identifier into a public ``(url, label_default)``
    pair. ``identifier`` is the canonical string the admin dropdown
    writes: registry key (``submission`` / ``contact``) for built-in
    forms, ``custom:<id>`` for an admin-authored CustomForm. Returns
    ``(None, None)`` when the identifier is empty / unrecognised /
    points at a deleted form so the caller can hide the CTA without
    crashing the page. ``label_default`` is the form's own title —
    used when the operator hasn't typed a custom button label."""
    if not identifier:
        return None, None
    from .forms_registry import form_by_key
    from .models import CustomForm as _CF
    if identifier.startswith("custom:"):
        try:
            cf_id = int(identifier.split(":", 1)[1])
        except (ValueError, IndexError):
            return None, None
        cf = _CF.query.filter_by(id=cf_id, enabled=True).first()
        if cf is None:
            return None, None
        # ``custom_form_submit`` is POST-only; the public GET URL is the
        # catch-all ``page_detail`` route which falls through to
        # CustomForm when no Page matches the slug.
        return url_for("frontend.page_detail", slug=cf.slug), cf.title
    entry = form_by_key(identifier)
    if entry is None:
        return None, None
    endpoint = entry.get("public_url_endpoint")
    if not endpoint:
        return None, None
    # Prefer the admin-customised slug when set — the canonical
    # path keeps working too, but URL surfaces (CTAs, nav links)
    # should read the operator's chosen URL so the public site
    # matches what they picked. ``identifier`` is the registry
    # key (``submission`` / ``story`` / ``contact``); the matching
    # SiteSetting slug column lives under
    # ``<key>_form_slug`` (or just ``contact_form_slug`` etc).
    site = _site()
    slug_overrides = {
        "submission": getattr(site, "submission_form_slug", None) if site else None,
        "story": getattr(site, "story_form_slug", None) if site else None,
        "contact": getattr(site, "contact_form_slug", None) if site else None,
    }
    custom_slug = (slug_overrides.get(identifier) or "").strip()
    if custom_slug:
        try:
            return url_for("frontend.page_detail", slug=custom_slug), entry.get("name") or "Submit"
        except Exception:  # noqa: BLE001
            pass
    try:
        return url_for(endpoint), entry.get("name") or "Submit"
    except Exception:  # noqa: BLE001 — endpoint missing / module disabled
        return None, None


@bp.route("/stories")
@public_section("Stories", gate=lambda s: bool(getattr(s, "stories_enabled", False)))
def stories_list():
    """Public list of every published recovery story. Layout selected
    via SiteSetting.frontend_stories_list_template; defaults to the
    paper-stack layout. Drafts and archives are filtered out."""
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "stories_enabled", False):
        abort(404)
    ctx = _frontend_context(site)
    rows = (Story.query
            .filter(Story.is_archived.is_(False),
                    Story.is_draft.is_(False))
            .order_by(Story.is_featured.desc(),
                      Story.story_date.desc().nulls_last(),
                      Story.created_at.desc())
            .all())
    tpl = _template_meta(STORIES_LIST_TEMPLATES,
                         (site.frontend_stories_list_template if site else None) or "paper-stack")
    width_mode = (site.frontend_stories_list_width_mode if site else None) or "boxed"
    if width_mode not in ("boxed", "full"):
        width_mode = "boxed"
    try:
        max_width = int(site.frontend_stories_list_max_width) if site else 1160
    except (TypeError, ValueError):
        max_width = 1160
    max_width = max(640, min(2400, max_width))
    try:
        pad_pct = int(site.frontend_stories_list_padding_pct) if site else 5
    except (TypeError, ValueError):
        pad_pct = 5
    pad_pct = max(0, min(20, pad_pct))
    list_heading = (site.frontend_stories_list_heading if site else None) or ""
    list_subheading = (site.frontend_stories_list_subheading if site else None) or ""
    # Optional "Submit a story" CTA. Resolver returns (None, None) for
    # empty / deleted / disabled targets so the template can hide the
    # button cleanly. Operator's custom label wins; falls back to the
    # form's own title when blank.
    submit_url, default_label = _resolve_form_link(
        site.frontend_stories_list_submit_form if site else None)
    submit_label = (site.frontend_stories_list_submit_label if site else None) or default_label
    return render_template("frontend/stories_list.html",
                           list_partial=tpl["partial"],
                           list_template_key=tpl["key"],
                           list_width_mode=width_mode,
                           list_max_width=max_width,
                           list_padding_pct=pad_pct,
                           list_heading=list_heading,
                           list_subheading=list_subheading,
                           submit_url=submit_url,
                           submit_label=submit_label,
                           all_stories=rows,
                           **ctx)


@bp.route("/stories/<slug>")
def story_detail(slug):
    """Public story detail page. The slug is the story title with
    non-alphanumerics collapsed to hyphens (or the explicit slug an
    editor set on the admin form). Drafts + archives are not viewable.
    Old slugs 301-redirect to the current one via EntitySlugHistory."""
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "stories_enabled", False):
        abort(404)
    candidates = (Story.query
                  .filter(Story.is_archived.is_(False),
                          Story.is_draft.is_(False))
                  .order_by(Story.id)
                  .all())
    story = next((s for s in candidates if s.public_slug == slug), None)
    if story is None:
        from .models import EntitySlugHistory
        hist = (EntitySlugHistory.query
                .filter_by(entity_type="story", old_slug=slug)
                .order_by(EntitySlugHistory.changed_at.desc())
                .first())
        if hist:
            target = next((s for s in candidates if s.id == hist.entity_id), None)
            if target:
                return redirect(url_for("frontend.story_detail", slug=target.public_slug), code=301)
        abort(404)
    ctx = _frontend_context(site)
    tpl = _template_meta(STORY_TEMPLATES,
                         (site.frontend_story_template if site else None) or "paper")
    _tpl_settings = template_settings(site, "story", tpl["key"])
    tpl_style = template_css_vars(_tpl_settings)
    # Story-detail dynbg lives on a flat SiteSetting field (`frontend_
    # story_bg_dynamic_key`) since the Templates admin's Story-detail
    # section uses a flat picker rather than the per-template-settings
    # JSON path. Per-template settings could still carry one as a
    # fallback (no admin UI today, but the plumbing supports it) so we
    # check the flat field first and fall through if absent.
    tpl_dynbg_key = (getattr(site, "frontend_story_bg_dynamic_key", None)
                     or _tpl_settings.get("bg_dynamic_key"))
    # Overlay + colours travel via the flat SiteSetting JSON column
    # (matches the Templates admin's flat picker for Story detail).
    from . import dynbg as _dynbg
    _story_cfg = _dynbg.decode_config(
        getattr(site, "frontend_story_bg_dynbg_config_json", None))
    tpl_dynbg_overlay = (_story_cfg["overlay"]
                         or _tpl_settings.get("bg_dynbg_overlay"))
    tpl_dynbg_colors = (_story_cfg["colors"]
                        or _tpl_settings.get("bg_dynbg_colors") or [])
    # Full per-template dynbg config — carries every dimension the
    # apply-partial / story templates read (overlay scope + size +
    # intensity, randomize flags, animate state) so the noise / motion
    # knobs the admin saved on the flat picker actually take effect on
    # the public render. Flat SiteSetting JSON wins; falls through to
    # the per-template-settings leaf keys for anything not set.
    tpl_dynbg_config = {
        "overlay": tpl_dynbg_overlay,
        "colors": tpl_dynbg_colors,
        "overlay_scope": (_story_cfg["overlay_scope"]
                          or _tpl_settings.get("bg_dynbg_overlay_scope")),
        "overlay_size": (_story_cfg["overlay_size"]
                         if _story_cfg["overlay_size"] is not None
                         else _tpl_settings.get("bg_dynbg_overlay_size")),
        "overlay_intensity": (_story_cfg["overlay_intensity"]
                              if _story_cfg["overlay_intensity"] is not None
                              else _tpl_settings.get("bg_dynbg_overlay_intensity")),
        "randomize_colors": (_story_cfg["randomize_colors"]
                             or _tpl_settings.get("bg_dynbg_randomize_colors", False)),
        "randomize_positions": (_story_cfg["randomize_positions"]
                                or _tpl_settings.get("bg_dynbg_randomize_positions", False)),
        "animate": (_tpl_settings.get("bg_dynbg_animate", True)
                    if _story_cfg["animate"] is True
                    else _story_cfg["animate"]),

        "pastel_light": _tpl_settings.get("bg_dynbg_pastel_light", False),
        "knobs": _tpl_settings.get("bg_dynbg_knobs", {}),
    }
    og = _page_og(site, title=story.title,
                  description=story.summary or story.body,
                  image_url=(url_for("public.story_featured_image", sid=story.id, _external=True)
                             if story.featured_image_filename else None))
    return render_template(tpl["partial"], story=story, tpl_style=tpl_style, tpl_dynbg_key=tpl_dynbg_key, tpl_dynbg_overlay=tpl_dynbg_overlay, tpl_dynbg_colors=tpl_dynbg_colors, tpl_dynbg_config=tpl_dynbg_config, **og, **ctx)


# ─────────────────────────────────────────────────────────────────────
# Blog — long-form editorial posts. The same data table can serve many
# distinct frontend "blogs" by filtering on category or tag (driven by
# the page-block when embedded in a custom Page; via ?category=<slug>
# or ?tag=<slug> on /blog itself for the canonical list view).
# ─────────────────────────────────────────────────────────────────────
def _blog_visible_query():
    """Base BlogPost query for public consumption — drafts and archived
    rows are filtered out, pinned posts surface first, then by
    published_at descending."""
    return (BlogPost.query
            .filter(BlogPost.is_archived.is_(False),
                    BlogPost.is_draft.is_(False))
            .order_by(BlogPost.is_pinned.desc(),
                      BlogPost.published_at.desc().nulls_last(),
                      BlogPost.created_at.desc()))


@bp.route("/blog")
@public_section("Blog", gate=lambda s: bool(getattr(s, "blog_enabled", False)))
def blog_list():
    """Public list of every published blog post. Layout selected via
    SiteSetting.frontend_blog_list_template; defaults to magazine.
    Optional ?category=<slug> / ?tag=<slug> scopes the list — the
    matching category / tag is also passed in so the active-filter UI
    can reflect the choice."""
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "blog_enabled", False):
        abort(404)
    ctx = _frontend_context(site)

    cat_slug = (request.args.get("category") or "").strip()
    tag_slug = (request.args.get("tag") or "").strip()
    active_category = BlogCategory.query.filter_by(slug=cat_slug).first() if cat_slug else None
    active_tag = BlogTag.query.filter_by(slug=tag_slug).first() if tag_slug else None

    q = _blog_visible_query()
    if active_category:
        q = q.filter(BlogPost.categories.any(BlogCategory.id == active_category.id))
    if active_tag:
        q = q.filter(BlogPost.tags.any(BlogTag.id == active_tag.id))
    rows = q.all()

    all_categories = (BlogCategory.query
                      .order_by(BlogCategory.position, BlogCategory.name).all())
    all_tags = BlogTag.query.order_by(BlogTag.name).all()

    tpl = _template_meta(BLOG_LIST_TEMPLATES,
                         (site.frontend_blog_list_template if site else None) or "magazine")
    width_mode = (site.frontend_blog_list_width_mode if site else None) or "boxed"
    if width_mode not in ("boxed", "full"):
        width_mode = "boxed"
    try:
        max_width = int(site.frontend_blog_list_max_width) if site else 1160
    except (TypeError, ValueError):
        max_width = 1160
    max_width = max(640, min(2400, max_width))
    try:
        pad_pct = int(site.frontend_blog_list_padding_pct) if site else 5
    except (TypeError, ValueError):
        pad_pct = 5
    pad_pct = max(0, min(20, pad_pct))
    list_heading = (site.frontend_blog_list_heading if site else None) or ""
    list_subheading = (site.frontend_blog_list_subheading if site else None) or ""
    return render_template("frontend/blog_list.html",
                           list_partial=tpl["partial"],
                           list_template_key=tpl["key"],
                           list_width_mode=width_mode,
                           list_max_width=max_width,
                           list_padding_pct=pad_pct,
                           list_heading=list_heading,
                           list_subheading=list_subheading,
                           all_posts=rows,
                           all_categories=all_categories,
                           all_tags=all_tags,
                           active_category=active_category,
                           active_tag=active_tag,
                           **ctx)


@bp.route("/blog/<slug>")
def blog_post_detail(slug):
    """Public blog post detail. The slug is the post title with non-
    alphanumerics collapsed to hyphens (or the explicit slug an editor
    set on the admin form). Drafts + archives are normally not
    viewable; an authenticated editor can preview them via the same
    URL — a "Draft preview" banner is stamped on top so the previewer
    knows they're looking at unpublished content. Old slugs
    301-redirect to the current one via EntitySlugHistory.

    Reserves the slugs ``category`` and ``tag`` so /blog/category/<slug>
    and /blog/tag/<slug> can serve filtered list views without
    colliding with a post that happened to be slugged "category"."""
    if slug in ("category", "tag"):
        abort(404)
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "blog_enabled", False):
        abort(404)
    # Authenticated editors get to preview drafts + archived posts;
    # everyone else only sees the published set. The `is_preview`
    # flag rides through to the template so it can stamp a banner.
    can_preview = (current_user.is_authenticated
                   and current_user.can_edit())
    if can_preview:
        all_posts = BlogPost.query.order_by(BlogPost.is_pinned.desc(),
                                             BlogPost.published_at.desc().nulls_last(),
                                             BlogPost.created_at.desc()).all()
    else:
        all_posts = _blog_visible_query().all()
    candidates = all_posts
    post = next((p for p in candidates if p.public_slug == slug), None)
    if post is None:
        from .models import EntitySlugHistory
        hist = (EntitySlugHistory.query
                .filter_by(entity_type="blog", old_slug=slug)
                .order_by(EntitySlugHistory.changed_at.desc())
                .first())
        if hist:
            target = next((p for p in candidates if p.id == hist.entity_id), None)
            if target:
                return redirect(url_for("frontend.blog_post_detail", slug=target.public_slug), code=301)
        abort(404)
    ctx = _frontend_context(site)
    tpl = _template_meta(BLOG_POST_TEMPLATES,
                         (site.frontend_blog_post_template if site else None) or "modern")
    _tpl_settings = template_settings(site, "blog_post", tpl["key"])
    tpl_style = template_css_vars(_tpl_settings)
    tpl_dynbg_key = (getattr(site, "frontend_blog_post_bg_dynamic_key", None)
                     or _tpl_settings.get("bg_dynamic_key"))
    from . import dynbg as _dynbg
    _post_cfg = _dynbg.decode_config(
        getattr(site, "frontend_blog_post_bg_dynbg_config_json", None))
    tpl_dynbg_overlay = (_post_cfg["overlay"]
                         or _tpl_settings.get("bg_dynbg_overlay"))
    tpl_dynbg_colors = (_post_cfg["colors"]
                        or _tpl_settings.get("bg_dynbg_colors") or [])
    tpl_dynbg_config = {
        "overlay": tpl_dynbg_overlay,
        "colors": tpl_dynbg_colors,
        "overlay_scope": _tpl_settings.get("bg_dynbg_overlay_scope"),
        "overlay_size": _tpl_settings.get("bg_dynbg_overlay_size"),
        "overlay_intensity": _tpl_settings.get("bg_dynbg_overlay_intensity"),
        "randomize_colors": _tpl_settings.get("bg_dynbg_randomize_colors", False),
        "randomize_positions": _tpl_settings.get("bg_dynbg_randomize_positions", False),
        "animate": _tpl_settings.get("bg_dynbg_animate", True),

        "pastel_light": _tpl_settings.get("bg_dynbg_pastel_light", False),
        "knobs": _tpl_settings.get("bg_dynbg_knobs", {}),
    }

    # Up to four related posts: prefer ones sharing a category, then
    # any other recent posts. Excludes the post itself + drafts +
    # archives; pinned posts can show up in related too.
    related = []
    if post.categories:
        cat_ids = [c.id for c in post.categories]
        related = (_blog_visible_query()
                   .filter(BlogPost.id != post.id)
                   .filter(BlogPost.categories.any(BlogCategory.id.in_(cat_ids)))
                   .limit(4).all())
    if len(related) < 4:
        existing_ids = {r.id for r in related} | {post.id}
        more = (_blog_visible_query()
                .filter(~BlogPost.id.in_(existing_ids))
                .limit(4 - len(related)).all())
        related = related + more
    all_categories = (BlogCategory.query
                      .order_by(BlogCategory.position, BlogCategory.name).all())
    og = _page_og(site, title=post.title,
                  description=post.summary or post.body,
                  image_url=(url_for("public.blog_post_featured_image", bid=post.id, _external=True)
                             if post.featured_image_filename else None))
    # Classic-blog rail toggles — both default to True. Defined at
    # the dispatcher so every template gets the same context shape
    # even if only `classic` actually consumes them today.
    show_related_widget = bool(_tpl_settings.get("show_related_widget", True))
    show_categories_widget = bool(_tpl_settings.get("show_categories_widget", True))
    # Container width controls — same shape as the blog-list page.
    # Templates render either a boxed shell (max-width: Npx) or a
    # full-bleed shell (padding-left/right: Nvw).
    post_width_mode = (site.frontend_blog_post_width_mode if site else None) or "boxed"
    if post_width_mode not in ("boxed", "full"):
        post_width_mode = "boxed"
    try:
        post_max_width = int(site.frontend_blog_post_max_width) if site else 1160
    except (TypeError, ValueError):
        post_max_width = 1160
    post_max_width = max(640, min(2400, post_max_width))
    try:
        post_padding_pct = int(site.frontend_blog_post_padding_pct) if site else 5
    except (TypeError, ValueError):
        post_padding_pct = 5
    post_padding_pct = max(0, min(20, post_padding_pct))
    # The preview banner shows on any unpublished state — drafts AND
    # archives — so the editor isn't surprised that an archived post
    # is reachable via the public URL.
    is_preview = can_preview and (post.is_draft or post.is_archived)
    preview_state = ("draft" if post.is_draft
                     else ("archived" if post.is_archived else ""))
    return render_template(tpl["partial"], post=post,
                           tpl_style=tpl_style,
                           tpl_dynbg_key=tpl_dynbg_key,
                           tpl_dynbg_overlay=tpl_dynbg_overlay,
                           tpl_dynbg_colors=tpl_dynbg_colors,
                           tpl_dynbg_config=tpl_dynbg_config,
                           related=related,
                           all_categories=all_categories,
                           show_related_widget=show_related_widget,
                           show_categories_widget=show_categories_widget,
                           post_width_mode=post_width_mode,
                           post_max_width=post_max_width,
                           post_padding_pct=post_padding_pct,
                           is_preview=is_preview,
                           preview_state=preview_state,
                           **og,
                           **ctx)


@bp.route("/blog/category/<slug>")
def blog_category_view(slug):
    """Pretty-URL alternative to /blog?category=<slug>. 302s into the
    canonical list view so existing list templates don't have to
    duplicate logic — the active filter, header, and meta all flow
    through one route."""
    return redirect(url_for("frontend.blog_list", category=slug))


@bp.route("/blog/tag/<slug>")
def blog_tag_view(slug):
    """Pretty-URL alternative to /blog?tag=<slug>."""
    return redirect(url_for("frontend.blog_list", tag=slug))


@bp.route("/api/live-meeting")
def api_live_meeting():
    """Current live-meeting state for the utility bar's poller, so the
    LIVE badge appears / updates / clears without a page refresh.

    Public — meeting names already show on the public site. Gated on the
    admin's live-badge toggle (``show_live``): returns ``{"live": false}``
    when the badge is disabled or no online/hybrid meeting is live right
    now. The response is small and uncached (the global after-request hook
    already stamps non-asset paths ``no-store``)."""
    from flask import jsonify
    from .utility_bar import utility_bar_context, current_live_meeting
    site = _site()
    ub = utility_bar_context(site)
    if not ub.get("show_live"):
        return jsonify(live=False)
    lm = current_live_meeting(site)
    if not lm or not lm.get("meeting"):
        return jsonify(live=False)
    return jsonify(live=True,
                   name=lm["meeting"].name,
                   join_url=lm.get("join_url") or None)


@bp.route("/api/search-index")
def api_search_index():
    """JSON feed for the frontend-wide search modal: every public
    surface the site exposes (meetings, events, announcements, archive,
    stories, blog posts, libraries, pages, sections) flattened into
    search-blob form by the registered sources in ``app/search.py``.
    Cached one-shot per page load on the client (modal fetches once on
    first open).

    Response is gzip-compressed when the client's ``Accept-Encoding``
    advertises gzip — every modern browser does, so the payload lands
    at roughly a fifth of its raw size on the wire. The handler
    short-circuits to plain JSON when gzip isn't accepted so curl /
    older clients still work.
    """
    from flask import jsonify, make_response
    import gzip
    from .search import build_search_index
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    payload = jsonify({"items": build_search_index(site)})
    accept_enc = (request.headers.get("Accept-Encoding") or "").lower()
    if "gzip" not in accept_enc:
        return payload
    body = gzip.compress(payload.get_data(), compresslevel=6)
    resp = make_response(body)
    resp.headers["Content-Encoding"] = "gzip"
    resp.headers["Content-Type"] = "application/json"
    resp.headers["Content-Length"] = str(len(body))
    # Tell caches (browser, future CDN) that the response varies by
    # Accept-Encoding so an identity-cached copy is never served to a
    # gzip-asking client (and vice versa).
    resp.headers["Vary"] = "Accept-Encoding"
    return resp


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
                          Post.is_draft.is_(False),
                          Post.is_pending_review.is_(False))
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
    _tpl_settings = template_settings(site, "event", tpl["key"])
    tpl_style = template_css_vars(_tpl_settings)
    tpl_dynbg_key = _tpl_settings.get("bg_dynamic_key")
    tpl_dynbg_overlay = _tpl_settings.get("bg_dynbg_overlay")
    tpl_dynbg_colors = _tpl_settings.get("bg_dynbg_colors") or []
    # Full per-template dynbg config — carries the randomize
    # flags / scope / noise knobs / animate state alongside the
    # base key + overlay + palette so each entity-detail partial
    # has every dimension the apply-partial expects. Earlier
    # only key/overlay/colors were threaded through, so the
    # randomize / freeze-movement settings persisted in JSON
    # but never applied on the public render.
    tpl_dynbg_config = {
        "overlay": tpl_dynbg_overlay,
        "colors": tpl_dynbg_colors,
        "overlay_scope": _tpl_settings.get("bg_dynbg_overlay_scope"),
        "overlay_size": _tpl_settings.get("bg_dynbg_overlay_size"),
        "overlay_intensity": _tpl_settings.get("bg_dynbg_overlay_intensity"),
        "randomize_colors": _tpl_settings.get("bg_dynbg_randomize_colors", False),
        "randomize_positions": _tpl_settings.get("bg_dynbg_randomize_positions", False),
        "animate": _tpl_settings.get("bg_dynbg_animate", True),

        "pastel_light": _tpl_settings.get("bg_dynbg_pastel_light", False),
        "knobs": _tpl_settings.get("bg_dynbg_knobs", {}),
    }
    og = _page_og(site, title=ev.title,
                  description=ev.summary or ev.body,
                  image_url=(url_for("public.post_featured_image", pid=ev.id, _external=True)
                             if ev.featured_image_filename else None))
    return render_template(tpl["partial"], event=ev, tpl_style=tpl_style, tpl_dynbg_key=tpl_dynbg_key, tpl_dynbg_overlay=tpl_dynbg_overlay, tpl_dynbg_colors=tpl_dynbg_colors, tpl_dynbg_config=tpl_dynbg_config,
                           is_in_archive=False, **og, **ctx)


@bp.route("/event/<slug>/calendar.ics")
def event_calendar_ics(slug):
    """One-tap "Add to Calendar" download for an event post. Same slug-
    resolution logic as ``event_detail`` (current → history → 404).
    Single VEVENT (no RRULE — events are one-time)."""
    from .calendar_export import event_to_ics
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "posts_enabled", True):
        abort(404)
    candidates = (Post.query
                  .filter(Post.is_event.is_(True),
                          Post.is_draft.is_(False),
                          Post.is_pending_review.is_(False))
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
                return redirect(url_for("frontend.event_calendar_ics",
                                        slug=target.public_slug), code=301)
        abort(404)
    base = request.url_root or ""
    body = event_to_ics(ev, site, base_url=base)
    fname = (ev.public_slug or "event") + ".ics"
    resp = current_app.response_class(body, mimetype="text/calendar")
    resp.headers["Content-Disposition"] = 'attachment; filename="' + fname + '"'
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/announcement/<slug>")
def announcement_detail(slug):
    """Public announcement detail page. Reuses the EVENT_TEMPLATES
    catalog (classic/poster/minimal/timeline) so the admin's chosen
    detail template renders both pure announcements and events. Pure
    announcements simply have no event_starts_at / location / Zoom —
    the detail templates already gate those panels behind `{% if %}`
    checks so they collapse gracefully."""
    from .routes import _auto_archive_events
    _auto_archive_events()
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "posts_enabled", True):
        abort(404)
    candidates = (Post.query
                  .filter(Post.is_announcement.is_(True),
                          Post.is_draft.is_(False),
                          Post.is_pending_review.is_(False))
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
    _tpl_settings = template_settings(site, "event", tpl["key"])
    tpl_style = template_css_vars(_tpl_settings)
    tpl_dynbg_key = _tpl_settings.get("bg_dynamic_key")
    tpl_dynbg_overlay = _tpl_settings.get("bg_dynbg_overlay")
    tpl_dynbg_colors = _tpl_settings.get("bg_dynbg_colors") or []
    # Full per-template dynbg config — carries the randomize
    # flags / scope / noise knobs / animate state alongside the
    # base key + overlay + palette so each entity-detail partial
    # has every dimension the apply-partial expects. Earlier
    # only key/overlay/colors were threaded through, so the
    # randomize / freeze-movement settings persisted in JSON
    # but never applied on the public render.
    tpl_dynbg_config = {
        "overlay": tpl_dynbg_overlay,
        "colors": tpl_dynbg_colors,
        "overlay_scope": _tpl_settings.get("bg_dynbg_overlay_scope"),
        "overlay_size": _tpl_settings.get("bg_dynbg_overlay_size"),
        "overlay_intensity": _tpl_settings.get("bg_dynbg_overlay_intensity"),
        "randomize_colors": _tpl_settings.get("bg_dynbg_randomize_colors", False),
        "randomize_positions": _tpl_settings.get("bg_dynbg_randomize_positions", False),
        "animate": _tpl_settings.get("bg_dynbg_animate", True),

        "pastel_light": _tpl_settings.get("bg_dynbg_pastel_light", False),
        "knobs": _tpl_settings.get("bg_dynbg_knobs", {}),
    }
    # Pass the post in as `event` so the existing event-detail templates
    # (which all reference `event.*`) render unchanged.
    og = _page_og(site, title=ann.title,
                  description=ann.summary or ann.body,
                  image_url=(url_for("public.post_featured_image", pid=ann.id, _external=True)
                             if ann.featured_image_filename else None))
    return render_template(tpl["partial"], event=ann, tpl_style=tpl_style, tpl_dynbg_key=tpl_dynbg_key, tpl_dynbg_overlay=tpl_dynbg_overlay, tpl_dynbg_colors=tpl_dynbg_colors, tpl_dynbg_config=tpl_dynbg_config,
                           is_in_archive=False, **og, **ctx)


@bp.route("/contact")
@public_section("Contact us", gate=lambda s: bool(getattr(s, "contact_form_enabled", False)))
def contact():
    """Public contact-us page. Honors the ``contact_form_enabled``
    SiteSetting toggle: when off the page returns 404 (matches every
    other admin-controlled public surface)."""
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "contact_form_enabled", False):
        abort(404)
    # When the admin set a custom slug, the canonical /contact path
    # redirects to /<custom-slug>. The page_detail catch-all calls
    # this function directly so request.path will be /<custom-slug>
    # in that branch and this check skips.
    _custom = (site.contact_form_slug or "").strip()
    if _custom and request.path.rstrip("/") == "/contact":
        return redirect(url_for("frontend.page_detail", slug=_custom))
    ctx = _frontend_context(site)
    return render_template("frontend/contact.html", **ctx)


@bp.route("/contact/submit", methods=["POST"])
def contact_submit():
    """Process a contact-form submission.

    Verifies Turnstile when enabled, persists a ContactSubmission
    row, and emails the public information chair (or whichever
    address the admin configured in ``contact_form_to``) with the
    visitor's email set as the ``Reply-To`` header so the admin
    can reply directly from their inbox. Mail failures don't block
    the submission — the row is still saved and the admin can chase
    the message in the Contact Form admin.
    """
    from flask import flash, current_app
    from .auth import _verify_turnstile
    from .mail import send_mail
    from .models import db as _db, ContactSubmission

    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "contact_form_enabled", False):
        abort(404)

    f = request.form
    # Honeypot — non-empty value means a bot. Silently redirect with
    # the success flash so the bot can't tell its submission was
    # rejected and try harder. No row written; no email sent.
    honeypot = (f.get("website") or "").strip()
    if honeypot:
        success_msg = (getattr(site, "contact_form_success_message", None)
                       or "Thanks — your message has been sent.")
        flash(success_msg, "success")
        return redirect(url_for("frontend.contact"))

    name = (f.get("name") or "").strip()[:200]
    email = (f.get("email") or "").strip()[:255]
    phone = (f.get("phone") or "").strip()[:64] or None
    subject = (f.get("subject") or "").strip()[:255] or None
    message = (f.get("message") or "").strip()[:6000]
    subj_required = bool(getattr(site, "contact_form_subject_required", False))

    if not name or not email or not message:
        flash("Name, email, and message are required.", "danger")
        return redirect(url_for("frontend.contact"))
    if subj_required and not subject:
        flash("Please include a subject for your message.", "danger")
        return redirect(url_for("frontend.contact"))
    # Cheap email sanity check — anything past this would be caught
    # by the SMTP server anyway, but we'd rather not write rows that
    # are obvious typos.
    if "@" not in email or "." not in email.split("@", 1)[-1]:
        flash("That email address doesn't look quite right — double-check it?", "danger")
        return redirect(url_for("frontend.contact"))

    if site.turnstile_enabled:
        token = f.get("cf-turnstile-response", "")
        ok, err = _verify_turnstile(site, token, request.remote_addr)
        if not ok:
            flash(err or "Security check failed — please try again.", "danger")
            return redirect(url_for("frontend.contact"))

    sub = ContactSubmission(
        name=name, email=email, phone=phone, subject=subject,
        message=message, ip_address=(request.remote_addr or "")[:64],
    )
    _db.session.add(sub)
    _db.session.commit()

    # Recipients fall back through the most specific to the most
    # generic admin contact: explicit contact_form_to → PIC email →
    # access-request notifications. That way an install that has
    # already configured PIC details but never touched the Contact
    # Form section still routes mail somewhere sensible.
    recipients = (getattr(site, "contact_form_to", None)
                  or getattr(site, "pic_email", None)
                  or getattr(site, "access_request_to", None) or "").strip()
    if site.smtp_host and recipients:
        # Build a structured plain-text email. Visitor's email is
        # echoed in the body too (in addition to the Reply-To
        # header) so admins reading the message on a phone can
        # tap the address even when their client buries Reply-To.
        site_label = (site.frontend_title or "Trusted Servants")
        subject_line = f"[{site_label} contact] " + (subject or f"Message from {name}")
        lines = [
            f"A new contact-form message has come in via the public {site_label} site.",
            "",
            "Reply directly to this email — your reply will go to the visitor.",
            "",
            f"Name:    {name}",
            f"Email:   {email}",
        ]
        if phone:
            lines.append(f"Phone:   {phone}")
        if subject:
            lines.append(f"Subject: {subject}")
        if sub.ip_address:
            lines.append(f"IP:      {sub.ip_address}")
        lines += ["", "─" * 60, "", message, "", "─" * 60]
        try:
            review_url = url_for("main.contact_form", _external=True)
            lines += ["", f"View in the admin: {review_url}"]
        except Exception:  # noqa: BLE001 — url_for can fail outside request ctx
            pass
        body_text = "\n".join(lines)

        # Override the From + Reply-To so admins can hit Reply in
        # their mail client and have it route straight back to the
        # visitor. send_mail() always writes From from SMTP settings
        # and doesn't accept extras yet, so we hand-build the message
        # below. Falls back to send_mail() on failure so an install
        # that customised send_mail() doesn't lose the email path.
        ok, err = _send_with_reply_to(site, recipients, subject_line,
                                      body_text, reply_to=email,
                                      reply_to_name=name)
        if not ok:
            # Fall back to the standard helper — drops Reply-To but
            # still gets the message out.
            ok, err = send_mail(site, recipients, subject_line, body_text)
        sub.email_sent = bool(ok)
        sub.email_error = (err or None) if not ok else None
        _db.session.commit()

    success_msg = (getattr(site, "contact_form_success_message", None)
                   or "Thanks — your message has been sent. We'll be in touch shortly.")
    flash(success_msg, "success")
    return redirect(url_for("frontend.contact"))


@bp.route("/contactlist")
@bp.route("/contactlist.pdf", endpoint="recovery_contacts_pdf")
@public_section("Recovery Contacts", gate=lambda s: bool(getattr(s, "recovery_contacts_enabled", False)))
def recovery_contacts():
    """Public Recovery Contacts directory. Renders the approved entries
    plus a submission form. Honors the ``recovery_contacts_enabled`` toggle —
    returns 404 when the module is off, like every other admin-gated
    surface. (Internal identifiers keep the legacy ``recovery_contacts`` name.)

    Two endpoints share this view (mirrors the printlist pattern):
      * ``/contactlist``     — the themed page (directory + search + form).
      * ``/contactlist.pdf`` — a clean, branded WeasyPrint render of the
                               directory for download/printing. Honors an
                               optional ``?q=`` filter so a PDF of a
                               searched view matches what's on screen."""
    from .models import RecoveryContact
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "recovery_contacts_enabled", False):
        abort(404)
    entries = (RecoveryContact.query
               .filter_by(approved=True)
               .order_by(RecoveryContact.name.asc())
               .all())

    if request.endpoint == "frontend.recovery_contacts_pdf":
        # Optional search filter, matching the on-screen client-side search
        # (name / public phone / public email, case-insensitive).
        q = (request.args.get("q") or "").strip().lower()
        if q:
            def _hit(e):
                hay = " ".join(filter(None, [e.name, e.public_phone, e.public_email])).lower()
                return q in hay
            entries = [e for e in entries if _hit(e)]
        from .timezone import now_in
        import re as _re
        heading = (getattr(site, "recovery_contacts_heading", None) or "Recovery Contacts")
        site_title = (site.frontend_title if site else None) or "Trusted Servants"
        # Public URL shown on the PDF header, with the scheme + trailing
        # slash stripped (e.g. "riverside.org"). Falls back to the request
        # host when no canonical Site URL is configured.
        _purl = (getattr(site, "site_url", None) or "").strip() or request.url_root
        display_url = _re.sub(r"^https?://", "", _purl).rstrip("/")
        # Full canonical URL of the public directory page, e.g.
        # "https://riverside.org/contactlist" — shown on listings that are
        # reachable only via the site's "Contact me" button.
        _base = _purl.rstrip("/")
        if not _re.match(r"^https?://", _base):
            _base = "https://" + _base
        contact_url = _base + url_for("frontend.recovery_contacts")
        generated_at = now_in(site)
        html = render_template("frontend/recovery_contacts_pdf.html",
                               site=site, entries=entries, heading=heading,
                               frontend_title=site_title, display_url=display_url,
                               contact_url=contact_url,
                               query=q, generated_at=generated_at)
        from weasyprint import HTML
        from flask import current_app
        pdf_bytes = HTML(string=html, base_url=request.url_root).write_pdf()
        # Filename convention: <site-name-hyphenated>-Recovery-Contacts_<yyyymmdd>.pdf
        name_slug = _re.sub(r"[^A-Za-z0-9]+", "-", site_title).strip("-") or "Site"
        filename = f"{name_slug}-Recovery-Contacts_{generated_at.strftime('%Y%m%d')}.pdf"
        resp = current_app.make_response(pdf_bytes)
        resp.headers["Content-Type"] = "application/pdf"
        resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp

    ctx = _frontend_context(site)
    return render_template("frontend/recovery_contacts.html", entries=entries, **ctx)


@bp.route("/phonelist")
def recovery_contacts_legacy_redirect():
    """The page moved from /phonelist to /contactlist — keep any old
    links / bookmarks / nav items working by redirecting."""
    return redirect(url_for("frontend.recovery_contacts"))


@bp.route("/contactlist/submit", methods=["POST"])
def recovery_contacts_submit():
    """Process a public Recovery Contacts submission.

    Runs the honeypot + Turnstile guards, then writes an UNAPPROVED
    ``RecoveryContact`` row (invisible to the public until an admin
    approves it) and optionally emails the configured recipients so the
    admin knows there's an entry awaiting review. The submitter picks a
    starting phone/email display preference; the admin can override it.
    """
    from datetime import datetime as _dt, timedelta as _td
    from flask import flash
    from .auth import _verify_turnstile
    from .mail import send_mail
    from .models import (db as _db, RecoveryContact, log_recovery_contact,
                         record_recovery_contact_abuse)

    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "recovery_contacts_enabled", False):
        abort(404)

    success_msg = (getattr(site, "recovery_contacts_success_message", None)
                   or "Thanks — your entry has been submitted and will appear once an admin approves it.")

    f = request.form
    # Honeypot — a non-empty hidden field means a bot. Silently flash the
    # success message so it can't tell it was rejected; no row written.
    if (f.get("website") or "").strip():
        flash(success_msg, "success")
        return redirect(url_for("frontend.recovery_contacts"))

    name = (f.get("name") or "").strip()[:200]
    email = (f.get("email") or "").strip()[:255]
    phone = (f.get("phone") or "").strip()[:64]
    # Submitter's starting display preference. The public form always
    # renders both checkboxes pre-checked, so an unchecked box arrives
    # as an ABSENT field — read absence as "hide", which both honours
    # the visitor's choice and is the privacy-preserving default.
    show_phone = f.get("show_phone") == "1"
    show_email = f.get("show_email") == "1"
    available_to_sponsor = f.get("available_to_sponsor") == "1"
    contact_enabled = f.get("contact_enabled") == "1"
    wants_update = f.get("wants_update") == "1"
    wants_removal = f.get("wants_removal") == "1"

    if not name:
        flash("Your name is required.", "danger")
        return redirect(url_for("frontend.recovery_contacts"))
    # Email is mandatory — it's how the removal confirmation is sent and
    # how the admin reaches the person.
    if not email:
        flash("An email address is required.", "danger")
        return redirect(url_for("frontend.recovery_contacts"))
    if "@" not in email or "." not in email.split("@", 1)[-1]:
        flash("That email address doesn't look quite right — double-check it?", "danger")
        return redirect(url_for("frontend.recovery_contacts"))

    if site.turnstile_enabled:
        token = f.get("cf-turnstile-response", "")
        ok, err = _verify_turnstile(site, token, request.remote_addr)
        if not ok:
            flash(err or "Security check failed — please try again.", "danger")
            return redirect(url_for("frontend.recovery_contacts"))

    # Update + removal requests are matched to the existing listing by
    # EMAIL (case-insensitive). Email is mandatory, and it's the stable
    # key the confirmation link is tied to.
    needs_confirm = wants_update or wants_removal
    matched_id = None
    if needs_confirm:
        email_n = email.strip().lower()
        if email_n:
            for cand in RecoveryContact.query.filter_by(approved=True).all():
                if (cand.email or "").strip().lower() == email_n:
                    matched_id = cand.id
                    break

    # ── Anti-abuse on the self-service update/removal flow ──────────────
    # Both checks need the matched (target) listing + the requestor's IP.
    target = RecoveryContact.query.get(matched_id) if matched_id else None
    now = _dt.utcnow()
    req_ip = (request.remote_addr or "")[:64]
    if needs_confirm and target is not None:
        # 7-day disavow lock — refuses BOTH update and removal requests
        # after the listing owner reported a prior request as not theirs.
        if target.requests_locked_until and target.requests_locked_until > now:
            kind_word = "removal" if wants_removal else "update"
            record_recovery_contact_abuse(
                "disavowed", target, req_ip,
                f"Blocked {kind_word} request while the listing is locked "
                "(owner previously reported a request as not theirs).",
                locked_until=target.requests_locked_until)
            log_recovery_contact(
                "request_blocked",
                f"{kind_word.capitalize()} request blocked — listing locked after a disavowed request",
                entry_name=target.name, actor="Visitor", ip_address=req_ip)
            flash("This listing is temporarily locked and can't accept update or "
                  "removal requests right now. If this is your listing, please "
                  "contact us directly.", "danger")
            return redirect(url_for("frontend.recovery_contacts"))
        # 24-hour update rate-limit (updates only). Discard the 2nd update
        # — its data is never ingested — and flag it.
        if (wants_update and target.last_update_request_at
                and (now - target.last_update_request_at) < _td(hours=24)):
            record_recovery_contact_abuse(
                "rate_limited", target, req_ip,
                "Second update request within 24 hours — discarded.")
            log_recovery_contact(
                "update_rate_limited",
                "Update request blocked — submitted more than once in 24 hours",
                entry_name=target.name, actor="Visitor", ip_address=req_ip)
            flash("You can only request an update to a listing once every 24 hours. "
                  "Please wait and try again later.", "danger")
            return redirect(url_for("frontend.recovery_contacts"))

    # Update + removal are both double opt-in: stash a confirmation token
    # and email the submitter a link. Clicking it auto-applies the change
    # (no admin approval). The request still shows in the admin panel so
    # an admin can apply it manually if the person never confirms.
    confirm_token = None
    if needs_confirm:
        import secrets
        confirm_token = secrets.token_urlsafe(32)

    entry = RecoveryContact(
        name=name, email=email or None, phone=phone or None,
        show_phone=show_phone, show_email=show_email,
        available_to_sponsor=available_to_sponsor,
        contact_enabled=contact_enabled,
        wants_update=wants_update, wants_removal=wants_removal,
        removal_token=confirm_token,
        matched_entry_id=matched_id,
        approved=False, ip_address=(request.remote_addr or "")[:64],
    )
    _db.session.add(entry)
    _db.session.commit()

    # Stamp the update rate-limit clock on the matched listing so a second
    # update within 24 h is rejected above.
    if wants_update and target is not None:
        target.last_update_request_at = now
        _db.session.commit()

    site_label = (site.frontend_title or "Trusted Servants")

    if needs_confirm:
        # Email the submitter a confirmation link (the opt-in mechanism)
        # plus a "this wasn't me" link that discards the request and locks
        # the listing against further requests for 7 days.
        if site.smtp_host and email:
            try:
                confirm_url = url_for("frontend.recovery_contacts_confirm",
                                      token=confirm_token, _external=True)
                disavow_url = url_for("frontend.recovery_contacts_disavow",
                                      token=confirm_token, _external=True)
            except Exception:  # noqa: BLE001
                _root = request.url_root.rstrip("/")
                confirm_url = _root + "/contactlist/confirm/" + confirm_token
                disavow_url = _root + "/contactlist/disavow/" + confirm_token
            if wants_removal:
                subj = "Confirm your removal request"
                msg = [f"Hi {name},", "",
                       f"We received a request to remove you from the {site_label} Recovery Contacts list.",
                       "Click the link below to confirm — you'll be removed automatically:", "",
                       confirm_url]
            else:
                subj = "Confirm your listing update"
                msg = [f"Hi {name},", "",
                       f"We received an update to your {site_label} Recovery Contacts listing.",
                       "Click the link below to confirm — your listing updates automatically:", "",
                       confirm_url]
            msg += ["", "Didn't request this?",
                    "Someone may have submitted it without your permission. Click below to "
                    "report it — the request will be discarded and your listing locked "
                    "against further changes for 7 days:", "",
                    disavow_url]
            send_mail(site, email, subj, "\n".join(msg))
        # NOTE: removal requests do NOT email the admin at submission time.
        # The admin is only notified once the person clicks the confirmation
        # link (see recovery_contacts_confirm) — so a bad actor can't get
        # someone removed, or even prompt the admin to act, without the real
        # owner confirming. Gated by the removal-alerts toggle there.
        if wants_removal:
            success_msg = ("Thanks — we've emailed you a confirmation link. Click it to confirm, "
                           "and you'll be removed from the list automatically.")
        else:
            success_msg = ("Thanks — we've emailed you a confirmation link. Click it to confirm, "
                           "and your listing updates automatically.")
    else:
        # Brand-new entry. Surfaces as a chip in the admin panel; only
        # send an admin email when the new-submission alert is on.
        recipients = (getattr(site, "recovery_contacts_to", None)
                      or getattr(site, "access_request_to", None) or "").strip()
        if getattr(site, "recovery_contacts_email_alerts", False) and site.smtp_host and recipients:
            subject_line = f"New Recovery Contacts entry from {name}"
            lines = [f"A new Recovery Contacts entry has been submitted on the public {site_label} site.",
                     "It is awaiting your approval and is not yet visible to the public.",
                     "", f"Name:  {name}"]
            if phone:
                lines.append(f"Phone: {phone}" + ("" if show_phone else "  (submitter asked to hide)"))
            if email:
                lines.append(f"Email: {email}" + ("" if show_email else "  (submitter asked to hide)"))
            if available_to_sponsor:
                lines.append("Available to sponsor: yes")
            try:
                lines += ["", f"Review: {url_for('main.recovery_contacts', _external=True)}"]
            except Exception:  # noqa: BLE001
                pass
            send_mail(site, recipients, subject_line, "\n".join(lines))

    # Audit log.
    _ip = (request.remote_addr or "")[:64]
    _sent = " — confirmation link sent" if (site.smtp_host and email) else ""
    if wants_removal:
        log_recovery_contact("removal_requested", f"Removal requested{_sent}",
                             entry_name=name, actor="Visitor", ip_address=_ip)
    elif wants_update:
        log_recovery_contact("update_requested", f"Update requested{_sent}",
                             entry_name=name, actor="Visitor", ip_address=_ip)
    else:
        log_recovery_contact("submitted", "New listing submitted",
                             entry_name=name, actor="Visitor", ip_address=_ip)

    flash(success_msg, "success")
    return redirect(url_for("frontend.recovery_contacts"))


@bp.route("/contactlist/confirm/<token>")
@bp.route("/contactlist/confirm-removal/<token>", endpoint="recovery_contacts_confirm_removal")
def recovery_contacts_confirm(token):
    """Landing page for the confirmation link emailed to the submitter for
    an update or a removal. Clicking it **auto-applies** the change — no
    admin approval: a removal deletes the matched entry, an update writes
    the submitted values onto the matched entry (or publishes the request
    as a new listing if nothing matched). The request row is then cleared.
    Until confirmed, the request stays visible in the admin panel so an
    admin can apply it by hand if the person never clicks."""
    from datetime import datetime as _dt
    from .models import db as _db, RecoveryContact, log_recovery_contact
    from .mail import send_mail
    site = _site()
    if not site:
        abort(404)
    entry = RecoveryContact.query.filter_by(removal_token=token).first() if token else None
    if entry is None or not (entry.wants_update or entry.wants_removal):
        return _render_rc_confirm(site, status="invalid", kind=None, name=None)

    is_removal = bool(entry.wants_removal)
    kind = "removal" if is_removal else "update"
    name = entry.name
    if entry.removal_confirmed_at:
        return _render_rc_confirm(site, status="already", kind=kind, name=name)

    entry.removal_confirmed_at = _dt.utcnow()
    target = entry.matched_entry

    if is_removal:
        # Auto-remove: delete the matched entry + the request row.
        _db.session.delete(entry)
        if target is not None:
            RecoveryContact.query.filter_by(matched_entry_id=target.id).update(
                {"matched_entry_id": None})
            _db.session.delete(target)
        _db.session.commit()
        log_recovery_contact("removal_confirmed",
                             "Removal confirmed via email link — entry deleted automatically",
                             entry_name=name, actor="Visitor")
        # Optional admin FYI that the removal went through.
        recipients = (getattr(site, "recovery_contacts_to", None)
                      or getattr(site, "access_request_to", None) or "").strip()
        if getattr(site, "recovery_contacts_removal_alerts", False) and site.smtp_host and recipients:
            site_label = (site.frontend_title or "Trusted Servants")
            send_mail(site, recipients,
                      f"Recovery Contacts removal confirmed — {name}",
                      "\n".join([f"{name} confirmed their removal from the {site_label} "
                                 "Recovery Contacts list and has been taken off it automatically.",
                                 "", "No action needed."]))
    else:
        # Auto-apply update onto the matched entry (or publish as new).
        if target is not None:
            target.name = entry.name
            target.phone = entry.phone
            target.email = entry.email
            target.show_phone = entry.show_phone
            target.show_email = entry.show_email
            target.available_to_sponsor = entry.available_to_sponsor
            target.contact_enabled = entry.contact_enabled
            target.approved = True
            target.approved_at = _dt.utcnow()
            _db.session.delete(entry)
            _db.session.commit()
            log_recovery_contact("update_confirmed",
                                 "Listing update confirmed via email link — applied automatically",
                                 entry_name=name, actor="Visitor")
        else:
            # Nothing matched — confirming publishes it as a new listing.
            entry.wants_update = False
            entry.removal_token = None
            entry.approved = True
            entry.approved_at = _dt.utcnow()
            _db.session.commit()
            log_recovery_contact("update_confirmed",
                                 "Update confirmed via email link — no match, published as a new listing",
                                 entry_name=name, actor="Visitor")

    return _render_rc_confirm(site, status="confirmed", kind=kind, name=name)


def _render_rc_confirm(site, status, kind, name):
    ctx = _frontend_context(site)
    return render_template("frontend/recovery_contacts_confirm.html",
                           status=status, kind=kind, confirm_name=name, **ctx)


@bp.route("/contactlist/disavow/<token>")
def recovery_contacts_disavow(token):
    """The "I didn't submit this" link in a confirmation email. Discards
    the pending update/removal request without applying it, locks the
    matched listing against further update/removal requests for 7 days,
    and records the requestor's IP as a flagged abuse event so an admin
    can block it from Watchtower."""
    from types import SimpleNamespace
    from datetime import datetime as _dt, timedelta as _td
    from .models import (db as _db, RecoveryContact, log_recovery_contact,
                         record_recovery_contact_abuse)
    from .mail import send_mail
    site = _site()
    if not site:
        abort(404)
    entry = RecoveryContact.query.filter_by(removal_token=token).first() if token else None
    if entry is None or not (entry.wants_update or entry.wants_removal):
        return _render_rc_confirm(site, status="invalid", kind=None, name=None)

    kind = "removal" if entry.wants_removal else "update"
    name = entry.name
    if entry.removal_confirmed_at:
        # Already confirmed/applied — too late to disavow.
        return _render_rc_confirm(site, status="already", kind=kind, name=name)

    target = entry.matched_entry
    req_ip = (entry.ip_address or "")        # IP that filed the request
    snap_email = entry.email
    lock_until = _dt.utcnow() + _td(days=7)

    if target is not None:
        target.requests_locked_until = lock_until
    # Discard the pending request — never apply it.
    _db.session.delete(entry)
    _db.session.commit()

    abuse_target = target if target is not None else SimpleNamespace(
        id=None, name=name, email=snap_email)
    record_recovery_contact_abuse(
        "disavowed", abuse_target, req_ip,
        f"Listing owner reported a {kind} request as not theirs — request "
        "discarded; listing locked against changes for 7 days.",
        locked_until=lock_until)
    log_recovery_contact(
        "disavowed",
        f"{kind.capitalize()} request reported as not submitted by the owner — "
        "discarded; listing locked for 7 days",
        entry_name=name, actor="Visitor", ip_address=req_ip)

    # Optional admin alert (reuses the removal-alerts toggle).
    recipients = (getattr(site, "recovery_contacts_to", None)
                  or getattr(site, "access_request_to", None) or "").strip()
    if getattr(site, "recovery_contacts_removal_alerts", False) and site.smtp_host and recipients:
        site_label = (site.frontend_title or "Trusted Servants")
        send_mail(site, recipients,
                  f"Recovery Contacts: disavowed {kind} request — {name}",
                  "\n".join([
                      f"A {kind} request for the {site_label} Recovery Contacts "
                      f"listing \"{name}\" was reported as not submitted by the owner.",
                      "", f"Requestor IP: {req_ip or 'unknown'}",
                      "The request has been discarded and the listing locked against "
                      "further update/removal requests for 7 days.",
                      "", "Open Watchtower to review it and block the IP if needed."]))
    return _render_rc_confirm(site, status="disavowed", kind=kind, name=name)


@bp.route("/contactlist/contact", methods=["POST"])
def recovery_contacts_contact():
    """Relay a visitor's message to a listed person who opted into
    email contact. The recipient's address is never exposed — the email
    is sent server-side to ``entry.email`` with Reply-To set to the
    sender, so the person can reply directly. Bumps ``contact_count``."""
    from flask import flash
    from .auth import _verify_turnstile
    from .mail import send_mail
    from .models import db as _db, RecoveryContact, log_recovery_contact

    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "recovery_contacts_enabled", False):
        abort(404)
    back = redirect(url_for("frontend.recovery_contacts"))
    f = request.form

    # Honeypot — silently accept so a bot can't tell.
    if (f.get("website") or "").strip():
        flash("Thanks — your message has been sent.", "success")
        return back

    try:
        eid = int(f.get("eid") or 0)
    except (ValueError, TypeError):
        eid = 0
    entry = RecoveryContact.query.filter_by(id=eid, approved=True).first() if eid else None
    if entry is None or not entry.contact_enabled or not entry.email:
        flash("Sorry — that person isn't reachable through the site.", "danger")
        return back

    vname = (f.get("name") or "").strip()[:200]
    vemail = (f.get("email") or "").strip()[:255]
    vmsg = (f.get("message") or "").strip()[:5000]
    if not vname or not vemail or not vmsg:
        flash("Please include your name, email, and a message.", "danger")
        return back
    if "@" not in vemail or "." not in vemail.split("@", 1)[-1]:
        flash("That email address doesn't look quite right — double-check it?", "danger")
        return back

    if site.turnstile_enabled:
        ok, err = _verify_turnstile(site, f.get("cf-turnstile-response", ""), request.remote_addr)
        if not ok:
            flash(err or "Security check failed — please try again.", "danger")
            return back

    if not site.smtp_host:
        flash("Contact isn't available right now — please try again later.", "danger")
        return back

    site_label = (site.frontend_title or "Trusted Servants")
    subject = f"{vname} would like to connect with you"
    body = "\n".join([
        f"Someone reached out to you through the {site_label} contact list.",
        "Reply directly to this email to respond — it goes straight to them.",
        "",
        f"From: {vname} <{vemail}>",
        "", "─" * 56, "", vmsg, "", "─" * 56,
    ])
    ok, err = _send_with_reply_to(site, entry.email, subject, body,
                                  reply_to=vemail, reply_to_name=vname)
    if not ok:
        ok, err = send_mail(site, entry.email, subject, body)
    if not ok:
        flash("Sorry — we couldn't send your message. Please try again later.", "danger")
        return back

    entry.contact_count = (entry.contact_count or 0) + 1
    _db.session.commit()
    log_recovery_contact("contacted", f"Contacted via the site by {vname} <{vemail}>",
                         entry_name=entry.name, actor="Visitor",
                         ip_address=(request.remote_addr or "")[:64])
    flash(f"Thanks — your message has been sent to {entry.name}.", "success")
    return back


def _render_custom_form(cf, ctx, errors=None, values=None, success_message=None):
    """Render a CustomForm through the shared "Forms" template chrome —
    the same dispatcher (``frontend/submission.html``) the events /
    announcements submission form uses. Heading / subheading / intro
    come from the CustomForm row; the rest of the templated chrome
    (variant choice, dynamic background, width mode, padding) reads
    from the same SiteSetting columns the submission form is tuned by,
    so flipping the site-wide template choice on the Templates admin
    page swaps EVERY form's look in step.

    ``errors`` is an optional ``{field_name: message}`` dict from a
    failed POST; ``values`` is the previously-typed payload so the
    page re-renders without losing the operator's input.
    ``success_message`` non-None means we're on the post-submit
    thank-you path (form body suppressed; thank-you copy rendered
    where the form would have sat)."""
    import json as _json
    blocks = []
    if cf.blocks_json:
        try:
            blocks = _json.loads(cf.blocks_json)
        except (ValueError, TypeError):
            blocks = []
    if not isinstance(blocks, list):
        blocks = []

    # Pull the submission-form template settings off SiteSetting so the
    # CustomForm renders with the operator's chosen variant + dynbg +
    # width / padding. Mirrors what main.submission_form() builds in
    # routes.py — kept here so the public form path doesn't depend on
    # the admin-side helper.
    site = ctx.get("site")
    tpl = _template_meta(SUBMISSION_FORM_TEMPLATES,
                         (site.frontend_submission_form_template if site else None) or "classic")
    tpl_settings_dict = template_settings(site, "submission_form", tpl["key"]) if site else {}
    tpl_style = template_css_vars(tpl_settings_dict)
    tpl_dynbg_key = tpl_settings_dict.get("bg_dynamic_key") \
        or (site.frontend_submission_form_bg_dynamic_key if site else None)
    width_mode = (site.frontend_submission_form_width_mode if site else None) or "boxed"
    if width_mode not in ("boxed", "full"):
        width_mode = "boxed"
    try:
        max_width = int(site.frontend_submission_form_max_width) if site else 720
    except (TypeError, ValueError):
        max_width = 720
    max_width = max(480, min(2400, max_width))
    try:
        pad_pct = int(site.frontend_submission_form_padding_pct) if site else 5
    except (TypeError, ValueError):
        pad_pct = 5
    pad_pct = max(0, min(20, pad_pct))

    return render_template(
        "frontend/submission.html",
        # Variant + dynbg + width settings — same names the submission
        # form route passes, so the dispatcher's existing logic kicks
        # in unchanged.
        submission_partial=tpl["partial"],
        submission_template_key=tpl["key"],
        submission_width_mode=width_mode,
        submission_max_width=max_width,
        submission_padding_pct=pad_pct,
        tpl_style=tpl_style,
        tpl_dynbg_key=tpl_dynbg_key,
        # CustomForm-specific overrides: dispatcher reads these in
        # place of the SiteSetting fallbacks, and the form-body partial
        # swap replaces the events/announcements form body with our
        # blocks-driven custom-form body.
        # Description renders through the variant's INTRO slot, which
        # already pipes through |markdown so the operator can use **bold**,
        # links, lists, etc. Subheading is forced empty so the events-
        # submission default ("Fill out the form below…") doesn't appear
        # under a CustomForm's title — empty string is the "explicitly
        # blank" signal the dispatcher checks for via `is defined`.
        heading_override=cf.title,
        subheading_override="",
        intro_override=cf.description,
        form_body_partial="frontend/_custom_form_body.html",
        # Body-partial context.
        cform=cf,
        cform_blocks=blocks,
        cform_errors=errors or {},
        cform_values=values or {},
        cform_success=success_message,
        **ctx,
    )


@bp.route("/<slug>", methods=["POST"])
def custom_form_submit(slug):
    """Public submission handler for CustomForm rows. Validates the
    fields declared in ``cf.blocks_json``, persists a ``FormSubmission``
    row, sends one email per recipient, and either redirects to
    ``cf.redirect_url`` or renders the thank-you message inline.

    A failed validation re-renders the form with field-level errors and
    the operator's previously-typed values so they don't have to retype
    everything."""
    import json as _json
    import uuid as _uuid
    from .models import CustomForm as _CF, FormSubmission as _FS, db as _db

    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    cf = _CF.query.filter_by(slug=slug, enabled=True).first()
    if cf is None:
        abort(404)

    blocks = []
    if cf.blocks_json:
        try:
            blocks = _json.loads(cf.blocks_json)
        except (ValueError, TypeError):
            blocks = []
    if not isinstance(blocks, list):
        blocks = []

    # Cloudflare Turnstile — gated by the same SiteSetting toggle the
    # auth login / contact form / events-submission form check. Verify
    # before doing any storage / email work so a failed challenge
    # short-circuits cheaply, and surface the result as a form-level
    # ``__turnstile__`` error so the template re-renders with the
    # banner above the form (rather than associated with any single
    # field). Posted field values still echo back so the visitor
    # doesn't lose their typing.
    if site and getattr(site, "turnstile_enabled", False):
        from .auth import _verify_turnstile
        token = request.form.get("cf-turnstile-response", "")
        ok, ts_err = _verify_turnstile(site, token, request.remote_addr)
        if not ok:
            # Collect just the user-facing string values so they re-
            # populate the form on re-render. Walk the form once;
            # checkboxes get multi-value handling.
            replay = {}
            for block in blocks:
                if not isinstance(block, dict): continue
                nm = block.get("name")
                if not nm: continue
                if block.get("type") == "checkboxes":
                    replay[nm] = request.form.getlist(nm)
                else:
                    replay[nm] = request.form.get(nm) or ""
            return _render_custom_form(
                cf, ctx=_frontend_context(site),
                errors={"__turnstile__": ts_err or "Security check failed — please try again."},
                values=replay), 400

    # Build the validated payload + capture form-level errors.
    payload = {}
    file_attachments = {}
    errors = {}
    posted_values = {}  # echoed back to the template on validation failure
    upload_dir = current_app.config["UPLOAD_FOLDER"]

    for block in blocks:
        if not isinstance(block, dict):
            continue
        name = block.get("name")
        if not name:
            continue
        ftype = block.get("type") or "text"
        required = bool(block.get("required"))
        if ftype == "checkboxes":
            vals = request.form.getlist(name)
            posted_values[name] = vals
            if required and not vals:
                errors[name] = "Please select at least one option."
                continue
            payload[name] = vals
        elif ftype == "file":
            f = request.files.get(name)
            if f and f.filename:
                accept_rule = (block.get("accept") or "").strip()
                if accept_rule and not _accept_matches(accept_rule, f):
                    errors[name] = (
                        f"File type not allowed. Accepted: {accept_rule}"
                    )
                    continue
                # UUID-prefix the filename to match the rest of the
                # uploads dir's convention. Storing only the filename
                # in payload (not the full path) keeps the FormSubmission
                # JSON small and references existing assets the
                # operator can already browse via the media admin.
                from werkzeug.utils import secure_filename
                safe = secure_filename(f.filename) or "upload.bin"
                stored = f"{_uuid.uuid4().hex}_{safe}"
                f.save(os.path.join(upload_dir, stored))
                file_attachments[name] = {
                    "stored": stored,
                    "original": f.filename,
                }
                payload[name] = stored
            elif required:
                errors[name] = "Please upload a file."
        else:
            raw = (request.form.get(name) or "").strip()
            posted_values[name] = raw
            if required and not raw:
                errors[name] = "This field is required."
                continue
            if ftype == "email" and raw and "@" not in raw:
                errors[name] = "Please enter a valid email address."
                continue
            payload[name] = raw

    if errors:
        return _render_custom_form(cf, ctx=_frontend_context(site),
                                   errors=errors, values=posted_values), 400

    # Persist the submission. The IP comes from ProxyFix-aware
    # request.remote_addr — same source the rest of the app uses for
    # client-side IP capture so logs stay consistent.
    sub = _FS(
        form_id=cf.id,
        payload_json=_json.dumps({"fields": payload, "files": file_attachments}),
        ip=request.remote_addr or "unknown",
    )
    _db.session.add(sub)
    _db.session.commit()

    # Email recipients (best-effort — a failed send doesn't lose the row).
    if cf.recipients_csv:
        rcpts = []
        seen = set()
        for r in cf.recipients_csv.split(","):
            r = r.strip().lower()
            if r and r not in seen:
                seen.add(r); rcpts.append(r)
        if rcpts:
            body_lines = [f"New submission to '{cf.title}' at {request.host}/{cf.slug}", ""]
            for block in blocks:
                if not isinstance(block, dict): continue
                name = block.get("name")
                if not name or name not in payload: continue
                label = block.get("label") or name
                val = payload[name]
                if isinstance(val, list):
                    val = ", ".join(val)
                body_lines.append(f"{label}: {val}")
            if file_attachments:
                body_lines.append("")
                body_lines.append("Attachments:")
                for n, info in file_attachments.items():
                    body_lines.append(f"  {n}: {info['original']} (stored as {info['stored']})")
            body_lines.append("")
            body_lines.append(f"IP: {sub.ip}  ·  Submitted at: {sub.created_at:%Y-%m-%d %H:%M} UTC")
            subject = f"[{(site.frontend_title if site else None) or 'Site'}] {cf.title} submission"
            # Use the submission's email field (if any) as Reply-To so
            # the operator can reply directly from their mail client.
            reply_to = None
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "email":
                    nm = block.get("name")
                    if nm and payload.get(nm):
                        reply_to = payload[nm]; break
            _send_with_reply_to(site, rcpts, subject, "\n".join(body_lines),
                                reply_to=reply_to)

    # Success handoff: redirect if configured, otherwise render the form
    # template again with a success message inline.
    if cf.redirect_url:
        return redirect(cf.redirect_url)
    msg = cf.thank_you_message or "Thanks — your submission was received."
    return _render_custom_form(cf, ctx=_frontend_context(site), success_message=msg)


def _send_with_reply_to(site, recipients, subject, body_text,
                        reply_to=None, reply_to_name=None):
    """Lightweight twin of mail.send_mail that lets us set Reply-To.

    Mirrors the outer helper's transport handling (SSL vs STARTTLS
    vs plain) so a site whose SMTP server requires implicit TLS still
    works. Returns ``(ok, error)`` exactly like ``send_mail`` so the
    caller can branch identically.
    """
    import smtplib, ssl
    from email.message import EmailMessage
    from email.utils import formataddr
    from .crypto import decrypt
    from .mail import _recipients

    if not site or not site.smtp_host or not site.smtp_from_email:
        return False, "SMTP is not configured"
    rcpts = recipients if isinstance(recipients, list) else _recipients(recipients)
    if not rcpts:
        return False, "No recipients"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((site.smtp_from_name or "", site.smtp_from_email))
    msg["To"] = ", ".join(rcpts)
    if reply_to:
        msg["Reply-To"] = formataddr((reply_to_name or "", reply_to))
    msg.set_content(body_text or "")

    password = decrypt(site.smtp_password_enc) if site.smtp_password_enc else ""
    port = int(site.smtp_port or (465 if site.smtp_security == "ssl" else 587))
    host = site.smtp_host
    try:
        if site.smtp_security == "ssl":
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=20, context=ctx) as s:
                if site.smtp_username:
                    s.login(site.smtp_username, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.ehlo()
                if site.smtp_security == "starttls":
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                if site.smtp_username:
                    s.login(site.smtp_username, password)
                s.send_message(msg)
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


@bp.route("/siteindex")
def site_index():
    """Auto-populated index of every public surface on the site.

    Pulls from each content model the admin opted into (Pages,
    Meetings, Events, Announcements, Stories, Library) and hands the
    chosen layout partial a unified ``groups`` structure: a list of
    ``{kind, label, items: [{title, url, kind, subtitle?, date?}]}``
    dicts. The 'grouped' layout iterates over groups; the 'alphabet'
    layout flattens everything into one alphabetical list and tags
    each row with its kind chip.

    Honors the ``frontend_site_index_enabled`` toggle (404s when off,
    matching every other admin-controlled public surface), the
    ``frontend_site_index_show_*`` per-kind toggles, and the
    ``frontend_site_index_sort_mode`` (``grouped`` or ``alpha``).
    """
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "frontend_site_index_enabled", False):
        abort(404)

    groups = _site_index_groups(site)

    tpl = _template_meta(SITE_INDEX_TEMPLATES,
                         (site.frontend_site_index_template if site else None) or "grouped")
    _tpl_settings = template_settings(site, "site_index", tpl["key"])
    tpl_style = template_css_vars(_tpl_settings)
    tpl_dynbg_key = _tpl_settings.get("bg_dynamic_key") \
        or (site.frontend_site_index_bg_dynamic_key if site else None)
    tpl_dynbg_overlay = _tpl_settings.get("bg_dynbg_overlay")
    tpl_dynbg_colors = _tpl_settings.get("bg_dynbg_colors") or []
    tpl_dynbg_config = {
        "overlay": tpl_dynbg_overlay,
        "colors": tpl_dynbg_colors,
        "overlay_scope": _tpl_settings.get("bg_dynbg_overlay_scope"),
        "overlay_size": _tpl_settings.get("bg_dynbg_overlay_size"),
        "overlay_intensity": _tpl_settings.get("bg_dynbg_overlay_intensity"),
        "randomize_colors": _tpl_settings.get("bg_dynbg_randomize_colors", False),
        "randomize_positions": _tpl_settings.get("bg_dynbg_randomize_positions", False),
        "animate": _tpl_settings.get("bg_dynbg_animate", True),

        "pastel_light": _tpl_settings.get("bg_dynbg_pastel_light", False),
        "knobs": _tpl_settings.get("bg_dynbg_knobs", {}),
    }
    sort_mode = (site.frontend_site_index_sort_mode or "grouped") if site else "grouped"
    heading = (site.frontend_site_index_heading if site else None) or "Site index"
    subheading = (site.frontend_site_index_subheading if site else None) \
        or "Every public page on the site, automatically updated."
    ctx = _frontend_context(site)
    return render_template("frontend/site_index.html",
                           groups=groups, sort_mode=sort_mode,
                           heading=heading, subheading=subheading,
                           list_partial=tpl["partial"],
                           list_template_key=tpl["key"],
                           tpl_style=tpl_style,
                           tpl_dynbg_key=tpl_dynbg_key,
                           tpl_dynbg_config=tpl_dynbg_config,
                           **ctx)


def _site_index_groups(site):
    """Collect every public surface the admin opted into (per the
    ``frontend_site_index_show_*`` toggles) and return them as a list
    of group dicts. Each item carries (title, url, kind, subtitle,
    date) so the layouts can render flexibly. Items default to
    alphabetical-by-title within each group so the layouts can
    render straight without re-sorting.
    """
    from .models import Page, Meeting, Post, Story, Library, LibraryItem
    groups = []

    # Sections — top-level template pages that make up the public
    # site's primary navigation (Home, Meetings, Hyperlist, Events,
    # Archive, Announcements, Stories, Blog, Library, Print list,
    # Submit, Contact). Discovered automatically from the
    # ``@public_section`` decorator on each route, so any new top-level
    # page registers here just by carrying the decorator. Each entry
    # is gated by the same predicate the route enforces, so the index
    # never advertises a page that would 404.
    if getattr(site, "frontend_site_index_show_pages", True):
        items = []
        seen_endpoints = set()
        for entry in _PUBLIC_SECTIONS:
            if entry["endpoint"] in seen_endpoints:
                continue
            seen_endpoints.add(entry["endpoint"])
            try:
                if not entry["gate"](site):
                    continue
                url_ = url_for(entry["endpoint"])
            except Exception:
                # A registered endpoint that can't currently build
                # (missing args, removed route) is silently skipped
                # rather than 500ing the whole index.
                continue
            items.append({"title": entry["title"], "url": url_,
                          "kind": "section", "subtitle": url_,
                          "date": None})
        items.sort(key=lambda i: (i["title"] or "").lower())
        if items:
            groups.append({"kind": "section", "label": "Sections", "items": items})

    # Custom Pages — every admin-authored row that's published.
    if getattr(site, "frontend_site_index_show_pages", True):
        items = []
        for p in (Page.query
                  .filter_by(is_published=True, is_private=False)
                  .order_by(Page.title.asc()).all()):
            items.append({
                "title": p.title,
                "url": url_for("frontend.page_detail", slug=p.slug),
                "kind": "page",
                "subtitle": "/" + p.slug,
                "date": p.updated_at,
            })
        items.sort(key=lambda i: (i["title"] or "").lower())
        if items:
            groups.append({"kind": "page", "label": "Pages", "items": items})

    # Meetings — active rows only.
    if getattr(site, "frontend_site_index_show_meetings", True):
        items = []
        for m in Meeting.query.filter(Meeting.archived_at.is_(None)).order_by(Meeting.name.asc()).all():
            items.append({
                "title": m.name,
                "url": url_for("frontend.meeting_detail", slug=m.public_slug),
                "kind": "meeting",
                "subtitle": (m.location or "").strip()[:80] or None,
                "date": None,
            })
        if items:
            groups.append({"kind": "meeting", "label": "Meetings", "items": items})

    # Events — published, non-archived event posts.
    if getattr(site, "frontend_site_index_show_events", True):
        items = []
        q = (Post.query.filter_by(is_event=True, is_draft=False, is_pending_review=False)
             .filter(Post.is_archived.is_(False))
             .order_by(Post.title.asc()))
        for ev in q.all():
            if _post_in_archive(ev):
                continue
            items.append({
                "title": ev.title,
                "url": _post_url(ev),
                "kind": "event",
                "subtitle": (ev.event_starts_at.strftime("%b %d, %Y")
                             if ev.event_starts_at else None),
                "date": ev.event_starts_at,
            })
        if items:
            groups.append({"kind": "event", "label": "Events", "items": items})

    # Announcements — published, non-archived announcement posts.
    if getattr(site, "frontend_site_index_show_announcements", True):
        items = []
        q = (Post.query.filter_by(is_announcement=True, is_draft=False, is_pending_review=False)
             .filter(Post.is_archived.is_(False))
             .order_by(Post.title.asc()))
        for an in q.all():
            if _post_in_archive(an):
                continue
            items.append({
                "title": an.title,
                "url": _post_url(an),
                "kind": "announcement",
                "subtitle": None,
                "date": an.created_at,
            })
        if items:
            groups.append({"kind": "announcement",
                           "label": "Announcements", "items": items})

    # Stories — published rows, when the module is on.
    if getattr(site, "frontend_site_index_show_stories", True) \
            and getattr(site, "stories_enabled", False):
        items = []
        for st in (Story.query
                   .filter(Story.is_archived.is_(False),
                           Story.is_draft.is_(False))
                   .order_by(Story.title.asc()).all()):
            items.append({
                "title": st.title,
                "url": url_for("frontend.story_detail", slug=st.public_slug),
                "kind": "story",
                "subtitle": (st.author_name or "").strip() or None,
                "date": st.created_at,
            })
        if items:
            groups.append({"kind": "story", "label": "Stories", "items": items})

    # Library — public-flagged libraries + items.
    if getattr(site, "frontend_site_index_show_library", True):
        items = []
        for lib in (Library.query.filter_by(public_visible=True)
                    .order_by(Library.name.asc()).all()):
            items.append({
                "title": lib.name,
                "url": url_for("frontend.literature_library") + "#lib-" + str(lib.id),
                "kind": "library",
                "subtitle": "Library",
                "date": None,
            })
            for it in (LibraryItem.query.filter_by(library_id=lib.id, public_visible=True)
                       .order_by(LibraryItem.title.asc()).all()):
                items.append({
                    "title": it.title,
                    "url": url_for("frontend.literature_library") + "#item-" + str(it.id),
                    "kind": "library",
                    "subtitle": lib.name,
                    "date": None,
                })
        if items:
            groups.append({"kind": "library", "label": "Library", "items": items})

    return groups


@bp.route("/<slug>")
def page_detail(slug):
    """Public catch-all for admin-authored content pages.

    Werkzeug picks more specific routes first, so /meetings, /events,
    /library etc. still resolve to their dedicated handlers — only
    single-segment URLs that don't match anything else fall through here.
    """
    import json as _json
    from .models import Page
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    # Module-form slug aliases — admins can pick a friendly URL for
    # each of the three built-in module forms on the form's settings
    # page. We resolve those here BEFORE the Page / CustomForm
    # lookups so a custom slug like ``/submit-an-event`` lands on
    # the real submission form rather than 404'ing through the
    # Page catalog. The canonical paths
    # (``/submissionform``, ``/storyform``, ``/contact``) keep
    # working via their dedicated routes so existing bookmarks
    # don't break.
    if site:
        slug_lower = (slug or "").strip().lower()
        if slug_lower and slug_lower == (site.submission_form_slug or "").strip().lower():
            return submission_form()
        if slug_lower and slug_lower == (site.story_form_slug or "").strip().lower():
            return story_submission_form()
        if slug_lower and slug_lower == (site.contact_form_slug or "").strip().lower():
            return contact()
    q = Page.query.filter_by(slug=slug, is_published=True)
    # Private pages are visible only to signed-in editors / admins; anon
    # visitors get the same 404 they'd see for an unpublished slug so the
    # page's existence isn't leaked.
    if not (current_user.is_authenticated and current_user.can_edit()):
        q = q.filter_by(is_private=False)
    page = q.first()
    if page is None:
        # Fall through to admin-authored custom forms. The form-builder
        # admin already rejects slugs that collide with existing Page
        # slugs (and the reserved-routes set), so this two-tier lookup
        # is unambiguous: either a Page owns the slug or a CustomForm
        # does, never both.
        from .models import CustomForm as _CF
        cf = _CF.query.filter_by(slug=slug, enabled=True).first()
        if cf is not None:
            return _render_custom_form(cf, ctx=_frontend_context(site))
        abort(404)
    return _render_page(page, site)


@bp.route("/_preview/page/<int:page_id>", methods=["GET", "POST"])
def page_preview(page_id):
    """Editor-only preview of a content page (or the homepage), rendered
    exactly as the public site would.

    Differs from the public ``page_detail`` in two ways:
      • Visible to signed-in frontend editors ONLY (never the public), so
        DRAFT / unpublished pages can be previewed before publishing.
      • On POST, renders the ``blocks_json`` posted from the structure
        editor — the current, UNSAVED edits — instead of the saved
        content, so changes can be seen before hitting Save. Page-level
        settings (background, layout, SEO) come from the saved row.
    """
    from .models import Page
    if not (current_user.is_authenticated
            and getattr(current_user, "can_edit_frontend", lambda: False)()):
        abort(404)
    site = _site()
    if not site or not site.frontend_module_enabled:
        abort(404)
    page = Page.query.get_or_404(page_id)
    sections = None
    if request.method == "POST":
        raw = request.form.get("blocks_json")
        if raw:
            import json as _json
            try:
                parsed = _json.loads(raw)
                if isinstance(parsed, list):
                    sections = parsed
            except (ValueError, TypeError):
                sections = None
    return _render_page(page, site, sections=sections, preview=True,
                        unsaved=(sections is not None))


@bp.route("/_preview/popup/<int:popup_id>")
def popup_preview(popup_id):
    """Editor-only preview of a popup, opened on a neutral page and
    forced visible regardless of the popup's enabled / per-device flags
    so admins can preview drafts before enabling them.

    Reuses the same site-wide popup partial as the live site (included
    in ``frontend/base.html``): we override the ``popups`` context with
    just this popup and set ``popup_force_open`` so the trigger JS opens
    it on load. Visible to signed-in frontend editors only."""
    from .models import Popup
    if not (current_user.is_authenticated
            and getattr(current_user, "can_edit_frontend", lambda: False)()):
        abort(404)
    site = _site()
    if not site or not site.frontend_module_enabled:
        abort(404)
    popup = Popup.query.get_or_404(popup_id)
    ctx = _frontend_context(site)
    # Override the context-processor's enabled-only list with this single
    # popup (which may be disabled) so the partial renders it.
    ctx["popups"] = [popup]
    return render_template("frontend/popup_preview.html",
                           popup=popup, popup_force_open=popup.name, **ctx)


def _sections_have_block_type(sections, block_type):
    """Recursively scan `sections` for any block of `block_type`.
    Used by the page route to decide whether to load the Lottie player
    (and any future block type that needs a one-off vendor script).
    """
    def _walk(blocks):
        for b in (blocks or []):
            if not isinstance(b, dict):
                continue
            if b.get("type") == block_type:
                return True
            if b.get("type") == "container":
                if _walk((b.get("data") or {}).get("blocks") or []):
                    return True
        return False
    for sec in (sections or []):
        if isinstance(sec, dict):
            if _walk(sec.get("blocks") or []):
                return True
    return False


def _collect_page_headings(sections):
    """Walk every block in `sections` (recursing into containers) and
    return a flat list of `{level, text, anchor}` dicts in document
    order. Powers the wiki-sidebar block's TOC: each heading block on
    the page becomes a jump-link in the sidebar list.

    Side effect: mutates each visited heading block in-place to add an
    `_anchor` key on its `data` dict so the renderer can stamp the
    matching `id="…"` on its `<hN>` without redoing the slug + dup-
    counting logic. Anchors are stable for a given page-render but
    re-derived each request, so heading text edits flow through
    immediately.

    Only includes blocks of type 'heading' — section titles are not
    listed here because we no longer auto-render them as headings, and
    the admin can drop a Heading block at the top of a section if they
    want it in the TOC."""
    import re as _re
    out = []
    seen = {}

    def _slug(text):
        s = (text or "").lower()
        s = _re.sub(r"[^a-z0-9]+", "-", s).strip("-")
        if not s:
            s = "section"
        # Ensure uniqueness — duplicate headings get -2, -3, …
        if s in seen:
            seen[s] += 1
            s = f"{s}-{seen[s]}"
        else:
            seen[s] = 1
        return s

    def _walk(blocks):
        for b in (blocks or []):
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            d = b.get("data") or {}
            if t == "heading":
                text = (d.get("text") or "").strip()
                if not text:
                    continue
                lvl = d.get("level") or 3
                try:
                    lvl = int(lvl)
                except (TypeError, ValueError):
                    lvl = 3
                lvl = max(2, min(lvl, 6))
                anchor = _slug(text)
                d["_anchor"] = anchor
                b["data"] = d
                out.append({"level": lvl, "text": text, "anchor": anchor})
            elif t == "container":
                _walk(d.get("blocks") or [])

    for sec in sections:
        if isinstance(sec, dict):
            _walk(sec.get("blocks") or [])
    return out
