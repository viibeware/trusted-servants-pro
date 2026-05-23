# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ephemeral per-session demo mode for TSP Pro.

When ``TSP_DEMO_MODE`` is set, every browser session gets its own private copy
of the SQLite database and uploads directory, lazily copied from a read-only
"golden" seed. Anything a visitor changes (editing meetings, flipping settings,
uploading files, …) lands only in their session copy and is swept away once the
session goes idle — so every visitor sees the same fresh state and nothing they
do persists globally.

How it works
------------
* A SQLAlchemy ``creator`` + ``NullPool`` route each DB connection to the file
  named by a thread-local "current session DB path". With **no request context**
  (app boot: ``create_all`` / ``_migrate_sqlite`` / the ``_seed_*`` helpers /
  ``seed_demo_data``) the creator targets the golden DB, so boot builds the
  golden state. ``NullPool`` gives one fresh connection per request, closed on
  app-context teardown, so concurrent sessions never share a handle.
* A :class:`DemoConfig` (a ``flask.Config`` subclass) redirects
  ``config["UPLOAD_FOLDER"]`` / ``config["DB_PATH"]`` to the per-session paths
  while a demo request is in flight, and to the golden paths otherwise. Every
  upload read/write in the app goes through ``current_app.config["UPLOAD_FOLDER"]``,
  so this single override covers all call sites.
* A ``before_request`` hook provisions the session DB (copy-on-first-touch) and
  uploads dir (symlink-farmed from golden so seeded images resolve), and stamps
  the thread-local. A throttled janitor reclaims idle sessions.

This module is inert unless :func:`configure` + :func:`install` are called, which
``app/__init__.py`` only does when ``TSP_DEMO_MODE`` is truthy.
"""
import os
import shutil
import sqlite3
import threading
import time
import uuid

from flask import Config, has_request_context, request, session
from sqlalchemy.pool import NullPool

# ── Module state (set by configure()) ──────────────────────────────────────
GOLDEN_DB_PATH = None        # the seeded, read-at-runtime canonical DB
GOLDEN_UPLOAD_DIR = None      # the seeded canonical uploads dir
SESSIONS_DIR = None           # per-session DB files live here
SESSION_UPLOADS_DIR = None    # per-session upload dirs live here
DATA_DIR = None

# Thread-local pointing at the SQLite file + uploads dir the current request
# should use. Unset / None ⇒ golden (boot + any background work).
_local = threading.local()

# A session is reclaimed by the janitor once its DB file goes untouched for
# this long. Overridable via TSP_DEMO_SESSION_TTL_MIN.
SESSION_TTL = 90 * 60
_JANITOR_INTERVAL = 60.0      # at most one sweep per minute
_last_janitor = 0.0
_janitor_lock = threading.Lock()


# ── Connection routing ─────────────────────────────────────────────────────
def _current_db_path():
    return getattr(_local, "db_path", None) or GOLDEN_DB_PATH


def _current_upload_dir():
    return getattr(_local, "upload_dir", None) or GOLDEN_UPLOAD_DIR


def _demo_connect():
    """SQLAlchemy ``creator``: open the SQLite file for the current context.

    ``check_same_thread=False`` mirrors SQLAlchemy's pysqlite default; with
    ``NullPool`` each request gets its own short-lived connection so there's no
    cross-thread/cross-session sharing.
    """
    return sqlite3.connect(_current_db_path(), check_same_thread=False)


# ── Context-aware config ───────────────────────────────────────────────────
def _ctx_path(key):
    """Per-session path for ``key`` when a demo request is active, else None."""
    if not has_request_context():
        return None
    if getattr(_local, "db_path", None) is None:
        return None
    if key == "UPLOAD_FOLDER":
        return getattr(_local, "upload_dir", None)
    if key == "DB_PATH":
        return getattr(_local, "db_path", None)
    return None


class DemoConfig(Config):
    """Config that redirects per-session paths during a demo request.

    Only ``UPLOAD_FOLDER`` and ``DB_PATH`` are context-sensitive. ``DATA_DIR`` is
    deliberately left alone — it must always resolve to the shared golden data
    dir (some maintenance code falls back to ``$TSP_DATA_DIR`` if it's None).
    """

    _CTX_KEYS = ("UPLOAD_FOLDER", "DB_PATH")

    def __getitem__(self, key):
        if key in self._CTX_KEYS:
            v = _ctx_path(key)
            if v is not None:
                return v
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key in self._CTX_KEYS:
            v = _ctx_path(key)
            if v is not None:
                return v
        return super().get(key, default)


# ── Session provisioning ───────────────────────────────────────────────────
def _session_db_path(sid):
    return os.path.join(SESSIONS_DIR, sid + ".db")


def _session_upload_dir(sid):
    return os.path.join(SESSION_UPLOADS_DIR, sid)


def _provision(sid):
    """Create a fresh per-session DB (copy of golden) + uploads dir
    (symlink-farmed from golden). Idempotent for the upload dir; the DB is only
    copied when missing so an in-flight session keeps its edits."""
    db_path = _session_db_path(sid)
    up_dir = _session_upload_dir(sid)
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    os.makedirs(up_dir, exist_ok=True)
    if not os.path.exists(db_path) and GOLDEN_DB_PATH and os.path.exists(GOLDEN_DB_PATH):
        tmp = db_path + ".tmp-" + uuid.uuid4().hex[:8]
        shutil.copyfile(GOLDEN_DB_PATH, tmp)
        os.replace(tmp, db_path)  # atomic publish
    _farm_uploads(up_dir)
    return db_path, up_dir


def _farm_uploads(up_dir):
    """Symlink each golden upload into the session upload dir so seeded images
    resolve, while new uploads written here stay private. Falls back to copying
    when symlinks aren't available (e.g. some bind mounts)."""
    if not (GOLDEN_UPLOAD_DIR and os.path.isdir(GOLDEN_UPLOAD_DIR)):
        return
    try:
        names = os.listdir(GOLDEN_UPLOAD_DIR)
    except OSError:
        return
    for name in names:
        src = os.path.join(GOLDEN_UPLOAD_DIR, name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(up_dir, name)
        if os.path.lexists(dst):
            continue
        try:
            os.symlink(os.path.abspath(src), dst)
        except OSError:
            try:
                shutil.copyfile(src, dst)
            except OSError:
                pass


def _purge(sid):
    """Delete a session's DB (+ sidecar journals) and uploads dir."""
    db_path = _session_db_path(sid)
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(db_path + suffix)
        except OSError:
            pass
    shutil.rmtree(_session_upload_dir(sid), ignore_errors=True)


# ── Janitor ────────────────────────────────────────────────────────────────
def _maybe_janitor():
    global _last_janitor
    now = time.time()
    if now - _last_janitor < _JANITOR_INTERVAL:
        return
    if not _janitor_lock.acquire(blocking=False):
        return
    try:
        _last_janitor = now
        cutoff = now - SESSION_TTL
        if not os.path.isdir(SESSIONS_DIR):
            return
        for fn in os.listdir(SESSIONS_DIR):
            if not fn.endswith(".db"):
                continue
            full = os.path.join(SESSIONS_DIR, fn)
            try:
                if os.path.getmtime(full) < cutoff:
                    _purge(fn[:-3])
            except OSError:
                continue
    finally:
        _janitor_lock.release()


# ── Request hooks ──────────────────────────────────────────────────────────
def _before_request():
    path = request.path or ""
    sid = session.get("demo_sid")
    if not sid:
        # Don't spin up a session for visitors who are only on the product
        # marketing pages, the docs, or the feature-request endpoint (none of
        # which touch the DB) — serve those from golden. Entering the demo at
        # /demo (or any deeper app URL) is what creates the private session.
        if (path.startswith("/static/") or path.startswith("/docs")
                or path in ("/", "/welcome", "/favicon.ico", "/feature-request")):
            _local.db_path = GOLDEN_DB_PATH
            _local.upload_dir = GOLDEN_UPLOAD_DIR
            return None
        sid = uuid.uuid4().hex
        session["demo_sid"] = sid
        session.permanent = True

    db_path = _session_db_path(sid)
    if not os.path.exists(db_path):
        db_path, up_dir = _provision(sid)
    else:
        up_dir = _session_upload_dir(sid)
        os.makedirs(up_dir, exist_ok=True)
        try:
            os.utime(db_path, None)  # keep the session alive against the TTL
        except OSError:
            pass

    _local.db_path = db_path
    _local.upload_dir = up_dir
    _maybe_janitor()
    return None


def _teardown(_exc=None):
    _local.db_path = None
    _local.upload_dir = None


# ── Public helpers ─────────────────────────────────────────────────────────
def reset_session():
    """Wipe the caller's session DB + uploads and rotate the sid. The next
    request re-provisions a clean copy from golden."""
    sid = session.get("demo_sid")
    if sid:
        _purge(sid)
    session["demo_sid"] = uuid.uuid4().hex
    session.permanent = True
    _local.db_path = None
    _local.upload_dir = None


# ── Wiring ─────────────────────────────────────────────────────────────────
def configure(app, *, data_dir, upload_dir, db_path):
    """Pre-``db.init_app`` setup: record golden paths and install the
    per-session engine creator + context-aware config. Must run BEFORE
    Flask-SQLAlchemy creates the engine so the creator/poolclass take effect."""
    global GOLDEN_DB_PATH, GOLDEN_UPLOAD_DIR, SESSIONS_DIR, SESSION_UPLOADS_DIR
    global DATA_DIR, SESSION_TTL
    GOLDEN_DB_PATH = db_path
    GOLDEN_UPLOAD_DIR = upload_dir
    DATA_DIR = data_dir
    SESSIONS_DIR = os.path.join(data_dir, "demo_sessions")
    SESSION_UPLOADS_DIR = os.path.join(data_dir, "demo_uploads")
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    os.makedirs(SESSION_UPLOADS_DIR, exist_ok=True)

    try:
        ttl_min = int(os.environ.get("TSP_DEMO_SESSION_TTL_MIN", "90"))
        SESSION_TTL = max(5, ttl_min) * 60
    except ValueError:
        pass

    opts = dict(app.config.get("SQLALCHEMY_ENGINE_OPTIONS") or {})
    opts["creator"] = _demo_connect
    opts["poolclass"] = NullPool
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = opts

    # Swap in the context-aware config so UPLOAD_FOLDER / DB_PATH redirect
    # per session during requests.
    new_config = DemoConfig(app.root_path)
    new_config.update(app.config)
    app.config = new_config


def install(app):
    """Post-``init_app`` setup: register the request hooks (the before_request
    must be registered before the app's DB-touching gates so the thread-local is
    set first) and expose the ``demo_mode`` flag to templates."""
    app.before_request(_before_request)
    app.teardown_appcontext(_teardown)
    app.jinja_env.globals["demo_mode"] = True
    app.jinja_env.globals["demo_credentials"] = {
        "username": "admin", "password": "admin",
    }
    # The live demo's "home" is /demo (the product marketing page owns "/").
    # The frontend header brand link falls back to this when set.
    app.jinja_env.globals["home_url"] = "/demo"
