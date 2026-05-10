# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lazy server-side thumbnail generation for uploaded images.

Used to keep admin and public list pages fast — instead of having every
row load the full-size featured image (often 1–4 MB each), the route
serving featured images takes a ``?thumb=<size>`` query param that
returns a fitted-into-<size>x<size> thumbnail. The first request for a
size generates the thumbnail file and writes it next to the source in
``UPLOAD_FOLDER``; subsequent requests just `send_from_directory` the
cached file.

Filename convention: a source uploaded as ``ab12cd34.jpg`` gets a
240px thumb at ``ab12cd34_thumb_240.jpg``. The ``_thumb_<N>`` suffix
makes thumbnails easy to identify + clean up when the source image is
retired (see ``thumbnails.cleanup_for(filename)``).

Animated GIFs and SVGs (vector) are returned as the source — Pillow
handles them poorly for our use case, and they're already small
enough.
"""
import os
import threading

from flask import current_app


# Sizes the public + admin templates may request. Anything not in this
# allowlist falls back to the source image — keeps the on-disk cache
# from ballooning when a malicious / sloppy template requests
# arbitrary sizes.
ALLOWED_SIZES = (120, 240, 400, 720, 1080)

# Pillow's `thumbnail()` is not thread-safe across the same source
# file. A boot-wide lock is plenty since thumbnail generation is rare
# (one-off per image-size combo).
_LOCK = threading.Lock()


def thumb_filename_for(filename, size):
    """Compute the on-disk thumb filename for a source + size. Pure —
    doesn't touch the filesystem. JPEG / WebP / PNG keep their
    extension; everything else gets `.jpg` since we'll re-encode."""
    if not filename or size not in ALLOWED_SIZES:
        return None
    base, ext = os.path.splitext(filename)
    ext_lower = ext.lower()
    if ext_lower in (".jpg", ".jpeg", ".png", ".webp"):
        out_ext = ext_lower
    else:
        out_ext = ".jpg"
    return f"{base}_thumb_{size}{out_ext}"


def ensure_thumb(filename, size, *, upload_dir=None):
    """Lazy-generate (if missing) and return the thumb filename. On
    failure (Pillow can't open, file missing, etc.) returns None so
    the caller can fall back to the source image."""
    if not filename or size not in ALLOWED_SIZES:
        return None
    upload_dir = upload_dir or current_app.config["UPLOAD_FOLDER"]
    thumb_name = thumb_filename_for(filename, size)
    if not thumb_name:
        return None
    thumb_path = os.path.join(upload_dir, thumb_name)
    if os.path.isfile(thumb_path):
        return thumb_name
    src_path = os.path.join(upload_dir, filename)
    if not os.path.isfile(src_path):
        return None
    # SVGs / GIFs / unknown formats: skip — let the caller fall back
    # to the source.
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".svg", ".gif"):
        return None
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    with _LOCK:
        # Another worker may have just generated it.
        if os.path.isfile(thumb_path):
            return thumb_name
        try:
            with Image.open(src_path) as im:
                # Honor EXIF rotation so portrait photos don't render
                # sideways in the resized version.
                im = ImageOps.exif_transpose(im)
                im.thumbnail((size, size), Image.LANCZOS)
                # JPEG can't carry an alpha channel; flatten over white
                # rather than crash.
                save_kwargs = {"optimize": True}
                out_ext = os.path.splitext(thumb_name)[1].lower()
                if out_ext in (".jpg", ".jpeg"):
                    if im.mode in ("RGBA", "LA", "P"):
                        from PIL import Image as _Image
                        bg = _Image.new("RGB", im.size, (255, 255, 255))
                        if im.mode == "P":
                            im = im.convert("RGBA")
                        bg.paste(im, mask=im.split()[-1] if im.mode in ("RGBA", "LA") else None)
                        im = bg
                    elif im.mode != "RGB":
                        im = im.convert("RGB")
                    save_kwargs["quality"] = 82
                    save_kwargs["progressive"] = True
                elif out_ext == ".png":
                    save_kwargs["compress_level"] = 6
                elif out_ext == ".webp":
                    save_kwargs["quality"] = 82
                im.save(thumb_path, **save_kwargs)
            return thumb_name
        except Exception:  # noqa: BLE001 — thumb is best-effort
            # Half-written thumb files would defeat the cache check on
            # the next request, so clean up.
            try:
                if os.path.isfile(thumb_path):
                    os.unlink(thumb_path)
            except OSError:
                pass
            return None


def cleanup_for(filename, *, upload_dir=None):
    """Delete every cached thumb for a given source filename. Called
    from the upload-cleanup helpers when the source image is replaced
    or the row referencing it is deleted, so stale thumbs don't pile
    up in the uploads folder."""
    if not filename:
        return
    upload_dir = upload_dir or current_app.config["UPLOAD_FOLDER"]
    for size in ALLOWED_SIZES:
        thumb_name = thumb_filename_for(filename, size)
        if not thumb_name:
            continue
        thumb_path = os.path.join(upload_dir, thumb_name)
        try:
            if os.path.isfile(thumb_path):
                os.unlink(thumb_path)
        except OSError:
            pass
