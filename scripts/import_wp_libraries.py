"""Importer for WP All Export CSV of `library` custom post type.

One WP library post -> one Library row. Its ACF repeaters
(library_readings, library_literature, library_documents, library_files,
library_external_links, library_video_links) -> Reading rows in that library.

File-based readings have their WP attachment resolved via REST and downloaded
into app.config['UPLOAD_FOLDER']. URL-based readings (external/video links)
populate Reading.url. Video thumbnails (attachment IDs) are downloaded into
Reading.thumbnail_filename when present.

Usage:
  WP_USER=admin WP_PASS='xxxx xxxx ...' \
    python scripts/import_wp_libraries.py \
      temp/Libraries-Export-2026-April-15-1215.csv \
      --site https://ts.dccma.com
  Add --dry-run to preview without downloading or committing.
"""
import argparse
import csv
import html
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from werkzeug.utils import secure_filename

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.models import db, Library, Reading

DEFAULT_TIMEOUT = 30


def clean(v):
    if v is None:
        return None
    s = html.unescape(str(v)).strip()
    return s or None


def collect_indexed_groups(row, prefix, fields, max_i=40):
    i = 0
    gap = 0
    while i <= max_i:
        keys = {f: f"{prefix}_{i}_{f}" for f in fields}
        data = {f: (row.get(k) or "").strip() for f, k in keys.items()}
        if any(data.values()):
            yield i, data
            gap = 0
        else:
            gap += 1
            if gap > 3:
                break
        i += 1


class MediaResolver:
    def __init__(self, site, user, password):
        self.base = site.rstrip("/") + "/wp-json/wp/v2/media"
        self.auth = (user, password)
        self.cache = {}

    def resolve(self, attachment_id):
        try:
            aid = int(attachment_id)
        except (TypeError, ValueError):
            return None
        if aid in self.cache:
            return self.cache[aid]
        try:
            r = requests.get(f"{self.base}/{aid}", auth=self.auth, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as e:
            print(f"  ! media {aid}: {e}")
            self.cache[aid] = None
            return None
        if r.status_code != 200:
            print(f"  ! media {aid}: HTTP {r.status_code}")
            self.cache[aid] = None
            return None
        d = r.json()
        src = d.get("source_url")
        if not src:
            self.cache[aid] = None
            return None
        info = {
            "source_url": src,
            "filename": os.path.basename(urlparse(src).path) or f"media-{aid}",
            "mime": d.get("mime_type"),
        }
        self.cache[aid] = info
        return info


def download_to_uploads(url, upload_dir, original_name):
    try:
        r = requests.get(url, timeout=DEFAULT_TIMEOUT, stream=True)
    except requests.RequestException as e:
        print(f"  ! download failed: {e}")
        return None
    if r.status_code != 200:
        print(f"  ! download HTTP {r.status_code}: {url}")
        return None
    original = secure_filename(original_name) or "download"
    ext = os.path.splitext(original)[1]
    stored = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(upload_dir, stored), "wb") as f:
        for chunk in r.iter_content(chunk_size=64 * 1024):
            if chunk:
                f.write(chunk)
    return stored, original


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--site", default="https://ts.dccma.com")
    ap.add_argument("--user", default=os.environ.get("WP_USER"))
    ap.add_argument("--password", default=os.environ.get("WP_PASS"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.dry_run and (not args.user or not args.password):
        print("Missing credentials. Set WP_USER/WP_PASS or pass --user/--password "
              "(or use --dry-run to preview without downloading).")
        sys.exit(2)

    app = create_app()
    with app.app_context():
        upload_dir = app.config["UPLOAD_FOLDER"]
        os.makedirs(upload_dir, exist_ok=True)

        resolver = MediaResolver(args.site, args.user or "", args.password or "")
        id_cache = {}  # attachment id -> (stored, original) or None

        def fetch_file(aid):
            if not aid:
                return None
            if aid in id_cache:
                return id_cache[aid]
            info = resolver.resolve(aid)
            if not info:
                id_cache[aid] = None
                return None
            if args.dry_run:
                print(f"  (dry) would download #{aid}: {info['source_url']}")
                id_cache[aid] = ("DRYRUN", info["filename"])
                return id_cache[aid]
            result = download_to_uploads(info["source_url"], upload_dir, info["filename"])
            if result:
                print(f"  ↓ #{aid}: {info['filename']}")
            id_cache[aid] = result
            return result

        libraries = 0
        readings = 0
        with open(args.csv_path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if (row.get("Post Type") or "").strip() and row.get("Post Type") != "library":
                    continue
                title = clean(row.get("Title"))
                if not title:
                    continue
                status = (row.get("Status") or "").strip()
                if status and status not in ("publish", "private"):
                    continue

                lib = Library.query.filter_by(name=title[:200]).first()
                if not lib:
                    lib = Library(name=title[:200], description=clean(row.get("Content")))
                    db.session.add(lib)
                    db.session.flush()
                    libraries += 1
                    print(f"+ Library: {lib.name}")
                else:
                    print(f"= Library (exists): {lib.name}")

                pos = lib.readings.count()

                def add_reading(title, url=None, stored=None, original=None, thumb=None, body=None):
                    nonlocal pos, readings
                    title = clean(title) or clean(original) or "Untitled"
                    existing = Reading.query.filter_by(
                        library_id=lib.id, title=title[:255]).first()
                    if existing:
                        # update file info if we now have it
                        if stored and not existing.stored_filename:
                            existing.stored_filename = stored
                            existing.original_filename = original
                        if url and not existing.url:
                            existing.url = url[:1000]
                        if thumb and not existing.thumbnail_filename:
                            existing.thumbnail_filename = thumb
                        return existing
                    r = Reading(
                        library_id=lib.id,
                        title=title[:255],
                        url=(url[:1000] if url else None),
                        stored_filename=stored,
                        original_filename=original,
                        thumbnail_filename=thumb,
                        body=body,
                        position=pos,
                    )
                    db.session.add(r)
                    db.session.flush()
                    pos += 1
                    readings += 1
                    return r

                # File-based repeaters: (prefix, file-field, title-field)
                file_groups = [
                    ("library_readings",  "reading_file",   "reading_title",   "file_type"),
                    ("library_literature","literature_file","literature_title","literature_file_type"),
                    ("library_documents", "document_file",  "document_title",  "document_file_type"),
                    ("library_files",     "file_select",    "file_name",       "file_type"),
                ]
                for prefix, ffield, tfield, typefield in file_groups:
                    for _, g in collect_indexed_groups(
                            row, prefix, [ffield, tfield, typefield]):
                        aid = g.get(ffield)
                        ttl = g.get(tfield)
                        got = fetch_file(aid)
                        stored = original = None
                        if got:
                            stored, original = got
                            if stored == "DRYRUN":
                                stored = None  # don't persist placeholders
                        add_reading(ttl, stored=stored, original=original)

                # External links
                for _, g in collect_indexed_groups(
                        row, "library_external_links",
                        ["external_link_url", "external_link_title"]):
                    url = g.get("external_link_url")
                    if not url:
                        continue
                    add_reading(g.get("external_link_title") or url, url=url)

                # Video links (+ optional thumbnail attachment id)
                for _, g in collect_indexed_groups(
                        row, "library_video_links",
                        ["video_url", "video_title", "video_thumbnail"]):
                    url = g.get("video_url")
                    if not url:
                        continue
                    thumb_stored = None
                    got = fetch_file(g.get("video_thumbnail"))
                    if got:
                        ts, _to = got
                        if ts and ts != "DRYRUN":
                            thumb_stored = ts
                    add_reading(g.get("video_title") or url, url=url, thumb=thumb_stored)

        if args.dry_run:
            db.session.rollback()
            print(f"\nDRY RUN — would add {libraries} libraries, {readings} readings; "
                  f"{len(id_cache)} unique attachment IDs resolved.")
        else:
            db.session.commit()
            print(f"\nDone — added {libraries} libraries, {readings} readings.")


if __name__ == "__main__":
    main()
