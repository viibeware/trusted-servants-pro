# SPDX-License-Identifier: AGPL-3.0-or-later
"""Populate the UrlRedirect table with 301s from every WordPress media URL
on the old site to /pub/<filename> on the Pro site. Run once per migration.

Prereqs:
  - WP Application Password. Pass via WP_USER / WP_PASS env vars or --user / --password.
  - The target Pro files are already in the MediaItem table (import_wp_libraries +
    fetch_wp_files have run, or uploads exist under the expected original filenames).

Usage:
  WP_USER=admin WP_PASS='xxxx xxxx ...' \
    python scripts/import_wp_redirects.py --site https://ts.dccma.com
  Add --dry-run to preview without writing to the DB.
"""
import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.models import db, UrlRedirect

DEFAULT_TIMEOUT = 30
PAGE_SIZE = 100


def fetch_media_urls(site, user, password):
    base = site.rstrip("/") + "/wp-json/wp/v2/media"
    auth = (user, password)
    page = 1
    while True:
        r = requests.get(base, params={"per_page": PAGE_SIZE, "page": page,
                                       "_fields": "source_url"},
                         auth=auth, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 400 and page > 1:
            break
        r.raise_for_status()
        items = r.json()
        if not items:
            break
        for item in items:
            src = item.get("source_url")
            if src:
                yield src
        if len(items) < PAGE_SIZE:
            break
        page += 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", required=True, help="WP site root, e.g. https://ts.dccma.com")
    ap.add_argument("--user", default=os.environ.get("WP_USER"))
    ap.add_argument("--password", default=os.environ.get("WP_PASS"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.user or not args.password:
        ap.error("WP credentials required (WP_USER / WP_PASS or --user/--password)")

    app = create_app()
    with app.app_context():
        existing = {r.source_path for r in UrlRedirect.query.all()}
        added = skipped = 0
        for src in fetch_media_urls(args.site, args.user, args.password):
            parsed = urlparse(src)
            source_path = parsed.path
            filename = os.path.basename(source_path)
            if not filename:
                continue
            target_path = "/pub/" + filename
            if source_path in existing:
                skipped += 1
                continue
            print(f"  + {source_path}  ->  {target_path}")
            if not args.dry_run:
                db.session.add(UrlRedirect(source_path=source_path, target_path=target_path))
            existing.add(source_path)
            added += 1
        if args.dry_run:
            print(f"\nDry run: would add {added} redirects ({skipped} already present)")
        else:
            db.session.commit()
            print(f"\nAdded {added} redirects ({skipped} already present)")


if __name__ == "__main__":
    main()
