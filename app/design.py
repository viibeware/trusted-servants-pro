# SPDX-License-Identifier: AGPL-3.0-or-later
"""Site-wide design tokens for the public web frontend.

Theme defaults flow as CSS custom properties on the public ``<body>``;
the admin can override any subset via the Site → Design admin page.
Per-section settings (e.g. the two-panel split's spacing dropdowns)
should resolve through the same scales so picking "Tight" anywhere
maps to the same value site-wide.

The font system in :mod:`app.fonts` follows the same model and is
declared as a sibling — design.py covers everything else (spacing,
radius, shadow, colors, buttons, links, text).
"""
import json
import re


# ----- Scales — the design language's vocabulary --------------------

# Spacing scale. Every gap/margin/padding default — and every per-section
# spacing dropdown — should resolve through one of these keys.
SPACING_SCALE = {
    "none": "0",
    "xs":   "0.25rem",
    "sm":   "0.5rem",
    "md":   "1rem",
    "lg":   "2rem",
    "xl":   "4rem",
    "2xl":  "6rem",
}
SPACING_KEYS = list(SPACING_SCALE.keys())

RADIUS_SCALE = {
    "none": "0",
    "sm":   "4px",
    "md":   "8px",
    "lg":   "16px",
    "pill": "999px",
}
RADIUS_KEYS = list(RADIUS_SCALE.keys())

SHADOW_SCALE = {
    "none": "none",
    "sm":   "0 1px 2px rgba(15, 23, 42, 0.06)",
    "md":   "0 4px 12px rgba(15, 23, 42, 0.10)",
    "lg":   "0 12px 28px rgba(15, 23, 42, 0.14)",
}
SHADOW_KEYS = list(SHADOW_SCALE.keys())

WEIGHT_KEYS = ["400", "500", "600", "700", "800"]
TEXT_TRANSFORM_KEYS = ["none", "uppercase"]
LINK_DECORATION_KEYS = ["none", "underline", "dotted"]


# ----- Theme defaults — what each token resolves to per theme -------

THEME_DEFAULTS = {
    "classic": {
        "color_brand":        "#0b5cff",
        "color_accent":       "#f59e0b",
        "color_surface":      "#ffffff",
        "color_surface_alt":  "#f8fafc",
        "color_border":       "#e2e8f0",
        "color_text":         "#0f172a",
        "color_text_soft":    "#475569",
        "color_link":         "#0b5cff",
        "color_link_hover":   "#0844c2",
        "color_nav_link":          "#0f172a",
        "color_nav_link_hover":    "#0b5cff",
        "color_megamenu_link":       "#ffffff",
        "color_megamenu_link_hover": "#ffffff",

        "section_gap":        "lg",
        "container_max_px":   1160,
        "card_radius":        "lg",
        "card_shadow":        "md",

        "btn_radius":         "md",
        "btn_padding_x":      "md",
        "btn_padding_y":      "sm",
        "btn_weight":         "600",
        "btn_text_transform": "none",
        "btn_decoration":     "none",

        "link_decoration":       "none",
        "link_decoration_hover": "underline",
        "megamenu_link_decoration":       "none",
        "megamenu_link_decoration_hover": "none",

        "text_size_base":     "1rem",
        "text_line_height":   "1.6",
    },
    "recovery-blue": {
        "color_brand":        "#0b5cff",
        "color_accent":       "#0ea5e9",
        "color_surface":      "#ffffff",
        "color_surface_alt":  "#f1f5f9",
        "color_border":       "#cbd5e1",
        "color_text":         "#1e293b",
        "color_text_soft":    "#64748b",
        "color_link":         "#0b5cff",
        "color_link_hover":   "#0844c2",
        "color_nav_link":          "#1e293b",
        "color_nav_link_hover":    "#0b5cff",
        "color_megamenu_link":       "#ffffff",
        "color_megamenu_link_hover": "#ffffff",

        "section_gap":        "lg",
        "container_max_px":   1200,
        "card_radius":        "md",
        "card_shadow":        "sm",

        "btn_radius":         "md",
        "btn_padding_x":      "md",
        "btn_padding_y":      "sm",
        "btn_weight":         "700",
        "btn_text_transform": "uppercase",
        "btn_decoration":     "none",

        "link_decoration":       "underline",
        "link_decoration_hover": "underline",
        "megamenu_link_decoration":       "none",
        "megamenu_link_decoration_hover": "none",

        "text_size_base":     "1rem",
        "text_line_height":   "1.55",
    },
}


# ----- Field schema ---------------------------------------------------
# Drives the admin form, the saved-value validator, and the css_vars
# emitter. Each entry has a `kind`:
#   "color"  — hex string (#rgb / #rrggbb / #rrggbbaa)
#   "scale"  — one of SPACING_KEYS / RADIUS_KEYS / SHADOW_KEYS keyed by `scale`
#   "select" — explicit `choices` list
#   "int"    — integer with optional min/max
#   "text"   — short free string (length-capped)

DESIGN_FIELDS = [
    # ----- Colors -----
    {"key": "color_brand",       "kind": "color",  "group": "Colors", "label": "Brand"},
    {"key": "color_accent",      "kind": "color",  "group": "Colors", "label": "Accent"},
    {"key": "color_surface",     "kind": "color",  "group": "Colors", "label": "Surface (page bg)"},
    {"key": "color_surface_alt", "kind": "color",  "group": "Colors", "label": "Surface — alt"},
    {"key": "color_border",      "kind": "color",  "group": "Colors", "label": "Border"},
    {"key": "color_text",        "kind": "color",  "group": "Colors", "label": "Text"},
    {"key": "color_text_soft",   "kind": "color",  "group": "Colors", "label": "Text — muted"},
    {"key": "color_link",        "kind": "color",  "group": "Colors", "label": "Link"},
    {"key": "color_link_hover",  "kind": "color",  "group": "Colors", "label": "Link — hover"},
    {"key": "color_nav_link",         "kind": "color", "group": "Colors", "label": "Header nav link"},
    {"key": "color_nav_link_hover",   "kind": "color", "group": "Colors", "label": "Header nav link — hover"},
    {"key": "color_megamenu_link",       "kind": "color", "group": "Colors", "label": "Mega-menu link"},
    {"key": "color_megamenu_link_hover", "kind": "color", "group": "Colors", "label": "Mega-menu link — hover"},

    # ----- Layout -----
    {"key": "section_gap",      "kind": "scale", "scale": "spacing",
     "group": "Layout", "label": "Default section spacing",
     "help": "Vertical rhythm between top-level sections."},
    {"key": "container_max_px", "kind": "int", "min": 720, "max": 1600, "step": 20,
     "group": "Layout", "label": "Container max width (px)"},
    {"key": "card_radius", "kind": "scale", "scale": "radius",
     "group": "Layout", "label": "Card radius"},
    {"key": "card_shadow", "kind": "scale", "scale": "shadow",
     "group": "Layout", "label": "Card shadow"},

    # ----- Buttons -----
    {"key": "btn_radius",         "kind": "scale", "scale": "radius",
     "group": "Buttons", "label": "Radius"},
    {"key": "btn_padding_x",      "kind": "scale", "scale": "spacing",
     "group": "Buttons", "label": "Horizontal padding"},
    {"key": "btn_padding_y",      "kind": "scale", "scale": "spacing",
     "group": "Buttons", "label": "Vertical padding"},
    {"key": "btn_weight",         "kind": "select", "choices": WEIGHT_KEYS,
     "group": "Buttons", "label": "Font weight"},
    {"key": "btn_text_transform", "kind": "select", "choices": TEXT_TRANSFORM_KEYS,
     "group": "Buttons", "label": "Text transform"},
    {"key": "btn_decoration", "kind": "select", "choices": LINK_DECORATION_KEYS,
     "group": "Buttons", "label": "Text decoration",
     "help": "Off (`none`) keeps anchor-styled buttons free of underline."},

    # ----- Links -----
    {"key": "link_decoration",       "kind": "select", "choices": LINK_DECORATION_KEYS,
     "group": "Links", "label": "Body link decoration"},
    {"key": "link_decoration_hover", "kind": "select", "choices": LINK_DECORATION_KEYS,
     "group": "Links", "label": "Body link decoration on hover"},
    {"key": "megamenu_link_decoration",       "kind": "select", "choices": LINK_DECORATION_KEYS,
     "group": "Links", "label": "Mega-menu link decoration"},
    {"key": "megamenu_link_decoration_hover", "kind": "select", "choices": LINK_DECORATION_KEYS,
     "group": "Links", "label": "Mega-menu link decoration on hover"},

    # ----- Text -----
    {"key": "text_size_base",   "kind": "text", "max_len": 16,
     "group": "Text", "label": "Base size", "placeholder": "1rem"},
    {"key": "text_line_height", "kind": "text", "max_len": 16,
     "group": "Text", "label": "Line height", "placeholder": "1.6"},
]
DESIGN_FIELDS_BY_KEY = {f["key"]: f for f in DESIGN_FIELDS}
DESIGN_GROUPS = ["Colors", "Layout", "Buttons", "Links", "Text"]

# Map "scale" name → the actual scale dict.
SCALES = {"spacing": SPACING_SCALE, "radius": RADIUS_SCALE, "shadow": SHADOW_SCALE}


_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def derive_dark_color(hex_str):
    """Return a dark-mode-friendly variant of an arbitrary hex color.

    Strategy: convert to HLS, preserve hue + saturation, clamp lightness
    into a dark band (12% or 16% depending on saturation so very
    saturated colours don't disappear into black). Returns None on
    invalid input. Used by the two-panel split's dark-mode-aware bg
    toggle so an admin's chosen pastel automatically gets a sensible
    dark companion in dark mode."""
    import colorsys
    if not isinstance(hex_str, str) or not _HEX_RE.match(hex_str):
        return None
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 8:  # drop alpha; we only emit #rrggbb output
        h = h[:6]
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
    except ValueError:
        return None
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    new_l = 0.16 if sat > 0.5 else 0.12
    nr, ng, nb = colorsys.hls_to_rgb(hue, new_l, sat)
    return "#{:02x}{:02x}{:02x}".format(int(nr * 255), int(ng * 255), int(nb * 255))


def _coerce(field, value):
    """Validate + coerce a single override value. Returns the safe value
    or None if the input is invalid (caller skips invalid overrides)."""
    if value is None:
        return None
    kind = field["kind"]
    if kind == "color":
        if isinstance(value, str) and _HEX_RE.match(value):
            return value
    elif kind == "scale":
        scale = SCALES.get(field.get("scale")) or {}
        if value in scale:
            return value
    elif kind == "select":
        if value in field.get("choices", []):
            return value
    elif kind == "int":
        try:
            iv = int(value)
        except (TypeError, ValueError):
            return None
        lo = field.get("min", 0)
        hi = field.get("max", 1_000_000)
        if lo <= iv <= hi:
            return iv
    elif kind == "text":
        if isinstance(value, str):
            v = value.strip()
            if 0 < len(v) <= field.get("max_len", 80):
                return v
    return None


def resolve_design(site):
    """Layer site overrides on top of the active theme's defaults."""
    theme = (site.frontend_theme if site else None) or "classic"
    base = dict(THEME_DEFAULTS.get(theme) or THEME_DEFAULTS["classic"])
    raw = (site.frontend_design_json if site else None) or ""
    try:
        overrides = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        overrides = {}
    for key, val in (overrides or {}).items():
        f = DESIGN_FIELDS_BY_KEY.get(key)
        if not f:
            continue
        coerced = _coerce(f, val)
        if coerced is not None:
            base[key] = coerced
    return base


def parse_design_form(form):
    """Read posted form fields keyed ``design_<token_key>`` and return a
    dict of valid overrides only. Empty / missing / invalid inputs are
    treated as 'not overridden' so the theme default takes over.

    Color fields are gated by a ``design_<key>_enabled`` checkbox: native
    ``<input type=color>`` always submits a value, so without the
    checkbox we couldn't tell "user picked this colour" from "user left
    it on the theme default". When the checkbox is missing, the colour
    is treated as not-overridden."""
    out = {}
    for f in DESIGN_FIELDS:
        if f["kind"] == "color" and form.get("design_" + f["key"] + "_enabled") != "1":
            continue
        raw = form.get("design_" + f["key"])
        if raw is None:
            continue
        if isinstance(raw, str) and not raw.strip():
            continue
        coerced = _coerce(f, raw)
        if coerced is not None:
            out[f["key"]] = coerced
    return out


def design_css_vars(site):
    """CSS custom-property string for the public ``<body>`` style.

    Emits both the raw scales (so any consumer can write
    ``padding: var(--fe-space-md)`` etc.) AND the resolved per-token
    defaults (e.g. ``--fe-color-brand``, ``--fe-btn-radius``)."""
    parts = []

    # Scales (always available, identical site-wide).
    for k, v in SPACING_SCALE.items():
        parts.append(f"--fe-space-{k}: {v};")
    for k, v in RADIUS_SCALE.items():
        parts.append(f"--fe-radius-{k}: {v};")
    for k, v in SHADOW_SCALE.items():
        parts.append(f"--fe-shadow-{k}: {v};")

    chosen = resolve_design(site)

    # Colors (raw hex).
    for key in ("color_brand", "color_accent", "color_surface", "color_surface_alt",
                "color_border", "color_text", "color_text_soft",
                "color_link", "color_link_hover",
                "color_nav_link", "color_nav_link_hover",
                "color_megamenu_link", "color_megamenu_link_hover"):
        parts.append("--fe-{}: {};".format(key.replace("_", "-"), chosen[key]))

    # Auto-derived dark-mode variants for chrome links that sit on dark
    # surfaces (mega menu). Uses the existing colors.dark_variant helper
    # which brightens hue-preserving toward the 0.70–0.92 lightness band
    # so a pure-white input becomes a slightly-dimmed off-white in dark
    # mode rather than staying harsh #ffffff.
    from .colors import dark_variant
    parts.append(f"--fe-color-megamenu-link-dark: {dark_variant(chosen['color_megamenu_link'])};")
    parts.append(f"--fe-color-megamenu-link-hover-dark: {dark_variant(chosen['color_megamenu_link_hover'])};")

    # Layout.
    parts.append(f"--fe-section-gap: var(--fe-space-{chosen['section_gap']});")
    parts.append(f"--fe-container-max: {chosen['container_max_px']}px;")
    parts.append(f"--fe-card-radius: var(--fe-radius-{chosen['card_radius']});")
    parts.append(f"--fe-card-shadow: var(--fe-shadow-{chosen['card_shadow']});")

    # Buttons.
    parts.append(f"--fe-btn-radius: var(--fe-radius-{chosen['btn_radius']});")
    parts.append(f"--fe-btn-padding-x: var(--fe-space-{chosen['btn_padding_x']});")
    parts.append(f"--fe-btn-padding-y: var(--fe-space-{chosen['btn_padding_y']});")
    parts.append(f"--fe-btn-weight: {chosen['btn_weight']};")
    parts.append(f"--fe-btn-text-transform: {chosen['btn_text_transform']};")
    parts.append(f"--fe-btn-decoration: {chosen['btn_decoration']};")

    # Links.
    parts.append(f"--fe-link-decoration: {chosen['link_decoration']};")
    parts.append(f"--fe-link-decoration-hover: {chosen['link_decoration_hover']};")
    parts.append(f"--fe-megamenu-link-decoration: {chosen['megamenu_link_decoration']};")
    parts.append(f"--fe-megamenu-link-decoration-hover: {chosen['megamenu_link_decoration_hover']};")

    # Text.
    parts.append(f"--fe-text-size-base: {chosen['text_size_base']};")
    parts.append(f"--fe-text-line-height: {chosen['text_line_height']};")

    return " ".join(parts)
