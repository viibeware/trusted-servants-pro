# SPDX-License-Identifier: AGPL-3.0-or-later
"""Catalog of dynamically-generated frontend backgrounds.

A "dynbg" (dynamic background) is a CSS-driven, optionally-animated
backdrop that any frontend surface (page, container block, hero,
section card, etc.) can opt into instead of a solid colour, gradient,
or uploaded image. Each preset:

  * renders as a `<div class="fe-dynbg fe-dynbg-<key>">` with a fixed
    set of inner spans the partial owns, so the consumer just stamps
    one tag and CSS does the rest;
  * relies on per-theme design tokens (`--fe-accent`, `--fe-color-bg`)
    so the same key produces a brand-coloured backdrop on every site
    without per-install tweaking;
  * has a dark-mode rule so the recipe stays legible when the visitor
    flips the theme toggle;
  * uses *only* CSS — no JS dependency. Animations are paused under
    `prefers-reduced-motion: reduce`.

Adding a new preset is two changes:

  1. Append an entry to ``CATALOG`` below.
  2. Add the matching ``.fe-dynbg-<key>`` rule (and dark-mode twin)
     to ``app/static/css/frontend.css``.

The picker UI (``_dynbg_picker.html`` macro) reads ``CATALOG`` on
each render, so a new preset shows up everywhere the picker is
embedded the moment the CSS is wired up.
"""


CATALOG = [
    {
        "key": "aurora-blobs",
        "name": "Aurora blobs",
        "description": (
            "Three brand-tinted blurred circles drifting on a soft "
            "tinted backdrop. Calm, premium feel. Best for hero / "
            "page-level backgrounds."
        ),
    },
    {
        "key": "mesh-gradient",
        "name": "Mesh gradient",
        "description": (
            "Static multi-stop mesh of brand colours layered with "
            "conic gradients. No motion — quiet but interesting."
        ),
    },
    {
        "key": "aurora-bands",
        "name": "Aurora bands",
        "description": (
            "Wide angled colour bands sweeping across the surface "
            "with a slow drift. Reads as soft northern lights."
        ),
    },
    {
        "key": "starfield",
        "name": "Starfield",
        "description": (
            "Dark backdrop with twinkling pinpoints. Great for "
            "moody section banners or footer regions."
        ),
    },
    {
        "key": "dotted-grid",
        "name": "Dotted grid",
        "description": (
            "Subtle dot pattern on a flat backdrop. Adds texture "
            "without competing with content."
        ),
    },
    {
        "key": "diagonal-lines",
        "name": "Diagonal lines",
        "description": (
            "Soft diagonal stripe pattern. Quiet structural texture "
            "for cards and section bands."
        ),
    },
    {
        "key": "noise-paper",
        "name": "Noise paper",
        "description": (
            "Hand-feel paper grain via SVG noise. Pairs well with "
            "serif typography on long-form pages."
        ),
    },
    {
        "key": "spotlight",
        "name": "Spotlight glow",
        "description": (
            "Two large radial glows — corner-anchored — fading into "
            "the page colour. Subtle, focuses the eye on content."
        ),
    },
]


VALID_KEYS = {entry["key"] for entry in CATALOG}


# ── Overlays ────────────────────────────────────────────────────
# Independent visual layer that paints ABOVE the base dynbg (and
# above content, with `pointer-events: none`) to add a tactile
# texture / mood pass over the whole surface. Inspired by the
# viibeware project's fixed-position fractal-noise grain — the
# subtle 3% noise overlay that gave that site its premium feel.
# Overlays compose with any base dynbg (or none — an admin can run
# a solid colour with just an overlay on top).
OVERLAYS = [
    {
        "key": "noise-grain",
        "name": "Noise grain",
        "description": (
            "Subtle SVG fractal-noise sandpaper texture across the "
            "whole surface. The viibeware-recipe overlay — sits at "
            "~3% opacity so content stays crisp."
        ),
    },
    {
        "key": "scanlines",
        "name": "Scanlines",
        "description": (
            "Faint 2px horizontal scanline pattern at ~1.5% alpha. "
            "CRT / film-still vibe; pairs well with bold heros."
        ),
    },
    {
        "key": "linen",
        "name": "Linen weave",
        "description": (
            "Crossed two-direction stripe pattern reading as a soft "
            "fabric weave. Adds material warmth without competing "
            "with photography or typography."
        ),
    },
    {
        "key": "vignette",
        "name": "Vignette",
        "description": (
            "Radial darken from the corners — focuses the eye on "
            "centred content. Strong on heros, subtle on cards."
        ),
    },
    {
        "key": "crosshatch",
        "name": "Crosshatch",
        "description": (
            "Two-direction diagonal lines forming an editorial "
            "crosshatch. Ink-on-paper feel for long-form pages."
        ),
    },
    {
        "key": "dot-weave",
        "name": "Dot weave",
        "description": (
            "Tiny dotted lattice with a soft falloff. Reads as "
            "halftone newsprint at a quiet 4% intensity."
        ),
    },
]


VALID_OVERLAY_KEYS = {entry["key"] for entry in OVERLAYS}


def by_key(key):
    """Return the catalog entry for ``key`` or None when unknown."""
    if not key:
        return None
    for entry in CATALOG:
        if entry["key"] == key:
            return entry
    return None


def overlay_by_key(key):
    """Return the overlay catalog entry for ``key`` or None."""
    if not key:
        return None
    for entry in OVERLAYS:
        if entry["key"] == key:
            return entry
    return None


def normalize(key):
    """Coerce a possibly-tampered request value to a known key or None.

    Any value not in ``VALID_KEYS`` collapses to None so the caller
    can render "no dynamic background" instead of crashing.
    """
    if not key:
        return None
    key = str(key).strip()
    return key if key in VALID_KEYS else None


def normalize_overlay(key):
    """Same gate as ``normalize`` but for the OVERLAYS catalog."""
    if not key:
        return None
    key = str(key).strip()
    return key if key in VALID_OVERLAY_KEYS else None


# Hex colour validation. Up to three custom colours travel alongside
# each dynbg via the shared persistence helpers. The colour gate is
# permissive (3-digit + 6-digit hex with optional alpha) but rejects
# anything that doesn't look like a colour so a tampered POST can't
# inject arbitrary CSS via the inline style stamp.
import re as _re

_HEX_COLOR_RE = _re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def normalize_color(value):
    """Return the value if it parses as a hex colour, else None."""
    if not value:
        return None
    v = str(value).strip()
    return v if _HEX_COLOR_RE.match(v) else None


def normalize_colors(raw):
    """Normalise an iterable / sequence of three colour values into a
    fixed-shape list of (hex|None) for the persistence layer.

    Always returns a 3-element list — None for any slot the admin
    didn't fill or that didn't parse as a colour. The callers then
    drop trailing Nones when persisting / stamping CSS so an empty
    palette costs nothing in storage or DOM weight.
    """
    if raw is None:
        raw = []
    if isinstance(raw, str):
        # Comma-separated form ("#aaa,#bbb,#ccc") — defensive against
        # callers that pre-joined the values.
        raw = [s for s in raw.split(",")]
    out = [None, None, None]
    for i, v in enumerate(raw[:3]):
        out[i] = normalize_color(v)
    return out


VALID_OVERLAY_SCOPES = {"all", "bg"}

# Subset of CATALOG keys whose CSS recipes include keyframe
# animations. Drives the "Disable animation" toggle in the modal —
# the picker only shows the toggle when the active preset is one of
# these, so admins never see a useless control on static presets.
ANIMATED_KEYS = {"aurora-blobs", "aurora-bands", "starfield"}

# Noise-grain admin-tunable ranges. baseFrequency on `<feTurbulence>`
# controls grain SIZE — lower values produce bigger particles, higher
# values produce finer ones. Intensity is the SVG-encoded rect alpha;
# tuned together with baseFrequency, the duo covers everything from
# heavy film grain (size 0.4, intensity 0.06) to barely-there sand
# (size 1.5, intensity 0.02). Defaults match the viibeware recipe.
NOISE_SIZE_DEFAULT = 0.9
NOISE_SIZE_MIN, NOISE_SIZE_MAX = 0.1, 2.0
NOISE_INTENSITY_DEFAULT = 0.03
NOISE_INTENSITY_MIN, NOISE_INTENSITY_MAX = 0.005, 0.5


def normalize_scope(value):
    """Coerce overlay scope to 'all' (above content — viibeware-style)
    or 'bg' (between base dynbg and content). Default is None which
    consumers treat as 'all'."""
    if not value:
        return None
    v = str(value).strip().lower()
    return v if v in VALID_OVERLAY_SCOPES else None


def normalize_float(value, lo, hi, default=None):
    """Clamp a string/number to [lo, hi] or fall back to default."""
    if value is None or value == "":
        return default
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, f))


def encode_config(overlay_key=None, colors=None, scope=None,
                  noise_size=None, noise_intensity=None,
                  randomize_colors=False, randomize_positions=False,
                  animate=True, randomize=None):
    """Return a JSON-serialisable dict shape for a surface's dynbg
    config column. Drops empty / default fields so a fresh install
    stores ``{}`` rather than a fat default record.

    The legacy ``randomize`` kwarg is accepted for back-compat; when
    True it implies both ``randomize_colors`` and
    ``randomize_positions``. The ``animate`` kwarg defaults to True
    (the preset's keyframe animations run); only an explicit opt-out
    persists, keeping the JSON minimal for the common case.
    """
    cleaned = {}
    ov = normalize_overlay(overlay_key)
    if ov:
        cleaned["overlay"] = ov
    sc = normalize_scope(scope)
    if sc and sc != "all":  # 'all' is the implicit default
        cleaned["overlay_scope"] = sc
    ns = normalize_float(noise_size, NOISE_SIZE_MIN, NOISE_SIZE_MAX, None)
    if ns is not None and abs(ns - NOISE_SIZE_DEFAULT) > 1e-6:
        cleaned["overlay_size"] = round(ns, 3)
    ni = normalize_float(noise_intensity, NOISE_INTENSITY_MIN,
                         NOISE_INTENSITY_MAX, None)
    if ni is not None and abs(ni - NOISE_INTENSITY_DEFAULT) > 1e-6:
        cleaned["overlay_intensity"] = round(ni, 4)
    if randomize:  # legacy single flag → expands to both
        randomize_colors = True
        randomize_positions = True
    if randomize_colors:
        cleaned["randomize_colors"] = True
    if randomize_positions:
        cleaned["randomize_positions"] = True
    # Opt-OUT semantics: only persist when the admin explicitly
    # disables animation. Animated presets default to running their
    # keyframe animations, so a fresh install with no `animate` key
    # behaves exactly as before.
    if animate is False:
        cleaned["animate"] = False
    norm = normalize_colors(colors)
    # Trim trailing None slots so ['#a', None, None] persists as ['#a'].
    while norm and norm[-1] is None:
        norm.pop()
    if norm:
        cleaned["colors"] = norm
    return cleaned


def decode_config(raw):
    """Parse a stored JSON config string back into a normalised config
    dict. Tolerant of None / blanks / malformed JSON — always returns
    a dict with every expected key so callers can `.get()` without
    extra guards. Keeps the legacy ``randomize`` boolean as an alias
    so old templates that read `.randomize` still get a sensible
    truthy value when either dimension is randomised."""
    import json as _json
    blank = {
        "overlay": None,
        "overlay_scope": None,
        "overlay_size": None,
        "overlay_intensity": None,
        "randomize_colors": False,
        "randomize_positions": False,
        "randomize": False,
        "animate": True,
        "colors": [],
    }
    if not raw:
        return blank
    try:
        data = _json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return blank
    if not isinstance(data, dict):
        return blank
    legacy = bool(data.get("randomize"))  # back-compat: implies both
    rc = bool(data.get("randomize_colors")) or legacy
    rp = bool(data.get("randomize_positions")) or legacy
    # Animation flag — opt-out semantics. An explicit `animate: false`
    # in the saved JSON means "freeze the preset's motion"; a missing
    # field defaults to True so existing configs keep animating.
    animate = data.get("animate")
    animate = False if animate is False else True
    return {
        "overlay": normalize_overlay(data.get("overlay")),
        "overlay_scope": normalize_scope(data.get("overlay_scope")),
        "overlay_size": normalize_float(data.get("overlay_size"),
                                         NOISE_SIZE_MIN, NOISE_SIZE_MAX, None),
        "overlay_intensity": normalize_float(data.get("overlay_intensity"),
                                              NOISE_INTENSITY_MIN, NOISE_INTENSITY_MAX, None),
        "randomize_colors": rc,
        "randomize_positions": rp,
        "randomize": rc or rp,  # legacy alias — true when either is on
        "animate": animate,
        "colors": [c for c in normalize_colors(data.get("colors") or []) if c],
    }


def colors_to_css_vars(colors):
    """Stamp up to three custom colours as ``--fe-dynbg-cN`` CSS
    custom properties for inline ``style`` use. Returns a string like
    ``--fe-dynbg-c1: #abc; --fe-dynbg-c2: #def;`` (no trailing
    semicolon trick — caller concatenates as needed) or empty string
    when the palette is empty.
    """
    parts = []
    for i, c in enumerate(colors or [], start=1):
        if c:
            parts.append(f"--fe-dynbg-c{i}: {c};")
    return " ".join(parts)


def random_colors(n=3):
    """Return a list of ``n`` random vibrant hex colours.

    Uses HSL with random hue + capped-medium saturation / lightness
    so the palette stays brand-friendly (no muddy browns or eye-
    searing neons). Each render generates a fresh palette so the
    same surface looks different every page load when the admin has
    `randomize` turned on.
    """
    import random as _random
    import colorsys as _colorsys
    out = []
    for _ in range(n):
        h = _random.random()
        s = 0.55 + _random.random() * 0.35  # 0.55–0.90
        l = 0.45 + _random.random() * 0.20  # 0.45–0.65
        r, g, b = _colorsys.hls_to_rgb(h, l, s)
        out.append("#{:02x}{:02x}{:02x}".format(
            int(r * 255), int(g * 255), int(b * 255)))
    return out


def resolve_colors(cfg):
    """Return the colours to stamp on a surface's dynbg-host. When
    ``cfg.randomize_colors`` is True the saved colours are ignored
    and a fresh random palette is generated for this render —
    matches the "randomize on every reload" behavior the hero's
    frosty mode already offers, but applies uniformly to every
    dynbg surface.

    Reads the colours flag in isolation: the user's ability to
    randomise positions while keeping the palette constant
    requires that this resolver doesn't fall back to a "legacy
    randomize" alias that conflates the two flags. The legacy
    ``randomize: true`` field is mapped into both new flags by
    ``decode_config`` upstream, so this resolver only needs to
    look at ``randomize_colors``.
    """
    if isinstance(cfg, str) or cfg is None:
        cfg = decode_config(cfg)
    if cfg.get("randomize_colors"):
        return random_colors(3)
    return cfg.get("colors", []) or []


def random_positions(dynbg_key):
    """Return a dict of CSS-variable strings → values that randomise
    the position-shaped properties of a single dynbg preset. Each
    value is server-rendered fresh on every request, so the same
    surface's blobs / mesh / bands / spotlights spawn at different
    coordinates each page load.

    Returns an empty dict for presets without meaningfully-randomis-
    able positions (dotted-grid, diagonal-lines, noise-paper) so
    the consumer can safely call this for any key.
    """
    import random as _random
    out = {}
    if dynbg_key == "aurora-blobs":
        # Each blob: (top|bottom, left|right, size). Randomise the
        # corner anchor + offset + size so the trio looks fresh.
        for slot in ("a", "b", "c"):
            top  = _random.randint(-30, 60)   # %, can go off-screen
            left = _random.randint(-30, 60)
            sz   = _random.randint(220, 460)  # px
            out[f"--fe-dynbg-blob-{slot}-top"]   = f"{top}%"
            out[f"--fe-dynbg-blob-{slot}-left"]  = f"{left}%"
            out[f"--fe-dynbg-blob-{slot}-bottom"] = "auto"
            out[f"--fe-dynbg-blob-{slot}-right"]  = "auto"
            out[f"--fe-dynbg-blob-{slot}-size"]  = f"{sz}px"
    elif dynbg_key == "mesh-gradient":
        # Conic-gradient origin + starting angle for each mesh layer.
        for slot, default_angle in (("a", 0), ("b", 180), ("c", 90)):
            x = _random.randint(15, 85)
            y = _random.randint(15, 85)
            ang = _random.randint(0, 360)
            out[f"--fe-dynbg-mesh-{slot}-x"] = f"{x}%"
            out[f"--fe-dynbg-mesh-{slot}-y"] = f"{y}%"
            out[f"--fe-dynbg-mesh-{slot}-angle"] = f"{ang}deg"
    elif dynbg_key == "aurora-bands":
        # Two bands; each gets a fresh sweep angle.
        for slot in ("a", "b"):
            ang = _random.randint(40, 160)
            out[f"--fe-dynbg-band-{slot}-angle"] = f"{ang}deg"
    elif dynbg_key == "spotlight":
        # Two corner-anchored spots; each gets a random corner +
        # size so the highlight pattern reads differently each load.
        for slot in ("a", "b"):
            top  = _random.choice(["-25%", "auto"])
            bot  = "auto" if top != "auto" else "-25%"
            left = _random.choice(["-15%", "auto"])
            right = "auto" if left != "auto" else "-15%"
            w = _random.randint(50, 90)
            h = _random.randint(60, 100)
            out[f"--fe-dynbg-spot-{slot}-top"]    = top
            out[f"--fe-dynbg-spot-{slot}-bottom"] = bot
            out[f"--fe-dynbg-spot-{slot}-left"]   = left
            out[f"--fe-dynbg-spot-{slot}-right"]  = right
            out[f"--fe-dynbg-spot-{slot}-w"] = f"{w}%"
            out[f"--fe-dynbg-spot-{slot}-h"] = f"{h}%"
    return out


def positions_to_css_vars(positions):
    """Format a dict of position vars into an inline-style string. Sister
    helper to ``colors_to_css_vars``. Returns empty string for an empty
    dict so consumers can safely concatenate."""
    if not positions:
        return ""
    return " ".join(f"{k}: {v};" for k, v in positions.items())


def resolve_positions_css(cfg, dynbg_key):
    """One-call helper for templates: returns the inline CSS-vars
    string for a dynbg's positional state. Empty string when
    randomize_positions is off OR the preset has nothing positional
    to randomise. Read from the host element's ``style="..."``.

    Reads the positions flag in isolation — same reasoning as
    ``resolve_colors``. The legacy single ``randomize: true`` field
    is mapped into both new flags by ``decode_config`` upstream, so
    this resolver only checks ``randomize_positions``.
    """
    if isinstance(cfg, str) or cfg is None:
        cfg = decode_config(cfg)
    if not cfg.get("randomize_positions"):
        return ""
    return positions_to_css_vars(random_positions(dynbg_key or ""))


def noise_grain_data_url(size=None, intensity=None):
    """Generate the noise-grain SVG as a data-URL with admin-chosen
    grain size + intensity baked in. baseFrequency on `feTurbulence`
    is the size knob (lower = bigger particles); the rect's opacity
    is the intensity knob.

    Returns the bare URL string suitable for inline
    ``style="background-image: url('...')"``. Caller adds the
    surrounding url() / quote chars as needed.
    """
    sz = normalize_float(size, NOISE_SIZE_MIN, NOISE_SIZE_MAX, NOISE_SIZE_DEFAULT)
    op = normalize_float(intensity, NOISE_INTENSITY_MIN,
                         NOISE_INTENSITY_MAX, NOISE_INTENSITY_DEFAULT)
    # All apostrophes inside the SVG are URL-encoded as %27 so they
    # don't conflict with the surrounding `url('...')` wrapper when
    # the data-URL is stamped as an inline `style="background-image:
    # url('...')"`. Without this, after HTML-decoding the apostrophes
    # inside e.g. `viewBox='0 0 256 256'` close the url() string
    # early and the browser drops the rest as invalid CSS — making
    # the noise grain silently vanish whenever a custom size or
    # intensity bakes a fresh URL.
    return (
        "data:image/svg+xml;utf8,"
        "%3Csvg viewBox=%270 0 256 256%27 xmlns=%27http://www.w3.org/2000/svg%27%3E"
        "%3Cfilter id=%27noise%27%3E"
        f"%3CfeTurbulence type=%27fractalNoise%27 baseFrequency=%27{sz}%27 "
        "numOctaves=%274%27 stitchTiles=%27stitch%27/%3E"
        "%3C/filter%3E"
        f"%3Crect width=%27100%25%27 height=%27100%25%27 filter=%27url(%23noise)%27 opacity=%27{op}%27/%3E"
        "%3C/svg%3E"
    )
