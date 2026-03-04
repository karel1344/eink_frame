#!/bin/bash
# Install E-Ink Frame systemd service
#
# Usage: sudo ./install_service.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
SERVICE_NAME="einkframe"

echo "Installing E-Ink Frame Service..."
echo "Project directory: $PROJECT_DIR"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run as root (sudo)"
    exit 1
fi

# Create venv if not exists
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$PROJECT_DIR/venv"
    echo "Virtual environment created"
fi

# Upgrade pip
echo "Upgrading pip..."
"$PROJECT_DIR/venv/bin/pip" install --upgrade pip

# Install dependencies from requirements.txt
REQUIREMENTS_FILE="$PROJECT_DIR/requirements.txt"
if [ -f "$REQUIREMENTS_FILE" ]; then
    echo "Installing dependencies from requirements.txt..."
    "$PROJECT_DIR/venv/bin/pip" install -r "$REQUIREMENTS_FILE"
    echo "Dependencies installed"
else
    echo "Warning: requirements.txt not found at $REQUIREMENTS_FILE"
fi

# Stop service if currently running (before overwriting unit file)
if systemctl is-active --quiet ${SERVICE_NAME}.service; then
    echo "Stopping running ${SERVICE_NAME} service..."
    systemctl stop ${SERVICE_NAME}.service
    echo "Service stopped"
fi

# Generate service file from current paths
cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=E-Ink Photo Frame
After=network-online.target NetworkManager.service
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${PROJECT_DIR}
ExecStart=${VENV_PYTHON} ${PROJECT_DIR}/einkframe.py
Restart=on-failure
RestartSec=10

# Environment
Environment=PYTHONUNBUFFERED=1

# Logging
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "Generated service file"

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

# Start service now
echo "Starting ${SERVICE_NAME} service..."
systemctl start ${SERVICE_NAME}.service
echo "Service started"

echo ""
echo "Installation complete!"
echo ""
echo "Commands:"
echo "  sudo systemctl stop ${SERVICE_NAME}     # Stop"
echo "  sudo systemctl restart ${SERVICE_NAME}  # Restart"
echo "  sudo systemctl status ${SERVICE_NAME}   # Check status"
echo "  sudo journalctl -u ${SERVICE_NAME} -f   # View logs"
echo ""
echo "The service is now running and will start automatically on boot."
