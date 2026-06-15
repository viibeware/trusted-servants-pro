# SPDX-License-Identifier: AGPL-3.0-or-later
"""SVG → PNG rasterization for raster fallbacks.

HTML email clients don't render SVG, so an uploaded SVG logo needs a
PNG twin for the branded notification emails. This wraps ``cairosvg``
(which renders via the libcairo runtime already present for WeasyPrint).
Every entry point is best-effort: a missing library or an un-parseable
SVG returns ``False`` rather than raising, so the upload it's triggered
from never fails because rasterization did.
"""


def available():
    """True when cairosvg + its libcairo runtime can be imported."""
    try:
        import cairosvg  # noqa: F401
        return True
    except Exception:
        return False


def svg_bytes_to_png(svg_bytes, png_path, output_width=640):
    """Rasterize SVG bytes to a PNG at ``png_path`` (transparent
    background preserved). ``output_width`` sets the raster width; the
    height follows the SVG's aspect ratio. Returns True on success,
    False on any failure. Never raises."""
    try:
        import cairosvg
    except Exception:
        return False
    try:
        cairosvg.svg2png(bytestring=svg_bytes, write_to=png_path,
                         output_width=output_width)
        return True
    except Exception:
        return False


def svg_file_to_png(svg_path, png_path, output_width=640):
    """Same as :func:`svg_bytes_to_png` but reads the SVG from a path."""
    try:
        with open(svg_path, "rb") as fh:
            data = fh.read()
    except OSError:
        return False
    return svg_bytes_to_png(data, png_path, output_width=output_width)
