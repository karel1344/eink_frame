"""Abstract base classes for photo sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Photo:
    """Represents a single photo from any source."""

    id: int
    source: str                        # 'local' or 'google'
    filename: str
    file_path: str                     # absolute path to the local file
    title: str | None = None
    width: int | None = None
    height: int | None = None
    mime_type: str | None = None
    taken_at: datetime | None = None
    added_at: datetime | None = None
    last_displayed: datetime | None = None
    thumbnail_path: str | None = None
    file_size: int | None = None
    google_id: str | None = None
    is_deleted: bool = False

    @property
    def display_name(self) -> str:
        return self.title or self.filename


class PhotoSource(ABC):
    """Abstract interface for photo sources (local, Google Photos, etc.)."""

    @abstractmethod
    def list_photos(self) -> list[Photo]:
        """Return all available (non-deleted) photos from this source."""

    @abstractmethod
    def get_photo(self, photo_id: int) -> Photo | None:
        """Return a single photo by DB id, or None if not found."""

    @abstractmethod
    def count(self) -> int:
        """Return the number of available photos."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Identifier string for this source ('local' or 'google')."""
