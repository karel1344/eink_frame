"""AP mode management using NetworkManager hotspot."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, List, Optional

from .recovery import RecoveryManager, get_recovery_manager

logger = logging.getLogger(__name__)


class ExecutionMode(Enum):
    """Execution modes for AP operations.

    DRY_RUN: Log commands but don't execute (for Mac/PC testing)
    PREVIEW: Print commands to stdout, don't execute (for Pi verification)
    SAFE: Execute with short timeout (60s) for initial Pi testing
    NORMAL: Full execution with configured timeout (production)
    """

    DRY_RUN = "dry_run"
    PREVIEW = "preview"
    SAFE = "safe"
    NORMAL = "normal"


@dataclass
class CommandResult:
    """Result of a command execution."""

    command: List[str]
    success: bool
    stdout: str
    stderr: str
    executed: bool  # False if dry-run/preview mode


class CommandExecutor:
    """Execute system commands with mode-aware behavior."""

    def __init__(self, mode: ExecutionMode):
        """Initialize command executor.

        Args:
            mode: Execution mode (dry_run, preview, safe, normal).
        """
        self.mode = mode

    def run(
        self,
        cmd: List[str],
        description: str,
        timeout: int = 30,
    ) -> CommandResult:
        """Run command based on execution mode.

        Args:
            cmd: Command and arguments as list.
            description: Human-readable description of the command.
            timeout: Command timeout in seconds.

        Returns:
            CommandResult with execution details.
        """
        cmd_str = " ".join(cmd)

        if self.mode == ExecutionMode.DRY_RUN:
            logger.info(f"[DRY-RUN] Would execute: {cmd_str}")
            return CommandResult(
                command=cmd,
                success=True,
                stdout="",
                stderr="",
                executed=False,
            )

        elif self.mode == ExecutionMode.PREVIEW:
            print(f"[PREVIEW] {description}")
            print(f"  Command: {cmd_str}")
            return CommandResult(
                command=cmd,
                success=True,
                stdout="",
                stderr="",
                executed=False,
            )

        else:  # SAFE or NORMAL
            logger.info(f"Executing: {cmd_str}")
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                success = result.returncode == 0
                if not success:
                    logger.warning(f"Command failed: {result.stderr}")
                return CommandResult(
                    command=cmd,
                    success=success,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    executed=True,
                )
            except subprocess.TimeoutExpired:
                logger.error(f"Command timed out after {timeout}s")
                return CommandResult(
                    command=cmd,
                    success=False,
                    stdout="",
                    stderr="Command timed out",
                    executed=True,
                )
            except Exception as e:
                logger.error(f"Command execution failed: {e}")
                return CommandResult(
                    command=cmd,
                    success=False,
                    stdout="",
                    stderr=str(e),
                    executed=True,
                )


@dataclass
class APStatus:
    """AP mode status."""

    active: bool
    ssid: Optional[str]
    elapsed_seconds: float
    timeout_remaining: float
    execution_mode: str


class APModeManager:
    """Manage AP mode lifecycle with safety mechanisms.

    Uses NetworkManager's built-in hotspot functionality instead of
    hostapd for simpler management and better integration with existing
    WiFi manager.
    """

    # NetworkManager's default hotspot IP
    AP_IP = "10.42.0.1"

    def __init__(
        self,
        mode: Optional[ExecutionMode] = None,
        timeout: Optional[int] = None,
        ssid_prefix: str = "EinkFrame",
        password: str = "",
        on_timeout: Optional[Callable[[], None]] = None,
    ):
        """Initialize AP mode manager.

        Args:
            mode: Execution mode. If None, reads from config.
            timeout: AP timeout in seconds. If None, reads from config.
            ssid_prefix: SSID prefix (device ID appended).
            password: AP password (empty for open network).
            on_timeout: Callback when timeout occurs.
        """
        self._mode = mode
        self._timeout = timeout
        self._ssid_prefix = ssid_prefix
        self._password = password
        self._on_timeout = on_timeout

        self._executor: Optional[CommandExecutor] = None
        self._recovery: Optional[RecoveryManager] = None
        self._active = False
        self._ssid: Optional[str] = None
        self._start_time: Optional[float] = None
        self._timeout_timer: Optional[threading.Timer] = None
        self._previous_ssid: Optional[str] = None

    def _init_from_config(self) -> None:
        """Initialize settings from config if not provided."""
        from ..config import get_config

        config = get_config()

        if self._mode is None:
            mode_str = config.get("web_ui.ap_execution_mode", "normal")
            try:
                self._mode = ExecutionMode(mode_str)
            except ValueError:
                logger.warning(f"Invalid execution mode: {mode_str}, using normal")
                self._mode = ExecutionMode.NORMAL

        if self._timeout is None:
            if self._mode == ExecutionMode.SAFE:
                self._timeout = config.get("web_ui.ap_safe_timeout", 60)
            else:
                self._timeout = config.get("web_ui.timeout", 600)

        if self._ssid_prefix == "EinkFrame":
            self._ssid_prefix = config.get("web_ui.ap_ssid_prefix", "EinkFrame")

        if self._password == "":
            self._password = config.get("web_ui.ap_password", "")

        self._executor = CommandExecutor(self._mode)
        self._recovery = get_recovery_manager()

    @property
    def mode(self) -> ExecutionMode:
        """Get execution mode."""
        if self._mode is None:
            self._init_from_config()
        return self._mode  # type: ignore

    @property
    def executor(self) -> CommandExecutor:
        """Get command executor."""
        if self._executor is None:
            self._init_from_config()
        return self._executor  # type: ignore

    @property
    def recovery(self) -> RecoveryManager:
        """Get recovery manager."""
        if self._recovery is None:
            self._init_from_config()
        return self._recovery  # type: ignore

    @property
    def timeout(self) -> int:
        """Get timeout value."""
        if self._timeout is None:
            self._init_from_config()
        return self._timeout  # type: ignore

    def _generate_ssid(self) -> str:
        """Generate unique SSID like EinkFrame-A1B2."""
        suffix = "0000"
        try:
            machine_id_path = Path("/etc/machine-id")
            if machine_id_path.exists():
                suffix = machine_id_path.read_text().strip()[-4:].upper()
        except Exception:
            pass
        return f"{self._ssid_prefix}-{suffix}"

    def _save_current_state(self) -> None:
        """Save current WiFi connection for restoration."""
        from .manager import get_wifi_manager

        wifi = get_wifi_manager()
        status = wifi.get_status()
        if status.connected and status.ssid:
            self._previous_ssid = status.ssid
            logger.info(f"Saved previous connection: {self._previous_ssid}")

    def _start_open_hotspot(self) -> CommandResult:
        """Start an open (no password) hotspot.

        nmcli hotspot doesn't support open networks directly,
        so we create the connection manually.
        """
        con_name = "EinkFrame-Open"

        # Delete existing connection if exists
        self.executor.run(
            ["nmcli", "connection", "delete", con_name],
            f"Deleting old connection: {con_name}",
            timeout=10,
        )

        # Create new WiFi AP connection
        result = self.executor.run(
            [
                "nmcli", "connection", "add",
                "type", "wifi",
                "ifname", "wlan0",
                "con-name", con_name,
                "autoconnect", "no",
                "ssid", self._ssid,
                "mode", "ap",
            ],
            f"Creating open AP connection: {self._ssid}",
            timeout=10,
        )
        if not result.success and result.executed:
            return result

        # Set to shared mode (provides DHCP)
        result = self.executor.run(
            ["nmcli", "connection", "modify", con_name, "ipv4.method", "shared"],
            "Setting IPv4 shared mode",
            timeout=10,
        )
        if not result.success and result.executed:
            return result

        # Note: For open networks created without security settings,
        # we don't need to modify wifi-sec.key-mgmt as it's already open by default.
        # Trying to modify it might fail if the wifi-sec section doesn't exist.

        # Activate the connection
        result = self.executor.run(
            ["nmcli", "connection", "up", con_name],
            f"Activating open AP: {self._ssid}",
            timeout=30,
        )

        return result

    def start(self) -> bool:
        """Start AP mode with safety mechanisms.

        Returns:
            True if AP mode started successfully.
        """
        if self._active:
            logger.warning("AP mode already active")
            return True

        # Ensure config is loaded
        if self._mode is None:
            self._init_from_config()

        logger.info(f"Starting AP mode (mode={self.mode.value}, timeout={self.timeout}s)")

        # 1. Save current connection info for restoration
        self._save_current_state()

        # 2. Write recovery flag BEFORE any changes
        self.recovery.set_recovery_flag(self._previous_ssid)

        # 3. Generate SSID
        self._ssid = self._generate_ssid()

        # 4. Start hotspot
        if self._password:
            # Secured network with password
            cmd = ["nmcli", "device", "wifi", "hotspot", "ifname", "wlan0", "ssid", self._ssid, "password", self._password]
            result = self.executor.run(cmd, f"Starting secured AP: {self._ssid}", timeout=30)
        else:
            # Open network (no password) - requires manual connection setup
            result = self._start_open_hotspot()

        if not result.success and result.executed:
            logger.error("Failed to start AP mode")
            self.recovery.clear_recovery_flag()
            return False

        # 5. Start timeout watchdog
        self._start_timeout_watchdog()

        self._active = True
        self._start_time = time.time()

        logger.info(f"AP mode started: {self._ssid}")
        return True

    def stop(self, reason: str = "manual") -> bool:
        """Stop AP mode and restore station mode.

        Args:
            reason: Reason for stopping (for logging).

        Returns:
            True if stopped successfully.
        """
        if not self._active and self.mode not in (ExecutionMode.DRY_RUN, ExecutionMode.PREVIEW):
            logger.debug("AP mode not active")
            return True

        logger.info(f"Stopping AP mode (reason: {reason})")

        # 1. Cancel timeout
        self._cancel_timeout_watchdog()

        # 2. Stop hotspot (try both secured and open connection names)
        result = self.executor.run(
            ["nmcli", "connection", "down", "Hotspot"],
            "Stopping secured AP",
            timeout=10,
        )
        # Also try to stop open network connection
        self.executor.run(
            ["nmcli", "connection", "down", "EinkFrame-Open"],
            "Stopping open AP",
            timeout=10,
        )

        # 3. Try to restore previous connection
        if self._previous_ssid:
            self.executor.run(
                ["nmcli", "connection", "up", self._previous_ssid],
                f"Restoring connection to {self._previous_ssid}",
                timeout=30,
            )

        # 4. Clear recovery flag
        self.recovery.clear_recovery_flag()

        self._active = False
        self._start_time = None
        self._ssid = None

        logger.info("AP mode stopped")
        return result.success or not result.executed

    def _start_timeout_watchdog(self) -> None:
        """Start the timeout timer."""
        if self.timeout <= 0:
            logger.info("AP timeout disabled (timeout=0)")
            return

        self._timeout_timer = threading.Timer(self.timeout, self._on_timeout_internal)
        self._timeout_timer.daemon = True
        self._timeout_timer.start()
        logger.info(f"AP timeout watchdog started: {self.timeout}s")

    def _cancel_timeout_watchdog(self) -> None:
        """Cancel the timeout timer."""
        if self._timeout_timer is not None:
            self._timeout_timer.cancel()
            self._timeout_timer = None

    def _on_timeout_internal(self) -> None:
        """Handle AP mode timeout."""
        logger.warning("AP mode timeout reached")

        if self._on_timeout:
            # Call external callback (e.g., to put event in queue)
            self._on_timeout()
        else:
            # Default: stop AP mode directly
            self.stop(reason="timeout")

    @property
    def is_active(self) -> bool:
        """Check if AP mode is active."""
        return self._active

    @property
    def ssid(self) -> Optional[str]:
        """Get current AP SSID."""
        return self._ssid

    @property
    def elapsed_time(self) -> float:
        """Get elapsed time since AP start."""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    @property
    def timeout_remaining(self) -> float:
        """Get remaining timeout seconds."""
        if not self._active or self.timeout <= 0:
            return 0.0
        remaining = self.timeout - self.elapsed_time
        return max(0.0, remaining)

    def get_status(self) -> APStatus:
        """Get current AP status."""
        return APStatus(
            active=self._active,
            ssid=self._ssid,
            elapsed_seconds=self.elapsed_time,
            timeout_remaining=self.timeout_remaining,
            execution_mode=self.mode.value,
        )


# Global instance
_ap_manager: Optional[APModeManager] = None


def get_ap_manager() -> APModeManager:
    """Get global AP manager instance."""
    global _ap_manager
    if _ap_manager is None:
        _ap_manager = APModeManager()
    return _ap_manager


def reset_ap_manager() -> None:
    """Reset global AP manager (for testing)."""
    global _ap_manager
    _ap_manager = None
