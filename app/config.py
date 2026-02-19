"""Application constants and defaults."""

import sys
from pathlib import Path

APP_NAME = "Timco DWG Viewer"
APP_ORG = "Timco"
APP_VERSION = "1.0.0"

# GitHub releases repo (public — used for auto-updates)
GITHUB_RELEASES_REPO = "DevonTheDev/timco-dwg-releases"

# Base directory: handles both dev and PyInstaller frozen modes
if getattr(sys, "frozen", False):
    # Running as PyInstaller bundle — _MEIPASS is the temp extraction dir for data,
    # but for writable presets we use the exe's directory
    BASE_DIR = Path(sys._MEIPASS)
    APP_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    APP_DIR = BASE_DIR

# Branding
TIMCO_GREEN = "#1A7A3D"
TIMCO_YELLOW = "#FFC000"
TIMCO_DARK_GREEN = "#0E5C2A"
LOGO_PATH = BASE_DIR / "timco-logo.png"

# Viewer defaults
BACKGROUND_COLOR = "#2D2D30"
ZOOM_FACTOR = 1.15

# ODA conversion
ODA_TIMEOUT_SECONDS = 120
ODA_OUTPUT_VERSION = "ACAD2018"
ODA_OUTPUT_FORMAT = "DXF"

# File filters
DWG_FILTER = "DWG Files (*.dwg)"
DXF_FILTER = "DXF Files (*.dxf)"
ALL_CAD_FILTER = "CAD Files (*.dwg *.dxf)"
ALL_FILES_FILTER = "All Files (*)"

OPEN_FILE_FILTER = f"{ALL_CAD_FILTER};;{DWG_FILTER};;{DXF_FILTER};;{ALL_FILES_FILTER}"
EXPORT_FILE_FILTER = f"{DXF_FILTER};;{ALL_FILES_FILTER}"

# Presets directory — writable, lives next to the exe (not in temp extraction)
PRESETS_DIR = APP_DIR / "presets"
