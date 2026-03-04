"""Witty Pi 4 L3V7 power management via I2C.

Reads battery voltage, sets startup/shutdown alarms, and handles
graceful shutdown sequences. Automatically falls back to a no-op
mode when I2C hardware is unavailable (e.g. on Mac).
"""

from __future__ import annotations

import logging
import platform
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Witty Pi 4 L3V7 I2C register map
# Reference: https://github.com/uugear/Witty-Pi-4/blob/main/Firmware/WittyPi4_L3V7/WittyPi4_L3V7.ino
# ---------------------------------------------------------------------------
_I2C_BUS = 1
_I2C_ADDR = 0x08
_FIRMWARE_ID = 0x37  # Witty Pi 4 L3V7

# Read-only registers
_REG_FIRMWARE_ID = 0
_REG_VOLTAGE_IN_I = 1   # Input voltage integer part
_REG_VOLTAGE_IN_D = 2   # Input voltage decimal part (×100)
_REG_VOLTAGE_OUT_I = 3   # Output voltage integer part
_REG_VOLTAGE_OUT_D = 4   # Output voltage decimal part (×100)
_REG_CURRENT_OUT_I = 5   # Output current integer part
_REG_CURRENT_OUT_D = 6   # Output current decimal part (×100)
_REG_POWER_MODE = 7      # 0 = USB 5V, 2 = 3.7V battery
_REG_LV_SHUTDOWN = 8     # Low-voltage shutdown flag

# Writable registers
_REG_LV_THRESHOLD = 19      # Low-voltage threshold
_REG_RECOVERY_VOLTAGE = 22  # Recovery voltage

# Startup alarm (Alarm 1) — BCD encoded
_REG_ALARM1_SECOND = 27
_REG_ALARM1_MINUTE = 28
_REG_ALARM1_HOUR = 29
_REG_ALARM1_DAY = 30

# Shutdown alarm (Alarm 2) — BCD encoded
_REG_ALARM2_SECOND = 32
_REG_ALARM2_MINUTE = 33
_REG_ALARM2_HOUR = 34
_REG_ALARM2_DAY = 35

_ALARM_DAY_EVERY_DAY = 0x80  # Wildcard: trigger every day


class PowerManager:
    """Interface to Witty Pi 4 L3V7 for battery and power scheduling."""

    def __init__(self, *, dry_run: bool = False):
        self._dry_run = dry_run
        self._bus = None       # smbus2.SMBus instance
        self._available = False
        self._smbus2_missing = False  # True if smbus2 not installed (no point retrying)
        self._init_i2c()

    # ------------------------------------------------------------------
    # I2C initialisation
    # ------------------------------------------------------------------

    def _init_i2c(self) -> None:
        if self._dry_run:
            logger.info("PowerManager: dry-run mode, I2C disabled")
            return

        # Signal SYS_UP to Witty Pi regardless of I2C status.
        # Without this pulse, Witty Pi won't recognise the Pi as "running"
        # and won't detect shutdown via TXD monitoring later.
        self._signal_system_up()

        self._try_connect_i2c()

    def _try_connect_i2c(self) -> None:
        """Single attempt to connect to Witty Pi over I2C.

        Updates ``self._available`` on success. Safe to call repeatedly —
        if smbus2 is not installed, marks ``_smbus2_missing`` and skips
        future attempts.
        """
        if self._smbus2_missing:
            return

        try:
            import smbus2
        except ImportError:
            logger.info("PowerManager: smbus2 not installed, running without I2C")
            self._smbus2_missing = True
            return

        try:
            self._bus = smbus2.SMBus(_I2C_BUS)
            fw_id = self._bus.read_byte_data(_I2C_ADDR, _REG_FIRMWARE_ID)
            if fw_id != _FIRMWARE_ID:
                logger.warning(
                    "Unexpected Witty Pi firmware ID: 0x%02X (expected 0x%02X)",
                    fw_id, _FIRMWARE_ID,
                )
            self._available = True
            logger.info("PowerManager: Witty Pi 4 L3V7 detected (firmware=0x%02X)", fw_id)
        except OSError as e:
            self._available = False
            logger.debug("PowerManager: I2C connect failed: %s", e)

    def _ensure_connected(self) -> bool:
        """Return True if Witty Pi I2C is available.

        If not yet connected and not in dry-run mode, attempts a single
        reconnection. This allows the service to recover automatically
        if the Witty Pi was not ready at boot time.
        """
        if self._available:
            return True
        if self._dry_run or self._smbus2_missing:
            return False
        self._try_connect_i2c()
        return self._available

    # ------------------------------------------------------------------
    # Low-level I2C helpers
    # ------------------------------------------------------------------

    def _read_register(self, register: int) -> int:
        return self._bus.read_byte_data(_I2C_ADDR, register)

    def _write_register(self, register: int, value: int) -> None:
        self._bus.write_byte_data(_I2C_ADDR, register, value)

    def _read_voltage_pair(self, reg_int: int, reg_dec: int) -> float:
        """Read an integer+decimal register pair and return volts."""
        integer = self._read_register(reg_int)
        decimal = self._read_register(reg_dec)
        return integer + decimal / 100.0

    # ------------------------------------------------------------------
    # BCD helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_bcd(value: int) -> int:
        """Convert integer to BCD.  E.g. 35 → 0x35."""
        return ((value // 10) << 4) | (value % 10)

    @staticmethod
    def _from_bcd(value: int) -> int:
        """Convert BCD to integer.  E.g. 0x35 → 35."""
        return ((value >> 4) * 10) + (value & 0x0F)

    # ------------------------------------------------------------------
    # Public: hardware availability
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """True if Witty Pi hardware was detected on I2C."""
        return self._available

    # ------------------------------------------------------------------
    # Public: voltage / power readings
    # ------------------------------------------------------------------

    def read_input_voltage(self) -> float | None:
        """Read battery/USB input voltage (V).  Returns None if unavailable."""
        if not self._ensure_connected():
            return None
        try:
            return self._read_voltage_pair(_REG_VOLTAGE_IN_I, _REG_VOLTAGE_IN_D)
        except OSError:
            logger.exception("Failed to read input voltage")
            return None

    def read_output_voltage(self) -> float | None:
        """Read 5 V rail output voltage (V)."""
        if not self._ensure_connected():
            return None
        try:
            return self._read_voltage_pair(_REG_VOLTAGE_OUT_I, _REG_VOLTAGE_OUT_D)
        except OSError:
            logger.exception("Failed to read output voltage")
            return None

    def read_output_current(self) -> float | None:
        """Read output current (A)."""
        if not self._ensure_connected():
            return None
        try:
            return self._read_voltage_pair(_REG_CURRENT_OUT_I, _REG_CURRENT_OUT_D)
        except OSError:
            logger.exception("Failed to read output current")
            return None

    def get_power_mode(self) -> str | None:
        """Return ``"usb"`` or ``"battery"``; ``None`` if unavailable."""
        if not self._ensure_connected():
            return None
        try:
            mode = self._read_register(_REG_POWER_MODE)
            return "usb" if mode == 0 else "battery"
        except OSError:
            logger.exception("Failed to read power mode")
            return None

    def is_on_battery(self) -> bool:
        """True when running on battery (not USB)."""
        return self.get_power_mode() == "battery"

    # ------------------------------------------------------------------
    # Public: battery status (dict for web API)
    # ------------------------------------------------------------------

    @staticmethod
    def _voltage_to_percentage(voltage: float) -> int:
        """Estimate battery % from voltage (3.7 V LiPo, linear approx)."""
        v_min, v_max = 3.0, 4.2
        pct = (voltage - v_min) / (v_max - v_min) * 100
        return max(0, min(100, int(pct)))

    def get_battery_status(self) -> dict:
        """Return battery info dict suitable for the ``/api/status`` response.

        Keys: voltage, percentage, charging, power_source.
        Values are ``None`` when hardware is unavailable.
        """
        voltage = self.read_input_voltage()
        if voltage is None:
            return {
                "voltage": None,
                "percentage": None,
                "charging": None,
                "power_source": "unknown",
            }

        power_mode = self.get_power_mode()
        return {
            "voltage": round(voltage, 2),
            "percentage": self._voltage_to_percentage(voltage),
            "charging": power_mode == "usb",
            "power_source": power_mode or "unknown",
        }

    # ------------------------------------------------------------------
    # Public: startup alarm
    # ------------------------------------------------------------------

    def set_startup_alarm(self, hour: int, minute: int, second: int = 0) -> None:
        """Set daily startup alarm (day register = 0x80 = every day)."""
        if not self._ensure_connected():
            logger.warning(
                "Cannot set startup alarm to %02d:%02d:%02d: Witty Pi I2C not available",
                hour, minute, second,
            )
            return

        try:
            self._write_register(_REG_ALARM1_SECOND, self._to_bcd(second))
            self._write_register(_REG_ALARM1_MINUTE, self._to_bcd(minute))
            self._write_register(_REG_ALARM1_HOUR, self._to_bcd(hour))
            self._write_register(_REG_ALARM1_DAY, _ALARM_DAY_EVERY_DAY)
            logger.info("Startup alarm set: every day at %02d:%02d:%02d", hour, minute, second)
        except OSError:
            logger.exception("Failed to set startup alarm")

    def clear_startup_alarm(self) -> None:
        """Clear the startup alarm registers."""
        if not self._ensure_connected():
            return
        try:
            for reg in (_REG_ALARM1_SECOND, _REG_ALARM1_MINUTE,
                        _REG_ALARM1_HOUR, _REG_ALARM1_DAY):
                self._write_register(reg, 0x00)
            logger.info("Startup alarm cleared")
        except OSError:
            logger.exception("Failed to clear startup alarm")

    def set_startup_from_config(self) -> None:
        """Parse ``schedule.update_time`` / ``schedule.timezone`` from config,
        convert to UTC, and set the startup alarm."""
        from datetime import datetime
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        from config import get_config

        config = get_config()
        update_time = config.update_time  # e.g. "06:00"
        timezone_str = config.get("schedule.timezone", "UTC")

        parts = update_time.split(":")
        local_hour, local_minute = int(parts[0]), int(parts[1])

        try:
            tz = ZoneInfo(timezone_str)
            local_dt = datetime.now(tz).replace(
                hour=local_hour, minute=local_minute, second=0, microsecond=0
            )
            utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
            hour, minute = utc_dt.hour, utc_dt.minute
            logger.info(
                "Startup alarm: %s %02d:%02d → UTC %02d:%02d",
                timezone_str, local_hour, local_minute, hour, minute,
            )
        except (ZoneInfoNotFoundError, Exception) as e:
            logger.warning(
                "Timezone '%s' conversion failed, using time as-is: %s",
                timezone_str, e,
            )
            hour, minute = local_hour, local_minute

        self.set_startup_alarm(hour, minute)

    # ------------------------------------------------------------------
    # Public: shutdown alarm
    # ------------------------------------------------------------------

    def set_shutdown_alarm(self, hour: int, minute: int, second: int = 0) -> None:
        """Set daily shutdown alarm."""
        if not self._ensure_connected():
            logger.warning(
                "Cannot set shutdown alarm to %02d:%02d:%02d: Witty Pi I2C not available",
                hour, minute, second,
            )
            return

        try:
            self._write_register(_REG_ALARM2_SECOND, self._to_bcd(second))
            self._write_register(_REG_ALARM2_MINUTE, self._to_bcd(minute))
            self._write_register(_REG_ALARM2_HOUR, self._to_bcd(hour))
            self._write_register(_REG_ALARM2_DAY, _ALARM_DAY_EVERY_DAY)
            logger.info("Shutdown alarm set: every day at %02d:%02d:%02d", hour, minute, second)
        except OSError:
            logger.exception("Failed to set shutdown alarm")

    # ------------------------------------------------------------------
    # Public: low-voltage threshold
    # ------------------------------------------------------------------

    def set_low_voltage_threshold(self, voltage: float) -> None:
        """Set the hardware low-voltage auto-shutdown threshold.

        The register stores voltage × 10 as a single byte
        (e.g. 3.0 V → 30).  Set to 0xFF to disable.
        """
        if not self._ensure_connected():
            return
        try:
            self._write_register(_REG_LV_THRESHOLD, int(voltage * 10))
            logger.info("Low-voltage threshold set to %.1fV", voltage)
        except OSError:
            logger.exception("Failed to set low-voltage threshold")

    def set_recovery_voltage(self, voltage: float) -> None:
        """Set the recovery voltage (V × 10)."""
        if not self._ensure_connected():
            return
        try:
            self._write_register(_REG_RECOVERY_VOLTAGE, int(voltage * 10))
            logger.info("Recovery voltage set to %.1fV", voltage)
        except OSError:
            logger.exception("Failed to set recovery voltage")

    # ------------------------------------------------------------------
    # Public: graceful shutdown sequence
    # ------------------------------------------------------------------

    def _signal_system_up(self) -> None:
        """Pulse GPIO17 (SYS_UP) to notify Witty Pi that the Pi is running.

        The Witty Pi 4 L3V7 firmware requires 2× HIGH/LOW pulses on GPIO17
        (BCM) at boot time to mark the Pi as "system up". Until this signal is
        received, the Witty Pi will NOT treat a subsequent TXD-line drop as a
        valid shutdown, so it will not cut 5V power after halt.

        Reference: official Witty Pi 4 daemon.sh (uugear/Witty-Pi-4)
        """
        import time

        _GPIO_SYSFS = "/sys/class/gpio"
        _GPIO_PIN = "17"  # BCM GPIO17 = SYS_UP signal to Witty Pi
        try:
            try:
                with open(f"{_GPIO_SYSFS}/export", "w") as f:
                    f.write(_GPIO_PIN)
            except OSError:
                pass  # Already exported

            with open(f"{_GPIO_SYSFS}/gpio{_GPIO_PIN}/direction", "w") as f:
                f.write("out")

            # 2× HIGH/LOW pulses (matches official daemon.sh behaviour)
            for _ in range(2):
                with open(f"{_GPIO_SYSFS}/gpio{_GPIO_PIN}/value", "w") as f:
                    f.write("1")
                time.sleep(0.1)
                with open(f"{_GPIO_SYSFS}/gpio{_GPIO_PIN}/value", "w") as f:
                    f.write("0")
                time.sleep(0.1)

            # Release pin back to input and unexport
            with open(f"{_GPIO_SYSFS}/gpio{_GPIO_PIN}/direction", "w") as f:
                f.write("in")
            try:
                with open(f"{_GPIO_SYSFS}/unexport", "w") as f:
                    f.write(_GPIO_PIN)
            except OSError:
                pass

            logger.info("GPIO17 SYS_UP signal sent — Witty Pi notified Pi is running")
        except Exception as e:
            logger.warning("Failed to send SYS_UP signal to Witty Pi: %s", e)

    def schedule_and_shutdown(self) -> None:
        """Full shutdown: set next startup alarm → save state → poweroff."""
        from config import get_config
        from database import get_db

        # 1. Schedule next boot
        self.set_startup_from_config()

        # 2. Set hardware low-voltage threshold
        critical_v = get_config().get("battery.critical_voltage", 3.0)
        self.set_low_voltage_threshold(critical_v)

        # 3. Persist battery voltage in DB
        voltage = self.read_input_voltage()
        if voltage is not None:
            get_db().set_state("last_battery_voltage", str(round(voltage, 2)))
            logger.info("Battery voltage at shutdown: %.2fV", voltage)

        # 4. Dry-run: skip actual poweroff (dev environment only)
        if self._dry_run:
            logger.info("Dry-run: would execute 'systemctl poweroff'")
            return

        # 5. Poweroff — Witty Pi detects halt by monitoring the TXD (UART TX)
        #    line going permanently LOW. No explicit GPIO signal needed from Pi.
        logger.info("Initiating system poweroff...")
        subprocess.run(["sudo", "systemctl", "poweroff"], check=False)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_power_manager: PowerManager | None = None


def get_power_manager(*, dry_run: bool | None = None) -> PowerManager:
    """Get the global PowerManager instance.

    On non-Linux platforms (e.g. macOS) *dry_run* defaults to ``True``
    so that the module never attempts I2C communication.
    """
    global _power_manager
    if _power_manager is None:
        if dry_run is None:
            dry_run = platform.system() != "Linux"
        _power_manager = PowerManager(dry_run=dry_run)
    return _power_manager
