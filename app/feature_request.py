# SPDX-License-Identifier: AGPL-3.0-or-later
"""Visitor feature-request widget for the product marketing site + docs.

The live demo runs from a per-session, throwaway database, so the usual
admin-configured SMTP settings (Settings → Email) don't apply here — there's no
durable place to store them. This module instead reads SMTP and Cloudflare
Turnstile configuration from **environment variables** so the marketing site can
deliver feature requests by email without any DB state.

Enable it by setting (at minimum) ``TSP_SMTP_HOST``, ``TSP_SMTP_FROM_EMAIL`` and
``TSP_FEATURE_REQUEST_TO``. When those are present the floating "Feature request"
button appears; otherwise the widget stays hidden. Turnstile is optional and
turns on by setting ``TSP_TURNSTILE_SITE_KEY`` (+ ``TSP_TURNSTILE_SECRET_KEY``
for server-side verification).

Environment variables
  TSP_SMTP_HOST            SMTP server hostname.
  TSP_SMTP_PORT            Port (default 465 for ssl, else 587).
  TSP_SMTP_USERNAME        SMTP auth username (optional).
  TSP_SMTP_PASSWORD        SMTP auth password (optional; plaintext, not stored).
  TSP_SMTP_FROM_EMAIL      Envelope/From address.
  TSP_SMTP_FROM_NAME       From display name (default "Trusted Servants Pro").
  TSP_SMTP_SECURITY        none | starttls | ssl  (default starttls).
  TSP_FEATURE_REQUEST_TO   Comma-separated recipient list for requests.
  TSP_TURNSTILE_SITE_KEY   Cloudflare Turnstile site key (shows the widget).
  TSP_TURNSTILE_SECRET_KEY Cloudflare Turnstile secret (enables verification).
"""
import os
import re
import ssl
import time
import smtplib
import logging
from threading import Lock
from email.message import EmailMessage
from email.utils import formataddr

import requests
from flask import Blueprint, request, jsonify, current_app

log = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Length caps — defensive, also keep the email readable.
_MAX = {"name": 120, "email": 200, "phone": 40, "feature": 5000}

# Lightweight per-IP rate limit (per worker; Turnstile is the real gate).
_RL_WINDOW = 600          # seconds
_RL_MAX = 5               # submissions per window per IP
_rl_hits = {}
_rl_lock = Lock()

bp = Blueprint("feature_request", __name__)


def _env(name, default=""):
    return (os.environ.get(name, default) or "").strip()


def _recipients(raw):
    if not raw:
        return []
    return [r.strip() for r in str(raw).replace(";", ",").split(",") if r.strip()]


def get_config():
    """Read the current SMTP + Turnstile config from the environment."""
    recipients = _recipients(_env("TSP_FEATURE_REQUEST_TO"))
    cfg = {
        "smtp_host": _env("TSP_SMTP_HOST"),
        "smtp_port": _env("TSP_SMTP_PORT"),
        "smtp_username": _env("TSP_SMTP_USERNAME"),
        # Don't strip passwords — leading/trailing spaces can be significant.
        "smtp_password": os.environ.get("TSP_SMTP_PASSWORD", ""),
        "smtp_from_email": _env("TSP_SMTP_FROM_EMAIL"),
        "smtp_from_name": _env("TSP_SMTP_FROM_NAME") or "Trusted Servants Pro",
        "smtp_security": (_env("TSP_SMTP_SECURITY") or "starttls").lower(),
        "recipients": recipients,
        "ts_sitekey": _env("TSP_TURNSTILE_SITE_KEY"),
        "ts_secret": _env("TSP_TURNSTILE_SECRET_KEY"),
    }
    cfg["enabled"] = bool(cfg["smtp_host"] and cfg["smtp_from_email"] and recipients)
    return cfg


def _rate_limited(ip):
    if not ip:
        return False
    now = time.time()
    with _rl_lock:
        hits = [t for t in _rl_hits.get(ip, []) if now - t < _RL_WINDOW]
        _rl_hits[ip] = hits
        return len(hits) >= _RL_MAX


def _record_hit(ip):
    if not ip:
        return
    with _rl_lock:
        _rl_hits.setdefault(ip, []).append(time.time())


def _verify_turnstile(secret, token, remote_ip):
    """Returns (ok, error). Fails closed on any error."""
    if not token:
        return False, "Please complete the security check."
    try:
        resp = requests.post(
            TURNSTILE_VERIFY_URL,
            data={"secret": secret, "response": token, "remoteip": remote_ip or ""},
            timeout=5,
        )
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("Turnstile verify failed: %s", exc)
        return False, "Security check failed — please try again."
    if data.get("success"):
        return True, None
    return False, "Security check failed — please try again."


def _send(cfg, name, email, phone, feature):
    """Send the feature request by email. Returns (ok, error)."""
    lines = [
        "New feature request from the Trusted Servants Pro website.",
        "",
        f"Name:    {name or '—'}",
        f"Email:   {email or '—'}",
        f"Phone:   {phone or '—'}",
        "",
        "Feature request:",
        feature,
    ]
    body = "\n".join(lines)

    msg = EmailMessage()
    msg["Subject"] = "New feature request — Trusted Servants Pro"
    msg["From"] = formataddr((cfg["smtp_from_name"], cfg["smtp_from_email"]))
    msg["To"] = ", ".join(cfg["recipients"])
    if email and _EMAIL_RE.match(email):
        msg["Reply-To"] = formataddr((name or "", email))
    msg.set_content(body)

    host = cfg["smtp_host"]
    security = cfg["smtp_security"]
    try:
        port = int(cfg["smtp_port"]) if cfg["smtp_port"] else (465 if security == "ssl" else 587)
    except ValueError:
        port = 465 if security == "ssl" else 587

    user, password = cfg["smtp_username"], cfg["smtp_password"]
    try:
        if security == "ssl":
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=20, context=ctx) as s:
                if user:
                    s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.ehlo()
                if security == "starttls":
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                if user:
                    s.login(user, password)
                s.send_message(msg)
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


@bp.route("/feature-request", methods=["POST"])
def submit():
    cfg = get_config()
    if not cfg["enabled"]:
        return jsonify(ok=False, error="Feature requests aren't configured on this site."), 503

    ip = request.remote_addr or ""
    if _rate_limited(ip):
        return jsonify(ok=False, error="Too many requests — please try again later."), 429

    f = request.form
    # Honeypot: bots fill hidden fields. Pretend success, drop silently.
    if (f.get("company") or "").strip():
        return jsonify(ok=True)

    feature = (f.get("feature") or "").strip()
    if not feature:
        return jsonify(ok=False, error="Please describe the feature you'd like to see."), 400
    feature = feature[:_MAX["feature"]]

    name = (f.get("name") or "").strip()[:_MAX["name"]]
    email = (f.get("email") or "").strip()[:_MAX["email"]]
    phone = (f.get("phone") or "").strip()[:_MAX["phone"]]
    if email and not _EMAIL_RE.match(email):
        return jsonify(ok=False, error="That email address doesn't look right."), 400

    # Turnstile, when configured.
    if cfg["ts_sitekey"]:
        if cfg["ts_secret"]:
            ok, err = _verify_turnstile(cfg["ts_secret"],
                                        f.get("cf-turnstile-response", ""), ip)
            if not ok:
                return jsonify(ok=False, error=err), 400
        else:
            log.warning("TSP_TURNSTILE_SITE_KEY set but TSP_TURNSTILE_SECRET_KEY "
                        "missing — skipping server-side verification.")

    ok, err = _send(cfg, name, email, phone, feature)
    if not ok:
        log.error("Feature request email failed: %s", err)
        return jsonify(ok=False, error="Sorry, we couldn't send that right now. Please try again later."), 502

    _record_hit(ip)
    return jsonify(ok=True)


def register(app):
    """Mount the route and expose template globals. Called from product.register."""
    app.register_blueprint(bp)
    cfg = get_config()
    app.jinja_env.globals["feature_request_enabled"] = cfg["enabled"]
    app.jinja_env.globals["feature_request_turnstile_sitekey"] = cfg["ts_sitekey"]
