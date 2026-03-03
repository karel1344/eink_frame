#!/usr/bin/env python3
"""E-Ink Photo Frame runner.

Usage:
    python run_production.py         # Pi - WiFi 연결 시도 → AP 모드 폴백 → 웹서버
    python run_production.py --dev   # Mac - 웹서버만 실행 (WiFi/AP 없음, 포트 8000, reload)
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def run_dev():
    """Mac 개발 모드: 웹서버만 실행, auto-reload 활성화."""
    import uvicorn

    logger.info("Starting in DEV mode (no WiFi/AP startup, port 8000)")
    uvicorn.run(
        "src.web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


def run_production():
    """Pi 프로덕션 모드: WiFi 연결 → 실패 시 AP 모드 → 웹서버."""
    import uvicorn
    from src.startup import run_startup
    from src.web.app import app

    logger.info("=" * 50)
    logger.info("E-Ink Photo Frame - Production Mode")
    logger.info("=" * 50)

    state = run_startup()
    logger.info(f"Startup complete, state: {state}")

    port = 80 if state == "ap_mode" else 8000
    logger.info(f"Starting web server on port {port}")

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    if "--dev" in sys.argv:
        run_dev()
    else:
        run_production()
