"""
Main application window.

Drill-down navigation:
    Universe (regions) → Region (systems) → Constellation (systems)
                       → System (planets) → Planet (moons + ores)

Breadcrumbs at the top of every page let you jump back up any level.
The default landing view is the user's assigned constellation, because that's
where their work happens; the universe and region levels are reachable through
the breadcrumb's "Universe" link or by clicking neighbouring constellations
on the region map.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QLabel, QMainWindow, QMessageBox, QStackedWidget, QStatusBar, QToolBar,
    QVBoxLayout, QWidget,
)

from .. import theme
from ..clipboard import ClipboardWatcher
from ..db import UserDB
from ..ingest import IngestStats, ingest_paste
from ..static_db import StaticDB
from .dialogs.export_dialog import ExportDialog
from .dialogs.paste_dialog import PasteDialog
from .dialogs.settings_dialog import SettingsDialog
from .views.map_view import (
    ConstellationMapView, RegionMapView, UniverseMapView,
)
from .views.moon_list import MoonListView
from .views.system_view import SystemView


PAGE_UNIVERSE      = 0
PAGE_REGION        = 1
PAGE_CONSTELLATION = 2
PAGE_SYSTEM        = 3
PAGE_MOONS         = 4
PAGE_STRANGERS     = 5


class MainWindow(QMainWindow):
    def __init__(self, user_db: UserDB, static_db: StaticDB):
        super().__init__()
        self.user_db = user_db
        self.static_db = static_db
        self.setWindowTitle("MoonScan")
        self.resize(1280, 820)

        self._watcher_interval_ms = 500
        self._watcher = ClipboardWatcher(self._watcher_interval_ms, self)
        self._watcher.scan_detected.connect(self._on_clipboard_scan_detected)

        # --- toolbar ---
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        universe_act = QAction("Universe", self)
        universe_act.triggered.connect(self._show_universe)
        toolbar.addAction(universe_act)

        home_act = QAction("Home", self)
        home_act.setShortcut(QKeySequence("Ctrl+H"))
        home_act.triggered.connect(self._show_home)
        toolbar.addAction(home_act)

        toolbar.addSeparator()

        paste_act = QAction("Paste Scan", self)
        paste_act.setShortcut(QKeySequence("Ctrl+V"))
        paste_act.triggered.connect(self._open_paste_dialog)
        toolbar.addAction(paste_act)

        self.watch_act = QAction("Watch Clipboard: OFF", self)
        self.watch_act.setCheckable(True)
        self.watch_act.toggled.connect(self._toggle_watcher)
        toolbar.addAction(self.watch_act)

        toolbar.addSeparator()

        export_act = QAction("Export for Alliance", self)
        export_act.triggered.connect(self._open_export_dialog)
        toolbar.addAction(export_act)

        toolbar.addSeparator()

        strangers_act = QAction("Stranger Moons", self)
        strangers_act.triggered.connect(self._show_strangers)
        toolbar.addAction(strangers_act)

        settings_act = QAction("Settings", self)
        settings_act.triggered.connect(self._open_settings)
        toolbar.addAction(settings_act)

        # --- breadcrumb ---
        self.breadcrumb = QLabel("")
        self.breadcrumb.setTextFormat(Qt.TextFormat.RichText)
        self.breadcrumb.setStyleSheet(
            f"padding: 8px 12px; background: {theme.BG_ALT.name()}; "
            f"border-bottom: 1px solid {theme.BORDER.name()};"
        )
        self.breadcrumb.linkActivated.connect(self._on_breadcrumb_link)

        # --- views ---
        self.universe_view = UniverseMapView(static_db)
        self.region_view = RegionMapView(static_db)
        self.constellation_view = ConstellationMapView(static_db)
        self.system_view = SystemView(static_db, user_db)
        self.moon_list = MoonListView(static_db, user_db)
        self.stranger_view = MoonListView(static_db, user_db)

        self.universe_view.node_clicked.connect(self._open_region)
        self.region_view.node_clicked.connect(self._open_constellation_from_system)
        self.constellation_view.node_clicked.connect(self._open_system)
        self.system_view.planet_clicked.connect(self._open_planet)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.universe_view)        # PAGE_UNIVERSE
        self.stack.addWidget(self.region_view)          # PAGE_REGION
        self.stack.addWidget(self.constellation_view)   # PAGE_CONSTELLATION
        self.stack.addWidget(self.system_view)          # PAGE_SYSTEM
        self.stack.addWidget(self.moon_list)            # PAGE_MOONS
        self.stack.addWidget(self.stranger_view)        # PAGE_STRANGERS

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.breadcrumb)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        # --- status bar ---
        self.setStatusBar(QStatusBar(self))
        self.progress_label = QLabel("")
        self.statusBar().addPermanentWidget(self.progress_label)

        # --- nav state ---
        self._current_region_id: int | None = None
        self._current_constellation_id: int | None = None
        self._current_system_id: int | None = None
        self._current_planet_id: int | None = None

        self._refresh_progress()
        self._show_home()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _show_home(self) -> None:
        """Show the user's assigned constellation map, or universe if no assignment."""
        const_id = self.user_db.get_constellation_id()
        if const_id is None:
            self._show_universe()
            return
        self._open_constellation(const_id)

    def _show_universe(self) -> None:
        user_region_id = self._user_region_id()
        self.universe_view.show_universe(user_region_id=user_region_id)
        crumb_parts = ["<b>Universe</b>"]
        self._set_breadcrumb(crumb_parts)
        self.stack.setCurrentIndex(PAGE_UNIVERSE)

    def _open_region(self, region_id: int) -> None:
        """Show all systems in a region."""
        self._current_region_id = region_id
        scan_counts = self._compute_scan_counts_for_region(region_id)
        user_const_id = self.user_db.get_constellation_id()
        # Only highlight the user's constellation if it's IN this region
        if user_const_id is not None:
            user_const_row = self.static_db.constellation(user_const_id)
            if user_const_row is None or user_const_row["region_id"] != region_id:
                user_const_id = None
        self.region_view.show_region(
            region_id,
            user_constellation_id=user_const_id,
            scan_counts=scan_counts,
            assigned_system_ids=set(self.user_db.get_assigned_system_ids()),
        )
        region_row = self.static_db.region(region_id)
        region_name = region_row["name"] if region_row else f"({region_id})"
        crumb_parts = [
            '<a href="universe">Universe</a>',
            f"<b>{region_name}</b>",
        ]
        self._set_breadcrumb(crumb_parts)
        self.stack.setCurrentIndex(PAGE_REGION)

    def _open_constellation_from_system(self, system_id: int) -> None:
        """User clicked a system on the region map → open its constellation."""
        sys_row = self.static_db.system(system_id)
        if sys_row is None:
            return
        self._open_constellation(sys_row["constellation_id"])

    def _open_constellation(self, constellation_id: int) -> None:
        self._current_constellation_id = constellation_id
        const_row = self.static_db.constellation(constellation_id)
        if const_row is None:
            return
        region_id = const_row["region_id"]
        self._current_region_id = region_id

        scan_counts = self._compute_scan_counts_for_constellation(constellation_id)
        assigned = set(self.user_db.get_assigned_system_ids())
        self.constellation_view.show_constellation(constellation_id, scan_counts, assigned)

        region_row = self.static_db.region(region_id)
        region_name = region_row["name"] if region_row else "?"
        crumb_parts = [
            '<a href="universe">Universe</a>',
            f'<a href="region:{region_id}">{region_name}</a>',
            f"<b>{const_row['name']}</b>",
        ]
        self._set_breadcrumb(crumb_parts)
        self.stack.setCurrentIndex(PAGE_CONSTELLATION)

    def _open_system(self, system_id: int) -> None:
        self._current_system_id = system_id
        self.system_view.show_system(system_id)
        sys_row = self.static_db.system(system_id)
        if sys_row is None:
            return
        const_row = self.static_db.constellation(sys_row["constellation_id"])
        region_id = const_row["region_id"] if const_row else None
        region_row = self.static_db.region(region_id) if region_id is not None else None
        crumb_parts = ['<a href="universe">Universe</a>']
        if region_row:
            crumb_parts.append(f'<a href="region:{region_row["region_id"]}">{region_row["name"]}</a>')
        if const_row:
            crumb_parts.append(
                f'<a href="constellation:{const_row["constellation_id"]}">{const_row["name"]}</a>'
            )
        crumb_parts.append(f"<b>{sys_row['name']}</b>")
        self._set_breadcrumb(crumb_parts)
        self.stack.setCurrentIndex(PAGE_SYSTEM)

    def _open_planet(self, planet_id: int) -> None:
        self._current_planet_id = planet_id
        self.moon_list.show_planet(planet_id)
        planet_row = self.static_db.planet(planet_id)
        sys_row = (
            self.static_db.system(self._current_system_id)
            if self._current_system_id else None
        )
        const_row = (
            self.static_db.constellation(sys_row["constellation_id"])
            if sys_row else None
        )
        region_row = (
            self.static_db.region(const_row["region_id"])
            if const_row else None
        )

        crumb_parts = ['<a href="universe">Universe</a>']
        if region_row:
            crumb_parts.append(f'<a href="region:{region_row["region_id"]}">{region_row["name"]}</a>')
        if const_row:
            crumb_parts.append(
                f'<a href="constellation:{const_row["constellation_id"]}">{const_row["name"]}</a>'
            )
        if sys_row:
            crumb_parts.append(
                f'<a href="system:{sys_row["system_id"]}">{sys_row["name"]}</a>'
            )
        if planet_row:
            crumb_parts.append(f"<b>{planet_row['name']}</b>")
        self._set_breadcrumb(crumb_parts)
        self.stack.setCurrentIndex(PAGE_MOONS)

    def _show_strangers(self) -> None:
        self.stranger_view.show_stranger_moons()
        self._set_breadcrumb([
            '<a href="universe">Universe</a>',
            "<b>Stranger Moons</b>",
        ])
        self.stack.setCurrentIndex(PAGE_STRANGERS)

    def _set_breadcrumb(self, parts: list[str]) -> None:
        self.breadcrumb.setText(" › ".join(parts))

    def _on_breadcrumb_link(self, link: str) -> None:
        if link == "universe":
            self._show_universe()
        elif link.startswith("region:"):
            self._open_region(int(link.split(":", 1)[1]))
        elif link.startswith("constellation:"):
            self._open_constellation(int(link.split(":", 1)[1]))
        elif link.startswith("system:"):
            self._open_system(int(link.split(":", 1)[1]))

    # ------------------------------------------------------------------
    # Scan ingest / export / watcher / settings
    # ------------------------------------------------------------------

    def _open_paste_dialog(self, prefill: bytes | None = None) -> None:
        dlg = PasteDialog(self, prefill_bytes=prefill if isinstance(prefill, (bytes, bytearray)) else None)
        if dlg.exec() == PasteDialog.DialogCode.Accepted:
            if not dlg.raw_bytes:
                return
            stats, _ = ingest_paste(dlg.raw_bytes, self.user_db, self.static_db)
            self._show_ingest_result(stats)
            self._refresh_progress()
            self._invalidate_maps()
            self._show_home()

    def _on_clipboard_scan_detected(self, data: bytes) -> None:
        self._open_paste_dialog(prefill=data)

    def _show_ingest_result(self, stats: IngestStats) -> None:
        msg = (
            f"Saved {stats.new_scans} new scan(s)\n"
            f"Updated {stats.rescans} existing scan(s)\n"
            f"In assignment: {stats.in_assignment}\n"
            f"Out of assignment: {stats.out_of_assignment}"
        )
        if stats.unknown_moons:
            msg += f"\n\nWarning: {len(stats.unknown_moons)} unknown moon ID(s) — these were saved but couldn't be located in the SDE."
        QMessageBox.information(self, "Scan saved", msg)

    def _open_export_dialog(self) -> None:
        ExportDialog(self.user_db, self).exec()

    def _toggle_watcher(self, on: bool) -> None:
        self._watcher.set_enabled(on)
        self.watch_act.setText("Watch Clipboard: ON" if on else "Watch Clipboard: OFF")

    def _open_settings(self) -> None:
        dlg = SettingsDialog(
            self.user_db, self.static_db,
            watcher_enabled=self._watcher.is_enabled(),
            watcher_interval_ms=self._watcher_interval_ms,
            parent=self,
        )
        dlg.assignment_changed.connect(self._on_assignment_changed)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            enabled, interval = dlg.watcher_settings()
            self._watcher_interval_ms = interval
            self._watcher.set_interval(interval)
            if enabled != self._watcher.is_enabled():
                self.watch_act.setChecked(enabled)

    def _on_assignment_changed(self) -> None:
        self._refresh_progress()
        self._invalidate_maps()
        self._show_home()

    def _invalidate_maps(self) -> None:
        """Mark all map views as needing a re-render on next visit
        (e.g. after a scan ingest or assignment change)."""
        for v in (self.universe_view, self.region_view, self.constellation_view):
            v.mark_dirty()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _user_region_id(self) -> int | None:
        const_id = self.user_db.get_constellation_id()
        if const_id is None:
            return None
        row = self.static_db.constellation(const_id)
        return row["region_id"] if row else None

    def _compute_scan_counts_for_constellation(self, constellation_id: int) -> dict[int, tuple[int, int]]:
        """Per-system (scanned, total) for systems in a constellation. Only
        the user's assigned systems get nonzero totals."""
        assigned_systems = set(self.user_db.get_assigned_system_ids())
        scanned_moon_ids = self.user_db.get_scanned_moon_ids(in_assignment=None)
        out: dict[int, list[int]] = {}
        for row in self.static_db.moons_in_constellation(constellation_id):
            out.setdefault(row["system_id"], []).append(row["moon_id"])
        result: dict[int, tuple[int, int]] = {}
        for sid, moons in out.items():
            if sid in assigned_systems:
                result[sid] = (sum(1 for m in moons if m in scanned_moon_ids), len(moons))
            else:
                result[sid] = (0, 0)
        return result

    def _compute_scan_counts_for_region(self, region_id: int) -> dict[int, tuple[int, int]]:
        """Per-system (scanned, total) for the user's assigned systems
        that happen to be in this region. Other systems get (0, 0)."""
        assigned_systems = set(self.user_db.get_assigned_system_ids())
        if not assigned_systems:
            return {}
        scanned_moon_ids = self.user_db.get_scanned_moon_ids(in_assignment=None)

        # For each assigned system in this region, count its moons + scanned
        out: dict[int, tuple[int, int]] = {}
        for s in self.static_db.systems_in_region(region_id):
            sid = s["system_id"]
            if sid not in assigned_systems:
                continue
            # Pull moons for that system
            moons = self.static_db.moons_in_system(sid)
            total = len(moons)
            scanned = sum(1 for m in moons if m["moon_id"] in scanned_moon_ids)
            out[sid] = (scanned, total)
        return out

    def _refresh_progress(self) -> None:
        scanned = self.user_db.count_scans(only_in_assignment=True)
        assigned_systems = self.user_db.get_assigned_system_ids()
        total = len(self.static_db.moon_ids_in_systems(assigned_systems))
        pct = (scanned / total * 100) if total else 0
        const_id = self.user_db.get_constellation_id()
        const_name = "(none)"
        if const_id is not None:
            row = self.static_db.constellation(const_id)
            if row:
                const_name = row["name"]
        self.progress_label.setText(
            f"  {const_name}  ·  {scanned} / {total} scanned ({pct:.1f}%)  "
        )

    def closeEvent(self, event):
        self._watcher.set_enabled(False)
        super().closeEvent(event)
