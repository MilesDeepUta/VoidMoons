"""
MoonScan application entry point.

Handles:
  - QApplication / theme setup
  - Static DB load (the shipped read-only EVE data)
  - User DB load + first-run setup wizard if no assignment exists
  - Main window display
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from .db import UserDB
from .paths import static_db_path, user_db_path
from .static_db import StaticDB
from .theme import apply_dark_theme
from .ui.main_window import MainWindow
from .ui.setup_wizard import SetupWizard


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MoonScan")
    apply_dark_theme(app)

    # Load static DB. If missing, surface a clear error.
    sde_path = static_db_path()
    if not sde_path.exists():
        QMessageBox.critical(
            None, "Missing data",
            f"Could not find the EVE static database at:\n{sde_path}\n\n"
            "If you're running from source, you may need to run:\n"
            "    python build_sde.py --src <jsonl_dir>",
        )
        return 1

    static_db = StaticDB(sde_path)
    user_db = UserDB(user_db_path())

    # First-run check: no assignment → run the setup wizard
    if not user_db.get_assigned_system_ids():
        wiz = SetupWizard(static_db)
        if wiz.exec() != QDialog.DialogCode.Accepted:
            return 0
        wiz.write_to_db(user_db)

    window = MainWindow(user_db, static_db)
    window.show()
    rc = app.exec()

    user_db.close()
    static_db.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
