# SPDX-License-Identifier: AGPL-3.0-or-later
"""Inline SVG icon rendering.

Two icon sources are supported:

1. **Built-in Lucide icons** — vendored under ``static/vendor/lucide/``. A JSON
   catalog plus the Lucide ISC license ship with the app. The catalog is
   loaded once at import time. All built-in icons share ``viewBox="0 0 24 24"``
   and ``stroke="currentColor"`` so colour is inherited from the CSS ``color``
   property on the wrapping span.

2. **User-uploaded custom icons** — stored in the ``custom_icon`` table and
   referenced from ``FrontendNavLink.icon_*`` as ``custom:<id>``. Rendered as
   an ``<img>`` element pointing at ``/pub/icon/<id>`` (public, so the frontend
   works for anonymous visitors). Uploaded SVGs keep their original fills; no
   ``currentColor`` rewriting is done.
"""
import json
from pathlib import Path
from markupsafe import Markup, escape

_CATALOG_PATH = Path(__file__).resolve().parent / "static" / "vendor" / "lucide" / "icons.json"

_SVG_ATTRS = (
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"'
)


def _load_catalog():
    with _CATALOG_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    paths = {}
    for cat in data.get("categories", []):
        for ic in cat.get("icons", []):
            name = ic.get("name")
            p = ic.get("paths")
            if name and p:
                paths[name] = p
    return paths


_PATHS = _load_catalog()


def _render_custom(name, extra_class):
    """Render a ``custom:<id>`` reference as an <img> tag. Called from icon()."""
    from .models import CustomIcon, db
    try:
        cid = int(name.split(":", 1)[1])
    except (ValueError, IndexError):
        return Markup("")
    ci = db.session.get(CustomIcon, cid)
    if not ci:
        return Markup("")
    cls = "icon icon-custom" + (" " + extra_class if extra_class else "")
    alt = escape(ci.name or "")
    return Markup(f'<img class="{cls}" src="/pub/icon/{cid}" alt="{alt}">')


def icon(name, extra_class=""):
    if not name:
        return Markup("")
    if name.startswith("custom:"):
        return _render_custom(name, extra_class)
    paths = _PATHS.get(name)
    if not paths:
        return Markup("")
    cls = "icon" + (" " + extra_class if extra_class else "")
    return Markup(f'<svg class="{cls}" {_SVG_ATTRS}>{paths}</svg>')


def icon_names():
    """All available built-in icon names (for backend validation)."""
    return set(_PATHS.keys())
