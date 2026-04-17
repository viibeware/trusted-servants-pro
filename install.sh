#!/usr/bin/env bash
#
# Trusted Servants Pro — unattended installer for Ubuntu 24.04.
#
# Run as root (or with sudo) on a fresh Ubuntu 24.04 server:
#
#   curl -fsSL https://raw.githubusercontent.com/<org>/trusted-servants-pro/main/install.sh | sudo bash
#
# Or:
#
#   sudo bash install.sh
#
# Optional environment variables:
#   TSP_INSTALL_DIR   Install directory             (default: /opt/tspro)
#   TSP_IMAGE         Docker image to deploy        (default: viibeware/trusted-servants-pro:latest)
#   TSP_DOMAIN        Public hostname for HTTPS     (default: unset — uses self-signed cert)
#   TSP_ACME_EMAIL    Email for Let's Encrypt cert  (default: admin@<TSP_DOMAIN>)
#   TSP_ADMIN_USERNAME / TSP_ADMIN_PASSWORD / TSP_ADMIN_EMAIL
#                     Seeded admin credentials      (defaults: admin / admin / admin@example.com)
#

set -euo pipefail

# ---------- config ----------
INSTALL_DIR="${TSP_INSTALL_DIR:-/opt/tspro}"
IMAGE="${TSP_IMAGE:-viibeware/trusted-servants-pro:latest}"
DOMAIN="${TSP_DOMAIN:-}"
ACME_EMAIL="${TSP_ACME_EMAIL:-}"
ADMIN_USERNAME="${TSP_ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${TSP_ADMIN_PASSWORD:-admin}"
ADMIN_EMAIL="${TSP_ADMIN_EMAIL:-admin@example.com}"

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a   # auto-restart services without prompting

log()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m!! \033[0m %s\n' "$*" >&2; }
fail() { printf '\n\033[1;31mXX \033[0m %s\n' "$*" >&2; exit 1; }

# ---------- preflight ----------
[[ $EUID -eq 0 ]] || fail "This installer must be run as root (try: sudo bash install.sh)"

if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || warn "This installer targets Ubuntu — detected ID=${ID:-unknown}, continuing anyway."
  [[ "${VERSION_ID:-}" == "24.04" ]] || warn "This installer targets Ubuntu 24.04 — detected ${VERSION_ID:-unknown}, continuing anyway."
else
  warn "Could not detect OS via /etc/os-release — continuing anyway."
fi

# ---------- domain prompt ----------
# Pick an input stream: stdin if it's a TTY, otherwise /dev/tty (so the prompt
# still works when the script is piped from curl). If neither is interactive,
# fall back to whatever was passed via env (default: self-signed).
PROMPT_FD=""
if [[ -t 0 ]]; then
  PROMPT_FD=0
elif [[ -r /dev/tty ]]; then
  exec 3</dev/tty
  PROMPT_FD=3
fi

if [[ -z "${DOMAIN}" && -n "${PROMPT_FD}" ]]; then
  printf '\n\033[1;36m==>\033[0m Will this server be reached via a public domain name?\n'
  printf '    A real domain lets Caddy issue a free Let'\''s Encrypt TLS certificate.\n'
  printf '    Leave blank to use a self-signed certificate (browser will warn).\n\n'
  printf '    DNS reminder: the domain'\''s A record must already point at this\n'
  printf '    server'\''s public IP, or certificate issuance will fail.\n\n'
  printf '  Domain (e.g. portal.example.org) [none]: '
  read -r DOMAIN <&${PROMPT_FD} || DOMAIN=""
  DOMAIN="$(printf '%s' "${DOMAIN}" | tr -d '[:space:]')"

  if [[ -n "${DOMAIN}" && -z "${ACME_EMAIL}" ]]; then
    printf '  Contact email for Let'\''s Encrypt [admin@%s]: ' "${DOMAIN}"
    read -r ACME_EMAIL <&${PROMPT_FD} || ACME_EMAIL=""
    ACME_EMAIL="$(printf '%s' "${ACME_EMAIL}" | tr -d '[:space:]')"
  fi
fi

if [[ -n "${DOMAIN}" ]]; then
  log "Using domain: ${DOMAIN} (Let's Encrypt)"
else
  log "No domain provided — Caddy will serve a self-signed certificate"
fi

# ---------- DNS pre-check ----------
# If a domain is set, make sure it resolves to this server's public IP before
# letting Caddy attempt Let's Encrypt issuance. The HTTP-01 challenge needs
# the domain to point at *this* machine on port 80; if DNS is wrong or a
# Cloudflare proxy is sitting in front, ACME fails and HTTPS is left
# unreachable. If the check fails we silently downgrade to a self-signed cert
# so the portal still comes up, and tell the user how to recover.
ORIGINAL_DOMAIN="${DOMAIN}"
DOMAIN_FALLBACK_REASON=""
if [[ -n "${DOMAIN}" ]]; then
  log "Verifying DNS for ${DOMAIN}"
  PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
  RESOLVED_IP="$(getent ahostsv4 "${DOMAIN}" 2>/dev/null | awk 'NR==1{print $1}')"

  if [[ -z "${PUBLIC_IP}" ]]; then
    warn "Could not determine this server's public IP (api.ipify.org unreachable)."
    warn "Skipping DNS pre-check — if Let's Encrypt fails, rerun after confirming DNS."
  elif [[ -z "${RESOLVED_IP}" ]]; then
    DOMAIN_FALLBACK_REASON="DNS for ${DOMAIN} does not resolve to any IP yet."
    warn "${DOMAIN_FALLBACK_REASON}"
    warn "Let's Encrypt would fail, so falling back to a self-signed certificate."
    warn "Point an A record for ${DOMAIN} at ${PUBLIC_IP}, then rerun this installer."
    DOMAIN=""
  elif [[ "${RESOLVED_IP}" != "${PUBLIC_IP}" ]]; then
    DOMAIN_FALLBACK_REASON="DNS for ${DOMAIN} resolves to ${RESOLVED_IP} but this server's public IP is ${PUBLIC_IP}."
    warn "${DOMAIN_FALLBACK_REASON}"
    warn "If you use Cloudflare, the proxy (orange cloud) hides the origin IP"
    warn "and breaks Let's Encrypt's HTTP-01 challenge."
    warn "Falling back to a self-signed certificate so the portal stays reachable."
    warn ""
    warn "To switch to Let's Encrypt once DNS is correct:"
    warn "  1. In Cloudflare, set the record for ${DOMAIN} to 'DNS only' (grey cloud),"
    warn "     or update the A record at your DNS provider to ${PUBLIC_IP}."
    warn "  2. Wait for propagation (usually under a minute)."
    warn "  3. Rerun this installer."
    warn "  4. After issuance succeeds you can re-enable the Cloudflare proxy."
    DOMAIN=""
  else
    log "DNS OK: ${DOMAIN} -> ${RESOLVED_IP}"
  fi
fi

# ---------- system update + base packages ----------
log "Updating apt package index and installing base packages"
apt-get update -y
apt-get upgrade -y
apt-get install -y \
  ca-certificates curl gnupg lsb-release \
  ufw openssl jq

# ---------- docker engine + compose plugin ----------
if ! command -v docker >/dev/null 2>&1; then
  log "Installing Docker Engine and the Compose plugin"
  install -m 0755 -d /etc/apt/keyrings
  if [[ ! -s /etc/apt/keyrings/docker.gpg ]]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
  fi

  ARCH="$(dpkg --print-architecture)"
  CODENAME="$( . /etc/os-release && echo "${UBUNTU_CODENAME:-${VERSION_CODENAME:-noble}}" )"
  cat >/etc/apt/sources.list.d/docker.list <<EOF
deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${CODENAME} stable
EOF

  apt-get update -y
  apt-get install -y \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

  systemctl enable --now docker
else
  log "Docker already installed: $(docker --version)"
fi

docker compose version >/dev/null 2>&1 || fail "docker compose plugin not available after install"

# ---------- firewall ----------
log "Configuring UFW (allow OpenSSH, 80/tcp, 443/tcp)"
ufw allow OpenSSH        >/dev/null || true
ufw allow 80/tcp         >/dev/null
ufw allow 443/tcp        >/dev/null
ufw --force enable       >/dev/null
ufw reload               >/dev/null || true

# ---------- install dir ----------
log "Preparing install directory at ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}/data" "${INSTALL_DIR}/caddy"
chmod 750 "${INSTALL_DIR}"

# ---------- secrets / .env ----------
ENV_FILE="${INSTALL_DIR}/.env"
if [[ -f "${ENV_FILE}" ]] && grep -q '^TSP_SECRET_KEY=' "${ENV_FILE}"; then
  log "Reusing existing TSP_SECRET_KEY from ${ENV_FILE}"
else
  log "Generating new TSP_SECRET_KEY"
  SECRET_KEY="$(openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-64)"
  cat >"${ENV_FILE}" <<EOF
# Generated by install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
TSP_SECRET_KEY=${SECRET_KEY}
TSP_ADMIN_USERNAME=${ADMIN_USERNAME}
TSP_ADMIN_PASSWORD=${ADMIN_PASSWORD}
TSP_ADMIN_EMAIL=${ADMIN_EMAIL}
EOF
  chmod 600 "${ENV_FILE}"
fi

# ---------- Caddyfile (reverse proxy + TLS) ----------
CADDYFILE="${INSTALL_DIR}/caddy/Caddyfile"
if [[ -n "${DOMAIN}" ]]; then
  EFFECTIVE_EMAIL="${ACME_EMAIL:-admin@${DOMAIN}}"
  log "Writing Caddyfile for ${DOMAIN} (Let's Encrypt, contact: ${EFFECTIVE_EMAIL})"
  cat >"${CADDYFILE}" <<EOF
{
    email ${EFFECTIVE_EMAIL}
}

${DOMAIN} {
    encode zstd gzip
    reverse_proxy tsp:8000
}

# Redirect bare-IP / unknown-host HTTP requests to the canonical domain.
:80 {
    redir https://${DOMAIN}{uri} permanent
}
EOF
else
  log "Writing Caddyfile with self-signed TLS (no TSP_DOMAIN set)"
  cat >"${CADDYFILE}" <<'EOF'
{
    # No public domain configured: serve HTTP on :80 and a self-signed cert on :443.
    auto_https off
}

:80 {
    encode zstd gzip
    reverse_proxy tsp:8000
}

:443 {
    tls internal
    encode zstd gzip
    reverse_proxy tsp:8000
}
EOF
fi

# ---------- docker-compose.yml ----------
COMPOSE_FILE="${INSTALL_DIR}/docker-compose.yml"
log "Writing ${COMPOSE_FILE}"
cat >"${COMPOSE_FILE}" <<EOF
services:
  tsp:
    image: ${IMAGE}
    container_name: tspro
    expose:
      - "8000"
    volumes:
      - ./data:/data
      - /proc:/host/proc:ro
      - /etc/os-release:/host/etc/os-release:ro
      - /etc/hostname:/host/etc/hostname:ro
    environment:
      - TSP_SECRET_KEY=\${TSP_SECRET_KEY:?TSP_SECRET_KEY must be set in .env}
      - TSP_ADMIN_USERNAME=\${TSP_ADMIN_USERNAME:-admin}
      - TSP_ADMIN_PASSWORD=\${TSP_ADMIN_PASSWORD:-admin}
      - TSP_ADMIN_EMAIL=\${TSP_ADMIN_EMAIL:-admin@example.com}
      - TSP_HOST_PROC=/host/proc
      - TSP_HOST_ETC=/host/etc
    restart: unless-stopped

  caddy:
    image: caddy:2-alpine
    container_name: tspro-caddy
    depends_on:
      - tsp
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    restart: unless-stopped

  watchtower:
    image: nickfedor/watchtower:latest
    container_name: tspro-watchtower
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - WATCHTOWER_CLEANUP=true
      - WATCHTOWER_INCLUDE_RESTARTING=true
      - WATCHTOWER_POLL_INTERVAL=86400
      - WATCHTOWER_LABEL_ENABLE=false
    restart: unless-stopped

volumes:
  caddy_data:
  caddy_config:
EOF

# ---------- pull + start ----------
log "Pulling images (this may take a moment)"
( cd "${INSTALL_DIR}" && docker compose pull )

log "Starting containers"
( cd "${INSTALL_DIR}" && docker compose up -d )

# ---------- wait for healthy response ----------
log "Waiting for the portal to start responding on localhost..."
for i in $(seq 1 30); do
  if curl -fsS --max-time 2 -o /dev/null http://127.0.0.1/; then
    break
  fi
  sleep 2
done

# ---------- finish ----------
PUBLIC_IP="$(curl -fsS --max-time 3 https://api.ipify.org 2>/dev/null || true)"
LOCAL_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

cat <<EOF

============================================================
  Trusted Servants Pro — install complete
============================================================

  Install dir   : ${INSTALL_DIR}
  Compose file  : ${COMPOSE_FILE}
  Data volume   : ${INSTALL_DIR}/data   (database, uploads, zoom.key)
  Env file      : ${ENV_FILE}           (chmod 600 — keep this safe)

  Open the portal in a browser:
EOF

if [[ -n "${DOMAIN}" ]]; then
  printf '    https://%s\n' "${DOMAIN}"
  printf '\n  DNS reminder: point an A record for %s at this server before browsing,\n' "${DOMAIN}"
  printf '  otherwise the Let'\''s Encrypt certificate will fail to issue.\n'
else
  [[ -n "${LOCAL_IP}"  ]] && printf '    http://%s/    https://%s/\n' "${LOCAL_IP}"  "${LOCAL_IP}"
  [[ -n "${PUBLIC_IP}" && "${PUBLIC_IP}" != "${LOCAL_IP}" ]] && \
      printf '    http://%s/    https://%s/\n' "${PUBLIC_IP}" "${PUBLIC_IP}"

  if [[ -n "${ORIGINAL_DOMAIN}" ]]; then
    printf '\n  Note: requested domain %s was NOT used.\n' "${ORIGINAL_DOMAIN}"
    printf '  Reason: %s\n' "${DOMAIN_FALLBACK_REASON}"
    printf '  The portal is still reachable at the URLs above with a self-signed cert.\n'
    printf '  Fix the DNS (see README — Cloudflare must be DNS-only during issuance)\n'
    printf '  and rerun this installer to switch to Let'\''s Encrypt.\n'
  else
    printf '\n  No TSP_DOMAIN set, so HTTPS uses a self-signed certificate —\n'
    printf '  your browser will show a warning the first time. To use a real cert,\n'
    printf '  rerun this script with TSP_DOMAIN=portal.example.org (DNS must point here first).\n'
  fi
fi

cat <<EOF

  Sign in with the seeded admin account:
    username : ${ADMIN_USERNAME}
    password : ${ADMIN_PASSWORD}

  CHANGE THE ADMIN PASSWORD IMMEDIATELY from Settings -> Users.

  Auto-updates:
    Watchtower is installed and checks Docker Hub every 24 hours.
    New portal releases will be pulled and restarted automatically.

  Useful commands:
    cd ${INSTALL_DIR}
    docker compose ps          # status
    docker compose logs -f     # tail logs
    docker compose pull && docker compose up -d   # force an upgrade now
    docker compose down        # stop

============================================================
EOF
