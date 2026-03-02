#!/bin/bash
# Install AP Mode Recovery Service
#
# This script installs the systemd service that runs the recovery script on boot.
# Run with sudo: sudo ./install_recovery.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="einkframe-recovery"

echo "Installing E-Ink Frame AP Recovery Service..."
echo "Project directory: $PROJECT_DIR"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run as root (sudo)"
    exit 1
fi

# Make recovery script executable
chmod +x "$SCRIPT_DIR/ap_recovery.sh"
echo "Made ap_recovery.sh executable"

# Create systemd service file
cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=E-Ink Frame AP Recovery
After=NetworkManager.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=${SCRIPT_DIR}/ap_recovery.sh
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "Created systemd service file"

# Reload systemd
systemctl daemon-reload
echo "Reloaded systemd daemon"

# Enable service
systemctl enable ${SERVICE_NAME}.service
echo "Enabled ${SERVICE_NAME} service"

# Create log file with proper permissions
touch /var/log/einkframe_recovery.log
chmod 644 /var/log/einkframe_recovery.log
echo "Created log file"

echo ""
echo "Installation complete!"
echo ""
echo "The recovery service will run on boot to check for crashed AP mode."
echo "To test the service manually: sudo systemctl start ${SERVICE_NAME}"
echo "To view logs: journalctl -u ${SERVICE_NAME} or cat /var/log/einkframe_recovery.log"
