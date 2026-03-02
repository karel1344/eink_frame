"""API routes for E-Ink Photo Frame web UI."""

from __future__ import annotations

from typing import Any, Optional, List, Dict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..config import get_config
from ..wifi.manager import get_wifi_manager

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


@router.post("/api/system/apply")
async def system_apply() -> ApiResponse:
    """Apply settings and reconnect to WiFi.

    This endpoint saves settings, stops AP mode, and attempts WiFi connection.
    """
    # TODO: Implement event queue integration
    # event_queue.put(Event.AP_USER_APPLY)
    return ApiResponse(success=True, message="Applying settings and reconnecting")


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
