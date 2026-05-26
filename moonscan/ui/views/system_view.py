"""Level 2 — System view: planets in the system with their scan counts."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

from ... import theme
from ...db import UserDB
from ...static_db import StaticDB


class SystemView(QWidget):
    """Shows planets in a system. Each row: planet name, scanned/total badge."""

    planet_clicked = Signal(int)  # planet_id

    def __init__(self, static_db: StaticDB, user_db: UserDB, parent=None):
        super().__init__(parent)
        self.static_db = static_db
        self.user_db = user_db

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.title = QLabel("")
        f = self.title.font()
        f.setPointSize(14)
        f.setBold(True)
        self.title.setFont(f)
        layout.addWidget(self.title)

        self.subtitle = QLabel("")
        self.subtitle.setStyleSheet(f"color: {theme.TEXT_DIM.name()};")
        layout.addWidget(self.subtitle)

        self.list = QListWidget()
        self.list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list, 1)

    def show_system(self, system_id: int) -> None:
        sys_row = self.static_db.system(system_id)
        if sys_row is None:
            return
        self.title.setText(sys_row["name"])

        planets = self.static_db.planets_in_system(system_id)
        scanned_ids = self.user_db.get_scanned_moon_ids(in_assignment=None)

        self.list.clear()
        sys_scanned = sys_total = 0
        for p in planets:
            moons = self.static_db.moons_in_planet(p["planet_id"])
            total = len(moons)
            scanned = sum(1 for m in moons if m["moon_id"] in scanned_ids)
            sys_scanned += scanned
            sys_total += total
            color = theme.progress_color(scanned, total)
            label = f"{p['name']}    —    {scanned} / {total} moons scanned"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, p["planet_id"])
            item.setForeground(color)
            self.list.addItem(item)

        self.subtitle.setText(f"{sys_scanned} / {sys_total} moons scanned in this system")

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        pid = item.data(Qt.ItemDataRole.UserRole)
        if pid is not None:
            self.planet_clicked.emit(int(pid))
