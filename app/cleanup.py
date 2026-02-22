"""Detect and remove old TimcoDWG installations sitting next to the current one."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtWidgets import QMessageBox


def find_old_installations(app_dir: Path) -> list[Path]:
    """Return sibling directories that contain a different TimcoDWG installation.

    Detection: any sibling folder whose name starts with "TimcoDWG" and contains
    a TimcoDWG.exe, but is not *this* installation's directory.
    """
    parent = app_dir.parent
    old: list[Path] = []

    try:
        for entry in parent.iterdir():
            if not entry.is_dir():
                continue
            if entry.resolve() == app_dir.resolve():
                continue
            if not entry.name.lower().startswith("timcodwg"):
                continue
            # Confirm it's actually an installation (has the exe or _internal)
            if (entry / "TimcoDWG.exe").exists() or (entry / "_internal").exists():
                old.append(entry)
    except OSError:
        pass

    return old


def _migrate_presets(src_dir: Path, dst_dir: Path) -> int:
    """Copy preset files from *src_dir*/presets into *dst_dir*/presets.

    Only copies files that don't already exist in the destination.
    Returns the number of files copied.
    """
    src_presets = src_dir / "presets"
    dst_presets = dst_dir / "presets"

    if not src_presets.is_dir():
        return 0

    dst_presets.mkdir(exist_ok=True)
    copied = 0

    for f in src_presets.iterdir():
        if f.is_file() and not (dst_presets / f.name).exists():
            shutil.copy2(f, dst_presets / f.name)
            copied += 1

    return copied


def prompt_cleanup(app_dir: Path) -> None:
    """If old installations exist, ask the user whether to remove them.

    Presets are migrated automatically before deletion so no user data is lost.
    Call this early in startup, after QApplication is created.
    """
    old_dirs = find_old_installations(app_dir)
    if not old_dirs:
        return

    names = "\n".join(f"  • {d.name}" for d in old_dirs)
    reply = QMessageBox.question(
        None,
        "Old Version Detected",
        f"The following older installation(s) were found:\n\n"
        f"{names}\n\n"
        f"Would you like to remove them?\n"
        f"(Any custom presets will be migrated automatically.)",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )

    if reply != QMessageBox.StandardButton.Yes:
        return

    # Migrate presets first, then delete
    for d in old_dirs:
        _migrate_presets(d, app_dir)
        shutil.rmtree(d, ignore_errors=True)
