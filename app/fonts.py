# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vendored font catalog + theme defaults + override resolution.

The frontend uses two sources of fonts:

  - Vendored fonts shipped in ``app/static/fonts/`` (Inter and Fraunces).
  - Admin-added ``CustomFont`` rows: either uploaded font files (TTF/OTF/WOFF/
    WOFF2 served from ``/pub/font/<id>``) or pasted Google Fonts CSS URLs
    loaded via ``<link rel="stylesheet">``.

Custom fonts are referenced everywhere a font key lives (theme overrides,
hero font picker, etc.) using the form ``custom:<id>``.
"""
import json


# Built-in font registry. Each entry has:
#   key       — admin storage value
#   name      — label in the picker
#   stack     — full CSS font-family stack (matches the @font-face block)
#   kind      — sans | serif | display | custom
FONTS = [
    {
        "key": "inter",
        "name": "Inter",
        "stack": "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        "kind": "sans",
    },
    {
        "key": "fraunces",
        "name": "Fraunces",
        "stack": "'Fraunces', 'Inter', Georgia, serif",
        "kind": "serif",
    },
]
FONTS_BY_KEY = {f["key"]: f for f in FONTS}


# Theme defaults — what each semantic role resolves to when the admin
# hasn't overridden it. DCCMA uses Inter everywhere; Classic uses
# Fraunces for headings (anything decorative outside the hero) and
# Inter for body copy. The hero font is independent of the theme — it
# has its own admin picker and never reads these variables.
THEME_DEFAULTS = {
    "classic": {
        "heading": "fraunces",   # logo, section h2/h3, stat numbers, testimonial italic
        "body":    "inter",      # paragraph + UI copy
    },
    "recovery-blue": {
        "heading": "inter",
        "body":    "inter",
    },
}

# Roles available as overrides on the settings page.
ROLES = ["heading", "body"]


def _custom_font_entry(cf):
    """Build a picker-shaped dict for a CustomFont row. Family name is
    quoted so it survives spaces (e.g. "Roboto Slab")."""
    fallback = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    return {
        "id": cf.id,
        "key": f"custom:{cf.id}",
        "name": cf.name,
        "family": cf.family,
        "stack": f"'{cf.family}', {fallback}",
        "kind": "custom",
        "source": cf.source,
        "google_url": cf.google_url,
        "size_bytes": cf.size_bytes or 0,
    }


def custom_fonts():
    """Return the list of CustomFont rows shaped for the picker. Returns an
    empty list if the model isn't available yet (e.g. during early app
    init before db.create_all has run)."""
    try:
        from .models import CustomFont
        return [_custom_font_entry(cf) for cf in CustomFont.query.order_by(CustomFont.name.asc()).all()]
    except Exception:
        return []


def all_fonts():
    """Vendored + admin-uploaded fonts, in picker order."""
    return FONTS + custom_fonts()


def font_by_key(key):
    """Look up a font entry by storage key (vendored or ``custom:<id>``)."""
    if not key:
        return None
    if key in FONTS_BY_KEY:
        return FONTS_BY_KEY[key]
    if key.startswith("custom:"):
        try:
            from .models import db, CustomFont
            cf = db.session.get(CustomFont, int(key.split(":", 1)[1]))
            if cf:
                return _custom_font_entry(cf)
        except (ValueError, TypeError, Exception):
            return None
    return None


def font_stack(key):
    """Return the CSS font-family stack for a font key (or Inter as a safe
    fallback for unknown / deleted keys)."""
    f = font_by_key(key)
    return f["stack"] if f else FONTS_BY_KEY["inter"]["stack"]


def resolve_fonts(site):
    """Return the active font choice per semantic role for a SiteSetting,
    layering admin overrides on top of the active theme's defaults.

    Unknown overrides (font deleted while still referenced) silently fall
    back to the theme default for that role rather than 500ing the page."""
    theme = (site.frontend_theme if site else None) or "classic"
    base = dict(THEME_DEFAULTS.get(theme) or THEME_DEFAULTS["classic"])
    raw = (site.frontend_fonts_json if site else None) or ""
    try:
        overrides = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        overrides = {}
    for role in ROLES:
        v = (overrides.get(role) or "").strip().lower()
        if v and font_by_key(v):
            base[role] = v
    return base


def font_css_vars(site):
    """Emit a string of CSS custom-property declarations to inline on the
    public ``<body>`` so every theme/override flows through one place:

        --fe-font-heading: <stack>;
        --fe-font-body:    <stack>;
    """
    chosen = resolve_fonts(site)
    parts = [f"--fe-font-{role}: {font_stack(chosen[role])};" for role in ROLES]
    return " ".join(parts)
