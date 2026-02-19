"""Persistent settings via QSettings."""

from PySide6.QtCore import QSettings

from app.config import APP_NAME, APP_ORG


def get_settings() -> QSettings:
    return QSettings(APP_ORG, APP_NAME)


def get_last_directory() -> str:
    return get_settings().value("last_directory", "")


def set_last_directory(path: str) -> None:
    s = get_settings()
    s.setValue("last_directory", path)


def get_oda_path() -> str:
    return get_settings().value("oda_converter_path", "")


def set_oda_path(path: str) -> None:
    s = get_settings()
    s.setValue("oda_converter_path", path)


MAX_RECENT_FILES = 10


def get_recent_files() -> list[str]:
    """Return list of recent file paths, most recent first."""
    s = get_settings()
    files = s.value("recent_files", [])
    if files is None:
        return []
    if isinstance(files, str):
        return [files] if files else []
    return list(files)


def add_recent_file(path: str) -> None:
    """Add a file to the top of the recent files list."""
    s = get_settings()
    files = get_recent_files()
    # Remove if already present (so it moves to top)
    path = str(path).replace("/", "\\")
    files = [f for f in files if f.replace("/", "\\") != path]
    files.insert(0, path)
    files = files[:MAX_RECENT_FILES]
    s.setValue("recent_files", files)
