# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public-facing frontend blueprint.

When `SiteSetting.frontend_enabled` is True, requests to the root URL serve
a marketing/content homepage instead of bouncing straight to the login
screen. When the toggle is off, the root URL redirects to the admin login.

Admin pages remain at /tspro/* and the authenticated dashboard is at /tspro/.
"""
from flask import Blueprint, render_template, redirect, url_for, abort
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

FOOTER_TEMPLATES = [
    {
        "key": "classic",
        "name": "Classic",
        "description": "Three-column footer with logo + tagline on the left, a short link list in the middle, and the copyright text on the right. Our original design.",
        "partial": "frontend/footers/classic.html",
    },
    {
        "key": "recovery-blue",
        "name": "Recovery Blue",
        "description": "Fellowship-style footer with meeting-location cards, a contact block, and a secondary link row.",
        "partial": "frontend/footers/recovery-blue.html",
    },
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
    footer_tpl = _template_meta(
        FOOTER_TEMPLATES,
        (site.frontend_footer_template if site else None) or "classic",
    )
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
    block_content = site_blocks(site)
    meetings_groups = filtered_meetings(block_content.get("_meetings"))
    events_list = filtered_events(block_content.get("_events"), site=site)
    return {
        "site": site,
        "header_template_partial": header_tpl["partial"],
        "header_template_key": header_tpl["key"],
        "footer_template_partial": footer_tpl["partial"],
        "footer_template_key": footer_tpl["key"],
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


@bp.route("/meeting/<slug>")
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
    return render_template(tpl["partial"], meeting=m, tpl_style=tpl_style, **ctx)


@bp.route("/meeting/<slug>/<path:resource>")
def meeting_resource(slug, resource):
    """Resolve a public file or reading attached to a meeting via its
    pretty URL — e.g. ``/meeting/daily-zoom-round-up/opening-statement.pdf``.

    The route looks up the meeting by slug first (same logic as
    ``meeting_detail``), then matches ``resource`` against the meeting's
    public files (``MeetingFile.public_visible=True``) and any
    ``meeting.public_readings`` by their respective ``url_slug`` properties.
    Files take precedence over readings on slug collision."""
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
        # Old slug — redirect to the current /meeting/<new>/<resource> URL
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

    for r in m.public_readings:
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
    """Public list of every active meeting, grouped by day. Linked from
    the homepage Upcoming Meetings block via the "See all meetings"
    CTA. Uses the same Meeting query the homepage block does, but with
    the full week so visitors can browse the whole schedule."""
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    ctx = _frontend_context(site)
    from .blocks import filtered_meetings
    all_groups = filtered_meetings({
        "filter": "next_7_days",
        "max_count": 200,
        "group_by_day": True,
    })
    return render_template("frontend/meetings_list.html",
                           all_meetings_groups=all_groups, **ctx)


@bp.route("/event/<slug>")
def event_detail(slug):
    """Public event detail page — featured image, schedule, location,
    online/Zoom info, contact, and full body. The slug is the event
    title with non-alphanumerics collapsed to hyphens. Drafts and
    archived events are not viewable. Past events remain reachable by
    direct link until the auto-archive sweep marks them archived."""
    from .colors import slugify
    site = _site()
    gate = _frontend_gate(site)
    if gate is not None:
        return gate
    if not site or not getattr(site, "posts_enabled", True):
        abort(404)
    candidates = (Post.query
                  .filter(Post.is_event.is_(True),
                          Post.is_archived.is_(False),
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
                return redirect(url_for("frontend.event_detail",
                                        slug=target.public_slug), code=301)
        abort(404)
    ctx = _frontend_context(site)
    tpl = _template_meta(EVENT_TEMPLATES,
                         (site.frontend_event_template if site else None) or "classic")
    tpl_style = template_css_vars(template_settings(site, "event", tpl["key"]))
    return render_template(tpl["partial"], event=ev, tpl_style=tpl_style, **ctx)
