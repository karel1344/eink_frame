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


def _generate_ap_screen(ssid: str, ip: str, password: str, width: int, height: int) -> "Image.Image":
    """AP 모드 안내용 E-Ink 이미지 생성 (RGB, width×height).

    레이아웃:
      - 가로 (landscape): 좌측 QR 코드 / 우측 텍스트
      - 세로 (portrait) : 상단 텍스트 / 하단 QR 코드
    """
    from PIL import Image, ImageDraw, ImageFont

    url = f"http://{ip}"
    img  = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    _FONT_PATHS = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ]

    def load_font(size: int):
        for path in _FONT_PATHS:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    is_landscape = width >= height
    pad = max(20, min(width, height) // 18)

    if is_landscape:
        qr_size = min(height - 2 * pad, (width - 3 * pad) // 2)
        qr_x    = pad
        qr_y    = (height - qr_size) // 2
        text_x  = 2 * pad + qr_size
        text_w  = width - text_x - pad
        title_sz = max(24, height // 12)
        ssid_sz  = max(20, height // 14)
        label_sz = max(14, height // 22)
        url_sz   = max(16, height // 16)
    else:
        qr_size = min(width - 4 * pad, height // 3)
        qr_x    = (width - qr_size) // 2
        qr_y    = height - qr_size - 2 * pad
        text_x  = pad
        text_w  = width - 2 * pad
        title_sz = max(36, width // 16)
        ssid_sz  = max(30, width // 18)
        label_sz = max(22, width // 26)
        url_sz   = max(26, width // 22)

    # QR 코드 생성
    try:
        import qrcode as _qr_lib
        qr = _qr_lib.QRCode(
            error_correction=_qr_lib.constants.ERROR_CORRECT_M,
            box_size=max(2, qr_size // 30),
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        qr_pil = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qr_pil = qr_pil.resize((qr_size, qr_size), Image.NEAREST)
        img.paste(qr_pil, (qr_x, qr_y))
        draw.rectangle(
            [qr_x - 2, qr_y - 2, qr_x + qr_size + 1, qr_y + qr_size + 1],
            outline=(0, 0, 0), width=2,
        )
    except ImportError:
        logger.warning("qrcode 모듈 없음 — QR 코드 생략")
        draw.rectangle(
            [qr_x, qr_y, qr_x + qr_size, qr_y + qr_size],
            outline=(0, 0, 0), width=2,
        )

    # 텍스트 렌더링
    fnt_title = load_font(title_sz)
    fnt_ssid  = load_font(ssid_sz)
    fnt_lbl   = load_font(label_sz)
    fnt_url   = load_font(url_sz)

    BLUE  = (12, 84, 172)   # E-Ink 캘리브레이션 파란색
    GRAY  = (80, 80, 80)
    BLACK = (0, 0, 0)

    def put(y: int, text: str, font, fill) -> int:
        """텍스트를 (text_x, y)에 그리고, 텍스트 하단 y 좌표 반환."""
        draw.text((text_x, y), text, font=font, fill=fill)
        bb = draw.textbbox((text_x, y), text, font=font)
        return bb[3]

    y = pad
    y = put(y, "Wi-Fi Setup", fnt_title, BLACK) + pad // 2
    draw.line([(text_x, y), (text_x + text_w, y)], fill=BLACK, width=2)
    y += pad

    y = put(y, "SSID", fnt_lbl, GRAY) + 6
    y = put(y, ssid, fnt_ssid, BLACK) + pad

    if password:
        y = put(y, "Password", fnt_lbl, GRAY) + 6
        y = put(y, password, fnt_ssid, BLACK) + pad

    y = put(y, "Web UI", fnt_lbl, GRAY) + 6
    put(y, url, fnt_url, BLUE)

    return img


def show_ap_mode_screen(
    ssid: str,
    ip: str = "10.42.0.1",
    password: str = "",
    dry_run: bool = False,
) -> bool:
    """AP 모드 진입 시 E-Ink 화면에 SSID·URL·QR 코드 표시.

    Args:
        ssid:     AP Wi-Fi SSID (예: EinkFrame-A1B2).
        ip:       AP IP 주소 (기본 10.42.0.1).
        password: AP 비밀번호. 빈 문자열이면 오픈 네트워크.
        dry_run:  True면 하드웨어 없이 debug_ap_screen.png로 저장.

    Returns:
        표시 성공 여부.
    """
    try:
        from config import get_config
        from display import get_display

        config = get_config()
        model  = config.display_model
        simulate_display = config.get("display.simulate", dry_run)

        display = get_display(model)
        image   = _generate_ap_screen(ssid, ip, password, display.width, display.height)

        if simulate_display:
            out = _PROJECT_ROOT / "debug_ap_screen.png"
            image.save(out)
            logger.info("AP 화면 시뮬레이션 → %s", out)
            return True

        display.init()
        display.show(image)
        display.sleep()
        logger.info("AP 화면 표시 완료 — SSID=%s URL=http://%s", ssid, ip)
        return True

    except Exception:
        logger.exception("AP 화면 표시 실패")
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
