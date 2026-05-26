"""
Critical correctness tests: parser + export round-trip must be byte-perfect.

These tests pin down the "export looks identical to what EVE produced"
requirement. If any of them ever fail, the alliance parser may reject our
output.
"""
from pathlib import Path

import pytest

from moonscan.parser import parse, looks_like_scan
from moonscan.export import build_export

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---------- core round-trip ----------

@pytest.mark.parametrize("fixture", [
    "sample_paste_no_trailing.bin",
    "sample_paste_with_trailing.bin",
    "sample_paste_lf.bin",
])
def test_round_trip_byte_exact(fixture):
    """The fundamental guarantee: parse → export reproduces input exactly."""
    original = _load(fixture)
    result = parse(original)
    rebuilt = build_export(
        chunks=[(m.moon_id, m.raw_chunk) for m in result.moons],
        header_bytes=result.header_bytes,
        trailer_bytes=result.trailer_bytes,
    )
    assert rebuilt == original, (
        f"Round-trip mismatch on {fixture}:\n"
        f"  original ({len(original)} bytes): {original!r}\n"
        f"  rebuilt  ({len(rebuilt)} bytes): {rebuilt!r}"
    )


# ---------- parsing details ----------

def test_parses_two_moons_from_sample():
    data = _load("sample_paste_no_trailing.bin")
    result = parse(data)
    assert len(result.moons) == 2
    m0, m1 = result.moons

    assert m0.moon_id == 40158360
    assert m0.system_id == 30002490
    assert m0.planet_id == 40158359
    assert m0.moon_name == "PYY3-5 I - Moon 1"
    assert len(m0.ores) == 2
    assert m0.ores[0].name == "Bitumens"
    assert m0.ores[0].ore_type_id == 45492
    assert m0.ores[0].quantity == pytest.approx(0.314450025558)

    assert m1.moon_id == 40158367
    assert m1.moon_name == "PYY3-5 III - Moon 1"
    assert len(m1.ores) == 3
    ore_names = {o.name for o in m1.ores}
    assert ore_names == {"Bitumens", "Sylvite", "Zeolites"}


def test_raw_chunks_preserve_line_endings_crlf():
    """raw_chunk must contain CRLF bytes exactly as input had them."""
    data = _load("sample_paste_no_trailing.bin")
    result = parse(data)
    # Every chunk should end with \r\n except possibly the very last one
    # (depends on whether input had trailing newline).
    for m in result.moons[:-1]:
        assert m.raw_chunk.endswith(b"\r\n"), f"Chunk for moon {m.moon_id} lost CRLF"
    # All chunks should contain CRLF as inter-line separator (since LF doesn't appear)
    for m in result.moons:
        assert b"\r\n" in m.raw_chunk
        assert m.raw_chunk.count(b"\n") == m.raw_chunk.count(b"\r\n"), \
            "Mismatched bare LF found"


def test_raw_chunks_preserve_line_endings_lf():
    """LF-only input must produce LF-only chunks."""
    data = _load("sample_paste_lf.bin")
    result = parse(data)
    for m in result.moons:
        assert b"\r\n" not in m.raw_chunk, "Spurious CRLF introduced"
        assert m.raw_chunk.count(b"\n") >= 1


def test_header_captured_exactly():
    data = _load("sample_paste_no_trailing.bin")
    result = parse(data)
    expected_header = (
        b"Moon\tMoon Product\tQuantity\tOre TypeID\t"
        b"SolarSystemID\tPlanetID\tMoonID\r\n"
    )
    assert result.header_bytes == expected_header


def test_trailing_newline_captured_as_trailer():
    data = _load("sample_paste_with_trailing.bin")
    result = parse(data)
    # Either it's in the trailer or it's part of the last moon's chunk.
    # Round trip is the real test — but as a sanity check, total bytes accounted for.
    total = (
        len(result.header_bytes)
        + sum(len(m.raw_chunk) for m in result.moons)
        + len(result.trailer_bytes)
        + sum(len(l) for l in result.unrecognized_lines)
    )
    assert total == len(data), \
        f"Bytes lost: {len(data) - total} (input={len(data)}, accounted={total})"


# ---------- watcher heuristic ----------

def test_looks_like_scan_positive():
    data = _load("sample_paste_no_trailing.bin")
    assert looks_like_scan(data)


def test_looks_like_scan_negative():
    assert not looks_like_scan(b"")
    assert not looks_like_scan(b"just some text I copied earlier")
    assert not looks_like_scan(b"name\tnumber\nAlice\t42")  # tabs but wrong shape


# ---------- edge cases ----------

def test_parse_empty_input():
    result = parse(b"")
    assert result.moons == []
    assert result.header_bytes == b""


def test_parse_header_only():
    data = b"Moon\tMoon Product\tQuantity\tOre TypeID\tSolarSystemID\tPlanetID\tMoonID\r\n"
    result = parse(data)
    assert result.moons == []
    assert result.header_bytes == data


def test_parse_without_header():
    # In-game paste of a single moon's data with no header line
    data = (
        b"PYY3-5 I - Moon 1\r\n"
        b"\tBitumens\t0.314450025558\t45492\t30002490\t40158359\t40158360\r\n"
    )
    result = parse(data)
    assert result.header_bytes == b""
    assert len(result.moons) == 1
    assert result.moons[0].moon_id == 40158360
    # And the round-trip still works
    rebuilt = build_export(
        [(m.moon_id, m.raw_chunk) for m in result.moons],
        result.header_bytes, result.trailer_bytes,
    )
    assert rebuilt == data
