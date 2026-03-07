"""Photo selection logic for E-Ink Photo Frame."""

from __future__ import annotations

import json
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

        if self._mode == "sequential":
            candidates = self._filter_candidates(all_photos)
            return self._pick_sequential(candidates)
        else:
            return self._pick_shuffle(all_photos)

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

    def _pick_shuffle(self, all_photos: list) -> object:
        """Shuffle-deck selection: show every photo once before repeating.

        Persists a queue of photo IDs in the DB (key: 'shuffle_queue').
        On each call:
          1. Load queue; remove IDs for deleted photos.
          2. Insert any new photos at random positions in the remaining queue.
          3. If queue is empty, generate a fresh shuffled queue from all photos.
          4. Pop and return the first photo; save updated queue.
        """
        photo_map = {p.id: p for p in all_photos}
        all_ids = set(photo_map.keys())

        # Load persisted queue
        raw = self._db.get_state("shuffle_queue")
        queue: list[int] = json.loads(raw) if raw else []

        # Drop IDs for photos that no longer exist
        queue = [pid for pid in queue if pid in all_ids]

        # Insert newly added photos at random positions
        queued_ids = set(queue)
        new_ids = [pid for pid in all_ids if pid not in queued_ids]
        if new_ids:
            for pid in new_ids:
                pos = random.randint(0, len(queue))
                queue.insert(pos, pid)
            logger.debug("Inserted %d new photo(s) into shuffle queue", len(new_ids))

        # If exhausted, start a new cycle
        if not queue:
            queue = list(all_ids)
            random.shuffle(queue)
            logger.info("Shuffle queue exhausted — starting new cycle (%d photos)", len(queue))

        photo_id = queue.pop(0)
        self._db.set_state("shuffle_queue", json.dumps(queue))
        logger.debug("Shuffle pick: photo_id=%d, %d remaining in queue", photo_id, len(queue))

        return photo_map.get(photo_id) or random.choice(all_photos)

    @staticmethod
    def _pick_sequential(candidates: list) -> object:
        """Return the photo with the oldest last_displayed time.

        Photos that have never been shown (last_displayed is None) are
        treated as oldest and always come first.
        """
        _epoch = datetime.min
        candidates.sort(key=lambda p: p.last_displayed or _epoch)
        return candidates[0]
