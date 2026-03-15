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

# Install system packages required for GPIO, I2C, and fonts
echo "Installing system packages..."
apt-get update -qq
apt-get install -y \
    python3-venv \
    python3-lgpio \
    liblgpio-dev \
    i2c-tools \
    fonts-noto-cjk
echo "System packages installed"

# Enable I2C if not already enabled
if ! grep -q "^dtparam=i2c_arm=on" /boot/firmware/config.txt 2>/dev/null && \
   ! grep -q "^dtparam=i2c_arm=on" /boot/config.txt 2>/dev/null; then
    echo "Enabling I2C in /boot/firmware/config.txt..."
    echo "dtparam=i2c_arm=on" >> /boot/firmware/config.txt
    echo "I2C enabled (reboot required for first-time setup)"
fi

# Add lgpio system package path to venv so pip-built lgpio isn't needed
SYSTEM_PKGS_PATH="/usr/lib/python3/dist-packages"
PTH_FILE="$PROJECT_DIR/venv/lib/python3.$(python3 -c 'import sys; print(sys.version_info.minor)')/site-packages/system.pth"

# Create venv if not exists
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$PROJECT_DIR/venv"
    echo "Virtual environment created"
fi

# Expose system lgpio to venv (avoids building from source)
if [ ! -f "$PTH_FILE" ] || ! grep -q "$SYSTEM_PKGS_PATH" "$PTH_FILE"; then
    echo "$SYSTEM_PKGS_PATH" >> "$PTH_FILE"
    echo "Linked system lgpio into venv"
fi

# Upgrade pip
echo "Upgrading pip..."
"$PROJECT_DIR/venv/bin/pip" install --upgrade pip

# Install dependencies from requirements.txt (lgpio excluded — provided by system package)
REQUIREMENTS_FILE="$PROJECT_DIR/requirements.txt"
if [ -f "$REQUIREMENTS_FILE" ]; then
    echo "Installing dependencies from requirements.txt..."
    grep -v '^\s*lgpio' "$REQUIREMENTS_FILE" | "$PROJECT_DIR/venv/bin/pip" install -r /dev/stdin
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
