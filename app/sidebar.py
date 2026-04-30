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
    {"key": "libraries",      "label": "Libraries",            "endpoint": "main.libraries",      "active_kind": "contains:librar|reading|!intergroup"},
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
    {"key": "user_log",        "label": "User Log",               "endpoint": "main.user_log",         "active_kind": "contains:user_log"},
    {"key": "delete_log",      "label": "Delete Log",             "endpoint": "main.delete_log",       "active_kind": "contains:delete_log"},
]

# Static (non-library) items that live inside the "Intergroup" sidebar
# subsection when the umbrella module is on. Library entries are
# discovered dynamically from ``Library.is_intergroup`` so admins can
# add new Intergroup libraries without code changes.
_INTERGROUP_CATALOG = [
    {"key": "ig_email", "label": "Email", "endpoint": "main.intergroup",
     "active_kind": "exact"},
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
        # When the umbrella Intergroup module is on, the standalone
        # Intergroup link is hidden — the Email entry inside the
        # Intergroup subsection covers the same destination.
        if site and site.intergroup_module_enabled:
            return False
        # Email Accounts is hard-gated to admins + intergroup_members
        # regardless of the per-module role setting; the standalone
        # fallback link mirrors the umbrella subsection's visibility.
        if not getattr(user, "can_edit_intergroup_libraries", lambda: False)():
            return False
        return bool(site and site.intergroup_enabled)
    if key == "zoom_tech":
        return bool(site and site.zoom_tech_enabled
                    and user_meets_role(user, site.zoom_tech_required_role))
    if key == "posts":
        return bool(site and site.posts_enabled
                    and user_meets_role(user, site.posts_required_role))
    if key == "access_requests": return bool(user.is_admin())
    if key == "user_log":        return bool(user.is_admin())
    if key == "delete_log":      return bool(user.is_admin())
    if key == "web_frontend":
        # The Web Frontend's route gates resolve to admin-only via
        # ``can_edit_frontend`` (the dedicated frontend_editor role
        # was retired). The required-role dropdown can additionally
        # tighten visibility but can't loosen it past the hard gate.
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
    """Resolve whether a sidebar item should render as active for the
    given Flask endpoint. Supported active_kind values:

      ``exact``          — sentinel; the item manages active state via
                           other logic (currently used by intergroup,
                           zoom_tech, ig_email, etc).
      ``prefix:<x>``     — matches when endpoint starts with ``<x>``.
      ``contains:a|b|!c`` — matches when endpoint contains ``a`` or
                            ``b`` and does NOT contain ``c``. The
                            negation form keeps the Libraries link from
                            lighting up while we're inside an
                            Intergroup library (whose endpoint contains
                            "library" but should be a separate row)."""
    ep = current_endpoint or ""
    if active_kind == "exact":
        return False
    if active_kind.startswith("prefix:"):
        return ep.startswith(active_kind[len("prefix:"):])
    if active_kind.startswith("contains:"):
        tokens = [t for t in active_kind[len("contains:"):].split("|") if t]
        negative = [t[1:] for t in tokens if t.startswith("!") and len(t) > 1]
        positive = [t for t in tokens if not t.startswith("!")]
        if any(n in ep for n in negative):
            return False
        return any(p in ep for p in positive)
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


def _build_intergroup_items(site, user, current_endpoint, url_for):
    """Resolve the items that go inside the new "Intergroup" subsection.
    Empty list when the umbrella module is off, the user lacks the
    section's required role, or none of the three items resolve to a
    visible link. ``Email Accounts`` honors the existing per-page
    intergroup toggle; ``Minutes`` / ``Documents`` resolve via library
    lookup by name and are skipped when the corresponding library
    doesn't exist in the database."""
    from flask import request
    from .permissions import user_meets_role
    if not user or not user.is_authenticated:
        return []
    if not (site and site.intergroup_module_enabled):
        return []
    if not user_meets_role(user, site.intergroup_module_required_role):
        return []
    # Pull the *current* library identity from the active request so we
    # can mark only the matching row as active. Intergroup libraries
    # resolve via slug at /tspro/intergroup/<slug>; non-IG hits land at
    # /tspro/libraries/<id> (and 301-redirect to the slug URL for IG).
    current_lid = None
    current_slug = None
    try:
        ep = current_endpoint or ""
        if ep == "main.library_detail":
            current_lid = (request.view_args or {}).get("lid")
        elif ep == "main.intergroup_library_detail":
            current_slug = (request.view_args or {}).get("slug")
    except RuntimeError:
        current_lid = None
        current_slug = None
    items = []
    # Email Accounts — hard-gated to admins + intergroup_members. The
    # per-module role setting under Settings → Modules no longer controls
    # this entry's visibility (the page itself returns 404 for any other
    # role), so the sidebar mirrors that policy.
    if site.intergroup_enabled and user.can_edit_intergroup_libraries():
        ep = "main.intergroup"
        items.append({
            "key": "ig_email",
            "label": "Email Accounts",
            "href": url_for(ep),
            "active": (current_endpoint or "") == ep,
            "target": None,
        })
    # Library shortcuts — every Library row flagged ``is_intergroup``
    # surfaces here, in alphabetical order. Admins add new entries via
    # the "+ Add Library" link below. Hrefs resolve to the canonical
    # slug URL so the address bar shows the human-readable path.
    from .models import Library
    from .colors import slugify
    libs = Library.query.filter(Library.is_intergroup == True)\
        .order_by(Library.name).all()  # noqa: E712
    for lib in libs:
        slug = slugify(lib.name)
        items.append({
            "key": f"ig_lib_{lib.id}",
            "label": lib.name,
            "href": url_for("main.intergroup_library_detail", slug=slug),
            "active": (current_slug == slug) or (current_lid == lib.id),
            "target": None,
        })
    # Apply manual reorder for the intergroup subsection if the admin
    # set one. Saved order wins; any item that isn't yet in the saved
    # list is appended in catalog order so newly-enabled items show up.
    mode = (site.sidebar_sort_mode if site else None) or "auto-asc"
    if mode == "manual" and items:
        try:
            stored = json.loads(site.sidebar_order_json) if site.sidebar_order_json else {}
        except (ValueError, TypeError):
            stored = {}
        saved = stored.get("intergroup")
        if isinstance(saved, list) and saved:
            by_key = {it["key"]: it for it in items}
            seen = set()
            ordered = []
            for k in saved:
                it = by_key.get(k)
                if it and k not in seen:
                    seen.add(k)
                    ordered.append(it)
            for it in items:
                if it["key"] not in seen:
                    ordered.append(it)
            items = ordered
    # Pin the admin-only "+ Add Library" action to the bottom of the
    # subsection regardless of sort mode — it's a creation entry point,
    # not a content row, so it shouldn't shuffle with the libraries
    # above it. Appending after any reorder logic keeps it sticky.
    if user.is_admin() and items is not None:
        ep = "main.intergroup_library_new"
        items.append({
            "key": "ig_add_library",
            "label": "+ Add Library",
            "href": url_for(ep),
            "active": (current_endpoint or "") == ep,
            "target": None,
            "is_action": True,
        })
    return items


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

    intergroup_items = _build_intergroup_items(site, user, current_endpoint, url_for)
    sections = [
        ("main",       None,         main_items),
        ("intergroup", "Intergroup", intergroup_items),
        ("external",   "External",   external_items),
        ("admin",      "Admin",      admin_items),
    ]
    sections_by_key = {s[0]: s for s in sections}
    if mode == "manual" and stored.get("sections"):
        seen = set()
        explicit = [k for k in stored["sections"]
                    if k in sections_by_key and not (k in seen or seen.add(k))]
        # Default placement for sections the user hasn't explicitly
        # ordered. New sections (e.g. intergroup, added in 1.7.6) won't
        # be in pre-existing saved orders; we slot each missing section
        # in at its *canonical position relative to the explicit keys*.
        # Concretely, walk the canonical order; for each missing key,
        # insert it just before the first explicit key whose canonical
        # index is higher. This keeps a saved [main, external, admin]
        # order rendering [main, intergroup, external, admin] without
        # bumping admin off the bottom.
        canonical = ("main", "intergroup", "external", "admin")
        canonical_idx = {k: i for i, k in enumerate(canonical)}
        missing = [k for k in canonical if k not in seen]
        order = list(explicit)
        for k in missing:
            ki = canonical_idx[k]
            insert_at = len(order)
            for j, ek in enumerate(order):
                if canonical_idx.get(ek, -1) > ki:
                    insert_at = j
                    break
            order.insert(insert_at, k)
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
    intergroup_items = []
    umbrella_on = bool(site and site.intergroup_module_enabled)
    for it in _MAIN_CATALOG:
        if it["key"] in PINNED_KEYS:
            continue
        # The standalone "intergroup" Main-catalog item is hidden in the
        # live sidebar when the umbrella module is on; mirror that here
        # so the reorder UI doesn't surface a phantom Main row that
        # never actually renders.
        if it["key"] == "intergroup" and umbrella_on:
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
    if umbrella_on:
        # Intergroup section: Email Accounts (static) plus one row per
        # Intergroup-flagged library. Surfaced here for visibility in
        # the reorder UI; reordering inside the section is not yet
        # supported.
        from .models import Library
        if site and site.intergroup_enabled:
            intergroup_items.append({"key": "ig_email", "label": "Email Accounts"})
        for lib in Library.query.filter(Library.is_intergroup == True)\
                .order_by(Library.name).all():  # noqa: E712
            intergroup_items.append({"key": f"ig_lib_{lib.id}", "label": lib.name})
    return {"main": main_items, "intergroup": intergroup_items, "admin": admin_items}
