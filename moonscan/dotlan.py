"""
Dotlan SVG integration.

Downloads region maps from evemaps.dotlan.net, caches them on disk, parses
out system positions/IDs, and rewrites system fill colors based on the
user's scan progress before rendering.

Dotlan's SVG layout (verified against /svg/Geminate.svg):
    <use id="sys<system_id>" x=".." y=".." width=".." height=".."
         xlink:href="#def<system_id>" />
    <symbol id="def<system_id>">
        <a xlink:href="http://evemaps.dotlan.net/system/<NAME>">
            <rect id="ice<system_id>" ... class="i" />
            <rect id="rect<system_id>" ... class="s" style="fill: #COLOR;" />
            <text x=".." y=".." class="ss">SYSTEM_NAME</text>
            ...
        </a>
    </symbol>

Cache location: <user_data_dir>/dotlan_cache/<RegionName>.svg
Default TTL: 7 days (system positions never change; the only thing that
shifts is sovereignty coloring, which we override anyway).

Per dotlan's terms, this is a personal tool that fetches each region SVG
once per week per user. We send a descriptive User-Agent so Wollari can
identify our traffic.
"""
from __future__ import annotations

import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .paths import user_data_dir

log = logging.getLogger(__name__)

DOTLAN_BASE = "https://evemaps.dotlan.net"
USER_AGENT = "MoonScan/1.0 (alliance moon-scan tracker; contact via Anthropic Claude)"
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


@dataclass
class SystemBox:
    """Bounding box of a system on the SVG, in SVG coordinates."""
    system_id: int
    x: float
    y: float
    width: float
    height: float

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2


def _region_filename(region_name: str) -> str:
    """Dotlan uses underscores for spaces: 'The Forge' → 'The_Forge'."""
    return region_name.replace(" ", "_")


def _cache_dir() -> Path:
    d = user_data_dir() / "dotlan_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(region_name: str) -> Path:
    return _cache_dir() / f"{_region_filename(region_name)}.svg"


def _is_cache_fresh(path: Path, ttl_seconds: int = CACHE_TTL_SECONDS) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < ttl_seconds


def fetch_region_svg(
    region_name: str,
    force_refresh: bool = False,
    timeout: float = 15.0,
) -> bytes:
    """Return the SVG bytes for `region_name`, downloading if necessary.

    Cached at <user_data_dir>/dotlan_cache/<Region>.svg. If the cache exists
    and we hit a network error, we fall back to the stale copy with a log
    warning rather than blowing up.

    Raises RuntimeError if no SVG is available (no cache + network failure).
    """
    path = _cache_path(region_name)
    if not force_refresh and _is_cache_fresh(path):
        return path.read_bytes()

    url = f"{DOTLAN_BASE}/svg/{_region_filename(region_name)}.svg"
    log.info("Fetching dotlan SVG: %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if not data or b"<svg" not in data[:200]:
            raise RuntimeError(f"Dotlan returned unexpected content for {region_name}")
        path.write_bytes(data)
        return data
    except (urllib.error.URLError, OSError, RuntimeError) as e:
        if path.exists():
            log.warning("Dotlan fetch failed (%s); using stale cache", e)
            return path.read_bytes()
        raise RuntimeError(
            f"Could not download dotlan map for {region_name} and no cached "
            f"copy is available. Check your internet connection. ({e})"
        ) from e


# ---------------------------------------------------------------------------
# SVG parsing — we use regex rather than XML parsing because dotlan's SVG has
# some tricky parts (CDATA sections, XML processing instructions) that trip
# up lxml/ElementTree, and the structure is very regular.
# ---------------------------------------------------------------------------

# <use id="sys30002490" x="123" y="456" width="62.5" height="30" ...
_RE_USE = re.compile(
    rb'<use\s+id="sys(\d+)"\s+x="([\d.\-]+)"\s+y="([\d.\-]+)"'
    rb'\s+width="([\d.\-]+)"\s+height="([\d.\-]+)"',
    re.IGNORECASE,
)

# We also need the SVG's viewBox / width / height for the QGraphicsView
_RE_VIEWBOX = re.compile(rb'viewBox="([\d.\-\s]+)"', re.IGNORECASE)
_RE_WIDTH = re.compile(rb'<svg\b[^>]*\bwidth="([\d.]+)"', re.IGNORECASE)
_RE_HEIGHT = re.compile(rb'<svg\b[^>]*\bheight="([\d.]+)"', re.IGNORECASE)


def parse_system_positions(svg: bytes) -> dict[int, SystemBox]:
    """Return {system_id: SystemBox} for every system in the SVG."""
    out: dict[int, SystemBox] = {}
    for m in _RE_USE.finditer(svg):
        sid = int(m.group(1))
        out[sid] = SystemBox(
            system_id=sid,
            x=float(m.group(2)),
            y=float(m.group(3)),
            width=float(m.group(4)),
            height=float(m.group(5)),
        )
    return out


def parse_viewbox(svg: bytes) -> tuple[float, float, float, float]:
    """Return (min_x, min_y, width, height) of the SVG viewBox.
    Falls back to width/height attributes if no viewBox is present.
    """
    m = _RE_VIEWBOX.search(svg)
    if m:
        parts = m.group(1).split()
        if len(parts) == 4:
            return tuple(float(p) for p in parts)  # type: ignore[return-value]
    w_m = _RE_WIDTH.search(svg)
    h_m = _RE_HEIGHT.search(svg)
    w = float(w_m.group(1)) if w_m else 1024.0
    h = float(h_m.group(1)) if h_m else 768.0
    return (0.0, 0.0, w, h)


# ---------------------------------------------------------------------------
# Recoloring — we override the fill on each system's main rect.
# ---------------------------------------------------------------------------

def recolor_systems(svg: bytes, color_by_system: dict[int, str]) -> bytes:
    """Return a new SVG with system rects re-filled per `color_by_system`.

    `color_by_system` maps system_id → CSS color string (e.g. "#cf4747").
    Systems not in the map are left at dotlan's default sovereignty color.

    Also strips <image> elements that reference external dotlan icon URLs
    (zoom buttons, etc.) so QSvgRenderer doesn't try to fetch them at render
    time.
    """
    # Strip remote <image href="https://i.dotlan.net/..."> elements
    svg = re.sub(
        rb'<image\b[^>]*\b(?:xlink:)?href="https?://[^"]+"[^/]*/>',
        b'',
        svg,
    )

    if not color_by_system:
        return svg

    def replacer(match: re.Match[bytes]) -> bytes:
        sid = int(match.group(1))
        color = color_by_system.get(sid)
        if color is None:
            return match.group(0)
        # group 0 = the entire <rect id="rect{sid}" ... style="fill: XYZ;" .../>
        # Replace the fill: portion of the style attribute.
        full = match.group(0)
        new_full = re.sub(
            rb'fill:\s*#[0-9A-Fa-f]+;?',
            f'fill: {color};'.encode("ascii"),
            full,
            count=1,
        )
        # If there was no fill in the style, inject one
        if new_full == full:
            new_full = re.sub(
                rb'(style=")',
                rb'\1fill: ' + color.encode("ascii") + rb'; ',
                full,
                count=1,
            )
        return new_full

    # Match: <rect id="rect<system_id>" ... class="s" ... style="..." ... />
    pattern = re.compile(
        rb'<rect\s+id="rect(\d+)"[^>]*\sclass="s"[^>]*/>',
        re.IGNORECASE,
    )
    return pattern.sub(replacer, svg)


def progress_color(scanned: int, total: int) -> str | None:
    """Return a CSS color string for a system based on its scan progress,
    or None to leave dotlan's default color in place."""
    if total <= 0:
        return None
    if scanned == 0:
        return "#cf4747"  # red — none scanned
    if scanned >= total:
        return "#4daf68"  # green — complete
    return "#d4a23a"      # yellow — partial


def constellation_bounding_box(
    positions: dict[int, SystemBox],
    system_ids_in_constellation: set[int],
    padding: float = 50.0,
) -> tuple[float, float, float, float] | None:
    """Compute a bounding box (x, y, w, h) covering all systems in the given
    constellation. Used to auto-zoom into KR-XF4 within the Geminate SVG."""
    boxes = [
        positions[sid] for sid in system_ids_in_constellation
        if sid in positions
    ]
    if not boxes:
        return None
    xmin = min(b.x for b in boxes) - padding
    xmax = max(b.x + b.width for b in boxes) + padding
    ymin = min(b.y for b in boxes) - padding
    ymax = max(b.y + b.height for b in boxes) + padding
    return (xmin, ymin, xmax - xmin, ymax - ymin)
