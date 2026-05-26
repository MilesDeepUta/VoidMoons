"""
User database — stores assignment and scan data.

Schema is intentionally minimal:
  - assignment: which system_ids count toward the user's scan goal
  - scans:      one row per moon ever scanned (PK = automatic rescan overwrite)
  - scan_ores:  parsed ore breakdown (regenerable from scans.raw_chunk)
  - meta:       key/value settings store

scans.raw_chunk is a BLOB of the exact bytes the user pasted for that moon.
We never re-encode or normalize it — this is what guarantees byte-perfect
export back to the alliance.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS assignment (
    system_id INTEGER PRIMARY KEY,
    added_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scans (
    moon_id        INTEGER PRIMARY KEY,
    scanned_at     TEXT NOT NULL,
    raw_chunk      BLOB NOT NULL,
    in_assignment  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scan_ores (
    moon_id     INTEGER NOT NULL,
    ore_name    TEXT NOT NULL,
    ore_type_id INTEGER NOT NULL,
    quantity    REAL NOT NULL,
    PRIMARY KEY (moon_id, ore_type_id),
    FOREIGN KEY (moon_id) REFERENCES scans(moon_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_scans_in_assignment ON scans(in_assignment);
"""

# Capture-of-clipboard format. Set during the first ingest of a real EVE paste.
META_HEADER_BYTES   = "fmt.header_bytes"     # the header line + its line ending
META_TRAILER_BYTES  = "fmt.trailer_bytes"    # any bytes after the last moon chunk
META_CONSTELLATION  = "assignment.constellation_id"  # for display


class UserDB:
    """Thin wrapper around the user.db SQLite file."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, isolation_level=None)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Cursor]:
        cur = self._conn.cursor()
        cur.execute("BEGIN")
        try:
            yield cur
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise

    # ----- meta key/value -----

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def get_meta_bytes(self, key: str) -> bytes | None:
        v = self.get_meta(key)
        if v is None:
            return None
        # we stored bytes hex-encoded as text
        return bytes.fromhex(v)

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def set_meta_bytes(self, key: str, value: bytes) -> None:
        self.set_meta(key, value.hex())

    # ----- assignment -----

    def set_assignment(self, system_ids: Iterable[int], constellation_id: int | None = None) -> None:
        ids = list(system_ids)
        with self.tx() as c:
            c.execute("DELETE FROM assignment")
            c.executemany(
                "INSERT INTO assignment(system_id, added_at) VALUES(?, datetime('now'))",
                [(sid,) for sid in ids],
            )
            # Reconcile in_assignment flags on existing scans
            c.execute("UPDATE scans SET in_assignment = 0")
            if ids:
                placeholders = ",".join("?" * len(ids))
                # we don't have system_id on scans, so we have to look up via static_db
                # at the caller level. Caller passes moon_ids that are in-assignment.
                # Cleaner: compute the moon set in caller using static_db, then update.
                pass  # the helper below handles this
        if constellation_id is not None:
            self.set_meta(META_CONSTELLATION, str(constellation_id))

    def reconcile_in_assignment(self, assigned_moon_ids: Iterable[int]) -> None:
        """Flip in_assignment flags on all existing scan rows.
        Caller is responsible for computing the moon set from the SDE."""
        ids = list(assigned_moon_ids)
        with self.tx() as c:
            c.execute("UPDATE scans SET in_assignment = 0")
            if ids:
                # Batch in chunks to avoid hitting SQLite parameter limits
                CHUNK = 500
                for i in range(0, len(ids), CHUNK):
                    chunk = ids[i:i + CHUNK]
                    placeholders = ",".join("?" * len(chunk))
                    c.execute(
                        f"UPDATE scans SET in_assignment = 1 WHERE moon_id IN ({placeholders})",
                        chunk,
                    )

    def get_assigned_system_ids(self) -> list[int]:
        return [r[0] for r in self._conn.execute("SELECT system_id FROM assignment").fetchall()]

    def get_constellation_id(self) -> int | None:
        v = self.get_meta(META_CONSTELLATION)
        return int(v) if v is not None else None

    # ----- scans -----

    def upsert_scan(
        self,
        moon_id: int,
        scanned_at: str,
        raw_chunk: bytes,
        in_assignment: bool,
        ores: list[tuple[str, int, float]],
    ) -> None:
        """Insert or replace a scan and its ore breakdown atomically.
        ores is a list of (ore_name, ore_type_id, quantity)."""
        with self.tx() as c:
            c.execute(
                "INSERT INTO scans(moon_id, scanned_at, raw_chunk, in_assignment) "
                "VALUES(?, ?, ?, ?) "
                "ON CONFLICT(moon_id) DO UPDATE SET "
                "  scanned_at = excluded.scanned_at, "
                "  raw_chunk = excluded.raw_chunk, "
                "  in_assignment = excluded.in_assignment",
                (moon_id, scanned_at, raw_chunk, 1 if in_assignment else 0),
            )
            c.execute("DELETE FROM scan_ores WHERE moon_id = ?", (moon_id,))
            c.executemany(
                "INSERT INTO scan_ores(moon_id, ore_name, ore_type_id, quantity) "
                "VALUES(?, ?, ?, ?)",
                [(moon_id, name, type_id, qty) for name, type_id, qty in ores],
            )

    def get_scan(self, moon_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT moon_id, scanned_at, raw_chunk, in_assignment FROM scans WHERE moon_id = ?",
            (moon_id,),
        ).fetchone()
        if not row:
            return None
        ores = self._conn.execute(
            "SELECT ore_name, ore_type_id, quantity FROM scan_ores "
            "WHERE moon_id = ? ORDER BY quantity DESC",
            (moon_id,),
        ).fetchall()
        return {
            "moon_id": row[0],
            "scanned_at": row[1],
            "raw_chunk": row[2],
            "in_assignment": bool(row[3]),
            "ores": [{"name": o[0], "type_id": o[1], "quantity": o[2]} for o in ores],
        }

    def get_scanned_moon_ids(self, in_assignment: bool | None = None) -> set[int]:
        if in_assignment is None:
            rows = self._conn.execute("SELECT moon_id FROM scans").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT moon_id FROM scans WHERE in_assignment = ?",
                (1 if in_assignment else 0,),
            ).fetchall()
        return {r[0] for r in rows}

    def get_all_scans_ordered(self, only_in_assignment: bool = True) -> list[tuple[int, bytes]]:
        """Returns [(moon_id, raw_chunk)] in (system, planet, moon) order.
        Ordering is approximate (by moon_id, which is roughly sequential by location)."""
        sql = "SELECT moon_id, raw_chunk FROM scans"
        if only_in_assignment:
            sql += " WHERE in_assignment = 1"
        sql += " ORDER BY moon_id"
        return self._conn.execute(sql).fetchall()

    def delete_scan(self, moon_id: int) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM scans WHERE moon_id = ?", (moon_id,))

    def count_scans(self, only_in_assignment: bool = True) -> int:
        if only_in_assignment:
            return self._conn.execute(
                "SELECT COUNT(*) FROM scans WHERE in_assignment = 1"
            ).fetchone()[0]
        return self._conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
