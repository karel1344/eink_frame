"""Captive portal DNS server for AP mode."""

from __future__ import annotations

import logging
import socket
import struct
import threading
from typing import Optional

from .ap_mode import ExecutionMode

logger = logging.getLogger(__name__)


class CaptivePortalDNS:
    """Simple DNS server that redirects all queries to AP IP.

    This enables captive portal detection on mobile devices.
    All DNS queries return the AP's IP address, causing devices
    to open the portal page automatically.
    """

    # NetworkManager's default hotspot IP
    AP_IP = "10.42.0.1"
    DNS_PORT = 53

    def __init__(self, mode: ExecutionMode = ExecutionMode.NORMAL):
        """Initialize DNS server.

        Args:
            mode: Execution mode for testing.
        """
        self.mode = mode
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._socket: Optional[socket.socket] = None

    def start(self) -> bool:
        """Start DNS server on port 53.

        Returns:
            True if started successfully.
        """
        if self._running:
            logger.warning("DNS server already running")
            return True

        if self.mode == ExecutionMode.DRY_RUN:
            logger.info(f"[DRY-RUN] Would start DNS server on {self.AP_IP}:{self.DNS_PORT}")
            self._running = True
            return True

        elif self.mode == ExecutionMode.PREVIEW:
            print(f"[PREVIEW] Starting DNS server on {self.AP_IP}:{self.DNS_PORT}")
            print(f"  All DNS queries will resolve to {self.AP_IP}")
            self._running = True
            return True

        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Try to bind to AP IP first, fall back to all interfaces
            try:
                self._socket.bind((self.AP_IP, self.DNS_PORT))
                logger.info(f"DNS server bound to {self.AP_IP}:{self.DNS_PORT}")
            except OSError:
                self._socket.bind(("0.0.0.0", self.DNS_PORT))
                logger.info(f"DNS server bound to 0.0.0.0:{self.DNS_PORT}")

            self._socket.settimeout(1.0)

            self._running = True
            self._thread = threading.Thread(target=self._serve, daemon=True)
            self._thread.start()

            logger.info(f"DNS server started, all queries resolve to {self.AP_IP}")
            return True

        except PermissionError:
            logger.error("DNS server requires root privileges (port 53)")
            return False
        except OSError as e:
            logger.error(f"Failed to bind DNS server: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to start DNS server: {e}")
            return False

    def stop(self) -> None:
        """Stop DNS server."""
        if not self._running:
            return

        logger.info("Stopping DNS server")
        self._running = False

        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

        logger.info("DNS server stopped")

    def _serve(self) -> None:
        """DNS server loop."""
        while self._running:
            try:
                data, addr = self._socket.recvfrom(512)  # type: ignore
                response = self._build_response(data)
                self._socket.sendto(response, addr)  # type: ignore
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    logger.debug("DNS socket closed")
                break
            except Exception as e:
                if self._running:
                    logger.exception(f"DNS server error: {e}")

    def _build_response(self, query: bytes) -> bytes:
        """Build DNS response pointing all queries to AP IP.

        Args:
            query: Raw DNS query packet.

        Returns:
            Raw DNS response packet.
        """
        # Parse query header (first 12 bytes)
        transaction_id = query[:2]

        # Build response header
        # Flags: 0x8180 = Response, Authoritative, No error
        flags = b"\x81\x80"
        questions = query[4:6]  # Copy question count
        answers = b"\x00\x01"  # 1 answer
        authority = b"\x00\x00"
        additional = b"\x00\x00"

        header = transaction_id + flags + questions + answers + authority + additional

        # Find end of question section
        # Format: labels (length-prefixed strings) + null byte + qtype (2) + qclass (2)
        question_end = 12
        while question_end < len(query) and query[question_end] != 0:
            label_len = query[question_end]
            question_end += label_len + 1
        question_end += 5  # null byte + qtype (2) + qclass (2)

        question = query[12:question_end]

        # Build answer
        # Name: pointer to name in question (0xC00C = offset 12)
        # Type: A (0x0001)
        # Class: IN (0x0001)
        # TTL: 60 seconds (0x0000003C)
        # Data length: 4 (0x0004)
        # Data: IP address
        answer = (
            b"\xc0\x0c"  # Pointer to name in question
            + b"\x00\x01"  # Type A
            + b"\x00\x01"  # Class IN
            + b"\x00\x00\x00\x3c"  # TTL 60 seconds
            + b"\x00\x04"  # Data length 4
            + socket.inet_aton(self.AP_IP)  # IP address
        )

        return header + question + answer

    @property
    def is_running(self) -> bool:
        """Check if DNS server is running."""
        return self._running


# Captive portal detection URLs that need special handling
CAPTIVE_PORTAL_PATHS = [
    # Android
    "/generate_204",
    "/gen_204",
    "/connectivitycheck.gstatic.com",
    # iOS
    "/hotspot-detect.html",
    "/library/test/success.html",
    # Windows
    "/ncsi.txt",
    "/connecttest.txt",
    # Generic
    "/success.txt",
]


def register_captive_portal_routes(app) -> None:
    """Register captive portal detection routes with FastAPI app.

    These routes intercept connectivity check requests from mobile devices
    and redirect them to the main web UI, triggering the captive portal popup.

    Args:
        app: FastAPI application instance.
    """
    from fastapi import Request
    from fastapi.responses import RedirectResponse, Response

    @app.get("/generate_204")
    @app.get("/gen_204")
    async def android_captive_check():
        """Android captive portal check - redirect to trigger portal."""
        return RedirectResponse(url="/", status_code=302)

    @app.get("/hotspot-detect.html")
    async def ios_captive_check():
        """iOS captive portal check - redirect to trigger portal."""
        return RedirectResponse(url="/", status_code=302)

    @app.get("/library/test/success.html")
    async def ios_captive_check_alt():
        """iOS alternate captive portal check."""
        return RedirectResponse(url="/", status_code=302)

    @app.get("/ncsi.txt")
    async def windows_captive_check():
        """Windows NCSI check - redirect to trigger portal."""
        return RedirectResponse(url="/", status_code=302)

    @app.get("/connecttest.txt")
    async def windows_captive_check_alt():
        """Windows alternate connectivity check."""
        return RedirectResponse(url="/", status_code=302)

    @app.get("/success.txt")
    async def generic_success_check():
        """Generic success check - redirect to trigger portal."""
        return RedirectResponse(url="/", status_code=302)

    logger.info("Captive portal routes registered")
