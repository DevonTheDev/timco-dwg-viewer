# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Timco DWG Viewer."""

import os
import sys
from pathlib import Path

import ezdxf

block_cipher = None

# Paths
PROJECT_DIR = os.path.abspath(".")
EZDXF_DIR = os.path.dirname(ezdxf.__file__)

a = Analysis(
    [os.path.join("app", "main.py")],
    pathex=[PROJECT_DIR],
    binaries=[],
    datas=[
        # Timco assets
        ("timco-logo.png", "."),
        ("presets", "presets"),
        # ezdxf data files (resources, templates, etc.)
        (os.path.join(EZDXF_DIR, "resources"), os.path.join("ezdxf", "resources")),
    ],
    hiddenimports=[
        # ezdxf drawing pipeline
        "ezdxf.addons.drawing",
        "ezdxf.addons.drawing.pyqt",
        "ezdxf.addons.drawing.frontend",
        "ezdxf.addons.drawing.backend",
        "ezdxf.addons.drawing.config",
        "ezdxf.addons.drawing.properties",
        "ezdxf.addons.drawing.type_hints",
        # ezdxf Qt compatibility layer
        "ezdxf.addons.xqt",
        # PySide6 modules ezdxf uses
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtSvgWidgets",
        # Auto-updater
        "packaging",
        "packaging.version",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude PyQt to avoid conflicts
        "PyQt5",
        "PyQt6",
        # Exclude unused PySide6 heavy modules
        "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DAnimation",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtRemoteObjects",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtQml",
        "PySide6.QtNetworkAuth",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TimcoDWG",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window
    icon="timco-logo.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TimcoDWG",
)
