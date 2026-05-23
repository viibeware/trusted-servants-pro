Title: Quick Start
Category: Getting Started
Order: 1
Slug: quick-start
Icon: rocket
Summary: Get a working portal running with Docker Compose in under a minute, then sign in and look around.

This is the fastest way to see Trusted Servants Pro running on your own machine.
If you're deploying to a public server with a domain and HTTPS, follow the full
[Installation](/docs/installation) guide instead.

## Prerequisites

- **Docker Engine** and the **Compose plugin**. Verify with:

```bash
docker --version && docker compose version
```

## 1. Create the project

Make an empty directory and add a `docker-compose.yml`:

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
    restart: unless-stopped
```

## 2. Generate a secret key

The portal signs session cookies with `TSP_SECRET_KEY`. Write a random one into
a `.env` file next to the compose file:

```bash
echo "TSP_SECRET_KEY=$(openssl rand -hex 32)" > .env
```

## 3. Start it

```bash
docker compose up -d
```

The image pulls and the container starts in the background. Your data lives in
`./data` and survives restarts and upgrades.

## 4. Sign in

Open the two entry points:

```text
→ http://localhost:8090         # public site
→ http://localhost:8090/tspro   # admin backend
```

Sign in to the admin with the seeded account:

```text
user: admin   ·   pass: admin
```

!!! danger "Change the password"
    Immediately set a real password under **Settings → Users**. The default
    `admin` / `admin` is public knowledge.

## What next?

- [Installation](/docs/installation) — the full production install with a domain,
  automatic HTTPS, and auto-updates.
- [Configuration &amp; Security](/docs/configuration) — environment variables and
  how secrets are stored.
- [Backup &amp; Restore](/docs/backup-restore) — keep your data safe.
