# Video Streamer (archived)

Live video broadcasting module for TSP. Archived 2026-05-26 — not
shipped with the active build yet. Restore when ready by following the
steps in [Restoring](#restoring) below.

## What it does

- Admin module at `/tspro/video-streamer` for configuring a live stream.
- Public viewer at `/videostreamer` with a dark, elegant HLS player
  built on `hls.js`.
- Five source types: **browser camera** (admin's webcam, sent over a
  WebSocket), **local v4l2 device** (OBS Virtual Cam through
  `/dev/video0`), **RTSP URL**, **HTTP URL**, and **local file**
  (uploaded via the form or referenced by server path).
- One `ffmpeg` subprocess per active stream; HLS segments written to
  `$TSP_DATA_DIR/stream/` and served back via Flask.
- Sidebar entry, Settings → Modules toggle, role gate, and full
  per-module on/off plumbing identical to other content modules.

## Layout

```
archive/video_streamer/
├── README.md              ← this file
├── integration.patch      ← diff of all changes against the
│                            integration touchpoints
└── app/
    ├── video_streamer.py            ← StreamManager (ffmpeg lifecycle)
    ├── static/js/hls.min.js         ← hls.js 1.5.17 (vendored)
    └── templates/
        ├── video_streamer.html      ← admin settings + control UI
        └── videostreamer.html       ← public viewer (standalone, dark)
```

The `integration.patch` captures all changes to the seven files the
module hooks into:

```
Dockerfile              ← adds ffmpeg + bumps gunicorn --timeout
app/__init__.py         ← Sock init + migration entries + manager.configure
app/models.py           ← SiteSetting columns + VideoStream model
app/routes.py           ← admin/public routes + WebSocket ingest
app/sidebar.py          ← catalog entry + visibility + section role
app/templates/base.html ← module toggle row in Settings → Modules
requirements.txt        ← flask-sock dependency
```

## Restoring

From the repo root:

```bash
# 1. Reapply the integration diff to the seven touched files.
git apply archive/video_streamer/integration.patch

# 2. Move the standalone files back to their live locations.
mv archive/video_streamer/app/video_streamer.py            app/
mv archive/video_streamer/app/templates/video_streamer.html app/templates/
mv archive/video_streamer/app/templates/videostreamer.html  app/templates/
mv archive/video_streamer/app/static/js/hls.min.js         app/static/js/

# 3. Delete the archive (optional — the patch + files are no
#    longer needed once they're back in place).
rm -rf archive/video_streamer/

# 4. Rebuild — Dockerfile installs ffmpeg and pip pulls flask-sock.
docker compose up -d --build
```

The `_migrate_sqlite` block re-runs idempotently, so the SiteSetting
columns (`video_streamer_enabled`, `video_streamer_required_role`)
and the `video_stream` table reappear on first boot. Any pre-archive
local-dev row in `video_stream` (e.g. an admin's saved bitrate,
uploaded video filename) is preserved — see
[Database state below](#database-state-left-behind).

## Database state left behind

The local SQLite DB (`data/tsp.db`) still has:

- Two columns on `site_setting`: `video_streamer_enabled` (Bool,
  default 0) and `video_streamer_required_role` (str, default
  `'admin'`).
- One row in `video_stream` with the last admin-saved configuration.

These are harmless while archived — no live code touches them. On
restore, the migration is a no-op for these schema bits and the saved
config is exactly where it was. If you want a fully clean slate before
restoring, drop the table + columns in SQLite manually; the migration
will recreate them on the next boot.

The `data/stream/` HLS-output directory is cleaned at archive time and
is recreated on demand by the StreamManager.

## Browser-camera ingest details

The trickiest piece is the WebSocket ingest. Notes for future-you:

- Admin browser uses `getUserMedia` → `MediaRecorder` (WebM/VP8+Opus)
  → WebSocket binary frames every 250 ms.
- Server route `/tspro/video-streamer/ws/ingest` (in routes.py)
  spawns `ffmpeg -f webm -i pipe:0 …` and pipes each WS frame into
  stdin. Closing the WS closes stdin and ffmpeg flushes the
  trailer + exits cleanly.
- `getUserMedia` requires a **secure context** — HTTPS, `localhost`,
  or `127.0.0.1`. The admin template detects insecure context and
  shows workaround instructions (SSH tunnel, Caddy with
  `tls internal`, install.sh's bundled Caddy).
- Gunicorn `--timeout` was bumped to 3600 s in the Dockerfile so
  long broadcasts aren't killed mid-stream (the WS is one "request"
  to gunicorn). The default 120 s would cap broadcasts at 2 min.
- `flask-sock` 0.7.0 uses `simple-websocket` which works with sync
  gunicorn workers via socket hijacking — at the cost of one worker
  per active WS connection. For our admin-only single-stream design
  that's fine.

## Why archived rather than shipped

User decision — feature is built and works end-to-end (verified with
ffmpeg test sources + a real browser camera over HTTPS) but not
needed in production right now. Pulled out so the next release can
ship without it. Code preserved here so it can be reinstated without
re-implementation work.
