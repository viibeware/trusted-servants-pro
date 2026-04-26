# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sidebar data layer.

Single source of truth for what shows up in the main sidebar. Builds a
section/item structure that the template iterates over, with per-item
visibility checks centralised here. Sorting honors the admin's
``sidebar_sort_mode``:

  auto-asc / auto-desc — alphabetical inside each section. The section
                         order is fixed: Main → External → Admin.
  manual               — reads ``sidebar_order_json`` written by the
                         drag-drop UI: {"sections": [...],
                         "main": [...], "admin": [...]}.

External-link items inside the External section are NOT reordered —
admins manage their order on the External Links tab. The whole external
group can still be moved within the section list in manual mode.
"""
import json


# Item keys → static metadata. Visibility / dynamic url_for live in the
# build function below since they need request context. Each entry's
# `endpoint_match` is a substring used by the active-state check.
_MAIN_CATALOG = [
    {"key": "dashboard",      "label": "Dashboard",            "endpoint": "main.index",          "active_kind": "exact"},
    {"key": "meetings",       "label": "Meetings",             "endpoint": "main.meetings",       "active_kind": "contains:meeting"},
    {"key": "libraries",      "label": "Libraries",            "endpoint": "main.libraries",      "active_kind": "contains:librar|reading"},
    {"key": "media",          "label": "File Browser",         "endpoint": "main.media_list",     "active_kind": "contains:media"},
    {"key": "zoom_accounts",  "label": "Zoom Accounts",        "endpoint": "main.zoom_accounts",  "active_kind": "contains:zoom_account"},
    # The four module-gated items below carry their own ``required_role``
    # column. Their section placement is decided at render time:
    # required_role == "admin" → Admin section; otherwise → Main.
    {"key": "intergroup",     "label": None,                   "endpoint": "main.intergroup",       "active_kind": "exact"},
    {"key": "zoom_tech",      "label": None,                   "endpoint": "main.zoom_tech",        "active_kind": "exact"},
    {"key": "posts",          "label": "Announcements & Events", "endpoint": "main.posts",          "active_kind": "prefix:main.post"},
    {"key": "web_frontend",   "label": "Web Frontend",         "endpoint": "main.frontend_dashboard", "active_kind": "prefix:main.frontend_"},
]

_ADMIN_CATALOG = [
    # Items that are always admin-only by code, not configuration.
    {"key": "access_requests", "label": "Access Requests",        "endpoint": "main.access_requests",  "active_kind": "contains:access_request"},
]

# Module-gated items whose section placement (Main vs Admin) follows
# their required_role: admin → Admin section, otherwise → Main.
# Maps item key → SiteSetting attribute that holds the required role.
_DYNAMIC_SECTION_ITEMS = {
    "intergroup":    "intergroup_required_role",
    "zoom_tech":     "zoom_tech_required_role",
    "posts":         "posts_required_role",
    "web_frontend":  "frontend_module_required_role",
}

# Keys that are always rendered first inside their section regardless of
# sort mode and are excluded from the drag-drop reorder UI. Dashboard is
# the canonical entry point so we never let it drift.
PINNED_KEYS = frozenset({"dashboard"})


def _is_visible(key, site, user):
    """Per-item visibility. Item is shown only when its visibility
    predicate is True. Falsy returns hide the item entirely (we don't
    render it greyed out).

    Module-gated items (intergroup, zoom_tech, posts, web_frontend)
    consult the per-module ``*_required_role`` columns the admin sets
    on the Settings → Modules tab so the dropdown's choice flows
    through to the sidebar in real time."""
    from .permissions import user_meets_role
    if not user or not user.is_authenticated:
        return False
    if key == "dashboard":      return True
    if key == "meetings":       return True
    if key == "libraries":      return True
    if key == "media":          return True
    if key == "zoom_accounts":  return True
    if key == "intergroup":
        return bool(site and site.intergroup_enabled
                    and user_meets_role(user, site.intergroup_required_role))
    if key == "zoom_tech":
        return bool(site and site.zoom_tech_enabled
                    and user_meets_role(user, site.zoom_tech_required_role))
    if key == "posts":
        return bool(site and site.posts_enabled
                    and user_meets_role(user, site.posts_required_role))
    if key == "access_requests": return bool(user.is_admin())
    if key == "web_frontend":
        # The Web Frontend's actual route gates remain @frontend_editor_required
        # for safety — the dropdown for this module additionally hides the
        # sidebar entry when the chosen tier is stricter.
        return bool(site and site.frontend_module_enabled
                    and getattr(user, "can_edit_frontend", lambda: False)()
                    and user_meets_role(user, site.frontend_module_required_role))
    return False


def _label_for(key, site, default):
    """Resolve the runtime label — Intergroup/Zoom Tech can be renamed
    by the admin via SiteSetting, so their label isn't a constant."""
    if key == "intergroup":
        return (site.ig_page_title if site else None) or "Intergroup"
    if key == "zoom_tech":
        return (site.zoom_tech_title if site else None) or "Zoom Tech Training"
    return default


def _active_for(active_kind, current_endpoint):
    ep = current_endpoint or ""
    if active_kind == "exact":
        return ep == active_kind  # never matches; used as a sentinel
    if active_kind.startswith("prefix:"):
        return ep.startswith(active_kind[len("prefix:"):])
    if active_kind.startswith("contains:"):
        for token in active_kind[len("contains:"):].split("|"):
            if token and token in ep:
                return True
        return False
    return False


def _ordered_keys(stored, catalog_keys, sort_mode, label_lookup):
    """Resolve the order of items inside a section. Manual mode reads
    `stored` (with append-fallback for new items not yet in the saved
    order). Auto modes alphabetise on label.

    Pinned keys (currently just ``dashboard``) are always emitted first
    in their original catalog order regardless of sort mode, so an admin
    can't accidentally bury the home link by reordering."""
    pinned = [k for k in catalog_keys if k in PINNED_KEYS]
    sortable = [k for k in catalog_keys if k not in PINNED_KEYS]

    if sort_mode == "manual" and stored:
        seen = set()
        # Strip any pinned keys the saved order included by accident —
        # they're never reorderable, so the saved JSON shouldn't carry
        # them. Append-fallback for new keys not yet in stored.
        out = [k for k in stored if k in sortable and not (k in seen or seen.add(k))]
        for k in sortable:
            if k not in seen:
                out.append(k)
        return pinned + out

    keys = list(sortable)
    keys.sort(key=lambda k: (label_lookup.get(k) or "").lower(),
              reverse=(sort_mode == "auto-desc"))
    return pinned + keys


def build_sidebar(site, user, current_endpoint, nav_links, url_for):
    """Returns ``[(section_key, section_label, [items...]), ...]`` in
    the order the template should render. Each item is a dict with
    ``key, label, href, active, badge`` keys plus a ``target`` for
    external links."""
    mode = (site.sidebar_sort_mode if site else None) or "auto-asc"
    raw_order = (site.sidebar_order_json if site else None) or ""
    try:
        stored = json.loads(raw_order) if raw_order else {}
    except (ValueError, TypeError):
        stored = {}

    # Decide which section each visible Main-catalog item lives in. For
    # the four module-gated items (intergroup, zoom_tech, posts,
    # web_frontend) the placement follows their per-module required-
    # role: ``admin`` → Admin section; anything else → Main. For all
    # other items the section is always Main.
    def _section_for(item_key):
        attr = _DYNAMIC_SECTION_ITEMS.get(item_key)
        if not attr:
            return "main"
        required = (getattr(site, attr, None) if site else None) or "viewer"
        return "admin" if required == "admin" else "main"

    main_items = []
    admin_items = []
    main_catalog_label_lookup = {it["key"]: _label_for(it["key"], site, it["label"]) for it in _MAIN_CATALOG}
    visible_main = [it for it in _MAIN_CATALOG if _is_visible(it["key"], site, user)]
    main_by_key = {it["key"]: it for it in visible_main}

    # Partition visible Main-catalog items into their resolved section.
    visible_main_keys_main = [it["key"] for it in visible_main if _section_for(it["key"]) == "main"]
    visible_main_keys_admin = [it["key"] for it in visible_main if _section_for(it["key"]) == "admin"]

    for k in _ordered_keys(stored.get("main"), visible_main_keys_main, mode, main_catalog_label_lookup):
        it = main_by_key[k]
        main_items.append({
            "key": k,
            "label": main_catalog_label_lookup[k],
            "href": url_for(it["endpoint"]),
            "active": _active_for(it["active_kind"], current_endpoint),
            "target": None,
        })

    external_items = [
        {"key": f"ext-{i}", "label": (n.title or "").strip() or n.url,
         "href": n.url, "active": False, "target": "_blank", "is_external": True}
        for i, n in enumerate(nav_links or [])
    ]
    if external_items and mode in ("auto-asc", "auto-desc"):
        external_items.sort(key=lambda x: (x["label"] or "").lower(),
                            reverse=(mode == "auto-desc"))

    # Admin section: static admin-only items (Access Requests) plus any
    # Main-catalog items the admin pinned to admin via required_role.
    admin_label_lookup = dict(main_catalog_label_lookup)
    admin_label_lookup.update({it["key"]: it["label"] for it in _ADMIN_CATALOG})
    visible_static_admin = [it for it in _ADMIN_CATALOG if _is_visible(it["key"], site, user)]
    static_admin_keys = [it["key"] for it in visible_static_admin]
    admin_keys_combined = static_admin_keys + visible_main_keys_admin
    admin_by_key = {it["key"]: it for it in visible_static_admin}
    admin_by_key.update({it["key"]: it for it in visible_main if it["key"] in visible_main_keys_admin})

    for k in _ordered_keys(stored.get("admin"), admin_keys_combined, mode, admin_label_lookup):
        it = admin_by_key[k]
        admin_items.append({
            "key": k,
            "label": admin_label_lookup[k],
            "href": url_for(it["endpoint"]),
            "active": _active_for(it["active_kind"], current_endpoint),
            "target": None,
        })

    sections = [
        ("main",     None,       main_items),
        ("external", "External", external_items),
        ("admin",    "Admin",    admin_items),
    ]
    sections_by_key = {s[0]: s for s in sections}
    if mode == "manual" and stored.get("sections"):
        seen = set()
        order = [k for k in stored["sections"] if k in sections_by_key and not (k in seen or seen.add(k))]
        for k in ("main", "external", "admin"):
            if k not in seen:
                order.append(k)
        sections = [sections_by_key[k] for k in order]
    # External should only render if there's at least one link AND
    # the user can see admin-area entries OR the user's role permits it.
    sections = [(k, lbl, items) for (k, lbl, items) in sections if items]
    return sections


# Catalog exposed for the admin reorder UI. Pinned keys are filtered
# out so they never appear as draggable rows. Module-gated items
# (intergroup, zoom_tech, posts, web_frontend) appear under whichever
# section their current required_role places them in, mirroring the
# live sidebar — so the manual reorder list always reflects what the
# visitor actually sees.
def admin_reorder_catalog(site):
    def _section_for(key):
        attr = _DYNAMIC_SECTION_ITEMS.get(key)
        if not attr:
            return "main"
        required = (getattr(site, attr, None) if site else None) or "viewer"
        return "admin" if required == "admin" else "main"

    main_items = []
    admin_items = []
    for it in _MAIN_CATALOG:
        if it["key"] in PINNED_KEYS:
            continue
        entry = {"key": it["key"], "label": _label_for(it["key"], site, it["label"]) or it["key"]}
        if _section_for(it["key"]) == "admin":
            admin_items.append(entry)
        else:
            main_items.append(entry)
    for it in _ADMIN_CATALOG:
        if it["key"] in PINNED_KEYS:
            continue
        admin_items.append({"key": it["key"], "label": it["label"]})
    return {"main": main_items, "admin": admin_items}
