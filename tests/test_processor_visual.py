#!/usr/bin/env python3
"""image_processor.py 시각적 테스트.

사용법:
    python tests/test_processor_visual.py                    # photos/local/ 에서 자동 선택
    python tests/test_processor_visual.py path/to/photo.jpg  # 특정 사진 지정
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from image_processor import ImageProcessor

# ── 설정 ──────────────────────────────────────────────────────────────────────
DISPLAY_W, DISPLAY_H = 800, 480
OUTPUT_DIR = Path(__file__).parent / "results"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── 사진 찾기 ─────────────────────────────────────────────────────────────────
if len(sys.argv) > 1:
    photos = [Path(sys.argv[1])]
else:
    local = Path(__file__).parent.parent / "photos" / "local"
    photos = [
        p for p in local.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic", ".heif"}
        and not p.name.startswith(".")
    ]
    if not photos:
        print("photos/local/ 에 사진이 없습니다. 경로를 직접 지정하세요:")
        print("  python tests/test_processor_visual.py ~/Pictures/photo.jpg")
        sys.exit(1)
    photos = photos[:1]  # 배터리 테스트는 첫 번째 사진 1장으로 충분

# ── 배터리 케이스 ──────────────────────────────────────────────────────────────
battery_cases = [
    ("battery_ok",       3.7,  "충분 (3.7V) — 아이콘 없음"),
    ("battery_low",      3.15, "낮음 (3.15V) — 주황 아이콘"),
    ("battery_critical", 2.95, "긴급 (2.95V) — 빨간 X 아이콘"),
]

# ── 처리 ──────────────────────────────────────────────────────────────────────
ASSETS_DIR = Path(__file__).parent.parent / "assets"
processor = ImageProcessor(DISPLAY_W, DISPLAY_H, fill_mode="fit", show_battery=True, assets_dir=ASSETS_DIR)

for photo in photos:
    print(f"\n▶ {photo.name}")
    for label, voltage, desc in battery_cases:
        result = processor.process(photo, battery_voltage=voltage)
        out = OUTPUT_DIR / f"{photo.stem}__{label}.jpg"
        result.save(out, "JPEG", quality=90)
        print(f"  {desc}")
        print(f"    → {out.name}")

print(f"\n✓ 결과 폴더: {OUTPUT_DIR}")
print(f"  open \"{OUTPUT_DIR}\"")
