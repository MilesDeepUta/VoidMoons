"""
Dark theme palette + status colors.

Uses Qt Fusion style with a hand-rolled dark QPalette. Avoids stylesheet libs
to keep the PyInstaller bundle small and avoid AV false-positives from extra
binary dependencies.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# ---- chrome ----
BG          = QColor("#1e1e1e")
BG_ALT      = QColor("#252526")
BG_DEEP     = QColor("#181818")  # for the map canvas
TEXT        = QColor("#d4d4d4")
TEXT_DIM    = QColor("#9aa0a6")
TEXT_BRIGHT = QColor("#ffffff")
ACCENT      = QColor("#3794ff")
ACCENT_DIM  = QColor("#094771")
BORDER      = QColor("#3c3c3c")
DISABLED    = QColor("#6e6e6e")

# ---- semantic status ----
STATUS_NONE       = QColor("#cf4747")   # 0% scanned
STATUS_PARTIAL    = QColor("#d4a23a")   # 1..99% scanned
STATUS_COMPLETE   = QColor("#4daf68")   # 100% scanned
STATUS_OUT        = QColor("#5a5a5a")   # not in assignment
STATUS_STRANGER   = QColor("#8b6db8")   # scanned but not in assignment

# ---- map-specific ----
MAP_BG       = QColor("#0d1117")
MAP_EDGE_IN  = QColor("#3c4452")   # intra-constellation stargate
MAP_EDGE_OUT = QColor("#2a2f3a")   # exit-constellation stargate (dimmed)
MAP_NODE_BORDER = QColor("#1c2128")


def apply_dark_theme(app: QApplication) -> None:
    """Apply Fusion + dark palette to the application."""
    app.setStyle("Fusion")
    pal = QPalette()

    pal.setColor(QPalette.ColorRole.Window, BG)
    pal.setColor(QPalette.ColorRole.WindowText, TEXT)
    pal.setColor(QPalette.ColorRole.Base, BG_ALT)
    pal.setColor(QPalette.ColorRole.AlternateBase, BG)
    pal.setColor(QPalette.ColorRole.ToolTipBase, BG_ALT)
    pal.setColor(QPalette.ColorRole.ToolTipText, TEXT)
    pal.setColor(QPalette.ColorRole.PlaceholderText, TEXT_DIM)
    pal.setColor(QPalette.ColorRole.Text, TEXT)
    pal.setColor(QPalette.ColorRole.Button, BG_ALT)
    pal.setColor(QPalette.ColorRole.ButtonText, TEXT)
    pal.setColor(QPalette.ColorRole.BrightText, TEXT_BRIGHT)
    pal.setColor(QPalette.ColorRole.Highlight, ACCENT_DIM)
    pal.setColor(QPalette.ColorRole.HighlightedText, TEXT_BRIGHT)
    pal.setColor(QPalette.ColorRole.Link, ACCENT)
    pal.setColor(QPalette.ColorRole.Mid, BORDER)
    pal.setColor(QPalette.ColorRole.Light, BG_ALT.lighter(115))
    pal.setColor(QPalette.ColorRole.Dark, BG_DEEP)

    # Disabled states
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, DISABLED)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, DISABLED)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, DISABLED)

    app.setPalette(pal)


def progress_color(scanned: int, total: int) -> QColor:
    if total == 0:
        return STATUS_OUT
    if scanned == 0:
        return STATUS_NONE
    if scanned >= total:
        return STATUS_COMPLETE
    return STATUS_PARTIAL
