"""API routes for E-Ink Photo Frame web UI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, List, Dict

from fastapi import APIRouter, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, FileResponse
from pydantic import BaseModel

from config import get_config
from wifi.manager import get_wifi_manager
from wifi.ap_mode import get_ap_manager, APStatus
from wifi.captive_portal import get_captive_dns, CAPTIVE_PORTAL_URLS

logger = logging.getLogger(__name__)

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

    wifi: Optional[WifiSettings] = None
    schedule: Optional[dict[str, Any]] = None
    photo_selection: Optional[dict[str, Any]] = None
    display: Optional[dict[str, Any]] = None
    image_processing: Optional[dict[str, Any]] = None
    battery: Optional[dict[str, Any]] = None
    storage: Optional[dict[str, Any]] = None


class StatusResponse(BaseModel):
    """System status response model."""

    battery: dict[str, Any]
    wifi_connected: bool
    last_update: Optional[str]
    next_update: Optional[str]
    current_photo: Optional[dict[str, Any]]
    version: str
    state: Optional[str] = None


class ApiResponse(BaseModel):
    """Generic API response model."""

    success: bool
    message: str = ""
    data: Optional[dict[str, Any]] = None


# ============================================================================
# Page Routes
# ============================================================================


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve main web UI page."""
    from web.app import get_templates

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
    from power_manager import get_power_manager

    from state_machine import get_state_machine

    battery = get_power_manager().get_battery_status()
    wifi_connected = get_wifi_manager().get_status().connected
    sm = get_state_machine()
    return StatusResponse(
        battery=battery,
        wifi_connected=wifi_connected,
        last_update=None,
        next_update=get_config().update_time,
        current_photo=None,
        version="0.1.0",
        state=sm.state.name if sm else None,
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

    if settings.image_processing is not None:
        config.update({"image_processing": settings.image_processing})

    if settings.battery is not None:
        config.update({"battery": settings.battery})

    if settings.storage is not None:
        config.update({"storage": settings.storage})

    config.save()

    # Apply startup alarm to Witty Pi immediately when schedule changes
    if settings.schedule is not None:
        try:
            from power_manager import get_power_manager
            get_power_manager().set_startup_from_config()
        except Exception as e:
            logger.warning("Failed to apply startup alarm to Witty Pi: %s", e)

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
    ssid: Optional[str]
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
    """Request shutdown via state machine, or direct shutdown in dev mode."""
    from state_machine import get_state_machine, Event

    sm = get_state_machine()
    if sm:
        sm.post_event(Event.SHUTDOWN_REQUEST)
        return ApiResponse(success=True, message="Shutdown requested")

    # Dev mode fallback: direct shutdown
    from power_manager import get_power_manager
    get_power_manager().schedule_and_shutdown()
    return ApiResponse(success=True, message="Shutdown initiated")


@router.post("/api/system/photo-update")
async def system_photo_update() -> ApiResponse:
    """Request photo update via state machine."""
    from state_machine import get_state_machine, Event

    sm = get_state_machine()
    if sm:
        sm.post_event(Event.PHOTO_UPDATE_REQUEST)
        return ApiResponse(success=True, message="Photo update requested")
    return ApiResponse(success=False, message="State machine not running")


class ApplyRequest(BaseModel):
    """Apply settings request."""

    wifi: Optional[WifiSettings] = None


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
                    # Notify state machine of WiFi success
                    from state_machine import get_state_machine, Event as SmEvent
                    sm = get_state_machine()
                    if sm:
                        sm.post_event(SmEvent.WIFI_SUCCESS)
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
async def system_apply(request: Optional[ApplyRequest] = None) -> ApiResponse:
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
    from web.app import get_templates

    templates = get_templates()
    return templates.TemplateResponse("captive.html", {"request": request})


async def _get_captive_html(request: Request):
    """Return captive portal HTML directly (no redirect)."""
    from web.app import get_templates

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
# Photos API
# ============================================================================

def _get_local_source():
    """Return a LocalPhotoSource using paths from config."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
    from photo_source.local import LocalPhotoSource
    from database import get_db

    config = get_config()
    photos_path = config.get("photo_sources.local.path", "photos/local")
    photos_dir = Path(__file__).parent.parent.parent / photos_path
    return LocalPhotoSource(photos_dir, db=get_db())


@router.get("/api/photos")
async def list_photos() -> dict[str, Any]:
    """List local photos."""
    source = _get_local_source()
    photos = source.list_photos()

    # Compute storage used
    storage_used = sum((p.file_size or 0) for p in photos)
    storage_limit_mb = get_config().get("storage.local_photos_max_mb", 500)

    return {
        "photos": [
            {
                "id": p.id,
                "filename": p.filename,
                "title": p.display_name,
                "width": p.width,
                "height": p.height,
                "mime_type": p.mime_type,
                "file_size": p.file_size,
                "taken_at": p.taken_at.isoformat() if p.taken_at else None,
                "added_at": p.added_at.isoformat() if p.added_at else None,
                "thumbnail_url": f"/api/photos/{p.id}/thumbnail" if p.thumbnail_path else None,
            }
            for p in photos
        ],
        "total": len(photos),
        "storage_used_mb": round(storage_used / (1024 * 1024), 1),
        "storage_limit_mb": storage_limit_mb,
    }


@router.post("/api/photos/upload")
async def upload_photo(file: UploadFile = File(...)) -> ApiResponse:
    """Upload a new photo (JPEG, PNG, HEIC — max 20 MB)."""
    source = _get_local_source()
    try:
        photo = source.save_upload(file.filename or "upload.jpg", file.file)
        return ApiResponse(
            success=True,
            message=f"Uploaded {photo.filename}",
            data={
                "id": photo.id,
                "filename": photo.filename,
                "width": photo.width,
                "height": photo.height,
                "thumbnail_url": f"/api/photos/{photo.id}/thumbnail" if photo.thumbnail_path else None,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Upload failed: %s", e)
        raise HTTPException(status_code=500, detail="Upload failed")


@router.delete("/api/photos/{photo_id}")
async def delete_photo(photo_id: int) -> ApiResponse:
    """Delete a photo by id."""
    source = _get_local_source()
    photo = source.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    source.delete_photo(photo_id)
    return ApiResponse(success=True, message=f"Deleted photo {photo_id}")


@router.get("/api/photos/{photo_id}/thumbnail")
async def get_thumbnail(photo_id: int):
    """Serve the thumbnail image for a photo."""
    source = _get_local_source()
    thumb_path = source.ensure_thumbnail(photo_id)
    if thumb_path is None or not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(thumb_path, media_type="image/jpeg")


@router.get("/api/photos/{photo_id}/original")
async def get_original_photo(photo_id: int):
    """Serve the original photo file for the crop UI."""
    source = _get_local_source()
    photo = source.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    file_path = Path(photo.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, media_type=photo.mime_type or "image/jpeg")


@router.post("/api/photos/{photo_id}/crop")
async def crop_photo(photo_id: int, file: UploadFile = File(...)) -> ApiResponse:
    """Overwrite a photo with a cropped version and regenerate its thumbnail."""
    import io
    from PIL import Image as PILImage
    from database import get_db

    source = _get_local_source()
    photo = source.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    try:
        content = await file.read()
        img = PILImage.open(io.BytesIO(content))
        file_path = Path(photo.file_path)
        fmt = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG"}.get(
            file_path.suffix.lower(), "JPEG"
        )
        img.save(str(file_path), format=fmt)

        db = get_db()
        if photo.thumbnail_path:
            Path(photo.thumbnail_path).unlink(missing_ok=True)
        db.update_photo(
            photo_id,
            width=img.width,
            height=img.height,
            file_size=file_path.stat().st_size,
            thumbnail_path=None,
        )
        source.ensure_thumbnail(photo_id)
        return ApiResponse(success=True, message="Cropped successfully")
    except Exception as e:
        logger.exception("Crop failed for photo %d: %s", photo_id, e)
        raise HTTPException(status_code=500, detail="Crop failed")


# ============================================================================
# Image Preview API
# ============================================================================

_PALETTE_RGB = [
    (  0,   0,   0),   # 0: Black
    (255, 255, 255),   # 1: White
    (207, 212,   4),   # 2: Yellow
    (150,  28,  23),   # 3: Red
    (  0,   0,   0),   # 4: unused
    ( 12,  84, 172),   # 5: Blue
    ( 29,  90,  72),   # 6: Green
]
_COLOR_NAMES = ["Black", "White", "Yellow", "Red", "(unused)", "Blue", "Green"]


def _build_eink_palette():
    from PIL import Image
    pal = Image.new("P", (1, 1))
    flat = [c for rgb in _PALETTE_RGB for c in rgb] + [0] * (3 * (256 - len(_PALETTE_RGB)))
    pal.putpalette(flat)
    return pal


def _img_to_b64(img) -> str:
    import base64, io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _simulate_eink(img):
    """Quantize PIL RGB image → (simulated_rgb, stats)."""
    from PIL import Image
    pal = _build_eink_palette()
    quantized = img.quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG)
    raw = quantized.tobytes("raw")
    total = max(len(raw), 1)
    counts = [0] * len(_PALETTE_RGB)
    for b in raw:
        if b < len(counts):
            counts[b] += 1
    stats = {
        _COLOR_NAMES[i]: round(counts[i] / total * 100, 1)
        for i in range(len(_PALETTE_RGB))
        if _COLOR_NAMES[i] != "(unused)"
    }
    return quantized.convert("RGB"), stats


def _get_random_photo_path() -> Optional[Path]:
    import random
    config = get_config()
    photos_path = config.get("photo_sources.local.path", "photos/local")
    photos_dir = Path(__file__).parent.parent.parent / photos_path
    if not photos_dir.exists():
        return None
    exts = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
    photos = [p for p in photos_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
    return random.choice(photos) if photos else None


class ImagePreviewParams(BaseModel):
    brightness: float = 1.0
    gamma: float = 1.0
    contrast: float = 1.2
    saturation: float = 1.5
    sharpness: float = 1.3
    warmth: float = 1.0
    photo_path: Optional[str] = None


def _make_processor(params: ImagePreviewParams, *, enhancements: bool = True):
    from image_processor import ImageProcessor
    config = get_config()
    if enhancements:
        br, gm, co, sa, sh, wa = (
            params.brightness, params.gamma, params.contrast,
            params.saturation, params.sharpness, params.warmth,
        )
    else:
        br = gm = co = sa = sh = wa = 1.0
    return ImageProcessor(
        display_width=800,
        display_height=480,
        fill_mode=config.get("image_processing.fill_mode", "fit"),
        auto_rotate=config.get("image_processing.auto_rotate", True),
        show_battery=False,
        brightness=br, gamma=gm, contrast=co,
        saturation=sa, sharpness=sh, warmth=wa,
    )


@router.post("/api/image-preview/random")
async def image_preview_random(params: ImagePreviewParams) -> dict[str, Any]:
    """Pick a random local photo and return original + E-Ink simulation."""
    import asyncio

    photo_path = _get_random_photo_path()
    if photo_path is None:
        return {"error": "사진이 없습니다. 사진 탭에서 먼저 업로드하세요."}

    def _run():
        orig_img = _make_processor(params, enhancements=False).process(photo_path)
        enh_img  = _make_processor(params, enhancements=True).process(photo_path)
        sim, stats = _simulate_eink(enh_img)
        return _img_to_b64(orig_img), _img_to_b64(sim), stats

    try:
        loop = asyncio.get_running_loop()
        orig_b64, sim_b64, stats = await loop.run_in_executor(None, _run)
        return {
            "photo_path": str(photo_path),
            "photo_name": photo_path.name,
            "original_b64": orig_b64,
            "simulated_b64": sim_b64,
            "stats": stats,
        }
    except Exception as e:
        logger.exception("image_preview_random failed")
        return {"error": str(e)}


@router.post("/api/image-preview/process")
async def image_preview_process(params: ImagePreviewParams) -> dict[str, Any]:
    """Re-process a photo with updated params and return E-Ink simulation."""
    import asyncio

    if not params.photo_path:
        raise HTTPException(status_code=400, detail="photo_path required")
    photo_path = Path(params.photo_path)
    if not photo_path.exists():
        raise HTTPException(status_code=404, detail="Photo not found")

    def _run():
        enh_img = _make_processor(params, enhancements=True).process(photo_path)
        sim, stats = _simulate_eink(enh_img)
        return _img_to_b64(sim), stats

    try:
        loop = asyncio.get_running_loop()
        sim_b64, stats = await loop.run_in_executor(None, _run)
        return {"simulated_b64": sim_b64, "stats": stats}
    except Exception as e:
        logger.exception("image_preview_process failed")
        raise HTTPException(status_code=500, detail=str(e))
