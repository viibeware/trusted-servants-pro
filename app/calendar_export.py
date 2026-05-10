# SPDX-License-Identifier: AGPL-3.0-or-later
"""Calendar (ICS) exports.

Builds RFC-5545 compatible iCalendar payloads for meetings so visitors
can drop a one-tap "Add to Calendar" download next to any schedule.

Each meeting renders as one VCALENDAR with one VEVENT per
``MeetingSchedule`` row, recurring weekly via ``RRULE:FREQ=WEEKLY``.
DTSTART / DTEND are emitted as UTC for maximum client compatibility:
the next occurrence of the schedule's weekday + start time is computed
in the site's configured timezone, then converted to UTC for the
serialised value. This keeps DST drift to ±1 h twice a year (a known
trade-off of recurring events without a full VTIMEZONE block) while
working out of the box on Apple Calendar, Google Calendar, Outlook,
and the rest of the modern client landscape.
"""
from datetime import datetime, timedelta, timezone

from .timezone import site_timezone


def _escape(text):
    """RFC-5545 text escape: backslash, comma, semicolon, newline."""
    if text is None:
        return ""
    s = str(text)
    return (s.replace("\\", "\\\\")
             .replace(";", "\\;")
             .replace(",", "\\,")
             .replace("\r\n", "\\n")
             .replace("\n", "\\n")
             .replace("\r", "\\n"))


def _fmt_utc(dt):
    """RFC-5545 UTC timestamp: YYYYMMDDTHHMMSSZ."""
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fold(line):
    """RFC-5545 line folding: break at 75 octets, prefix continuation
    with a space. Operates on chars (close enough for ASCII payloads;
    the few unicode bytes admins put in titles fold imperfectly but
    every client accepts the result)."""
    if len(line) <= 75:
        return line
    parts = [line[:75]]
    rest = line[75:]
    while len(rest) > 74:
        parts.append(" " + rest[:74])
        rest = rest[74:]
    if rest:
        parts.append(" " + rest)
    return "\r\n".join(parts)


def _next_occurrence(now_aware, day_of_week, hh, mm):
    """Return an aware datetime for the next occurrence of `day_of_week`
    (Monday=0..Sunday=6) at `hh:mm`, in the same timezone as `now_aware`.
    If today's occurrence is in the past, advances to next week."""
    today_dow = now_aware.weekday()
    days_ahead = (day_of_week - today_dow) % 7
    candidate = now_aware.replace(hour=hh, minute=mm, second=0, microsecond=0) \
                          + timedelta(days=days_ahead)
    if days_ahead == 0 and candidate <= now_aware:
        candidate += timedelta(days=7)
    return candidate


# ICAL day codes — aligned to MeetingSchedule.day_of_week (0=Mon..6=Sun).
_ICAL_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def meeting_to_ics(meeting, site, base_url=""):
    """Serialise a Meeting to an ICS string.

    `base_url` (e.g. ``https://example.org``) is prepended to the
    meeting's permalink in the event description so users get a
    clickable "View meeting" link inside whatever calendar app they
    add the event to. When blank, the URL is omitted.

    Schedules with a missing/invalid `start_time` are skipped — they
    can't generate a sensible event.
    """
    tz = site_timezone(site)
    now = datetime.now(tz=tz)
    stamp = _fmt_utc(datetime.now(tz=timezone.utc))

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//tspro//Meeting Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    # Compose human-readable description once so each event references
    # the same blob. Includes the meeting body, Zoom credentials, and
    # the canonical URL so the calendar entry stays useful even when
    # the user is offline.
    desc_parts = []
    if meeting.description:
        desc_parts.append(meeting.description.strip())
    if meeting.meeting_type in ("online", "hybrid"):
        if meeting.zoom_link:
            desc_parts.append("Join Zoom: " + meeting.zoom_link)
        if meeting.zoom_meeting_id:
            desc_parts.append("Meeting ID: " + meeting.zoom_meeting_id)
        if meeting.zoom_passcode:
            desc_parts.append("Passcode: " + meeting.zoom_passcode)
    if base_url and getattr(meeting, "public_slug", None):
        desc_parts.append("Details: " + base_url.rstrip("/")
                          + "/meetings/" + meeting.public_slug)
    description = "\n\n".join(desc_parts).strip()

    # LOCATION priority: full address from the linked Location row →
    # raw `meeting.location` text → the Zoom link (for online-only).
    location = ""
    if meeting.location:
        location = meeting.location
        # Try to enrich with the matched Location row's address.
        from .models import Location
        loc_norm = meeting.location.strip().lower()
        for _l in Location.query.all():
            if _l.name and _l.name.strip().lower() == loc_norm and _l.address:
                location = _l.name + ", " + _l.address
                break
    elif meeting.meeting_type in ("online", "hybrid") and meeting.zoom_link:
        location = "Zoom · " + meeting.zoom_link

    summary = (meeting.name or "Meeting").strip()

    for s in (meeting.schedules or []):
        st = (s.start_time or "").strip()
        if ":" not in st:
            continue
        try:
            hh, mm = (int(x) for x in st.split(":", 1))
        except (TypeError, ValueError):
            continue
        dow = int(s.day_of_week or 0)
        if dow < 0 or dow > 6:
            continue
        first = _next_occurrence(now, dow, hh, mm)
        duration = max(1, int(s.duration_minutes or 60))
        last = first + timedelta(minutes=duration)

        # Stable UID: includes meeting id + schedule id so each
        # weekly recurring event is its own calendar entry.
        uid = "meeting-{}-sched-{}@tspro".format(meeting.id, s.id)

        lines.extend([
            "BEGIN:VEVENT",
            "UID:" + uid,
            "DTSTAMP:" + stamp,
            "DTSTART:" + _fmt_utc(first),
            "DTEND:"   + _fmt_utc(last),
            "RRULE:FREQ=WEEKLY;BYDAY=" + _ICAL_DAYS[dow],
            "SUMMARY:" + _escape(summary),
        ])
        if description:
            lines.append("DESCRIPTION:" + _escape(description))
        if location:
            lines.append("LOCATION:" + _escape(location))
        if meeting.meeting_type in ("online", "hybrid") and meeting.zoom_link:
            # URL is a separate property — many clients render it as a
            # dedicated link button on the event card.
            lines.append("URL:" + _escape(meeting.zoom_link))
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    # Fold long lines per RFC-5545 §3.1, then join with CRLF (also per
    # spec — most clients tolerate LF but Apple Calendar is stricter).
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


def event_to_ics(event, site, base_url=""):
    """Serialise a single Post (`is_event=True`) to an ICS string.

    Unlike meetings, event posts are single-occurrence — one VEVENT,
    no RRULE. `event_starts_at` / `event_ends_at` live in the model
    as naive datetimes representing the site's local wall clock; we
    attach the site's tz when present so the UTC conversion preserves
    the admin's intent across DST. When `event_ends_at` is missing we
    default the event to a 1-hour duration (most user-submitted events
    leave ends_at blank).

    Falls back gracefully when `event_starts_at` is missing — returns a
    VCALENDAR with no VEVENT, which calendar apps will silently ignore.
    The caller's button-render guard already gates on the start time so
    this is just defence-in-depth.
    """
    tz = site_timezone(site)
    stamp = _fmt_utc(datetime.now(tz=timezone.utc))

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//tspro//Event Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    starts = getattr(event, "event_starts_at", None)
    ends = getattr(event, "event_ends_at", None)
    if starts is not None:
        # Stored datetimes are tz-naive but represent the site's local
        # wall clock (the Posts admin form takes raw HH:MM strings).
        # Anchor them to the site tz before converting to UTC so the
        # UTC value matches the wall clock the admin typed.
        if starts.tzinfo is None:
            starts = starts.replace(tzinfo=tz)
        if ends is None:
            ends = starts + timedelta(hours=1)
        elif ends.tzinfo is None:
            ends = ends.replace(tzinfo=tz)

        # Build the human-readable description: body / summary, online
        # join info, contact, website, and the canonical URL.
        desc_parts = []
        if event.summary:
            desc_parts.append(event.summary.strip())
        if event.body:
            desc_parts.append(event.body.strip())
        if event.is_online:
            if event.zoom_url:
                desc_parts.append("Join: " + event.zoom_url)
            if event.zoom_meeting_id:
                desc_parts.append("Meeting ID: " + event.zoom_meeting_id)
            if event.zoom_passcode:
                desc_parts.append("Passcode: " + event.zoom_passcode)
        contact_bits = []
        if event.contact_name:  contact_bits.append(event.contact_name)
        if event.contact_phone: contact_bits.append(event.contact_phone)
        if event.contact_email: contact_bits.append(event.contact_email)
        if contact_bits:
            desc_parts.append("Contact: " + " · ".join(contact_bits))
        if event.website_url:
            label = event.website_label or "Event website"
            desc_parts.append(label + ": " + event.website_url)
        if base_url and getattr(event, "public_slug", None):
            desc_parts.append("Details: " + base_url.rstrip("/")
                              + "/event/" + event.public_slug)
        description = "\n\n".join(desc_parts).strip()

        # Location preference: explicit name + address → name → raw
        # address → online fallback (Zoom URL).
        location = ""
        if event.location_name and event.location_address:
            location = event.location_name + ", " + event.location_address
        elif event.location_name:
            location = event.location_name
        elif event.location_address:
            location = event.location_address
        elif event.is_online and event.zoom_url:
            location = "Online · " + event.zoom_url

        uid = "event-{}@tspro".format(event.id)
        summary = (event.title or "Event").strip()

        lines.extend([
            "BEGIN:VEVENT",
            "UID:" + uid,
            "DTSTAMP:" + stamp,
            "DTSTART:" + _fmt_utc(starts),
            "DTEND:"   + _fmt_utc(ends),
            "SUMMARY:" + _escape(summary),
        ])
        if description:
            lines.append("DESCRIPTION:" + _escape(description))
        if location:
            lines.append("LOCATION:" + _escape(location))
        # Public URL on the post takes precedence over the Zoom link
        # since the detail page surfaces the Zoom URL inline anyway.
        link_url = event.website_url or (event.zoom_url if event.is_online else "")
        if link_url:
            lines.append("URL:" + _escape(link_url))
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"
