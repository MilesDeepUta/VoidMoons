"""
First-run setup dialog.

Replaces a QWizard-based flow (which had clunky native Windows chrome and
buried region lists behind a tiny dropdown arrow) with a custom QDialog that
shows a search box + always-visible scrolling list at each step.

Three steps:
  1. Region        — search/click one of 114 regions
  2. Constellation — search/click one of N constellations in that region
  3. Systems       — checklist of all systems in that constellation (all on)

On finish, writes the assignment to the user DB and reconciles in_assignment
flags on any existing scans.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import theme
from ..db import UserDB, META_CONSTELLATION
from ..static_db import StaticDB


# ----------------------------------------------------------------------------
# Reusable: search box + scrollable list widget
# ----------------------------------------------------------------------------

class SearchableList(QWidget):
    """A search-as-you-type filtered list of selectable items.

    Items are added via add_item(label, data). The current selection's data is
    available via selected_data(). Emits item_chosen(data) on double-click
    (caller can wire that to "advance to next step").
    """
    selection_changed = Signal(object)  # emits the UserRole data, or None
    item_chosen = Signal(object)        # emits on double-click

    def __init__(self, placeholder: str = "Type to filter...", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refilter)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.itemDoubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self.list, 1)

    # --- public API ---

    def clear(self) -> None:
        self.list.clear()
        self.search.clear()

    def add_item(self, label: str, data) -> None:
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, data)
        self.list.addItem(item)

    def add_items(self, pairs) -> None:
        for label, data in pairs:
            self.add_item(label, data)

    def selected_data(self):
        it = self.list.currentItem()
        if it is None or it.isHidden():
            return None
        return it.data(Qt.ItemDataRole.UserRole)

    def select_first_visible(self) -> None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            if not it.isHidden():
                self.list.setCurrentItem(it)
                return

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    # --- internals ---

    def _refilter(self, text: str) -> None:
        needle = text.strip().lower()
        first_visible = None
        for i in range(self.list.count()):
            it = self.list.item(i)
            visible = (needle in it.text().lower()) if needle else True
            it.setHidden(not visible)
            if visible and first_visible is None:
                first_visible = it
        # Re-anchor selection if current was hidden
        cur = self.list.currentItem()
        if cur is None or cur.isHidden():
            if first_visible is not None:
                self.list.setCurrentItem(first_visible)
            else:
                self.selection_changed.emit(None)

    def _on_current_changed(self, current, _previous) -> None:
        if current is None or current.isHidden():
            self.selection_changed.emit(None)
        else:
            self.selection_changed.emit(current.data(Qt.ItemDataRole.UserRole))

    def _on_double_clicked(self, item) -> None:
        if item is not None and not item.isHidden():
            self.item_chosen.emit(item.data(Qt.ItemDataRole.UserRole))


# ----------------------------------------------------------------------------
# Setup dialog
# ----------------------------------------------------------------------------

STEP_REGION = 0
STEP_CONST = 1
STEP_SYSTEMS = 2

STEP_TITLES = [
    "Region",
    "Constellation",
    "Systems",
]
STEP_SUBTITLES = [
    "Which region are you assigned to scan?",
    "Which constellation in this region?",
    "All systems are checked by default. Uncheck any you're not responsible for.",
]


class SetupWizard(QDialog):
    """Modal first-run dialog. Caller checks exec() result, then calls
    write_to_db() to persist the selections."""

    def __init__(self, static_db: StaticDB, parent=None):
        super().__init__(parent)
        self.static_db = static_db
        self.setWindowTitle("MoonScan — Setup")
        self.setModal(True)
        self.resize(720, 600)
        self.setMinimumSize(560, 480)

        # State
        self._step = STEP_REGION
        self._region_id: int | None = None
        self._region_name: str = ""
        self._constellation_id: int | None = None
        self._constellation_name: str = ""

        # Layout root
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(10)

        # Step indicator strip
        self.step_indicator = self._build_step_indicator()
        root.addWidget(self.step_indicator)

        # Title + subtitle
        self.title_label = QLabel("")
        tf = self.title_label.font()
        tf.setPointSize(16)
        tf.setBold(True)
        self.title_label.setFont(tf)
        root.addWidget(self.title_label)

        self.subtitle_label = QLabel("")
        self.subtitle_label.setStyleSheet(f"color: {theme.TEXT_DIM.name()};")
        self.subtitle_label.setWordWrap(True)
        root.addWidget(self.subtitle_label)

        root.addSpacing(6)

        # Step pages stacked
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self.region_page = SearchableList("Type to filter regions (e.g. 'gem' for Geminate)")
        self.const_page  = SearchableList("Type to filter constellations")
        self.systems_page = SystemsChecklist()
        self.stack.addWidget(self.region_page)    # 0
        self.stack.addWidget(self.const_page)     # 1
        self.stack.addWidget(self.systems_page)   # 2

        # Selection events
        self.region_page.selection_changed.connect(self._refresh_buttons)
        self.region_page.item_chosen.connect(lambda _d: self._go_next())
        self.const_page.selection_changed.connect(self._refresh_buttons)
        self.const_page.item_chosen.connect(lambda _d: self._go_next())
        self.systems_page.selection_changed.connect(self._refresh_buttons)

        # Button row
        button_row = QHBoxLayout()
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(self._go_back)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.next_btn = QPushButton("Next")
        self.next_btn.setDefault(True)
        self.next_btn.clicked.connect(self._go_next)
        button_row.addWidget(self.back_btn)
        button_row.addStretch()
        button_row.addWidget(self.cancel_btn)
        button_row.addWidget(self.next_btn)
        root.addLayout(button_row)

        # Populate step 1 immediately
        self._populate_regions()
        self._show_step(STEP_REGION)

    # ----- step indicator -----

    def _build_step_indicator(self) -> QWidget:
        """Three pill-style step badges across the top."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self._step_labels: list[QLabel] = []
        for i, name in enumerate(STEP_TITLES, start=1):
            lbl = QLabel(f"  {i}. {name}  ")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._step_labels.append(lbl)
            h.addWidget(lbl, 1)
        return w

    def _refresh_step_indicator(self) -> None:
        for i, lbl in enumerate(self._step_labels):
            if i == self._step:
                lbl.setStyleSheet(
                    f"background: {theme.ACCENT_DIM.name()}; "
                    f"color: {theme.TEXT_BRIGHT.name()}; "
                    f"padding: 6px 0; border-radius: 4px; font-weight: 600;"
                )
            elif i < self._step:
                lbl.setStyleSheet(
                    f"background: {theme.BG_DEEP.name()}; "
                    f"color: {theme.STATUS_COMPLETE.name()}; "
                    f"padding: 6px 0; border-radius: 4px;"
                )
            else:
                lbl.setStyleSheet(
                    f"background: {theme.BG_DEEP.name()}; "
                    f"color: {theme.TEXT_DIM.name()}; "
                    f"padding: 6px 0; border-radius: 4px;"
                )

    # ----- navigation -----

    def _show_step(self, step: int) -> None:
        self._step = step
        self.stack.setCurrentIndex(step)
        self.title_label.setText(f"Step {step + 1} of 3 — {STEP_TITLES[step]}")
        self.subtitle_label.setText(STEP_SUBTITLES[step])
        self.back_btn.setEnabled(step > 0)
        if step == STEP_SYSTEMS:
            self.next_btn.setText("Finish")
        else:
            self.next_btn.setText("Next")
        self._refresh_step_indicator()
        self._refresh_buttons()

        # Focus the search box on list-style steps
        if step == STEP_REGION:
            self.region_page.focus_search()
        elif step == STEP_CONST:
            self.const_page.focus_search()

    def _go_back(self) -> None:
        if self._step > 0:
            self._show_step(self._step - 1)

    def _go_next(self) -> None:
        if self._step == STEP_REGION:
            data = self.region_page.selected_data()
            if data is None:
                return
            self._region_id = int(data)
            it = self.region_page.list.currentItem()
            self._region_name = it.text() if it else ""
            self._populate_constellations(self._region_id)
            self._show_step(STEP_CONST)
        elif self._step == STEP_CONST:
            data = self.const_page.selected_data()
            if data is None:
                return
            self._constellation_id = int(data)
            it = self.const_page.list.currentItem()
            self._constellation_name = it.text() if it else ""
            self._populate_systems(self._constellation_id)
            self._show_step(STEP_SYSTEMS)
        else:  # STEP_SYSTEMS
            # Finish
            if not self.systems_page.selected_system_ids():
                return
            self.accept()

    def _refresh_buttons(self) -> None:
        if self._step == STEP_REGION:
            ok = self.region_page.selected_data() is not None
        elif self._step == STEP_CONST:
            ok = self.const_page.selected_data() is not None
        else:
            ok = len(self.systems_page.selected_system_ids()) > 0
        self.next_btn.setEnabled(ok)

    # ----- data loading -----

    def _populate_regions(self) -> None:
        self.region_page.clear()
        for r in self.static_db.all_regions():
            self.region_page.add_item(r["name"], r["region_id"])

    def _populate_constellations(self, region_id: int) -> None:
        self.const_page.clear()
        for c in self.static_db.constellations_in_region(region_id):
            self.const_page.add_item(c["name"], c["constellation_id"])

    def _populate_systems(self, constellation_id: int) -> None:
        systems = self.static_db.systems_in_constellation(constellation_id)
        self.systems_page.set_systems(systems)

    # ----- persistence -----

    def write_to_db(self, user_db: UserDB) -> None:
        system_ids = self.systems_page.selected_system_ids()
        user_db.set_assignment(system_ids, constellation_id=self._constellation_id)
        assigned_moon_ids = self.static_db.moon_ids_in_systems(system_ids)
        user_db.reconcile_in_assignment(assigned_moon_ids)


# ----------------------------------------------------------------------------
# Systems checklist page (step 3)
# ----------------------------------------------------------------------------

class SystemsChecklist(QWidget):
    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Top row: select all / none + summary
        top = QHBoxLayout()
        self.all_btn = QPushButton("Select all")
        self.none_btn = QPushButton("Select none")
        self.all_btn.clicked.connect(lambda: self._set_all(True))
        self.none_btn.clicked.connect(lambda: self._set_all(False))
        top.addWidget(self.all_btn)
        top.addWidget(self.none_btn)
        top.addStretch()
        self.summary = QLabel("")
        self.summary.setStyleSheet(f"color: {theme.TEXT_DIM.name()};")
        top.addWidget(self.summary)
        layout.addLayout(top)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.itemChanged.connect(lambda _i: self._update_summary())
        layout.addWidget(self.list, 1)

    def set_systems(self, systems) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for s in systems:
            item = QListWidgetItem(s["name"])
            item.setData(Qt.ItemDataRole.UserRole, s["system_id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._update_summary()

    def _set_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(state)
        self.list.blockSignals(False)
        self._update_summary()

    def _update_summary(self) -> None:
        total = self.list.count()
        sel = sum(
            1 for i in range(total)
            if self.list.item(i).checkState() == Qt.CheckState.Checked
        )
        self.summary.setText(f"{sel} of {total} selected")
        self.selection_changed.emit()

    def selected_system_ids(self) -> list[int]:
        out: list[int] = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(int(it.data(Qt.ItemDataRole.UserRole)))
        return out
