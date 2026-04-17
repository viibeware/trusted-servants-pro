# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resolve WP attachment IDs from the export CSV, download each file, and
attach them to already-imported Meeting/Reading rows.

Prereqs:
  - scripts/import_wp_meetings.py has already been run (meetings + placeholder
    MeetingFile / Reading rows exist).
  - WP Application Password created. Pass via WP_USER / WP_PASS env vars or
    --user / --password flags.

Usage:
  WP_USER=admin WP_PASS='xxxx xxxx ...' \
    python scripts/fetch_wp_files.py temp/Posts-Export-XXXX.csv \
      --site https://ts.dccma.com
  Add --dry-run to preview without downloading or committing.
"""
import argparse
import csv
import html
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from werkzeug.utils import secure_filename

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.models import db, Meeting, MeetingFile, Library, Reading

SHARED_LIBRARY_NAME = "Imported Readings"
DEFAULT_TIMEOUT = 30


def clean(value):
    if value is None:
        return None
    s = html.unescape(str(value)).strip()
    return s or None


def collect_indexed_groups(row, prefix, fields, max_i=30):
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
            if gap > 2:
                break
        i += 1


class MediaResolver:
    def __init__(self, site, user, password):
        self.base = site.rstrip("/") + "/wp-json/wp/v2/media"
        self.auth = (user, password)
        self.cache = {}  # id -> {source_url, mime, filename}

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
            print(f"  ! media {aid}: request failed: {e}")
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
        filename = os.path.basename(urlparse(src).path) or f"media-{aid}"
        info = {"source_url": src, "mime": d.get("mime_type"), "filename": filename}
        self.cache[aid] = info
        return info


def download_to_uploads(url, upload_dir, original_name):
    """Stream URL to upload_dir with a UUID filename. Returns (stored, original)."""
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
    dest = os.path.join(upload_dir, stored)
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=64 * 1024):
            if chunk:
                f.write(chunk)
    return stored, original


def find_meeting_for_row(row):
    title = clean(row.get("Title"))
    if not title:
        return None
    return Meeting.query.filter_by(name=title[:200]).first()


def find_meeting_file(meeting, category, title):
    title = clean(title)
    if not title:
        return None
    return (MeetingFile.query
            .filter_by(meeting_id=meeting.id, category=category, title=title[:255])
            .first())


def find_reading(library, title):
    title = clean(title)
    if not title:
        return None
    return Reading.query.filter_by(library_id=library.id, title=title[:255]).first()


def attach_file_to_mf(mf, stored, original):
    mf.stored_filename = stored
    mf.original_filename = original


def attach_file_to_reading(r, stored, original):
    r.stored_filename = stored
    r.original_filename = original


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--site", default="https://ts.dccma.com")
    ap.add_argument("--user", default=os.environ.get("WP_USER"))
    ap.add_argument("--password", default=os.environ.get("WP_PASS"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-size-mb", type=int, default=200,
                    help="Skip files larger than this (via Content-Length) (default 200)")
    args = ap.parse_args()

    if not args.user or not args.password:
        print("Missing credentials. Set WP_USER and WP_PASS or pass --user/--password.")
        sys.exit(2)

    app = create_app()
    with app.app_context():
        upload_dir = app.config["UPLOAD_FOLDER"]
        os.makedirs(upload_dir, exist_ok=True)

        resolver = MediaResolver(args.site, args.user, args.password)
        shared_library = Library.query.filter_by(name=SHARED_LIBRARY_NAME).first()

        downloaded = 0
        attached = 0
        skipped = 0
        id_to_stored = {}  # dedupe: attachment id -> (stored, original)

        def get_file_for_id(aid, original_hint=None):
            nonlocal downloaded
            if aid in id_to_stored:
                return id_to_stored[aid]
            info = resolver.resolve(aid)
            if not info:
                id_to_stored[aid] = None
                return None
            if args.dry_run:
                print(f"  (dry) would download #{aid}: {info['source_url']}")
                placeholder = ("DRYRUN", info["filename"])
                id_to_stored[aid] = placeholder
                return placeholder
            result = download_to_uploads(info["source_url"], upload_dir, info["filename"])
            if result:
                downloaded += 1
                print(f"  ↓ #{aid}: {info['filename']}")
            id_to_stored[aid] = result
            return result

        with open(args.csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not clean(row.get("Title")):
                    continue
                if not (row.get("meeting_days") or "").strip():
                    continue  # non-meeting row (filtered in original import)
                meeting = find_meeting_for_row(row)
                if not meeting:
                    print(f"  ? no DB meeting for '{clean(row.get('Title'))}' — skipping")
                    continue

                # Scripts (MeetingFile, category='scripts')
                for idx, g in collect_indexed_groups(row, "meeting_scripts",
                                                    ["script_file", "script_title", "script_file_type"]):
                    aid = g.get("script_file")
                    if not aid:
                        continue
                    mf = find_meeting_file(meeting, "scripts", g.get("script_title"))
                    if not mf:
                        skipped += 1
                        continue
                    got = get_file_for_id(aid)
                    if got:
                        stored, original = got
                        attach_file_to_mf(mf, stored, original)
                        attached += 1

                # Literature (MeetingFile, category='documents')
                for idx, g in collect_indexed_groups(row, "meeting_literature",
                                                    ["literature_file", "literature_title", "literature_file_type"]):
                    aid = g.get("literature_file")
                    if not aid:
                        continue
                    mf = find_meeting_file(meeting, "documents", g.get("literature_title"))
                    if not mf:
                        skipped += 1
                        continue
                    got = get_file_for_id(aid)
                    if got:
                        stored, original = got
                        attach_file_to_mf(mf, stored, original)
                        attached += 1

                # Readings (Reading in shared library)
                if shared_library:
                    for idx, g in collect_indexed_groups(row, "meeting_readings",
                                                        ["reading_file", "reading_title", "file_type"]):
                        aid = g.get("reading_file")
                        if not aid:
                            continue
                        r = find_reading(shared_library, g.get("reading_title"))
                        if not r:
                            skipped += 1
                            continue
                        got = get_file_for_id(aid)
                        if got:
                            stored, original = got
                            attach_file_to_reading(r, stored, original)
                            attached += 1

                # meeting_files (MeetingFile, category='documents') — different field names
                for idx, g in collect_indexed_groups(row, "meeting_files",
                                                    ["meeting_file_select", "meeting_file_name", "meeting_file_type"]):
                    aid = g.get("meeting_file_select")
                    if not aid:
                        continue
                    mf = find_meeting_file(meeting, "documents", g.get("meeting_file_name"))
                    if not mf:
                        skipped += 1
                        continue
                    got = get_file_for_id(aid)
                    if got:
                        stored, original = got
                        attach_file_to_mf(mf, stored, original)
                        attached += 1

        if args.dry_run:
            db.session.rollback()
            print(f"\nDRY RUN — would attach {attached} files, skipped {skipped}, "
                  f"{len(id_to_stored)} unique attachment IDs resolved.")
        else:
            db.session.commit()
            print(f"\nDone — downloaded {downloaded} files, attached to {attached} DB rows, "
                  f"skipped {skipped} (no matching DB row).")


if __name__ == "__main__":
    main()
