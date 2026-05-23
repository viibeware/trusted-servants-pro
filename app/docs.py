# SPDX-License-Identifier: AGPL-3.0-or-later
"""Product documentation site.

A small, file-driven docs system that lives alongside the marketing homepage
(both are demo-mode-only — see :mod:`app.product`). Each guide is a Markdown
file in ``app/docs_content/`` with a short metadata header::

    Title: Installation
    Category: Getting Started
    Order: 2
    Slug: installation
    Icon: download
    Summary: One-line description used on cards and in search.

    ## First section
    prose...

At import time every file is parsed once into an in-memory registry: rendered
HTML, a heading table-of-contents (for the right rail), and a plaintext copy
(for the client-side search index). To add a guide, drop in a new ``.md`` file
and restart — no code changes required.

Routes:
  * ``/docs``              → overview, guides grouped by category.
  * ``/docs/<slug>``       → a single guide.
  * ``/docs/search.json``  → the search index consumed by ``docs.js``.
"""
import os
import re
import logging
from datetime import datetime

import markdown
from flask import Blueprint, render_template, abort, jsonify

log = logging.getLogger(__name__)

CONTENT_DIR = os.path.join(os.path.dirname(__file__), "docs_content")

# Categories render in this order in the sidebar and on the overview page.
# Anything not listed here falls to the end, alphabetically.
CATEGORY_ORDER = ["Getting Started", "Configuration", "Operations"]

_MD_EXTENSIONS = ["extra", "toc", "admonition", "sane_lists", "meta", "attr_list"]

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

bp = Blueprint("docs", __name__)


@bp.context_processor
def _inject_year():
    """Scoped to docs requests — the base template's footer uses `year`."""
    return {"year": datetime.utcnow().year}

# Populated by _load() at import time: slug -> guide dict.
_GUIDES = {}
# Ordered list of {"category": str, "guides": [guide, ...]} for the sidebar.
_NAV = []


def _meta_str(meta, key, default=""):
    """Markdown's `meta` extension returns each key as a list of lines."""
    val = meta.get(key)
    if not val:
        return default
    return " ".join(val).strip()


def _plaintext(html):
    """Strip tags + collapse whitespace for the search index."""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", html)).strip()


def _parse_file(path):
    """Parse one Markdown guide into a registry dict, or return None on error."""
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()

    # A fresh converter per file keeps `toc_tokens` / `Meta` state isolated.
    md = markdown.Markdown(extensions=_MD_EXTENSIONS)
    html = md.convert(raw)
    meta = getattr(md, "Meta", {}) or {}

    title = _meta_str(meta, "title")
    if not title:
        log.warning("docs: skipping %s — no Title metadata", os.path.basename(path))
        return None

    stem = os.path.splitext(os.path.basename(path))[0]
    slug = _meta_str(meta, "slug") or stem
    try:
        order = int(_meta_str(meta, "order", "100"))
    except ValueError:
        order = 100

    text = _plaintext(html)
    words = len(text.split())

    return {
        "slug": slug,
        "title": title,
        "category": _meta_str(meta, "category", "Guides"),
        "order": order,
        "icon": _meta_str(meta, "icon", "book"),
        "summary": _meta_str(meta, "summary"),
        "html": html,
        # toc_tokens: nested [{level, id, name, children:[...]}]; the body starts
        # at H2, so the top level is section headings.
        "toc": getattr(md, "toc_tokens", []),
        "text": text,
        "reading_min": max(1, round(words / 200)),
    }


def _load():
    """Parse every guide and build the slug map + grouped sidebar nav."""
    _GUIDES.clear()
    del _NAV[:]

    if not os.path.isdir(CONTENT_DIR):
        log.warning("docs: content dir %s does not exist", CONTENT_DIR)
        return

    for fn in os.listdir(CONTENT_DIR):
        if not fn.endswith(".md"):
            continue
        try:
            guide = _parse_file(os.path.join(CONTENT_DIR, fn))
        except Exception:  # noqa: BLE001 — one bad file must not break the site
            log.exception("docs: failed to parse %s", fn)
            continue
        if guide:
            _GUIDES[guide["slug"]] = guide

    # Group by category, ordering categories by CATEGORY_ORDER (unknowns last),
    # and guides within a category by their Order then Title.
    def cat_key(cat):
        return (CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER
                else len(CATEGORY_ORDER), cat)

    by_cat = {}
    for g in _GUIDES.values():
        by_cat.setdefault(g["category"], []).append(g)

    for cat in sorted(by_cat, key=cat_key):
        guides = sorted(by_cat[cat], key=lambda g: (g["order"], g["title"]))
        _NAV.append({"category": cat, "guides": guides})


def _nav():
    return _NAV


@bp.route("/docs")
def index():
    return render_template("product/docs_index.html", nav=_nav(), current_slug=None)


@bp.route("/docs/search.json")
def search():
    """Flat index for the client-side search in docs.js."""
    items = [{
        "slug": g["slug"],
        "title": g["title"],
        "category": g["category"],
        "summary": g["summary"],
        "url": f"/docs/{g['slug']}",
        "headings": [{"id": t["id"], "name": t["name"]}
                     for t in g["toc"]],
        "text": g["text"],
    } for g in _GUIDES.values()]
    return jsonify(items)


@bp.route("/docs/<slug>")
def article(slug):
    guide = _GUIDES.get(slug)
    if guide is None:
        abort(404)
    return render_template("product/docs_article.html",
                           nav=_nav(), guide=guide, current_slug=slug)


def register(app):
    """Parse content and mount the docs blueprint. Called from product.register."""
    _load()
    app.register_blueprint(bp)
