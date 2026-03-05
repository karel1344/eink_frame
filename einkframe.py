#!/usr/bin/env python3
"""E-Ink Photo Frame runner.

Usage:
    python einkframe.py              # Pi - WiFi 연결 시도 → AP 모드 폴백 → 웹서버
    python einkframe.py --dev        # Mac - 웹서버만 실행 (WiFi/AP 없음, 포트 8000, reload)
    python einkframe.py --frame      # Pi - 사진 표시 한 번 실행 후 종료
    python einkframe.py --frame --dry-run  # Mac - 사진 처리 결과를 debug_output.png로 저장
"""

import logging
import os
import sys

_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))  # bare imports in src/ modules

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


def run_frame(dry_run: bool = False):
    """사진 표시 모드: 사진 선택 → 처리 → 표시 → 종료."""
    from src.frame_runner import run_once

    logger.info("=" * 50)
    logger.info("E-Ink Photo Frame - Frame Mode%s", " (dry-run)" if dry_run else "")
    logger.info("=" * 50)

    success = run_once(dry_run=dry_run)
    sys.exit(0 if success else 1)


def run_production(dry_run: bool = False):
    """Pi 프로덕션 모드: 상태머신이 전체 라이프사이클 관리."""
    from src.state_machine import create_state_machine

    logger.info("=" * 50)
    logger.info("E-Ink Photo Frame - Production Mode%s", " (dry-run)" if dry_run else "")
    logger.info("=" * 50)

    sm = create_state_machine(dry_run=dry_run)
    try:
        sm.run()  # Blocks until SHUTDOWN or ERROR
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        sm.stop()
    sys.exit(0)


if __name__ == "__main__":
    if "--frame" in sys.argv:
        run_frame(dry_run="--dry-run" in sys.argv)
    elif "--dev" in sys.argv:
        run_dev()
    else:
        run_production(dry_run="--dry-run" in sys.argv)
