"""Auto-update system using GitHub Releases."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

from packaging.version import Version
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
)

from app.config import (
    APP_NAME,
    APP_VERSION,
    GITHUB_RELEASES_REPO,
    LOGO_PATH,
    TIMCO_DARK_GREEN,
    TIMCO_GREEN,
)

logger = logging.getLogger(__name__)

_API_URL = f"https://api.github.com/repos/{GITHUB_RELEASES_REPO}/releases/latest"
_HEADERS = {"Accept": "application/vnd.github+json"}
_TIMEOUT = 10


class UpdateInfo:
    """Holds information about an available update."""

    def __init__(self, version: str, download_url: str, release_notes: str):
        self.version = version
        self.download_url = download_url
        self.release_notes = release_notes


def check_for_update() -> UpdateInfo | None:
    """Check GitHub for a newer release. Returns UpdateInfo or None."""
    try:
        req = Request(_API_URL, headers=_HEADERS)
        with urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except (URLError, OSError, ValueError) as e:
        logger.debug("Update check failed: %s", e)
        return None

    tag = data.get("tag_name", "")
    remote_version = tag.lstrip("v")

    try:
        if Version(remote_version) <= Version(APP_VERSION):
            return None
    except Exception:
        return None

    # Find the .zip asset for Windows
    download_url = ""
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".zip") and "windows" in name.lower():
            download_url = asset["browser_download_url"]
            break

    # Fallback: take the first .zip asset
    if not download_url:
        for asset in data.get("assets", []):
            if asset.get("name", "").endswith(".zip"):
                download_url = asset["browser_download_url"]
                break

    if not download_url:
        logger.debug("No suitable download asset found in release %s", tag)
        return None

    return UpdateInfo(
        version=remote_version,
        download_url=download_url,
        release_notes=data.get("body", ""),
    )


class _DownloadWorker(QObject):
    """Downloads and extracts the update zip in a background thread."""

    progress = Signal(str)  # status message
    finished = Signal(bool, str)  # (success, error_or_batch_path)

    def __init__(self, info: UpdateInfo):
        super().__init__()
        self._info = info

    def run(self) -> None:
        if not getattr(sys, "frozen", False):
            self.finished.emit(False, "Cannot apply update in dev mode.")
            return

        app_dir = Path(sys.executable).parent

        try:
            tmp_dir = tempfile.mkdtemp(prefix="timco_update_")
            zip_path = Path(tmp_dir) / "update.zip"

            # Download with progress
            self.progress.emit("Downloading update...")
            logger.info("Downloading update from %s", self._info.download_url)
            req = Request(self._info.download_url, headers=_HEADERS)
            with urlopen(req, timeout=120) as resp:
                total = resp.headers.get("Content-Length")
                downloaded = 0
                chunk_size = 64 * 1024
                with open(zip_path, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total and int(total) > 0:
                            pct = int(downloaded / int(total) * 100)
                            self.progress.emit(f"Downloading... {pct}%")

            # Extract
            self.progress.emit("Extracting update...")
            extract_dir = Path(tmp_dir) / "extracted"
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            # Find the actual content root (may be nested in a folder)
            contents = list(extract_dir.iterdir())
            if len(contents) == 1 and contents[0].is_dir():
                source_dir = contents[0]
            else:
                source_dir = extract_dir

            # Write the batch script that swaps files and relaunches
            self.progress.emit("Preparing update...")
            updater_bat = Path(tmp_dir) / "do_update.bat"
            exe_path = app_dir / "TimcoDWG.exe"
            internal_dir = app_dir / "_internal"
            updater_bat.write_text(
                f"""@echo off
echo Updating Timco DWG Viewer...

:: Wait for the app to close
:waitloop
tasklist /FI "PID eq {os.getpid()}" 2>NUL | find /I "{os.getpid()}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto waitloop
)

:: Extra delay to ensure all file locks are released
timeout /t 3 /nobreak >NUL

:: Remove old _internal directory completely to avoid stale/corrupt modules
if exist "{internal_dir}" (
    rmdir /S /Q "{internal_dir}" 2>NUL
    timeout /t 1 /nobreak >NUL
)

:: Remove old exe
if exist "{exe_path}" (
    del /F /Q "{exe_path}" 2>NUL
)

:: Copy new files over
xcopy /E /Y /Q "{source_dir}\\*" "{app_dir}\\"
if errorlevel 1 (
    echo ERROR: Failed to copy update files.
    pause
    exit /b 1
)

:: Verify the exe exists before relaunching
if not exist "{exe_path}" (
    echo ERROR: Update failed — executable not found after copy.
    pause
    exit /b 1
)

:: Relaunch
start "" "{exe_path}"

:: Clean up temp dir (best effort)
rmdir /S /Q "{tmp_dir}" 2>NUL
:: Delete self
del "%~f0" 2>NUL
""",
                encoding="utf-8",
            )

            self.finished.emit(True, str(updater_bat))

        except Exception as e:
            logger.exception("Failed to download/extract update")
            self.finished.emit(False, str(e))


class UpdateProgressDialog(QDialog):
    """Small standalone progress window shown during update download."""

    def __init__(self, info: UpdateInfo, parent=None):
        super().__init__(parent)
        self._info = info
        self._thread: QThread | None = None
        self._worker: _DownloadWorker | None = None

        self.setWindowTitle(f"Updating {APP_NAME}")
        self.setFixedSize(380, 140)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.CustomizeWindowHint
        )

        if LOGO_PATH.is_file():
            self.setWindowIcon(QIcon(str(LOGO_PATH)))

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._title_label = QLabel(f"Installing v{info.version}...")
        self._title_label.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {TIMCO_DARK_GREEN};"
        )
        layout.addWidget(self._title_label)

        self._status_label = QLabel("Starting download...")
        self._status_label.setStyleSheet("font-size: 12px; color: #555;")
        layout.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setStyleSheet(
            f"QProgressBar::chunk {{ background: {TIMCO_GREEN}; }}"
        )
        layout.addWidget(self._progress)

    def start(self) -> None:
        """Kick off the background download."""
        self._thread = QThread()
        self._worker = _DownloadWorker(self._info)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)

        self._thread.start()

    def _on_progress(self, message: str) -> None:
        self._status_label.setText(message)

    def _on_finished(self, success: bool, result: str) -> None:
        if success:
            self._status_label.setText("Restarting...")
            # Launch the updater batch script and quit
            subprocess.Popen(
                ["cmd", "/c", result],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            QApplication.quit()
        else:
            self._status_label.setText("")
            self._progress.setVisible(False)
            self._title_label.setText("Update failed")
            QMessageBox.warning(
                self,
                "Update Failed",
                f"Could not apply the update:\n\n{result}\n\n"
                "Please try again later or download the latest version manually.",
            )
            self.reject()

    def closeEvent(self, event) -> None:
        # Don't allow closing while downloading
        if self._thread and self._thread.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)
