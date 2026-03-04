"""Photo selection logic for E-Ink Photo Frame."""

from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class PhotoSelector:
    """Selects which photo to display next.

    Supports two modes (configured via photo_selection.mode):
      - 'random'     : random choice from eligible photos
      - 'sequential' : oldest last_displayed first (never-shown photos first)

    Repeat avoidance: photos shown in the last *repeat_threshold* displays
    are excluded from the candidate pool (unless the pool would be empty).
    """

    def __init__(self, db, config):
        """
        Args:
            db:     Database instance
            config: Config instance
        """
        self._db = db
        self._mode = config.get("photo_selection.mode", "random")
        self._avoid_repeats = config.get("photo_selection.avoid_repeats", True)
        self._repeat_threshold = int(
            config.get("photo_selection.repeat_threshold", 30)
        )

    def pick(self, sources: list) -> Optional[object]:
        """Select one photo from the given sources.

        Args:
            sources: List of PhotoSource instances to pull photos from.

        Returns:
            A Photo instance, or None if no photos are available.
        """
        all_photos = []
        for source in sources:
            all_photos.extend(source.list_photos())

        if not all_photos:
            logger.warning("No photos available in any source")
            return None

        candidates = self._filter_candidates(all_photos)

        if self._mode == "sequential":
            return self._pick_sequential(candidates)
        else:
            return random.choice(candidates)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _filter_candidates(self, all_photos: list) -> list:
        """Remove recently displayed photos from the candidate pool.

        If filtering would leave an empty pool, falls back to all photos
        so the display never gets stuck with nothing to show.
        """
        if not self._avoid_repeats or len(all_photos) <= 1:
            return all_photos

        recent_ids = set(self._db.get_recent_photo_ids(self._repeat_threshold))
        candidates = [p for p in all_photos if p.id not in recent_ids]

        if not candidates:
            logger.debug(
                "All %d photos were recently shown; resetting repeat window",
                len(all_photos),
            )
            return all_photos

        logger.debug(
            "%d candidates after excluding %d recent photos",
            len(candidates), len(recent_ids),
        )
        return candidates

    @staticmethod
    def _pick_sequential(candidates: list) -> object:
        """Return the photo with the oldest last_displayed time.

        Photos that have never been shown (last_displayed is None) are
        treated as oldest and always come first.
        """
        _epoch = datetime.min
        candidates.sort(key=lambda p: p.last_displayed or _epoch)
        return candidates[0]
