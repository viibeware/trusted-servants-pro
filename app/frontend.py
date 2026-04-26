# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public-facing frontend blueprint.

When `SiteSetting.frontend_enabled` is True, requests to the root URL serve
a marketing/content homepage instead of bouncing straight to the login
screen. When the toggle is off, the root URL redirects to the admin login.

Admin pages remain at /tspro/* and the authenticated dashboard is at /tspro/.
"""
from flask import Blueprint, render_template, redirect, url_for, abort
from flask_login import current_user
from .models import SiteSetting, Meeting, FrontendNavItem

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


def _template_meta(templates, key):
    for t in templates:
        if t["key"] == key:
            return t
    return templates[0]


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

    Module disabled:
      - unauthenticated visitor → /tspro login (so they can sign in
        and find the admin)
      - authenticated visitor   → /tspro 404 page (they're already in
        and a redirect-loop to login would be confusing)
    Module on but frontend_enabled off (admin preview mode):
      - non-editors get the same redirect-to-login treatment.
    """
    from flask import render_template
    if not site or not site.frontend_module_enabled:
        if current_user.is_authenticated:
            return render_template("404.html"), 404
        return redirect(url_for("auth.login"))
    if not site.frontend_enabled:
        if not (current_user.is_authenticated and current_user.can_edit_frontend()):
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
    m = next((mt for mt in candidates if slugify(mt.name) == slug), None)
    if m is None:
        abort(404)
    ctx = _frontend_context(site)
    return render_template("frontend/meeting_detail.html", meeting=m, **ctx)
