"""Local filesystem photo source."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Iterator

from PIL import Image, ExifTags

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass  # pillow-heif not installed; HEIC files will fail to open

from database import Database, get_db
from photo_source.base import Photo, PhotoSource

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
THUMBNAIL_SIZE = (200, 200)
THUMBNAIL_DIR_NAME = ".thumbnails"
UPLOAD_CHUNK_SIZE = 256 * 1024        # 256 KB per chunk
MAX_UPLOAD_BYTES = 20 * 1024 * 1024   # 20 MB hard limit


class LocalPhotoSource(PhotoSource):
    """Manages photos stored in the local filesystem under *photos_dir*.

    Directory layout::

        photos_dir/          (e.g. photos/local/)
            photo1.jpg
            photo2.png
            .thumbnails/
                photo1.jpg
                photo2.png
    """

    def __init__(
        self,
        photos_dir: Path | str,
        db: Database | None = None,
    ):
        self._dir = Path(photos_dir)
        self._thumb_dir = self._dir / THUMBNAIL_DIR_NAME
        self._db = db or get_db()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._thumb_dir.mkdir(parents=True, exist_ok=True)
        self._sync()

    # ------------------------------------------------------------------
    # PhotoSource interface
    # ------------------------------------------------------------------

    @property
    def source_name(self) -> str:
        return "local"

    def list_photos(self) -> list[Photo]:
        rows = self._db.list_photos(source="local", include_deleted=False)
        return [self._row_to_photo(r) for r in rows]

    def get_photo(self, photo_id: int) -> Photo | None:
        row = self._db.get_photo(photo_id)
        if row is None or row["source"] != "local":
            return None
        return self._row_to_photo(row)

    def count(self) -> int:
        return self._db.count_photos(source="local")

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def save_upload(
        self,
        filename: str,
        stream: BinaryIO,
        *,
        preserve_original: bool = True,
    ) -> Photo:
        """Write an uploaded file to disk in chunks, register it in the DB.

        Args:
            filename: Original filename from the client (used as-is after
                      sanitisation; duplicate names get a numeric suffix).
            stream: Readable binary stream (e.g. SpooledTemporaryFile from
                    FastAPI's UploadFile).
            preserve_original: If True, the file is stored as received.
                               (Future: False could trigger immediate resize.)

        Returns:
            The newly created Photo.

        Raises:
            ValueError: If the file type is unsupported or the size exceeds
                        MAX_UPLOAD_BYTES.
        """
        safe_name = _sanitise_filename(filename)
        suffix = Path(safe_name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError(
                f"Unsupported file type '{suffix}'. "
                f"Allowed: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
            )

        dest_path = self._unique_path(safe_name)
        written = 0
        try:
            with open(dest_path, "wb") as out:
                for chunk in _iter_chunks(stream):
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise ValueError(
                            f"Upload exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB limit"
                        )
                    out.write(chunk)
        except Exception:
            dest_path.unlink(missing_ok=True)
            raise

        # Build metadata
        width, height, taken_at = _read_image_meta(dest_path)
        thumb_path = self._make_thumbnail(dest_path)

        photo_id = self._db.add_photo(
            source="local",
            filename=dest_path.name,
            file_path=str(dest_path),
            title=Path(filename).stem,
            width=width,
            height=height,
            mime_type=_suffix_to_mime(suffix),
            taken_at=taken_at,
            file_size=written,
        )
        if thumb_path:
            self._db.update_photo(photo_id, thumbnail_path=str(thumb_path))

        logger.info("Saved upload: %s (%d bytes)", dest_path.name, written)
        row = self._db.get_photo(photo_id)
        assert row is not None
        return self._row_to_photo(row)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_photo(self, photo_id: int) -> None:
        """Remove a photo file (and its thumbnail) and hard-delete the DB row."""
        row = self._db.get_photo(photo_id)
        if row is None or row["source"] != "local":
            return

        file_path = Path(row["file_path"])
        file_path.unlink(missing_ok=True)

        if row["thumbnail_path"]:
            Path(row["thumbnail_path"]).unlink(missing_ok=True)

        self._db.delete_photo(photo_id)
        logger.info("Deleted local photo id=%d (%s)", photo_id, file_path.name)

    # ------------------------------------------------------------------
    # Thumbnails
    # ------------------------------------------------------------------

    def ensure_thumbnail(self, photo_id: int) -> Path | None:
        """Generate a thumbnail if one doesn't exist yet. Returns the path."""
        row = self._db.get_photo(photo_id)
        if row is None:
            return None

        if row["thumbnail_path"] and Path(row["thumbnail_path"]).exists():
            return Path(row["thumbnail_path"])

        thumb_path = self._make_thumbnail(Path(row["file_path"]))
        if thumb_path:
            self._db.update_photo(photo_id, thumbnail_path=str(thumb_path))
        return thumb_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sync(self) -> None:
        """Scan the photos directory and register any untracked files in the DB."""
        for path in self._dir.iterdir():
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if self._db.get_photo_by_filename("local", path.name) is not None:
                continue

            width, height, taken_at = _read_image_meta(path)
            thumb_path = self._make_thumbnail(path)
            photo_id = self._db.add_photo(
                source="local",
                filename=path.name,
                file_path=str(path),
                title=path.stem,
                width=width,
                height=height,
                mime_type=_suffix_to_mime(path.suffix.lower()),
                taken_at=taken_at,
                file_size=path.stat().st_size,
            )
            if thumb_path:
                self._db.update_photo(photo_id, thumbnail_path=str(thumb_path))
            logger.debug("Registered local photo: %s", path.name)

    def _unique_path(self, filename: str) -> Path:
        """Return a non-colliding destination path inside self._dir."""
        candidate = self._dir / filename
        if not candidate.exists():
            return candidate
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        n = 1
        while True:
            candidate = self._dir / f"{stem}_{n}{suffix}"
            if not candidate.exists():
                return candidate
            n += 1

    def _make_thumbnail(self, src: Path) -> Path | None:
        """Create a 200×200 thumbnail in self._thumb_dir. Returns the path."""
        if not src.exists():
            return None
        thumb_path = self._thumb_dir / src.name
        try:
            with Image.open(src) as img:
                img = _apply_exif_rotation(img)
                img.thumbnail(THUMBNAIL_SIZE)
                img.save(thumb_path, format=_pil_format(src.suffix))
            return thumb_path
        except Exception as exc:
            logger.warning("Thumbnail generation failed for %s: %s", src.name, exc)
            return None

    @staticmethod
    def _row_to_photo(row) -> Photo:
        def _dt(val: str | None) -> datetime | None:
            if not val:
                return None
            try:
                return datetime.fromisoformat(val)
            except ValueError:
                return None

        return Photo(
            id=row["id"],
            source=row["source"],
            filename=row["filename"],
            file_path=row["file_path"],
            title=row["title"],
            width=row["width"],
            height=row["height"],
            mime_type=row["mime_type"],
            taken_at=_dt(row["taken_at"]),
            added_at=_dt(row["added_at"]),
            last_displayed=_dt(row["last_displayed"]),
            thumbnail_path=row["thumbnail_path"],
            file_size=row["file_size"],
            google_id=row["google_id"],
            is_deleted=bool(row["is_deleted"]),
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _sanitise_filename(name: str) -> str:
    """Strip directory components and replace unsafe characters."""
    name = Path(name).name          # drop any path prefix
    name = name.replace("\x00", "") # strip null bytes
    return name or "upload"


def _iter_chunks(stream: BinaryIO) -> Iterator[bytes]:
    while True:
        chunk = stream.read(UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        yield chunk


def _read_image_meta(path: Path) -> tuple[int | None, int | None, datetime | None]:
    """Return (width, height, taken_at) from the image file, or (None, None, None)."""
    try:
        with Image.open(path) as img:
            width, height = img.size
            taken_at = _exif_datetime(img)
            return width, height, taken_at
    except Exception:
        return None, None, None


def _exif_datetime(img: Image.Image) -> datetime | None:
    """Extract DateTimeOriginal from EXIF data."""
    try:
        exif = img._getexif()  # type: ignore[attr-defined]
        if not exif:
            return None
        tag_map = {v: k for k, v in ExifTags.TAGS.items()}
        raw = exif.get(tag_map.get("DateTimeOriginal", 0))
        if raw:
            return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


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


def _suffix_to_mime(suffix: str) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".heic": "image/heic",
        ".heif": "image/heif",
    }.get(suffix, "application/octet-stream")


def _pil_format(suffix: str) -> str:
    return {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".heic": "JPEG",   # save thumbnail as JPEG regardless
        ".heif": "JPEG",
    }.get(suffix.lower(), "JPEG")
