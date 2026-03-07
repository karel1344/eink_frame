"""E-Ink 상태 화면 표시 유틸리티.

config의 display.model에 따라 올바른 default 이미지를 선택하고
e-ink 디스플레이에 표시한다.

사용처:
  - state_machine._restore_last_photo(): AP/WEB_UI 종료 시 직전 사진 복원
  - frame_runner.run_once(): 표시할 사진이 없을 때 default 화면
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
_ASSETS_DIR   = _PROJECT_ROOT / "assets"


# ---------------------------------------------------------------------------
# Default image selection
# ---------------------------------------------------------------------------

def get_default_image_path(model: Optional[str] = None, rotation: Optional[int] = None) -> Path:
    """config의 display.model + display.rotation에 맞는 default 이미지 경로를 반환.

    파일 명명 규칙: default_{model}_{landscape|portrait}.png
      e.g. default_7in3e_landscape.png, default_13in3e_portrait.png

    선택 로직:
      - 7in3e  native = landscape (800×480)
      - 13in3e native = portrait  (1200×1600)
      - rotation 90/270 → 가로·세로 반전
    """
    try:
        from config import get_config
        cfg = get_config()
        if model is None:
            model = cfg.display_model
        if rotation is None:
            rotation = int(cfg.get("display.rotation", 0))
    except Exception:
        model = model or "7in3e"
        rotation = rotation or 0

    # 각 모델의 native 해상도 (w, h)
    _NATIVE: dict[str, tuple[int, int]] = {
        "7in3e":  (800,  480),
        "13in3e": (1200, 1600),
    }
    nw, nh = _NATIVE.get(model, (800, 480))

    # rotation 90/270이면 가로·세로 반전
    if rotation in (90, 270):
        eff_w, eff_h = nh, nw
    else:
        eff_w, eff_h = nw, nh

    orient = "landscape" if eff_w >= eff_h else "portrait"

    for name in [
        f"default_{model}_{orient}.png",
        f"default_{model}.png",
        "default.png",
    ]:
        p = _ASSETS_DIR / name
        if p.exists():
            return p

    return _ASSETS_DIR / "default.png"


# ---------------------------------------------------------------------------
# Show helpers
# ---------------------------------------------------------------------------

def show_default_image(dry_run: bool = False, model: Optional[str] = None,
                       rotation: Optional[int] = None) -> bool:
    """config에 맞는 default 이미지를 e-ink 디스플레이에 표시.

    Args:
        dry_run: True면 하드웨어 접근 없이 debug_default.png로 저장.
        model: 디스플레이 모델 오버라이드.
        rotation: 회전값 오버라이드 (0/90/180/270).

    Returns:
        표시 성공 여부.
    """
    try:
        from config import get_config
        from display import get_display
        from image_processor import ImageProcessor

        config = get_config()
        if model is None:
            model = config.display_model
        if rotation is None:
            rotation = int(config.get("display.rotation", 0))

        image_path = get_default_image_path(model, rotation)
        if not image_path.exists():
            logger.warning("Default image not found: %s", image_path)
            return False

        processor = ImageProcessor.from_config(assets_dir=_ASSETS_DIR)
        image = processor.process(image_path)

        simulate_display = config.get("display.simulate", dry_run)
        if simulate_display:
            out = _PROJECT_ROOT / "debug_default.png"
            image.save(out)
            logger.info("Display simulated: default image saved → %s", out)
            return True

        display = get_display(model)
        display.init()
        display.show(image)
        display.sleep()
        logger.info("Default image shown on %s display", model)
        return True

    except Exception:
        logger.exception("Failed to show default image")
        return False


def restore_last_photo(dry_run: bool = False) -> bool:
    """DB의 마지막 표시 사진을 복원. 없으면 default 이미지 표시.

    Args:
        dry_run: True면 하드웨어 접근 없이 debug_restore.png로 저장.

    Returns:
        표시 성공 여부.
    """
    try:
        from config import get_config
        from database import get_db
        from display import get_display
        from image_processor import ImageProcessor

        config = get_config()
        model = config.display_model
        db = get_db()
        photo_id = db.last_displayed_photo_id

        if photo_id is None:
            logger.info("No last photo — showing default image")
            return show_default_image(dry_run=dry_run, model=model)

        # photo_id로 파일 경로 조회
        photo = db.get_photo(photo_id)
        if photo is None or not Path(photo["file_path"]).exists():
            logger.warning("Last photo file not found (id=%s) — falling back to default", photo_id)
            return show_default_image(dry_run=dry_run, model=model)

        processor = ImageProcessor.from_config(assets_dir=_ASSETS_DIR)
        try:
            from power_manager import get_power_manager
            voltage = get_power_manager().read_input_voltage()
        except Exception:
            voltage = None

        image = processor.process(photo["file_path"], battery_voltage=voltage)

        simulate_display = config.get("display.simulate", dry_run)
        if simulate_display:
            out = _PROJECT_ROOT / "debug_restore.png"
            image.save(out)
            logger.info("Display simulated: restored photo saved → %s (id=%s)", out, photo_id)
            return True

        display = get_display(model)
        display.init()
        display.show(image)
        display.sleep()
        logger.info("Restored last photo id=%s on %s display", photo_id, model)
        return True

    except Exception:
        logger.exception("Failed to restore last photo")
        return False
