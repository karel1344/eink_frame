"""Startup sequence with WiFi connection and AP mode fallback."""

from __future__ import annotations

import logging
import time
from typing import Optional

from .config import get_config
from .wifi.manager import get_wifi_manager
from .wifi.ap_mode import get_ap_manager
from .wifi.recovery import get_recovery_manager

logger = logging.getLogger(__name__)


class StartupManager:
    """Manage startup sequence with WiFi fallback to AP mode."""

    def __init__(
        self,
        connection_timeout: Optional[int] = None,
        retry_count: Optional[int] = None,
    ):
        """Initialize startup manager.

        Args:
            connection_timeout: WiFi connection timeout in seconds.
            retry_count: Number of connection retries.
        """
        self.config = get_config()
        self.wifi = get_wifi_manager()
        self.ap = get_ap_manager()
        self.recovery = get_recovery_manager()

        self.connection_timeout = connection_timeout or self.config.get(
            "wifi.connection_timeout", 30
        )
        self.retry_count = retry_count or self.config.get("wifi.retry_count", 3)

    def run(self) -> str:
        """Run startup sequence.

        Returns:
            Final state: "wifi_connected", "ap_mode", or "offline"
        """
        logger.info("=== Starting E-Ink Frame ===")

        # 1. Check if recovery is needed from previous crash
        if self.recovery.check_recovery_needed():
            logger.warning("Recovery flag detected from previous session")
            self.recovery.perform_recovery()

        # 2. Check if WiFi is enabled
        if not self.config.wifi_enabled:
            logger.info("WiFi disabled, running in offline mode")
            return "offline"

        # 3. Check if already connected to WiFi
        status = self.wifi.get_status()
        if status.connected:
            logger.info(f"Already connected to WiFi: {status.ssid}")
            return "wifi_connected"

        # 4. Check if WiFi credentials are configured
        ssid = self.config.wifi_ssid
        if not ssid:
            logger.info("No WiFi configured and not connected, starting AP mode")
            return self._start_ap_mode("no_wifi_configured")

        # 5. Try to connect to WiFi
        logger.info(f"Attempting to connect to WiFi: {ssid}")
        connected = self._try_wifi_connection(ssid)

        if connected:
            logger.info(f"Successfully connected to WiFi: {ssid}")
            return "wifi_connected"
        else:
            logger.warning(f"Failed to connect to WiFi after {self.retry_count} attempts")
            return self._start_ap_mode("wifi_connection_failed")

    def _try_wifi_connection(self, ssid: str) -> bool:
        """Try to connect to WiFi with retries.

        Args:
            ssid: WiFi SSID to connect to.

        Returns:
            True if connected successfully.
        """
        password = self.config.wifi_password

        for attempt in range(1, self.retry_count + 1):
            logger.info(f"WiFi connection attempt {attempt}/{self.retry_count}")

            # Check if already connected
            status = self.wifi.get_status()
            if status.connected and status.ssid == ssid:
                logger.info("Already connected to target WiFi")
                return True

            # Try to connect
            success = self.wifi.connect(ssid, password)

            if success:
                # Verify connection
                time.sleep(2)  # Wait for connection to stabilize
                status = self.wifi.get_status()
                if status.connected:
                    return True

            # Wait before retry
            if attempt < self.retry_count:
                wait_time = min(5 * attempt, 15)  # 5s, 10s, 15s...
                logger.info(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)

        return False

    def _start_ap_mode(self, reason: str) -> str:
        """Start AP mode as fallback.

        Args:
            reason: Reason for starting AP mode.

        Returns:
            "ap_mode" if successful, "offline" if failed.
        """
        logger.info(f"Starting AP mode (reason: {reason})")

        success = self.ap.start()

        if success:
            logger.info(f"AP mode started: {self.ap.ssid}")
            return "ap_mode"
        else:
            logger.error("Failed to start AP mode")
            return "offline"


def run_startup() -> str:
    """Run startup sequence.

    Returns:
        Final state: "wifi_connected", "ap_mode", or "offline"
    """
    manager = StartupManager()
    return manager.run()
