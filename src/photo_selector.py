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

        Persists {remaining, shown} in the DB (key: 'shuffle_queue').
        - remaining: IDs not yet shown this cycle (in shuffled order)
        - shown:     IDs already shown this cycle

        On each call:
          1. Load state; drop IDs for deleted photos from both lists.
          2. Any photo not in remaining OR shown is treated as new and
             inserted at a random position in remaining.
          3. If remaining is empty (all shown), start a new cycle.
          4. Pop the first ID from remaining, add to shown, save, return.
        """
        photo_map = {p.id: p for p in all_photos}
        all_ids = set(photo_map.keys())

        raw = self._db.get_state("shuffle_queue")
        parsed = json.loads(raw) if raw else {}
        # Support migration from old format (plain list) to new dict format
        if isinstance(parsed, list):
            parsed = {}
        data: dict = parsed
        remaining: list[int] = data.get("remaining", [])
        shown: set[int] = set(data.get("shown", []))

        # Drop IDs for photos that no longer exist
        remaining = [pid for pid in remaining if pid in all_ids]
        shown = {pid for pid in shown if pid in all_ids}

        # Insert newly added photos into remaining at random positions
        known_ids = set(remaining) | shown
        new_ids = [pid for pid in all_ids if pid not in known_ids]
        if new_ids:
            for pid in new_ids:
                pos = random.randint(0, len(remaining))
                remaining.insert(pos, pid)
            logger.debug("Inserted %d new photo(s) into shuffle queue", len(new_ids))

        # If remaining is exhausted, start a new cycle
        if not remaining:
            remaining = list(all_ids)
            random.shuffle(remaining)
            shown = set()
            logger.info("Shuffle queue exhausted — starting new cycle (%d photos)", len(remaining))

        photo_id = remaining.pop(0)
        shown.add(photo_id)

        self._db.set_state("shuffle_queue", json.dumps({
            "remaining": remaining,
            "shown": list(shown),
        }))
        logger.debug(
            "Shuffle pick: photo_id=%d, %d remaining / %d shown this cycle",
            photo_id, len(remaining), len(shown),
        )

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
