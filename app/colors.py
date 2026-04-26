# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small colour utilities. Currently: derive a dark-mode variant of a hex colour.

The transform inverts HSL lightness around 50% while preserving hue and
saturation, then clamps to a 15–85% band so extreme colours stay visible on
the opposite background. Exposed as a Jinja filter ``| dark_variant``.
"""


def _hex_to_rgb(h):
    if not h:
        raise ValueError("empty color")
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) not in (6, 8):
        raise ValueError(f"bad hex color: {h!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r, g, b):
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, int(round(r)))),
        max(0, min(255, int(round(g)))),
        max(0, min(255, int(round(b)))),
    )


def _rgb_to_hsl(r, g, b):
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2.0
    if mx == mn:
        return 0.0, 0.0, l
    d = mx - mn
    s = d / (2.0 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == r:
        h = ((g - b) / d + (6.0 if g < b else 0.0)) / 6.0
    elif mx == g:
        h = ((b - r) / d + 2.0) / 6.0
    else:
        h = ((r - g) / d + 4.0) / 6.0
    return h, s, l


def _hsl_to_rgb(h, s, l):
    if s == 0:
        r = g = b = l
    else:
        def hue2rgb(p, q, t):
            if t < 0:
                t += 1
            if t > 1:
                t -= 1
            if t < 1 / 6:
                return p + (q - p) * 6 * t
            if t < 1 / 2:
                return q
            if t < 2 / 3:
                return p + (q - p) * (2 / 3 - t) * 6
            return p
        q = l * (1 + s) if l < 0.5 else l + s - l * s
        p = 2 * l - q
        r = hue2rgb(p, q, h + 1 / 3)
        g = hue2rgb(p, q, h)
        b = hue2rgb(p, q, h - 1 / 3)
    return r * 255, g * 255, b * 255


import re as _re

def slugify(text):
    """Lowercase, replace any run of non-alphanumerics with a single hyphen,
    and strip leading/trailing hyphens. Returns ``meeting`` for empty input."""
    if text is None:
        return "meeting"
    s = _re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s or "meeting"


def hex_lightness(hex_color):
    """Return the HSL lightness (0–1) for a hex colour, or None if invalid."""
    try:
        r, g, b = _hex_to_rgb(hex_color)
    except (ValueError, AttributeError, TypeError):
        return None
    _, _, l = _rgb_to_hsl(r, g, b)
    return l


def avg_lightness(hex_colors):
    """Average HSL lightness of a list/tuple of hex colours. Returns None
    when the list is empty or every colour is invalid."""
    if not hex_colors:
        return None
    vals = [hex_lightness(c) for c in hex_colors]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def dark_variant(hex_color, target_l=0.70, sat_cap=0.75):
    """Return a hex colour suitable for a dark-mode background.

    Assumes the input was picked for a light background and brightens it enough
    to stay readable on a dark one. Strategy: preserve hue, lift HSL lightness
    to at least ``target_l``, and cap saturation at ``sat_cap`` so fully
    saturated colours don't look neon on dark. Near-white inputs are clamped
    to 0.92 so they don't become pure white and lose contrast with true-white
    UI chrome. If the input is not a valid hex colour it's returned unchanged.
    """
    try:
        r, g, b = _hex_to_rgb(hex_color)
    except (ValueError, AttributeError, TypeError):
        return hex_color
    h, s, l = _rgb_to_hsl(r, g, b)
    new_l = max(target_l, min(0.92, l if l > target_l else target_l))
    new_s = min(sat_cap, s)
    nr, ng, nb = _hsl_to_rgb(h, new_s, new_l)
    return _rgb_to_hex(nr, ng, nb)
