"""
Parse EVE moon survey paste data while preserving the original bytes
EXACTLY for each moon's chunk. This is the source of truth for the
"export must be byte-identical to in-game paste" guarantee.

The EVE format is tab-separated lines:

    Moon\tMoon Product\tQuantity\tOre TypeID\tSolarSystemID\tPlanetID\tMoonID
    <moon_name>
    \t<ore_name>\t<quantity>\t<ore_type_id>\t<system_id>\t<planet_id>\t<moon_id>
    \t<ore_name>\t<quantity>\t<ore_type_id>\t<system_id>\t<planet_id>\t<moon_id>
    <moon_name>
    \t...

We work in bytes throughout. The "name line" of a moon section is identified
by NOT starting with a tab byte (0x09). The ore lines under it start with tab.
The chunk for a moon = the bytes of its name line + all of its ore lines,
preserving their original line endings exactly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

TAB = b"\t"
LF = b"\n"
CR = b"\r"

# Recognized header signature (case-insensitive on the first field name)
HEADER_PREFIX = b"Moon\tMoon Product"


@dataclass
class OreRecord:
    name: str           # "Bitumens"
    quantity: float     # 0.314450025558
    ore_type_id: int
    system_id: int
    planet_id: int
    moon_id: int


@dataclass
class MoonRecord:
    moon_id: int
    system_id: int
    planet_id: int
    moon_name: str
    ores: list[OreRecord]
    raw_chunk: bytes    # exact bytes of this moon's section, EOL-preserved


@dataclass
class ParseResult:
    moons: list[MoonRecord]
    header_bytes: bytes     # the header line + its line ending, or b"" if absent
    trailer_bytes: bytes    # anything after the last moon's chunk
    unrecognized_lines: list[bytes]  # lines we couldn't classify


def looks_like_scan(data: bytes) -> bool:
    """Cheap heuristic for clipboard watcher — does this look like a moon paste?"""
    if not data:
        return False
    # Has tabs, has at least one line matching the ore-line shape
    # (tab-leading, 7 tab-separated fields total when including the leading tab,
    # last field is a numeric moon_id).
    if TAB not in data:
        return False
    # find any ore-shaped line: starts with \t, has 6 more tabs, ends with digits
    pattern = re.compile(rb"(?m)^\t[^\t\r\n]+\t[\d.]+\t\d+\t\d+\t\d+\t\d+\s*$")
    return bool(pattern.search(data))


def _split_lines_keep_endings(data: bytes) -> list[bytes]:
    """Split bytes into lines, each line retaining its original \\n / \\r\\n.
    The final line may have no trailing newline."""
    out: list[bytes] = []
    i = 0
    n = len(data)
    start = 0
    while i < n:
        b = data[i:i + 1]
        if b == LF:
            out.append(data[start:i + 1])
            i += 1
            start = i
        elif b == CR:
            # CRLF or lone CR
            if i + 1 < n and data[i + 1:i + 2] == LF:
                out.append(data[start:i + 2])
                i += 2
            else:
                out.append(data[start:i + 1])
                i += 1
            start = i
        else:
            i += 1
    if start < n:
        out.append(data[start:])  # trailing line with no EOL
    return out


def parse(data: bytes) -> ParseResult:
    """Parse a moon scan paste. Pure / no side effects.

    Returns ParseResult where each MoonRecord.raw_chunk is the EXACT bytes
    of the lines belonging to that moon (its name line + its ore lines),
    with original line endings preserved.

    If the input does not start with a header line, header_bytes will be b"".
    Trailer bytes are anything left over after the last classified chunk
    (typically empty, but could be a trailing newline-only line).
    """
    lines = _split_lines_keep_endings(data)
    if not lines:
        return ParseResult(moons=[], header_bytes=b"", trailer_bytes=b"", unrecognized_lines=[])

    header_bytes = b""
    i = 0
    # Optional header line
    if lines[0].lstrip().startswith(HEADER_PREFIX):
        header_bytes = lines[0]
        i = 1

    moons: list[MoonRecord] = []
    unrecognized: list[bytes] = []
    current_name_line: bytes | None = None
    current_chunk_parts: list[bytes] = []
    current_ores: list[OreRecord] = []
    current_moon_id: int | None = None
    current_system_id: int | None = None
    current_planet_id: int | None = None
    current_name_str: str = ""

    def flush_current():
        nonlocal current_name_line, current_chunk_parts, current_ores
        nonlocal current_moon_id, current_system_id, current_planet_id, current_name_str
        if current_moon_id is not None:
            moons.append(MoonRecord(
                moon_id=current_moon_id,
                system_id=current_system_id or 0,
                planet_id=current_planet_id or 0,
                moon_name=current_name_str,
                ores=current_ores,
                raw_chunk=b"".join(current_chunk_parts),
            ))
        current_name_line = None
        current_chunk_parts = []
        current_ores = []
        current_moon_id = None
        current_system_id = None
        current_planet_id = None
        current_name_str = ""

    while i < len(lines):
        line = lines[i]
        # Strip just the EOL to inspect content
        stripped = line.rstrip(b"\r\n")
        if not stripped:
            # Blank line. If we're inside a moon chunk we treat it as trailer-y;
            # most EVE pastes don't include blank lines mid-data.
            unrecognized.append(line)
            i += 1
            continue

        if stripped.startswith(TAB):
            # Ore line. Must belong to a current moon.
            try:
                ore = _parse_ore_line(stripped)
            except ValueError:
                unrecognized.append(line)
                i += 1
                continue
            if current_moon_id is None and current_name_line is None:
                # Truly orphan ore line (no name line preceded it).
                # Start a synthetic moon section from the ore's IDs.
                current_moon_id = ore.moon_id
                current_system_id = ore.system_id
                current_planet_id = ore.planet_id
                current_name_str = ""
                current_chunk_parts = []
            elif current_moon_id is None and current_name_line is not None:
                # First ore line after a name line — adopt this ore's moon_id.
                # KEEP the chunk_parts (already contains the name line).
                current_moon_id = ore.moon_id
                current_system_id = ore.system_id
                current_planet_id = ore.planet_id
            elif ore.moon_id != current_moon_id:
                # Ore line jumped to a different moon without a name line.
                flush_current()
                current_moon_id = ore.moon_id
                current_system_id = ore.system_id
                current_planet_id = ore.planet_id
                current_name_str = ""
            current_chunk_parts.append(line)
            current_ores.append(ore)
        else:
            # Non-tab line = moon name line. Flush any in-progress moon.
            flush_current()
            current_name_line = line
            current_chunk_parts.append(line)
            current_name_str = stripped.decode("utf-8", errors="replace")
        i += 1

    flush_current()

    # Anything left in unrecognized_lines AFTER the last moon counts as trailer,
    # but only the contiguous tail. Leading unrecognized lines remain.
    trailer = b""
    # We don't try to reconstruct positional trailer here because we always
    # captured ore/name lines as part of moon chunks. If there are blank lines
    # at the end of input, those would be in `unrecognized`. Pull contiguous
    # trailing blanks into trailer_bytes.
    trailing_blanks: list[bytes] = []
    while unrecognized and unrecognized[-1].strip() == b"":
        trailing_blanks.insert(0, unrecognized.pop())
    trailer = b"".join(trailing_blanks)

    return ParseResult(
        moons=moons,
        header_bytes=header_bytes,
        trailer_bytes=trailer,
        unrecognized_lines=unrecognized,
    )


def _parse_ore_line(stripped: bytes) -> OreRecord:
    """Parse a single ore line (without its trailing newline)."""
    # Format: \t<ore_name>\t<quantity>\t<type_id>\t<system_id>\t<planet_id>\t<moon_id>
    fields = stripped.split(TAB)
    # First field is empty (the leading tab); we expect 7 fields total.
    if len(fields) != 7 or fields[0] != b"":
        raise ValueError(f"ore line wrong field count: {fields!r}")
    try:
        return OreRecord(
            name=fields[1].decode("utf-8"),
            quantity=float(fields[2]),
            ore_type_id=int(fields[3]),
            system_id=int(fields[4]),
            planet_id=int(fields[5]),
            moon_id=int(fields[6].rstrip()),
        )
    except (UnicodeDecodeError, ValueError) as e:
        raise ValueError(f"ore line parse failed: {e}") from e
