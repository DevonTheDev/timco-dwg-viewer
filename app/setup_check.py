"""First-run setup check — runs inside the same exe, no separate installer."""

from __future__ import annotations

import subprocess
import shutil
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QProgressBar,
    QGroupBox,
)

from app.config import (
    LOGO_PATH,
    PRESETS_DIR,
    TIMCO_DARK_GREEN,
    TIMCO_GREEN,
    TIMCO_YELLOW,
)
from app.utils.oda_finder import find_oda_converter
from app.utils.settings import get_oda_path, set_oda_path

ODA_DOWNLOAD_URL = "https://www.opendesign.com/guestfiles/oda_file_converter"
WINGET_PACKAGE_ID = "ODA.ODAFileConverter"


def is_setup_complete() -> bool:
    """Quick check — returns True if everything is ready (fast path)."""
    oda = find_oda_converter()
    return oda is not None


def ensure_presets_dir() -> None:
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)


def has_winget() -> bool:
    return shutil.which("winget") is not None


class WingetInstallWorker(QThread):
    """Background thread to run winget install."""

    finished = Signal(bool, str)  # (success, message)

    def run(self) -> None:
        try:
            result = subprocess.run(
                [
                    "winget", "install", "-e",
                    "--id", WINGET_PACKAGE_ID,
                    "--accept-source-agreements",
                    "--accept-package-agreements",
                ],
                capture_output=True,
                text=True,
                timeout=300,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                self.finished.emit(True, "ODA File Converter installed successfully.")
            else:
                output = (result.stdout + "\n" + result.stderr).strip()
                self.finished.emit(False, f"winget exited with code {result.returncode}.\n{output}")
        except subprocess.TimeoutExpired:
            self.finished.emit(False, "Installation timed out after 5 minutes.")
        except FileNotFoundError:
            self.finished.emit(False, "winget not found on this system.")
        except Exception as e:
            self.finished.emit(False, str(e))


class SetupDialog(QDialog):
    """Branded first-run setup dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Timco DWG Viewer — Setup")
        self.setFixedSize(520, 480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._worker: WingetInstallWorker | None = None
        self._oda_found = False

        if LOGO_PATH.is_file():
            self.setWindowIcon(QIcon(str(LOGO_PATH)))

        self._build_ui()
        self._refresh_status()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header with logo and title
        header = QHBoxLayout()
        if LOGO_PATH.is_file():
            logo_label = QLabel()
            pm = QPixmap(str(LOGO_PATH)).scaledToHeight(50, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(pm)
            header.addWidget(logo_label)
        title = QLabel("DWG Viewer Setup")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {TIMCO_GREEN};")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # Description
        desc = QLabel(
            "This tool needs <b>ODA File Converter</b> to open DWG files.\n"
            "It converts DWG to DXF so the viewer can read them.\n\n"
            "Without it, you can still open DXF files directly."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Status group
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout(status_group)
        self._oda_status = QLabel()
        self._oda_status.setTextFormat(Qt.TextFormat.RichText)
        status_layout.addWidget(self._oda_status)
        layout.addWidget(status_group)

        # Install options group
        install_group = QGroupBox("Install ODA File Converter")
        install_layout = QVBoxLayout(install_group)

        # Winget button
        winget_row = QHBoxLayout()
        self._btn_winget = QPushButton("Install via winget (Recommended)")
        self._btn_winget.setMinimumHeight(36)
        self._btn_winget.clicked.connect(self._install_winget)
        winget_row.addWidget(self._btn_winget)
        install_layout.addLayout(winget_row)

        if not has_winget():
            self._btn_winget.setEnabled(False)
            self._btn_winget.setToolTip("winget is not available on this system")
            no_winget = QLabel(
                '<span style="color: gray; font-size: 11px;">'
                "winget not found — use the download option below instead</span>"
            )
            install_layout.addWidget(no_winget)

        # Download button
        dl_row = QHBoxLayout()
        self._btn_download = QPushButton("Download from ODA website")
        self._btn_download.setMinimumHeight(36)
        self._btn_download.clicked.connect(self._open_download_page)
        dl_row.addWidget(self._btn_download)
        install_layout.addLayout(dl_row)

        # Browse button
        browse_row = QHBoxLayout()
        self._btn_browse = QPushButton("I already have it — locate manually")
        self._btn_browse.setMinimumHeight(36)
        self._btn_browse.clicked.connect(self._browse_oda)
        browse_row.addWidget(self._btn_browse)
        install_layout.addLayout(browse_row)

        # Progress bar (hidden by default)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        install_layout.addWidget(self._progress)

        self._install_status = QLabel("")
        self._install_status.setWordWrap(True)
        self._install_status.setVisible(False)
        install_layout.addWidget(self._install_status)

        layout.addWidget(install_group)
        self._install_group = install_group

        # Bottom buttons
        bottom = QHBoxLayout()
        bottom.addStretch()

        self._btn_skip = QPushButton("Skip — DXF files only")
        self._btn_skip.clicked.connect(self._skip)
        bottom.addWidget(self._btn_skip)

        self._btn_continue = QPushButton("Continue")
        self._btn_continue.setMinimumWidth(120)
        self._btn_continue.setMinimumHeight(36)
        self._btn_continue.setStyleSheet(
            f"QPushButton {{ background: {TIMCO_GREEN}; color: white; "
            f"font-weight: bold; border-radius: 4px; padding: 6px 20px; }}"
            f"QPushButton:hover {{ background: {TIMCO_DARK_GREEN}; }}"
        )
        self._btn_continue.clicked.connect(self.accept)
        bottom.addWidget(self._btn_continue)

        layout.addLayout(bottom)

    def _refresh_status(self) -> None:
        oda = find_oda_converter()
        self._oda_found = oda is not None

        if oda:
            self._oda_status.setText(
                f'<span style="color: green; font-size: 14px;">&#10004;</span> '
                f'ODA File Converter found: <code>{oda}</code>'
            )
            self._install_group.setVisible(False)
            self._btn_skip.setVisible(False)
        else:
            self._oda_status.setText(
                '<span style="color: #CC6600; font-size: 14px;">&#10008;</span> '
                "ODA File Converter <b>not found</b>"
            )
            self._install_group.setVisible(True)
            self._btn_skip.setVisible(True)

    def _set_installing(self, active: bool) -> None:
        self._progress.setVisible(active)
        self._btn_winget.setEnabled(not active and has_winget())
        self._btn_download.setEnabled(not active)
        self._btn_browse.setEnabled(not active)
        self._btn_skip.setEnabled(not active)
        self._btn_continue.setEnabled(not active)

    # ── Install actions ──

    def _install_winget(self) -> None:
        self._set_installing(True)
        self._install_status.setText("Installing via winget... this may take a minute.")
        self._install_status.setVisible(True)

        self._worker = WingetInstallWorker()
        self._worker.finished.connect(self._on_winget_done)
        self._worker.start()

    def _on_winget_done(self, success: bool, message: str) -> None:
        self._set_installing(False)

        if success:
            self._install_status.setStyleSheet("color: green;")
            self._install_status.setText(message)
            self._refresh_status()
        else:
            self._install_status.setStyleSheet("color: red;")
            self._install_status.setText(message)

    def _open_download_page(self) -> None:
        webbrowser.open(ODA_DOWNLOAD_URL)
        QMessageBox.information(
            self,
            "Download ODA",
            "Your browser has been opened to the ODA download page.\n\n"
            "1. Download and install ODA File Converter\n"
            "2. Come back here and click 'Continue'\n\n"
            "If it still isn't detected, use 'locate manually'.",
        )
        # Re-check in case they installed quickly
        self._refresh_status()

    def _browse_oda(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Locate ODAFileConverter.exe",
            "C:\\Program Files",
            "ODAFileConverter (ODAFileConverter.exe)",
        )
        if path and Path(path).is_file():
            set_oda_path(path)
            self._refresh_status()

    def _skip(self) -> None:
        self.accept()


def run_setup_if_needed() -> bool:
    """Check setup state. Show dialog only if ODA is missing.

    Returns True if the app should proceed, False to exit.
    """
    ensure_presets_dir()

    # Fast path — everything already in order
    if is_setup_complete():
        return True

    # Show setup dialog
    dialog = SetupDialog()
    result = dialog.exec()

    # User closed the dialog with X — exit the app
    if result == QDialog.DialogCode.Rejected:
        return False

    return True
