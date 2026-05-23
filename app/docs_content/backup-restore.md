Title: Backup & Restore
Category: Operations
Order: 1
Slug: backup-restore
Icon: save
Summary: Export a portable archive of your portal, restore it on a fresh server, and migrate between hosts — from the UI or the command line.

Everything that makes your portal *yours* lives in one place: the `./data`
directory (or the volume you mounted to `/data`). It holds the SQLite database,
every uploaded file, and the `zoom.key` used to decrypt stored credentials. Back
that up and you can rebuild anywhere.

## Export from the UI (recommended)

The simplest, no-command-line option:

1. Go to **Settings → Data → Export**.
2. The portal builds a single zip containing a **VACUUM-copied** SQLite database,
   every upload, and the `zoom.key` file.
3. Download and store it somewhere safe.

Because the export bundles `zoom.key`, a UI export always carries the encryption
key needed to read your Zoom/SMTP credentials on another host.

## Restore from the UI

To restore onto a fresh server:

1. Start the container once so it creates the data directory.
2. Go to **Settings → Data → Import** and upload your export archive.
3. The portal validates the archive, moves the existing database, uploads, and
   key into a timestamped `data/backup-YYYYMMDD-HHMMSS/` folder, restores the
   archive in place, re-runs migrations, and signs you out.
4. Sign back in — your content is restored.

!!! note "Nothing is destroyed on import"
    The previous state is moved aside into `data/backup-<timestamp>/` rather than
    deleted, so a restore is reversible if something looks wrong.

!!! warning "Large restores and upload limits"
    A full-portal archive can be large. The upload ceiling defaults to 4 GiB —
    if your bundle is bigger, raise [`TSP_MAX_UPLOAD_MB`](/docs/configuration)
    on the server and restart before importing.

## Command-line backup

If you'd rather work on the host, the data directory is all you need:

```bash
docker compose down
cp -r ./data ./data.bak
docker compose up -d
```

To restore a UI-style export by hand, copy its contents (`tsp.db`, `uploads/`,
`zoom.key`) into `./data/` while the container is stopped, then start it again:

```bash
docker compose down
# copy tsp.db, uploads/, and zoom.key into ./data/
docker compose up -d
```

## Migrating to a new host

1. **Export** from the old portal (UI export, or copy `./data`).
2. Install Trusted Servants Pro on the new host — see
   [Installation](/docs/installation).
3. **Import** the archive (UI), or drop the data directory into place (CLI).

!!! danger "Don't leave zoom.key behind"
    If you migrate by copying files manually, make sure `zoom.key` comes along
    (or set `TSP_FERNET_KEY` to the same value). Without it, stored Zoom and SMTP
    passwords can't be decrypted on the new host. The UI export includes it
    automatically.

## Next steps

- [Configuration &amp; Security](/docs/configuration) — how `zoom.key` and
  encryption work.
- [Upgrading &amp; Uninstalling](/docs/upgrading) — staying current and clean
  teardown.
