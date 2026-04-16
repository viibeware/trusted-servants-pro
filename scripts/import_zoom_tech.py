"""Import the 'Zoom Tech Training' post from the WP CSV export:
   - Download every <img>/<video> source from the post using WP credentials,
   - Store locally under UPLOAD_FOLDER with UUID names (deduped by sha256),
   - Rewrite the post HTML so src attributes point to /uploads/<stored>,
   - Strip WP block comments,
   - Save into SiteSetting.zoom_tech_content (+ title) and enable the page.

Usage:
   WP_USER=admin WP_PASS='xxxx xxxx ...' \
     python scripts/import_zoom_tech.py temp/Posts-Export-XXXX.csv \
       --site https://ts.dccma.com
"""
import argparse
import csv
import hashlib
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from werkzeug.utils import secure_filename

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.models import db, SiteSetting, MediaItem

DEFAULT_TIMEOUT = 60


def fetch(url, auth):
    r = requests.get(url, timeout=DEFAULT_TIMEOUT, stream=True, auth=auth)
    r.raise_for_status()
    return r.content


def store_bytes(upload_dir, data, original_name, mime=None):
    h = hashlib.sha256(data).hexdigest()
    existing = MediaItem.query.filter_by(content_hash=h).first()
    if existing:
        return existing.stored_filename
    original = secure_filename(original_name) or "download"
    ext = os.path.splitext(original)[1]
    stored = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(upload_dir, stored), "wb") as f:
        f.write(data)
    db.session.add(MediaItem(stored_filename=stored, original_filename=original,
                             content_hash=h, size_bytes=len(data), mime_type=mime))
    db.session.flush()
    return stored


def strip_wp_comments(html):
    return re.sub(r"<!--\s*/?wp:[^>]*-->", "", html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--site", default="https://ts.dccma.com")
    ap.add_argument("--user", default=os.environ.get("WP_USER"))
    ap.add_argument("--password", default=os.environ.get("WP_PASS"))
    ap.add_argument("--title-match", default="zoom tech training")
    args = ap.parse_args()

    if not args.user or not args.password:
        print("Missing WP_USER/WP_PASS.")
        sys.exit(1)
    auth = (args.user, args.password)

    row = None
    with open(args.csv_path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if args.title_match in (r.get("Title") or "").lower():
                row = r; break
    if not row:
        print("Post not found."); sys.exit(1)

    title = row["Title"].strip()
    content = row["Content"] or ""
    print(f"Found: {title} ({len(content)} chars)")

    app = create_app()
    with app.app_context():
        upload_dir = app.config["UPLOAD_FOLDER"]
        urls = set(re.findall(r'src="([^"]+)"', content))
        url_map = {}
        for url in sorted(urls):
            host = urlparse(url).netloc
            if host and host not in urlparse(args.site).netloc:
                print(f"  skip external: {url}"); continue
            try:
                data = fetch(url, auth)
            except Exception as e:
                print(f"  ! fetch failed {url}: {e}"); continue
            original = os.path.basename(urlparse(url).path) or "file"
            stored = store_bytes(upload_dir, data, original)
            url_map[url] = f"/uploads/{stored}"
            print(f"  {url} -> {url_map[url]} ({len(data)} bytes)")

        new_content = content
        for old, new in url_map.items():
            new_content = new_content.replace(old, new)
        new_content = strip_wp_comments(new_content)

        s = SiteSetting.query.first()
        if not s:
            s = SiteSetting(); db.session.add(s)
        s.zoom_tech_title = title
        s.zoom_tech_content = new_content
        s.zoom_tech_enabled = True
        db.session.commit()
        print(f"Saved. Rewrote {len(url_map)} URLs. Page enabled.")


if __name__ == "__main__":
    main()
