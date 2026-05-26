"""End-to-end test: clipboard bytes → DB → export → byte-exact match."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from moonscan.db import UserDB, META_HEADER_BYTES, META_TRAILER_BYTES
from moonscan.export import build_export
from moonscan.ingest import ingest_paste
from moonscan.static_db import StaticDB

FIXTURES = Path(__file__).parent / "fixtures"
STATIC_DB = Path(__file__).parent.parent / "data" / "eve_static.db"


@pytest.fixture
def static_db():
    db = StaticDB(STATIC_DB)
    yield db
    db.close()


@pytest.fixture
def user_db(tmp_path):
    db = UserDB(tmp_path / "user.db")
    yield db
    db.close()


def test_full_ingest_then_export_round_trip(static_db, user_db):
    """End-to-end byte-exact: real EVE paste → DB → reconstructed paste."""
    original = (FIXTURES / "sample_paste_with_trailing.bin").read_bytes()

    # Assign PYY3-5 (system 30002490) so both sample moons count as in-assignment
    user_db.set_assignment([30002490])
    # We must also reconcile the in_assignment flags. But on first ingest there
    # are no existing scans so reconcile is a no-op; ingest computes flags fresh.

    stats, _ = ingest_paste(original, user_db, static_db)
    assert stats.moons_in_paste == 2
    assert stats.new_scans == 2
    assert stats.rescans == 0
    assert stats.in_assignment == 2
    assert stats.unknown_moons == []

    # Header + trailer should now be captured in meta
    assert user_db.get_meta_bytes(META_HEADER_BYTES) is not None

    # Pull stored chunks and reassemble
    chunks = user_db.get_all_scans_ordered(only_in_assignment=True)
    header = user_db.get_meta_bytes(META_HEADER_BYTES) or b""
    trailer = user_db.get_meta_bytes(META_TRAILER_BYTES) or b""
    rebuilt = build_export(chunks, header_bytes=header, trailer_bytes=trailer)

    assert rebuilt == original, (
        f"E2E mismatch.\n"
        f"  original: {original!r}\n"
        f"  rebuilt:  {rebuilt!r}"
    )


def test_rescan_overwrites_in_place(static_db, user_db):
    """User rescans a moon; we keep the most recent paste only."""
    user_db.set_assignment([30002490])
    first = (FIXTURES / "sample_paste_no_trailing.bin").read_bytes()
    stats1, _ = ingest_paste(first, user_db, static_db)
    assert stats1.new_scans == 2

    # Imagine the same moons re-pasted later (same bytes). Should be rescans.
    stats2, _ = ingest_paste(first, user_db, static_db)
    assert stats2.new_scans == 0
    assert stats2.rescans == 2
    # Total moons in DB still 2
    assert user_db.count_scans(only_in_assignment=False) == 2


def test_out_of_assignment_moons_stored_but_not_counted(static_db, user_db):
    """Moons outside our assigned systems get stored but don't count toward goal."""
    # Assign a completely different system (one that's not PYY3-5)
    user_db.set_assignment([30000142])  # Jita, some other system
    data = (FIXTURES / "sample_paste_no_trailing.bin").read_bytes()
    stats, _ = ingest_paste(data, user_db, static_db)
    assert stats.moons_in_paste == 2
    assert stats.in_assignment == 0
    assert stats.out_of_assignment == 2
    # Stored, just flagged
    assert user_db.count_scans(only_in_assignment=False) == 2
    assert user_db.count_scans(only_in_assignment=True) == 0
