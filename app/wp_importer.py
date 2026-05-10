# SPDX-License-Identifier: AGPL-3.0-or-later
"""WordPress post importer — REST or CSV → Stories / Announcements / Events.

Wizard flow (driven by routes in app/routes.py and templates in
templates/wp_import_*):

  1. Source pick → admin chooses REST (URL + user + app password) or CSV.
  2. Connect / parse → posts + categories normalized into one shape and
     written to a stash JSON keyed by an opaque token. The stash lives
     in ``$TSP_DATA_DIR/wp_import/<token>.json`` so it survives gunicorn
     worker churn within a single boot.
  3. Map → admin assigns each post (or all posts in a category) to one
     of stories / announcements / events / skip. The mapping is saved
     back into the stash.
  4. Dry run → ``compile_plan`` walks the saved mapping and resolves
     per-target slug uniqueness, so the preview names exactly which
     rows would be created vs. skipped vs. blocked by a slug clash.
  5. Commit → ``apply_plan(dry_run=False)`` creates the rows + downloads
     featured images via ``download_image_to_uploads`` (with sha256
     dedupe through MediaItem). Stash is deleted on success.

Post body is stored as the WP-rendered HTML — the rendered Stories /
Announcements / Events templates already pass body through the
``markdown`` Jinja filter, which routes HTML through bleach with the
SAFE_RICH_TAGS allowlist. So WP HTML round-trips through to the public
site without a separate HTML→Markdown pass.
"""
import csv
import hashlib
import io
import json
import os
import re
import time
import uuid
from datetime import datetime
from urllib.parse import urlparse

import requests
from flask import current_app
from werkzeug.utils import secure_filename


DEFAULT_TIMEOUT = 25
USER_AGENT = "tspro-wp-importer/1.0"
TARGETS = ("stories", "announcements", "events", "skip")
TARGET_LABELS = {
    "stories":       "Story",
    "announcements": "Announcement",
    "events":        "Event",
    "skip":          "Skip",
}


# ---------------------------------------------------------------------------
# Stash — short-lived JSON files keyed by an opaque token. Used to ferry
# parsed posts + admin mapping selections between wizard steps without
# pushing the whole payload through the form on every POST.
# ---------------------------------------------------------------------------

def _stash_dir():
    upload = current_app.config["UPLOAD_FOLDER"].rstrip("/")
    data_dir = os.path.dirname(upload)
    path = os.path.join(data_dir, "wp_import")
    os.makedirs(path, exist_ok=True)
    return path


def stash_save(token, payload):
    p = os.path.join(_stash_dir(), f"{token}.json")
    with open(p, "w") as f:
        json.dump(payload, f)
    return p


def stash_load(token):
    if not _valid_token(token):
        return None
    p = os.path.join(_stash_dir(), f"{token}.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except (ValueError, OSError):
        return None


def stash_delete(token):
    if not _valid_token(token):
        return
    p = os.path.join(_stash_dir(), f"{token}.json")
    if os.path.isfile(p):
        try:
            os.unlink(p)
        except OSError:
            pass


def stash_purge_old(max_age_seconds=86400):
    """Drop stash files older than 24h. Called opportunistically on
    every wizard entry so abandoned wizards don't accumulate."""
    d = _stash_dir()
    cutoff = time.time() - max_age_seconds
    try:
        for name in os.listdir(d):
            if not name.endswith(".json"):
                continue
            full = os.path.join(d, name)
            try:
                if os.path.getmtime(full) < cutoff:
                    os.unlink(full)
            except OSError:
                pass
    except OSError:
        pass


def new_token():
    return uuid.uuid4().hex


def _valid_token(token):
    return bool(token) and re.fullmatch(r"[a-f0-9]{16,64}", str(token)) is not None


# ---------------------------------------------------------------------------
# WordPress REST fetcher
# ---------------------------------------------------------------------------

def fetch_wp(site_url, user, app_password, *, max_posts=500):
    """Fetch posts + categories via WP REST API.

    Returns ``(posts, categories, error_msg)`` — on failure ``posts`` and
    ``categories`` are None and ``error_msg`` is a human-readable string.

    Authentication uses HTTP Basic with the admin's WP "Application
    Password" (recommended) or username + password. Anonymous fetches
    work too — pass ``user=None`` and only published posts will be
    returned.
    """
    site_url = (site_url or "").strip().rstrip("/")
    if not site_url:
        return None, None, "WordPress site URL is required."
    if not site_url.startswith(("http://", "https://")):
        site_url = "https://" + site_url
    base = site_url + "/wp-json/wp/v2"
    auth = (user, app_password) if (user and app_password) else None

    cats_by_id = {}
    page = 1
    while True:
        try:
            r = requests.get(f"{base}/categories", auth=auth, timeout=DEFAULT_TIMEOUT,
                             params={"per_page": 100, "page": page},
                             headers={"User-Agent": USER_AGENT})
        except requests.RequestException as e:
            return None, None, f"Could not reach {base}/categories: {e}"
        if r.status_code == 404:
            return None, None, ("WP REST API not reachable at "
                                f"{base} (404). Make sure permalinks are not set to plain.")
        if r.status_code in (401, 403):
            return None, None, (f"Authentication failed ({r.status_code}). "
                                "Verify the username and Application Password.")
        if r.status_code != 200:
            break
        chunk = r.json()
        if not chunk:
            break
        for c in chunk:
            cats_by_id[c["id"]] = c.get("name", "")
        if len(chunk) < 100:
            break
        page += 1

    posts = []
    page = 1
    statuses = "publish,draft,private,pending" if auth else "publish"
    while len(posts) < max_posts:
        try:
            r = requests.get(f"{base}/posts", auth=auth, timeout=DEFAULT_TIMEOUT,
                             params={"per_page": 50, "page": page,
                                     "_embed": "1", "status": statuses,
                                     "orderby": "date", "order": "desc"},
                             headers={"User-Agent": USER_AGENT})
        except requests.RequestException as e:
            return None, None, f"Could not fetch posts: {e}"
        if r.status_code == 400 and page > 1:
            # WP returns 400 ("rest_post_invalid_page_number") when paginated
            # past the last page — treat as end-of-list.
            break
        if r.status_code in (401, 403):
            return None, None, (f"Authentication failed ({r.status_code}). "
                                "Verify the username and Application Password.")
        if r.status_code != 200:
            break
        chunk = r.json()
        if not chunk:
            break
        for p in chunk:
            posts.append(_normalize_rest_post(p, cats_by_id))
        if len(chunk) < 50:
            break
        page += 1

    cats = sorted({n for n in cats_by_id.values() if n})
    return posts, cats, None


def _normalize_rest_post(p, cats_by_id):
    """Reduce a WP REST post object to the importer's flat dict shape."""
    cat_ids = p.get("categories") or []
    cat_names = [cats_by_id.get(cid) for cid in cat_ids if cats_by_id.get(cid)]

    img_url = None
    embedded = p.get("_embedded") or {}
    media = (embedded.get("wp:featuredmedia") or [None])[0]
    if isinstance(media, dict):
        img_url = (media.get("source_url")
                   or ((media.get("media_details") or {}).get("sizes") or {})
                   .get("full", {}).get("source_url"))

    author_name = None
    authors = embedded.get("author") or []
    if authors and isinstance(authors[0], dict):
        author_name = (authors[0].get("name") or "").strip() or None

    title = (p.get("title") or {}).get("rendered") or ""
    excerpt = (p.get("excerpt") or {}).get("rendered") or ""
    body = (p.get("content") or {}).get("rendered") or ""

    return {
        "key": f"wp-{p.get('id')}",
        "wp_id": p.get("id"),
        "title": _strip_html(title),
        "slug": (p.get("slug") or "").strip(),
        "summary": _strip_html(excerpt).strip()[:500],
        "body_html": body,
        "categories": cat_names,
        "author_name": author_name,
        "date": (p.get("date") or "")[:10],  # YYYY-MM-DD
        "featured_image_url": img_url,
        "is_draft": p.get("status") in ("draft", "private", "pending"),
        "url": p.get("link") or "",
    }


def _strip_html(s):
    if not s:
        return ""
    import html as _html
    txt = re.sub(r"<[^>]+>", "", str(s))
    return _html.unescape(txt).strip()


# ---------------------------------------------------------------------------
# CSV parser — accepts either WP All Export's "Posts" CSV or a generic
# WordPress CSV with `Title`, `Categories`, `Date`, `Content`, etc.
# ---------------------------------------------------------------------------

def parse_csv(file_obj, *, max_posts=2000):
    """Parse a WordPress posts CSV. Returns ``(posts, categories, err)``."""
    try:
        raw = file_obj.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            file_obj.seek(0)
            raw = file_obj.read().decode("latin-1")
        except UnicodeDecodeError:
            return None, None, "Could not decode the CSV — expected UTF-8."
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        return None, None, "CSV is empty or has no header row."

    posts = []
    cats_set = set()
    for i, row in enumerate(reader):
        if i >= max_posts:
            break
        title = _csv_field(row, "Title", "post_title", "Post Title").strip()
        if not title:
            continue
        cats_raw = _csv_field(row, "Categories", "post_category", "Category", "Tags")
        cat_names = [c.strip() for c in re.split(r"[|;,]", cats_raw or "") if c.strip()]
        for c in cat_names:
            cats_set.add(c)
        date_raw = _csv_field(row, "Date", "post_date", "Published", "Publish Date")
        date_iso = ""
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                date_iso = datetime.strptime(date_raw[:19], fmt).date().isoformat()
                break
            except (ValueError, IndexError):
                continue
        body = _csv_field(row, "Content", "post_content", "Body")
        excerpt = _csv_field(row, "Excerpt", "post_excerpt", "Summary").strip()
        author = _csv_field(row, "Author", "post_author").strip() or None
        slug = _csv_field(row, "Slug", "post_name", "URL Slug").strip()
        img_url = _csv_field(row, "Featured Image", "Image URL", "Attachment URL").strip() or None
        status = _csv_field(row, "Status", "post_status").strip().lower()
        permalink = _csv_field(row, "Permalink", "URL", "Link").strip()
        posts.append({
            "key": f"csv-{i+1}",
            "wp_id": None,
            "title": title,
            "slug": slug,
            "summary": excerpt[:500],
            "body_html": body,
            "categories": cat_names,
            "author_name": author,
            "date": date_iso,
            "featured_image_url": img_url,
            "is_draft": status in ("draft", "pending", "private"),
            "url": permalink,
        })
    if not posts:
        return None, None, ("No rows with a Title column. Make sure the CSV has a "
                            "header row including Title (or post_title).")
    return posts, sorted(cats_set), None


def _csv_field(row, *keys):
    for k in keys:
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v)
    return ""


# ---------------------------------------------------------------------------
# Plan compile + apply
# ---------------------------------------------------------------------------

def compile_plan(posts, mapping):
    """Walk every post and produce an action dict per post.

    Each action is ``{target, post, slug, conflict}`` — ``target`` is one
    of the TARGETS values, ``slug`` is the resolved unique-within-target
    slug, ``conflict`` is None when the slug doesn't clash with any
    existing row (or "slug-exists" when it does).

    Slug conflict resolution: rather than rejecting clashing posts, the
    apply phase auto-suffixes ``-2``, ``-3``, etc. via the same uniqueness
    helpers Stories/Posts already use. ``conflict`` is reported here so
    the dry-run preview can call out the rename to the admin.
    """
    from .models import Story, Post
    actions = []
    by_slug = {
        "stories":       {s.public_slug for s in Story.query.all()},
        "announcements": {p.public_slug for p in Post.query.filter(Post.is_announcement.is_(True)).all()},
        "events":        {p.public_slug for p in Post.query.filter(Post.is_event.is_(True)).all()},
    }
    for p in posts:
        target = (mapping.get(p["key"]) or "skip").strip()
        if target not in TARGETS or target == "skip":
            actions.append({"target": "skip", "post": p, "slug": None, "conflict": None})
            continue
        slug = _slugify(p["slug"] or p["title"])
        conflict = "slug-exists" if (slug and slug in by_slug.get(target, set())) else None
        actions.append({"target": target, "post": p, "slug": slug, "conflict": conflict})
    return actions


def _slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:200] or None


def _unique_slug(base, used):
    """Auto-suffix a slug with ``-2``, ``-3``, … until it doesn't appear
    in ``used`` (the in-process tracking of already-claimed slugs for the
    current target table). Mutates ``used`` to claim the resolved slug.
    """
    if not base:
        return None
    candidate = base
    n = 2
    while candidate in used:
        candidate = f"{base}-{n}"
        n += 1
    used.add(candidate)
    return candidate


def apply_plan(actions, *, dry_run=True, image_cb=None, created_by=None):
    """Walk a compiled plan and either render a preview (dry_run=True)
    or commit it (dry_run=False).

    Returns ``{counts, rows, warnings}``:
      counts.{stories,announcements,events,skipped,renamed,image_failed}
      rows  — list of {target, id (None on dry-run), title, slug,
                       image_status, was_renamed}
      warnings — list of "post X: …" strings the UI surfaces in red.
    """
    from .models import db, Story, Post

    counts = {"stories": 0, "announcements": 0, "events": 0,
              "skipped": 0, "renamed": 0, "image_failed": 0}
    rows = []
    warnings = []

    used_slugs = {
        "stories":       {s.public_slug for s in Story.query.all()},
        "announcements": {p.public_slug for p in Post.query.filter(Post.is_announcement.is_(True)).all()},
        "events":        {p.public_slug for p in Post.query.filter(Post.is_event.is_(True)).all()},
    }

    for a in actions:
        t = a["target"]
        p = a["post"]
        if t == "skip":
            counts["skipped"] += 1
            rows.append({"target": "skip", "id": None, "title": p["title"],
                         "slug": None, "image_status": None, "was_renamed": False})
            continue

        # Resolve final slug (auto-suffix on conflict).
        base = a.get("slug") or _slugify(p["title"])
        final_slug = _unique_slug(base, used_slugs.setdefault(t, set()))
        was_renamed = bool(base and final_slug and final_slug != base)
        if was_renamed:
            counts["renamed"] += 1

        # Featured image
        img_filename = None
        img_status = None
        url = p.get("featured_image_url") or None
        if url:
            if dry_run:
                img_status = "would-download"
            elif image_cb:
                try:
                    img_filename = image_cb(url)
                    img_status = "downloaded" if img_filename else "skipped"
                except Exception as e:  # noqa: BLE001
                    counts["image_failed"] += 1
                    warnings.append(f"{p['title'][:60]} — image download failed: {e}")
                    img_status = "failed"

        # Build the row
        try:
            d = datetime.strptime(p["date"], "%Y-%m-%d").date() if p.get("date") else None
        except (ValueError, TypeError):
            d = None

        if t == "stories":
            row = Story(
                title=p["title"][:255],
                # Only persist explicit slug when the slug differs from
                # the title-derived default — keeps Story.public_slug
                # tracking the title on subsequent renames.
                slug=(final_slug if final_slug != _slugify(p["title"]) else None),
                summary=(p.get("summary") or None) and p["summary"][:500] or None,
                body=p.get("body_html") or None,
                author_name=p.get("author_name"),
                story_date=d,
                featured_image_filename=img_filename,
                is_draft=bool(p.get("is_draft")),
                created_by=created_by,
            )
        else:
            row = Post(
                title=p["title"][:255],
                slug=(final_slug if final_slug != _slugify(p["title"]) else None),
                summary=(p.get("summary") or None) and p["summary"][:500] or None,
                body=p.get("body_html") or None,
                featured_image_filename=img_filename,
                is_announcement=(t == "announcements"),
                is_event=(t == "events"),
                event_starts_at=(datetime.combine(d, datetime.min.time())
                                 if (t == "events" and d) else None),
                is_draft=bool(p.get("is_draft")),
                created_by=created_by,
            )

        if not dry_run:
            db.session.add(row)
            db.session.flush()
            row_id = row.id
        else:
            row_id = None

        rows.append({
            "target": t,
            "id": row_id,
            "title": row.title,
            "slug": final_slug,
            "image_status": img_status,
            "was_renamed": was_renamed,
        })
        counts[t] += 1

    if not dry_run:
        db.session.commit()
    return {"counts": counts, "rows": rows, "warnings": warnings}


# ---------------------------------------------------------------------------
# Featured image download — used as the ``image_cb`` for apply_plan.
# Dedupes via MediaItem content_hash so re-imports don't pile up
# redundant copies of the same hero.
# ---------------------------------------------------------------------------

def download_image_to_uploads(url, *, uploaded_by=None):
    from .models import db, MediaItem
    resp = requests.get(url, timeout=DEFAULT_TIMEOUT, stream=True,
                        headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    data = resp.content
    h = hashlib.sha256(data).hexdigest()
    media = MediaItem.query.filter_by(content_hash=h).first()
    if media:
        return media.stored_filename
    parsed = urlparse(url)
    ext = (os.path.splitext(parsed.path)[1] or "").lower()
    if not ext or len(ext) > 6:
        # Pick from Content-Type when the URL didn't carry a usable ext.
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        ext = {
            "image/jpeg": ".jpg", "image/png": ".png",
            "image/webp": ".webp", "image/gif": ".gif",
        }.get(ctype, ".bin")
    stored = f"{uuid.uuid4().hex}{ext}"
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    with open(os.path.join(upload_dir, stored), "wb") as f:
        f.write(data)
    original = os.path.basename(parsed.path) or "wp-image"
    m = MediaItem(stored_filename=stored,
                  original_filename=secure_filename(original) or stored,
                  content_hash=h, size_bytes=len(data),
                  mime_type=resp.headers.get("Content-Type"),
                  uploaded_by=uploaded_by)
    db.session.add(m)
    db.session.flush()
    return stored
