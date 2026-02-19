"""Auto-update system using GitHub Releases with manifest-based patching."""

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

    def __init__(
        self,
        version: str,
        download_url: str,
        release_notes: str,
        patch_url: str = "",
        manifest_url: str = "",
    ):
        self.version = version
        self.download_url = download_url  # full zip
        self.release_notes = release_notes
        self.patch_url = patch_url  # patch zip (smaller, may be empty)
        self.manifest_url = manifest_url  # manifest.json asset URL


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

    # Scan assets for full zip, patch zip, and manifest
    download_url = ""
    patch_url = ""
    manifest_url = ""

    for asset in data.get("assets", []):
        name = asset.get("name", "")
        url = asset.get("browser_download_url", "")

        if name == "manifest.json":
            manifest_url = url
        elif name.endswith("-patch.zip"):
            patch_url = url
        elif name.endswith(".zip"):
            download_url = url

    if not download_url:
        logger.debug("No suitable download asset found in release %s", tag)
        return None

    return UpdateInfo(
        version=remote_version,
        download_url=download_url,
        release_notes=data.get("body", ""),
        patch_url=patch_url,
        manifest_url=manifest_url,
    )


def _download_file(url: str, dest: Path, progress_cb=None) -> None:
    """Download a URL to a local file with optional progress callback."""
    req = Request(url, headers=_HEADERS)
    with urlopen(req, timeout=120) as resp:
        total = resp.headers.get("Content-Length")
        downloaded = 0
        chunk_size = 64 * 1024
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb and total and int(total) > 0:
                    pct = int(downloaded / int(total) * 100)
                    progress_cb(pct)


class _DownloadWorker(QObject):
    """Downloads and prepares the update in a background thread."""

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
            # Try patch update first — much smaller download
            if self._info.patch_url and self._info.manifest_url:
                local_manifest = app_dir / "manifest.json"
                if local_manifest.exists():
                    result = self._try_patch(app_dir, local_manifest)
                    if result:
                        self.finished.emit(True, result)
                        return
                    logger.info("Patch not applicable, falling back to full download")

            # Full update (fallback)
            result = self._full_update(app_dir)
            self.finished.emit(True, result)

        except Exception as e:
            logger.exception("Failed to download/extract update")
            self.finished.emit(False, str(e))

    # ── Patch update ─────────────────────────────────────────

    def _try_patch(self, app_dir: Path, local_manifest_path: Path) -> str | None:
        """Attempt a patch update. Returns batch script path or None."""
        try:
            self.progress.emit("Checking what changed...")
            tmp_dir = tempfile.mkdtemp(prefix="timco_patch_")

            # Download remote manifest (tiny — a few KB)
            manifest_path = Path(tmp_dir) / "manifest.json"
            _download_file(self._info.manifest_url, manifest_path)

            remote_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            local_manifest = json.loads(local_manifest_path.read_text(encoding="utf-8"))

            remote_files = remote_manifest.get("files", {})
            local_files = local_manifest.get("files", {})

            changed = [f for f, h in remote_files.items() if local_files.get(f) != h]
            deleted = [f for f in local_files if f not in remote_files]

            if not changed and not deleted:
                return None

            n = len(changed) + len(deleted)
            logger.info("Patch: %d changed, %d deleted files", len(changed), len(deleted))

            # Download patch zip
            self.progress.emit(f"Downloading patch ({n} files changed)...")
            zip_path = Path(tmp_dir) / "patch.zip"
            _download_file(
                self._info.patch_url,
                zip_path,
                lambda pct: self.progress.emit(f"Downloading patch... {pct}%"),
            )

            # Extract
            self.progress.emit("Extracting patch...")
            extract_dir = Path(tmp_dir) / "extracted"
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            # Remove patch metadata file so it doesn't get copied to app dir
            meta_path = extract_dir / "_patch_meta.json"
            if meta_path.exists():
                meta_path.unlink()

            self.progress.emit("Preparing update...")
            return self._write_patch_batch(app_dir, extract_dir, deleted, tmp_dir)

        except Exception as e:
            logger.debug("Patch update failed: %s", e)
            return None

    def _write_patch_batch(
        self, app_dir: Path, patch_dir: Path, deleted: list[str], tmp_dir: str
    ) -> str:
        """Write a batch script that overlays changed files and deletes removed ones."""
        exe_path = app_dir / "TimcoDWG.exe"

        delete_cmds = "\n".join(
            f'del /F /Q "{app_dir / rel}" 2>NUL' for rel in deleted
        )

        bat_path = Path(tmp_dir) / "do_update.bat"
        bat_path.write_text(
            f"""@echo off
echo Updating Timco DWG Viewer (patch)...

:waitloop
tasklist /FI "PID eq {os.getpid()}" 2>NUL | find /I "{os.getpid()}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto waitloop
)
timeout /t 1 /nobreak >NUL

:: Overlay changed files onto existing installation
xcopy /E /Y /Q "{patch_dir}\\*" "{app_dir}\\"
if errorlevel 1 (
    echo ERROR: Failed to copy patch files.
    pause
    exit /b 1
)

:: Remove deleted files
{delete_cmds}

if not exist "{exe_path}" (
    echo ERROR: Update failed — executable not found.
    pause
    exit /b 1
)

start "" "{exe_path}"
rmdir /S /Q "{tmp_dir}" 2>NUL
del "%~f0" 2>NUL
""",
            encoding="utf-8",
        )
        return str(bat_path)

    # ── Full update ──────────────────────────────────────────

    def _full_update(self, app_dir: Path) -> str:
        """Full update — download entire zip and swap all files."""
        tmp_dir = tempfile.mkdtemp(prefix="timco_update_")
        zip_path = Path(tmp_dir) / "update.zip"

        # Download
        self.progress.emit("Downloading update...")
        logger.info("Downloading full update from %s", self._info.download_url)
        _download_file(
            self._info.download_url,
            zip_path,
            lambda pct: self.progress.emit(f"Downloading... {pct}%"),
        )

        # Extract
        self.progress.emit("Extracting update...")
        extract_dir = Path(tmp_dir) / "extracted"
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        # Find content root (may be nested in a single folder)
        contents = list(extract_dir.iterdir())
        if len(contents) == 1 and contents[0].is_dir():
            source_dir = contents[0]
        else:
            source_dir = extract_dir

        # Write batch script — rename old files (fast) instead of deleting
        self.progress.emit("Preparing update...")
        exe_path = app_dir / "TimcoDWG.exe"
        internal_dir = app_dir / "_internal"
        old_internal = app_dir / "_internal_old"
        old_exe = app_dir / "TimcoDWG_old.exe"

        bat_path = Path(tmp_dir) / "do_update.bat"
        bat_path.write_text(
            f"""@echo off
echo Updating Timco DWG Viewer...

:waitloop
tasklist /FI "PID eq {os.getpid()}" 2>NUL | find /I "{os.getpid()}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto waitloop
)
timeout /t 1 /nobreak >NUL

:: Clean up any leftover old files from a previous update
if exist "{old_internal}" rmdir /S /Q "{old_internal}" 2>NUL
if exist "{old_exe}" del /F /Q "{old_exe}" 2>NUL

:: Rename current files out of the way (instant — no slow delete)
if exist "{internal_dir}" ren "{internal_dir}" "_internal_old" 2>NUL
if exist "{exe_path}" ren "{exe_path}" "TimcoDWG_old.exe" 2>NUL

:: Copy new files
xcopy /E /Y /Q "{source_dir}\\*" "{app_dir}\\"
if errorlevel 1 (
    echo ERROR: Failed to copy update files.
    :: Attempt rollback
    if not exist "{internal_dir}" if exist "{old_internal}" ren "{old_internal}" "_internal" 2>NUL
    if not exist "{exe_path}" if exist "{old_exe}" ren "{old_exe}" "TimcoDWG.exe" 2>NUL
    pause
    exit /b 1
)

if not exist "{exe_path}" (
    echo ERROR: Update failed — executable not found.
    if exist "{old_internal}" ren "{old_internal}" "_internal" 2>NUL
    if exist "{old_exe}" ren "{old_exe}" "TimcoDWG.exe" 2>NUL
    pause
    exit /b 1
)

:: Relaunch immediately — clean up old files afterwards
start "" "{exe_path}"
timeout /t 2 /nobreak >NUL
rmdir /S /Q "{old_internal}" 2>NUL
del /F /Q "{old_exe}" 2>NUL
rmdir /S /Q "{tmp_dir}" 2>NUL
del "%~f0" 2>NUL
""",
            encoding="utf-8",
        )
        return str(bat_path)


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
