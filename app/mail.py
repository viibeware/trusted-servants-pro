import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr


def _recipients(raw):
    if not raw:
        return []
    return [r.strip() for r in str(raw).replace(";", ",").split(",") if r.strip()]


def send_mail(site, to, subject, body_text, body_html=None):
    """Send a plain-text (optionally HTML) email using SMTP settings on SiteSetting.

    Returns (ok: bool, error: str|None).
    """
    if not site or not site.smtp_host or not site.smtp_from_email:
        return False, "SMTP is not configured"

    recipients = to if isinstance(to, list) else _recipients(to)
    if not recipients:
        return False, "No recipients"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((site.smtp_from_name or "", site.smtp_from_email))
    msg["To"] = ", ".join(recipients)
    msg.set_content(body_text or "")
    if body_html:
        msg.add_alternative(body_html, subtype="html")

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
