"""WiFi management module using NetworkManager (nmcli)."""

from __future__ import annotations

import subprocess
import shutil
from dataclasses import dataclass
from typing import Optional, List, Dict


@dataclass
class WifiNetwork:
    """WiFi network information."""

    ssid: str
    signal: int  # Signal strength in percentage
    security: str  # open / wpa / wpa2 / wpa3


@dataclass
class WifiStatus:
    """Current WiFi connection status."""

    connected: bool
    ssid: Optional[str]
    ip_address: Optional[str]


class WifiManager:
    """Manage WiFi connections using NetworkManager."""

    def __init__(self):
        """Initialize WiFi manager."""
        self._nmcli_available = shutil.which("nmcli") is not None

    @property
    def is_available(self) -> bool:
        """Check if NetworkManager is available."""
        return self._nmcli_available

    def scan(self) -> List[WifiNetwork]:
        """Scan for available WiFi networks.

        Returns:
            List of available WiFi networks sorted by signal strength.
        """
        if not self._nmcli_available:
            return self._mock_scan()

        try:
            # Trigger a fresh scan
            subprocess.run(
                ["nmcli", "device", "wifi", "rescan"],
                capture_output=True,
                timeout=10,
            )

            # Get scan results
            # Format: SSID:SIGNAL:SECURITY
            result = subprocess.run(
                ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return []

            networks: Dict[str, WifiNetwork] = {}

            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue

                parts = line.split(":")
                if len(parts) < 3:
                    continue

                ssid = parts[0].strip()
                if not ssid:  # Skip hidden networks
                    continue

                try:
                    signal = int(parts[1])
                except ValueError:
                    signal = 0

                security_raw = parts[2].strip().upper() if len(parts) > 2 else ""
                security = self._parse_security(security_raw)

                # Keep the strongest signal for duplicate SSIDs
                if ssid not in networks or networks[ssid].signal < signal:
                    networks[ssid] = WifiNetwork(
                        ssid=ssid,
                        signal=signal,
                        security=security,
                    )

            # Sort by signal strength (descending)
            return sorted(networks.values(), key=lambda n: n.signal, reverse=True)

        except subprocess.TimeoutExpired:
            return []
        except Exception:
            return []

    def get_status(self) -> WifiStatus:
        """Get current WiFi connection status.

        Returns:
            Current WiFi connection status.
        """
        if not self._nmcli_available:
            return WifiStatus(connected=False, ssid=None, ip_address=None)

        try:
            # Get connection status
            result = subprocess.run(
                ["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            connected = False
            ssid = None

            for line in result.stdout.strip().split("\n"):
                if line.startswith("yes:"):
                    connected = True
                    ssid = line.split(":", 1)[1] if ":" in line else None
                    break

            # Get IP address if connected
            ip_address = None
            if connected:
                ip_result = subprocess.run(
                    ["nmcli", "-t", "-f", "IP4.ADDRESS", "device", "show", "wlan0"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                for line in ip_result.stdout.strip().split("\n"):
                    if line.startswith("IP4.ADDRESS"):
                        ip_address = line.split(":", 1)[1].split("/")[0]
                        break

            return WifiStatus(connected=connected, ssid=ssid, ip_address=ip_address)

        except Exception:
            return WifiStatus(connected=False, ssid=None, ip_address=None)

    def connect(self, ssid: str, password: str = "") -> bool:
        """Connect to a WiFi network.

        Args:
            ssid: Network SSID
            password: Network password (empty for open networks)

        Returns:
            True if connection successful, False otherwise.
        """
        if not self._nmcli_available:
            return False

        try:
            # Build command
            cmd = ["nmcli", "device", "wifi", "connect", ssid]
            if password:
                cmd.extend(["password", password])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            return result.returncode == 0

        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    def disconnect(self) -> bool:
        """Disconnect from current WiFi network.

        Returns:
            True if disconnection successful, False otherwise.
        """
        if not self._nmcli_available:
            return False

        try:
            result = subprocess.run(
                ["nmcli", "device", "disconnect", "wlan0"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _parse_security(self, security_raw: str) -> str:
        """Parse security type from nmcli output."""
        if not security_raw or security_raw == "--":
            return "open"
        elif "WPA3" in security_raw:
            return "wpa3"
        elif "WPA2" in security_raw:
            return "wpa2"
        elif "WPA" in security_raw:
            return "wpa"
        elif "WEP" in security_raw:
            return "wep"
        else:
            return "open"

    def _mock_scan(self) -> List[WifiNetwork]:
        """Return mock data for development on non-Pi machines."""
        return [
            WifiNetwork(ssid="MyHomeWiFi", signal=85, security="wpa2"),
            WifiNetwork(ssid="Neighbor_5G", signal=62, security="wpa2"),
            WifiNetwork(ssid="CoffeeShop_Free", signal=45, security="open"),
            WifiNetwork(ssid="Office_Network", signal=30, security="wpa3"),
        ]


# Global instance
_wifi_manager: Optional[WifiManager] = None


def get_wifi_manager() -> WifiManager:
    """Get global WiFi manager instance."""
    global _wifi_manager
    if _wifi_manager is None:
        _wifi_manager = WifiManager()
    return _wifi_manager
