#!/bin/bash
# AP Mode Recovery Script
# Runs on boot to recover from crashed AP mode
#
# If the system crashed during AP mode, this script detects the recovery flag
# and restores the previous WiFi connection.

set -e

RECOVERY_FLAG="/tmp/einkframe_ap_recovery"
RECOVERY_DATA="/tmp/einkframe_ap_state.json"
LOG_FILE="/var/log/einkframe_recovery.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"
}

# Check if recovery is needed
if [ ! -f "$RECOVERY_FLAG" ]; then
    log "No recovery needed"
    exit 0
fi

log "=========================================="
log "Recovery flag detected, performing recovery..."

# 1. Stop any hotspot (both secured and open)
log "Stopping any active hotspot..."
nmcli connection down Hotspot 2>/dev/null || true
nmcli connection down EinkFrame-Open 2>/dev/null || true
sleep 2

# 2. Try to restore previous connection
if [ -f "$RECOVERY_DATA" ]; then
    SSID=$(python3 -c "import sys,json; print(json.load(open('$RECOVERY_DATA')).get('ssid',''))" 2>/dev/null || echo "")
    if [ -n "$SSID" ]; then
        log "Attempting to reconnect to: $SSID"
        if nmcli connection up "$SSID" 2>/dev/null; then
            log "Successfully reconnected to: $SSID"
        else
            log "Failed to reconnect to: $SSID"
            # Try to connect to any known network
            log "Trying to connect to any saved network..."
            nmcli device wifi connect 2>/dev/null || true
        fi
    else
        log "No previous SSID found in recovery data"
    fi
else
    log "No recovery data file found"
fi

# 3. Clean up flags
log "Cleaning up recovery flags..."
rm -f "$RECOVERY_FLAG" "$RECOVERY_DATA"

log "Recovery complete"
log "=========================================="
exit 0
