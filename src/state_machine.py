"""State machine for E-Ink Photo Frame lifecycle.

Orchestrates the full boot-to-shutdown sequence:
  INIT → WIFI_CONNECT → PHOTO_UPDATE → SCHEDULE → SHUTDOWN
                      → WEB_UI_MODE (button + WiFi success)
                      → AP_MODE (WiFi failure)

Architecture:
  - Main thread: event loop (queue.get blocking)
  - Background threads: WiFi connect, photo update, uvicorn web server
  - Timer threads: AP timeout, WEB_UI timeout
  - Button callbacks: post events to queue (non-blocking)
"""

from __future__ import annotations

import logging
import platform
import queue
import threading
import time
from enum import Enum, auto
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class State(Enum):
    INIT = auto()
    WIFI_CONNECT = auto()
    WEB_UI_MODE = auto()
    AP_MODE = auto()
    PHOTO_UPDATE = auto()
    SCHEDULE = auto()
    SHUTDOWN = auto()
    ERROR = auto()


class Event(Enum):
    INIT_COMPLETE = auto()
    WIFI_SUCCESS = auto()
    WIFI_FAIL = auto()
    WIFI_SUCCESS_WEB_UI = auto()
    AP_TIMEOUT = auto()
    WEB_UI_TIMEOUT = auto()
    PHOTO_DONE = auto()
    PHOTO_FAIL = auto()
    SHUTDOWN_REQUEST = auto()
    PHOTO_UPDATE_REQUEST = auto()
    ERROR_OCCURRED = auto()


# ---------------------------------------------------------------------------
# StateMachine
# ---------------------------------------------------------------------------

class StateMachine:
    """Main state machine for the E-Ink photo frame lifecycle."""

    def __init__(self):
        self._state: State = State.INIT
        self._event_queue: queue.Queue[Event] = queue.Queue()
        self._running: bool = False
        self._web_ui_requested: bool = False
        self._web_activity_seen: bool = False
        self._uvicorn_server = None
        self._web_server_thread: Optional[threading.Thread] = None
        self._timeout_timer: Optional[threading.Timer] = None
        try:
            from config import get_config
            self._dry_run: bool = bool(get_config().get("dry_run", platform.system() != "Linux"))
        except Exception:
            self._dry_run = platform.system() != "Linux"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def post_event(self, event: Event) -> None:
        """Post an event to the queue (thread-safe)."""
        logger.info("Event: %s (state: %s)", event.name, self._state.name)
        self._event_queue.put(event)

    @property
    def state(self) -> State:
        return self._state

    def run(self) -> None:
        """Main event loop. Blocks until SHUTDOWN or ERROR."""
        self._running = True
        logger.info("State machine started")

        self._enter_init()

        while self._running:
            try:
                event = self._event_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            self._handle_event(event)

            if self._state in (State.SHUTDOWN, State.ERROR):
                self._running = False

        logger.info("State machine stopped in state: %s", self._state.name)

    def stop(self) -> None:
        """Request the event loop to stop."""
        self._running = False
        self.post_event(Event.SHUTDOWN_REQUEST)

    def notify_web_connection(self) -> None:
        """웹 페이지/API 접속 시 호출. no_connection 타이머를 idle 타이머로 전환.

        첫 접속 시에만 타이머를 전환하고, 이후에는 아무 것도 하지 않음.
        idle 타이머 리셋은 notify_web_activity()가 담당.
        """
        if self._state not in (State.WEB_UI_MODE, State.AP_MODE):
            return
        if self._web_activity_seen:
            return  # 이미 idle 타이머로 전환됨

        self._web_activity_seen = True

        try:
            from config import get_config
            idle_timeout = get_config().get("web_ui.timeout", 1800)
        except Exception:
            idle_timeout = 1800

        timeout_event = (
            Event.WEB_UI_TIMEOUT if self._state == State.WEB_UI_MODE
            else Event.AP_TIMEOUT
        )

        logger.info("Web connection detected — switching to %ds idle timeout", idle_timeout)

        # AP 모드: AP 매니저 자체 watchdog 비활성화 (상태머신으로 통일)
        if self._state == State.AP_MODE:
            try:
                from wifi.ap_mode import get_ap_manager
                get_ap_manager()._cancel_timeout_watchdog()
            except Exception:
                pass

        self._start_timeout(idle_timeout, timeout_event)

    def notify_web_activity(self) -> None:
        """사용자의 의미 있는 웹 동작 시 호출. idle 타임아웃을 리셋.

        동작 예: 사진 업로드/삭제/크롭, 설정 변경, WiFi 연결 등
        단순 페이지 로드나 조회 API는 해당하지 않음.
        """
        if self._state not in (State.WEB_UI_MODE, State.AP_MODE):
            return

        # 아직 접속 전이면 접속 감지 먼저
        if not self._web_activity_seen:
            self.notify_web_connection()

        try:
            from config import get_config
            idle_timeout = get_config().get("web_ui.timeout", 1800)
        except Exception:
            idle_timeout = 1800

        timeout_event = (
            Event.WEB_UI_TIMEOUT if self._state == State.WEB_UI_MODE
            else Event.AP_TIMEOUT
        )

        self._start_timeout(idle_timeout, timeout_event)
        logger.debug("Idle timeout reset: %ds → %s", idle_timeout, timeout_event.name)

    # ------------------------------------------------------------------
    # State transition
    # ------------------------------------------------------------------

    def _set_state(self, new_state: State) -> None:
        old = self._state
        self._state = new_state
        logger.info("Transition: %s → %s", old.name, new_state.name)

    def _handle_event(self, event: Event) -> None:
        handler = getattr(self, f"_on_{self._state.name.lower()}", None)
        if handler:
            handler(event)
        else:
            logger.warning("No handler for state %s, event %s", self._state.name, event.name)

    # ------------------------------------------------------------------
    # INIT
    # ------------------------------------------------------------------

    def _enter_init(self) -> None:
        self._set_state(State.INIT)
        threading.Thread(target=self._init_sequence, daemon=True).start()

    def _init_sequence(self) -> None:
        try:
            from config import get_config
            from power_manager import get_power_manager
            from button import get_button_handler
            from wifi.recovery import get_recovery_manager

            config = get_config()

            # 1. Recovery check
            recovery = get_recovery_manager()
            if recovery.check_recovery_needed():
                logger.warning("Recovery flag detected")
                recovery.perform_recovery()

            # 2. PowerManager init (SYS_UP signal)
            pm = get_power_manager()

            # 3. Battery check
            voltage = pm.read_input_voltage()
            if voltage is not None:
                critical = config.get("battery.critical_voltage", 3.0)
                if voltage < critical:
                    logger.warning("Battery critically low: %.2fV (threshold: %.1fV)", voltage, critical)

            # 4. Button check (level-based: is it pressed right now?)
            btn = get_button_handler()
            btn.setup()
            if btn.is_pressed:
                self._web_ui_requested = True
                logger.info("Button held during boot → WEB_UI requested")

            # 6. Decide next state
            if not config.wifi_enabled:
                logger.info("WiFi disabled → skip WiFi connect")
                self.post_event(Event.WIFI_FAIL)
            else:
                self.post_event(Event.INIT_COMPLETE)

        except Exception:
            logger.exception("INIT sequence failed")
            self.post_event(Event.ERROR_OCCURRED)

    def _on_init(self, event: Event) -> None:
        if event == Event.INIT_COMPLETE:
            self._enter_wifi_connect()
        elif event == Event.WIFI_FAIL:
            # WiFi disabled
            if self._web_ui_requested:
                logger.info("Button held + WiFi disabled → AP_MODE")
                self._enter_ap_mode()
            else:
                self._enter_photo_update()
        elif event == Event.SHUTDOWN_REQUEST:
            self._enter_shutdown()
        elif event == Event.ERROR_OCCURRED:
            self._enter_error("Init sequence failed")

    # ------------------------------------------------------------------
    # WIFI_CONNECT
    # ------------------------------------------------------------------

    def _enter_wifi_connect(self) -> None:
        self._set_state(State.WIFI_CONNECT)
        threading.Thread(target=self._wifi_connect_sequence, daemon=True).start()

    def _wifi_connect_sequence(self) -> None:
        """WiFi connection with retries. Does NOT auto-start AP."""
        try:
            from config import get_config
            from wifi.manager import get_wifi_manager

            config = get_config()
            wifi = get_wifi_manager()

            # Already connected?
            status = wifi.get_status()
            if status.connected:
                logger.info("Already connected to WiFi: %s", status.ssid)
                self._post_wifi_result(success=True)
                return

            ssid = config.wifi_ssid
            if not ssid:
                logger.info("No WiFi SSID configured")
                self._post_wifi_result(success=False)
                return

            password = config.wifi_password
            retry_count = config.get("wifi.retry_count", 3)

            for attempt in range(1, retry_count + 1):
                logger.info("WiFi attempt %d/%d: %s", attempt, retry_count, ssid)

                success = wifi.connect(ssid, password)
                if success:
                    time.sleep(2)
                    status = wifi.get_status()
                    if status.connected:
                        logger.info("WiFi connected: %s (IP: %s)", status.ssid, status.ip_address)
                        self._post_wifi_result(success=True)
                        return

                if attempt < retry_count:
                    wait = min(5 * attempt, 15)
                    logger.info("Waiting %ds before retry...", wait)
                    time.sleep(wait)

            logger.warning("WiFi failed after %d attempts", retry_count)
            self._post_wifi_result(success=False)

        except Exception:
            logger.exception("WiFi connect error")
            self._post_wifi_result(success=False)

    def _post_wifi_result(self, *, success: bool) -> None:
        if success:
            if self._web_ui_requested:
                self.post_event(Event.WIFI_SUCCESS_WEB_UI)
            else:
                self.post_event(Event.WIFI_SUCCESS)
        else:
            self.post_event(Event.WIFI_FAIL)

    def _on_wifi_connect(self, event: Event) -> None:
        if event == Event.WIFI_SUCCESS:
            self._enter_photo_update()
        elif event == Event.WIFI_SUCCESS_WEB_UI:
            self._enter_web_ui_mode()
        elif event == Event.WIFI_FAIL:
            if self._web_ui_requested:
                self._enter_ap_mode()
            else:
                logger.info("WiFi failed, no button → offline photo update")
                self._enter_photo_update()
        elif event == Event.SHUTDOWN_REQUEST:
            self._enter_shutdown()
        elif event == Event.ERROR_OCCURRED:
            self._enter_error("WiFi connection error")

    # ------------------------------------------------------------------
    # WEB_UI_MODE
    # ------------------------------------------------------------------

    def _enter_web_ui_mode(self) -> None:
        self._set_state(State.WEB_UI_MODE)
        self._web_ui_requested = False

        from config import get_config
        config = get_config()
        port = config.get("web_ui.port", 80)

        # Log IP and show E-Ink info screen
        try:
            from wifi.manager import get_wifi_manager
            status = get_wifi_manager().get_status()
            ip        = status.ip_address or "unknown"
            wifi_ssid = status.ssid or ""
            logger.info("WEB_UI_MODE: access at http://%s:%d", ip, port)
        except Exception:
            ip        = "unknown"
            wifi_ssid = ""

        _ip       = ip
        _ssid     = wifi_ssid
        _port     = port
        _dry      = self._dry_run

        def _show_webui_screen() -> None:
            try:
                from status_display import show_web_ui_screen
                show_web_ui_screen(wifi_ssid=_ssid, ip=_ip, port=_port, dry_run=_dry)
            except Exception:
                logger.exception("Web UI 화면 표시 실패")

        threading.Thread(target=_show_webui_screen, daemon=True, name="webui-screen").start()

        # Start web server
        self._start_web_server(port=port)

        # no_connection_timeout: 접속이 없으면 자동 종료
        # 접속 후에는 notify_web_activity()가 timeout(idle)으로 전환
        self._web_activity_seen = False
        no_conn_timeout = config.get("web_ui.no_connection_timeout", 600)
        if no_conn_timeout > 0:
            self._start_timeout(no_conn_timeout, Event.WEB_UI_TIMEOUT)
            logger.info("WEB_UI no-connection timeout: %ds", no_conn_timeout)

        # 부팅 홀드로 진입했으므로 손을 뗀 후에 "재누름 = 사용자 종료" 콜백 등록
        try:
            from button import get_button_handler
            get_button_handler().setup_after_release(
                on_press=lambda: self.post_event(Event.SHUTDOWN_REQUEST)
            )
        except Exception:
            logger.warning("Failed to register button exit callback")

    def _on_web_ui_mode(self, event: Event) -> None:
        if event == Event.WEB_UI_TIMEOUT:
            self._cancel_timeout()
            self._clear_button_callback()
            self._stop_web_server()
            self._restore_last_photo()
            self._enter_shutdown()
        elif event == Event.SHUTDOWN_REQUEST:
            self._cancel_timeout()
            self._clear_button_callback()
            self._stop_web_server()
            self._restore_last_photo()
            self._enter_shutdown()
        elif event == Event.PHOTO_UPDATE_REQUEST:
            self._cancel_timeout()
            self._clear_button_callback()
            self._stop_web_server()
            self._enter_photo_update()

    # ------------------------------------------------------------------
    # AP_MODE
    # ------------------------------------------------------------------

    def _enter_ap_mode(self) -> None:
        self._set_state(State.AP_MODE)
        self._web_ui_requested = False

        from config import get_config
        from wifi.ap_mode import get_ap_manager
        ap = get_ap_manager()

        # Start AP if not already running (disable AP manager's own timeout —
        # state machine manages all timeouts via _start_timeout)
        if not ap.is_active:
            ap._on_timeout = lambda: None  # no-op; state machine handles timeout
            ap._timeout = 0  # disable AP manager watchdog
            ap.start()
        else:
            ap._cancel_timeout_watchdog()

        # ap_safe_timeout: 접속이 없으면 자동 종료
        # 접속 후에는 notify_web_activity()가 timeout(idle)으로 전환
        self._web_activity_seen = False
        ap_no_conn_timeout = get_config().get("web_ui.ap_safe_timeout", 180)
        if ap_no_conn_timeout > 0:
            self._start_timeout(ap_no_conn_timeout, Event.AP_TIMEOUT)
            logger.info("AP no-connection timeout: %ds", ap_no_conn_timeout)

        logger.info("AP_MODE: SSID=%s", ap.ssid)

        # E-Ink 화면에 AP 안내 표시 (백그라운드 — 디스플레이 갱신이 느리므로 비차단)
        _ssid = ap.ssid or ""
        _ip   = ap.AP_IP
        _dry  = self._dry_run
        try:
            from config import get_config as _gc
            _pw = _gc().get("web_ui.ap_password", "")
        except Exception:
            _pw = ""

        def _show_ap_screen() -> None:
            try:
                from status_display import show_ap_mode_screen
                show_ap_mode_screen(ssid=_ssid, ip=_ip, password=_pw, dry_run=_dry)
            except Exception:
                logger.exception("AP 화면 표시 실패")

        threading.Thread(target=_show_ap_screen, daemon=True, name="ap-screen").start()

        # Start web server on port 8000 (nftables forwards 80 → 8000)
        self._start_web_server(port=8000)

        # Button re-press → exit AP mode
        self._setup_button_for_exit(lambda: self.post_event(Event.AP_TIMEOUT))

    def _on_ap_mode(self, event: Event) -> None:
        if event == Event.AP_TIMEOUT:
            self._clear_button_callback()
            self._stop_web_server()
            self._stop_ap()
            self._restore_last_photo()
            self._enter_shutdown()
        elif event == Event.WIFI_SUCCESS:
            # WiFi connected via web UI → stop AP → photo update
            self._clear_button_callback()
            self._stop_web_server()
            self._stop_ap()
            self._enter_photo_update()
        elif event == Event.SHUTDOWN_REQUEST:
            self._clear_button_callback()
            self._stop_web_server()
            self._stop_ap()
            self._enter_shutdown()
        elif event == Event.PHOTO_UPDATE_REQUEST:
            self._clear_button_callback()
            self._stop_web_server()
            self._stop_ap()
            self._enter_photo_update()

    def _stop_ap(self) -> None:
        try:
            from wifi.ap_mode import get_ap_manager
            get_ap_manager().stop(reason="state_machine")
        except Exception:
            logger.exception("Failed to stop AP mode")

    # ------------------------------------------------------------------
    # PHOTO_UPDATE
    # ------------------------------------------------------------------

    def _enter_photo_update(self) -> None:
        self._set_state(State.PHOTO_UPDATE)
        threading.Thread(target=self._photo_update_sequence, daemon=True).start()

    def _photo_update_sequence(self) -> None:
        try:
            from frame_runner import run_once
            success = run_once(dry_run=self._dry_run)
            self.post_event(Event.PHOTO_DONE if success else Event.PHOTO_FAIL)
        except Exception:
            logger.exception("Photo update failed")
            self.post_event(Event.PHOTO_FAIL)

    def _on_photo_update(self, event: Event) -> None:
        if event in (Event.PHOTO_DONE, Event.PHOTO_FAIL):
            if event == Event.PHOTO_FAIL:
                logger.warning("Photo update failed, proceeding to shutdown")
            self._enter_schedule()
        elif event == Event.SHUTDOWN_REQUEST:
            self._enter_shutdown()

    # ------------------------------------------------------------------
    # SCHEDULE → SHUTDOWN
    # ------------------------------------------------------------------

    def _enter_schedule(self) -> None:
        self._set_state(State.SCHEDULE)
        logger.info("Schedule phase — proceeding to shutdown")
        self._enter_shutdown()

    def _on_schedule(self, event: Event) -> None:
        pass  # Instant transition

    # ------------------------------------------------------------------
    # SHUTDOWN
    # ------------------------------------------------------------------

    def _enter_shutdown(self) -> None:
        self._set_state(State.SHUTDOWN)

        if self._dry_run:
            logger.info("DRY RUN: skipping schedule_and_shutdown()")
            return

        try:
            from power_manager import get_power_manager
            get_power_manager().schedule_and_shutdown()
        except Exception:
            logger.exception("Shutdown sequence failed")

    def _on_shutdown(self, event: Event) -> None:
        pass  # Terminal state

    # ------------------------------------------------------------------
    # ERROR
    # ------------------------------------------------------------------

    def _enter_error(self, message: str) -> None:
        self._set_state(State.ERROR)
        logger.error("ERROR: %s", message)
        # TODO: status_display.show_error(message)

        # Recover to AP_MODE so user can diagnose/reconfigure
        self._enter_ap_mode()

    def _on_error(self, event: Event) -> None:
        pass  # Terminal state

    # ------------------------------------------------------------------
    # Web server management
    # ------------------------------------------------------------------

    def _start_web_server(self, port: int) -> None:
        import uvicorn
        from web.app import app

        config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
        self._uvicorn_server = uvicorn.Server(config)

        self._web_server_thread = threading.Thread(
            target=self._uvicorn_server.run,
            daemon=True,
            name="uvicorn",
        )
        self._web_server_thread.start()
        logger.info("Web server started on port %d", port)

    def _stop_web_server(self) -> None:
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
            if self._web_server_thread and self._web_server_thread.is_alive():
                self._web_server_thread.join(timeout=5.0)
                if self._web_server_thread.is_alive():
                    logger.warning("Web server thread did not stop within 5s")
            self._uvicorn_server = None
            self._web_server_thread = None
            logger.info("Web server stopped")

    # ------------------------------------------------------------------
    # Timeout timer
    # ------------------------------------------------------------------

    def _start_timeout(self, seconds: float, event: Event) -> None:
        self._cancel_timeout()
        self._timeout_timer = threading.Timer(seconds, lambda: self.post_event(event))
        self._timeout_timer.daemon = True
        self._timeout_timer.start()
        logger.info("Timeout set: %ds → %s", seconds, event.name)

    def _cancel_timeout(self) -> None:
        if self._timeout_timer is not None:
            self._timeout_timer.cancel()
            self._timeout_timer = None

    # ------------------------------------------------------------------
    # Button helpers
    # ------------------------------------------------------------------

    def _setup_button_for_exit(self, callback) -> None:
        """Register button short-press callback (AP/WEB_UI mode exit)."""
        try:
            from button import get_button_handler
            get_button_handler().setup(on_press=callback)
            logger.debug("Button exit callback registered")
        except Exception:
            logger.warning("Failed to register button exit callback")

    def _clear_button_callback(self) -> None:
        """Clear button callbacks on mode exit."""
        try:
            from button import get_button_handler
            get_button_handler().setup()  # no callbacks
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Last photo restore
    # ------------------------------------------------------------------

    def _restore_last_photo(self) -> None:
        """Restore the last displayed photo before shutdown (버튼/타임아웃 종료 시)."""
        try:
            from status_display import restore_last_photo
            restore_last_photo(dry_run=self._dry_run)
        except Exception:
            logger.exception("Failed to restore last photo")

    # ------------------------------------------------------------------
    # Status info (for web API)
    # ------------------------------------------------------------------

    @property
    def mode_info(self) -> dict:
        return {
            "state": self._state.name,
            "web_ui_requested": self._web_ui_requested,
            "running": self._running,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_state_machine: Optional[StateMachine] = None


def get_state_machine() -> Optional[StateMachine]:
    """Get the global state machine instance. Returns None in dev mode."""
    return _state_machine


def create_state_machine() -> StateMachine:
    """Create and set the global state machine instance."""
    global _state_machine
    _state_machine = StateMachine()
    return _state_machine


def reset_state_machine() -> None:
    """Reset the global state machine (for testing)."""
    global _state_machine
    if _state_machine is not None:
        _state_machine.stop()
    _state_machine = None
