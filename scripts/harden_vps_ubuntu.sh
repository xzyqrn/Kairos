#!/usr/bin/env bash
set -euo pipefail

ADMIN_USER="${1:-}"
SSH_PORT="${2:-22}"
APP_DIR="${3:-/opt/kairos}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root: sudo bash $0 <admin_user> [ssh_port] [app_dir]" >&2
  exit 1
fi

if [[ -z "${ADMIN_USER}" ]]; then
  echo "Usage: sudo bash $0 <admin_user> [ssh_port] [app_dir]" >&2
  exit 1
fi

if ! [[ "${SSH_PORT}" =~ ^[0-9]+$ ]] || (( SSH_PORT < 1 || SSH_PORT > 65535 )); then
  echo "SSH port must be an integer between 1 and 65535." >&2
  exit 1
fi

if ! id -u "${ADMIN_USER}" >/dev/null 2>&1; then
  echo "User '${ADMIN_USER}' does not exist." >&2
  exit 1
fi

if [[ "${ADMIN_USER}" == "root" ]]; then
  echo "Refusing to harden SSH for root-only access. Create a non-root sudo user first." >&2
  exit 1
fi

ADMIN_HOME="$(getent passwd "${ADMIN_USER}" | cut -d: -f6)"
AUTHORIZED_KEYS="${ADMIN_HOME}/.ssh/authorized_keys"
if [[ ! -s "${AUTHORIZED_KEYS}" ]]; then
  echo "No SSH public key found at ${AUTHORIZED_KEYS}." >&2
  echo "Set up key-based SSH for ${ADMIN_USER} before disabling password login." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  fail2ban \
  ufw \
  unattended-upgrades

install -d -m 755 /etc/fail2ban/jail.d
cat > /etc/fail2ban/jail.d/sshd.local <<EOF
[sshd]
enabled = true
backend = systemd
port = ${SSH_PORT}
maxretry = 5
findtime = 10m
bantime = 1h
EOF

cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

install -d -m 755 /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/60-kairos-hardening.conf <<EOF
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
X11Forwarding no
MaxAuthTries 3
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
Port ${SSH_PORT}
EOF

sshd -t

ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow "${SSH_PORT}/tcp"
ufw --force enable

systemctl enable --now fail2ban
systemctl enable --now apt-daily.timer apt-daily-upgrade.timer
systemctl reload ssh

if [[ -f "${APP_DIR}/.env" ]]; then
  chmod 600 "${APP_DIR}/.env"
fi

cat <<EOF
Hardening complete.

What changed:
- UFW enabled with only TCP ${SSH_PORT} open
- fail2ban enabled for SSH
- unattended security updates enabled
- SSH hardened for key-only login

Important:
1. Open a SECOND terminal now.
2. Verify SSH still works before closing this session:
   ssh -p ${SSH_PORT} ${ADMIN_USER}@YOUR_SERVER_IP
3. Check services:
   sudo fail2ban-client status sshd
   sudo ufw status verbose
EOF
