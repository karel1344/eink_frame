"""API routes for E-Ink Photo Frame web UI."""

from __future__ import annotations

from typing import Any, Optional, List, Dict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from pydantic import BaseModel

from ..config import get_config
from ..wifi.manager import get_wifi_manager
from ..wifi.ap_mode import get_ap_manager, APStatus
from ..wifi.captive_portal import get_captive_dns, CAPTIVE_PORTAL_URLS

router = APIRouter()


# ============================================================================
# Pydantic Models
# ============================================================================


class WifiSettings(BaseModel):
    """WiFi configuration model."""

    enabled: bool = True
    ssid: str = ""
    password: str = ""


class WifiNetwork(BaseModel):
    """WiFi network scan result."""

    ssid: str
    signal: int  # Signal strength in percentage
    security: str  # open / wpa / wpa2


class SettingsUpdate(BaseModel):
    """Settings update request model."""

    wifi: WifiSettings | None = None
    schedule: dict[str, Any] | None = None
    photo_selection: dict[str, Any] | None = None
    display: dict[str, Any] | None = None


class StatusResponse(BaseModel):
    """System status response model."""

    battery: dict[str, Any]
    wifi_connected: bool
    last_update: str | None
    next_update: str | None
    current_photo: dict[str, Any] | None
    version: str


class ApiResponse(BaseModel):
    """Generic API response model."""

    success: bool
    message: str = ""
    data: dict[str, Any] | None = None


# ============================================================================
# Page Routes
# ============================================================================


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve main web UI page."""
    from .app import get_templates

    templates = get_templates()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "title": "E-Ink Photo Frame"},
    )


# ============================================================================
# Status API
# ============================================================================


@router.get("/api/status", response_model=StatusResponse)
async def get_status():
    """Get system status."""
    # TODO: Implement actual status retrieval
    return StatusResponse(
        battery={"voltage": 3.85, "percentage": 72, "charging": False},
        wifi_connected=False,  # In AP mode
        last_update=None,
        next_update=None,
        current_photo=None,
        version="0.1.0",
    )


# ============================================================================
# Settings API
# ============================================================================


@router.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    """Get current settings."""
    config = get_config()
    return config.to_dict()


@router.put("/api/settings")
async def update_settings(settings: SettingsUpdate) -> ApiResponse:
    """Update settings."""
    config = get_config()

    if settings.wifi is not None:
        config.set_section("wifi", settings.wifi.model_dump())

    if settings.schedule is not None:
        config.update({"schedule": settings.schedule})

    if settings.photo_selection is not None:
        config.update({"photo_selection": settings.photo_selection})

    if settings.display is not None:
        config.update({"display": settings.display})

    config.save()

    return ApiResponse(success=True, message="Settings saved")


# ============================================================================
# WiFi API
# ============================================================================


@router.get("/api/wifi/scan")
async def scan_wifi() -> list[WifiNetwork]:
    """Scan for available WiFi networks.

    Note: This only works on Raspberry Pi with NetworkManager.
    Returns mock data on development machines.
    """
    wifi = get_wifi_manager()
    networks = wifi.scan()

    return [
        WifiNetwork(ssid=n.ssid, signal=n.signal, security=n.security)
        for n in networks
    ]


@router.get("/api/wifi/status")
async def get_wifi_status() -> dict[str, Any]:
    """Get current WiFi connection status."""
    config = get_config()
    wifi = get_wifi_manager()
    status = wifi.get_status()

    return {
        "enabled": config.wifi_enabled,
        "configured_ssid": config.wifi_ssid,
        "connected": status.connected,
        "current_ssid": status.ssid,
        "ip_address": status.ip_address,
        "ap_mode": not status.connected,  # If not connected to WiFi, assume AP mode
    }


class WifiConnectRequest(BaseModel):
    """WiFi connection request."""

    ssid: str
    password: str = ""


@router.post("/api/wifi/connect")
async def connect_wifi(request: WifiConnectRequest) -> ApiResponse:
    """Connect to a WiFi network.

    Note: This disconnects from AP mode and attempts to connect to the specified network.
    """
    wifi = get_wifi_manager()

    if not wifi.is_available:
        return ApiResponse(success=False, message="WiFi manager not available (nmcli not found)")

    # Save credentials to config
    config = get_config()
    config.set("wifi.ssid", request.ssid)
    config.set("wifi.password", request.password)
    config.save()

    # Attempt connection
    success = wifi.connect(request.ssid, request.password)

    if success:
        return ApiResponse(success=True, message=f"Connected to {request.ssid}")
    else:
        return ApiResponse(success=False, message=f"Failed to connect to {request.ssid}")


# ============================================================================
# AP Mode API
# ============================================================================


class APStatusResponse(BaseModel):
    """AP mode status response."""

    active: bool
    ssid: str | None
    elapsed_seconds: float
    timeout_remaining: float
    execution_mode: str


@router.get("/api/ap/status")
async def get_ap_status() -> APStatusResponse:
    """Get AP mode status."""
    ap = get_ap_manager()
    status = ap.get_status()
    return APStatusResponse(
        active=status.active,
        ssid=status.ssid,
        elapsed_seconds=status.elapsed_seconds,
        timeout_remaining=status.timeout_remaining,
        execution_mode=status.execution_mode,
    )


@router.post("/api/ap/start")
async def start_ap_mode() -> ApiResponse:
    """Start AP mode (for testing).

    In production, AP mode is started by the state machine.
    This endpoint is for development/testing only.
    """
    ap = get_ap_manager()

    if ap.is_active:
        return ApiResponse(success=True, message="AP mode already active")

    success = ap.start()
    if success:
        return ApiResponse(
            success=True,
            message=f"AP mode started: {ap.ssid}",
            data={"ssid": ap.ssid},
        )
    else:
        return ApiResponse(success=False, message="Failed to start AP mode")


@router.post("/api/ap/stop")
async def stop_ap_mode() -> ApiResponse:
    """Stop AP mode (for testing).

    In production, AP mode is stopped by the state machine.
    This endpoint is for development/testing only.
    """
    ap = get_ap_manager()

    if not ap.is_active:
        return ApiResponse(success=True, message="AP mode not active")

    success = ap.stop(reason="api_request")
    if success:
        return ApiResponse(success=True, message="AP mode stopped")
    else:
        return ApiResponse(success=False, message="Failed to stop AP mode")


# ============================================================================
# System Control API
# ============================================================================


@router.post("/api/system/shutdown")
async def system_shutdown() -> ApiResponse:
    """Shutdown system (display default image and power off).

    This endpoint puts an event in the queue for the main state machine.
    """
    # TODO: Implement event queue integration
    # event_queue.put(Event.AP_USER_SHUTDOWN)
    return ApiResponse(success=True, message="Shutdown initiated")


class ApplyRequest(BaseModel):
    """Apply settings request."""

    wifi: WifiSettings | None = None


_wifi_connect_in_progress = False


def _connect_wifi_background(ssid: str, password: str) -> None:
    """Background task to connect to WiFi after AP mode stops."""
    import logging
    import subprocess
    import time

    global _wifi_connect_in_progress
    logger = logging.getLogger(__name__)
    wifi = get_wifi_manager()
    ap = get_ap_manager()

    try:
        # Wait for HTTP response to be sent before stopping AP
        time.sleep(1)

        # 1. Stop AP mode connections
        logger.info("Stopping any active AP connections")
        subprocess.run(["nmcli", "connection", "down", "Hotspot"], capture_output=True)
        subprocess.run(["nmcli", "connection", "down", "EinkFrame-Open"], capture_output=True)
        ap._active = False

        # Wait for interface to settle
        time.sleep(3)

        # 2. Disconnect current WiFi
        logger.info("Disconnecting current WiFi connection")
        wifi.disconnect()
        time.sleep(2)

        # 3. Attempt connection with retries
        for connect_attempt in range(3):
            logger.info(f"WiFi connect attempt {connect_attempt + 1}/3 to: {ssid}")
            wifi.connect(ssid, password)

            # Verify connection (10 seconds per attempt)
            # Check that we connected with OUR connection, not an existing one
            for _ in range(2):
                time.sleep(5)
                status = wifi.get_status()
                logger.info(f"Connection check: connected={status.connected}, ssid={status.ssid}, ip={status.ip_address}")
                # Connection name must match what we created (ssid), not existing like netplan-wlan0-XXX
                if status.connected and status.ip_address and status.ssid == ssid:
                    logger.info(f"Successfully connected to {ssid}")
                    return

            # Wait before retry
            if connect_attempt < 2:
                logger.info("Connection not established, retrying...")
                time.sleep(2)

        # 4. All attempts failed - restart AP mode
        logger.warning(f"Failed to connect to {ssid} after 3 attempts, restarting AP mode")
        ap.start()

    except Exception as e:
        logger.error(f"Error during WiFi connection: {e}")
        # Always restart AP mode on error
        try:
            ap.start()
        except Exception:
            pass

    finally:
        _wifi_connect_in_progress = False


@router.post("/api/system/apply")
async def system_apply(request: ApplyRequest | None = None) -> ApiResponse:
    """Apply settings and reconnect to WiFi.

    This endpoint saves WiFi settings and starts a background task
    to connect. The response is sent immediately before AP mode stops,
    so the client receives confirmation.
    """
    import logging
    import threading

    global _wifi_connect_in_progress
    logger = logging.getLogger(__name__)
    config = get_config()

    # Prevent duplicate execution
    if _wifi_connect_in_progress:
        return ApiResponse(success=False, message="WiFi connection already in progress")

    # 1. Save WiFi settings if provided
    if request and request.wifi:
        config.set("wifi.ssid", request.wifi.ssid)
        config.set("wifi.password", request.wifi.password)
        config.set("wifi.enabled", request.wifi.enabled)
        config.save()
        logger.info(f"Saved WiFi settings for SSID: {request.wifi.ssid}")

    # Get saved credentials
    ssid = config.wifi_ssid
    password = config.wifi_password

    if not ssid:
        return ApiResponse(success=False, message="No WiFi SSID configured")

    # 2. Start background thread to handle WiFi connection
    # This allows us to send response before AP mode stops
    _wifi_connect_in_progress = True
    try:
        thread = threading.Thread(
            target=_connect_wifi_background,
            args=(ssid, password),
            daemon=True,
        )
        thread.start()
    except Exception as e:
        _wifi_connect_in_progress = False
        logger.error(f"Failed to start WiFi connection thread: {e}")
        return ApiResponse(success=False, message="Failed to start connection process")

    return ApiResponse(
        success=True,
        message=f"Connecting to {ssid}... AP mode will stop shortly.",
    )


# ============================================================================
# Captive Portal Detection Routes
# ============================================================================


@router.get("/captive")
async def captive_portal_page(request: Request):
    """Simple captive portal landing page.

    Directs users to open the full UI in their browser.
    """
    from .app import get_templates

    templates = get_templates()
    return templates.TemplateResponse("captive.html", {"request": request})


async def _get_captive_html(request: Request):
    """Return captive portal HTML directly (no redirect)."""
    from .app import get_templates

    templates = get_templates()
    return templates.TemplateResponse("captive.html", {"request": request})


@router.get("/generate_204")
@router.get("/gen_204")
async def captive_portal_android(request: Request):
    """Android captive portal detection.

    Android expects 204 for internet, non-204 triggers portal popup.
    """
    ap = get_ap_manager()
    if ap.is_active:
        # Return HTML directly with 200 (not 204) to trigger portal
        return await _get_captive_html(request)
    return PlainTextResponse("", status_code=204)


@router.get("/hotspot-detect.html")
@router.get("/library/test/success.html")
async def captive_portal_apple(request: Request):
    """iOS/macOS captive portal detection.

    Apple expects "Success" text for internet, anything else triggers portal.
    """
    ap = get_ap_manager()
    if ap.is_active:
        # Return HTML directly (not "Success") to trigger portal
        return await _get_captive_html(request)
    return PlainTextResponse("Success", status_code=200)


@router.get("/ncsi.txt")
async def captive_portal_windows(request: Request):
    """Windows NCSI captive portal detection."""
    ap = get_ap_manager()
    if ap.is_active:
        return await _get_captive_html(request)
    return PlainTextResponse("Microsoft NCSI", status_code=200)


@router.get("/connecttest.txt")
async def captive_portal_windows_connect(request: Request):
    """Windows connectivity test."""
    ap = get_ap_manager()
    if ap.is_active:
        return await _get_captive_html(request)
    return PlainTextResponse("Microsoft Connect Test", status_code=200)


@router.get("/success.txt")
async def captive_portal_firefox(request: Request):
    """Firefox captive portal detection."""
    ap = get_ap_manager()
    if ap.is_active:
        return await _get_captive_html(request)
    return PlainTextResponse("success\n", status_code=200)


@router.get("/api/captive/status")
async def captive_dns_status() -> dict[str, Any]:
    """Get captive portal DNS server status."""
    dns = get_captive_dns()
    return {
        "dns_running": dns.is_running,
        "ap_ip": dns._ap_ip,
    }


@router.post("/api/captive/start")
async def start_captive_dns() -> ApiResponse:
    """Start captive portal DNS server (requires root)."""
    dns = get_captive_dns()
    if dns.is_running:
        return ApiResponse(success=True, message="DNS server already running")

    success = dns.start()
    if success:
        return ApiResponse(success=True, message="Captive portal DNS started")
    return ApiResponse(success=False, message="Failed to start DNS (requires root)")


@router.post("/api/captive/stop")
async def stop_captive_dns() -> ApiResponse:
    """Stop captive portal DNS server."""
    dns = get_captive_dns()
    dns.stop()
    return ApiResponse(success=True, message="Captive portal DNS stopped")


@router.get("/api/captive/test")
async def test_captive_dns() -> dict[str, Any]:
    """Test captive portal DNS server by sending a query.

    This helps debug DNS issues by testing locally.
    """
    import socket
    import struct

    dns = get_captive_dns()
    ap_ip = dns._ap_ip

    # Build a simple DNS query for google.com
    transaction_id = b"\x00\x01"
    flags = b"\x01\x00"  # Standard query
    counts = struct.pack("!HHHH", 1, 0, 0, 0)  # 1 question
    # google.com as DNS labels
    domain = b"\x06google\x03com\x00"
    qtype_qclass = struct.pack("!HH", 1, 1)  # A record, IN class
    query = transaction_id + flags + counts + domain + qtype_qclass

    result = {
        "dns_running": dns.is_running,
        "ap_ip": ap_ip,
        "query_sent": False,
        "response_received": False,
        "response_ip": None,
        "error": None,
    }

    if not dns.is_running:
        result["error"] = "DNS server not running"
        return result

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3.0)
        sock.sendto(query, (ap_ip, 53))
        result["query_sent"] = True

        response, _ = sock.recvfrom(512)
        result["response_received"] = True

        # Extract IP from response (last 4 bytes)
        if len(response) >= 4:
            ip_bytes = response[-4:]
            result["response_ip"] = ".".join(str(b) for b in ip_bytes)

        sock.close()
    except socket.timeout:
        result["error"] = "DNS timeout - no response received"
    except Exception as e:
        result["error"] = str(e)

    return result


# ============================================================================
# Photos API (placeholder)
# ============================================================================


@router.get("/api/photos")
async def list_photos() -> dict[str, Any]:
    """List local photos with thumbnails."""
    # TODO: Implement photo listing
    return {
        "photos": [],
        "total": 0,
        "storage_used_mb": 0,
        "storage_available_mb": 500,
    }


@router.post("/api/photos/upload")
async def upload_photo() -> ApiResponse:
    """Upload a new photo."""
    # TODO: Implement photo upload
    return ApiResponse(success=False, message="Not implemented yet")


@router.delete("/api/photos/{photo_id}")
async def delete_photo(photo_id: str) -> ApiResponse:
    """Delete a photo."""
    # TODO: Implement photo deletion
    return ApiResponse(success=False, message="Not implemented yet")
