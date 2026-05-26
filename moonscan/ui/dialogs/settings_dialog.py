"""Settings dialog."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from ...db import UserDB
from ...paths import user_db_path
from ...static_db import StaticDB


class SettingsDialog(QDialog):
    """Backup/restore + assignment editing + watcher settings.

    Emits assignment_changed when the user re-runs the setup wizard from here.
    """
    assignment_changed = Signal()

    def __init__(self, user_db: UserDB, static_db: StaticDB,
                 watcher_enabled: bool, watcher_interval_ms: int,
                 parent=None):
        super().__init__(parent)
        self.user_db = user_db
        self.static_db = static_db
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(460, 360)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.watcher_check = QCheckBox()
        self.watcher_check.setChecked(watcher_enabled)
        form.addRow("Clipboard watcher enabled:", self.watcher_check)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(100, 5000)
        self.interval_spin.setSingleStep(100)
        self.interval_spin.setValue(watcher_interval_ms)
        self.interval_spin.setSuffix(" ms")
        form.addRow("Poll interval:", self.interval_spin)
        layout.addLayout(form)

        layout.addSpacing(12)
        layout.addWidget(QLabel("<b>Assignment</b>"))
        edit_row = QHBoxLayout()
        edit_btn = QPushButton("Edit assignment...")
        edit_btn.clicked.connect(self._edit_assignment)
        edit_row.addWidget(edit_btn)
        edit_row.addStretch()
        layout.addLayout(edit_row)

        layout.addSpacing(12)
        layout.addWidget(QLabel("<b>Backup & restore</b>"))
        layout.addWidget(QLabel(
            "Your scan data is stored in:\n" + str(user_db_path())
        ))

        backup_row = QHBoxLayout()
        backup_btn = QPushButton("Backup to file...")
        backup_btn.clicked.connect(self._backup)
        restore_btn = QPushButton("Restore from file...")
        restore_btn.clicked.connect(self._restore)
        backup_row.addWidget(backup_btn)
        backup_row.addWidget(restore_btn)
        backup_row.addStretch()
        layout.addLayout(backup_row)

        layout.addStretch()

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def watcher_settings(self) -> tuple[bool, int]:
        return self.watcher_check.isChecked(), self.interval_spin.value()

    def _edit_assignment(self) -> None:
        # Lazy import to avoid circular
        from ..setup_wizard import SetupWizard
        wiz = SetupWizard(self.static_db, parent=self)
        if wiz.exec() == QDialog.DialogCode.Accepted:
            wiz.write_to_db(self.user_db)
            self.assignment_changed.emit()
            QMessageBox.information(self, "Assignment updated",
                                    "Your assignment has been updated. Existing scan data was preserved.")

    def _backup(self) -> None:
        dest, _ = QFileDialog.getSaveFileName(
            self, "Backup user.db",
            "moonscan_backup.db", "SQLite database (*.db);;All files (*)"
        )
        if not dest:
            return
        try:
            shutil.copy2(self.user_db.path, dest)
            QMessageBox.information(self, "Backup complete", f"Saved to:\n{dest}")
        except OSError as e:
            QMessageBox.critical(self, "Backup failed", str(e))

    def _restore(self) -> None:
        src, _ = QFileDialog.getOpenFileName(
            self, "Restore user.db",
            "", "SQLite database (*.db);;All files (*)"
        )
        if not src:
            return
        reply = QMessageBox.warning(
            self, "Confirm restore",
            "This will REPLACE your current scan data with the backup file.\n\n"
            "The app will need to restart afterward. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.user_db.close()
            shutil.copy2(src, self.user_db.path)
            QMessageBox.information(
                self, "Restore complete",
                "Backup restored. Please close and reopen the app."
            )
            self.accept()
        except OSError as e:
            QMessageBox.critical(self, "Restore failed", str(e))
