# SPDX-License-Identifier: AGPL-3.0-or-later
"""Utility-bar helpers.

The utility bar is the slim row pinned above the public site header.
It carries admin-defined items (links, pill buttons, plain text, icons)
on the far left and far right, and — when the admin enables it — a
yellow "Live Meeting" badge in the centre that surfaces whichever
online/hybrid meeting is currently in session.

Two pieces of state shape what gets rendered:

* ``SiteSetting.utility_bar_*`` columns hold the admin-edited content.
* :func:`current_live_meeting` is evaluated once per request and returns
  the meeting whose schedule is "live" right now (open time reached,
  not yet ended) — at most one, falling through to the next meeting as
  soon as its open time arrives.

Both halves are wired into ``frontend._frontend_context`` so every
public template — including every header partial — can read the same
resolved values via ``utility_bar`` / ``live_meeting``.
"""
import json


_LEAF_KINDS = {"link", "button", "text", "icon"}
_CONTAINER_KIND = "container"
_THEME_TOGGLE_KIND = "theme_toggle"
_SEARCH_TRIGGER_KIND = "search_trigger"
_GSR_SUMMARY_KIND = "gsr_summary"
_ALLOWED_KINDS = _LEAF_KINDS | {_CONTAINER_KIND, _THEME_TOGGLE_KIND,
                                 _SEARCH_TRIGGER_KIND, _GSR_SUMMARY_KIND}


def _coerce_leaf(raw):
    """Normalise a non-container admin-supplied item. Drops items
    missing their primary content and silently rejects unknown kinds.
    Returns None when the item should be discarded.

    The ``theme_toggle`` kind is a singleton placeholder for the
    dark/light mode button — it carries no editable content (the
    button's chrome is fixed) but lives in the items stream so the
    admin can drag it to any position and the public renderer can
    place it inline with whatever surrounds it."""
    if not isinstance(raw, dict):
        return None
    kind = (raw.get("kind") or "link").strip().lower()
    if kind == _THEME_TOGGLE_KIND:
        return {"kind": _THEME_TOGGLE_KIND}
    if kind == _SEARCH_TRIGGER_KIND:
        # Search-trigger button — singleton like the theme toggle. No
        # editable fields; the chrome (search-icon button + Cmd/Ctrl+K
        # shortcut) is fixed by the public renderer.
        return {"kind": _SEARCH_TRIGGER_KIND}
    if kind == _GSR_SUMMARY_KIND:
        # GSR Summary pill — singleton like the theme toggle. No
        # editable fields; the public renderer emits a fixed pill that
        # links to /announcements#gsr (jumping straight to the GSR
        # Summary tab on the announcements omni layout).
        return {"kind": _GSR_SUMMARY_KIND}
    if kind not in _LEAF_KINDS:
        return None
    label = (raw.get("label") or "").strip()
    url   = (raw.get("url") or "").strip()
    icon  = (raw.get("icon") or "").strip()
    new_tab = bool(raw.get("open_in_new_tab"))
    if kind in ("link", "button") and (not label or not url):
        return None
    if kind == "text" and not label:
        return None
    if kind == "icon" and not icon:
        return None
    return {"kind": kind, "label": label, "url": url,
            "icon": icon, "open_in_new_tab": new_tab}


def _has_theme_toggle(items):
    """Recursively scan a list of items (containers + leaves) for a
    theme_toggle entry. Used to decide whether to auto-inject one."""
    for it in items or []:
        if not isinstance(it, dict):
            continue
        if it.get("kind") == _THEME_TOGGLE_KIND:
            return True
        if it.get("kind") == _CONTAINER_KIND and _has_theme_toggle(it.get("items") or []):
            return True
    return False


def _has_search_trigger(items):
    """Recursive scan for the search_trigger singleton. Mirrors
    ``_has_theme_toggle`` so the auto-inject path can preserve the
    invariant: a search-trigger always exists in the items stream so
    visitors always have a clickable affordance for the search modal
    (the Cmd/Ctrl+K keyboard shortcut works regardless)."""
    for it in items or []:
        if not isinstance(it, dict):
            continue
        if it.get("kind") == _SEARCH_TRIGGER_KIND:
            return True
        if it.get("kind") == _CONTAINER_KIND and _has_search_trigger(it.get("items") or []):
            return True
    return False


def _has_gsr_summary(items):
    """Recursive scan for the gsr_summary singleton. Mirrors the other
    ``_has_*`` helpers so the auto-inject path keeps a single GSR pill
    in the items stream — visitors always have a clickable shortcut to
    the GSR Summary view of the announcements page."""
    for it in items or []:
        if not isinstance(it, dict):
            continue
        if it.get("kind") == _GSR_SUMMARY_KIND:
            return True
        if it.get("kind") == _CONTAINER_KIND and _has_gsr_summary(it.get("items") or []):
            return True
    return False


def _coerce_item(raw):
    """Normalise an admin-supplied top-level item dict. Containers
    (``kind: 'container'``) are normalised into ``{kind, label,
    items: [...]}`` with each inner item run through :func:`_coerce_leaf`.
    Empty containers (no inner items survived) are dropped — a container
    with nothing in it has no public render and no purpose. Containers
    can NOT nest (any inner item with ``kind == 'container'`` is
    rejected by ``_coerce_leaf``). Non-container items are normalised
    via :func:`_coerce_leaf` directly."""
    if not isinstance(raw, dict):
        return None
    kind = (raw.get("kind") or "link").strip().lower()
    if kind == _CONTAINER_KIND:
        label = (raw.get("label") or "").strip()
        collapsed_icon = (raw.get("collapsed_icon") or "").strip()
        items_raw = raw.get("items") or []
        if not isinstance(items_raw, list):
            return None
        items = []
        for it in items_raw:
            leaf = _coerce_leaf(it)
            if leaf is not None:
                items.append(leaf)
        if not items:
            return None
        return {"kind": _CONTAINER_KIND, "label": label,
                "collapsed_icon": collapsed_icon, "items": items}
    return _coerce_leaf(raw)


def parse_items(raw_json):
    """Parse one side's JSON column into a list of normalised items.
    Always returns a list — invalid JSON or wrong shape collapses to []."""
    if not raw_json:
        return []
    try:
        data = json.loads(raw_json)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for raw in data:
        coerced = _coerce_item(raw)
        if coerced is not None:
            out.append(coerced)
    return out


def serialise_items(items):
    """Inverse of :func:`parse_items` — produce the JSON string we store
    on the ``SiteSetting`` columns."""
    safe = []
    for raw in items or []:
        c = _coerce_item(raw)
        if c is not None:
            safe.append(c)
    return json.dumps(safe)


def parse_form_payload(form, side):
    """Pull a JSON-encoded ``utility_<side>_payload`` field out of the
    admin POST and return the normalised item list (containers
    included). The admin form's drag-drop UI builds this payload in JS
    on submit so the server gets the full nested shape in one field
    instead of trying to reconstruct it from parallel arrays."""
    raw = form.get(f"utility_{side}_payload")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, list):
        return None
    out = []
    for entry in data:
        coerced = _coerce_item(entry)
        if coerced is not None:
            out.append(coerced)
    return out


def parse_form_items(form, side):
    """Pull repeating ``utility_<side>_kind[]`` / ``label[]`` / ``url[]``
    / ``icon[]`` / ``open_in_new_tab[]`` lists out of the admin POST
    payload and return the normalised item list. Indices line up across
    fields so item N's kind matches item N's label etc."""
    prefix = f"utility_{side}_"
    kinds   = form.getlist(prefix + "kind[]")
    labels  = form.getlist(prefix + "label[]")
    urls    = form.getlist(prefix + "url[]")
    icons   = form.getlist(prefix + "icon[]")
    new_tabs = set(form.getlist(prefix + "open_in_new_tab[]"))
    n = max(len(kinds), len(labels), len(urls), len(icons))
    items = []
    for i in range(n):
        item = {
            "kind":  kinds[i] if i < len(kinds) else "",
            "label": labels[i] if i < len(labels) else "",
            "url":   urls[i] if i < len(urls) else "",
            "icon":  icons[i] if i < len(icons) else "",
            "open_in_new_tab": str(i) in new_tabs,
        }
        coerced = _coerce_item(item)
        if coerced is not None:
            items.append(coerced)
    return items


def utility_bar_context(site):
    """Return a dict the templates can render directly.

    ``enabled``            — hard on/off switch (admin can fully hide
                              the bar without losing their content)
    ``bg_color``           — hex string (admin-chosen) or None
    ``text_color``         — hex string (admin-chosen) or None
    ``left``               — list of normalised items
    ``right``              — list of normalised items
    ``show_live``          — admin enabled the live-meeting badge
    ``show_theme_toggle``  — append the dark-mode toggle button to the
                              right side; set by the per-theme header
                              partial when the toggle is part of that
                              theme's chrome (currently Recovery Blue).
    """
    if not site:
        return {"enabled": False, "bg_color": None, "text_color": None,
                "left": [], "right": [], "show_live": False,
                "show_theme_toggle": False, "mobile_default": ""}
    header_tpl = (getattr(site, "frontend_header_template", None) or "").strip()
    left = parse_items(getattr(site, "utility_bar_left_json", None))
    right = parse_items(getattr(site, "utility_bar_right_json", None))
    show_theme_toggle = header_tpl == "recovery-blue"
    # Auto-inject the theme-toggle row when this theme owns it but the
    # saved items don't carry one yet. Lands at the end of the right
    # side by default — matching the pre-draggable behaviour. Once it
    # exists in the items stream the admin can drag it anywhere; on
    # save the new position persists. Removing it via a malformed POST
    # just causes the next render to inject it again, so the toggle
    # can't be permanently lost.
    if show_theme_toggle and not _has_theme_toggle(left + right):
        right.append({"kind": _THEME_TOGGLE_KIND})
    # Search trigger is a fixture for every site — auto-inject when the
    # admin's saved items don't carry one yet. Lands at the start of
    # the right side (just left of the theme toggle by default) so the
    # default ordering matches what visitors expect from a command-bar
    # icon. Once it exists in the items stream the admin can drag it
    # anywhere; on save the new position persists. Removing it via a
    # malformed POST just causes the next render to inject it again,
    # so the trigger can't be permanently lost.
    if not _has_search_trigger(left + right):
        right.insert(0, {"kind": _SEARCH_TRIGGER_KIND})
    # GSR Summary pill — singleton fixture. Auto-inject only when posts
    # are enabled (the pill links to /announcements which 404s without
    # posts) so a site that's turned off the announcements feature
    # doesn't carry an unreachable button. Once posts come back on, the
    # next render injects one and the admin can drag it into place.
    if getattr(site, "posts_enabled", True) and not _has_gsr_summary(left + right):
        right.insert(0, {"kind": _GSR_SUMMARY_KIND})
    raw_default = (getattr(site, "utility_bar_mobile_default", None) or "").strip()
    mobile_default = _resolve_mobile_default(raw_default, left, right)
    return {
        "enabled":           bool(getattr(site, "utility_bar_enabled", True)),
        "bg_color":          getattr(site, "utility_bar_bg_color", None) or None,
        "text_color":        getattr(site, "utility_bar_text_color", None) or None,
        "left":              left,
        "right":             right,
        "show_live":         bool(getattr(site, "utility_bar_live_meetings", False)),
        "show_theme_toggle": show_theme_toggle,
        "mobile_default":    mobile_default,
    }


def _resolve_mobile_default(raw, left, right):
    """Validate the stored selector against the current item lists.

    Accepted shapes:
      ``"left:N"`` / ``"right:N"`` — show that single item by default
      ``"left"`` / ``"right"``     — show that whole side as one group
    Falls back to the first item that exists on either side so the
    mobile strip always has a sane initial scroll target. Returns the
    normalised selector, or '' when the bar has no items at all."""
    raw = (raw or "").strip().lower()
    if raw == "left" and left:
        return "left"
    if raw == "right" and right:
        return "right"
    if ":" in raw:
        side, _, idx = raw.partition(":")
        try:
            i = int(idx)
        except (TypeError, ValueError):
            i = -1
        if side == "left" and 0 <= i < len(left):
            return f"left:{i}"
        if side == "right" and 0 <= i < len(right):
            return f"right:{i}"
    if left:
        return "left:0"
    if right:
        return "right:0"
    return ""


# ── Live meeting resolver ──────────────────────────────────────────────
def _hhmm_to_min(s):
    if not s or ":" not in s:
        return None
    try:
        h, m = s.split(":", 1)
        return int(h) * 60 + int(m)
    except (ValueError, TypeError):
        return None


def current_live_meeting(site):
    """Return the (Meeting, MeetingSchedule, join_url) tuple for the
    online/hybrid meeting that is currently live, or None.

    "Live" rules:

    * The meeting must be online or hybrid.
    * Its schedule must be on today's day-of-week (resolved via the
      site's configured timezone — see ``app/timezone.py``).
    * The schedule's *opens time* (or, missing that, its start time)
      has been reached.
    * The schedule's end time (start + duration) has not been reached.

    When two schedules overlap, the most recently opened one wins —
    so the bar switches to the next meeting the moment its opens time
    arrives, even if the previous meeting hasn't ended.
    """
    from .models import Meeting, MeetingSchedule
    from .timezone import now_in
    now = now_in(site)
    today_dow = now.weekday()
    now_min = now.hour * 60 + now.minute

    rows = (MeetingSchedule.query
            .join(Meeting, Meeting.id == MeetingSchedule.meeting_id)
            .filter(Meeting.archived_at.is_(None))
            .filter(Meeting.meeting_type.in_(("online", "hybrid")))
            .filter(MeetingSchedule.day_of_week == today_dow)
            .all())

    best = None
    best_opens = -1
    for sch in rows:
        start = _hhmm_to_min(sch.start_time)
        if start is None:
            continue
        opens = _hhmm_to_min(sch.opens_time) if sch.opens_time else start
        end = start + int(sch.duration_minutes or 60)
        if opens <= now_min < end and opens > best_opens:
            best = sch
            best_opens = opens

    if best is None:
        return None
    m = best.meeting
    join_url = (m.zoom_link or "").strip() or None
    return {"meeting": m, "schedule": best, "join_url": join_url}
