"""Recovery management for AP mode failures."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class RecoveryManager:
    """Handle AP mode recovery mechanisms.

    Creates a recovery flag before AP mode starts and clears it on clean exit.
    If the system crashes during AP mode, the boot recovery script detects
    the flag and restores station mode.
    """

    RECOVERY_FLAG_PATH = Path("/tmp/einkframe_ap_recovery")
    RECOVERY_DATA_PATH = Path("/tmp/einkframe_ap_state.json")

    def __init__(self, enabled: bool = True):
        """Initialize recovery manager.

        Args:
            enabled: Whether recovery is enabled.
        """
        self.enabled = enabled

    def set_recovery_flag(self, ssid: Optional[str] = None) -> None:
        """Set recovery flag before AP mode starts.

        This should be called BEFORE any AP mode changes are made.
        If the system crashes, the boot recovery script will detect this flag.

        Args:
            ssid: Previous WiFi SSID to restore on recovery.
        """
        if not self.enabled:
            logger.debug("Recovery disabled, skipping flag set")
            return

        recovery_data = {
            "timestamp": time.time(),
            "pid": os.getpid(),
            "ssid": ssid or "",
        }

        try:
            self.RECOVERY_FLAG_PATH.touch()
            self.RECOVERY_DATA_PATH.write_text(json.dumps(recovery_data))
            logger.info("Recovery flag set")
        except Exception as e:
            logger.error(f"Failed to set recovery flag: {e}")

    def clear_recovery_flag(self) -> None:
        """Clear recovery flag after clean AP mode exit.

        This should be called AFTER AP mode has been successfully stopped.
        """
        if not self.enabled:
            return

        try:
            self.RECOVERY_FLAG_PATH.unlink(missing_ok=True)
            self.RECOVERY_DATA_PATH.unlink(missing_ok=True)
            logger.info("Recovery flag cleared")
        except Exception as e:
            logger.error(f"Failed to clear recovery flag: {e}")

    def check_recovery_needed(self) -> bool:
        """Check if recovery is needed (called on boot).

        Returns:
            True if recovery flag exists (previous AP mode crashed).
        """
        return self.RECOVERY_FLAG_PATH.exists()

    def get_recovery_data(self) -> dict:
        """Get recovery data if available.

        Returns:
            Recovery data dictionary or empty dict.
        """
        if not self.RECOVERY_DATA_PATH.exists():
            return {}

        try:
            return json.loads(self.RECOVERY_DATA_PATH.read_text())
        except Exception:
            return {}

    def perform_recovery(self) -> bool:
        """Perform recovery: stop any AP mode, restore station mode.

        Returns:
            True if recovery was performed.
        """
        if not self.check_recovery_needed():
            logger.debug("No recovery needed")
            return False

        logger.warning("Performing AP mode recovery...")

        # 1. Try to stop any hotspot
        try:
            subprocess.run(
                ["nmcli", "connection", "down", "Hotspot"],
                capture_output=True,
                timeout=10,
            )
            logger.info("Stopped hotspot")
        except Exception as e:
            logger.warning(f"Failed to stop hotspot: {e}")

        # 2. Try to restore previous connection
        data = self.get_recovery_data()
        ssid = data.get("ssid")
        if ssid:
            try:
                result = subprocess.run(
                    ["nmcli", "connection", "up", ssid],
                    capture_output=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    logger.info(f"Restored connection to: {ssid}")
                else:
                    logger.warning(f"Failed to restore connection to: {ssid}")
            except Exception as e:
                logger.warning(f"Failed to restore connection: {e}")

        # 3. Clear flags
        self.clear_recovery_flag()

        logger.info("Recovery complete")
        return True


# Global instance
_recovery_manager: Optional[RecoveryManager] = None


def get_recovery_manager() -> RecoveryManager:
    """Get global recovery manager instance."""
    global _recovery_manager
    if _recovery_manager is None:
        from config import get_config

        config = get_config()
        _recovery_manager = RecoveryManager(
            enabled=config.get("web_ui.recovery_enabled", True)
        )
    return _recovery_manager
