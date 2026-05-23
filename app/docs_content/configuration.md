Title: Configuration & Security
Category: Configuration
Order: 1
Slug: configuration
Icon: sliders
Summary: Every environment variable, the .env file, the maximum upload size, and how Trusted Servants Pro encrypts stored credentials.

Trusted Servants Pro is configured entirely through environment variables, with
sensible defaults for everything except the session secret. In a Compose
deployment those variables live in a `.env` file that sits alongside your
`docker-compose.yml`.

## The .env file

At minimum, `.env` must define `TSP_SECRET_KEY` — a long, random value used to
sign Flask session cookies. Generate one with `openssl`:

```bash
openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-64
```

A typical `.env`:

```ini
TSP_SECRET_KEY=replace-with-the-output-of-the-command-above
TSP_ADMIN_USERNAME=admin
TSP_ADMIN_PASSWORD=change-me-before-first-boot
TSP_ADMIN_EMAIL=admin@example.com
```

!!! warning "Keep .env private"
    Never commit `.env` to version control, and set it to mode `600` on the host
    (`chmod 600 .env`). The one-command installer does this for you.

## Environment variables

All variables have defaults except `TSP_SECRET_KEY`, which you should always set
explicitly in production.

| Variable | Default | Purpose |
| --- | --- | --- |
| `TSP_SECRET_KEY` | `dev-secret-change-me` | Flask session signing key. **Set this in production.** |
| `TSP_ADMIN_USERNAME` | `admin` | Seeded on first boot only. |
| `TSP_ADMIN_PASSWORD` | `admin` | Seeded on first boot only. |
| `TSP_ADMIN_EMAIL` | `admin@example.com` | Seeded on first boot only. |
| `TSP_DATA_DIR` | `/data` | In-container data directory. Mounted to `./data` by default. |
| `TSP_UPLOAD_DIR` | `$TSP_DATA_DIR/uploads` | Where uploaded files are stored. |
| `TSP_MAX_UPLOAD_MB` | `4096` | Maximum upload size in MiB (default 4 GiB). |
| `TSP_FERNET_KEY` | _auto-generated_ | Encryption key for stored credentials. If unset, a key is generated and saved to `data/zoom.key`. |

!!! note "The admin variables only seed the first boot"
    `TSP_ADMIN_USERNAME` / `TSP_ADMIN_PASSWORD` / `TSP_ADMIN_EMAIL` create the
    initial admin **only when the database is empty**. Changing them later has no
    effect — manage users from **Settings → Users** instead.

## Upload size

Uploads default to a generous **4 GiB** ceiling so a full-portal restore bundle
(database plus the entire uploads directory in one request) isn't truncated.
Lower it with `TSP_MAX_UPLOAD_MB` if you want a tighter limit:

```yaml
environment:
  - TSP_MAX_UPLOAD_MB=512
```

## How credentials are encrypted

Trusted Servants Pro stores some secrets on your behalf — Zoom account
passwords, the OTP email password, and your SMTP password. These are **encrypted
at rest** with [Fernet](https://cryptography.io/en/latest/fernet/) symmetric
encryption.

- The Fernet key is auto-generated on first boot and written to
  `data/zoom.key`, **unless** you provide `TSP_FERNET_KEY` explicitly, in which
  case that value is used.
- The key is independent of `TSP_SECRET_KEY`. Rotating your session secret signs
  everyone out but does **not** affect stored credentials.

!!! danger "Keep zoom.key with your database"
    If you move your database to another host without the matching `zoom.key`
    (or `TSP_FERNET_KEY`), the portal can no longer decrypt stored Zoom/SMTP
    passwords. The **Settings → Data → Export** archive bundles the key for you,
    so a UI export/import migration always carries it along.

## A note on public file URLs

Files are served at human-readable URLs like `/pub/<original-filename>` —
intentionally without hashes or tokens. These URLs are **unauthenticated**:
anyone with the link can read the file. Don't upload anything you wouldn't want
shared. See [Security](#how-credentials-are-encrypted) above for how stored
secrets differ from public files.

## Next steps

- [Backup &amp; Restore](/docs/backup-restore) — export, import, and migrate.
- [Upgrading &amp; Uninstalling](/docs/upgrading) — keep the portal current.
