# Trusted Servants Pro

A self-hosted portal for recovery-fellowship trusted servants and members: organize meetings, share readings and files, manage Zoom host accounts, collect access requests, and brand it to your group — all from a single admin UI, no command line required.

Flask + SQLAlchemy + SQLite, packaged to run in a single Docker container with a persistent volume.

## Highlights

### Meetings
- Full create / edit / archive / restore with per-meeting logo and alert banner.
- In-person, online, and hybrid types with matching zoom/address fields shown conditionally.
- Unlimited per-day schedules (day-of-week + start time + duration + optional "opens" time).
- Table and card views with sort by name / day / type, both per-user remembered via cookies.
- Attach any number of libraries with `all` or `granular` visibility so each meeting can show just the readings it uses.
- Meeting detail page: schedule table, Zoom info (meeting ID, passcode, link, host account) with click-to-copy and Reveal controls, embedded OTP email credentials for hybrid/online meetings, and per-category file lists (documents, scripts, links, videos, images).

### Libraries
- Grouped reading collections with optional alert banner and description.
- Drag-and-drop ordering, inline edit, thumbnail support, optional inline body text, and external-link entries.
- File uploads or existing-asset selection from the File Browser.

### File Browser
- Central media library indexed from every upload across the app (`MediaItem` auto-backfilled on startup).
- Search, sort, grid / table views, rename, upload with progress, delete with reference-count guard.
- Public shareable URLs at `/pub/<original-filename>` — human-readable, no hashes or tokens. Serves the newest file of that name with the correct `Content-Disposition`.
- Inline **Copy Link** buttons everywhere a file appears (File Browser, Meetings, Libraries).

### Access Requests
- Public Request Access form on the login screen captures name, phone, email, role(s), and meeting.
- Submissions emailed to a configurable recipient list via the portal's SMTP settings.
- Admin-only Access Requests page (sidebar with pending-count badge) for triage: Mark Handled / Reopen / Delete.
- Recent requests widget on the dashboard.

### Zoom accounts
- Encrypted credential storage (Fernet with a local key file, see **Security**).
- Assign any account to any meeting schedule.
- Weekly assignment calendar starting Sunday, with automatic time-conflict detection (overlapping slots on the same account highlighted red).
- Separate OTP email credentials shown to members on online/hybrid meeting pages so they can retrieve one-time codes without admin involvement.
- Viewable by editors and viewers (read-only); admin-only for create/edit/delete.

### Login experience
- Redesigned split login screen with animated canvas particle background.
- Nine selectable effects: Off, Network, Starfield, Fireflies, Bubbles, Snow, Waves, Orbits, Rain.
- Adjustable **speed** and **particle size** sliders, **mouse-reactive physics**, live preview inside Settings.
- Configurable background: default sine-wave gradient, solid color, or custom gradient with 2–4 color stops and a palette randomizer.
- Optional 3D **login transition**: doors swing open on successful authentication to reveal a moving full-saturation sine-wave rainbow with the branding logo, then fades to the active theme's background before the next page loads.
- Theme carries through: the chosen theme is applied to the login screen before paint.

### Themes & branding
- Six full palettes: Light, Dark, Neobrutal Light/Dark, Cyberpunk, Solarpunk.
- Unified accent color (`#0b5cff`) across buttons, links, and active nav states.
- Inter font (weights 100–900) shipped app-wide.
- Admin-configurable sidebar footer logo (upload + width slider + link URL) and login screen (particles, background, transition).

### Dashboard
- Stats row (meeting count, library count, your role).
- Configurable widgets: Recent Meetings, Libraries, Recent Files, Intergroup, Public Information Chair contact, Access Requests (admin).
- Each widget toggleable from the Customize Dashboard modal.

### Settings
- Full-viewport modal on mobile, horizontally-scrollable tabs with fade hint, AJAX-save with in-modal toast — the modal never closes when you save.
- Tabs: **Appearance** (theme, branding, login screen), **Users**, **Zoom Accounts**, **Meeting Locations**, **External Links**, **Special Sections**, **Email**, **Data**, **About**.
- Role gating: admins see everything; editors/viewers see Appearance → Theme, Zoom Accounts (read-only), and About.

### Email
- Global SMTP configuration (host, port, username/password, STARTTLS / SSL / plain).
- Encrypted password storage using the same Fernet key as Zoom credentials.
- Configurable From name + address, comma-separated recipient list for access-request notifications, and a one-click Send Test button.

### Data export / import
- One-click **Export** produces a zip containing a VACUUM-copied SQLite database, every upload, and the `zoom.key` file used to decrypt stored Zoom credentials.
- One-click **Import** takes an export archive, validates it, moves the existing database + uploads + key to a timestamped `backup-YYYYMMDD-HHMMSS/` folder inside `./data`, restores the archive in place, re-runs migrations, and signs the user out. No command-line access required.

### Session
- 6-month remember-me cookie so users aren't repeatedly prompted for credentials.

### Mobile
- Dedicated mobile layouts across the app (meetings/libraries/files, users/zoom/locations inside Settings).
- Stacked "data cards" replace overflowing tables, actions expand to full width.
- Sidebar is a slide-in drawer with tap-outside-to-close.

## Quick start

```bash
docker compose up -d --build
```

Open http://localhost:8090 and sign in with the seeded admin (defaults: `admin` / `admin`). Change these in `.env` before first run, or rotate later from the Users tab.

### docker-compose.yml

```yaml
services:
  tsp:
    image: viibeware/trusted-servants-pro:latest
    container_name: tspro
    ports:
      - "8090:8000"
    volumes:
      - ./data:/data
    environment:
      - TSP_SECRET_KEY=${TSP_SECRET_KEY:?TSP_SECRET_KEY must be set in .env}
      - TSP_ADMIN_USERNAME=admin
      - TSP_ADMIN_PASSWORD=admin
      - TSP_ADMIN_EMAIL=admin@example.com
    restart: unless-stopped
```

## Configuration

A `.env` file sits alongside `docker-compose.yml`:

```
TSP_SECRET_KEY=<long random string>
```

Other environment variables (all with sensible defaults):

| Variable | Default | Purpose |
| --- | --- | --- |
| `TSP_SECRET_KEY` | `dev-secret-change-me` | Flask session signing key. Required to be set in production. |
| `TSP_ADMIN_USERNAME` | `admin` | Seeded on first boot only. |
| `TSP_ADMIN_PASSWORD` | `admin` | Seeded on first boot only. |
| `TSP_ADMIN_EMAIL` | `admin@example.com` | Seeded on first boot only. |
| `TSP_DATA_DIR` | `/data` | Inside-container data directory. Mounted to `./data` on the host by default. |
| `TSP_UPLOAD_DIR` | `$TSP_DATA_DIR/uploads` | Location of uploaded files. |
| `TSP_FERNET_KEY` | _auto-generated_ | If set, used directly; otherwise a key is generated and stored in `data/zoom.key`. |

Uploads are limited to **256 MB** per file.

## Security

- **Session cookies** are signed with `TSP_SECRET_KEY`. Rotating it will sign users out but does not affect encrypted credentials.
- **Zoom account passwords, OTP email password, and SMTP password** are encrypted with Fernet. The key lives at `data/zoom.key` (auto-generated on first boot) or is loaded from the `TSP_FERNET_KEY` env var. **Keep this file alongside your database if you restore to another host**, or set `TSP_FERNET_KEY` explicitly — the Data export bundles it for you.
- Public file URLs (`/pub/<filename>`) are intentionally human-readable and unauthenticated. Anyone with the link can read the file. Do not upload content you do not want shared.
- Access-request submissions are public (no login required) but rate-limited by the browser.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Serves on http://localhost:8000 with `debug=True`.

## Backing up & migrating

Use **Settings → Data → Export** for a portable archive. To restore on a fresh server, start the container once (which creates the data directory), then upload the export through **Settings → Data → Import**. The existing state is moved to `data/backup-<timestamp>/` before the restore runs.

If you prefer the command line:

```bash
docker compose down
cp -r ./data ./data.bak
# copy the export zip contents (tsp.db, uploads/, zoom.key) into ./data/
docker compose up -d
```

## Project layout

```
app/
  __init__.py      # app factory, startup migrations, Fernet init
  auth.py          # login / logout / user CRUD
  crypto.py        # Fernet helpers
  mail.py          # SMTP send helper
  models.py        # SQLAlchemy models (Meeting, Library, Reading, User, ZoomAccount, ...)
  routes.py        # main blueprint — nearly all feature routes
  static/          # CSS, JS, images, login_fx engine
  templates/       # Jinja templates (base + per-feature)
scripts/           # one-off WP / Zoom import utilities
docker-compose.yml
Dockerfile
requirements.txt
run.py
README.md
```

## License

© Viibeware Corp. All rights reserved.
