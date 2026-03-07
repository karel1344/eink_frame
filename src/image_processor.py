"""Image processor for E-Ink display.

Converts arbitrary photos into display-ready PIL Images:
  1. Load (JPEG / PNG / HEIC)
  2. EXIF auto-rotation
  3. Resize to display canvas (fit or fill)
  4. Battery status overlay (top-right corner)
  5. Physical display rotation compensation

Usage::

    from image_processor import ImageProcessor
    from display import get_display

    display = get_display("7in3e")
    processor = ImageProcessor.from_config()

    image = processor.process("photos/local/photo.jpg", battery_voltage=3.7)
    display.init()
    display.show(image)
    display.sleep()
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ExifTags

logger = logging.getLogger(__name__)


class ImageProcessor:
    """Converts source photos into display-ready PIL Images.

    Args:
        display_width:  Native display width  (e.g. 800 for 7in3e).
        display_height: Native display height (e.g. 480 for 7in3e).
        rotation:       Physical display rotation in degrees (0/90/180/270).
                        90/270 swap the canvas dimensions so portrait content
                        fills the frame correctly.
        fill_mode:      "fit"  – letterbox (white bars, full image visible).
                        "fill" – crop-fill (no bars, image may be cropped).
        auto_rotate:    Apply EXIF orientation tag before resizing.
        show_battery:   Overlay a battery icon when battery_voltage is given.
        assets_dir:     Directory containing assets/icons/battery_*.png files.
                        If None or icons are missing, a drawn fallback is used.
    """

    def __init__(
        self,
        display_width: int,
        display_height: int,
        *,
        rotation: int = 0,
        fill_mode: str = "fit",
        auto_rotate: bool = True,
        show_battery: bool = True,
        assets_dir: Path | None = None,
        brightness: float = 1.0,
        gamma: float = 1.0,
        contrast: float = 1.0,
        saturation: float = 1.0,
        sharpness: float = 1.0,
        warmth: float = 1.0,
    ) -> None:
        if rotation not in (0, 90, 180, 270):
            raise ValueError(f"rotation must be 0/90/180/270, got {rotation}")
        if fill_mode not in ("fit", "fill"):
            raise ValueError(f"fill_mode must be 'fit' or 'fill', got {fill_mode!r}")

        self._native_w = display_width
        self._native_h = display_height
        self._rotation = rotation
        self._fill_mode = fill_mode
        self._auto_rotate = auto_rotate
        self._show_battery = show_battery
        self._assets_dir = assets_dir
        self._brightness = brightness
        self._gamma = gamma
        self._contrast = contrast
        self._saturation = saturation
        self._sharpness = sharpness
        self._warmth = warmth

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, assets_dir: Path | None = None) -> "ImageProcessor":
        """Build an ImageProcessor from the global project config."""
        from config import get_config
        from display import get_display

        cfg = get_config()
        display = get_display(cfg.display_model)

        # Resolve assets dir (project_root/assets)
        if assets_dir is None:
            assets_dir = Path(__file__).parent.parent / "assets"

        return cls(
            display_width=display.width,
            display_height=display.height,
            rotation=cfg.display_rotation,
            fill_mode=cfg.image_fill_mode,
            auto_rotate=cfg.image_auto_rotate,
            show_battery=cfg.battery_show_indicator,
            assets_dir=assets_dir,
            brightness=float(cfg.get("image_processing.brightness", 1.0)),
            gamma=float(cfg.get("image_processing.gamma", 1.0)),
            contrast=float(cfg.get("image_processing.contrast", 1.0)),
            saturation=float(cfg.get("image_processing.saturation", 1.0)),
            sharpness=float(cfg.get("image_processing.sharpness", 1.0)),
            warmth=float(cfg.get("image_processing.warmth", 1.0)),
        )

    @property
    def canvas_size(self) -> tuple[int, int]:
        """(width, height) of the content canvas after rotation."""
        if self._rotation in (90, 270):
            return self._native_h, self._native_w
        return self._native_w, self._native_h

    def process(
        self,
        source: Path | str | Image.Image,
        *,
        battery_voltage: float | None = None,
    ) -> Image.Image:
        """Process a photo into a display-ready PIL Image.

        Args:
            source:          File path or already-opened PIL Image.
            battery_voltage: If given (and show_battery is True), overlays a
                             battery status icon.  Units: Volts.

        Returns:
            RGB PIL Image at native display resolution, ready for
            EinkDisplay.show().
        """
        # 1. Load
        img = _load(source)

        # 2. EXIF rotation
        if self._auto_rotate:
            img = _apply_exif_rotation(img)

        # 3. Resize to canvas
        cw, ch = self.canvas_size
        if self._fill_mode == "fill":
            img = _resize_fill(img, cw, ch)
        else:
            img = _resize_fit(img, cw, ch)

        # 4. Ensure RGB
        img = img.convert("RGB")

        # 5. Enhancement — e-ink 색 재현 한계 보완 (양자화 전에 적용)
        if self._brightness != 1.0:
            img = ImageEnhance.Brightness(img).enhance(self._brightness)
        if self._gamma != 1.0:
            img = _apply_gamma(img, self._gamma)
        if self._contrast != 1.0:
            img = ImageEnhance.Contrast(img).enhance(self._contrast)
        if self._saturation != 1.0:
            img = ImageEnhance.Color(img).enhance(self._saturation)
        if self._sharpness != 1.0:
            img = ImageEnhance.Sharpness(img).enhance(self._sharpness)
        if self._warmth != 1.0:
            img = _apply_warmth(img, self._warmth)

        # 6. Battery overlay
        if self._show_battery and battery_voltage is not None:
            img = _draw_battery(img, battery_voltage, self._assets_dir)

        # 7. Compensate for physical display rotation
        #    rotate() with expand=True keeps the full image and adjusts size
        if self._rotation == 90:
            img = img.rotate(-90, expand=True)   # CCW 90 → correct for CW-mounted display
        elif self._rotation == 180:
            img = img.rotate(180, expand=True)
        elif self._rotation == 270:
            img = img.rotate(90, expand=True)    # CW 90 → correct for CCW-mounted display

        logger.debug(
            "Processed image → %dx%d (rotation=%d, fill=%s)",
            img.width, img.height, self._rotation, self._fill_mode,
        )
        return img


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load(source: Path | str | Image.Image) -> Image.Image:
    if isinstance(source, Image.Image):
        return source.copy()
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass
    return Image.open(Path(source))


def _apply_gamma(img: Image.Image, gamma: float) -> Image.Image:
    """Gamma correction: >1.0 = brighter midtones, <1.0 = darker midtones."""
    lut = [int((i / 255) ** (1.0 / gamma) * 255 + 0.5) for i in range(256)]
    return img.point(lut * 3)


def _apply_warmth(img: Image.Image, warmth: float) -> Image.Image:
    """Color temperature: >1.0 = warmer (more red), <1.0 = cooler (more blue)."""
    r, g, b = img.split()
    r = r.point([min(255, int(i * warmth)) for i in range(256)])
    b = b.point([min(255, int(i / warmth)) for i in range(256)])
    return Image.merge("RGB", (r, g, b))


def _apply_exif_rotation(img: Image.Image) -> Image.Image:
    """Rotate image according to EXIF Orientation tag."""
    try:
        tag_map = {v: k for k, v in ExifTags.TAGS.items()}
        exif = img._getexif()  # type: ignore[attr-defined]
        if not exif:
            return img
        orientation = exif.get(tag_map.get("Orientation", 0))
        rotations = {3: 180, 6: 270, 8: 90}
        if orientation in rotations:
            return img.rotate(rotations[orientation], expand=True)
    except Exception:
        pass
    return img


def _resize_fit(img: Image.Image, width: int, height: int) -> Image.Image:
    """Letterbox: fit entire image inside canvas, pad with white."""
    img = img.convert("RGB")
    img.thumbnail((width, height), Image.LANCZOS)
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    x = (width - img.width) // 2
    y = (height - img.height) // 2
    canvas.paste(img, (x, y))
    return canvas


def _resize_fill(img: Image.Image, width: int, height: int) -> Image.Image:
    """Crop-fill: scale and center-crop to exactly fill canvas."""
    src_ratio = img.width / img.height
    dst_ratio = width / height
    if src_ratio > dst_ratio:
        # Source wider → match height, crop sides
        new_h = height
        new_w = int(img.width * height / img.height)
    else:
        # Source taller → match width, crop top/bottom
        new_w = width
        new_h = int(img.height * width / img.width)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    return img.crop((left, top, left + width, top + height))


# ---------------------------------------------------------------------------
# Battery overlay
# ---------------------------------------------------------------------------

_BATTERY_THRESHOLDS = {
    "ok":       3.3,   # voltage >= 3.3 V
    "low":      3.0,   # 3.0 <= voltage < 3.3 V
    "critical": 0.0,   # voltage < 3.0 V
}


def _battery_state(voltage: float) -> str:
    if voltage >= _BATTERY_THRESHOLDS["ok"]:
        return "ok"
    if voltage >= _BATTERY_THRESHOLDS["low"]:
        return "low"
    return "critical"


def _draw_battery(
    img: Image.Image,
    voltage: float,
    assets_dir: Path | None,
) -> Image.Image:
    state = _battery_state(voltage)

    # 배터리가 충분하면 아이콘 표시 안 함
    if state == "ok":
        return img

    # Try PNG icon from assets/icons/battery_<state>.png
    if assets_dir:
        icon_path = assets_dir / "icons" / f"battery_{state}.png"
        if icon_path.exists():
            icon = Image.open(icon_path).convert("RGBA")
            out = img.copy().convert("RGBA")
            x = img.width - icon.width - 8
            y = 8
            out.paste(icon, (x, y), icon)
            out = out.convert("RGB")
            if state == "critical":
                _draw_charge_label(out, x, y + icon.height, icon.width)
            return out

    # Fallback: draw battery icon with Pillow
    out = _draw_battery_fallback(img, state)
    if state == "critical":
        margin = 8
        bw, nub_w = 36, 4
        icon_x = img.width - bw - nub_w - margin
        icon_bottom = margin + 16
        _draw_charge_label(out, icon_x, icon_bottom, bw + nub_w)
    return out


def _pick_contrast_color(img: Image.Image, region: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """Pick black or white text color based on average brightness of the region."""
    # Clamp region to image bounds
    x1 = max(0, region[0])
    y1 = max(0, region[1])
    x2 = min(img.width, region[2])
    y2 = min(img.height, region[3])
    if x2 <= x1 or y2 <= y1:
        return (0, 0, 0)
    crop = img.crop((x1, y1, x2, y2)).convert("L")
    avg = sum(crop.getdata()) / max(1, crop.width * crop.height)
    return (0, 0, 0) if avg > 128 else (255, 255, 255)


def _draw_charge_label(
    img: Image.Image,
    icon_x: int,
    icon_bottom: int,
    icon_width: int,
) -> None:
    """Draw '충전 필요' text below the battery icon with contrast-aware color."""
    draw = ImageDraw.Draw(img)
    text = "충전 필요"
    font_size = 12
    font = _load_korean_font(font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = icon_x + (icon_width - tw) // 2
    ty = icon_bottom + 2
    # Determine text color from background region
    color = _pick_contrast_color(img, (tx - 2, ty - 2, tx + tw + 2, ty + th + 2))
    draw.text((tx, ty), text, fill=color, font=font)


def _load_korean_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try to load a Korean-capable font; fall back to default."""
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _draw_battery_fallback(img: Image.Image, state: str) -> Image.Image:
    """Draw a simple 40×20px battery icon at top-right corner."""
    COLOR = {"ok": (30, 180, 30), "low": (220, 140, 0), "critical": (210, 30, 30)}
    BARS  = {"ok": 3, "low": 1, "critical": 0}

    fill_color = COLOR[state]
    bars = BARS[state]

    out = img.copy()
    draw = ImageDraw.Draw(out)

    margin = 8
    bw, bh = 36, 16          # body width/height
    nub_w, nub_h = 4, 8      # terminal nub
    x = img.width - bw - nub_w - margin
    y = margin

    # Body outline
    draw.rectangle([x, y, x + bw, y + bh], outline=(40, 40, 40), width=2)
    # Terminal nub
    ny = y + (bh - nub_h) // 2
    draw.rectangle([x + bw, ny, x + bw + nub_w, ny + nub_h], fill=(40, 40, 40))

    # Fill segments (3 segments max)
    seg_w = (bw - 8) // 3
    for i in range(bars):
        sx = x + 4 + i * (seg_w + 1)
        draw.rectangle([sx, y + 3, sx + seg_w, y + bh - 3], fill=fill_color)

    # Critical: red X through body
    if state == "critical":
        draw.line([x + 5, y + 3, x + bw - 5, y + bh - 3], fill=(210, 30, 30), width=2)
        draw.line([x + bw - 5, y + 3, x + 5, y + bh - 3], fill=(210, 30, 30), width=2)

    return out
