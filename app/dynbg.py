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
]


VALID_KEYS = {entry["key"] for entry in CATALOG}


# ── Per-preset capability spec ──────────────────────────────────
# Drives which Options-tab controls the picker modal shows for the
# active background ("don't show settings that won't apply"), and
# declares each preset's tunable knobs. The modal reads this via the
# ``dynbg_preset_caps`` Jinja global (stamped as JSON on the modal),
# so adding a knob here surfaces it in the UI with no template edit.
#
#   colors              — number of custom-colour slots that matter
#                         (0 hides the colour fieldset entirely).
#   color_labels        — optional per-slot labels. When present they
#                         replace the generic "Colour 1/2/3" headings,
#                         so e.g. the pattern presets read "Dots" /
#                         "Background" instead. The renderer maps slot
#                         N → --fe-dynbg-cN regardless of label.
#   randomize_positions — show the "randomize positions" toggle.
#   randomize_default   — when an admin first PICKS this preset, default
#                         the randomize-colours toggle on. False for the
#                         pattern presets (dots/lines), whose whole point
#                         is a deliberate fg/bg pair the admin sets.
#   animate             — show the "freeze movement" toggle (and the
#                         preset's CSS actually animates).
#   knobs               — ordered list of numeric sliders unique to
#                         this preset. Each: key (stored under
#                         cfg['knobs'][key] + stamped as the css_var),
#                         label, min/max/step, default, unit, and the
#                         CSS custom property it feeds.
PRESET_CAPS = {
    "aurora-blobs": {
        "colors": 3, "randomize_positions": True, "randomize_default": True,
        "animate": True, "knobs": [],
    },
    "mesh-gradient": {
        "colors": 3, "randomize_positions": True, "randomize_default": True,
        "animate": False, "knobs": [],
    },
    "aurora-bands": {
        "colors": 2, "randomize_positions": True, "randomize_default": True,
        "animate": True, "knobs": [],
    },
    "dotted-grid": {
        "colors": 2, "color_labels": ["Dots", "Background"],
        "randomize_positions": False, "randomize_default": False,
        "animate": False,
        "knobs": [
            {"key": "dot_size", "label": "Dot size", "min": 1, "max": 5,
             "step": 0.5, "default": 1, "unit": "px", "css_var": "--fe-dynbg-dot-size"},
            {"key": "dot_gap", "label": "Spacing", "min": 8, "max": 48,
             "step": 2, "default": 18, "unit": "px", "css_var": "--fe-dynbg-dot-gap"},
            {"key": "dot_angle", "label": "Rotation", "min": 0, "max": 360,
             "step": 5, "default": 0, "unit": "deg", "css_var": "--fe-dynbg-dot-angle"},
            {"key": "dot_opacity", "label": "Opacity", "min": 5, "max": 100,
             "step": 5, "default": 50, "unit": "%", "css_var": "--fe-dynbg-dot-opacity"},
        ],
    },
    "diagonal-lines": {
        "colors": 2, "color_labels": ["Lines", "Background"],
        "randomize_positions": False, "randomize_default": False,
        "animate": False,
        "knobs": [
            {"key": "line_angle", "label": "Angle", "min": 0, "max": 180,
             "step": 5, "default": 135, "unit": "deg", "css_var": "--fe-dynbg-line-angle"},
            {"key": "line_gap", "label": "Spacing", "min": 6, "max": 40,
             "step": 2, "default": 14, "unit": "px", "css_var": "--fe-dynbg-line-gap"},
            {"key": "line_opacity", "label": "Opacity", "min": 3, "max": 100,
             "step": 1, "default": 7, "unit": "%", "css_var": "--fe-dynbg-line-opacity"},
            {"key": "line_thickness", "label": "Thickness", "min": 1, "max": 6,
             "step": 0.5, "default": 1, "unit": "px", "css_var": "--fe-dynbg-line-thickness"},
        ],
    },
}

# Flattened lookup: {preset_key: {knob_key: spec}} for O(1) validation.
KNOB_SPECS = {pk: {k["key"]: k for k in caps["knobs"]}
              for pk, caps in PRESET_CAPS.items()}


def preset_caps(key):
    """Return the capability dict for a preset key, or a safe empty
    shape (no colours, no knobs) for unknown / blank keys so callers
    can read fields without guards."""
    return PRESET_CAPS.get(key, {"colors": 0, "randomize_positions": False,
                                  "animate": False, "knobs": []})


def normalize_knobs(preset_key, raw):
    """Validate a raw {knob_key: value} mapping against ``preset_key``'s
    spec. Drops unknown keys and any value equal to the knob's default
    (so a vanilla config stores nothing). Each value is clamped to the
    knob's [min, max]. Returns a dict (possibly empty)."""
    specs = KNOB_SPECS.get(preset_key) or {}
    if not specs or not isinstance(raw, dict):
        return {}
    out = {}
    for k, spec in specs.items():
        if k not in raw:
            continue
        v = normalize_float(raw.get(k), spec["min"], spec["max"], None)
        if v is None:
            continue
        # Drop values that round-trip to the default (keep JSON tiny).
        if abs(v - spec["default"]) < 1e-9:
            continue
        # Integer-valued knobs (step is a whole number) store as int.
        out[k] = int(round(v)) if float(spec["step"]).is_integer() and v == int(v) else round(v, 3)
    return out


def knobs_to_css_vars(preset_key, knobs):
    """Stamp a preset's knob values as their CSS custom properties for
    inline ``style`` use, appending the unit. Returns '' when empty.
    Only emits vars for knobs the preset actually declares."""
    specs = KNOB_SPECS.get(preset_key) or {}
    if not specs or not knobs:
        return ""
    def _num(v):
        # Render whole numbers without a trailing `.0` (3.0 → "3") so
        # the stamped CSS reads cleanly; keep the fraction otherwise.
        f = float(v)
        return str(int(f)) if f == int(f) else str(round(f, 3))
    parts = []
    for k, spec in specs.items():
        if k not in knobs:
            continue
        unit = spec.get("unit", "")
        val = knobs[k]
        if unit == "deg":
            parts.append(f"{spec['css_var']}: {_num(val)}deg;")
        elif unit == "px":
            parts.append(f"{spec['css_var']}: {_num(val)}px;")
        elif unit == "%":
            # Stamp as a 0-1 fraction so recipes can use it directly as
            # an opacity / alpha without a calc() divide.
            parts.append(f"{spec['css_var']}: {round(float(val) / 100.0, 4)};")
        else:
            parts.append(f"{spec['css_var']}: {_num(val)};")
    return " ".join(parts)


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
ANIMATED_KEYS = {"aurora-blobs", "aurora-bands"}

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

# Persisted overlay size/intensity clamp — a UNION range wide enough to
# hold both the noise-grain ranges above AND the pattern-overlay ranges
# below, so a single pair of stored fields (overlay_size /
# overlay_intensity) round-trips for any overlay. The modal sets the
# per-overlay slider bounds from OVERLAY_KNOBS; decode only needs to
# not reject a valid value.
OVERLAY_SIZE_MIN, OVERLAY_SIZE_MAX = 0.1, 3.0
OVERLAY_INTENSITY_MIN, OVERLAY_INTENSITY_MAX = 0.0, 1.0

# Per-overlay Size + Intensity knob specs. EVERY overlay exposes both
# sliders now (the admin asked for size+intensity on all textures), but
# the meaning differs by overlay family:
#   • noise-grain — size = feTurbulence baseFrequency (lower = bigger
#     particles), intensity = the SVG rect's alpha. Baked into a data-
#     URL at render (the SVG can't read CSS vars).
#   • every other (pattern) overlay — size = a pattern-scale multiplier
#     stamped as `--fe-dynbg-ov-scale` (×1 = the recipe's hand-tuned
#     dimensions), intensity = layer opacity stamped as
#     `--fe-dynbg-ov-opacity`. Defaults of 1.0/1.0 reproduce the
#     original look so existing saves render unchanged.
OVERLAY_KNOBS = {
    "noise-grain": {
        "size": {"min": NOISE_SIZE_MIN, "max": NOISE_SIZE_MAX, "step": 0.05,
                 "default": NOISE_SIZE_DEFAULT, "label": "Grain size",
                 "lo": "coarse", "hi": "fine"},
        "intensity": {"min": NOISE_INTENSITY_MIN, "max": NOISE_INTENSITY_MAX,
                      "step": 0.005, "default": NOISE_INTENSITY_DEFAULT,
                      "label": "Intensity", "lo": "whisper", "hi": "heavy"},
    },
}
# Pattern overlays all share the same scale + opacity knob shape.
for _ov in ("scanlines", "linen", "vignette", "crosshatch", "dot-weave"):
    OVERLAY_KNOBS[_ov] = {
        "size": {"min": 0.25, "max": 3.0, "step": 0.05, "default": 1.0,
                 "label": "Scale", "lo": "tight", "hi": "wide"},
        "intensity": {"min": 0.0, "max": 1.0, "step": 0.05, "default": 1.0,
                      "label": "Intensity", "lo": "faint", "hi": "bold"},
    }


def overlay_knobs(key):
    """Return the Size/Intensity knob spec dict for an overlay key, or
    None for unknown/blank. Drives the modal's per-overlay sliders."""
    return OVERLAY_KNOBS.get(key)


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


def normalize_pastel_strength(v, default=0):
    """Coerce a stored ``pastel_light`` value into an int 0-100 strength.

    Legacy storage was a boolean (``True`` = pastelise, ``False`` = off);
    new storage is the 0-100 strength the admin set via the slider.
    Both forms decode here so existing rows keep behaving the same:

        True  → 100   (full pastel, matches legacy behaviour)
        False → 0     (off)
        '1'   → 1     (purely numeric — strength of 1%, NOT legacy on)
        '100' → 100
        out-of-range → clamped
        garbage → ``default``
    """
    if v is True:
        return 100
    if v is False or v is None or v == "":
        return default
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return default
    return max(0, min(100, n))


def encode_config(overlay_key=None, colors=None, scope=None,
                  noise_size=None, noise_intensity=None,
                  randomize_colors=False, randomize_positions=False,
                  animate=True, randomize=None, pastel_light=0,
                  knobs=None, preset_key=None):
    """Return a JSON-serialisable dict shape for a surface's dynbg
    config column. Drops empty / default fields so a fresh install
    stores ``{}`` rather than a fat default record.

    The legacy ``randomize`` kwarg is accepted for back-compat; when
    True it implies both ``randomize_colors`` and
    ``randomize_positions``. The ``animate`` kwarg defaults to True
    (the preset's keyframe animations run); only an explicit opt-out
    persists, keeping the JSON minimal for the common case.

    ``knobs`` is a {knob_key: value} mapping of the active preset's
    per-preset sliders (dot size/gap, line angle/thickness, …);
    ``preset_key`` scopes its validation. ``noise_size`` /
    ``noise_intensity`` carry the active overlay's Size/Intensity and
    are dropped only when equal to THAT overlay's default (so pattern
    overlays whose default differs from noise-grain's persist
    correctly).
    """
    cleaned = {}
    ov = normalize_overlay(overlay_key)
    if ov:
        cleaned["overlay"] = ov
    sc = normalize_scope(scope)
    if sc and sc != "all":  # 'all' is the implicit default
        cleaned["overlay_scope"] = sc
    # Overlay Size / Intensity. Default-drop against the active
    # overlay's own defaults (noise-grain vs pattern overlays differ).
    _ovk = OVERLAY_KNOBS.get(ov) if ov else None
    _sz_def = _ovk["size"]["default"] if _ovk else NOISE_SIZE_DEFAULT
    _int_def = _ovk["intensity"]["default"] if _ovk else NOISE_INTENSITY_DEFAULT
    ns = normalize_float(noise_size, OVERLAY_SIZE_MIN, OVERLAY_SIZE_MAX, None)
    if ns is not None and abs(ns - _sz_def) > 1e-6:
        cleaned["overlay_size"] = round(ns, 3)
    ni = normalize_float(noise_intensity, OVERLAY_INTENSITY_MIN,
                         OVERLAY_INTENSITY_MAX, None)
    if ni is not None and abs(ni - _int_def) > 1e-6:
        cleaned["overlay_intensity"] = round(ni, 4)
    if randomize:  # legacy single flag → expands to both
        randomize_colors = True
        randomize_positions = True
    if randomize_colors:
        cleaned["randomize_colors"] = True
    if randomize_positions:
        cleaned["randomize_positions"] = True
    # Per-preset knobs (validated + default-dropped against the spec).
    nk = normalize_knobs(preset_key, knobs)
    if nk:
        cleaned["knobs"] = nk
    # Opt-in: only persist a non-zero pastel strength. Stored as an int
    # 0-100 (the slider's value). Legacy True/False is mapped through
    # normalize_pastel_strength so older callers stay correct without
    # any migration: True → 100, False → 0 (omitted).
    ps = normalize_pastel_strength(pastel_light, default=0)
    if ps > 0:
        cleaned["pastel_light"] = ps
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
        "pastel_light": 0,
        "knobs": {},
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
                                         OVERLAY_SIZE_MIN, OVERLAY_SIZE_MAX, None),
        "overlay_intensity": normalize_float(data.get("overlay_intensity"),
                                              OVERLAY_INTENSITY_MIN, OVERLAY_INTENSITY_MAX, None),
        "randomize_colors": rc,
        "randomize_positions": rp,
        "randomize": rc or rp,  # legacy alias — true when either is on
        "animate": animate,
        # Strength int 0-100. Back-compat: a legacy ``True`` boolean
        # still decodes as 100 (full pastel) via normalize_pastel_strength.
        "pastel_light": normalize_pastel_strength(data.get("pastel_light"), 0),
        # Per-preset knob values. Left un-scoped here (we don't know the
        # preset key at decode time) — the raw dict is passed through and
        # consumers scope it via knobs_to_css_vars(preset_key, knobs),
        # which only emits vars for knobs that preset declares.
        "knobs": (data.get("knobs") if isinstance(data.get("knobs"), dict) else {}),
        "colors": [c for c in normalize_colors(data.get("colors") or []) if c],
    }


_PASTEL_HEX_RE = __import__("re").compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def pastelize(hex_str, strength=100):
    """Return a pastel-soft variant of an arbitrary hex colour, with the
    admin-controlled strength dialed in.

    ``strength`` is an int 0-100. At 100 the colour lands fully in the
    pastel band (low saturation, raised lightness); at 0 the function
    returns the input unchanged (no pastelisation). Intermediate values
    linearly interpolate between the source HSL values and the full-
    pastel target, so admins can dial the paleness from "vivid" through
    "softened" to "cream wash" without having to swap the toggle.

    Returns ``None`` on invalid input so callers can short-circuit
    without crashing the render. Output is ``#rrggbb`` (no alpha)
    because the inline CSS-vars are blended downstream.
    """
    import colorsys
    if not isinstance(hex_str, str) or not _PASTEL_HEX_RE.match(hex_str):
        return None
    s = max(0, min(100, int(strength) if strength is not None else 0))
    if s == 0:
        # Strength 0 short-circuits to the source colour so the consumer
        # can still emit the var without a special case.
        return hex_str if hex_str.startswith("#") else "#" + hex_str
    t = s / 100.0
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 8:
        h = h[:6]
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
    except ValueError:
        return None
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    # Full-strength target — the legacy pastel band (saturation clipped
    # to 0.339, lightness clamped 0.69-0.75) pushed an additional 50%
    # of the way toward pure white. The earlier implementation read as
    # a still-slightly-punchy pastel; this revision lands at strength=
    # 100 in true cream / blush / mint territory. At lower strengths
    # we lerp from the source (sat, light) into this paler target.
    legacy_target_s = min(sat, 0.339)
    legacy_target_l = max(0.69, min(0.75, light * 0.24 + 0.53))
    target_s = legacy_target_s * 0.5
    target_l = legacy_target_l + (1.0 - legacy_target_l) * 0.5
    new_s = sat * (1 - t) + target_s * t
    new_l = light * (1 - t) + target_l * t
    nr, ng, nb = colorsys.hls_to_rgb(hue, new_l, new_s)
    return "#{:02x}{:02x}{:02x}".format(int(nr * 255), int(ng * 255), int(nb * 255))


def colors_to_css_vars(colors, cfg=None):
    """Stamp up to three custom colours as ``--fe-dynbg-cN`` CSS
    custom properties for inline ``style`` use. Returns a string like
    ``--fe-dynbg-c1: #abc; --fe-dynbg-c2: #def;`` (no trailing
    semicolon trick — caller concatenates as needed) or empty string
    when the palette is empty.

    When ``cfg`` (the decoded dynbg config dict) is passed AND
    ``cfg.pastel_light`` is True, emits a companion
    ``--fe-dynbg-cN-light`` for each colour carrying the pastelised
    variant. A CSS rule under ``html:not([data-theme="dark"])`` swaps
    `--fe-dynbg-cN` to the light variant at render time, so the
    same palette pastelises only when the visitor is in light mode.

    Special case for ``pastel_light=True`` with no admin-picked
    colours: each preset's CSS falls through to its own
    brand-derived fallback when ``--fe-dynbg-cN`` isn't set, and
    those hardcoded fallbacks ignore the pastel flag entirely. To
    keep "Use pastels in light mode" meaningful without forcing
    the admin to also pick colours, stamp three hardcoded pale
    defaults onto ``--fe-dynbg-cN-light`` so the light-mode swap
    still has something to swap to. Dark mode is unaffected — the
    canonical `--fe-dynbg-cN` is never set, so the preset's brand
    fallback continues to drive the dark surface.
    """
    parts = []
    pastel_strength = normalize_pastel_strength(
        cfg.get("pastel_light") if cfg else None, 0)
    pastel_light = pastel_strength > 0
    cleaned = [c for c in (colors or []) if c]
    for i, c in enumerate(cleaned, start=1):
        parts.append(f"--fe-dynbg-c{i}: {c};")
        if pastel_light:
            p = pastelize(c, strength=pastel_strength)
            if p:
                parts.append(f"--fe-dynbg-c{i}-light: {p};")
    if pastel_light and not cleaned:
        # Hardcoded neutral pastels — soft cool / warm / mint
        # tints that read as a calm palette in light mode without
        # locking the surface to any particular brand colour. The
        # admin's own colour picks (if they're added later) take
        # precedence via the loop above.
        for i, default_pastel in enumerate(("#ecf0f6", "#f4ecef", "#eef4ee"), start=1):
            parts.append(f"--fe-dynbg-c{i}-light: {default_pastel};")
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


def thumb_style(dynbg_key):
    """Return an inline-style string that seeds a preset thumbnail with a
    FRESH random palette + random positions, so every catalog thumbnail
    (and the modal's live preview when it falls back to a preset's own
    look) reads as a distinct, lively sample rather than the identical
    brand-default render.

    Combines a 3-colour ``random_colors`` palette (stamped as
    ``--fe-dynbg-cN``) with ``random_positions(key)`` for the presets
    that have movable parts (blobs / mesh / bands). Static presets
    (dotted-grid, diagonal-lines) still get a random palette so their
    tint differs tile-to-tile. Returns '' for an unknown / blank key.

    Server-rendered, so each page load reshuffles the picker — matching
    the "randomly selected colors and positions" behaviour the admin
    asked for without any client-side colour math.
    """
    if not dynbg_key or dynbg_key not in VALID_KEYS:
        return ""
    parts = []
    for i, c in enumerate(random_colors(3), start=1):
        parts.append(f"--fe-dynbg-c{i}: {c};")
    pos = positions_to_css_vars(random_positions(dynbg_key))
    style = " ".join(parts)
    if pos:
        style = (style + " " + pos).strip()
    return style


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
    surface's blobs / mesh / bands spawn at different coordinates
    each page load.

    Returns an empty dict for presets without meaningfully-randomis-
    able positions (dotted-grid, diagonal-lines) so the consumer can
    safely call this for any key.
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
    sz = normalize_float(size, OVERLAY_SIZE_MIN, OVERLAY_SIZE_MAX, NOISE_SIZE_DEFAULT)
    op = normalize_float(intensity, OVERLAY_INTENSITY_MIN,
                         OVERLAY_INTENSITY_MAX, NOISE_INTENSITY_DEFAULT)
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
