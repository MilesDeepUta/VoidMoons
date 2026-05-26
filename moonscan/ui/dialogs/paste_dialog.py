"""Manual paste dialog: textarea preview + ingest button."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QVBoxLayout,
)

from ... import theme
from ...clipboard import read_clipboard_bytes
from ...parser import parse


class PasteDialog(QDialog):
    """Modal dialog showing the current clipboard content for review.

    On Save, the dialog stores the raw bytes in `self.raw_bytes` and accepts.
    Caller (main window) is responsible for calling ingest_paste().
    """

    def __init__(self, parent=None, prefill_bytes: bytes | None = None):
        super().__init__(parent)
        self.setWindowTitle("Paste Scan Data")
        self.setModal(True)
        self.resize(700, 480)
        self.raw_bytes: bytes = b""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        self.summary = QLabel("Loading clipboard...")
        self.summary.setStyleSheet(f"color: {theme.TEXT_DIM.name()};")
        layout.addWidget(self.summary)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(False)
        f = self.text.font()
        f.setFamily("Consolas, Menlo, monospace")
        f.setPointSize(9)
        self.text.setFont(f)
        layout.addWidget(self.text, 1)

        button_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Re-read clipboard")
        self.refresh_btn.clicked.connect(self._refresh)
        button_row.addWidget(self.refresh_btn)
        button_row.addStretch()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save scan")
        self.buttons.accepted.connect(self._on_save)
        self.buttons.rejected.connect(self.reject)
        button_row.addWidget(self.buttons)
        layout.addLayout(button_row)

        # Prefill with provided bytes (e.g. from watcher) or clipboard
        if prefill_bytes is not None:
            self._set_payload(prefill_bytes)
        else:
            self._refresh()

    def _refresh(self) -> None:
        self._set_payload(read_clipboard_bytes())

    def _set_payload(self, data: bytes) -> None:
        self.raw_bytes = data
        try:
            preview = data.decode("utf-8")
        except UnicodeDecodeError:
            preview = data.decode("utf-8", errors="replace")
        self.text.setPlainText(preview)

        # Quick parse to summarize
        if not data:
            self.summary.setText("Clipboard is empty.")
            self._enable_save(False)
            return
        result = parse(data)
        n = len(result.moons)
        if n == 0:
            self.summary.setText(
                "No moons detected. Make sure you used 'Copy to Clipboard' in EVE's moon scan window."
            )
            self._enable_save(False)
        else:
            ores = sum(len(m.ores) for m in result.moons)
            self.summary.setText(f"Detected {n} moon(s), {ores} ore record(s).")
            self._enable_save(True)

    def _enable_save(self, enabled: bool) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(enabled)

    def _on_save(self) -> None:
        # If the user edited the text area, prefer the edited content as bytes.
        edited = self.text.toPlainText()
        if edited and edited.encode("utf-8") != self.raw_bytes:
            # User modified — re-encode as UTF-8. Note: this may lose CRLF if Qt
            # normalized them, so we warn the user via accept-on-edit semantics.
            self.raw_bytes = edited.encode("utf-8")
        self.accept()
