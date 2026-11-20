#!/usr/bin/env bash
# ==============================================================================
# Freelancer Agency - Server Environment Provisioning & Setup Script
# Designed for Linux / Oracle Cloud Always Free VM (Ubuntu 22.04 / 24.04 LTS)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CURRENT_USER="$(id -un)"
PYTHON_BIN="$(command -v python3 || true)"

echo "=== Freelancer Agency Server Setup ==="
echo "Target Directory: ${PROJECT_ROOT}"
echo "Current User:     ${CURRENT_USER}"
echo "Python Binary:    ${PYTHON_BIN}"
echo "--------------------------------------"

if [ -z "${PYTHON_BIN}" ]; then
    echo "[ERROR] Python 3 was not found on PATH. Please install python3 first."
    exit 1
fi

# 1. Create required runtime directories
echo "[*] Creating data and log directories..."
mkdir -p "${PROJECT_ROOT}/data"
mkdir -p "${PROJECT_ROOT}/logs"

# 2. Setup environment file template if missing
if [ ! -f "${PROJECT_ROOT}/.env.local" ]; then
    if [ -f "${PROJECT_ROOT}/.env.example" ]; then
        echo "[*] Creating .env.local from .env.example..."
        cp "${PROJECT_ROOT}/.env.example" "${PROJECT_ROOT}/.env.local"
        chmod 600 "${PROJECT_ROOT}/.env.local"
        echo "[!] Remember to update ${PROJECT_ROOT}/.env.local with your real Telegram Bot Token and Chat ID."
    fi
else
    echo "[*] Existing .env.local detected. Preserving existing credentials."
fi

# 3. Generate production systemd unit tailored to this host
SERVICE_FILE="${PROJECT_ROOT}/agency.service"
echo "[*] Generating production systemd unit (${SERVICE_FILE})..."
cat <<EOF > "${SERVICE_FILE}"
[Unit]
Description=Freelancer Agency Autonomous Daemon
After=network.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${PROJECT_ROOT}
Environment="PYTHONUNBUFFERED=1"
EnvironmentFile=${PROJECT_ROOT}/.env.local
ExecStart=${PYTHON_BIN} ${PROJECT_ROOT}/run_agency.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "[*] Running local offline healthcheck..."
${PYTHON_BIN} "${SCRIPT_DIR}/healthcheck.py" --offline || true

echo "--------------------------------------"
echo "Setup preparation complete."
echo "To install and activate the systemd service, run the following commands:"
echo ""
echo "sudo cp ${SERVICE_FILE} /etc/systemd/system/agency.service"
echo "sudo systemctl daemon-reload"
echo "sudo systemctl enable --now agency.service"
echo "sudo systemctl status agency.service"
echo ""
echo "To monitor live logs in real time:"
echo "journalctl -u agency.service -f"
