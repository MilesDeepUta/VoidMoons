"""
Level 3 — Moon list.

Tree of moons in a planet (or a flat list across the constellation), with
ore breakdowns shown as expandable child rows including the percentage as
text + a tiny bar. Mimics the in-game survey scanner visual.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QHeaderView, QLabel, QStyle,
    QStyleOptionProgressBar, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ... import theme
from ...db import UserDB
from ...static_db import StaticDB


class _BarDelegate(QStyledItemDelegate):
    """Render a small horizontal bar for ore-quantity cells (column 1).

    We store the quantity (0..1) in Qt.UserRole on child items. Parent rows
    leave UserRole empty and fall back to default text rendering.
    """
    def paint(self, painter: QPainter, option, index) -> None:
        if index.column() != 1:
            super().paint(painter, option, index)
            return
        qty = index.data(Qt.ItemDataRole.UserRole)
        if qty is None:
            super().paint(painter, option, index)
            return
        try:
            qty = float(qty)
        except (TypeError, ValueError):
            super().paint(painter, option, index)
            return

        # Draw text first
        super().paint(painter, option, index)
        # Then overlay a bar in the right ~half of the cell
        painter.save()
        rect: QRect = option.rect
        bar_h = max(4, rect.height() // 3)
        bar_y = rect.y() + (rect.height() - bar_h) // 2
        # Right-justify the bar so it doesn't overlap the % text on the left
        text_w = 60
        bar_x = rect.x() + text_w
        bar_w = rect.width() - text_w - 8
        if bar_w < 10:
            painter.restore()
            return
        # Background track
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(theme.BG_DEEP))
        painter.drawRect(bar_x, bar_y, bar_w, bar_h)
        # Filled portion
        fill_w = int(bar_w * max(0.0, min(1.0, qty)))
        painter.setBrush(QBrush(theme.ACCENT))
        painter.drawRect(bar_x, bar_y, fill_w, bar_h)
        painter.restore()


class MoonListView(QWidget):
    """Tree of moons. Two display modes:
      - show_planet(planet_id): moons under one planet
      - show_system(system_id): all moons in a system, grouped by planet
    """

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

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Moon / Ore", "Quantity", "Scanned"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setColumnWidth(1, 240)
        self.tree.setItemDelegate(_BarDelegate(self.tree))
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        layout.addWidget(self.tree, 1)

    # ----- public API -----

    def show_planet(self, planet_id: int) -> None:
        rows = self.static_db.moons_in_planet(planet_id)
        planet_row = self.static_db.planet(planet_id)
        planet_name = planet_row["name"] if planet_row else "Planet"
        self.title.setText(planet_name)
        self._populate(rows)

    def show_system(self, system_id: int) -> None:
        sys_row = self.static_db.system(system_id)
        self.title.setText(f"All moons — {sys_row['name'] if sys_row else system_id}")
        rows = self.static_db.moons_in_system(system_id)
        self._populate(rows)

    def show_stranger_moons(self) -> None:
        """Show all scanned moons that aren't in the assignment."""
        self.title.setText("Stranger Moons")
        self.subtitle.setText("Scanned moons outside your assigned systems")
        self.tree.clear()
        scanned = self.user_db.get_scanned_moon_ids(in_assignment=False)
        # Build rows via static_db lookups
        rows = []
        for mid in sorted(scanned):
            sde = self.static_db.moon(mid)
            if sde is None:
                continue
            rows.append({
                "moon_id": sde["moon_id"],
                "name": sde["name"],
                "moon_index": sde["moon_index"],
            })
        self._populate(rows, hide_unscanned=True)

    # ----- internal -----

    def _populate(self, moon_rows, hide_unscanned: bool = False) -> None:
        self.tree.clear()
        scanned_count = total_count = 0

        for r in moon_rows:
            moon_id = r["moon_id"]
            name = r["name"]
            scan = self.user_db.get_scan(moon_id)
            total_count += 1
            is_scanned = scan is not None
            if is_scanned:
                scanned_count += 1
            elif hide_unscanned:
                continue

            top = QTreeWidgetItem([name, "", "✓" if is_scanned else "—"])
            top.setData(0, Qt.ItemDataRole.UserRole, moon_id)
            if not is_scanned:
                top.setForeground(0, QBrush(theme.DISABLED))
                top.setForeground(2, QBrush(theme.DISABLED))
            else:
                top.setForeground(2, QBrush(theme.STATUS_COMPLETE))

            self.tree.addTopLevelItem(top)

            if is_scanned:
                for ore in scan["ores"]:
                    qty = ore["quantity"]
                    qty_text = f"{qty * 100:.2f}%"
                    child = QTreeWidgetItem(["  " + ore["name"], qty_text, ""])
                    child.setData(1, Qt.ItemDataRole.UserRole, qty)
                    self.tree.addTopLevelItem  # nothing
                    top.addChild(child)
                top.setExpanded(False)

        self.subtitle.setText(f"{scanned_count} / {total_count} moons scanned")
