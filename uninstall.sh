#!/usr/bin/env bash
#
# Trusted Servants Pro — uninstaller.
#
# Leaves the system as blank as possible: stops and removes the TSP
# containers, wipes every Caddy/Let's Encrypt volume, deletes the
# installer-pulled Docker images, reverts the 80/443 UFW rules, and
# removes the install directory (including ./data unless --keep-data).
# Docker itself is only removed if --remove-docker is passed.
#
# Usage:
#
#   sudo bash uninstall.sh [flags]
#
# Flags:
#   -y, --yes              Skip the confirmation prompt.
#   --keep-data            Preserve ${INSTALL_DIR}/data (DB, uploads, zoom.key).
#   --keep-images          Keep the pulled Docker images (default: remove them).
#   --keep-ufw             Keep the UFW allow-rules for 80/tcp & 443/tcp
#                          (default: revert them; OpenSSH is never touched).
#   --remove-docker        Also uninstall Docker Engine + Compose plugin and
#                          the apt source/keyring the installer added.
#   --nuke                 Shorthand that additionally passes --remove-docker.
#                          (Does NOT imply --yes.)
#
# Environment:
#   TSP_INSTALL_DIR   Install directory (default: /opt/tspro — must match installer)
#

set -euo pipefail

# ---------- config ----------
INSTALL_DIR="${TSP_INSTALL_DIR:-/opt/tspro}"

ASSUME_YES=0
KEEP_DATA=0
# Aggressive-by-default cleanup so cert/domain setups can be re-run from scratch.
PURGE_IMAGES=1
REMOVE_UFW=1
REMOVE_DOCKER=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes)           ASSUME_YES=1 ;;
    --keep-data)        KEEP_DATA=1 ;;
    --keep-images)      PURGE_IMAGES=0 ;;
    --keep-ufw)         REMOVE_UFW=0 ;;
    # Back-compat with earlier flag names (they were opt-in; now default).
    --purge-images)     PURGE_IMAGES=1 ;;
    --remove-ufw-rules) REMOVE_UFW=1 ;;
    --remove-docker)    REMOVE_DOCKER=1 ;;
    --nuke)             REMOVE_DOCKER=1 ;;
    -h|--help)
      sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)  printf 'Unknown flag: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

log()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m!! \033[0m %s\n' "$*" >&2; }
fail() { printf '\n\033[1;31mXX \033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "This uninstaller must be run as root (try: sudo bash uninstall.sh)"

# ---------- confirmation ----------
printf '\nThis will remove Trusted Servants Pro from this server:\n'
printf '  - Stop and remove containers: tspro, tspro-caddy, tspro-watchtower\n'
printf '  - Wipe Caddy volumes:         ALL Let'\''s Encrypt certs, ACME account\n'
printf '                                data, and Caddy config are deleted so a\n'
printf '                                fresh install can re-issue from scratch.\n'
if [[ "${KEEP_DATA}" -eq 1 ]]; then
  printf '  - Remove install dir:         %s  (data/ preserved)\n' "${INSTALL_DIR}"
else
  printf '  - Remove install dir:         %s  (INCLUDING data/ — DB + uploads)\n' "${INSTALL_DIR}"
fi
[[ "${PURGE_IMAGES}" -eq 1 ]] && printf '  - Remove Docker images:       tsp, caddy:2-alpine, watchtower\n'
[[ "${REMOVE_UFW}"   -eq 1 ]] && printf '  - Revert UFW rules:           deny 80/tcp, 443/tcp\n'
[[ "${REMOVE_DOCKER}" -eq 1 ]] && printf '  - Uninstall Docker Engine:    docker-ce and friends, apt source\n'

if [[ "${ASSUME_YES}" -ne 1 ]]; then
  PROMPT_FD=""
  if [[ -t 0 ]]; then
    PROMPT_FD=0
  elif [[ -r /dev/tty ]]; then
    exec 3</dev/tty
    PROMPT_FD=3
  else
    fail "No TTY available for confirmation. Re-run with --yes to proceed non-interactively."
  fi
  printf '\nType "yes" to proceed: '
  read -r CONFIRM <&${PROMPT_FD} || CONFIRM=""
  [[ "${CONFIRM}" == "yes" ]] || { printf 'Aborted.\n'; exit 1; }
fi

# ---------- stop + remove containers ----------
if command -v docker >/dev/null 2>&1; then
  if [[ -f "${INSTALL_DIR}/docker-compose.yml" ]]; then
    log "Stopping compose stack in ${INSTALL_DIR}"
    ( cd "${INSTALL_DIR}" && docker compose down --volumes --remove-orphans ) || \
      warn "docker compose down reported an error — falling back to direct removal"
  fi

  # Defensive: remove by name in case compose metadata is gone.
  for c in tspro tspro-caddy tspro-watchtower; do
    if docker ps -a --format '{{.Names}}' | grep -qx "$c"; then
      log "Removing container: $c"
      docker rm -f "$c" >/dev/null || warn "Failed to remove container $c"
    fi
  done

  # Wipe every Caddy-related volume so Let's Encrypt certs, the ACME account
  # JSON, and any cached issuance state are gone. Docker-compose prefixes named
  # volumes with the project dir name, and stray volumes from prior aborted
  # installs can have arbitrary prefixes — sweep anything that ends in
  # caddy_data / caddy_config or contains 'caddy' in the name.
  log "Removing Caddy volumes (Let's Encrypt certs + ACME account data)"
  mapfile -t VOLS < <(docker volume ls --format '{{.Name}}' \
      | grep -E '(^|[/_-])caddy([/_-]|$)' || true)
  if [[ "${#VOLS[@]}" -eq 0 ]]; then
    printf '   (no caddy volumes found)\n'
  fi
  for v in "${VOLS[@]}"; do
    docker volume rm "$v" >/dev/null && printf '   removed volume: %s\n' "$v" || \
      warn "Failed to remove volume $v (may still be in use)"
  done

  if [[ "${PURGE_IMAGES}" -eq 1 ]]; then
    log "Removing Docker images pulled by the installer"
    for img in \
        "$(grep -E '^\s*image:' "${INSTALL_DIR}/docker-compose.yml" 2>/dev/null | awk '{print $2}')" \
        viibeware/trusted-servants-pro:latest \
        caddy:2-alpine \
        nickfedor/watchtower:latest
    do
      [[ -z "$img" ]] && continue
      if docker image inspect "$img" >/dev/null 2>&1; then
        docker image rm "$img" >/dev/null && printf '   removed image: %s\n' "$img" || \
          warn "Failed to remove image $img (it may still be in use)"
      fi
    done
  fi
else
  warn "docker not installed — skipping container/volume/image cleanup"
fi

# ---------- remove install dir ----------
if [[ -d "${INSTALL_DIR}" ]]; then
  if [[ "${KEEP_DATA}" -eq 1 && -d "${INSTALL_DIR}/data" ]]; then
    log "Removing ${INSTALL_DIR} contents but preserving data/"
    shopt -s dotglob nullglob
    for entry in "${INSTALL_DIR}"/*; do
      [[ "$(basename "$entry")" == "data" ]] && continue
      rm -rf -- "$entry"
    done
    shopt -u dotglob nullglob
    printf '   data preserved at: %s/data\n' "${INSTALL_DIR}"
  else
    log "Removing install directory: ${INSTALL_DIR}"
    rm -rf -- "${INSTALL_DIR}"
  fi
else
  warn "Install directory ${INSTALL_DIR} not found — nothing to remove there"
fi

# ---------- ufw rules ----------
if [[ "${REMOVE_UFW}" -eq 1 ]]; then
  if command -v ufw >/dev/null 2>&1; then
    log "Reverting UFW rules for 80/tcp and 443/tcp (leaving OpenSSH intact)"
    ufw delete allow 80/tcp  >/dev/null 2>&1 || true
    ufw delete allow 443/tcp >/dev/null 2>&1 || true
    ufw reload               >/dev/null 2>&1 || true
  else
    warn "ufw not installed — skipping firewall cleanup"
  fi
fi

# ---------- docker engine ----------
if [[ "${REMOVE_DOCKER}" -eq 1 ]]; then
  if command -v apt-get >/dev/null 2>&1; then
    log "Uninstalling Docker Engine and Compose plugin"
    export DEBIAN_FRONTEND=noninteractive
    apt-get purge -y docker-ce docker-ce-cli containerd.io \
                     docker-buildx-plugin docker-compose-plugin || \
      warn "apt-get purge of docker packages reported an error"
    apt-get autoremove -y --purge || true

    log "Removing Docker apt source and keyring added by the installer"
    rm -f /etc/apt/sources.list.d/docker.list
    rm -f /etc/apt/keyrings/docker.gpg

    log "Removing /var/lib/docker and /var/lib/containerd"
    rm -rf /var/lib/docker /var/lib/containerd
  else
    warn "apt-get not found — cannot uninstall Docker packages automatically"
  fi
fi

# ---------- done ----------
cat <<EOF

============================================================
  Trusted Servants Pro — uninstall complete
============================================================

  Removed: TSP containers, all Caddy volumes (ACME account +
           Let's Encrypt certs), and ${INSTALL_DIR}$( [[ "${KEEP_DATA}" -eq 1 ]] && printf ' (data kept)' )
$( [[ "${PURGE_IMAGES}" -eq 1 ]] && printf '  Removed: Docker images (tsp, caddy, watchtower)\n' )$( [[ "${REMOVE_UFW}"   -eq 1 ]] && printf '  Reverted: UFW 80/tcp and 443/tcp rules\n' )$( [[ "${REMOVE_DOCKER}" -eq 1 ]] && printf '  Removed: Docker Engine + /var/lib/docker\n' )
  Not touched: base packages (curl, jq, openssl, ufw, …),
               OpenSSH firewall rule, and any unrelated containers.

  A subsequent install.sh run will start from a clean slate:
  Caddy will request a brand-new Let's Encrypt certificate for
  whatever TSP_DOMAIN you set. Note: Let's Encrypt enforces
  per-domain rate limits (5 duplicate certs/week) that can't be
  reset by an uninstall — use a staging issuer if iterating.

============================================================
EOF
