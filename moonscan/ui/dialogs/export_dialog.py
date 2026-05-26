"""Export dialog: shows the built export with a Copy-to-Clipboard button."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QClipboard
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QVBoxLayout,
)

from ... import theme
from ...db import META_HEADER_BYTES, META_TRAILER_BYTES, UserDB
from ...export import build_export


class ExportDialog(QDialog):
    def __init__(self, user_db: UserDB, parent=None):
        super().__init__(parent)
        self.user_db = user_db
        self.setWindowTitle("Export for Alliance")
        self.setModal(True)
        self.resize(720, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.summary = QLabel("")
        self.summary.setStyleSheet(f"color: {theme.TEXT_DIM.name()};")
        layout.addWidget(self.summary)

        self.include_strangers = QCheckBox("Include 'stranger' moons (scans outside assignment)")
        self.include_strangers.setChecked(False)
        self.include_strangers.stateChanged.connect(self._rebuild)
        layout.addWidget(self.include_strangers)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        f = self.text.font()
        f.setFamily("Consolas, Menlo, monospace")
        f.setPointSize(9)
        self.text.setFont(f)
        layout.addWidget(self.text, 1)

        button_row = QHBoxLayout()
        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.setDefault(True)
        self.copy_btn.clicked.connect(self._copy)
        button_row.addWidget(self.copy_btn)
        button_row.addStretch()
        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        close_box.accepted.connect(self.accept)
        button_row.addWidget(close_box)
        layout.addLayout(button_row)

        self._payload: bytes = b""
        self._rebuild()

    def _rebuild(self) -> None:
        include_strangers = self.include_strangers.isChecked()
        chunks = self.user_db.get_all_scans_ordered(only_in_assignment=not include_strangers)
        header = self.user_db.get_meta_bytes(META_HEADER_BYTES) or b""
        trailer = self.user_db.get_meta_bytes(META_TRAILER_BYTES) or b""
        self._payload = build_export(chunks, header_bytes=header, trailer_bytes=trailer)

        try:
            display = self._payload.decode("utf-8")
        except UnicodeDecodeError:
            display = self._payload.decode("utf-8", errors="replace")
        self.text.setPlainText(display)
        moon_count = len(chunks)
        bytes_count = len(self._payload)
        self.summary.setText(f"{moon_count} moons, {bytes_count:,} bytes")

    def _copy(self) -> None:
        cb: QClipboard = QApplication.clipboard()
        # Decode for the clipboard text path — Qt's clipboard works with QString
        # internally, and CRLF behavior is platform-dependent. Users paste into
        # pastebin which strips/normalizes anyway, so this is fine in practice.
        try:
            text = self._payload.decode("utf-8")
        except UnicodeDecodeError:
            text = self._payload.decode("utf-8", errors="replace")
        cb.setText(text)
        self.copy_btn.setText("Copied!")
