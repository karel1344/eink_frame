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
_REG_ALARM1_SECOND  = 27
_REG_ALARM1_MINUTE  = 28
_REG_ALARM1_HOUR    = 29
_REG_ALARM1_DAY     = 30
_REG_ALARM1_WEEKDAY = 31

# Shutdown alarm (Alarm 2) — BCD encoded
_REG_ALARM2_SECOND  = 32
_REG_ALARM2_MINUTE  = 33
_REG_ALARM2_HOUR    = 34
_REG_ALARM2_DAY     = 35
_REG_ALARM2_WEEKDAY = 36

# _REG_ALARM1_WEEKDAY (31) and _REG_ALARM2_WEEKDAY (36) are intentionally
# never written by user code. The ATtiny firmware manages these registers
# exclusively (sets 0x80 two seconds before alarm fires via reset_rtc_alarm).
# Writing to them will corrupt the alarm state.


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
        # Always attempt SYS_UP signal and I2C connection, even in dry-run mode.
        # On Mac/non-Pi, gpiozero/smbus2 import errors are handled gracefully
        # inside _signal_system_up() and _try_connect_i2c().
        # dry_run only skips the final 'systemctl poweroff' step.

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

        Attempts a single reconnection if not yet connected. This allows
        the service to recover if Witty Pi was not ready at boot time.
        Note: dry_run only suppresses 'systemctl poweroff'; I2C still works
        on real hardware so that alarms are always set before shutdown.
        """
        if self._available:
            return True
        if self._smbus2_missing:
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

    def set_startup_alarm(self, hour: int, minute: int, second: int, day: int) -> None:
        """Set startup alarm to an absolute date+time (UTC).

        All fields written as BCD. Weekday register (31) is intentionally
        not touched — managed exclusively by ATtiny firmware.
        """
        if not self._ensure_connected():
            logger.warning(
                "Cannot set startup alarm to day=%02d %02d:%02d:%02d: Witty Pi I2C not available",
                day, hour, minute, second,
            )
            return

        try:
            self._write_register(_REG_ALARM1_SECOND, self._to_bcd(second))
            self._write_register(_REG_ALARM1_MINUTE, self._to_bcd(minute))
            self._write_register(_REG_ALARM1_HOUR,   self._to_bcd(hour))
            self._write_register(_REG_ALARM1_DAY,    self._to_bcd(day))
            # _REG_ALARM1_WEEKDAY (31) intentionally not written
            logger.info(
                "Startup alarm set: day=%02d %02d:%02d:%02d UTC", day, hour, minute, second
            )
        except OSError:
            logger.exception("Failed to set startup alarm")

    def clear_startup_alarm(self) -> None:
        """Clear the startup alarm registers (sec/min/hour/day only)."""
        if not self._ensure_connected():
            return
        try:
            for reg in (_REG_ALARM1_SECOND, _REG_ALARM1_MINUTE,
                        _REG_ALARM1_HOUR, _REG_ALARM1_DAY):
                self._write_register(reg, 0x00)
            # _REG_ALARM1_WEEKDAY (31) intentionally not cleared
            logger.info("Startup alarm cleared")
        except OSError:
            logger.exception("Failed to clear startup alarm")

    # ------------------------------------------------------------------
    # Public: RTC sync
    # ------------------------------------------------------------------

    def sync_rtc(self) -> None:
        """Write the Pi's current UTC time to the Witty Pi RTC registers.

        Should be called after NTP sync to ensure the Witty Pi wakes up
        at the correct time. PCF85063 RTC registers exposed via ATtiny (BCD):
          58=sec, 59=min, 60=hour, 61=day, 62=weekday, 63=month, 64=year (00-99)
        Weekday uses ISO convention: 1=Mon … 7=Sun (matches ``date +%u``).
        """
        if not self._ensure_connected():
            logger.warning("Cannot sync RTC: Witty Pi I2C not available")
            return

        from datetime import datetime, timezone as tz_utc

        now = datetime.now(tz_utc.utc)
        try:
            # Bit 7 of seconds register is the PCF85063 OS (Oscillator Stop) flag;
            # writing plain BCD (bit 7 = 0) clears it, confirming oscillator is running.
            self._write_register(58, self._to_bcd(now.second))
            self._write_register(59, self._to_bcd(now.minute))
            self._write_register(60, self._to_bcd(now.hour))
            self._write_register(61, self._to_bcd(now.day))
            self._write_register(62, self._to_bcd(now.isoweekday()))  # 1=Mon…7=Sun
            self._write_register(63, self._to_bcd(now.month))
            self._write_register(64, self._to_bcd(now.year % 100))
            logger.info(
                "Witty Pi RTC synced to %04d-%02d-%02d %02d:%02d:%02d UTC",
                now.year, now.month, now.day, now.hour, now.minute, now.second,
            )
        except OSError:
            logger.exception("Failed to sync RTC")

    def set_startup_from_config(self) -> None:
        """Dispatch to daily or interval startup alarm based on ``schedule.mode``."""
        from config import get_config

        # Sync RTC first so the ATtiny has accurate time to compare against
        self.sync_rtc()

        config = get_config()
        mode = config.get("schedule.mode", "daily")

        if mode == "interval":
            self._set_startup_interval(config)
        else:
            self._set_startup_daily(config)

    def _set_startup_daily(self, config) -> None:
        """Set startup alarm for a fixed daily time (existing logic)."""
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        update_time = config.update_time  # e.g. "06:00"
        timezone_str = config.get("schedule.timezone", "UTC")

        parts = update_time.split(":")
        local_hour, local_minute = int(parts[0]), int(parts[1])

        try:
            tz = ZoneInfo(timezone_str)
            now_local = datetime.now(tz)
            alarm_local = now_local.replace(
                hour=local_hour, minute=local_minute, second=0, microsecond=0
            )
            if alarm_local <= now_local:
                alarm_local += timedelta(days=1)
            utc_alarm = alarm_local.astimezone(ZoneInfo("UTC"))
            logger.info(
                "Startup alarm (daily): %s %02d:%02d → UTC day=%02d %02d:%02d:%02d",
                timezone_str, local_hour, local_minute,
                utc_alarm.day, utc_alarm.hour, utc_alarm.minute, utc_alarm.second,
            )
        except (ZoneInfoNotFoundError, Exception) as e:
            logger.warning("Timezone '%s' conversion failed, using UTC: %s", timezone_str, e)
            from datetime import timezone
            now_utc = datetime.now(timezone.utc)
            utc_alarm = now_utc.replace(
                hour=local_hour, minute=local_minute, second=0, microsecond=0
            )
            if utc_alarm <= now_utc:
                utc_alarm += timedelta(days=1)

        self.set_startup_alarm(utc_alarm.hour, utc_alarm.minute, 0, utc_alarm.day)

    def _set_startup_interval(self, config) -> None:
        """Set startup alarm to now + N minutes."""
        from datetime import datetime, timedelta, timezone

        interval = int(config.get("schedule.interval_minutes", 60))
        now_utc = datetime.now(timezone.utc)
        utc_alarm = now_utc + timedelta(minutes=interval)

        logger.info(
            "Startup alarm (interval): +%d min → UTC day=%02d %02d:%02d:%02d",
            interval, utc_alarm.day, utc_alarm.hour, utc_alarm.minute, utc_alarm.second,
        )
        self.set_startup_alarm(utc_alarm.hour, utc_alarm.minute, utc_alarm.second, utc_alarm.day)

    # ------------------------------------------------------------------
    # Public: shutdown alarm
    # ------------------------------------------------------------------

    def set_shutdown_alarm(
        self, hour: int, minute: int, second: int = 0, day: int | None = None
    ) -> None:
        """Set shutdown alarm to an absolute date+time (UTC).

        ``day`` defaults to today (UTC) when not provided.
        Weekday register (36) is intentionally not touched.
        """
        if day is None:
            from datetime import datetime, timezone
            day = datetime.now(timezone.utc).day

        if not self._ensure_connected():
            logger.warning(
                "Cannot set shutdown alarm to day=%02d %02d:%02d:%02d: Witty Pi I2C not available",
                day, hour, minute, second,
            )
            return

        try:
            self._write_register(_REG_ALARM2_SECOND, self._to_bcd(second))
            self._write_register(_REG_ALARM2_MINUTE, self._to_bcd(minute))
            self._write_register(_REG_ALARM2_HOUR,   self._to_bcd(hour))
            self._write_register(_REG_ALARM2_DAY,    self._to_bcd(day))
            # _REG_ALARM2_WEEKDAY (36) intentionally not written
            logger.info(
                "Shutdown alarm set: day=%02d %02d:%02d:%02d UTC", day, hour, minute, second
            )
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

        Uses gpiozero + lgpio (character device interface) which works on
        Raspberry Pi OS Bookworm where the legacy sysfs GPIO is unreliable.

        Reference: official Witty Pi 4 daemon.sh (uugear/Witty-Pi-4)
        """
        import time

        _GPIO_PIN = 17  # BCM GPIO17 = SYS_UP signal to Witty Pi

        try:
            from gpiozero import OutputDevice
            pin = OutputDevice(_GPIO_PIN, active_high=True, initial_value=False)
            try:
                # 2× HIGH/LOW pulses (matches official daemon.sh behaviour)
                for _ in range(2):
                    pin.on()
                    time.sleep(0.1)
                    pin.off()
                    time.sleep(0.1)
                logger.info("GPIO17 SYS_UP signal sent — Witty Pi notified Pi is running")
            finally:
                pin.close()
        except ImportError:
            logger.warning(
                "gpiozero not installed — SYS_UP signal not sent. "
                "Run: pip install gpiozero lgpio"
            )
        except Exception as e:
            logger.warning("Failed to send SYS_UP signal to Witty Pi: %s", e)

    def schedule_and_shutdown(self) -> None:
        """Full shutdown: set next startup alarm → save state → poweroff.

        Each step is wrapped independently so that a failure in alarm-setting
        never prevents the actual poweroff from running.
        """
        from config import get_config
        from database import get_db

        critical_v = get_config().get("battery.critical_voltage", 3.0)

        # 1. Read battery voltage early (needed for alarm decision)
        voltage = None
        try:
            voltage = self.read_input_voltage()
            if voltage is not None:
                get_db().set_state("last_battery_voltage", str(round(voltage, 2)))
                logger.info("Battery voltage at shutdown: %.2fV", voltage)
        except Exception:
            logger.warning("Failed to read/save battery voltage")

        # 2. Schedule next boot — or clear alarm if battery is critically low
        if voltage is not None and voltage <= critical_v:
            logger.warning(
                "Battery critically low (%.2fV <= %.2fV) — clearing startup alarm to prevent reboot",
                voltage, critical_v,
            )
            try:
                self.clear_startup_alarm()
            except Exception:
                logger.warning("Failed to clear startup alarm")
        else:
            try:
                self.set_startup_from_config()
            except Exception:
                logger.exception(
                    "Failed to set startup alarm — Pi will shut down without next-boot alarm. "
                    "Check I2C connection and config."
                )

        # 3. Set hardware low-voltage threshold
        try:
            self.set_low_voltage_threshold(critical_v)
        except Exception:
            logger.warning("Failed to set low-voltage threshold")

        # 4. Dry-run: skip actual poweroff (dev environment only)
        if self._dry_run:
            logger.info("Dry-run: would execute 'systemctl poweroff'")
            return

        # 5. Poweroff — always runs regardless of alarm-setting success.
        #    Witty Pi detects halt by monitoring the TXD (UART TX) line going
        #    permanently LOW. No explicit GPIO signal needed from Pi.
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
