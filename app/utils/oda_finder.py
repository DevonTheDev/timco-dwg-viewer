"""Auto-detect ODA File Converter installation."""

from __future__ import annotations

import glob
import shutil
import winreg
from pathlib import Path

from app.utils.settings import get_oda_path, set_oda_path

ODA_EXE_NAME = "ODAFileConverter.exe"

KNOWN_PATHS = [
    r"C:\Program Files\ODA\ODAFileConverter",
    r"C:\Program Files (x86)\ODA\ODAFileConverter",
]


def _check_registry() -> str | None:
    """Search Windows registry uninstall entries for ODA."""
    uninstall_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(root, uninstall_key)
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    subkey = winreg.OpenKey(key, subkey_name)
                    try:
                        display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                        if "ODA" in display_name and "File Converter" in display_name:
                            install_loc = winreg.QueryValueEx(subkey, "InstallLocation")[0]
                            exe = Path(install_loc) / ODA_EXE_NAME
                            if exe.is_file():
                                return str(exe)
                    except OSError:
                        pass
                    finally:
                        winreg.CloseKey(subkey)
                except OSError:
                    break
                i += 1
        finally:
            winreg.CloseKey(key)
    return None


def _check_known_paths() -> str | None:
    """Check common ODA install directories."""
    for base in KNOWN_PATHS:
        exe = Path(base) / ODA_EXE_NAME
        if exe.is_file():
            return str(exe)
    # Glob for versioned folders
    for pattern in [
        r"C:\Program Files\ODA\*\ODAFileConverter.exe",
        r"C:\Program Files (x86)\ODA\*\ODAFileConverter.exe",
    ]:
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None


def _check_path() -> str | None:
    """Check if ODA is on the system PATH."""
    result = shutil.which(ODA_EXE_NAME)
    if result:
        return result
    # Also try without .exe
    result = shutil.which("ODAFileConverter")
    return result


def find_oda_converter() -> str | None:
    """Find ODA File Converter, checking cached setting first.

    Returns the full path to the executable, or None if not found.
    """
    # Check cached setting
    cached = get_oda_path()
    if cached and Path(cached).is_file():
        return cached

    # Search for it
    for finder in (_check_registry, _check_known_paths, _check_path):
        result = finder()
        if result:
            set_oda_path(result)
            return result

    return None
