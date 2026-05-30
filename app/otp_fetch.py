# SPDX-License-Identifier: AGPL-3.0-or-later
"""Retrieve Zoom one-time-passcode codes over IMAP.

The shared OTP inbox (see :class:`ZoomOtpEmail`) receives Zoom's login
verification emails. Rather than make a trusted servant open webmail,
hunt for the newest message, and squint at the code, the guided Zoom
launcher calls :func:`fetch_latest_code` which logs in over IMAP, finds
the freshest Zoom code, and hands back the digits plus the email's own
timestamp so the user can be sure they're copying the *current* code.

Design notes / guard rails:

* Only codes from emails **younger than ``max_age_minutes``** (default
  15) are returned. Zoom codes expire quickly; surfacing a stale one
  would send the user in circles. The age is measured from the email's
  ``Date`` header (falling back to the IMAP ``INTERNALDATE``), not from
  when we happen to poll.
* We prefer messages whose sender looks like Zoom and whose subject/body
  mentions a passcode, but fall back to any recent 6-digit code so minor
  wording changes in Zoom's emails don't silently break retrieval.
* Nothing here mutates the mailbox (no flag/delete) — read-only access
  via ``EXAMINE`` keeps the inbox untouched for the next user.
"""
import imaplib
import re
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from .crypto import decrypt

# A Zoom one-time passcode is six digits. Keep the boundary loose enough
# to match "code: 123456", "123 456" is NOT matched (we require the six
# to be contiguous) so we don't glue unrelated numbers together.
_CODE_RE = re.compile(r"\b(\d{6})\b")
# Words that, when sitting next to a 6-digit run, strongly imply it's the
# passcode rather than a stray number (meeting id, year, zip, phone, map
# coordinate). "expire(s)" is the single strongest anchor: Zoom prints the
# code immediately before "The code will expire in N minutes." The other
# strong hints cover wording variants across Zoom's sign-in / verification
# templates.
_CODE_HINTS_STRONG = (
    "expire", "passcode", "pass code", "one-time", "one time",
    "verification code", "verification", "security code", "otp",
)
# Weaker contextual cues — accepted only when no strong-hinted code exists.
_CODE_HINTS_WEAK = (
    "code below", "enter the code", "the code", "code to sign", "your code",
    "sign in to zoom", "signing in to zoom", "code is", "code:", "verify",
)


def _decode(value):
    """Best-effort decode of a MIME-encoded header to a plain string."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _html_to_text(html):
    """Flatten an HTML email body to visible text.

    Critically drops ``<head>`` / ``<style>`` / ``<script>`` blocks first.
    A marketing-style HTML email (Zoom's sign-in code mail included)
    carries hundreds of stray digits in its embedded CSS, web-font URLs,
    and ``unicode-range`` rules. Left in, those numbers pollute the
    6-digit-code search and the wrong one gets chosen. After removing the
    non-visible blocks we strip the remaining tags (so the code wrapped in
    a ``<td>``/``<strong>`` still reads as adjacent text) and collapse
    whitespace."""
    html = re.sub(r"(?is)<head\b.*?</head>", " ", html)
    html = re.sub(r"(?is)<style\b.*?</style>", " ", html)
    html = re.sub(r"(?is)<script\b.*?</script>", " ", html)
    html = re.sub(r"<[^>]+>", " ", html)
    html = html.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", html).strip()


def _body_text(msg):
    """Flatten a message to a single text blob (plain parts preferred,
    HTML parts reduced to their *visible* text)."""
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype not in ("text/plain", "text/html"):
                continue
            try:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                parts.append((ctype, payload.decode(charset, errors="replace")))
            except Exception:
                continue
    else:
        try:
            payload = msg.get_payload(decode=True) or b""
            charset = msg.get_content_charset() or "utf-8"
            parts.append((msg.get_content_type(),
                          payload.decode(charset, errors="replace")))
        except Exception:
            pass
    return "\n".join(_html_to_text(raw) if ctype == "text/html" else raw
                     for ctype, raw in parts)


def _extract_code(subject, body):
    """Pull the most likely 6-digit passcode out of subject/body.

    Scores every standalone 6-digit run by the strongest hint word in a
    ~60-char window around it: a strong hint ("expire", "passcode",
    "verification"…) outranks a weak one ("the code", "sign in to zoom"…),
    which outranks no hint at all. The highest-scoring run wins; ties go to
    the earliest. Returns ``None`` when there's no 6-digit run at all.

    The score gate is what stops the footer's map coordinate or the
    sign-in-activity date/phone from being mistaken for the code — they
    sit far from any hint and only score when nothing better exists.

    Returns ``(code, confidence)`` where confidence is 2 (strong hint near
    the run), 1 (weak hint), or 0 (no hint / pure fallback); ``(None, 0)``
    when there's no 6-digit run at all. The confidence lets the caller
    keep a genuine code from losing to a stray number in a *newer*
    non-code email (e.g. a "sign-in detected" notice)."""
    text = (subject or "") + " \n " + (body or "")
    low = text.lower()
    best = None  # (score, position, code)
    for m in _CODE_RE.finditer(text):
        window = low[max(0, m.start() - 60):m.end() + 60]
        if any(h in window for h in _CODE_HINTS_STRONG):
            score = 2
        elif any(h in window for h in _CODE_HINTS_WEAK):
            score = 1
        else:
            score = 0
        if best is None or score > best[0]:
            best = (score, m.start(), m.group(1))
    return (best[2], best[0]) if best else (None, 0)


def _msg_datetime(msg, internaldate_bytes):
    """Aware UTC datetime for a message, Date header first."""
    raw = msg.get("Date")
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
        except Exception:
            pass
    if internaldate_bytes:
        try:
            # Internaldate2tuple returns a *local-time* struct_time (it has
            # already folded in the message's zone offset). Convert through
            # the epoch so the result is a correct aware-UTC datetime
            # regardless of the host's timezone.
            tup = imaplib.Internaldate2tuple(internaldate_bytes)
            if tup:
                import time as _time
                return datetime.fromtimestamp(_time.mktime(tup), tz=timezone.utc)
        except Exception:
            pass
    return None


def fetch_latest_code(otp, max_age_minutes=10):
    """Return the freshest Zoom OTP code from the configured IMAP inbox.

    ``otp`` is a :class:`ZoomOtpEmail` row. Returns a dict:
      ``{"ok": True, "code": "123456", "sent_at": <aware UTC datetime>,
         "age_seconds": <int>}``
    on success, or ``{"ok": False, "error": "<human message>"}`` on any
    misconfiguration / connection / empty-mailbox condition. Never
    raises — the caller is a user-facing button.
    """
    if otp is None:
        return {"ok": False, "error": "OTP email is not configured."}

    host = (otp.imap_host or "").strip()
    if not host:
        return {"ok": False,
                "error": "IMAP server is not configured. Add it under "
                         "Settings → Security → Zoom OTP Email."}

    username = (otp.imap_username or otp.email or "").strip()
    if not username:
        return {"ok": False, "error": "No IMAP username or email is configured."}

    # IMAP password falls back to the mailbox password when no separate
    # app password was stored.
    password = decrypt(otp.imap_password_enc) if otp.imap_password_enc else ""
    if not password:
        password = decrypt(otp.password_enc) if otp.password_enc else ""
    if not password:
        return {"ok": False, "error": "No IMAP password is stored for the OTP inbox."}

    port = otp.imap_port or (993 if otp.imap_ssl else 143)
    mailbox = (otp.imap_mailbox or "INBOX").strip() or "INBOX"
    use_ssl = otp.imap_ssl if otp.imap_ssl is not None else True

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)

    conn = None
    try:
        if use_ssl:
            conn = imaplib.IMAP4_SSL(host, port, timeout=20)
        else:
            conn = imaplib.IMAP4(host, port, timeout=20)
            try:
                conn.starttls()
            except Exception:
                pass  # server may not advertise STARTTLS on the plain port
        conn.login(username, password)
        # EXAMINE = read-only SELECT; never touches \Seen flags.
        typ, _ = conn.select(mailbox, readonly=True)
        if typ != "OK":
            return {"ok": False, "error": f"Could not open mailbox '{mailbox}'."}

        # IMAP SINCE granularity is whole days AND compares against each
        # message's INTERNALDATE *in the mail server's own timezone*, which
        # can lag UTC by up to ~14h (e.g. a US-Pacific server still reads
        # "29-May" at 00:39 UTC on the 30th). Computing SINCE from UTC
        # "now" would then exclude a just-arrived code sitting just past the
        # UTC midnight boundary. Widen the search by a day; the precise
        # per-message `sent_at >= cutoff` check below still enforces the
        # real freshness window. Format: 01-Jan-2026.
        since = (cutoff - timedelta(days=1)).strftime("%d-%b-%Y")
        typ, data = conn.search(None, "SINCE", since)
        if typ != "OK" or not data or not data[0]:
            return {"ok": False,
                    "error": "No recent verification emails found. "
                             "Wait for the code to arrive, then retry."}

        ids = data[0].split()
        # Newest UIDs last; walk back from the end and stop once messages
        # fall before the cutoff (a small look-back budget guards against
        # out-of-order Date headers).
        best = None  # (sent_at, code)
        misses = 0
        for mid in reversed(ids):
            typ, fetched = conn.fetch(mid, "(INTERNALDATE RFC822)")
            if typ != "OK" or not fetched or not isinstance(fetched[0], tuple):
                continue
            meta = fetched[0][0] or b""
            raw = fetched[0][1] or b""
            m = re.search(rb'INTERNALDATE "([^"]+)"', meta)
            internaldate = m.group(1) if m else None
            msg = message_from_bytes(raw)

            sent_at = _msg_datetime(msg, internaldate)
            if sent_at is None:
                continue
            if sent_at < cutoff:
                misses += 1
                if misses >= 5:
                    break
                continue

            subject = _decode(msg.get("Subject"))
            sender = (_decode(msg.get("From")) + " " + (msg.get("Return-Path") or "")).lower()
            body = _body_text(msg)

            code, confidence = _extract_code(subject, body)
            if not code:
                continue
            # Ranking key, compared as a tuple:
            #   (is_zoom, confidence, sent_at)
            # • is_zoom first so a stray forward never beats a Zoom mail.
            # • confidence next so a genuine code (hinted) always wins over a
            #   stray 6-digit in a *newer* non-code notice (e.g. "sign-in
            #   detected"), which would otherwise hijack the result.
            # • sent_at last so that among equally-credible Zoom codes the
            #   NEWEST one is returned — the valid code when a host requested
            #   several within the window.
            is_zoom = "zoom" in sender or "zoom" in subject.lower()
            score = (1 if is_zoom else 0, confidence, sent_at)
            if best is None or score > best[0]:
                best = (score, code, sent_at)

        if not best:
            return {"ok": False,
                    "error": "No verification code found in the last "
                             f"{max_age_minutes} minutes. Wait for a fresh "
                             "email and retry."}

        _, code, sent_at = best
        age = int((datetime.now(timezone.utc) - sent_at).total_seconds())
        return {"ok": True, "code": code, "sent_at": sent_at, "age_seconds": max(0, age)}

    except imaplib.IMAP4.error as e:
        return {"ok": False, "error": f"IMAP login failed: {e}"}
    except (OSError, TimeoutError) as e:
        return {"ok": False, "error": f"Could not reach the mail server: {e}"}
    except Exception as e:  # last-resort guard — this backs a UI button
        return {"ok": False, "error": f"Unexpected error retrieving the code: {e}"}
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass
