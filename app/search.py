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


def _text_blob(*parts):
    """Helper: lowercase + strip punctuation from a list of fragments."""
    joined = " ".join(p for p in parts if p)
    return _PUNCT_STRIP_RE.sub("", joined.lower())


def _strip_html(html):
    """Naive HTML-stripper used to turn an admin-authored body field
    into a search-friendly blob. We don't need fidelity — we just need
    to expose the words inside so substring-matching can find them."""
    if not html:
        return ""
    return re.sub(r"<[^>]+>", " ", html)


def _blocks_text(blocks_json):
    """Extract every searchable text fragment from a Page / blocks JSON.
    Walks the same shape ``_blocks.html`` renders (sections → blocks →
    typed fields). Pulls heading / text / rich body / button label /
    caption fields so a page's contents are searchable even though they
    live inside a JSON blob rather than dedicated columns."""
    if not blocks_json:
        return ""
    import json
    try:
        data = json.loads(blocks_json)
    except (ValueError, TypeError):
        return ""
    bits = []
    # The schema is either a list of sections (each with .blocks) or a
    # list of blocks directly — _walk handles both by recursing.
    def _walk(node):
        if isinstance(node, dict):
            for key in ("heading", "subheading", "title", "text", "body",
                        "html", "caption", "label", "alt", "summary"):
                v = node.get(key)
                if isinstance(v, str) and v.strip():
                    bits.append(_strip_html(v))
            for v in node.values():
                if isinstance(v, (dict, list)):
                    _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)
    _walk(data)
    return " ".join(bits)


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
    from .timezone import now_local_naive
    from .models import Post
    from .frontend import _post_url

    items = []
    # event_ends_at is naive site-local; comparing in UTC would
    # hide / show events by the host's UTC offset.
    now = now_local_naive(site)
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


def _announcements_source(site):
    """Built-in source: every live (non-archived, non-draft) announcement.
    Archived announcements come through ``_archive_source`` instead so
    each result row links to the right detail URL."""
    if not (site and getattr(site, "posts_enabled", True)):
        return []
    from flask import url_for
    from .models import Post
    from .frontend import _post_url

    items = []
    rows = (Post.query
            .filter(Post.is_announcement.is_(True),
                    Post.is_event.is_(False),
                    Post.is_archived.is_(False),
                    Post.is_draft.is_(False),
                    Post.is_pending_review.is_(False))
            .order_by(Post.created_at.desc())
            .all())
    for a in rows:
        d = a.published_at or a.created_at
        sub = d.strftime("%b %-d, %Y") if d else ""
        items.append({
            "kind": "announcement",
            "title": a.title or "",
            "subtitle": sub,
            "url": _post_url(a),
            "search": _text_blob(a.title,
                                 a.summary,
                                 _strip_html(a.body),
                                 "announcement",
                                 d.strftime("%B %Y") if d else ""),
        })
    return items


def _archive_source(site):
    """Built-in source: every post on the public /archive page.
    Past events (ended OR explicitly archived) + archived announcements
    — same union the /archive route renders, with each row linking to
    its archive_detail page via ``_post_url``."""
    if not (site and getattr(site, "posts_enabled", True)):
        return []
    from .timezone import now_local_naive
    from .models import Post
    from .frontend import _post_url

    items = []
    # Naive site-local — matches the storage convention of
    # event_ends_at (see _events_source for the same reasoning).
    now = now_local_naive(site)

    # Past events: ended OR explicitly archived. Skip rows with no date
    # so we don't false-positive a brand-new event as archived.
    events = (Post.query
              .filter(Post.is_event.is_(True),
                      Post.is_draft.is_(False),
                      Post.is_pending_review.is_(False))
              .all())
    for e in events:
        ref_end = e.event_ends_at or e.event_starts_at
        if ref_end is None:
            continue
        if not (e.is_archived or ref_end < now):
            continue
        d = e.event_starts_at
        sub_bits = ["Past event"]
        if d:
            sub_bits.append(d.strftime("%b %-d, %Y"))
        if getattr(e, "location_name", None):
            sub_bits.append(e.location_name)
        items.append({
            "kind": "archive",
            "title": e.title or "",
            "subtitle": " · ".join(sub_bits),
            "url": _post_url(e),
            "search": _text_blob(e.title,
                                 e.summary,
                                 _strip_html(e.body),
                                 e.location_name,
                                 "past event archive",
                                 d.strftime("%B %Y") if d else ""),
        })

    # Archived announcements (excludes anything also tagged is_event so
    # mixed posts only appear once, with the event row above).
    announcements = (Post.query
                     .filter(Post.is_announcement.is_(True),
                             Post.is_event.is_(False),
                             Post.is_archived.is_(True),
                             Post.is_draft.is_(False),
                             Post.is_pending_review.is_(False))
                     .all())
    for a in announcements:
        d = a.published_at or a.created_at
        sub_bits = ["Archived announcement"]
        if d:
            sub_bits.append(d.strftime("%b %-d, %Y"))
        items.append({
            "kind": "archive",
            "title": a.title or "",
            "subtitle": " · ".join(sub_bits),
            "url": _post_url(a),
            "search": _text_blob(a.title,
                                 a.summary,
                                 _strip_html(a.body),
                                 "archived announcement",
                                 d.strftime("%B %Y") if d else ""),
        })
    return items


def _stories_source(site):
    """Built-in source: every published, non-archived recovery story."""
    if not (site and getattr(site, "stories_enabled", False)):
        return []
    from flask import url_for
    from .models import Story

    items = []
    rows = (Story.query
            .filter(Story.is_draft.is_(False),
                    Story.is_archived.is_(False))
            .order_by(Story.title.asc())
            .all())
    for s in rows:
        sub_bits = []
        if s.author_name:
            sub_bits.append(s.author_name)
        d = getattr(s, "story_date", None) or s.created_at
        if d:
            sub_bits.append(d.strftime("%b %-d, %Y") if hasattr(d, "hour")
                            else d.strftime("%b %-d, %Y"))
        items.append({
            "kind": "story",
            "title": s.title or "",
            "subtitle": " · ".join(sub_bits),
            "url": url_for("frontend.story_detail", slug=s.public_slug),
            "search": _text_blob(s.title,
                                 s.summary,
                                 _strip_html(s.body),
                                 s.author_name,
                                 "story recovery"),
        })
    return items


def _blog_source(site):
    """Built-in source: every published, non-archived blog post + its
    category / tag names so a category-flavoured search ("anniversaries")
    also surfaces the posts under it."""
    if not (site and getattr(site, "blog_enabled", False)):
        return []
    from flask import url_for
    from .models import BlogPost

    items = []
    rows = (BlogPost.query
            .filter(BlogPost.is_draft.is_(False),
                    BlogPost.is_archived.is_(False))
            .order_by(BlogPost.published_at.desc().nulls_last(),
                      BlogPost.created_at.desc())
            .all())
    for b in rows:
        sub_bits = []
        if b.author_name:
            sub_bits.append(b.author_name)
        d = b.display_date
        if d:
            sub_bits.append(d.strftime("%b %-d, %Y"))
        cat_names = [c.name for c in (b.categories or []) if c and c.name]
        tag_names = [t.name for t in (b.tags or []) if t and t.name]
        items.append({
            "kind": "blog",
            "title": b.title or "",
            "subtitle": " · ".join(sub_bits) or "Blog post",
            "url": url_for("frontend.blog_post_detail", slug=b.public_slug),
            "search": _text_blob(b.title,
                                 b.summary,
                                 _strip_html(b.body),
                                 b.author_name,
                                 " ".join(cat_names),
                                 " ".join(tag_names),
                                 "blog post"),
        })
    return items


def _library_source(site):
    """Built-in source: every public-visible Library + its public-
    visible items. Each result anchors into the /library page so the
    visitor lands on the right card / section."""
    from flask import url_for
    from .models import Library, LibraryItem

    items = []
    libs = (Library.query
            .filter_by(public_visible=True)
            .order_by(Library.name.asc())
            .all())
    base_url = url_for("frontend.literature_library")
    for lib in libs:
        items.append({
            "kind": "library",
            "title": lib.name or "",
            "subtitle": "Library",
            "url": base_url + "#lib-" + str(lib.id),
            "search": _text_blob(lib.name, lib.description, "library"),
        })
        for it in (LibraryItem.query
                   .filter_by(library_id=lib.id, public_visible=True)
                   .order_by(LibraryItem.title.asc())
                   .all()):
            items.append({
                "kind": "library",
                "title": it.title or "",
                "subtitle": lib.name or "Library item",
                "url": base_url + "#item-" + str(it.id),
                "search": _text_blob(it.title,
                                     _strip_html(it.body),
                                     it.original_filename,
                                     lib.name,
                                     "library item reading"),
            })
    return items


def _pages_source(site):
    """Built-in source: every admin-authored Page row that's published
    and not marked private. Search blob walks the page's blocks JSON so
    body content is searchable, not just the title."""
    from flask import url_for
    from .models import Page

    items = []
    rows = (Page.query
            .filter_by(is_published=True, is_private=False)
            .order_by(Page.title.asc())
            .all())
    for p in rows:
        items.append({
            "kind": "page",
            "title": p.title or "",
            "subtitle": "/" + p.slug,
            "url": url_for("frontend.page_detail", slug=p.slug),
            "search": _text_blob(p.title, p.slug, _blocks_text(p.blocks_json), "page"),
        })
    return items


def _fellowships_source(site):
    """Built-in source: every row in the admin-curated Fellowships
    Index. Only emits items when the public /fellowships page is on
    (``frontend_fellowships_enabled``) so a toggle-off mirrors what
    the route + /siteindex already do — no orphan results pointing to
    a 404. Each result anchors into /fellowships at the row's name
    via #fellowship-<id> for easy scroll-to-card."""
    if not (site and getattr(site, "frontend_fellowships_enabled", False)):
        return []
    from flask import url_for
    from .models import Fellowship

    items = []
    rows = (Fellowship.query
            .order_by(Fellowship.sort_order, Fellowship.id)
            .all())
    base_url = url_for("frontend.fellowships_list")
    for f in rows:
        if f.is_virtual:
            sub_bits = ["Virtual"]
            type_blob = "virtual online"
        else:
            sub_bits = []
            if f.state_region:
                sub_bits.append(f.state_region)
            if f.country:
                sub_bits.append(f.country)
            if not sub_bits:
                sub_bits.append("Regional")
            type_blob = "regional"
        items.append({
            "kind": "fellowship",
            "title": f.name or "",
            "subtitle": " · ".join(sub_bits),
            "url": base_url + "#fellowship-" + str(f.id),
            "search": _text_blob(f.name,
                                 f.country,
                                 f.state_region,
                                 f.url,
                                 type_blob,
                                 "fellowship recovery"),
        })
    return items


def _sections_source(site):
    """Built-in source: every top-level public template page registered
    via ``@public_section`` (Home, Meetings, Hyperlist, Events, Archive,
    Announcements, Stories, Blog, Library, Print list, Submit, Contact).
    Pulled live from the same registry /siteindex uses, so a new
    top-level page becomes findable in search just by carrying the
    decorator — no second edit needed here."""
    from flask import url_for
    from .frontend import _PUBLIC_SECTIONS

    items = []
    seen = set()
    for entry in _PUBLIC_SECTIONS:
        endpoint = entry["endpoint"]
        if endpoint in seen:
            continue
        seen.add(endpoint)
        try:
            if not entry["gate"](site):
                continue
            url_ = url_for(endpoint)
        except Exception:
            continue
        title = entry["title"]
        items.append({
            "kind": "section",
            "title": title,
            "subtitle": url_,
            "url": url_,
            "search": _text_blob(title, url_, "section page"),
        })
    return items


# Self-register the built-in sources so the default index covers
# every public surface out of the box. The first call wins (the
# registry de-dupes by identity), so re-importing this module won't
# pile up duplicate calls.
register_search_source(_meetings_source)
register_search_source(_events_source)
register_search_source(_announcements_source)
register_search_source(_archive_source)
register_search_source(_stories_source)
register_search_source(_blog_source)
register_search_source(_library_source)
register_search_source(_pages_source)
register_search_source(_fellowships_source)
register_search_source(_sections_source)


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
