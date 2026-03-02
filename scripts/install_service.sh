#!/bin/bash
# Install E-Ink Frame systemd service
#
# Usage: sudo ./install_service.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="einkframe"

echo "Installing E-Ink Frame Service..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run as root (sudo)"
    exit 1
fi

# Copy service file
cp "$SCRIPT_DIR/${SERVICE_NAME}.service" /etc/systemd/system/
echo "Copied service file"

# Reload systemd
systemctl daemon-reload
echo "Reloaded systemd daemon"

# Enable service (start on boot)
systemctl enable ${SERVICE_NAME}.service
echo "Enabled ${SERVICE_NAME} service"

# Also install recovery service
if [ -f "$SCRIPT_DIR/install_recovery.sh" ]; then
    bash "$SCRIPT_DIR/install_recovery.sh"
fi

echo ""
echo "Installation complete!"
echo ""
echo "Commands:"
echo "  sudo systemctl start ${SERVICE_NAME}    # Start now"
echo "  sudo systemctl stop ${SERVICE_NAME}     # Stop"
echo "  sudo systemctl status ${SERVICE_NAME}   # Check status"
echo "  sudo journalctl -u ${SERVICE_NAME} -f   # View logs"
echo ""
echo "The service will start automatically on next boot."
