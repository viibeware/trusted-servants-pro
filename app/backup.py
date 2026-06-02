# SPDX-License-Identifier: AGPL-3.0-or-later
"""Daily SQLite snapshot.

Runs once per day at app boot:

  - Source: ``app.config["DB_PATH"]`` (the live SQLite file).
  - Destination: ``<DATA_DIR>/backups/tsp-YYYYMMDD.db``.
  - Method: SQLite's online ``.backup()`` API — produces a consistent
    file even while the live DB is being written to (handles WAL etc.).
  - Retention: keeps the most recent ``RETAIN_DAYS`` (default 14)
    snapshots; older ones are pruned.

If today's snapshot already exists, the function is a no-op so multiple
boots in a single day don't pile up duplicates. Any error is swallowed
so a backup failure never blocks the app from coming up — the failure
is logged and the next boot will retry.
"""
import io
import json
import logging
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

RETAIN_DAYS = 14
SNAPSHOT_PREFIX = "tsp-"
SNAPSHOT_SUFFIX = ".db"

# Prefix used for full off-site backup archives. Distinct from the daily
# .db snapshot prefix so the two never collide in listings.
EXPORT_PREFIX = "tsp-export-"
EXPORT_SUFFIX = ".zip"


def _backup_dir(app):
    data_dir = app.config.get("DATA_DIR") or os.environ.get("TSP_DATA_DIR", "/data")
    backups = Path(data_dir) / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    return backups


def _today_key():
    return datetime.utcnow().strftime("%Y%m%d")


def daily_snapshot(app, retain_days=RETAIN_DAYS):
    """Create today's snapshot if it doesn't yet exist; prune old ones.

    Returns the snapshot Path on success, or None if a snapshot already
    existed (or on failure, which is logged but not raised)."""
    db_path = app.config.get("DB_PATH")
    if not db_path or not os.path.exists(db_path):
        logger.warning("daily_snapshot: source DB %r missing — skipping", db_path)
        return None

    backups = _backup_dir(app)
    target = backups / f"{SNAPSHOT_PREFIX}{_today_key()}{SNAPSHOT_SUFFIX}"

    if target.exists():
        # Prune anyway so an admin who reduces RETAIN_DAYS sees the
        # change apply on the next boot.
        _prune(backups, retain_days)
        return None

    # Use SQLite's online backup API — copies the DB safely even if a
    # concurrent worker is writing. shutil.copy would race with the WAL.
    src_conn = None
    dst_conn = None
    try:
        src_conn = sqlite3.connect(db_path)
        dst_conn = sqlite3.connect(str(target))
        src_conn.backup(dst_conn)
        logger.info("daily_snapshot: wrote %s (%d bytes)",
                    target, target.stat().st_size if target.exists() else 0)
    except Exception as e:  # noqa: BLE001
        logger.error("daily_snapshot: backup failed: %s", e, exc_info=True)
        # Don't leave a partial / corrupt file behind
        try:
            if target.exists():
                target.unlink()
        except OSError:
            pass
        return None
    finally:
        if dst_conn is not None:
            try: dst_conn.close()
            except Exception: pass
        if src_conn is not None:
            try: src_conn.close()
            except Exception: pass

    _prune(backups, retain_days)
    return target


def _prune(backups, retain_days):
    """Delete snapshots older than retain_days. Filenames carry their
    date so the cutoff is computed on filename, not file mtime
    (resilient to manual touch/restore of older files)."""
    cutoff = (datetime.utcnow() - timedelta(days=retain_days)).strftime("%Y%m%d")
    for f in backups.glob(f"{SNAPSHOT_PREFIX}*{SNAPSHOT_SUFFIX}"):
        # Pull the YYYYMMDD chunk between prefix and suffix.
        stem = f.name[len(SNAPSHOT_PREFIX):-len(SNAPSHOT_SUFFIX)]
        if not stem.isdigit() or len(stem) != 8:
            continue
        if stem < cutoff:
            try:
                f.unlink()
                logger.info("daily_snapshot: pruned %s", f.name)
            except OSError as e:
                logger.warning("daily_snapshot: could not prune %s: %s", f.name, e)


def build_export_archive(app):
    """Produce a full app backup archive at a temp path.

    Mirrors the Data tab's manual export: a zip containing tsp.db (via
    SQLite ``VACUUM INTO`` for a consistent snapshot), the uploads/
    directory, the zoom.key Fernet seed (required to decrypt stored
    credentials post-restore), and a manifest.json describing format.

    Returns ``(zip_path: str, archive_name: str, size_bytes: int)``. The
    caller owns the temp file and is responsible for unlinking it. We
    name the file with a UTC timestamp so the same scheduler firing twice
    in a minute still produces distinct names.
    """
    upload_dir = app.config["UPLOAD_FOLDER"]
    data_dir = os.path.dirname(upload_dir.rstrip("/"))
    db_path = app.config.get("DB_PATH") or os.path.join(data_dir, "tsp.db")

    # VACUUM INTO writes a fully-formed copy of the DB regardless of WAL
    # state — same guarantee as the daily .backup() snapshot, but
    # invoked via the SQLAlchemy engine so it works in any request /
    # background context without needing a raw sqlite3 connect.
    # Scratch files (the VACUUM copy and the in-progress zip) go on the
    # data volume, NOT the system temp dir. /tmp is frequently a small
    # tmpfs or a space-constrained container overlay; VACUUM INTO needs
    # roughly the full DB size in free space and fails with "database or
    # disk is full" there. The data dir already holds tsp.db + uploads,
    # so it's guaranteed to have room for a copy. Honour TSP_TMP_DIR as an
    # explicit override for installs that mount a dedicated scratch volume.
    scratch_dir = os.environ.get("TSP_TMP_DIR") or data_dir
    try:
        os.makedirs(scratch_dir, exist_ok=True)
    except OSError:
        scratch_dir = None  # fall back to the system temp dir

    from .models import db as _db
    tmp_db = tempfile.NamedTemporaryFile(prefix="tsp-export-", suffix=".db", dir=scratch_dir, delete=False)
    tmp_db.close()
    os.unlink(tmp_db.name)
    with _db.engine.connect() as conn:
        conn.exec_driver_sql(f"VACUUM INTO '{tmp_db.name}'")

    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    archive_name = f"{EXPORT_PREFIX}{stamp}{EXPORT_SUFFIX}"
    tmp_zip = tempfile.NamedTemporaryFile(prefix="tsp-export-", suffix=".zip", dir=scratch_dir, delete=False)
    tmp_zip.close()

    # Capture context the importer uses to decide whether to scrub
    # domain-bound settings (currently Turnstile) post-restore. ``source_host``
    # is best-effort: only available when the export runs inside a request
    # (manual export from the Data tab); scheduled background exports leave
    # it None and the importer treats missing as "host unknown → scrub".
    src_host = None
    try:
        from flask import request as _req, has_request_context
        if has_request_context():
            src_host = _req.host
    except Exception:  # noqa: BLE001 — manifest field is best-effort context
        src_host = None
    try:
        from .models import SiteSetting as _SS
        _ss = _SS.query.first()
        _turnstile_was_on = bool(_ss and _ss.turnstile_enabled)
    except Exception:  # noqa: BLE001 — same; missing manifest hint is fine
        _turnstile_was_on = False

    manifest = {
        "app": "trusted-servants-pro",
        "format_version": 2,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "source_host": src_host,
        "turnstile_enabled_at_export": _turnstile_was_on,
        "db_filename": "tsp.db",
        "uploads_dir": "uploads/",
        "fernet_key_filename": "zoom.key",
        "note": (
            "Restore by importing through the Data tab, or extract into "
            "the target's data directory (replacing tsp.db, uploads/, and "
            "zoom.key) before first boot. zoom.key is required to decrypt "
            "Zoom credentials. On import to a different host, Turnstile is "
            "auto-disabled — the sitekey is domain-bound and would lock the "
            "admin out at login."
        ),
    }
    zoom_key_path = os.path.join(data_dir, "zoom.key")
    try:
        with zipfile.ZipFile(tmp_zip.name, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            z.write(tmp_db.name, arcname="tsp.db")
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
            if os.path.isfile(zoom_key_path):
                z.write(zoom_key_path, arcname="zoom.key")
            if os.path.isdir(upload_dir):
                for root, _, files in os.walk(upload_dir):
                    for fname in files:
                        full = os.path.join(root, fname)
                        rel = os.path.relpath(full, upload_dir)
                        z.write(full, arcname=os.path.join("uploads", rel))
    finally:
        try:
            os.unlink(tmp_db.name)
        except OSError:
            pass

    size = os.path.getsize(tmp_zip.name)
    return tmp_zip.name, archive_name, size


# Plaintext chunk size for streamed archive encryption. Each chunk becomes
# one independently-authenticated Fernet token, so peak memory is ~chunk +
# its base64 token (a few MB) regardless of total archive size — a 4 GB
# backup encrypts in the same footprint as a 4 MB one.
_ENC_CHUNK = 4 * 1024 * 1024


def encrypt_archive_file(src_path: str, passphrase: str) -> str:
    """Wrap a zip with passphrase-based Fernet encryption, streamed in
    chunks so memory stays flat on multi-hundred-MB / multi-GB archives.

    Derives a Fernet key from the passphrase via PBKDF2-HMAC-SHA256 with a
    fresh 16-byte salt, then writes ``<src>.enc``: a tiny header followed
    by a sequence of length-prefixed Fernet tokens, one per plaintext
    chunk. Returns the new path. Caller unlinks both src and result.

    Format (big-endian length frames):
        offset 0  : 4 bytes  magic   b"TSPB"
        offset 4  : 1 byte   version 0x02  (0x01 = legacy single-token)
        offset 5  : 16 bytes salt
        offset 21 : repeated until EOF:
                      4 bytes  uint32  token length L
                      L bytes  fernet token for one plaintext chunk

    v0x01 archives (whole-file single token) are still readable by
    ``decrypt_archive_file`` so backups taken before this change restore.
    """
    import base64
    import struct
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    if not passphrase:
        raise ValueError("passphrase required for archive encryption")

    salt = os.urandom(16)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480_000)
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
    f = Fernet(key)

    dst_path = src_path + ".enc"
    with open(src_path, "rb") as src, open(dst_path, "wb") as dst:
        dst.write(b"TSPB")
        dst.write(bytes([2]))
        dst.write(salt)
        while True:
            chunk = src.read(_ENC_CHUNK)
            if not chunk:
                break
            token = f.encrypt(chunk)
            dst.write(struct.pack(">I", len(token)))
            dst.write(token)
    return dst_path


def decrypt_archive_file(src_path: str, passphrase: str) -> str:
    """Inverse of ``encrypt_archive_file``. Returns the decrypted temp path.

    Handles both the streamed v0x02 frame format and the legacy v0x01
    single-token format (so archives written before chunked encryption
    still restore)."""
    import base64
    import struct
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    # Stage the decrypted zip next to the source (on the data volume),
    # not /tmp — a full-portal archive can be large and /tmp is often
    # space-constrained. os.environ override mirrors build_export_archive.
    scratch_dir = os.environ.get("TSP_TMP_DIR") or os.path.dirname(os.path.abspath(src_path)) or None

    with open(src_path, "rb") as src:
        magic = src.read(4)
        if magic != b"TSPB":
            raise ValueError("not a TSP encrypted archive (bad magic)")
        version = src.read(1)
        salt = src.read(16)
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480_000)
        key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
        f = Fernet(key)

        tmp = tempfile.NamedTemporaryFile(prefix="tsp-restore-", suffix=".zip",
                                          dir=scratch_dir, delete=False)
        try:
            if version == bytes([2]):
                # Streamed frames: [uint32 len][token] until EOF.
                while True:
                    hdr = src.read(4)
                    if not hdr:
                        break
                    if len(hdr) != 4:
                        raise ValueError("truncated encrypted archive (frame header)")
                    (length,) = struct.unpack(">I", hdr)
                    token = src.read(length)
                    if len(token) != length:
                        raise ValueError("truncated encrypted archive (frame body)")
                    tmp.write(f.decrypt(token))
            elif version == bytes([1]):
                # Legacy single token covering the whole file.
                tmp.write(f.decrypt(src.read()))
            else:
                raise ValueError(f"unsupported archive version {version!r}")
        except InvalidToken as e:
            tmp.close()
            os.unlink(tmp.name)
            raise ValueError("wrong passphrase or corrupt archive") from e
        except Exception:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            raise
        tmp.close()
    return tmp.name


def list_snapshots(app):
    """Return a list of (Path, datetime, size_bytes) tuples for the
    snapshots currently on disk, newest first."""
    backups = _backup_dir(app)
    out = []
    for f in backups.glob(f"{SNAPSHOT_PREFIX}*{SNAPSHOT_SUFFIX}"):
        stem = f.name[len(SNAPSHOT_PREFIX):-len(SNAPSHOT_SUFFIX)]
        if not stem.isdigit() or len(stem) != 8:
            continue
        try:
            dt = datetime.strptime(stem, "%Y%m%d")
        except ValueError:
            continue
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        out.append((f, dt, size))
    out.sort(key=lambda x: x[1], reverse=True)
    return out
