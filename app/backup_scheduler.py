# SPDX-License-Identifier: AGPL-3.0-or-later
"""Off-site backup scheduler.

A single daemon thread checks ``BackupTarget.next_run_at`` once a
minute and fires due jobs. Because gunicorn runs multiple workers,
the loop is gated by an exclusive flock on a file in the data
directory — only one worker actually drives the scheduler at a time;
the others sleep harmlessly. If the worker holding the lock dies,
the OS releases the flock and a sibling picks it up on its next tick.

This module owns three responsibilities:

  1. ``run_target(app, target_id, triggered_by)`` — synchronous full
     run: build archive, encrypt if configured, upload, prune remote,
     write BackupRun, update target's status mirror, fire SMTP alert
     on ok→failed transition. Used by the scheduler and by the
     manual "Run now" route.

  2. ``compute_next_run(cron_expr, base)`` — pure helper around
     croniter so the route handlers can compute next_run_at after a
     schedule edit without depending on scheduler state.

  3. ``start_scheduler(app)`` — boot-time entry; spawns the daemon
     thread (no-op if the lock is held). Safe to call multiple times.

Failures during a run are caught and recorded; they never raise out
of run_target. The scheduler itself logs and continues — one busted
target can't stop the others.
"""
import errno
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Tick interval. One minute matches the resolution of standard cron
# expressions; shorter would burn CPU for no benefit.
TICK_SECONDS = 60

# Re-entrant attempt cooldown after a failed run — don't retry the same
# target immediately, give a 10-minute window for transient network /
# remote-auth issues to clear.
RETRY_COOLDOWN_SECONDS = 10 * 60


def _lock_path(app):
    data_dir = app.config.get("DATA_DIR") or os.environ.get("TSP_DATA_DIR", "/data")
    return Path(data_dir) / ".backup-scheduler.lock"


def _try_acquire_lock(path):
    """Open + non-blocking flock. Returns the open file handle on
    success, None if another process already holds the lock.

    The handle must be kept open for the lifetime of the holder — when
    it's garbage-collected the lock releases. We stash it on the thread
    so it survives.
    """
    import fcntl
    fh = open(path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        fh.close()
        if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
            return None
        raise
    fh.write(f"{os.getpid()}\n")
    fh.flush()
    return fh


def compute_next_run(cron_expr, base=None):
    """Return the next datetime ``cron_expr`` fires after ``base`` (UTC).

    Falls back to base+1d if the expression is unparseable so a bad
    schedule never wedges the scheduler — the row will still appear in
    the UI as failing-to-parse via the wizard's validator.

    Cron is interpreted in the **site's configured timezone**, not
    UTC, so the operator who types ``0 3 * * *`` gets 3 AM local
    (matching what they see in the UI and the wall clock), not 3 AM
    UTC. We attach the site's zone to the base, hand the aware
    datetime to croniter, then strip the tz so the returned value
    stays naive-UTC — the storage convention every other backup
    column uses. Falls back to UTC interpretation when the site row
    can't be loaded (test fixtures, scheduler-before-app-context, etc.)
    so a missing SiteSetting never breaks the scheduler.
    """
    from datetime import timezone as _tz
    base = base or datetime.utcnow()
    try:
        from .models import SiteSetting as _SS
        from .timezone import site_timezone as _stz
        from flask import has_app_context
        local_tz = _tz.utc
        if has_app_context():
            try:
                local_tz = _stz(_SS.query.first())
            except Exception:  # noqa: BLE001 — DB hiccup → fall back to UTC
                local_tz = _tz.utc
        base_aware = base.replace(tzinfo=_tz.utc).astimezone(local_tz)
        from croniter import croniter
        it = croniter(cron_expr, base_aware)
        nxt_local = it.get_next(datetime)
        # croniter preserves the tzinfo it was given; convert back to
        # UTC and strip so the stored next_run_at is naive-UTC.
        if nxt_local.tzinfo is None:
            nxt_local = nxt_local.replace(tzinfo=local_tz)
        return nxt_local.astimezone(_tz.utc).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        logger.warning("compute_next_run: bad cron %r — defaulting to +1d", cron_expr)
        return base + timedelta(days=1)


def _send_failure_email(app, target, error):
    """Notify the admin via SMTP if configured.

    Fires on ok→failed transition only (caller checks). Best-effort —
    swallow exceptions so a broken SMTP doesn't compound the backup
    failure into an outage.
    """
    try:
        from . import mail
        from .models import SiteSetting, User
        ss = SiteSetting.query.first()
        if not ss or not getattr(ss, "smtp_host", None):
            return
        admin_emails = [u.email for u in User.query.filter_by(role="admin").all() if u.email]
        if not admin_emails:
            return
        subject = f"[TSP] Backup failed: {target.name}"
        body = (
            f"The scheduled backup target '{target.name}' ({target.kind}) "
            f"failed at {datetime.utcnow().isoformat()}Z.\n\n"
            f"Error: {error}\n\n"
            f"Open Settings → Data → Backups in the app for details."
        )
        ok, err = mail.send_mail(ss, admin_emails, subject, body)
        if not ok:
            logger.warning("failure email not sent: %s", err)
    except Exception:
        logger.exception("failure-email path errored")


def run_target(app, target_id, triggered_by="schedule"):
    """Execute one backup. Returns the BackupRun row (committed)."""
    from .models import db, BackupTarget, BackupRun
    from .backup import build_export_archive, encrypt_archive_file
    from .backup_backends import make_backend, BackendError
    from .crypto import decrypt

    with app.app_context():
        target = db.session.get(BackupTarget, target_id)
        if target is None:
            logger.warning("run_target: target %d disappeared", target_id)
            return None

        run = BackupRun(
            target_id=target.id,
            started_at=datetime.utcnow(),
            status="running",
            triggered_by=triggered_by,
        )
        db.session.add(run)
        previous_status = target.last_status
        target.last_status = "running"
        db.session.commit()

        archive_path = None
        encrypted_path = None
        try:
            archive_path, archive_name, _size = build_export_archive(app)

            upload_path = archive_path
            if target.encrypt_archive and target.archive_passphrase_enc:
                passphrase = decrypt(target.archive_passphrase_enc)
                if not passphrase:
                    raise RuntimeError("archive encryption configured but passphrase is unreadable")
                encrypted_path = encrypt_archive_file(archive_path, passphrase)
                upload_path = encrypted_path
                archive_name = archive_name + ".enc"

            backend = make_backend(target)
            backend.open()
            try:
                backend.put(upload_path, archive_name)
                # Prune remote retention only after a successful put so
                # a botched upload can't take out the prior good copy.
                remotes = backend.list()
                if target.retain_count and len(remotes) > target.retain_count:
                    for rf in remotes[target.retain_count:]:
                        try:
                            backend.delete(rf.name)
                        except BackendError as e:
                            logger.warning("prune failed for %s: %s", rf.name, e)
            finally:
                backend.close()

            run.status = "ok"
            run.archive_name = archive_name
            run.bytes_uploaded = os.path.getsize(upload_path)
            run.finished_at = datetime.utcnow()
            target.last_status = "ok"
            target.last_error = None
            target.last_run_at = run.finished_at
            target.next_run_at = compute_next_run(target.schedule_cron, run.finished_at)
            db.session.commit()
            logger.info("backup target %d (%s) ok: %s (%d bytes)",
                        target.id, target.name, archive_name, run.bytes_uploaded or 0)
        except Exception as e:  # noqa: BLE001
            db.session.rollback()
            # Re-fetch target after the rollback so we can write the
            # failure row in a clean session state.
            target = db.session.get(BackupTarget, target_id)
            run = db.session.get(BackupRun, run.id) if run.id else None
            if run is None:
                run = BackupRun(
                    target_id=target.id,
                    started_at=datetime.utcnow(),
                    status="failed",
                    triggered_by=triggered_by,
                    error_message=str(e),
                    finished_at=datetime.utcnow(),
                )
                db.session.add(run)
            else:
                run.status = "failed"
                run.error_message = str(e)
                run.finished_at = datetime.utcnow()
            target.last_status = "failed"
            target.last_error = str(e)
            target.last_run_at = run.finished_at
            # Push next attempt out so we don't tight-loop on a broken
            # target; the scheduled cron still wins if it fires sooner.
            target.next_run_at = max(
                compute_next_run(target.schedule_cron),
                datetime.utcnow() + timedelta(seconds=RETRY_COOLDOWN_SECONDS),
            )
            db.session.commit()
            logger.error("backup target %d (%s) failed: %s",
                         target.id, target.name, e)
            if previous_status == "ok":
                _send_failure_email(app, target, e)
        finally:
            for p in (archive_path, encrypted_path):
                if p and os.path.exists(p):
                    try: os.unlink(p)
                    except OSError: pass

        return run


def _scheduler_loop(app, lock_handle):
    """Tick loop. Hold the lock for the life of the loop."""
    from .models import db, BackupTarget
    logger.info("backup scheduler started (pid=%d)", os.getpid())
    while True:
        try:
            with app.app_context():
                now = datetime.utcnow()
                due = (BackupTarget.query
                       .filter(BackupTarget.enabled.is_(True))
                       .filter(BackupTarget.next_run_at.isnot(None))
                       .filter(BackupTarget.next_run_at <= now)
                       .all())
                for t in due:
                    try:
                        run_target(app, t.id, triggered_by="schedule")
                    except Exception:
                        logger.exception("scheduler: unhandled error running target %d", t.id)
        except Exception:
            logger.exception("scheduler tick errored — continuing")
        time.sleep(TICK_SECONDS)


def start_scheduler(app):
    """Spawn the scheduler thread if we win the flock.

    Idempotent: re-entering returns the same thread (or None if another
    worker holds the lock). Sets ``next_run_at`` for any target that
    has none yet so newly-created targets land in the next tick.
    """
    if app.config.get("_BACKUP_SCHEDULER_STARTED"):
        return None
    lock_path = _lock_path(app)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = _try_acquire_lock(lock_path)
    if handle is None:
        logger.info("backup scheduler: lock held by another worker, idle")
        app.config["_BACKUP_SCHEDULER_STARTED"] = True
        return None

    # Seed next_run_at for targets that have none (rows just created,
    # or rows from an upgrade prior to this feature).
    try:
        from .models import db, BackupTarget
        with app.app_context():
            dirty = False
            for t in BackupTarget.query.filter_by(enabled=True).all():
                if t.next_run_at is None:
                    t.next_run_at = compute_next_run(t.schedule_cron)
                    dirty = True
            if dirty:
                db.session.commit()
    except Exception:
        logger.exception("backup scheduler: failed to seed next_run_at")

    t = threading.Thread(target=_scheduler_loop, args=(app, handle),
                         name="backup-scheduler", daemon=True)
    t.start()
    app.config["_BACKUP_SCHEDULER_STARTED"] = True
    app.config["_BACKUP_SCHEDULER_LOCK"] = handle  # keep it alive
    return t
