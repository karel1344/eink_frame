"""Tests for database.py"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import pytest

from database import Database


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


# ---------------------------------------------------------------------------
# Schema / connection
# ---------------------------------------------------------------------------

class TestSchema:
    def test_wal_mode(self, db):
        conn = sqlite3.connect(db._db_path)
        row = conn.execute("PRAGMA journal_mode").fetchone()
        conn.close()
        assert row[0] == "wal"

    def test_tables_created(self, db):
        conn = sqlite3.connect(db._db_path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert {"photos", "display_history", "state", "schema_version"} <= tables

    def test_schema_version_is_1(self, db):
        conn = sqlite3.connect(db._db_path)
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        conn.close()
        assert row[0] == 1

    def test_migration_idempotent(self, tmp_path):
        """Creating the DB twice must not raise."""
        db1 = Database(tmp_path / "idem.db")
        db2 = Database(tmp_path / "idem.db")  # re-open same file
        assert db2.count_photos() == 0

    def test_google_id_unique_index(self, db):
        db.add_photo("google", "a.jpg", "/photos/a.jpg", google_id="gid1")
        with pytest.raises(Exception):
            # Second row with same google_id must fail
            db.add_photo("google", "b.jpg", "/photos/b.jpg", google_id="gid1")

    def test_google_id_null_not_unique_constrained(self, db):
        db.add_photo("local", "a.jpg", "/photos/a.jpg")
        db.add_photo("local", "b.jpg", "/photos/b.jpg")  # both have google_id=None


# ---------------------------------------------------------------------------
# Photos CRUD
# ---------------------------------------------------------------------------

class TestPhotos:
    def test_add_returns_id(self, db):
        id_ = db.add_photo("local", "cat.jpg", "/photos/cat.jpg")
        assert isinstance(id_, int)
        assert id_ > 0

    def test_add_duplicate_returns_same_id(self, db):
        id1 = db.add_photo("local", "cat.jpg", "/photos/cat.jpg")
        id2 = db.add_photo("local", "cat.jpg", "/photos/cat.jpg")
        assert id1 == id2

    def test_add_invalid_source_raises(self, db):
        with pytest.raises(ValueError, match="Invalid source"):
            db.add_photo("dropbox", "x.jpg", "/x.jpg")

    def test_get_photo(self, db):
        id_ = db.add_photo("local", "x.jpg", "/x.jpg", title="X")
        row = db.get_photo(id_)
        assert row["title"] == "X"
        assert row["source"] == "local"

    def test_get_photo_missing(self, db):
        assert db.get_photo(999) is None

    def test_get_photo_by_filename(self, db):
        db.add_photo("local", "x.jpg", "/x.jpg")
        assert db.get_photo_by_filename("local", "x.jpg") is not None
        assert db.get_photo_by_filename("local", "nope.jpg") is None

    def test_get_photo_by_google_id(self, db):
        db.add_photo("google", "g.jpg", "/g.jpg", google_id="GID")
        assert db.get_photo_by_google_id("GID") is not None
        assert db.get_photo_by_google_id("NOPE") is None

    def test_list_photos_all(self, db):
        db.add_photo("local", "a.jpg", "/a.jpg")
        db.add_photo("google", "b.jpg", "/b.jpg")
        assert len(db.list_photos()) == 2

    def test_list_photos_by_source(self, db):
        db.add_photo("local", "a.jpg", "/a.jpg")
        db.add_photo("google", "b.jpg", "/b.jpg")
        assert len(db.list_photos(source="local")) == 1
        assert len(db.list_photos(source="google")) == 1

    def test_list_photos_excludes_deleted_by_default(self, db):
        id_ = db.add_photo("local", "a.jpg", "/a.jpg")
        db.mark_deleted(id_)
        assert len(db.list_photos()) == 0
        assert len(db.list_photos(include_deleted=True)) == 1

    def test_update_photo(self, db):
        id_ = db.add_photo("local", "x.jpg", "/x.jpg")
        db.update_photo(id_, title="New Title", width=800)
        row = db.get_photo(id_)
        assert row["title"] == "New Title"
        assert row["width"] == 800

    def test_update_photo_invalid_field_raises(self, db):
        id_ = db.add_photo("local", "x.jpg", "/x.jpg")
        with pytest.raises(ValueError, match="Unknown photo fields"):
            db.update_photo(id_, nonexistent_col="bad")

    def test_mark_deleted(self, db):
        id_ = db.add_photo("local", "x.jpg", "/x.jpg")
        db.mark_deleted(id_)
        row = db.get_photo(id_)
        assert row["is_deleted"] == 1
        assert db.count_photos() == 0
        assert db.count_photos(include_deleted=True) == 1

    def test_delete_photo_hard(self, db):
        id_ = db.add_photo("local", "x.jpg", "/x.jpg")
        db.delete_photo(id_)
        assert db.get_photo(id_) is None
        assert db.count_photos(include_deleted=True) == 0

    def test_count_photos(self, db):
        db.add_photo("local", "a.jpg", "/a.jpg")
        db.add_photo("local", "b.jpg", "/b.jpg")
        db.add_photo("google", "c.jpg", "/c.jpg")
        assert db.count_photos() == 3
        assert db.count_photos(source="local") == 2
        assert db.count_photos(source="google") == 1

    def test_get_lru_photos(self, db):
        now = datetime.now()
        id1 = db.add_photo("local", "a.jpg", "/a.jpg")
        id2 = db.add_photo("local", "b.jpg", "/b.jpg")
        db.update_photo(id1, last_accessed=datetime(2024, 1, 1))
        db.update_photo(id2, last_accessed=datetime(2024, 6, 1))
        lru = db.get_lru_photos("local", limit=1)
        assert lru[0]["id"] == id1  # oldest first


# ---------------------------------------------------------------------------
# Display history
# ---------------------------------------------------------------------------

class TestDisplayHistory:
    def test_record_display_updates_last_displayed(self, db):
        id_ = db.add_photo("local", "x.jpg", "/x.jpg")
        db.record_display(id_)
        row = db.get_photo(id_)
        assert row["last_displayed"] is not None

    def test_get_recent_photo_ids_order(self, db):
        id1 = db.add_photo("local", "a.jpg", "/a.jpg")
        id2 = db.add_photo("local", "b.jpg", "/b.jpg")
        db.record_display(id1, displayed_at=datetime(2024, 1, 1))
        db.record_display(id2, displayed_at=datetime(2024, 6, 1))
        db.record_display(id1, displayed_at=datetime(2025, 1, 1))  # id1 most recent
        recent = db.get_recent_photo_ids(limit=30)
        assert recent[0] == id1  # id1 has MAX displayed_at

    def test_get_recent_photo_ids_limit(self, db):
        ids = [db.add_photo("local", f"{i}.jpg", f"/{i}.jpg") for i in range(5)]
        for id_ in ids:
            db.record_display(id_)
        assert len(db.get_recent_photo_ids(limit=3)) == 3

    def test_trim_history(self, db):
        id_ = db.add_photo("local", "x.jpg", "/x.jpg")
        for _ in range(10):
            db.record_display(id_)
        db.trim_history(keep=3)
        conn = sqlite3.connect(db._db_path)
        count = conn.execute("SELECT COUNT(*) FROM display_history").fetchone()[0]
        conn.close()
        assert count == 3

    def test_cascade_delete_removes_history(self, db):
        id_ = db.add_photo("local", "x.jpg", "/x.jpg")
        db.record_display(id_)
        db.delete_photo(id_)
        conn = sqlite3.connect(db._db_path)
        count = conn.execute("SELECT COUNT(*) FROM display_history").fetchone()[0]
        conn.close()
        assert count == 0


# ---------------------------------------------------------------------------
# State store
# ---------------------------------------------------------------------------

class TestState:
    def test_set_get(self, db):
        db.set_state("key1", "value1")
        assert db.get_state("key1") == "value1"

    def test_get_missing_returns_default(self, db):
        assert db.get_state("nope") is None
        assert db.get_state("nope", "fallback") == "fallback"

    def test_upsert(self, db):
        db.set_state("k", "v1")
        db.set_state("k", "v2")
        assert db.get_state("k") == "v2"

    def test_delete_state(self, db):
        db.set_state("k", "v")
        db.delete_state("k")
        assert db.get_state("k", "default") == "default"

    def test_last_sync_token(self, db):
        db.last_sync_token = "tok_abc"
        assert db.last_sync_token == "tok_abc"

    def test_last_sync_token_none_deletes_key(self, db):
        db.last_sync_token = "tok"
        db.last_sync_token = None
        assert db.get_state("last_sync_token", "default") == "default"

    def test_last_displayed_photo_id(self, db):
        id_ = db.add_photo("local", "x.jpg", "/x.jpg")
        db.last_displayed_photo_id = id_
        assert db.last_displayed_photo_id == id_

    def test_last_displayed_photo_id_none(self, db):
        db.last_displayed_photo_id = None
        assert db.last_displayed_photo_id is None


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_writes(self, db):
        errors = []

        def insert(n):
            try:
                db.add_photo("local", f"photo_{n}.jpg", f"/photo_{n}.jpg")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=insert, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert db.count_photos() == 20
