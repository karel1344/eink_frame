"""E-Ink Photo Frame main entry point."""

from __future__ import annotations

import logging
import sys
import uvicorn

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def run_production():
    """Run the full startup sequence for production (Pi).

    1. Check WiFi connection
    2. If fails → Start AP mode
    3. Run web server
    """
    from .startup import run_startup
    from .web.app import create_app

    # Run startup sequence
    state = run_startup()
    logger.info(f"Startup complete, state: {state}")

    # Start web server
    app = create_app()

    # Use port 80 for AP mode (captive portal), 8000 otherwise
    port = 80 if state == "ap_mode" else 8000

    logger.info(f"Starting web server on port {port}")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )


def run_dev():
    """Run the web server for development (no startup sequence)."""
    from .web.app import create_app

    app = create_app()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


def main():
    """Main entry point."""
    # Check for --production flag
    if "--production" in sys.argv or "-p" in sys.argv:
        run_production()
    else:
        run_dev()


if __name__ == "__main__":
    main()
