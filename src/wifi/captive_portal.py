"""Captive Portal DNS server for AP mode.

Redirects all DNS queries to the AP IP address to trigger
captive portal detection on mobile devices.
"""

from __future__ import annotations

import socket
import struct
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class CaptivePortalDNS:
    """DNS server that redirects all queries to AP IP.

    When a device connects to the AP, it checks for internet connectivity
    by making DNS queries. This server responds to all queries with the
    AP's IP address, triggering the captive portal popup.
    """

    AP_IP = "10.42.0.1"  # NetworkManager default hotspot IP
    DNS_PORT = 53

    def __init__(self, ap_ip: str | None = None):
        """Initialize Captive Portal DNS server.

        Args:
            ap_ip: IP address to redirect to. Uses default AP IP if not specified.
        """
        self._ap_ip = ap_ip or self.AP_IP
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        """Check if DNS server is running."""
        return self._running

    def start(self) -> bool:
        """Start the DNS server.

        Returns:
            True if started successfully, False otherwise.
        """
        if self._running:
            logger.warning("DNS server already running")
            return True

        # Only check for port conflicts if using privileged port 53
        import subprocess
        if self.DNS_PORT == 53:
            # Check and stop dnsmasq if running (NetworkManager may have started it)
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", "dnsmasq"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:  # dnsmasq is active
                    logger.info("Stopping dnsmasq to avoid port 53 conflict")
                    subprocess.run(["systemctl", "stop", "dnsmasq"], timeout=10)
            except Exception as e:
                logger.debug(f"Could not check/stop dnsmasq: {e}")

            # Check if something else is using port 53
            try:
                result = subprocess.run(
                    ["ss", "-ulnp", "sport", "=", ":53"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.stdout.strip() and "python" not in result.stdout:
                    logger.warning(f"Port 53 in use by another process:\n{result.stdout}")
            except Exception as e:
                logger.debug(f"Could not check port 53 usage: {e}")

        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # For non-privileged ports (5353), bind to 0.0.0.0
            # For port 53, try AP IP first then fallback
            if self.DNS_PORT != 53:
                self._socket.bind(("0.0.0.0", self.DNS_PORT))
                logger.info(f"DNS server bound to 0.0.0.0:{self.DNS_PORT}")
            else:
                bind_ip = self._ap_ip
                try:
                    self._socket.bind((bind_ip, self.DNS_PORT))
                    logger.info(f"DNS server bound to {bind_ip}:{self.DNS_PORT}")
                except OSError as bind_err:
                    logger.warning(f"Could not bind to {bind_ip}: {bind_err}, trying 0.0.0.0")
                    self._socket.bind(("0.0.0.0", self.DNS_PORT))
                    logger.info(f"DNS server bound to 0.0.0.0:{self.DNS_PORT}")

            self._socket.settimeout(1.0)  # Allow periodic check for stop signal

            self._running = True
            self._thread = threading.Thread(target=self._serve, daemon=True)
            self._thread.start()

            # Log socket info for debugging
            sock_name = self._socket.getsockname()
            logger.info(f"Captive Portal DNS started on {sock_name}, redirecting to {self._ap_ip}")
            logger.info(f"Socket fileno: {self._socket.fileno()}, blocking: {self._socket.getblocking()}")
            return True

        except PermissionError:
            logger.error("Permission denied: DNS server requires root privileges (port 53)")
            return False
        except OSError as e:
            logger.error(f"Failed to start DNS server: {e}")
            return False

    def stop(self) -> None:
        """Stop the DNS server."""
        if not self._running:
            return

        self._running = False

        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

        logger.info("Captive Portal DNS stopped")

    def _extract_query_info(self, query: bytes) -> tuple[str, str]:
        """Extract domain name and query type from DNS query for logging."""
        try:
            if len(query) < 12:
                return "?", "?"
            # Domain starts at byte 12
            pos = 12
            labels = []
            while pos < len(query) and query[pos] != 0:
                label_len = query[pos]
                if label_len > 63:  # Compression pointer or invalid
                    break
                pos += 1
                labels.append(query[pos:pos + label_len].decode('ascii', errors='replace'))
                pos += label_len
            domain = ".".join(labels) if labels else "?"

            # Get query type
            pos += 1  # Skip null terminator
            if pos + 2 <= len(query):
                qtype = struct.unpack("!H", query[pos:pos + 2])[0]
                type_names = {1: "A", 28: "AAAA", 5: "CNAME", 15: "MX", 16: "TXT", 2: "NS", 6: "SOA", 12: "PTR", 255: "ANY"}
                qtype_str = type_names.get(qtype, str(qtype))
            else:
                qtype_str = "?"

            return domain, qtype_str
        except Exception:
            return "?", "?"

    def _serve(self) -> None:
        """Main DNS server loop."""
        logger.info("DNS server thread started, waiting for queries...")
        while self._running and self._socket:
            try:
                data, addr = self._socket.recvfrom(512)
                domain, qtype = self._extract_query_info(data)
                logger.info(f"DNS query: {domain} [{qtype}] (from {addr[0]})")
                response = self._build_response(data)
                if response:
                    self._socket.sendto(response, addr)
                    logger.debug(f"DNS response sent to {addr[0]}")
                else:
                    logger.warning(f"DNS: Failed to respond to {domain} from {addr[0]}")
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.warning(f"DNS server error: {e}")

    def _build_response(self, query: bytes) -> Optional[bytes]:
        """Build DNS response redirecting to AP IP.

        Args:
            query: Raw DNS query packet

        Returns:
            DNS response packet or None if invalid query
        """
        if len(query) < 12:
            return None

        try:
            # Parse DNS header
            transaction_id = query[:2]
            flags = query[2:4]

            # Check if it's a standard query (QR=0, OPCODE=0)
            flag_value = struct.unpack("!H", flags)[0]
            if (flag_value >> 15) != 0:  # QR bit should be 0 for query
                return None

            # Find the question section (skip header)
            question_start = 12
            question_end = question_start

            # Parse domain name (series of labels ending with 0)
            while question_end < len(query) and query[question_end] != 0:
                label_len = query[question_end]
                question_end += label_len + 1
            question_end += 1  # Skip the null terminator

            # Get QTYPE (2 bytes after domain)
            if question_end + 4 > len(query):
                return None
            qtype = struct.unpack("!H", query[question_end:question_end + 2])[0]

            # Add QTYPE (2 bytes) and QCLASS (2 bytes)
            question_end += 4
            question = query[question_start:question_end]

            # Only respond to A record queries (type 1)
            # For AAAA (type 28) and others, return empty response
            if qtype != 1:
                # Return response with no answers for non-A queries
                response_flags = struct.pack("!H", 0x8580)  # QR=1, AA=1, RA=1
                counts = struct.pack("!HHHH", 1, 0, 0, 0)  # QDCOUNT=1, ANCOUNT=0
                return transaction_id + response_flags + counts + question

            # Build response header for A record
            # QR=1 (response), AA=1 (authoritative), RA=1 (recursion available)
            response_flags = struct.pack("!H", 0x8580)

            # QDCOUNT=1, ANCOUNT=1, NSCOUNT=0, ARCOUNT=0
            counts = struct.pack("!HHHH", 1, 1, 0, 0)

            # Build answer section
            # Name pointer to question (0xC00C points to offset 12)
            answer_name = struct.pack("!H", 0xC00C)
            # TYPE=A (1), CLASS=IN (1)
            answer_type_class = struct.pack("!HH", 1, 1)
            # TTL=60 seconds (short TTL for captive portal)
            answer_ttl = struct.pack("!I", 60)
            # RDLENGTH=4 (IPv4 address)
            answer_rdlength = struct.pack("!H", 4)
            # RDATA=IP address
            ip_parts = [int(p) for p in self._ap_ip.split(".")]
            answer_rdata = struct.pack("!BBBB", *ip_parts)

            answer = answer_name + answer_type_class + answer_ttl + answer_rdlength + answer_rdata

            # Combine response
            response = transaction_id + response_flags + counts + question + answer

            return response

        except Exception as e:
            logger.debug(f"Failed to build DNS response: {e}")
            return None


# Captive portal detection URLs that devices check
CAPTIVE_PORTAL_URLS = {
    # Android
    "/generate_204": 204,
    "/gen_204": 204,
    "/connectivitycheck.gstatic.com": 204,
    # iOS/macOS
    "/hotspot-detect.html": 200,
    "/library/test/success.html": 200,
    # Windows
    "/ncsi.txt": 200,
    "/connecttest.txt": 200,
    # Firefox
    "/success.txt": 200,
}


def get_captive_portal_response(path: str) -> tuple[int, str]:
    """Get appropriate response for captive portal detection.

    Args:
        path: Request path

    Returns:
        Tuple of (status_code, body)
    """
    # Check exact path matches
    if path in CAPTIVE_PORTAL_URLS:
        status = CAPTIVE_PORTAL_URLS[path]
        if status == 204:
            return (302, "")  # Redirect to trigger portal
        return (302, "")  # Redirect to trigger portal

    # Check partial matches
    for url_pattern in CAPTIVE_PORTAL_URLS:
        if url_pattern in path:
            return (302, "")  # Redirect to trigger portal

    return (200, "")


# Global instance
_captive_dns: Optional[CaptivePortalDNS] = None


def get_captive_dns() -> CaptivePortalDNS:
    """Get global Captive Portal DNS instance."""
    global _captive_dns
    if _captive_dns is None:
        _captive_dns = CaptivePortalDNS()
    return _captive_dns
