#!/usr/bin/env bash
# ============================================================================
# One-shot VM bootstrapper. Run this ONCE on a fresh Oracle Always Free VM.
# Idempotent: safe to re-run.
# ============================================================================
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Re-running with sudo..."
  exec sudo -E "$0" "$@"
fi

echo "==> Updating apt and installing prerequisites..."
apt-get update -y
apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg lsb-release ufw git

# --- Docker (official repo) -------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker..."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi

# Allow the default Ubuntu user to run docker without sudo.
DEFAULT_USER="${SUDO_USER:-ubuntu}"
if id "$DEFAULT_USER" >/dev/null 2>&1; then
  usermod -aG docker "$DEFAULT_USER" || true
fi

# --- Firewall ---------------------------------------------------------------
echo "==> Configuring UFW (allow 22, 80, 443)..."
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# --- iptables: Oracle's default Ubuntu image keeps deny rules in iptables ---
# even when ufw is open. Make sure 80/443 are explicitly accepted.
echo "==> Patching iptables..."
iptables -I INPUT -p tcp -m state --state NEW -m tcp --dport 80 -j ACCEPT  || true
iptables -I INPUT -p tcp -m state --state NEW -m tcp --dport 443 -j ACCEPT || true
if command -v netfilter-persistent >/dev/null 2>&1; then
  netfilter-persistent save || true
fi

echo
echo "==> VM bootstrap complete."
echo "    Log out and back in (or run 'newgrp docker') so docker works without sudo."
echo "    Then clone the repo and run deploy/deploy.sh"
