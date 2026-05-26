"""Read-only access to the shipped EVE static DB."""
from __future__ import annotations

import sqlite3
from pathlib import Path


class StaticDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    # ----- regions / constellations -----

    def all_regions(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT region_id, name FROM regions ORDER BY name"
        ).fetchall()

    def constellations_in_region(self, region_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT constellation_id, name FROM constellations "
            "WHERE region_id = ? ORDER BY name",
            (region_id,),
        ).fetchall()

    def region_of_constellation(self, constellation_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT r.region_id, r.name FROM regions r "
            "JOIN constellations c ON c.region_id = r.region_id "
            "WHERE c.constellation_id = ?",
            (constellation_id,),
        ).fetchone()

    def region(self, region_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT region_id, name FROM regions WHERE region_id = ?",
            (region_id,),
        ).fetchone()

    def constellation(self, constellation_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT constellation_id, name, region_id FROM constellations "
            "WHERE constellation_id = ?",
            (constellation_id,),
        ).fetchone()

    # ----- systems -----

    def systems_in_constellation(self, constellation_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT system_id, name, x, y, z, security_status FROM systems "
            "WHERE constellation_id = ? ORDER BY name",
            (constellation_id,),
        ).fetchall()

    def system(self, system_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT system_id, name, constellation_id, x, y, z, security_status "
            "FROM systems WHERE system_id = ?",
            (system_id,),
        ).fetchone()

    def stargates_in_constellation(self, constellation_id: int) -> list[tuple[int, int]]:
        """Return (system_a, system_b) pairs where BOTH endpoints are in the constellation,
        plus pairs where one endpoint is in and the other is out (caller can filter)."""
        rows = self._conn.execute(
            """
            SELECT g.system_a, g.system_b,
                   sa.constellation_id AS ca,
                   sb.constellation_id AS cb
              FROM stargates g
              JOIN systems sa ON sa.system_id = g.system_a
              JOIN systems sb ON sb.system_id = g.system_b
             WHERE sa.constellation_id = ? OR sb.constellation_id = ?
            """,
            (constellation_id, constellation_id),
        ).fetchall()
        return [(r["system_a"], r["system_b"]) for r in rows]

    # ----- planets / moons -----

    def planets_in_system(self, system_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT planet_id, planet_index, name FROM planets "
            "WHERE system_id = ? ORDER BY planet_index",
            (system_id,),
        ).fetchall()

    def moons_in_planet(self, planet_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT moon_id, moon_index, name FROM moons "
            "WHERE planet_id = ? ORDER BY moon_index",
            (planet_id,),
        ).fetchall()

    def planet(self, planet_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT planet_id, system_id, planet_index, name FROM planets "
            "WHERE planet_id = ?",
            (planet_id,),
        ).fetchone()

    def moons_in_system(self, system_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT m.moon_id, m.planet_id, m.moon_index, m.name,
                   p.planet_index
              FROM moons m
              JOIN planets p ON p.planet_id = m.planet_id
             WHERE p.system_id = ?
             ORDER BY p.planet_index, m.moon_index
            """,
            (system_id,),
        ).fetchall()

    def moons_in_constellation(self, constellation_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT m.moon_id, m.planet_id, m.moon_index, m.name,
                   p.planet_index, p.system_id, s.name AS system_name
              FROM moons m
              JOIN planets p ON p.planet_id = m.planet_id
              JOIN systems s ON s.system_id = p.system_id
             WHERE s.constellation_id = ?
             ORDER BY s.name, p.planet_index, m.moon_index
            """,
            (constellation_id,),
        ).fetchall()

    def moon(self, moon_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT m.moon_id, m.planet_id, m.moon_index, m.name AS name,
                   p.system_id, p.planet_index,
                   s.name AS system_name, s.constellation_id
              FROM moons m
              JOIN planets p ON p.planet_id = m.planet_id
              JOIN systems s ON s.system_id = p.system_id
             WHERE m.moon_id = ?
            """,
            (moon_id,),
        ).fetchone()

    def moon_ids_in_systems(self, system_ids: list[int]) -> set[int]:
        if not system_ids:
            return set()
        out: set[int] = set()
        CHUNK = 500
        for i in range(0, len(system_ids), CHUNK):
            chunk = system_ids[i:i + CHUNK]
            placeholders = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"""
                SELECT m.moon_id FROM moons m
                  JOIN planets p ON p.planet_id = m.planet_id
                 WHERE p.system_id IN ({placeholders})
                """,
                chunk,
            ).fetchall()
            out.update(r[0] for r in rows)
        return out

    # ----- 2D map helpers (depend on x_2d / y_2d in systems table) -----

    def region_positions(self) -> dict[int, tuple[float, float]]:
        """Return {region_id: (x_centroid, y_centroid)} computed from member
        systems' 2D coordinates. Regions with no 2D-positioned systems are
        omitted (e.g. wormhole regions)."""
        rows = self._conn.execute(
            """
            SELECT c.region_id, AVG(s.x_2d), AVG(s.y_2d)
              FROM systems s
              JOIN constellations c ON c.constellation_id = s.constellation_id
             WHERE s.x_2d IS NOT NULL AND s.y_2d IS NOT NULL
             GROUP BY c.region_id
            """
        ).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}

    def regions_with_positions(self) -> list[sqlite3.Row]:
        """All regions that have at least one 2D-positioned system."""
        return self._conn.execute(
            """
            SELECT DISTINCT r.region_id, r.name
              FROM regions r
              JOIN constellations c ON c.region_id = r.region_id
              JOIN systems s ON s.constellation_id = c.constellation_id
             WHERE s.x_2d IS NOT NULL
             ORDER BY r.name
            """
        ).fetchall()

    def region_connections(self) -> list[tuple[int, int]]:
        """Pairs of (region_a, region_b) where at least one stargate crosses
        the boundary. Returned as a deduplicated list with a < b."""
        rows = self._conn.execute(
            """
            SELECT DISTINCT
                MIN(ca.region_id, cb.region_id) AS r1,
                MAX(ca.region_id, cb.region_id) AS r2
              FROM stargates g
              JOIN systems sa ON sa.system_id = g.system_a
              JOIN systems sb ON sb.system_id = g.system_b
              JOIN constellations ca ON ca.constellation_id = sa.constellation_id
              JOIN constellations cb ON cb.constellation_id = sb.constellation_id
             WHERE ca.region_id != cb.region_id
            """
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def systems_in_region(self, region_id: int) -> list[sqlite3.Row]:
        """All systems in a region with their 2D coords + constellation."""
        return self._conn.execute(
            """
            SELECT s.system_id, s.name, s.constellation_id, s.x_2d, s.y_2d,
                   s.security_status
              FROM systems s
              JOIN constellations c ON c.constellation_id = s.constellation_id
             WHERE c.region_id = ?
             ORDER BY s.name
            """,
            (region_id,),
        ).fetchall()

    def stargates_in_region(self, region_id: int) -> list[tuple[int, int]]:
        """Stargate pairs where at least one endpoint is in `region_id`."""
        rows = self._conn.execute(
            """
            SELECT g.system_a, g.system_b
              FROM stargates g
              JOIN systems sa ON sa.system_id = g.system_a
              JOIN systems sb ON sb.system_id = g.system_b
              JOIN constellations ca ON ca.constellation_id = sa.constellation_id
              JOIN constellations cb ON cb.constellation_id = sb.constellation_id
             WHERE ca.region_id = ? OR cb.region_id = ?
            """,
            (region_id, region_id),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def system_2d(self, system_id: int) -> tuple[float, float] | None:
        row = self._conn.execute(
            "SELECT x_2d, y_2d FROM systems WHERE system_id = ?",
            (system_id,),
        ).fetchone()
        if row and row[0] is not None and row[1] is not None:
            return (row[0], row[1])
        return None
