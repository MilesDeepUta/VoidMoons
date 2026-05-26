"""
SDE builder.

Reads the EVE Static Data Export jsonl files (mapRegions, mapConstellations,
mapSolarSystems, mapPlanets, mapMoons, mapStargates) and produces a compact
SQLite database (eve_static.db) used by the moonscan app at runtime.

Moon and planet names are PRE-CONSTRUCTED here so the runtime app never has
to do Roman-numeral arithmetic. Run this once per SDE release.

Usage:
    python build_sde.py --src /path/to/jsonl/dir --out data/eve_static.db
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path


ROMAN = [
    "", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
    "XXI", "XXII", "XXIII", "XXIV", "XXV", "XXVI", "XXVII", "XXVIII", "XXIX", "XXX",
    "XXXI", "XXXII", "XXXIII", "XXXIV", "XXXV", "XXXVI", "XXXVII", "XXXVIII", "XXXIX", "XL",
]


def to_roman(n: int) -> str:
    """Convert 1..40 to Roman numerals. EVE planets don't exceed ~13."""
    if 0 < n < len(ROMAN):
        return ROMAN[n]
    # fallback for crazy cases
    vals = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    out = []
    for v, s in vals:
        while n >= v:
            out.append(s)
            n -= v
    return "".join(out)


def create_schema(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.executescript("""
        DROP TABLE IF EXISTS regions;
        DROP TABLE IF EXISTS constellations;
        DROP TABLE IF EXISTS systems;
        DROP TABLE IF EXISTS planets;
        DROP TABLE IF EXISTS moons;
        DROP TABLE IF EXISTS stargates;

        CREATE TABLE regions (
            region_id INTEGER PRIMARY KEY,
            name      TEXT NOT NULL
        );
        CREATE TABLE constellations (
            constellation_id INTEGER PRIMARY KEY,
            name             TEXT NOT NULL,
            region_id        INTEGER NOT NULL,
            FOREIGN KEY (region_id) REFERENCES regions(region_id)
        );
        CREATE TABLE systems (
            system_id        INTEGER PRIMARY KEY,
            name             TEXT NOT NULL,
            constellation_id INTEGER NOT NULL,
            x REAL, y REAL, z REAL,
            x_2d REAL, y_2d REAL,
            security_status  REAL,
            FOREIGN KEY (constellation_id) REFERENCES constellations(constellation_id)
        );
        CREATE TABLE planets (
            planet_id    INTEGER PRIMARY KEY,
            system_id    INTEGER NOT NULL,
            planet_index INTEGER NOT NULL,
            name         TEXT NOT NULL,   -- e.g. "Atioth III"
            FOREIGN KEY (system_id) REFERENCES systems(system_id)
        );
        CREATE TABLE moons (
            moon_id    INTEGER PRIMARY KEY,
            planet_id  INTEGER NOT NULL,
            moon_index INTEGER NOT NULL,
            name       TEXT NOT NULL,   -- e.g. "Atioth III - Moon 4"
            FOREIGN KEY (planet_id) REFERENCES planets(planet_id)
        );
        CREATE TABLE stargates (
            system_a INTEGER NOT NULL,
            system_b INTEGER NOT NULL,
            PRIMARY KEY (system_a, system_b)
        );

        CREATE INDEX idx_constellations_region ON constellations(region_id);
        CREATE INDEX idx_systems_constellation ON systems(constellation_id);
        CREATE INDEX idx_planets_system        ON planets(system_id);
        CREATE INDEX idx_moons_planet          ON moons(planet_id);
        CREATE INDEX idx_moons_name            ON moons(name);
    """)
    conn.commit()


def load_jsonl(path: Path):
    """Yield each JSON object from a .jsonl file."""
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def build(src_dir: Path, out_path: Path, pos2d_path: Path | None = None) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    conn = sqlite3.connect(out_path)
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA temp_store = MEMORY")
    create_schema(conn)
    c = conn.cursor()

    # --- Regions ---
    print("Loading regions...", file=sys.stderr)
    rows = [(r["_key"], r["name"]["en"]) for r in load_jsonl(src_dir / "mapRegions.jsonl")]
    c.executemany("INSERT INTO regions VALUES (?, ?)", rows)
    print(f"  {len(rows)} regions", file=sys.stderr)

    # --- Constellations ---
    print("Loading constellations...", file=sys.stderr)
    rows = [
        (cn["_key"], cn["name"]["en"], cn["regionID"])
        for cn in load_jsonl(src_dir / "mapConstellations.jsonl")
    ]
    c.executemany("INSERT INTO constellations VALUES (?, ?, ?)", rows)
    print(f"  {len(rows)} constellations", file=sys.stderr)

    # --- 2D positions (optional) ---
    pos2d_map: dict[int, tuple[float, float]] = {}
    if pos2d_path and pos2d_path.exists():
        print(f"Loading 2D positions from {pos2d_path}...", file=sys.stderr)
        with pos2d_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for sid_str, rec in data.items():
            x2d = rec.get("x")
            y2d = rec.get("y")
            if x2d is not None and y2d is not None:
                pos2d_map[int(sid_str)] = (float(x2d), float(y2d))
        print(f"  {len(pos2d_map)} systems with 2D coords", file=sys.stderr)

    # --- Systems ---
    print("Loading systems...", file=sys.stderr)
    rows = []
    for s in load_jsonl(src_dir / "mapSolarSystems.jsonl"):
        pos = s.get("position") or {}
        sid = s["_key"]
        x2d, y2d = pos2d_map.get(sid, (None, None))
        rows.append((
            sid, s["name"]["en"], s["constellationID"],
            pos.get("x"), pos.get("y"), pos.get("z"),
            x2d, y2d,
            s.get("securityStatus"),
        ))
    c.executemany("INSERT INTO systems VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    print(f"  {len(rows)} systems", file=sys.stderr)

    # --- Planets: need system name to construct planet name ---
    print("Loading planets...", file=sys.stderr)
    system_names = dict(c.execute("SELECT system_id, name FROM systems"))
    rows = []
    for p in load_jsonl(src_dir / "mapPlanets.jsonl"):
        sys_name = system_names.get(p["solarSystemID"])
        if sys_name is None:
            continue  # orphan planet, skip
        idx = p["celestialIndex"]
        rows.append((p["_key"], p["solarSystemID"], idx, f"{sys_name} {to_roman(idx)}"))
    c.executemany("INSERT INTO planets VALUES (?, ?, ?, ?)", rows)
    print(f"  {len(rows)} planets", file=sys.stderr)

    # --- Moons: name = "<planet_name> - Moon <n>".  Index within parent planet. ---
    # We need to assign each moon its index within its parent planet's moonIDs list,
    # because the moon record's own celestialIndex/orbitIndex are not the moon number.
    print("Building moon index map from planets...", file=sys.stderr)
    moon_to_index = {}  # moonID -> moon number (1-based)
    for p in load_jsonl(src_dir / "mapPlanets.jsonl"):
        for i, mid in enumerate(p.get("moonIDs") or [], start=1):
            moon_to_index[mid] = i

    print("Loading moons...", file=sys.stderr)
    planet_names = dict(c.execute("SELECT planet_id, name FROM planets"))
    rows = []
    for m in load_jsonl(src_dir / "mapMoons.jsonl"):
        pid = m["orbitID"]
        planet_name = planet_names.get(pid)
        if planet_name is None:
            continue  # orphan moon
        idx = moon_to_index.get(m["_key"])
        if idx is None:
            # Fall back to orbitIndex if not in any planet's list (shouldn't happen)
            idx = m.get("orbitIndex", 1)
        rows.append((m["_key"], pid, idx, f"{planet_name} - Moon {idx}"))
    c.executemany("INSERT INTO moons VALUES (?, ?, ?, ?)", rows)
    print(f"  {len(rows)} moons", file=sys.stderr)

    # --- Stargates: dedupe pairs ---
    print("Loading stargates...", file=sys.stderr)
    pairs = set()
    for g in load_jsonl(src_dir / "mapStargates.jsonl"):
        a = g["solarSystemID"]
        b = g["destination"]["solarSystemID"]
        if a > b:
            a, b = b, a
        pairs.add((a, b))
    c.executemany("INSERT INTO stargates VALUES (?, ?)", list(pairs))
    print(f"  {len(pairs)} stargate links", file=sys.stderr)

    conn.commit()
    conn.execute("VACUUM")
    conn.close()

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\nWrote {out_path} ({size_mb:.1f} MB)", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=".", help="Directory containing the jsonl files")
    ap.add_argument("--out", default="data/eve_static.db", help="Output SQLite path")
    ap.add_argument("--pos2d", default="data/position2d.json",
                    help="Optional JSON file with system 2D coordinates")
    args = ap.parse_args()
    pos2d = Path(args.pos2d) if args.pos2d else None
    build(Path(args.src), Path(args.out), pos2d_path=pos2d)


if __name__ == "__main__":
    main()
