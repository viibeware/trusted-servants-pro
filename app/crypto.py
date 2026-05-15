# SPDX-License-Identifier: AGPL-3.0-or-later
import os
from cryptography.fernet import Fernet
from flask import current_app


def _key_path(app):
    return os.path.join(os.path.dirname(app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")),
                        "zoom.key")


def init_fernet(app):
    key = os.environ.get("TSP_FERNET_KEY")
    if not key:
        data_dir = os.path.dirname(app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", ""))
        path = os.path.join(data_dir, "zoom.key")
        if os.path.exists(path):
            with open(path, "rb") as f:
                key = f.read().decode()
        else:
            key = Fernet.generate_key().decode()
            with open(path, "wb") as f:
                f.write(key.encode())
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
    app.config["FERNET"] = Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str) -> bytes:
    return current_app.config["FERNET"].encrypt((value or "").encode())


def decrypt(token: bytes) -> str:
    if not token:
        return ""
    try:
        return current_app.config["FERNET"].decrypt(token).decode()
    except Exception:
        # Fernet decrypt fails when (a) the token was signed with a
        # different key (TSP_SECRET_KEY rotation or zoom.key replaced),
        # or (b) the token is corrupted. Returning "" silently means
        # the admin sees a previously-set Zoom / OTP password just
        # vanish from the UI with no clue why. Log a warning so the
        # mismatch surfaces in container logs and admins can diagnose.
        # We deliberately do not log the token bytes (could include
        # short-prefix hints about which row failed) — just enough to
        # know the failure happened. Never raise: callers expect a
        # string and a partial DB read would otherwise crash the
        # request.
        try:
            current_app.logger.warning(
                "Fernet decrypt failed — encrypted column unreadable. "
                "Most likely cause: TSP_SECRET_KEY or zoom.key was rotated "
                "after this value was stored. Re-enter the affected "
                "credential to re-encrypt under the current key."
            )
        except Exception:
            pass
        return ""
