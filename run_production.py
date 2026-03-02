#!/usr/bin/env python3
"""Production server runner with WiFi fallback to AP mode.

Usage:
    sudo python run_production.py

This script:
1. Tries to connect to saved WiFi
2. If fails after 3 attempts → starts AP mode
3. Runs web server (port 80 for AP mode, port 8000 otherwise)
"""

import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Run production startup sequence."""
    import uvicorn
    from src.startup import run_startup
    from src.web.app import app

    logger.info("=" * 50)
    logger.info("E-Ink Photo Frame - Production Mode")
    logger.info("=" * 50)

    # Run startup sequence (WiFi → AP mode fallback)
    state = run_startup()
    logger.info(f"Startup complete, state: {state}")

    # Determine port based on state
    # AP mode needs port 80 for captive portal
    if state == "ap_mode":
        port = 80
        logger.info("Running in AP mode - Captive Portal on port 80")
    else:
        port = 8000
        logger.info(f"Running in {state} mode on port 8000")

    # Run web server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
