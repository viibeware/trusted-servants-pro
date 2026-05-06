# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frontend-wide search index builder.

Computes a flat list of searchable items (meetings + events) ready for
the client-side global search modal to filter live. Each item carries a
human-readable title + subtitle, the URL to navigate to, a kind tag for
icon/grouping, and a normalised search blob the modal substring-matches
against.

Punctuation is stripped from blobs (apostrophes, ?, !, ., ,, ;, quote +
bracket variants) so a meeting called "What's the T?" resolves equally
for `what`, `whats`, and `what's`. Time colons + the `in-person` hyphen
are deliberately preserved.
"""
import re
from sqlalchemy.orm import joinedload

_PUNCT_STRIP_RE = re.compile(r"[‘’'?!.,;\"“”()\[\]{}]")

_DAY_FULL = ["monday", "tuesday", "wednesday", "thursday",
             "friday", "saturday", "sunday"]

_TYPE_ALIASES = {
    "in_person": ["in person", "in-person", "inperson"],
    "online":    ["online", "zoom", "virtual"],
    "hybrid":    ["hybrid", "online", "zoom", "in person"],
}


def _meeting_search_blob(m):
    """Build the normalised search blob for one Meeting row."""
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
    return _PUNCT_STRIP_RE.sub("", " ".join(parts))


def _meeting_subtitle(m):
    """Short context line for the search-result row."""
    if not m.schedules:
        bits = []
    else:
        s = m.schedules[0]
        day = _DAY_FULL[s.day_of_week][:3].title() if 0 <= (s.day_of_week or 0) < 7 else ""
        time = ""
        if s.start_time:
            try:
                hh, mm = s.start_time.split(":")
                h, mn = int(hh), int(mm)
                h12 = h % 12 if h % 12 != 0 else 12
                ampm = "am" if h < 12 else "pm"
                time = ("%d:%02d %s" % (h12, mn, ampm)) if mn else ("%d %s" % (h12, ampm))
            except (ValueError, TypeError):
                pass
        bits = [b for b in (day, time) if b]
    type_label = {"in_person": "In Person",
                  "online": "Online",
                  "hybrid": "Hybrid"}.get(m.meeting_type, "")
    if type_label:
        bits.append(type_label)
    if m.location:
        bits.append(m.location)
    return " · ".join(bits)


def _event_search_blob(e):
    parts = []
    if e.title:
        parts.append(e.title.lower())
    if e.summary:
        parts.append(e.summary.lower())
    if getattr(e, "is_event", False):
        parts.append("event")
    if getattr(e, "is_announcement", False):
        parts.append("announcement")
    if getattr(e, "is_online", False):
        parts.extend(["online", "zoom"])
    if getattr(e, "location_name", None):
        parts.append(e.location_name.lower())
    if getattr(e, "event_starts_at", None):
        d = e.event_starts_at
        # Day name, month name, year + numeric variants
        parts.append(_DAY_FULL[d.weekday()])
        parts.append(_DAY_FULL[d.weekday()][:3])
        parts.append(d.strftime("%B").lower())
        parts.append(d.strftime("%b").lower())
        parts.append(d.strftime("%Y"))
        parts.append("%d" % d.day)
    return _PUNCT_STRIP_RE.sub("", " ".join(parts))


def _event_subtitle(e):
    bits = []
    d = getattr(e, "event_starts_at", None)
    if d:
        bits.append(d.strftime("%b %-d, %Y"))
        h, m = d.hour, d.minute
        h12 = h % 12 if h % 12 != 0 else 12
        ampm = "am" if h < 12 else "pm"
        bits.append(("%d:%02d %s" % (h12, m, ampm)) if m else ("%d %s" % (h12, ampm)))
    if getattr(e, "is_online", False):
        bits.append("Online")
    elif getattr(e, "location_name", None):
        bits.append(e.location_name)
    return " · ".join(bits)


# ---------------------------------------------------------------------------
# Extensible search-source registry. Built-in sources (meetings + events) live
# in this file and self-register at module import; downstream code can register
# more sources via :func:`register_search_source`. Each source is a callable
# that accepts ``site`` (the SiteSetting row, possibly None) and returns a
# list of {kind, title, subtitle, url, search} dicts. Returning an empty list
# is fine; raising is fine — :func:`build_search_index` swallows exceptions
# from any one source so a bad plugin never blanks the whole index.
#
# Item shape:
#   kind     — short string used by the client to group + icon. Built-ins
#              register "meeting" / "event"; plugins can introduce any new
#              kind and the client falls back to the kind string as the
#              display label when no override is registered.
#   title    — visible primary line in each result row
#   subtitle — visible secondary line (optional, may be empty)
#   url      — destination on click / Enter
#   search   — punctuation-stripped lowercase blob the client substring-
#              matches against. Use the same regex the built-ins use
#              (``_PUNCT_STRIP_RE``) so adaptive matching stays consistent.
# ---------------------------------------------------------------------------

_SEARCH_SOURCES = []


def register_search_source(fn):
    """Add a callable to the search index. The callable takes ``site``
    and returns a list of item dicts. Returns ``fn`` so the call works
    as a decorator."""
    if fn not in _SEARCH_SOURCES:
        _SEARCH_SOURCES.append(fn)
    return fn


def _meetings_source(site):
    """Built-in source: every active meeting on the site."""
    from flask import url_for
    from .models import Meeting

    items = []
    meetings = (Meeting.query
                .options(joinedload(Meeting.schedules))
                .filter(Meeting.archived_at.is_(None))
                .order_by(Meeting.name.asc())
                .all())
    for m in meetings:
        items.append({
            "kind": "meeting",
            "title": m.name or "",
            "subtitle": _meeting_subtitle(m),
            "url": url_for("frontend.meeting_detail", slug=m.public_slug),
            "search": _meeting_search_blob(m),
        })
    return items


def _events_source(site):
    """Built-in source: every upcoming, non-draft, non-archived event."""
    if not (site and getattr(site, "posts_enabled", True)):
        return []
    from datetime import datetime
    from .models import Post
    from .frontend import _post_url

    items = []
    now = datetime.utcnow()
    events = (Post.query
              .filter(Post.is_event.is_(True),
                      Post.is_archived.is_(False),
                      Post.is_draft.is_(False))
              .order_by(Post.event_starts_at.asc().nulls_last())
              .all())
    for e in events:
        ref_end = e.event_ends_at or e.event_starts_at
        if ref_end is not None and ref_end < now:
            continue
        items.append({
            "kind": "event",
            "title": e.title or "",
            "subtitle": _event_subtitle(e),
            "url": _post_url(e),
            "search": _event_search_blob(e),
        })
    return items


# Self-register the built-in sources so the default index covers
# meetings + events out of the box. The first call wins (the registry
# de-dupes by identity), so re-importing this module won't pile up
# duplicate calls.
register_search_source(_meetings_source)
register_search_source(_events_source)


def build_search_index(site):
    """Run every registered source and return the flat concatenation
    of their items. Exceptions from any one source are swallowed so a
    misbehaving plugin can't break the whole index — failures show up
    in the Flask logger but the rest of the sources keep contributing."""
    import logging
    items = []
    for source in _SEARCH_SOURCES:
        try:
            produced = source(site) or []
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "search source %s failed: %s", getattr(source, "__name__", source), exc)
            continue
        if isinstance(produced, list):
            items.extend(produced)
    return items
