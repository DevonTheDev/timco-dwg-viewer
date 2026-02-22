"""Entry point for Timco DWG Viewer."""

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.config import APP_DIR, APP_NAME, APP_ORG, LOGO_PATH
from app.main_window import MainWindow


def main() -> None:
    # Install global error handler first — before anything else can fail
    from app.error_handler import install as install_error_handler
    install_error_handler()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)

    if LOGO_PATH.is_file():
        app.setWindowIcon(QIcon(str(LOGO_PATH)))

    # Offer to remove old installations sitting next to this one
    if getattr(sys, "frozen", False):
        from app.cleanup import prompt_cleanup
        prompt_cleanup(APP_DIR)

    # First-run setup check — instant skip if everything is already installed
    from app.setup_check import run_setup_if_needed

    if not run_setup_if_needed():
        sys.exit(0)

    window = MainWindow()
    window.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
