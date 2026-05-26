"""
Clipboard helpers.

We use Qt's QClipboard so we don't pull in pyperclip as a dependency
(one fewer thing for PyInstaller to bundle). For the watcher, polling
every ~500ms via a QTimer is simpler than hooking native clipboard
events and is fast enough that users won't notice the latency.

Reading: QClipboard.mimeData() exposes text/plain bytes. We decode/encode
as UTF-8 to stay in bytes-land for the parser.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QClipboard
from PySide6.QtWidgets import QApplication

from .parser import looks_like_scan


def read_clipboard_bytes() -> bytes:
    """Return the current text clipboard contents as bytes (UTF-8 encoded).

    Returns b"" if the clipboard has no text content. Qt normalizes line
    endings to '\\n' on read, so we re-encode CRLF before parsing if we
    detect Windows-style content; however, since EVE on Windows always
    pastes CRLF, we can't reliably round-trip on a chat-text fallback.

    The watcher and paste dialog should both use this function so behavior
    is consistent.
    """
    cb: QClipboard = QApplication.clipboard()
    md = cb.mimeData()
    if md is None or not md.hasText():
        return b""
    text = cb.text()
    if not text:
        return b""
    # We trust Qt's text mode and encode UTF-8. Note: Qt normalizes line endings
    # to LF on read. To preserve the *exact* bytes EVE put on the clipboard,
    # we read via the platform-specific raw text/plain mime type when available.
    raw = md.data("text/plain")
    if raw and len(raw) > 0:
        return bytes(raw)
    return text.encode("utf-8")


class ClipboardWatcher(QObject):
    """Polls the clipboard for moon-scan-shaped content.

    Emits `scan_detected(bytes)` once per distinct payload. The UI is responsible
    for confirming with the user before ingesting (we don't auto-save, to avoid
    eating someone's unrelated clipboard copy).
    """
    scan_detected = Signal(bytes)

    def __init__(self, interval_ms: int = 500, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)
        self._last_seen: bytes = b""
        self._enabled = False

    def set_enabled(self, on: bool) -> None:
        self._enabled = on
        if on:
            # Prime _last_seen with current clipboard so we don't trigger on
            # whatever was there before we started watching.
            self._last_seen = read_clipboard_bytes()
            self._timer.start()
        else:
            self._timer.stop()

    def is_enabled(self) -> bool:
        return self._enabled

    def set_interval(self, ms: int) -> None:
        self._timer.setInterval(ms)

    def _poll(self) -> None:
        try:
            data = read_clipboard_bytes()
        except Exception:
            return
        if not data or data == self._last_seen:
            return
        self._last_seen = data
        if looks_like_scan(data):
            self.scan_detected.emit(data)
