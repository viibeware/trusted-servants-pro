Title: Installation
Category: Getting Started
Order: 2
Slug: installation
Icon: download
Summary: A complete, end-to-end guide to deploying Trusted Servants Pro — from a one-command production install with automatic HTTPS to running it on any machine with Docker Compose.

Trusted Servants Pro ships as a single self-contained Docker image: one Flask
app, one SQLite database, one persistent data directory. There is no external
database to provision, no message queue, and no per-seat licensing. This guide
walks you through every supported way to install it, what each step does, and
how to verify the result.

There are two supported paths. Pick the one that matches where you're running it:

| | **One-command installer** | **Docker Compose** |
| --- | --- | --- |
| Best for | A public production server | A laptop, homelab, or any VPS |
| You get | Docker, hardened Compose file, generated secret, **automatic HTTPS** (Caddy + Let's Encrypt), auto-updates (Watchtower) | A single container you manage yourself |
| Requires | A fresh **Ubuntu 24.04** host with root/sudo | Any machine with Docker Engine + the Compose plugin |
| TLS | Issued and renewed for you | You add your own reverse proxy if needed |
| Time | 2–5 minutes | Under a minute |

If you want a real domain with HTTPS that just works, use **Path A**. If you
just want to kick the tires or run it behind your own proxy, use **Path B**.

!!! note "Prefer not to install anything yet?"
    Every feature in this documentation is available to try in the [live
    demo](/demo) — no install required. Your changes there are private to your
    browser session and reset automatically when you leave.

## Before you begin

Whichever path you choose, it helps to have these ready:

- **A host to run it on.** For Path A this must be a fresh Ubuntu 24.04 LTS
  server. 1 vCPU / 1 GB RAM comfortably handles a small-to-medium fellowship.
- **(Optional) A domain name.** Only needed if you want a browser-trusted TLS
  certificate. Without one, the installer issues a self-signed certificate and
  your browser will show a one-time warning.
- **A way to generate a random secret.** The installer does this for you; for
  the manual path you'll run a single `openssl` command shown below.

## Path A — One-command installer (production + HTTPS)

`install.sh` is a turnkey installer for a public server. In one run it:

1. Updates apt, installs **Docker Engine** and the **Compose plugin**, and opens
   the firewall (UFW) for ports `22`, `80`, and `443`.
2. Writes a hardened `docker-compose.yml` to the install directory.
3. Generates a random `TSP_SECRET_KEY` and stores it in a `.env` file with
   mode `600` (readable only by root).
4. Configures **Caddy** for automatic TLS — a real Let's Encrypt certificate if
   you provide a domain, or a self-signed one if you don't.
5. Installs **Watchtower** so the portal pulls and restarts on new releases on
   its own.
6. Pulls the image, starts everything, and waits for the portal to respond.

### 1. Provision a server

Spin up a fresh **Ubuntu 24.04 LTS** instance on any provider — DigitalOcean,
Hetzner, AWS Lightsail, or bare metal all work. SSH in as `root` or a user with
`sudo`:

```bash
ssh root@your-server-ip
```

### 2. Point your domain at the server

This step is **required for a real (Let's Encrypt) certificate** and can be
skipped entirely if you're fine with a self-signed cert.

Add a DNS **A record** for your hostname pointing at the server's public IP, and
let it propagate before running the installer:

```text
portal.yourfellowship.org   →   203.0.113.10
```

During issuance, Let's Encrypt performs an HTTP-01 challenge on port 80. The
hostname **must already resolve to this server** or the challenge fails.

!!! warning "Cloudflare users: use “DNS only” (grey cloud) during install"
    Cloudflare's proxy (orange cloud) terminates TLS at its edge and intercepts
    port 80, which breaks the HTTP-01 challenge and hands Let's Encrypt one of
    Cloudflare's IPs instead of your server's. Set the record to **DNS only**
    while installing; you can switch it back to proxied *after* the certificate
    is issued.

The installer runs a DNS pre-check. If the hostname doesn't resolve to this
machine, it automatically falls back to a self-signed certificate and prints how
to re-enable Let's Encrypt later. Fix the DNS and re-run `install.sh` to switch
to a real cert.

### 3. Run the installer

Pipe it straight from GitHub — the recommended path:

```bash
curl -fsSL https://raw.githubusercontent.com/viibeware/trusted-servants-pro/main/install.sh | sudo bash
```

Or clone the repository first if you'd like to read the script before running it:

```bash
git clone https://github.com/viibeware/trusted-servants-pro.git
cd trusted-servants-pro
sudo bash install.sh
```

### 4. Answer the prompts

The installer asks at most two questions:

```text
Domain (blank = self-signed): portal.yourfellowship.org
Contact email: you@yourfellowship.org
```

- **Domain** — the hostname from step 2. Press Enter to skip and get a
  self-signed certificate.
- **Contact email** — only asked if you entered a domain; Let's Encrypt uses it
  for renewal notices.

It then pulls `viibeware/trusted-servants-pro:latest`, starts the stack, and
waits for a healthy response. Typical runtime is **2–5 minutes** on a fresh VM.

### 5. Sign in and secure it

When it finishes, the installer prints your portal URL — either
`https://<your-domain>` or `https://<server-ip>`. Open it and sign in with the
seeded admin:

```text
user: admin   ·   pass: admin
```

!!! danger "Change the admin password immediately"
    The seeded `admin` / `admin` credentials are public knowledge. Your first
    action should be **Settings → Users → change password**. You can also set a
    strong password up front with the non-interactive install below.

### Non-interactive installs

Skip every prompt by passing answers inline on the same command:

```bash
sudo TSP_DOMAIN=portal.yourfellowship.org \
     TSP_ACME_EMAIL=you@yourfellowship.org \
     TSP_ADMIN_PASSWORD='a-strong-password' \
     bash install.sh
```

Recognized installer variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `TSP_INSTALL_DIR` | `/opt/tspro` | Where the compose file, data, and backups live. |
| `TSP_IMAGE` | `viibeware/trusted-servants-pro:latest` | Image tag to deploy. |
| `TSP_DOMAIN` | _unset_ | Public hostname. If set, Caddy requests a Let's Encrypt cert. |
| `TSP_ACME_EMAIL` | `admin@$TSP_DOMAIN` | Contact address for renewal notices. |
| `TSP_ADMIN_USERNAME` | `admin` | Seeded on first boot only. |
| `TSP_ADMIN_PASSWORD` | `admin` | Seeded on first boot only. |
| `TSP_ADMIN_EMAIL` | `admin@example.com` | Seeded on first boot only. |

## Path B — Docker Compose (any machine)

The quickest way to run the portal anywhere — a laptop, a homelab box, or any
VPS. One container, one SQLite file, no TLS automation.

### 1. Confirm Docker is installed

You need Docker Engine and the Compose plugin. Confirm both before you start:

```bash
docker --version && docker compose version
```

If either is missing, install Docker from [docker.com](https://docs.docker.com/engine/install/)
first.

### 2. Create a compose file

You can clone the repo, or just drop this `docker-compose.yml` in an empty
directory:

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

The host serves on port **8090**; the container listens on `8000`. Your
database and uploads persist in `./data` next to the compose file.

### 3. Set a secret key

Trusted Servants Pro signs session cookies with `TSP_SECRET_KEY`. Generate a
random value into a `.env` file beside your compose file:

```bash
echo "TSP_SECRET_KEY=$(openssl rand -hex 32)" > .env
```

### 4. Build and start

```bash
docker compose up -d
```

(If you cloned the repository and want to build the image locally instead of
pulling it, use `docker compose up -d --build`.)

### 5. Open it

```text
→ http://localhost:8090         # public site
→ http://localhost:8090/tspro   # admin (admin / admin)
```

Sign in, then change the admin password from **Settings → Users**.

## After installation

A few things worth doing right away:

- **Change the admin password** (Settings → Users) if you haven't already.
- **Set up email** (Settings → Email) so access-request notifications can be
  delivered, and send yourself a test message.
- **Brand it** (Settings → Appearance) — pick a theme, upload your logo, and
  configure the login screen.
- **Take your first backup** once you've added content — see
  [Backup &amp; Restore](/docs/backup-restore).

## Troubleshooting

!!! tip "Check the logs first"
    Almost every install issue is explained in the container logs. From the
    install directory: `docker compose logs -f tsp`.

**The HTTPS certificate didn't issue.** The hostname likely didn't resolve to
this server when the installer ran (or Cloudflare was proxying). Fix the DNS A
record, ensure it's "DNS only", and re-run `install.sh`. Until then the portal
is reachable on its self-signed certificate.

**Port 8090 (or 80/443) is already in use.** Another service is bound to that
port. For Compose, change the host side of the `ports` mapping (e.g.
`"9000:8000"`). For the installer, stop whatever is using 80/443.

**The container starts then exits.** This almost always means `TSP_SECRET_KEY`
is unset. Confirm your `.env` defines it and that it sits next to the compose
file, then `docker compose up -d` again.

**I forgot the admin password.** The `TSP_ADMIN_*` variables only seed the
*first* boot — changing them later has no effect. Reset the password from
another admin account under Settings → Users.

## Next steps

- [Configuration &amp; Security](/docs/configuration) — every environment
  variable, the `.env` file, and how credentials are encrypted.
- [Backup &amp; Restore](/docs/backup-restore) — export a portable archive and
  migrate to a new host.
- [Upgrading &amp; Uninstalling](/docs/upgrading) — Watchtower auto-updates,
  manual upgrades, and a clean teardown.
