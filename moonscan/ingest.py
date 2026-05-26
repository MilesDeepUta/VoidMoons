"""
Pipeline: clipboard bytes → parsed moons → user DB.

This is the only module that ever writes to scans / scan_ores.
Keeps the parser pure and the DB layer simple.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .db import UserDB, META_HEADER_BYTES, META_TRAILER_BYTES
from .parser import ParseResult, parse
from .static_db import StaticDB


@dataclass
class IngestStats:
    moons_in_paste: int = 0
    new_scans: int = 0           # moons we'd never seen before
    rescans: int = 0             # moons we'd already scanned
    in_assignment: int = 0       # of these moons, how many count toward our goal
    out_of_assignment: int = 0
    unknown_moons: list[int] = None     # moon_ids that aren't in the SDE (shouldn't happen)
    unrecognized_lines: int = 0

    def __post_init__(self):
        if self.unknown_moons is None:
            self.unknown_moons = []


def ingest_paste(
    raw: bytes,
    user_db: UserDB,
    static_db: StaticDB,
) -> tuple[IngestStats, ParseResult]:
    """Parse `raw` clipboard bytes and store all moons into the user DB.

    Returns (stats, parse_result) so the UI can surface details to the user.
    """
    result = parse(raw)
    stats = IngestStats(
        moons_in_paste=len(result.moons),
        unrecognized_lines=len(result.unrecognized_lines),
    )

    # Capture format-of-paste bytes the FIRST time we see a real paste,
    # so future exports use the exact same header/trailer.
    if result.header_bytes and user_db.get_meta_bytes(META_HEADER_BYTES) is None:
        user_db.set_meta_bytes(META_HEADER_BYTES, result.header_bytes)
    if result.trailer_bytes and user_db.get_meta_bytes(META_TRAILER_BYTES) is None:
        user_db.set_meta_bytes(META_TRAILER_BYTES, result.trailer_bytes)

    assigned_systems = set(user_db.get_assigned_system_ids())
    previously_scanned = user_db.get_scanned_moon_ids()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for m in result.moons:
        sde_moon = static_db.moon(m.moon_id)
        if sde_moon is None:
            stats.unknown_moons.append(m.moon_id)
            # Still store the scan — data preservation matters more than name knowledge
            in_assignment = False
        else:
            in_assignment = sde_moon["system_id"] in assigned_systems

        user_db.upsert_scan(
            moon_id=m.moon_id,
            scanned_at=now,
            raw_chunk=m.raw_chunk,
            in_assignment=in_assignment,
            ores=[(o.name, o.ore_type_id, o.quantity) for o in m.ores],
        )

        if m.moon_id in previously_scanned:
            stats.rescans += 1
        else:
            stats.new_scans += 1
        if in_assignment:
            stats.in_assignment += 1
        else:
            stats.out_of_assignment += 1

    return stats, result
