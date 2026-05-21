# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frontend asset caching — headers + cache-busting, centralized.

Two problems this module solves:

1. **Returning visitors re-downloaded every image.** The app's
   ``_security_headers`` after-request hook forces ``Cache-Control:
   no-store`` on everything that isn't ``/static/`` or ``/pub/`` — which
   includes nearly every image route (``/story-image``, ``/blog-image``,
   ``/site-branding/*`` …). So browsers fetched them fresh on every page
   load. :func:`apply_cache_headers` instead stamps image responses with a
   long-lived ``public, max-age=...`` (optionally ``immutable``) so they
   serve straight from the browser / Cloudflare cache.

2. **Long caching normally means stale images after an edit.** We avoid
   that with a cache-bust token (``?v=<n>``) appended to every image URL
   via Flask's ``url_defaults`` hook (:func:`inject_bust`). The token is
   ``SiteSetting.media_cache_version``; it advances automatically whenever
   an image is uploaded/replaced (:func:`note_image_change`, wired into
   ``_save_upload``) and on demand from the "Clear cache" button
   (:func:`clear_cache`). A new token = a new URL = an immediate refetch,
   no waiting for the cache to expire.

   ``/static`` CSS/JS/font assets are busted by the app build-id instead
   (``version.__build_id__``, a content hash of the source tree), so a
   redeploy invalidates them without any admin action.

Everything is gated by ``SiteSetting.media_cache_enabled`` so the whole
behaviour is one toggle in Web Frontend → Caching. The policy is read
through a short-TTL process cache so the per-response / per-``url_for``
lookups don't hammer SQLite.
"""
import os
import re
import time

from flask import current_app, request, g, has_request_context

from .models import db, SiteSetting


# Endpoints that serve a single cacheable asset file keyed by a row id /
# singleton (NOT by the stored filename — those are self-busting). These
# get the media cache-bust token appended to their URLs and the configured
# image cache policy applied. Keep in sync if new image routes are added.
IMAGE_ENDPOINTS = frozenset({
    "public.public_page_bg",
    "public.public_page_og_image",
    "public.site_footer_logo",
    "public.public_custom_icon",
    "public.frontend_404_image",
    "public.site_frontend_logo",
    "public.site_frontend_brand_logo",
    "public.site_og_image",
    "public.site_frontend_og_image",
    "public.site_frontend_favicon",
    "public.site_apple_touch_icon",
    "public.site_frontend_apple_touch_icon",
    "public.post_featured_image",
    "public.post_gallery_image",
    "public.story_featured_image",
    "public.public_meeting_logo",
    "public.blog_post_featured_image",
    "main.meeting_logo",
    "main.reading_thumbnail",
})

# Asset endpoints whose URL already embeds a unique (UUID) stored
# filename, so they're self-busting — a replacement is a new URL. We still
# want to cache them aggressively (currently they get no-store), but they
# must NOT carry the image version token (which would needlessly refetch
# fonts every time any image changes).
FILEHASH_ASSET_ENDPOINTS = frozenset({
    "public.site_custom_font_asset",
})

# Extensions we treat as images for the purpose of auto-bumping the token
# on upload. Anything else (PDFs, docs, scripts) flows through the same
# upload helper but shouldn't churn the image cache.
IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp",
    ".ico", ".avif", ".apng", ".tif", ".tiff",
})

# Generated thumbnails on disk follow `<base>_thumb_<size>.<ext>` (see
# app/thumbnails.py). This matches them for the server-side thumb cache
# stats / clear actions.
_THUMB_RE = re.compile(r"_thumb_\d+(?:\.[^.]+)?$")

_DEFAULT_POLICY = {
    "enabled": False,
    "max_age": 604800,
    "immutable": True,
    "static_enabled": False,
    "static_max_age": 2592000,
    "version": 0,
}

# Process-local policy cache. Reading SiteSetting on every image/static
# response and every url_for would be wasteful; refresh at most every
# _POLICY_TTL seconds. Cross-worker staleness is bounded by the same TTL.
_POLICY_TTL = 3.0
_policy_cache = {"data": None, "ts": 0.0}


def _load_policy():
    """Return the current caching policy dict, cached for a few seconds.

    Falls back to a fully-disabled policy on any error (DB not migrated
    yet, transient failure) so we never serve aggressively-cached assets
    we can't subsequently bust."""
    now = time.monotonic()
    cached = _policy_cache["data"]
    if cached is not None and (now - _policy_cache["ts"]) < _POLICY_TTL:
        return cached
    data = dict(_DEFAULT_POLICY)
    try:
        s = SiteSetting.query.first()
        if s is not None:
            data = {
                "enabled": bool(s.media_cache_enabled),
                "max_age": int(s.media_cache_max_age or 0),
                "immutable": bool(s.media_cache_immutable),
                "static_enabled": bool(s.media_cache_static_assets),
                "static_max_age": int(s.media_cache_static_max_age or 0),
                "version": int(s.media_cache_version or 0),
            }
    except Exception:
        data = dict(_DEFAULT_POLICY)
    _policy_cache["data"] = data
    _policy_cache["ts"] = now
    return data


def invalidate():
    """Drop the cached policy so the next read re-queries SiteSetting.
    Called after a settings save / cache clear so the new token / toggle
    takes effect immediately in this worker."""
    _policy_cache["data"] = None
    _policy_cache["ts"] = 0.0


def _live_version():
    """The committed media cache version, read live and cached per-request
    in ``g`` (one cheap indexed query per page render). Used for the URL
    bust token so an upload/clear is reflected immediately, without waiting
    out the policy cache TTL. Falls back to the TTL-cached policy value off
    the request path."""
    if has_request_context():
        cached = getattr(g, "_imgcache_version", None)
        if cached is not None:
            return cached
    v = None
    try:
        row = (SiteSetting.query
               .with_entities(SiteSetting.media_cache_version).first())
        if row is not None and row[0] is not None:
            v = int(row[0])
    except Exception:
        v = None
    if v is None:
        v = _load_policy()["version"]
    if has_request_context():
        g._imgcache_version = v
    return v


def static_token():
    """Cache-bust token for /static assets — the app build-id (a content
    hash of the source tree), so any redeploy that ships new CSS/JS busts
    them automatically. Truncated to keep URLs short."""
    try:
        from .version import __build_id__
        return (__build_id__ or "0")[:12]
    except Exception:
        return "0"


def inject_bust(endpoint, values):
    """``url_defaults`` hook: append ``?v=<token>`` to asset URLs so a
    content change produces a new URL. Image endpoints use the media
    version; the static endpoint uses the build-id. No-op (and never
    raises) when caching is off or anything goes wrong."""
    try:
        if "v" in values:
            return
        if endpoint in IMAGE_ENDPOINTS:
            if _load_policy()["enabled"]:
                values["v"] = str(_live_version())
        elif endpoint == "static":
            pol = _load_policy()
            if pol["static_enabled"]:
                values["v"] = static_token()
    except Exception:
        pass


def apply_cache_headers(response):
    """Stamp Cache-Control on image / static asset responses per policy.

    Returns ``True`` when this response is an asset we've taken ownership
    of (so the caller's generic ``no-store`` rule should skip it), else
    ``False``."""
    endpoint = request.endpoint or ""
    is_static = endpoint == "static"
    is_listed = endpoint in IMAGE_ENDPOINTS
    is_filehash = endpoint in FILEHASH_ASSET_ENDPOINTS
    is_image = is_listed or (response.mimetype or "").startswith("image/")
    if not (is_static or is_image or is_filehash):
        return False

    pol = _load_policy()
    # 200/206 (full/partial file) and 304 (conditional hit) are the only
    # statuses worth a positive cache directive; errors fall through.
    cacheable = response.status_code in (200, 206, 304)

    if is_static:
        if pol["static_enabled"] and cacheable:
            response.headers["Cache-Control"] = (
                f"public, max-age={pol['static_max_age']}, immutable")
            response.headers.pop("Pragma", None)
            response.headers.pop("Expires", None)
        # When static caching is off we leave Flask's default handling in
        # place (ETag/conditional) rather than forcing no-store — static
        # assets are inherently safe to revalidate.
        return True

    # Image / self-busting file asset, gated by the master image toggle.
    if pol["enabled"] and cacheable:
        # File-hash assets and our listed (token-bearing) image endpoints
        # are both safe to mark immutable — the URL changes on any content
        # change. Bare image/* responses (no token) get a plain max-age.
        max_age = pol["static_max_age"] if is_filehash else pol["max_age"]
        cc = f"public, max-age={max_age}"
        if pol["immutable"] and (is_listed or is_filehash):
            cc += ", immutable"
        response.headers["Cache-Control"] = cc
        response.headers.pop("Pragma", None)
        response.headers.pop("Expires", None)
    else:
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return True


def is_image_filename(name):
    """True if ``name`` looks like an image we should bust the cache for."""
    if not name:
        return False
    return os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS


def note_image_change():
    """Advance the bust token after an image upload/replace, if autobump
    is enabled.

    Mutates the SiteSetting row on the *current* session WITHOUT
    committing — the caller's own ``db.session.commit()`` persists it
    atomically with the upload. Best-effort: any failure is swallowed so
    cache bookkeeping can never break an upload. The "Clear cache" button
    is the guaranteed fallback path."""
    try:
        s = SiteSetting.query.first()
        if s is None or not s.media_cache_autobump:
            return
        s.media_cache_version = (s.media_cache_version or 1) + 1
    except Exception:
        pass


def clear_cache():
    """Manual cache bust: advance the token, record the time, commit.
    Returns the new version (or ``None`` if there's no settings row)."""
    from datetime import datetime
    s = SiteSetting.query.first()
    if s is None:
        return None
    s.media_cache_version = (s.media_cache_version or 1) + 1
    s.media_cache_cleared_at = datetime.utcnow()
    db.session.commit()
    invalidate()
    return s.media_cache_version


def thumb_stats():
    """(count, total_bytes) of generated thumbnail files on disk."""
    folder = current_app.config.get("UPLOAD_FOLDER")
    count = 0
    total = 0
    try:
        with os.scandir(folder) as it:
            for e in it:
                try:
                    if e.is_file() and _THUMB_RE.search(e.name):
                        count += 1
                        total += e.stat().st_size
                except OSError:
                    continue
    except (OSError, TypeError):
        pass
    return count, total


def clear_thumbnails():
    """Delete all generated thumbnail files (regenerated lazily on next
    request). Returns the number removed."""
    folder = current_app.config.get("UPLOAD_FOLDER")
    names = []
    try:
        with os.scandir(folder) as it:
            names = [e.name for e in it
                     if e.is_file() and _THUMB_RE.search(e.name)]
    except (OSError, TypeError):
        return 0
    removed = 0
    for n in names:
        try:
            os.remove(os.path.join(folder, n))
            removed += 1
        except OSError:
            continue
    return removed


def register(app):
    """Wire the url_defaults bust-token injector into the app."""
    app.url_defaults(inject_bust)
