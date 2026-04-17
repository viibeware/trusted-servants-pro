# SPDX-License-Identifier: AGPL-3.0-or-later
"""One-time importer for WP All Export CSV of meeting posts.

Usage:
    python scripts/import_wp_meetings.py temp/Posts-Export-2026-April-14-2155.csv
    python scripts/import_wp_meetings.py <csv> --dry-run
"""
import argparse
import csv
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.models import (
    db, Meeting, MeetingSchedule, MeetingFile, Library, Reading, MeetingLibrary,
)

SHARED_LIBRARY_NAME = "Imported Readings"

DAY_TO_INDEX = {
    "monday": 0, "mondays": 0,
    "tuesday": 1, "tuesdays": 1,
    "wednesday": 2, "wednesdays": 2,
    "thursday": 3, "thursdays": 3,
    "friday": 4, "fridays": 4,
    "saturday": 5, "saturdays": 5,
    "sunday": 6, "sundays": 6,
}

MEETING_TYPE_MAP = {
    "in-person": "in_person", "in person": "in_person",
    "online": "online",
    "hybrid": "hybrid",
}


def parse_php_serialized_days(value):
    """Parse a php-serialized string list like a:2:{i:0;s:7:\"Sundays\";i:1;s:9:\"Saturdays\";}"""
    if not value:
        return []
    days = []
    for m in re.finditer(r's:\d+:"([^"]+)"', value):
        key = m.group(1).strip().lower()
        if key in DAY_TO_INDEX:
            days.append(DAY_TO_INDEX[key])
    return sorted(set(days))


def parse_time_to_24h(value):
    """'1:00 pm' -> '13:00'. Returns None on failure."""
    if not value:
        return None
    v = value.strip().lower().replace(".", "")
    m = re.match(r"^(\d{1,2}):(\d{2})\s*(am|pm)?$", v)
    if not m:
        m = re.match(r"^(\d{1,2})\s*(am|pm)$", v)
        if not m:
            return None
        hh, mm, ap = int(m.group(1)), 0, m.group(2)
    else:
        hh, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    if ap == "pm" and hh != 12:
        hh += 12
    elif ap == "am" and hh == 12:
        hh = 0
    return f"{hh:02d}:{mm:02d}"


def duration_minutes(start24, end24):
    if not start24 or not end24:
        return 60
    sh, sm = map(int, start24.split(":"))
    eh, em = map(int, end24.split(":"))
    mins = (eh * 60 + em) - (sh * 60 + sm)
    return mins if mins > 0 else 60


def map_meeting_type(value):
    if not value:
        return "in_person"
    return MEETING_TYPE_MAP.get(value.strip().lower(), "in_person")


def clean(value):
    if value is None:
        return None
    s = html.unescape(str(value)).strip()
    return s or None


def nonempty(*vals):
    for v in vals:
        c = clean(v)
        if c:
            return c
    return None


def collect_indexed_groups(row, prefix, fields):
    """Yield dicts for groups like meeting_scripts_0_script_file, meeting_scripts_1_... """
    i = 0
    while True:
        keys = {f: f"{prefix}_{i}_{f}" for f in fields}
        if not any(row.get(k) for k in keys.values()):
            if i > 20:
                break
            # allow a few gaps
            if i > 0:
                break
        data = {f: (row.get(k) or "").strip() for f, k in keys.items()}
        if any(data.values()):
            yield data
        else:
            break
        i += 1


def import_row(row, shared_library, dry_run=False):
    title = clean(row.get("Title"))
    if not title:
        return None
    # Filter: only rows that look like meetings (must have meeting_days scheduled)
    if not (row.get("meeting_days") or "").strip():
        return None

    meeting = Meeting(
        name=title[:200],
        description=nonempty(row.get("meeting_summary"), row.get("Content")),
        meeting_type=map_meeting_type(row.get("meeting_type")),
        location=nonempty(row.get("in_person_location")),
        zoom_meeting_id=nonempty(row.get("zoom_meeting_id"), row.get("zoom_id")),
        zoom_passcode=nonempty(row.get("zoom_password"), row.get("zoom_meeting_passcode")),
        zoom_link=nonempty(row.get("zoom_link"), row.get("zoom_url")),
        zoom_opens_time=parse_time_to_24h(row.get("zoom_meeting_fellowship_open_time")),
    )
    db.session.add(meeting)
    db.session.flush()

    # Schedules: one per day using same start/end.
    days = parse_php_serialized_days(row.get("meeting_days"))
    start24 = parse_time_to_24h(row.get("meeting_start_time"))
    end24 = parse_time_to_24h(row.get("meeting_end_time"))
    if days and start24:
        dur = duration_minutes(start24, end24)
        for d in days:
            db.session.add(MeetingSchedule(
                meeting_id=meeting.id,
                day_of_week=d,
                start_time=start24,
                duration_minutes=dur,
                opens_time=parse_time_to_24h(row.get("zoom_meeting_fellowship_open_time")),
            ))

    # Scripts -> MeetingFile(category='scripts')
    for g in collect_indexed_groups(row, "meeting_scripts", ["script_title", "script_file", "script_file_type"]):
        ttl = g.get("script_title") or g.get("script_file") or "Script"
        db.session.add(MeetingFile(
            meeting_id=meeting.id, category="scripts",
            title=ttl[:255],
            description=g.get("script_file_type") or None,
        ))

    # Literature -> MeetingFile(category='documents')
    for g in collect_indexed_groups(row, "meeting_literature", ["literature_title", "literature_file", "literature_file_type"]):
        ttl = g.get("literature_title") or g.get("literature_file") or "Document"
        db.session.add(MeetingFile(
            meeting_id=meeting.id, category="documents",
            title=ttl[:255],
            description=g.get("literature_file_type") or None,
        ))

    # External links -> MeetingFile(category='external_links') with URL
    for g in collect_indexed_groups(row, "meeting_external_links", ["external_link_title", "external_link_url"]):
        ttl = g.get("external_link_title") or g.get("external_link_url") or "Link"
        db.session.add(MeetingFile(
            meeting_id=meeting.id, category="external_links",
            title=ttl[:255],
            url=g.get("external_link_url") or None,
        ))

    # Readings -> shared Library; granular association
    reading_titles = []
    for g in collect_indexed_groups(row, "meeting_readings", ["reading_title", "reading_file", "file_type"]):
        ttl = clean(g.get("reading_title")) or clean(g.get("reading_file"))
        if not ttl:
            continue
        reading_titles.append(ttl)

    if reading_titles:
        assoc = MeetingLibrary(meeting_id=meeting.id, library_id=shared_library.id, mode="granular")
        db.session.add(assoc)
        for ttl in reading_titles:
            existing = Reading.query.filter_by(library_id=shared_library.id, title=ttl[:255]).first()
            if existing:
                reading = existing
            else:
                reading = Reading(library_id=shared_library.id, title=ttl[:255])
                db.session.add(reading)
                db.session.flush()
            if reading not in meeting.selected_readings:
                meeting.selected_readings.append(reading)

    return meeting


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        shared_library = Library.query.filter_by(name=SHARED_LIBRARY_NAME).first()
        if not shared_library:
            shared_library = Library(name=SHARED_LIBRARY_NAME,
                                     description="Readings imported from WordPress.")
            db.session.add(shared_library)
            db.session.flush()

        count = 0
        skipped = 0
        with open(args.csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not clean(row.get("Title")):
                    skipped += 1
                    continue
                m = import_row(row, shared_library)
                if m is not None:
                    count += 1
                    print(f"  + {m.name}")
                else:
                    skipped += 1

        if args.dry_run:
            db.session.rollback()
            print(f"\nDRY RUN: would have imported {count} meetings ({skipped} skipped).")
        else:
            db.session.commit()
            print(f"\nImported {count} meetings ({skipped} skipped).")


if __name__ == "__main__":
    main()
