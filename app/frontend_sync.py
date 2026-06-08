# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frontend staging sync — outbound client.

The inbound side (the API a peer calls) lives in ``routes.py`` on the
``frontend_sync_bp`` blueprint. This module is the *driving* half: when an
admin clicks **Pull from peer** or **Push to peer**, these helpers reach
across to the configured sibling install's API and move the scoped
frontend bundle (presentation + page-builder Pages + assets — never
Stories, users, meetings, or libraries).

Pairing is a single shared secret stored on ``FrontendSyncPeer`` (see
``models.py``); the same token lives on both installs and authenticates
traffic in both directions. We send it in the ``X-Frontend-Sync-Token``
header, mirroring the remote-restore client style in
``backup_backends.py``.

All functions run inside an app context (they read config, hit the DB, and
write files) and raise :class:`FrontendSyncError` with a friendly message
on any failure so the admin routes can flash it directly.
"""
import os
import tempfile

import requests
from flask import current_app

# Network timeouts: (connect, read). The read leg is generous because a
# bundle with fonts / hero images can take a moment to build and stream.
_TIMEOUT = (10, 180)
_TOKEN_HEADER = "X-Frontend-Sync-Token"


class FrontendSyncError(Exception):
    """A sync attempt failed; the message is safe to show an admin."""


def _endpoint(peer, path):
    """Absolute URL for one of the peer's frontend-sync endpoints."""
    base = (peer.base_url or "").strip().rstrip("/")
    if not base:
        raise FrontendSyncError("No peer base URL configured.")
    if not (base.startswith("http://") or base.startswith("https://")):
        raise FrontendSyncError("Peer base URL must start with http:// or https://")
    return f"{base}/api/v1/frontend-sync/{path}"


def _headers(peer):
    token = peer.token
    if not token:
        raise FrontendSyncError("No shared sync token configured.")
    return {_TOKEN_HEADER: token}


def _friendly_request_error(exc):
    if isinstance(exc, requests.exceptions.SSLError):
        return "TLS/SSL error reaching the peer (check the certificate or use http:// for a trusted LAN)."
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "Timed out connecting to the peer."
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return "The peer took too long to respond."
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "Could not reach the peer (connection refused or host unreachable)."
    return f"Request to the peer failed: {exc}"


def _error_from_response(resp):
    """Pull the server's JSON ``error`` out of a non-2xx response, with a
    sensible fallback per status code."""
    detail = ""
    try:
        body = resp.json()
        if isinstance(body, dict):
            detail = body.get("error") or ""
    except ValueError:
        pass
    if resp.status_code == 401:
        return detail or "Peer rejected the token (check it matches, and that the peer has inbound sync enabled)."
    if resp.status_code == 429:
        return detail or "Peer is rate-limiting sync attempts; try again in a few minutes."
    if resp.status_code == 404:
        return "Peer does not expose the frontend-sync API (is it running this version?)."
    return detail or f"Peer returned HTTP {resp.status_code}."


def ping(peer):
    """Probe the peer for reachability + identity. Returns the parsed JSON
    (``{ok, app, version, format_version, name}``) or raises."""
    try:
        resp = requests.get(_endpoint(peer, "ping"), headers=_headers(peer), timeout=_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        raise FrontendSyncError(_friendly_request_error(exc))
    if resp.status_code != 200:
        raise FrontendSyncError(_error_from_response(resp))
    try:
        data = resp.json()
    except ValueError:
        raise FrontendSyncError("Peer responded but not with JSON — is the URL the portal root?")
    if data.get("app") != "trusted-servants-pro":
        raise FrontendSyncError("That URL does not look like a Trusted Servants Pro install.")
    return data


def pull_from_peer(peer):
    """Download the peer's scoped frontend bundle and apply it locally.
    Snapshots our current frontend first (rollback point). Returns
    ``(summary, snapshot_name)``."""
    from datetime import datetime
    from .routes import _import_frontend_bundle_zip, _frontend_sync_snapshot
    from .models import db

    upload_dir = current_app.config["UPLOAD_FOLDER"]
    data_dir = os.path.dirname(upload_dir.rstrip("/"))
    fd, zip_path = tempfile.mkstemp(prefix="tsp-fe-pull-", suffix=".zip", dir=data_dir)
    os.close(fd)
    try:
        try:
            with requests.get(_endpoint(peer, "pull"), headers=_headers(peer),
                              timeout=_TIMEOUT, stream=True) as resp:
                if resp.status_code != 200:
                    raise FrontendSyncError(_error_from_response(resp))
                with open(zip_path, "wb") as out:
                    for block in resp.iter_content(chunk_size=1024 * 1024):
                        if block:
                            out.write(block)
        except requests.exceptions.RequestException as exc:
            raise FrontendSyncError(_friendly_request_error(exc))

        # Rollback point before we overwrite our own frontend.
        snapshot = _frontend_sync_snapshot()
        ok, result = _import_frontend_bundle_zip(zip_path)
        if not ok:
            raise FrontendSyncError(result)
        peer.last_pulled_at = datetime.utcnow()
        db.session.commit()
        return result, snapshot
    finally:
        try: os.unlink(zip_path)
        except OSError: pass


def push_to_peer(peer):
    """Build our scoped frontend bundle and push it to the peer, which
    snapshots + applies it. Returns the peer's applied-summary dict (with a
    ``snapshot`` key naming the rollback bundle it saved)."""
    from datetime import datetime
    from .routes import _write_frontend_bundle_zip
    from .models import db

    upload_dir = current_app.config["UPLOAD_FOLDER"]
    data_dir = os.path.dirname(upload_dir.rstrip("/"))
    fd, zip_path = tempfile.mkstemp(prefix="tsp-fe-push-", suffix=".zip", dir=data_dir)
    os.close(fd)
    try:
        _write_frontend_bundle_zip(zip_path, include_stories=False)
        try:
            with open(zip_path, "rb") as fh:
                resp = requests.post(
                    _endpoint(peer, "push"), headers=_headers(peer),
                    files={"archive": ("frontend-sync.zip", fh, "application/zip")},
                    timeout=_TIMEOUT)
        except requests.exceptions.RequestException as exc:
            raise FrontendSyncError(_friendly_request_error(exc))
        if resp.status_code != 200:
            raise FrontendSyncError(_error_from_response(resp))
        try:
            data = resp.json()
        except ValueError:
            raise FrontendSyncError("Peer applied the bundle but returned an unreadable response.")
        if not data.get("ok"):
            raise FrontendSyncError(data.get("error") or "Peer rejected the bundle.")
        peer.last_pushed_at = datetime.utcnow()
        db.session.commit()
        result = data.get("applied") or {}
        result["snapshot"] = data.get("snapshot")
        return result
    finally:
        try: os.unlink(zip_path)
        except OSError: pass
