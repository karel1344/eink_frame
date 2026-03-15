"""Photo display loop for E-Ink Photo Frame.

One execution of run_once() does:
  1. Sync local photo directory → DB
  2. Select a photo (random or sequential, with repeat avoidance)
  3. Process image (resize, EXIF rotate, battery overlay)
  4. Send to display hardware (or save as PNG in dry-run mode)
  5. Record display event in DB and sleep display

Intended to be called once per wake cycle; Witty Pi handles the schedule
and reboots the Pi at the configured update_time.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Project root is two levels up from this file (src/frame_runner.py)
_PROJECT_ROOT = Path(__file__).parent.parent


def _build_sources(config) -> list:
    """Instantiate all enabled photo sources."""
    from database import get_db
    from photo_source.local import LocalPhotoSource

    db = get_db()
    sources = []

    if config.get("photo_sources.local.enabled", True):
        raw_path = config.get("photo_sources.local.path", "photos/local")
        local_path = Path(raw_path)
        if not local_path.is_absolute():
            local_path = _PROJECT_ROOT / local_path
        sources.append(LocalPhotoSource(local_path, db))
        logger.debug("Local photo source: %s", local_path)

    # Google Photos: not yet implemented
    if config.get("photo_sources.google_photos.enabled", False):
        logger.warning("Google Photos source is not yet implemented; skipping")

    return sources


def run_once(*, dry_run: bool = False) -> bool:
    """Select a photo, process it, display it, record it.

    Args:
        dry_run: If True, saves the processed image to ``debug_output.png``
                 in the project root instead of sending it to the display
                 hardware.  Useful for testing on Mac.

    Returns:
        True if a photo was successfully displayed (or saved in dry-run),
        False if nothing could be shown (e.g. no photos available).
    """
    from config import get_config
    from database import get_db
    from display import get_display
    from image_processor import ImageProcessor
    from photo_selector import PhotoSelector

    config = get_config()
    db = get_db()

    # 1. Build photo sources (LocalPhotoSource syncs disk → DB on init)
    sources = _build_sources(config)
    if not sources:
        logger.error("No photo sources configured")
        return False

    # 2. Select photo
    selector = PhotoSelector(db, config)
    photo = selector.pick(sources)
    if photo is None:
        logger.warning("No photos available — showing default image")
        from status_display import show_default_image
        show_default_image(dry_run=dry_run)
        return False

    logger.info("Selected: %s (id=%d, source=%s)", photo.display_name, photo.id, photo.source)

    # 3. Process image
    try:
        from power_manager import get_power_manager
        voltage = get_power_manager().read_input_voltage()

        processor = ImageProcessor.from_config(
            assets_dir=_PROJECT_ROOT / "assets"
        )
        image = processor.process(photo.file_path, battery_voltage=voltage)
    except Exception:
        logger.exception("Image processing failed for %s", photo.file_path)
        return False

    # 4. Show on display
    # display.simulate=true → PNG 저장 (하드웨어 미사용)
    # display.simulate 미설정 시 dry_run 값으로 폴백 (--frame --dry-run 하위 호환)
    simulate_display = config.get("display.simulate", dry_run)
    if simulate_display:
        out_path = _PROJECT_ROOT / "debug_output.png"
        image.save(out_path)
        logger.info("Display simulated: saved processed image → %s", out_path)
    else:
        try:
            display = get_display(config.display_model)
            display.init()
            display.show(image)
            display.sleep()
        except Exception:
            logger.exception("Display error")
            return False

    # 5. Record in DB
    db.record_display(photo.id)
    db.last_displayed_photo_id = photo.id

    logger.info("Done — displayed: %s", photo.display_name)
    return True
