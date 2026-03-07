#!/usr/bin/env python3
"""E-Ink display preview tool (Mac).

Simulates how an image will look on the Waveshare 7.3" 6-color E-Ink display,
including Floyd-Steinberg dithering and the hybrid color palette used by the driver.

Usage:
    python scripts/preview_eink.py photo.jpg
    python scripts/preview_eink.py photo.jpg --contrast 1.5 --saturation 2.0
    python scripts/preview_eink.py photo.jpg --brightness 1.2 --gamma 0.8
    python scripts/preview_eink.py photo.jpg --warmth 1.5   # 따뜻하게
    python scripts/preview_eink.py photo.jpg --dither none   # 포스터 느낌
    python scripts/preview_eink.py photo.jpg --no-enhance    # 보정 없이
    python scripts/preview_eink.py photo.jpg --fill          # crop-fill 모드
    python scripts/preview_eink.py photo.jpg --compare --output preview.png
    python scripts/preview_eink.py photo.jpg --output out.png   # 저장만

Dependencies: pip install Pillow
Optional:     pip install pillow-heif   (for HEIC support)
"""

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFont
except ImportError:
    print("ERROR: Pillow is required.  Run: pip install Pillow")
    sys.exit(1)

# ── Display spec ─────────────────────────────────────────────────────────────
DISPLAY_W = 800
DISPLAY_H = 480

# ── Hybrid palette (must match driver.py) ────────────────────────────────────
# Index order: 0=Black 1=White 2=Yellow 3=Red 4=unused(Black) 5=Blue 6=Green
PALETTE_RGB = [
    (  0,   0,   0),   # 0: Black  — ideal
    (255, 255, 255),   # 1: White  — ideal
    (207, 212,   4),   # 2: Yellow — calibrated
    (150,  28,  23),   # 3: Red    — calibrated
    (  0,   0,   0),   # 4: unused
    ( 12,  84, 172),   # 5: Blue   — calibrated
    ( 29,  90,  72),   # 6: Green  — calibrated
]

COLOR_NAMES = ["Black", "White", "Yellow", "Red", "(unused)", "Blue", "Green"]


def build_palette_image() -> Image.Image:
    pal_image = Image.new("P", (1, 1))
    flat = []
    for r, g, b in PALETTE_RGB:
        flat += [r, g, b]
    flat += [0, 0, 0] * (256 - len(PALETTE_RGB))
    pal_image.putpalette(flat)
    return pal_image


def load_image(path: str) -> Image.Image:
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass
    return Image.open(path)


def apply_exif_rotation(img: Image.Image) -> Image.Image:
    try:
        from PIL import ExifTags
        tag_map = {v: k for k, v in ExifTags.TAGS.items()}
        exif = img._getexif()
        if exif:
            orientation = exif.get(tag_map.get("Orientation", 0))
            rotations = {3: 180, 6: 270, 8: 90}
            if orientation in rotations:
                return img.rotate(rotations[orientation], expand=True)
    except Exception:
        pass
    return img


def resize_fit(img: Image.Image, w: int, h: int) -> Image.Image:
    img = img.convert("RGB")
    img.thumbnail((w, h), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    canvas.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
    return canvas


def resize_fill(img: Image.Image, w: int, h: int) -> Image.Image:
    src_r = img.width / img.height
    dst_r = w / h
    if src_r > dst_r:
        new_h, new_w = h, int(img.width * h / img.height)
    else:
        new_w, new_h = w, int(img.height * w / img.width)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return img.crop((left, top, left + w, top + h))


def apply_gamma(img: Image.Image, gamma: float) -> Image.Image:
    """Gamma correction via LUT: >1.0 = brighter midtones, <1.0 = darker midtones."""
    if gamma == 1.0:
        return img
    lut = [int((i / 255) ** (1.0 / gamma) * 255 + 0.5) for i in range(256)]
    return img.point(lut * 3)


def apply_warmth(img: Image.Image, warmth: float) -> Image.Image:
    """Color temperature shift. >1.0 = warmer (more R/Y), <1.0 = cooler (more B).
    Implemented as per-channel multiplier: R *= warmth, B /= warmth."""
    if warmth == 1.0:
        return img
    r, g, b = img.split()
    r_lut = [min(255, int(i * warmth))       for i in range(256)]
    b_lut = [min(255, int(i / warmth))       for i in range(256)]
    r = r.point(r_lut)
    b = b.point(b_lut)
    return Image.merge("RGB", (r, g, b))


def simulate_eink(
    img: Image.Image,
    contrast: float = 1.0,
    saturation: float = 1.0,
    sharpness: float = 1.0,
    brightness: float = 1.0,
    gamma: float = 1.0,
    warmth: float = 1.0,
    dither: str = "fs",
    fill_mode: bool = False,
    auto_rotate: bool = True,
) -> tuple[Image.Image, dict]:
    """Run the full E-Ink pipeline and return (simulated_image, stats)."""
    if auto_rotate:
        img = apply_exif_rotation(img)

    if fill_mode:
        img = resize_fill(img, DISPLAY_W, DISPLAY_H)
    else:
        img = resize_fit(img, DISPLAY_W, DISPLAY_H)

    img = img.convert("RGB")

    # Enhancement (order matters: brightness/gamma before contrast/saturation)
    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    if gamma != 1.0:
        img = apply_gamma(img, gamma)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if saturation != 1.0:
        img = ImageEnhance.Color(img).enhance(saturation)
    if sharpness != 1.0:
        img = ImageEnhance.Sharpness(img).enhance(sharpness)
    if warmth != 1.0:
        img = apply_warmth(img, warmth)

    pal_image = build_palette_image()
    dither_mode = Image.Dither.FLOYDSTEINBERG if dither == "fs" else Image.Dither.NONE
    quantized = img.quantize(palette=pal_image, dither=dither_mode)

    # Count color usage
    pixel_bytes = quantized.tobytes("raw")
    counts = [0] * len(PALETTE_RGB)
    total = len(pixel_bytes)
    for b in pixel_bytes:
        if b < len(counts):
            counts[b] += 1
    stats = {COLOR_NAMES[i]: f"{counts[i]/total*100:.1f}%" for i in range(len(PALETTE_RGB))}

    # Reconstruct RGB image using palette colors (= what display actually shows)
    simulated = quantized.convert("RGB")
    return simulated, stats


def make_compare(original: Image.Image, simulated: Image.Image, stats: dict, label: str = "") -> Image.Image:
    """Build a side-by-side comparison image."""
    LABEL_H = 32
    STAT_H  = 20
    PAD = 8
    w = DISPLAY_W * 2 + PAD * 3
    h = DISPLAY_H + LABEL_H + STAT_H + PAD * 3

    canvas = Image.new("RGB", (w, h), (30, 30, 30))
    draw = ImageDraw.Draw(canvas)

    try:
        font  = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
    except Exception:
        font = small = ImageFont.load_default()

    # Original
    orig_resized = original.copy().convert("RGB")
    orig_resized.thumbnail((DISPLAY_W, DISPLAY_H), Image.LANCZOS)
    ox = PAD + (DISPLAY_W - orig_resized.width) // 2
    oy = LABEL_H + PAD * 2 + (DISPLAY_H - orig_resized.height) // 2
    canvas.paste(orig_resized, (ox, oy))
    draw.text((PAD, PAD), "Original", fill=(200, 200, 200), font=font)

    # Simulated
    sx = DISPLAY_W + PAD * 2
    canvas.paste(simulated, (sx, LABEL_H + PAD * 2))
    sim_label = f"E-Ink Simulation  {label}" if label else "E-Ink Simulation"
    draw.text((sx, PAD), sim_label, fill=(200, 200, 200), font=font)

    # Color stats
    stat_y = LABEL_H + PAD * 2 + DISPLAY_H + 4
    x_cursor = sx
    stat_colors = {
        "Black": (60, 60, 60), "White": (230, 230, 230), "Yellow": (207, 212, 4),
        "Red": (150, 28, 23), "(unused)": None, "Blue": (12, 84, 172), "Green": (29, 90, 72),
    }
    for name, pct in stats.items():
        if name == "(unused)":
            continue
        color = stat_colors.get(name, (150, 150, 150))
        draw.rectangle([x_cursor, stat_y, x_cursor + 12, stat_y + 12], fill=color, outline=(100, 100, 100))
        draw.text((x_cursor + 15, stat_y - 1), f"{name} {pct}", fill=(180, 180, 180), font=small)
        x_cursor += 95

    return canvas


def main():
    parser = argparse.ArgumentParser(
        description="Preview E-Ink display output on Mac",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
파라미터 가이드 (모두 1.0 = 원본 그대로):
  --brightness  전체 밝기.  너무 어두운 사진은 1.2~1.5 시도
  --gamma       중간 톤만 조절.  >1.0 → 밝아짐, <1.0 → 어두워짐.
                하이라이트/쉐도우는 유지됨 (contrast보다 자연스러움)
  --contrast    명암 차이.  E-Ink는 1.1~1.4가 적당
  --saturation  채도.  색이 연한 사진은 1.5~2.5 시도
  --sharpness   선명도.  E-Ink는 1.2~1.8 권장. 너무 높으면 디더 노이즈 강조
  --warmth      색온도.  >1.0 → 따뜻(붉음), <1.0 → 차갑게(푸름)
  --dither      fs=Floyd-Steinberg(계조, 기본값), none=포스터/만화 느낌
""",
    )
    parser.add_argument("image", help="입력 이미지 경로 (JPEG/PNG/HEIC)")
    parser.add_argument("--contrast",   type=float, default=1.2, metavar="N")
    parser.add_argument("--saturation", type=float, default=1.5, metavar="N")
    parser.add_argument("--sharpness",  type=float, default=1.3, metavar="N")
    parser.add_argument("--brightness", type=float, default=1.0, metavar="N",
                        help="전체 밝기 (default: 1.0)")
    parser.add_argument("--gamma",      type=float, default=1.0, metavar="N",
                        help="감마 보정. >1.0=밝은 중간톤, <1.0=어두운 중간톤 (default: 1.0)")
    parser.add_argument("--warmth",     type=float, default=1.0, metavar="N",
                        help="색온도. >1.0=따뜻, <1.0=차갑게 (default: 1.0)")
    parser.add_argument("--dither",     choices=["fs", "none"], default="fs",
                        help="디더링 알고리즘: fs=Floyd-Steinberg(기본), none=포스터 느낌")
    parser.add_argument("--no-enhance", action="store_true",
                        help="모든 보정 끄기 (순수 디더링만)")
    parser.add_argument("--fill",       action="store_true",
                        help="crop-fill 모드 (기본: letterbox fit)")
    parser.add_argument("--compare",    action="store_true",
                        help="원본과 나란히 비교 이미지 생성")
    parser.add_argument("--output", "-o", metavar="PATH",
                        help="저장할 파일 경로 (미지정 시 preview 창 표시)")
    args = parser.parse_args()

    if not Path(args.image).exists():
        print(f"ERROR: 파일 없음: {args.image}")
        sys.exit(1)

    if args.no_enhance:
        contrast = saturation = sharpness = brightness = gamma = warmth = 1.0
    else:
        contrast   = args.contrast
        saturation = args.saturation
        sharpness  = args.sharpness
        brightness = args.brightness
        gamma      = args.gamma
        warmth     = args.warmth

    print(f"로딩: {args.image}")
    original = load_image(args.image)
    print(f"원본 크기: {original.width}×{original.height}")
    print(
        f"설정: brightness={brightness}, gamma={gamma}, contrast={contrast}, "
        f"saturation={saturation}, sharpness={sharpness}, warmth={warmth}, "
        f"dither={args.dither}, fill={'yes' if args.fill else 'no'}"
    )

    simulated, stats = simulate_eink(
        original,
        contrast=contrast,
        saturation=saturation,
        sharpness=sharpness,
        brightness=brightness,
        gamma=gamma,
        warmth=warmth,
        dither=args.dither,
        fill_mode=args.fill,
    )

    print("\n색상 분포:")
    for name, pct in stats.items():
        if name != "(unused)":
            bar = "█" * int(float(pct.rstrip("%")) / 2)
            print(f"  {name:8s}: {pct:6s}  {bar}")

    param_label = (
        f"br={brightness} γ={gamma} co={contrast} "
        f"sa={saturation} sh={sharpness} wa={warmth} d={args.dither}"
    )

    if args.compare:
        result = make_compare(original, simulated, stats, label=param_label)
    else:
        result = simulated

    if args.output:
        out_path = Path(args.output)
        result.save(out_path)
        print(f"\n저장 완료 → {out_path}")
    else:
        print("\n미리보기 창 열기... (창 닫으면 종료)")
        result.show()


if __name__ == "__main__":
    main()
