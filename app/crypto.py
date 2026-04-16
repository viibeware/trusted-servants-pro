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
        return ""
