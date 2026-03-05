"""State machine 전이 테스트 (Mac 개발용).

_enter_* 메서드만 mock으로 교체하여 모든 _on_* 핸들러의 전이 로직을 검증합니다.
백그라운드 스레드, GPIO, 시스템 콜 없이 Mac에서 바로 실행 가능합니다.

Usage:
    cd eink_frame
    python3 -m pytest tests/test_state_machine.py -v
"""

import pytest
from unittest.mock import MagicMock, patch

from state_machine import StateMachine, State, Event


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def sm() -> StateMachine:
    """
    _enter_* 메서드를 state만 변경하는 lambda로 교체한 StateMachine.
    실제 전이 로직(_on_* handlers)은 그대로 실행됩니다.
    """
    m = StateMachine()
    ss = m._set_state  # 진짜 _set_state 보관

    # 각 _enter_*: 해당 State로 설정만 함 (스레드/시스템 콜 없음)
    m._enter_init          = lambda:       ss(State.INIT)
    m._enter_wifi_connect  = lambda:       ss(State.WIFI_CONNECT)
    m._enter_ap_mode       = lambda:       ss(State.AP_MODE)
    m._enter_web_ui_mode   = lambda:       ss(State.WEB_UI_MODE)
    m._enter_photo_update  = lambda:       ss(State.PHOTO_UPDATE)
    m._enter_shutdown      = lambda:       ss(State.SHUTDOWN)

    # _enter_schedule: 실제 코드와 동일하게 즉시 _enter_shutdown 호출
    m._enter_schedule = lambda: (ss(State.SCHEDULE), m._enter_shutdown())

    # _enter_error: 실제 코드와 동일하게 ERROR 후 _enter_ap_mode 호출
    m._enter_error = lambda msg="": (ss(State.ERROR), m._enter_ap_mode())

    # 사이드이펙트 mock
    m._start_web_server      = MagicMock()
    m._stop_web_server       = MagicMock()
    m._stop_ap               = MagicMock()
    m._setup_button_for_exit = MagicMock()
    m._clear_button_callback = MagicMock()
    m._restore_last_photo    = MagicMock()
    m._start_timeout         = MagicMock()
    m._cancel_timeout        = MagicMock()

    return m


# ── INIT ──────────────────────────────────────────────────────────────────────

class TestInit:
    def test_init_complete_goes_to_wifi_connect(self, sm):
        sm._set_state(State.INIT)
        sm._on_init(Event.INIT_COMPLETE)
        assert sm.state == State.WIFI_CONNECT

    def test_wifi_fail_offline_goes_to_photo_update(self, sm):
        sm._set_state(State.INIT)
        sm._on_init(Event.WIFI_FAIL)
        assert sm.state == State.PHOTO_UPDATE

    def test_shutdown_request(self, sm):
        sm._set_state(State.INIT)
        sm._on_init(Event.SHUTDOWN_REQUEST)
        assert sm.state == State.SHUTDOWN

    def test_error_goes_to_ap_mode(self, sm):
        sm._set_state(State.INIT)
        sm._on_init(Event.ERROR_OCCURRED)
        assert sm.state == State.AP_MODE  # ERROR → _enter_ap_mode


# ── WIFI_CONNECT ──────────────────────────────────────────────────────────────

class TestWifiConnect:
    def test_success_goes_to_photo_update(self, sm):
        sm._set_state(State.WIFI_CONNECT)
        sm._on_wifi_connect(Event.WIFI_SUCCESS)
        assert sm.state == State.PHOTO_UPDATE

    def test_success_web_ui_goes_to_web_ui_mode(self, sm):
        sm._set_state(State.WIFI_CONNECT)
        sm._on_wifi_connect(Event.WIFI_SUCCESS_WEB_UI)
        assert sm.state == State.WEB_UI_MODE

    def test_fail_goes_to_ap_mode(self, sm):
        sm._set_state(State.WIFI_CONNECT)
        sm._on_wifi_connect(Event.WIFI_FAIL)
        assert sm.state == State.AP_MODE

    def test_shutdown_request(self, sm):
        sm._set_state(State.WIFI_CONNECT)
        sm._on_wifi_connect(Event.SHUTDOWN_REQUEST)
        assert sm.state == State.SHUTDOWN

    def test_error_goes_to_ap_mode(self, sm):
        sm._set_state(State.WIFI_CONNECT)
        sm._on_wifi_connect(Event.ERROR_OCCURRED)
        assert sm.state == State.AP_MODE  # ERROR → _enter_ap_mode


# ── WEB_UI_MODE ───────────────────────────────────────────────────────────────

class TestWebUiMode:
    def test_timeout_goes_to_shutdown(self, sm):
        sm._set_state(State.WEB_UI_MODE)
        sm._on_web_ui_mode(Event.WEB_UI_TIMEOUT)
        assert sm.state == State.SHUTDOWN

    def test_timeout_restores_last_photo(self, sm):
        sm._set_state(State.WEB_UI_MODE)
        sm._on_web_ui_mode(Event.WEB_UI_TIMEOUT)
        sm._restore_last_photo.assert_called_once()

    def test_timeout_clears_button_callback(self, sm):
        sm._set_state(State.WEB_UI_MODE)
        sm._on_web_ui_mode(Event.WEB_UI_TIMEOUT)
        sm._clear_button_callback.assert_called_once()

    def test_timeout_cancels_timer(self, sm):
        sm._set_state(State.WEB_UI_MODE)
        sm._on_web_ui_mode(Event.WEB_UI_TIMEOUT)
        sm._cancel_timeout.assert_called_once()

    def test_shutdown_request_no_photo_restore(self, sm):
        sm._set_state(State.WEB_UI_MODE)
        sm._on_web_ui_mode(Event.SHUTDOWN_REQUEST)
        assert sm.state == State.SHUTDOWN
        sm._restore_last_photo.assert_not_called()  # 디폴트 이미지 경로

    def test_photo_update_request(self, sm):
        sm._set_state(State.WEB_UI_MODE)
        sm._on_web_ui_mode(Event.PHOTO_UPDATE_REQUEST)
        assert sm.state == State.PHOTO_UPDATE


# ── AP_MODE ───────────────────────────────────────────────────────────────────

class TestApMode:
    def test_timeout_goes_to_shutdown(self, sm):
        sm._set_state(State.AP_MODE)
        sm._on_ap_mode(Event.AP_TIMEOUT)
        assert sm.state == State.SHUTDOWN

    def test_timeout_restores_last_photo(self, sm):
        sm._set_state(State.AP_MODE)
        sm._on_ap_mode(Event.AP_TIMEOUT)
        sm._restore_last_photo.assert_called_once()

    def test_timeout_clears_button_callback(self, sm):
        sm._set_state(State.AP_MODE)
        sm._on_ap_mode(Event.AP_TIMEOUT)
        sm._clear_button_callback.assert_called_once()

    def test_timeout_stops_ap(self, sm):
        sm._set_state(State.AP_MODE)
        sm._on_ap_mode(Event.AP_TIMEOUT)
        sm._stop_ap.assert_called_once()

    def test_wifi_success_goes_to_photo_update(self, sm):
        sm._set_state(State.AP_MODE)
        sm._on_ap_mode(Event.WIFI_SUCCESS)
        assert sm.state == State.PHOTO_UPDATE

    def test_wifi_success_clears_button_callback(self, sm):
        sm._set_state(State.AP_MODE)
        sm._on_ap_mode(Event.WIFI_SUCCESS)
        sm._clear_button_callback.assert_called_once()

    def test_shutdown_request(self, sm):
        sm._set_state(State.AP_MODE)
        sm._on_ap_mode(Event.SHUTDOWN_REQUEST)
        assert sm.state == State.SHUTDOWN

    def test_photo_update_request(self, sm):
        sm._set_state(State.AP_MODE)
        sm._on_ap_mode(Event.PHOTO_UPDATE_REQUEST)
        assert sm.state == State.PHOTO_UPDATE


# ── PHOTO_UPDATE ──────────────────────────────────────────────────────────────

class TestPhotoUpdate:
    def test_photo_done_goes_to_shutdown(self, sm):
        sm._set_state(State.PHOTO_UPDATE)
        sm._on_photo_update(Event.PHOTO_DONE)
        assert sm.state == State.SHUTDOWN  # SCHEDULE 즉시 전이

    def test_photo_fail_goes_to_shutdown(self, sm):
        sm._set_state(State.PHOTO_UPDATE)
        sm._on_photo_update(Event.PHOTO_FAIL)
        assert sm.state == State.SHUTDOWN  # SCHEDULE 즉시 전이

    def test_shutdown_request(self, sm):
        sm._set_state(State.PHOTO_UPDATE)
        sm._on_photo_update(Event.SHUTDOWN_REQUEST)
        assert sm.state == State.SHUTDOWN


# ── ERROR ─────────────────────────────────────────────────────────────────────

class TestError:
    def test_enter_error_recovers_to_ap_mode(self, sm):
        sm._set_state(State.ERROR)
        sm._enter_error("test error")
        assert sm.state == State.AP_MODE  # ERROR → _enter_ap_mode


# ── _enter_ap_mode / _enter_web_ui_mode 사이드이펙트 ──────────────────────────

class TestEnterApMode:
    """실제 _enter_ap_mode 실행 — AP manager만 mock."""

    @pytest.fixture
    def mock_ap(self):
        ap = MagicMock()
        ap.is_active = False
        ap.ssid = "EinkFrame-TEST"
        ap._on_timeout = None
        return ap

    def test_state_becomes_ap_mode(self, mock_ap):
        m = StateMachine()
        m._start_web_server = MagicMock()
        m._setup_button_for_exit = MagicMock()
        with patch("wifi.ap_mode.get_ap_manager", return_value=mock_ap):
            m._enter_ap_mode()
        assert m.state == State.AP_MODE

    def test_ap_start_called(self, mock_ap):
        m = StateMachine()
        m._start_web_server = MagicMock()
        m._setup_button_for_exit = MagicMock()
        with patch("wifi.ap_mode.get_ap_manager", return_value=mock_ap):
            m._enter_ap_mode()
        mock_ap.start.assert_called_once()

    def test_ap_timeout_callback_registered(self, mock_ap):
        m = StateMachine()
        m._start_web_server = MagicMock()
        m._setup_button_for_exit = MagicMock()
        with patch("wifi.ap_mode.get_ap_manager", return_value=mock_ap):
            m._enter_ap_mode()
        assert mock_ap._on_timeout is not None

    def test_web_server_started_on_port_80(self, mock_ap):
        m = StateMachine()
        m._start_web_server = MagicMock()
        m._setup_button_for_exit = MagicMock()
        with patch("wifi.ap_mode.get_ap_manager", return_value=mock_ap):
            m._enter_ap_mode()
        m._start_web_server.assert_called_once_with(port=80)

    def test_button_for_exit_registered(self, mock_ap):
        m = StateMachine()
        m._start_web_server = MagicMock()
        m._setup_button_for_exit = MagicMock()
        with patch("wifi.ap_mode.get_ap_manager", return_value=mock_ap):
            m._enter_ap_mode()
        m._setup_button_for_exit.assert_called_once()


class TestEnterWebUiMode:
    """실제 _enter_web_ui_mode 실행 — WiFi manager와 config만 mock."""

    @pytest.fixture
    def mock_wifi(self):
        status = MagicMock()
        status.ip_address = "192.168.1.100"
        wifi = MagicMock()
        wifi.get_status.return_value = status
        return wifi

    @pytest.fixture
    def mock_config(self):
        config = MagicMock()
        config.get.return_value = 600  # web_ui.timeout
        return config

    def test_state_becomes_web_ui_mode(self, mock_wifi, mock_config):
        m = StateMachine()
        m._start_web_server = MagicMock()
        m._start_timeout = MagicMock()
        m._setup_button_for_exit = MagicMock()
        with patch("wifi.manager.get_wifi_manager", return_value=mock_wifi), \
             patch("config.get_config", return_value=mock_config):
            m._enter_web_ui_mode()
        assert m.state == State.WEB_UI_MODE

    def test_web_server_started_on_port_8080(self, mock_wifi, mock_config):
        m = StateMachine()
        m._start_web_server = MagicMock()
        m._start_timeout = MagicMock()
        m._setup_button_for_exit = MagicMock()
        with patch("wifi.manager.get_wifi_manager", return_value=mock_wifi), \
             patch("config.get_config", return_value=mock_config):
            m._enter_web_ui_mode()
        m._start_web_server.assert_called_once_with(port=8080)

    def test_timeout_timer_started(self, mock_wifi, mock_config):
        m = StateMachine()
        m._start_web_server = MagicMock()
        m._start_timeout = MagicMock()
        m._setup_button_for_exit = MagicMock()
        with patch("wifi.manager.get_wifi_manager", return_value=mock_wifi), \
             patch("config.get_config", return_value=mock_config):
            m._enter_web_ui_mode()
        m._start_timeout.assert_called_once()

    def test_button_for_exit_registered(self, mock_wifi, mock_config):
        m = StateMachine()
        m._start_web_server = MagicMock()
        m._start_timeout = MagicMock()
        m._setup_button_for_exit = MagicMock()
        with patch("wifi.manager.get_wifi_manager", return_value=mock_wifi), \
             patch("config.get_config", return_value=mock_config):
            m._enter_web_ui_mode()
        m._setup_button_for_exit.assert_called_once()
