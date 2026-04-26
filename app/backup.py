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
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

RETAIN_DAYS = 14
SNAPSHOT_PREFIX = "tsp-"
SNAPSHOT_SUFFIX = ".db"


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
