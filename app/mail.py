# SPDX-License-Identifier: AGPL-3.0-or-later
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr


def _recipients(raw):
    if not raw:
        return []
    return [r.strip() for r in str(raw).replace(";", ",").split(",") if r.strip()]


def send_mail(site, to, subject, body_text, body_html=None, attachments=None,
              reply_to=None, reply_to_name=None):
    """Send a plain-text (optionally HTML) email using the transport
    configured on SiteSetting.

    Two transports are supported, chosen by ``site.mail_transport``:

    - ``smtp`` (default) — connect directly to the SMTP server in the
      ``smtp_*`` columns. Works anywhere outbound SMTP ports are open.
    - ``relay`` — POST the message as JSON to a TSP email-relay
      container over HTTPS (port 443 behind a reverse proxy). Used on
      hosts like DigitalOcean that block outbound 25/465/587. The relay
      holds the real SMTP credentials; this side only stores the relay
      URL + a shared API key.

    The From header comes from ``smtp_from_email`` / ``smtp_from_name``
    in both modes, so switching transports doesn't change the sender.

    ``attachments`` is an optional list of dicts:
        {"path": "/abs/path/on/disk",
         "filename": "what-the-recipient-sees.jpg",
         "mime_type": "image/jpeg"}     # defaults to application/octet-stream
    Files that don't exist on disk are silently skipped — the email
    still goes out, the admin just doesn't get the attachment.

    Returns (ok: bool, error: str|None).
    """
    import os as _os
    if not site or not site.smtp_from_email:
        return False, "Outgoing email is not configured (no From address)"

    recipients = to if isinstance(to, list) else _recipients(to)
    if not recipients:
        return False, "No recipients"

    # --- API relay transport -------------------------------------------------
    if (getattr(site, "mail_transport", "smtp") or "smtp") == "relay":
        return _send_via_relay(site, recipients, subject, body_text,
                               body_html=body_html, attachments=attachments,
                               reply_to=reply_to, reply_to_name=reply_to_name)

    # --- Direct SMTP transport ----------------------------------------------
    if not site.smtp_host:
        return False, "SMTP is not configured"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((site.smtp_from_name or "", site.smtp_from_email))
    msg["To"] = ", ".join(recipients)
    if reply_to:
        msg["Reply-To"] = formataddr((reply_to_name or "", reply_to))
    msg.set_content(body_text or "")
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    for att in (attachments or []):
        path = att.get("path")
        if not path or not _os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except (OSError, IOError):
            continue
        mime = (att.get("mime_type") or "application/octet-stream")
        if "/" not in mime:
            mime = "application/octet-stream"
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(
            data, maintype=maintype, subtype=subtype or "octet-stream",
            filename=(att.get("filename") or _os.path.basename(path)),
        )

    from .crypto import decrypt
    password = decrypt(site.smtp_password_enc) if site.smtp_password_enc else ""
    port = int(site.smtp_port or (465 if site.smtp_security == "ssl" else 587))
    host = site.smtp_host
    try:
        if site.smtp_security == "ssl":
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as s:
                if site.smtp_username:
                    s.login(site.smtp_username, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.ehlo()
                if site.smtp_security == "starttls":
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                if site.smtp_username:
                    s.login(site.smtp_username, password)
                s.send_message(msg)
        return True, None
    except Exception as e:
        return False, str(e)


def _send_via_relay(site, recipients, subject, body_text, body_html=None,
                    attachments=None, reply_to=None, reply_to_name=None):
    """POST the message to the configured TSP email-relay over HTTPS.

    Mirrors the SMTP path's signature/return contract so callers don't
    branch on transport. Attachments are read from disk and base64-
    encoded into the JSON payload (missing files are skipped, same as
    the SMTP path). Authenticates with the shared API key as a Bearer
    token. Returns (ok, error)."""
    import os as _os
    import base64
    import requests
    from flask import current_app
    from .crypto import decrypt

    base = (site.relay_url or "").strip().rstrip("/")
    if not base:
        return False, "Relay URL is not configured"
    api_key = decrypt(site.relay_api_key_enc) if site.relay_api_key_enc else ""
    if not api_key:
        return False, "Relay API key is not configured"

    payload_attachments = []
    for att in (attachments or []):
        path = att.get("path")
        if not path or not _os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except (OSError, IOError):
            continue
        payload_attachments.append({
            "filename": att.get("filename") or _os.path.basename(path),
            "mime_type": att.get("mime_type") or "application/octet-stream",
            "content_b64": base64.b64encode(data).decode("ascii"),
        })

    payload = {
        "from_email": site.smtp_from_email,
        "from_name": site.smtp_from_name or "",
        "to": recipients,
        "subject": subject or "",
        "text": body_text or "",
        "html": body_html or None,
        "reply_to": reply_to or None,
        "reply_to_name": reply_to_name or None,
        "attachments": payload_attachments,
    }

    url = base + "/api/send"
    try:
        resp = requests.post(
            url, json=payload, timeout=30,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except requests.exceptions.SSLError as e:
        return False, f"Relay TLS error: {e}"
    except requests.exceptions.RequestException as e:
        return False, f"Relay connection failed: {e}"

    # Try to surface the relay's own error message when it returns JSON.
    detail = None
    try:
        body = resp.json()
        if isinstance(body, dict):
            if body.get("ok"):
                return True, None
            detail = body.get("error")
    except ValueError:
        body = None

    if resp.status_code == 200 and detail is None:
        return True, None

    try:
        current_app.logger.warning("email relay send failed: %s %s",
                                    resp.status_code, detail or resp.text[:200])
    except Exception:
        pass
    return False, (detail or f"Relay returned HTTP {resp.status_code}")


def relay_health(url, api_key, timeout=15):
    """Probe a TSP email-relay for reachability + API-key validity
    *without sending mail*. Backs the "Test connection" button / status
    pill on the Settings → Domain / Email tab.

    Primary probe: ``GET {base}/api/health`` with the key as a Bearer
    token. The relay validates the key (401 if wrong) and reports
    whether its own SMTP delivery is configured (``configured``).

    Fallback for relays predating /api/health (they 404 it): POST an
    empty body to ``/api/send``. The relay checks the Bearer key
    *before* it parses the body, so a wrong key still yields 401 and a
    valid key yields 400 ("Expected a JSON object body") — i.e. we
    validate the key without ever delivering a message.

    Returns ``(ok: bool, detail: str, configured: bool|None)`` where
    ``configured`` is the relay's own SMTP-setup state (None when the
    relay is too old to report it).
    """
    import requests

    if not (url or "").strip():
        return False, "Relay URL is not set.", None
    if not api_key:
        return False, "Relay API key is not set.", None

    base = url.strip().rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.get(base + "/api/health", headers=headers, timeout=timeout)
    except requests.exceptions.SSLError as e:
        return False, f"TLS error reaching the relay: {e}", None
    except requests.exceptions.RequestException as e:
        return False, f"Could not reach the relay: {e}", None

    if resp.status_code in (401, 403):
        return False, "The relay rejected the API key (HTTP 401). Check that the key matches the one on the relay's Settings page.", None
    if resp.status_code == 404:
        return _relay_health_legacy(base, headers, timeout)
    if resp.status_code != 200:
        return False, f"The relay returned HTTP {resp.status_code}.", None

    try:
        body = resp.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    configured = body.get("configured")
    configured = bool(configured) if configured is not None else None
    if body.get("ok") is False:
        return False, (body.get("error") or "The relay reported a problem."), configured
    if configured is False:
        return (True,
                "Connected, but the relay's own SMTP server isn't set up yet — "
                "configure it on the relay before it can deliver mail.",
                configured)
    return True, "Connection OK — the relay is reachable and the API key is valid.", configured


def _relay_health_legacy(base, headers, timeout):
    """Key-validation fallback for relays without /api/health: POST an
    empty body to /api/send. Auth is checked before the body is parsed,
    so a bad key → 401 and a good key → 400, and no mail is delivered
    either way. See :func:`relay_health`."""
    import requests
    try:
        resp = requests.post(base + "/api/send", headers=headers, timeout=timeout)
    except requests.exceptions.SSLError as e:
        return False, f"TLS error reaching the relay: {e}", None
    except requests.exceptions.RequestException as e:
        return False, f"Could not reach the relay: {e}", None
    if resp.status_code in (401, 403):
        return False, "The relay rejected the API key (HTTP 401). Check that the key matches the one on the relay's Settings page.", None
    # 400 ("Expected a JSON object body") means auth passed — the key is
    # valid. Any non-401 reply also proves the URL is reachable.
    if resp.status_code in (200, 400, 413, 500, 502):
        return (True,
                "Connection OK — the relay is reachable and the API key is valid. "
                "(Update the relay to report its SMTP status here.)",
                None)
    return False, f"The relay returned HTTP {resp.status_code}.", None
