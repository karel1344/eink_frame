"""SQLite database management for E-Ink Photo Frame."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional

# Current schema version - increment when adding migrations
SCHEMA_VERSION = 1

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "einkframe.db"


class Database:
    """SQLite database manager with WAL mode, migrations, and thread-safe access."""

    def __init__(self, db_path: Path | str | None = None):
        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    # ------------------------------------------------------------------
    # Internal: setup
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._db_path,
            timeout=10,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _cursor(self) -> Generator[tuple[sqlite3.Connection, sqlite3.Cursor], None, None]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            yield conn, cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._cursor() as (conn, cur):
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
            )
            row = cur.execute("SELECT version FROM schema_version").fetchone()
            current = row["version"] if row else 0

        self._migrate(current)

    # ------------------------------------------------------------------
    # Migrations
    # ------------------------------------------------------------------

    def _migrate(self, from_version: int) -> None:
        migrations = {
            0: self._migrate_v0_to_v1,
        }
        for version in range(from_version, SCHEMA_VERSION):
            if version in migrations:
                migrations[version]()

    def _migrate_v0_to_v1(self) -> None:
        """Initial schema.

        Uses individual execute() calls (not executescript) so that the entire
        migration runs inside the transaction managed by _cursor(), allowing a
        full rollback if any statement fails.
        """
        with self._cursor() as (conn, cur):
            cur.execute("""
                CREATE TABLE IF NOT EXISTS photos (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    source          TEXT    NOT NULL CHECK(source IN ('local', 'google')),
                    filename        TEXT    NOT NULL,
                    google_id       TEXT,
                    title           TEXT,
                    width           INTEGER,
                    height          INTEGER,
                    mime_type       TEXT,
                    taken_at        TIMESTAMP,
                    added_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_displayed  TIMESTAMP,
                    last_accessed   TIMESTAMP,
                    file_path       TEXT    NOT NULL,
                    thumbnail_path  TEXT,
                    file_size       INTEGER,
                    is_deleted      INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(source, filename)
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_photos_source ON photos(source)"
            )
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_photos_google_id "
                "ON photos(google_id) WHERE google_id IS NOT NULL"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_photos_last_accessed ON photos(last_accessed)"
            )
            cur.execute("""
                CREATE TABLE IF NOT EXISTS display_history (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    photo_id     INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
                    displayed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_displayed_at "
                "ON display_history(displayed_at DESC)"
            )
            cur.execute("""
                CREATE TABLE IF NOT EXISTS state (
                    key        TEXT      PRIMARY KEY,
                    value      TEXT,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("DELETE FROM schema_version")
            cur.execute("INSERT INTO schema_version VALUES (?)", (1,))

    # ------------------------------------------------------------------
    # Photos
    # ------------------------------------------------------------------

    def add_photo(
        self,
        source: str,
        filename: str,
        file_path: str,
        *,
        google_id: str | None = None,
        title: str | None = None,
        width: int | None = None,
        height: int | None = None,
        mime_type: str | None = None,
        taken_at: datetime | None = None,
        file_size: int | None = None,
    ) -> int:
        """Insert a photo record. Returns the new row id.

        If a record with the same (source, filename) already exists, returns
        its existing id without modifying it.
        """
        if source not in ("local", "google"):
            raise ValueError(f"Invalid source '{source}': must be 'local' or 'google'")

        with self._cursor() as (conn, cur):
            cur.execute(
                """
                INSERT OR IGNORE INTO photos
                    (source, filename, file_path, google_id, title,
                     width, height, mime_type, taken_at, file_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source, filename, file_path, google_id, title,
                    width, height, mime_type,
                    taken_at.isoformat() if taken_at else None,
                    file_size,
                ),
            )
            if cur.lastrowid and cur.lastrowid != 0:
                return cur.lastrowid

        # Row already existed — fetch its id
        with self._cursor() as (conn, cur):
            row = cur.execute(
                "SELECT id FROM photos WHERE source=? AND filename=?",
                (source, filename),
            ).fetchone()
            return row["id"]

    def get_photo(self, photo_id: int) -> sqlite3.Row | None:
        """Return a single photo by id, or None."""
        with self._cursor() as (conn, cur):
            return cur.execute(
                "SELECT * FROM photos WHERE id=?", (photo_id,)
            ).fetchone()

    def get_photo_by_filename(self, source: str, filename: str) -> sqlite3.Row | None:
        with self._cursor() as (conn, cur):
            return cur.execute(
                "SELECT * FROM photos WHERE source=? AND filename=?",
                (source, filename),
            ).fetchone()

    def get_photo_by_google_id(self, google_id: str) -> sqlite3.Row | None:
        with self._cursor() as (conn, cur):
            return cur.execute(
                "SELECT * FROM photos WHERE google_id=?", (google_id,)
            ).fetchone()

    def list_photos(
        self,
        source: str | None = None,
        include_deleted: bool = False,
    ) -> list[sqlite3.Row]:
        """Return all photos, optionally filtered by source."""
        conditions = []
        params: list[Any] = []

        if source is not None:
            conditions.append("source=?")
            params.append(source)
        if not include_deleted:
            conditions.append("is_deleted=0")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with self._cursor() as (conn, cur):
            return cur.execute(
                f"SELECT * FROM photos {where} ORDER BY added_at DESC",
                params,
            ).fetchall()

    def update_photo(self, photo_id: int, **fields: Any) -> None:
        """Update arbitrary columns on a photo row."""
        if not fields:
            return
        allowed = {
            "title", "width", "height", "mime_type", "taken_at",
            "last_displayed", "last_accessed", "file_path",
            "thumbnail_path", "file_size", "is_deleted",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Unknown photo fields: {bad}")

        # Serialise datetime values
        for k, v in list(fields.items()):
            if isinstance(v, datetime):
                fields[k] = v.isoformat()

        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [photo_id]
        with self._cursor() as (conn, cur):
            cur.execute(
                f"UPDATE photos SET {set_clause} WHERE id=?", values
            )

    def mark_deleted(self, photo_id: int) -> None:
        """Soft-delete: mark is_deleted=1."""
        self.update_photo(photo_id, is_deleted=1)

    def delete_photo(self, photo_id: int) -> None:
        """Hard-delete a photo record (cascade removes display_history)."""
        with self._cursor() as (conn, cur):
            cur.execute("DELETE FROM photos WHERE id=?", (photo_id,))

    def get_lru_photos(self, source: str, limit: int) -> list[sqlite3.Row]:
        """Return up to *limit* non-deleted photos ordered by last_accessed ASC (oldest first)."""
        with self._cursor() as (conn, cur):
            return cur.execute(
                """
                SELECT * FROM photos
                WHERE source=? AND is_deleted=0
                ORDER BY COALESCE(last_accessed, added_at) ASC
                LIMIT ?
                """,
                (source, limit),
            ).fetchall()

    def count_photos(self, source: str | None = None, include_deleted: bool = False) -> int:
        conditions = []
        params: list[Any] = []
        if source is not None:
            conditions.append("source=?")
            params.append(source)
        if not include_deleted:
            conditions.append("is_deleted=0")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with self._cursor() as (conn, cur):
            row = cur.execute(f"SELECT COUNT(*) AS cnt FROM photos {where}", params).fetchone()
            return row["cnt"]

    # ------------------------------------------------------------------
    # Display history
    # ------------------------------------------------------------------

    def record_display(self, photo_id: int, displayed_at: datetime | None = None) -> None:
        """Record that a photo was shown on the display."""
        ts = (displayed_at or datetime.now()).isoformat()
        with self._cursor() as (conn, cur):
            cur.execute(
                "INSERT INTO display_history (photo_id, displayed_at) VALUES (?, ?)",
                (photo_id, ts),
            )
            # Also update photos.last_displayed
            cur.execute(
                "UPDATE photos SET last_displayed=?, last_accessed=? WHERE id=?",
                (ts, ts, photo_id),
            )

    def get_recent_photo_ids(self, limit: int = 30) -> list[int]:
        """Return photo ids shown in the most recent *limit* displays (newest first).

        Uses MAX(displayed_at) per photo so that a photo shown multiple times
        is ranked by its latest display time, not an arbitrary earlier one.
        """
        with self._cursor() as (conn, cur):
            rows = cur.execute(
                """
                SELECT photo_id FROM display_history
                GROUP BY photo_id
                ORDER BY MAX(displayed_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [r["photo_id"] for r in rows]

    def trim_history(self, keep: int = 30) -> None:
        """Keep only the most recent *keep* display history entries."""
        with self._cursor() as (conn, cur):
            cur.execute(
                """
                DELETE FROM display_history
                WHERE id NOT IN (
                    SELECT id FROM display_history
                    ORDER BY displayed_at DESC
                    LIMIT ?
                )
                """,
                (keep,),
            )

    # ------------------------------------------------------------------
    # State (key-value)
    # ------------------------------------------------------------------

    def get_state(self, key: str, default: str | None = None) -> str | None:
        """Read a persistent state value."""
        with self._cursor() as (conn, cur):
            row = cur.execute(
                "SELECT value FROM state WHERE key=?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_state(self, key: str, value: str | None) -> None:
        """Write (upsert) a persistent state value."""
        ts = datetime.now().isoformat()
        with self._cursor() as (conn, cur):
            cur.execute(
                """
                INSERT INTO state (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, ts),
            )

    def delete_state(self, key: str) -> None:
        with self._cursor() as (conn, cur):
            cur.execute("DELETE FROM state WHERE key=?", (key,))

    # ------------------------------------------------------------------
    # Convenience state helpers
    # ------------------------------------------------------------------

    @property
    def last_sync_token(self) -> str | None:
        return self.get_state("last_sync_token")

    @last_sync_token.setter
    def last_sync_token(self, token: str | None) -> None:
        if token is None:
            self.delete_state("last_sync_token")
        else:
            self.set_state("last_sync_token", token)

    @property
    def last_displayed_photo_id(self) -> int | None:
        value = self.get_state("last_displayed_photo_id")
        return int(value) if value is not None else None

    @last_displayed_photo_id.setter
    def last_displayed_photo_id(self, photo_id: int | None) -> None:
        self.set_state(
            "last_displayed_photo_id",
            str(photo_id) if photo_id is not None else None,
        )


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

_db: Database | None = None


def get_db() -> Database:
    """Return the global Database instance (created on first call)."""
    global _db
    if _db is None:
        _db = Database()
    return _db
