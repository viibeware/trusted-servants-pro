Title: Upgrading & Uninstalling
Category: Operations
Order: 2
Slug: upgrading
Icon: refresh
Summary: How automatic updates work, how to force an upgrade or roll day-to-day commands, and how to cleanly uninstall everything the installer added.

Trusted Servants Pro is distributed as a versioned Docker image, so upgrading is
just pulling a newer image and restarting the container. Your data in `./data`
is untouched by upgrades.

## Automatic updates (one-command installs)

If you used the [one-command installer](/docs/installation#path-a-one-command-installer-production-https),
**Watchtower** is already running. It polls Docker Hub every 24 hours and
restarts the `tspro` container whenever a new image is published. No action is
required on your part.

## Forcing an upgrade

To upgrade immediately instead of waiting for Watchtower — or on a Compose-only
deployment without it — pull and recreate:

```bash
cd /opt/tspro          # or wherever your compose file lives
docker compose pull && docker compose up -d
```

Startup migrations run automatically on boot, so the schema is brought up to
date the moment the new container starts.

## Day-to-day commands

```bash
docker compose ps                  # what's running
docker compose logs -f tsp         # tail the portal logs
docker compose pull && docker compose up -d   # upgrade now
docker compose down                # stop everything (data is preserved)
```

!!! tip "Back up before a major upgrade"
    Upgrades are designed to be safe and migrations are additive, but a quick
    [export](/docs/backup-restore) before a big jump is cheap insurance.

## Uninstalling

`uninstall.sh` ships next to the installer and reverses what it did, with safe
defaults: it removes only the TSP containers, named volumes, and the install
directory. Docker itself, the firewall, and base packages are left alone unless
you ask.

```bash
# From a clone of the repo:
sudo bash uninstall.sh

# Or pipe directly from GitHub:
curl -fsSL https://raw.githubusercontent.com/viibeware/trusted-servants-pro/main/uninstall.sh | sudo bash
```

You'll be asked to type `yes` before anything is removed. Flags let you go
further:

| Flag | Effect |
| --- | --- |
| `-y`, `--yes` | Skip the confirmation prompt (needed when piping from curl). |
| `--keep-data` | Preserve `/opt/tspro/data/` (database, uploads, `zoom.key`). |
| `--purge-images` | Also remove the pulled TSP, Caddy, and Watchtower images. |
| `--remove-ufw-rules` | Revert the 80/443 UFW rules (OpenSSH is left intact). |
| `--remove-docker` | Purge Docker, its apt source/keyring, and `/var/lib/docker`. |
| `--nuke` | Shorthand for `--purge-images --remove-ufw-rules --remove-docker`. |

Full teardown of everything the installer put on the server:

```bash
sudo bash uninstall.sh --nuke --yes
```

!!! danger "Save your data before uninstalling"
    Unless you pass `--keep-data`, uninstalling removes `/opt/tspro/data/` — your
    database, uploads, and encryption key. [Export](/docs/backup-restore) first
    if you might want any of it back.

## Next steps

- [Backup &amp; Restore](/docs/backup-restore) — protect your data before any
  big change.
- [Configuration &amp; Security](/docs/configuration) — environment variables and
  encryption.
