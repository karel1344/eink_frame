"""Tests for photo_source/local.py"""

import io
from pathlib import Path

import pytest
from PIL import Image

from database import Database
from photo_source.base import Photo, PhotoSource
from photo_source.local import (
    SUPPORTED_SUFFIXES,
    THUMBNAIL_SIZE,
    MAX_UPLOAD_BYTES,
    LocalPhotoSource,
    _sanitise_filename,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def photos_dir(tmp_path):
    return tmp_path / "photos" / "local"


@pytest.fixture
def source(photos_dir, db):
    return LocalPhotoSource(photos_dir, db=db)


def make_jpeg_bytes(width=400, height=300, color=(100, 150, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buf, format="JPEG")
    return buf.getvalue()


def make_png_bytes(width=200, height=200) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(50, 50, 50)).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# base.py: Photo dataclass & PhotoSource interface
# ---------------------------------------------------------------------------

class TestPhotoBase:
    def test_photo_display_name_prefers_title(self):
        p = Photo(id=1, source="local", filename="file.jpg", file_path="/f.jpg", title="My Photo")
        assert p.display_name == "My Photo"

    def test_photo_display_name_fallback_filename(self):
        p = Photo(id=1, source="local", filename="file.jpg", file_path="/f.jpg")
        assert p.display_name == "file.jpg"

    def test_photo_source_is_abstract(self):
        with pytest.raises(TypeError):
            PhotoSource()  # type: ignore


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestInit:
    def test_creates_directories(self, photos_dir, db):
        LocalPhotoSource(photos_dir, db=db)
        assert photos_dir.exists()
        assert (photos_dir / ".thumbnails").exists()

    def test_empty_dir_count_zero(self, source):
        assert source.count() == 0

    def test_list_photos_empty(self, source):
        assert source.list_photos() == []

    def test_sync_registers_existing_files(self, photos_dir, db):
        img_path = photos_dir / "pre.jpg"
        photos_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (100, 100)).save(img_path, "JPEG")

        src = LocalPhotoSource(photos_dir, db=db)
        assert src.count() == 1
        assert src.list_photos()[0].filename == "pre.jpg"

    def test_sync_skips_already_registered(self, photos_dir, db):
        photos_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (100, 100)).save(photos_dir / "x.jpg", "JPEG")

        src1 = LocalPhotoSource(photos_dir, db=db)
        count_after_first = src1.count()
        LocalPhotoSource(photos_dir, db=db)  # re-init
        assert db.count_photos() == count_after_first  # no duplicates

    def test_sync_ignores_unsupported_files(self, photos_dir, db):
        photos_dir.mkdir(parents=True, exist_ok=True)
        (photos_dir / "readme.txt").write_text("hello")
        src = LocalPhotoSource(photos_dir, db=db)
        assert src.count() == 0


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

class TestUpload:
    def test_upload_jpeg(self, source):
        photo = source.save_upload("cat.jpg", io.BytesIO(make_jpeg_bytes(800, 600)))
        assert photo.source == "local"
        assert photo.filename == "cat.jpg"
        assert photo.mime_type == "image/jpeg"
        assert photo.width == 800
        assert photo.height == 600
        assert photo.file_size > 0

    def test_upload_png(self, source):
        photo = source.save_upload("img.png", io.BytesIO(make_png_bytes()))
        assert photo.mime_type == "image/png"

    def test_upload_creates_thumbnail(self, source, photos_dir):
        photo = source.save_upload("cat.jpg", io.BytesIO(make_jpeg_bytes()))
        assert photo.thumbnail_path is not None
        thumb = Path(photo.thumbnail_path)
        assert thumb.exists()
        assert thumb.parent == photos_dir / ".thumbnails"
        # thumbnail must be at most 200×200
        with Image.open(thumb) as img:
            assert img.width <= THUMBNAIL_SIZE[0]
            assert img.height <= THUMBNAIL_SIZE[1]

    def test_upload_registered_in_db(self, source, db):
        source.save_upload("x.jpg", io.BytesIO(make_jpeg_bytes()))
        assert db.count_photos(source="local") == 1

    def test_upload_unsupported_extension_raises(self, source):
        with pytest.raises(ValueError, match="Unsupported file type"):
            source.save_upload("bad.bmp", io.BytesIO(b"data"))

    def test_upload_gif_raises(self, source):
        with pytest.raises(ValueError, match="Unsupported file type"):
            source.save_upload("anim.gif", io.BytesIO(b"data"))

    def test_upload_size_limit_raises(self, source):
        big = io.BytesIO(b"x" * (MAX_UPLOAD_BYTES + 1))
        with pytest.raises(ValueError, match="limit"):
            source.save_upload("big.jpg", big)

    def test_upload_size_limit_cleans_up_file(self, source, photos_dir):
        big = io.BytesIO(b"x" * (MAX_UPLOAD_BYTES + 1))
        try:
            source.save_upload("big.jpg", big)
        except ValueError:
            pass
        remaining = list(photos_dir.glob("big*.jpg"))
        assert remaining == []

    def test_upload_duplicate_name_gets_suffix(self, source):
        p1 = source.save_upload("photo.jpg", io.BytesIO(make_jpeg_bytes()))
        p2 = source.save_upload("photo.jpg", io.BytesIO(make_jpeg_bytes()))
        assert p1.filename != p2.filename
        assert p2.filename == "photo_1.jpg"

    def test_upload_path_traversal_sanitised(self, source, photos_dir):
        photo = source.save_upload("../evil.jpg", io.BytesIO(make_jpeg_bytes()))
        # file must land inside photos_dir, not outside
        assert Path(photo.file_path).parent == photos_dir
        assert photo.filename == "evil.jpg"

    def test_upload_null_byte_in_filename(self, source):
        photo = source.save_upload("na\x00me.jpg", io.BytesIO(make_jpeg_bytes()))
        assert "\x00" not in photo.filename


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

class TestDelete:
    def test_delete_removes_file(self, source, photos_dir):
        photo = source.save_upload("x.jpg", io.BytesIO(make_jpeg_bytes()))
        source.delete_photo(photo.id)
        assert not Path(photo.file_path).exists()

    def test_delete_removes_thumbnail(self, source):
        photo = source.save_upload("x.jpg", io.BytesIO(make_jpeg_bytes()))
        thumb = photo.thumbnail_path
        source.delete_photo(photo.id)
        if thumb:
            assert not Path(thumb).exists()

    def test_delete_removes_db_row(self, source, db):
        photo = source.save_upload("x.jpg", io.BytesIO(make_jpeg_bytes()))
        source.delete_photo(photo.id)
        assert db.get_photo(photo.id) is None
        assert source.count() == 0

    def test_delete_nonexistent_is_noop(self, source):
        source.delete_photo(999)  # must not raise


# ---------------------------------------------------------------------------
# Thumbnails
# ---------------------------------------------------------------------------

class TestThumbnails:
    def test_ensure_thumbnail_creates_if_missing(self, source, db):
        photo = source.save_upload("x.jpg", io.BytesIO(make_jpeg_bytes()))
        # remove thumbnail manually
        if photo.thumbnail_path:
            Path(photo.thumbnail_path).unlink()
            db.update_photo(photo.id, thumbnail_path=None)
        result = source.ensure_thumbnail(photo.id)
        assert result is not None
        assert result.exists()

    def test_ensure_thumbnail_returns_existing_path(self, source):
        photo = source.save_upload("x.jpg", io.BytesIO(make_jpeg_bytes()))
        path1 = source.ensure_thumbnail(photo.id)
        path2 = source.ensure_thumbnail(photo.id)
        assert path1 == path2

    def test_ensure_thumbnail_unknown_id_returns_none(self, source):
        assert source.ensure_thumbnail(999) is None


# ---------------------------------------------------------------------------
# Sanitise filename helper
# ---------------------------------------------------------------------------

class TestSanitiseFilename:
    def test_strips_path_prefix(self):
        assert _sanitise_filename("../../../etc/passwd") == "passwd"

    def test_strips_null_bytes(self):
        assert "\x00" not in _sanitise_filename("na\x00me.jpg")

    def test_empty_string_fallback(self):
        assert _sanitise_filename("") == "upload"

    def test_normal_name_unchanged(self):
        assert _sanitise_filename("photo.jpg") == "photo.jpg"
