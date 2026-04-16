# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run (Docker, preferred):** `docker compose up -d --build` — serves on host port 8090 (container 8000). Data/uploads persisted in `./data`.

**Run (local):** `pip install -r requirements.txt && python run.py` — serves on port 8000 with `debug=True`.

**Seeded admin:** on first boot (empty DB), `TSP_ADMIN_USERNAME` / `TSP_ADMIN_PASSWORD` (defaults `admin`/`admin`) is created.

**Data import scripts** (one-off utilities, not part of the app): `scripts/import_wp_*.py`, `scripts/import_zoom_tech.py`, `scripts/parse_zoom_tech_to_blocks.py`, `scripts/fetch_wp_files.py`. Run against a populated `./data/tsp.db`.

No test suite or linter is configured.

## Architecture

Flask + SQLAlchemy + SQLite app factory (`app/__init__.py::create_app`). Two blueprints: `auth` (`app/auth.py`) and `main` (`app/routes.py` — ~1300 lines, holds nearly all routes). Templates in `app/templates/`, static CSS/JS in `app/static/`. Jinja custom filters are registered in `create_app`: `file_type`, `safe_html` (bleach allowlist), `markdown`, `fmt12h`.

**Schema migrations:** there is no Alembic. `_migrate_sqlite()` in `app/__init__.py` runs on every startup and uses `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` to additively patch columns onto existing tables. When adding a new column to a model, **also add a matching entry in `_migrate_sqlite`** or existing deployments will break. `db.create_all()` handles fresh installs; `_migrate_sqlite` handles upgrades.

**Media indexing:** `_backfill_media()` scans `MeetingFile`/`Reading` stored filenames and indexes any missing files into `MediaItem` (with sha256 + size) at startup. All uploads live flat under `UPLOAD_FOLDER` (`/data/uploads`) with UUID-prefixed filenames.

**Domain model** (`app/models.py`): `Meeting` is the central entity; it has many `MeetingFile` rows grouped by `FILE_CATEGORIES` (`documents`, `scripts`, `external_links`, `videos`, `images`), many `MeetingSchedule` rows (day_of_week 0=Mon..6=Sun + HH:MM start), and many `Library` associations via `MeetingLibrary` with a `mode` of `all` or `granular`. In `granular` mode, the subset of visible readings is stored in the `meeting_reading_selections` join table. `SiteSetting` is a singleton row storing portal-wide branding, intergroup config, dashboard toggles, and Zoom-tech content. `ZoomAccount` and `ZoomOtpEmail` store encrypted credentials (Fernet, see `app/crypto.py`; key derived from `TSP_SECRET_KEY`).

**Roles:** `admin` / `editor` / `viewer`. Edit routes gate on `current_user.can_edit()`; user management gates on `is_admin()`.

**Rich content blocks:** `SiteSetting.zoom_tech_blocks_json` stores a JSON-encoded ordered list of content blocks rendered by `templates/_blocks.html`. The WP/Zoom import scripts produce this format.

## Configuration

Env vars (see README table): `TSP_SECRET_KEY` (also the Fernet key seed — rotating it invalidates stored encrypted credentials), `TSP_ADMIN_*` (seed only, ignored after first user exists), `TSP_DATA_DIR` (default `/data`), `TSP_UPLOAD_DIR` (default `$TSP_DATA_DIR/uploads`). Max upload size 256 MB.
