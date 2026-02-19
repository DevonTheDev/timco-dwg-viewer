"""Auto-update system using GitHub Releases."""

from __future__ import annotations

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

from app.config import APP_VERSION, GITHUB_RELEASES_REPO

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
    import json

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


def apply_update(info: UpdateInfo) -> bool:
    """Download and apply the update. Returns True on success.

    Strategy: download zip to temp, extract, then use a small batch script
    that waits for this process to exit, copies the new files over, and
    relaunches the app.
    """
    if not getattr(sys, "frozen", False):
        logger.warning("Cannot apply update in dev mode")
        return False

    app_dir = Path(sys.executable).parent

    try:
        # Download the zip
        tmp_dir = tempfile.mkdtemp(prefix="timco_update_")
        zip_path = Path(tmp_dir) / "update.zip"

        logger.info("Downloading update from %s", info.download_url)
        req = Request(info.download_url, headers=_HEADERS)
        with urlopen(req, timeout=120) as resp, open(zip_path, "wb") as f:
            shutil.copyfileobj(resp, f)

        # Extract
        extract_dir = Path(tmp_dir) / "extracted"
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        # Find the actual content root (may be nested in a folder)
        contents = list(extract_dir.iterdir())
        if len(contents) == 1 and contents[0].is_dir():
            source_dir = contents[0]
        else:
            source_dir = extract_dir

        # Write a batch script that:
        # 1. Waits for the current process to exit
        # 2. Copies new files over the old install
        # 3. Relaunches the app
        # 4. Cleans up the temp dir and itself
        updater_bat = Path(tmp_dir) / "do_update.bat"
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
:: Copy new files over old install
xcopy /E /Y /Q "{source_dir}\\*" "{app_dir}\\"
:: Relaunch
start "" "{app_dir / 'TimcoDWG.exe'}"
:: Clean up temp dir (best effort)
rmdir /S /Q "{tmp_dir}" 2>NUL
:: Delete self
del "%~f0" 2>NUL
""",
            encoding="utf-8",
        )

        # Launch the updater script hidden and exit
        subprocess.Popen(
            ["cmd", "/c", str(updater_bat)],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True

    except Exception:
        logger.exception("Failed to apply update")
        return False
