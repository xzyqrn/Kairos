#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/opt/kairos}"
APP_USER="${2:-kairos}"
SERVICE_NAME="${3:-kairos}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root: sudo bash $0 [app_dir] [app_user] [service_name]" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICE_TEMPLATE="${REPO_DIR}/deploy/systemd/kairos.service.template"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ ! -f "${REPO_DIR}/main.py" ]]; then
  echo "Could not find main.py. Run this from inside the repo." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  ca-certificates \
  git \
  python3 \
  python3-pip \
  python3-venv \
  rsync \
  sqlite3

if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --shell /bin/bash "${APP_USER}"
fi

mkdir -p "${APP_DIR}"
rsync -a \
  --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  --exclude ".pytest_cache" \
  "${REPO_DIR}/" "${APP_DIR}/"

mkdir -p "${APP_DIR}/data" "${APP_DIR}/logs"

if [[ ! -f "${APP_DIR}/.env" && -f "${APP_DIR}/.env.example" ]]; then
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
fi

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip wheel
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

sed \
  -e "s|__APP_DIR__|${APP_DIR}|g" \
  -e "s|__APP_USER__|${APP_USER}|g" \
  "${SERVICE_TEMPLATE}" > "${SERVICE_PATH}"

chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
chmod 640 "${SERVICE_PATH}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

cat <<EOF
Bootstrap complete.

Next steps:
1. Edit ${APP_DIR}/.env and set DISCORD_TOKEN.
2. Start the bot:
   sudo systemctl start ${SERVICE_NAME}
3. Check logs:
   sudo journalctl -u ${SERVICE_NAME} -f
EOF
