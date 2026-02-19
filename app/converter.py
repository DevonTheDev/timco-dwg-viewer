"""DWG to DXF conversion using ODA File Converter."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from app.config import ODA_OUTPUT_FORMAT, ODA_OUTPUT_VERSION, ODA_TIMEOUT_SECONDS
from app.utils.oda_finder import find_oda_converter


class ConversionError(Exception):
    pass


def convert_dwg_to_dxf(dwg_path: Path) -> Path:
    """Convert a single DWG file to DXF using ODA File Converter.

    Returns the path to the converted DXF file (in a temp directory).
    Raises ConversionError on failure.
    """
    oda_exe = find_oda_converter()
    if not oda_exe:
        raise ConversionError(
            "ODA File Converter not found.\n\n"
            "Please install it from:\n"
            "https://www.opendesign.com/guestfiles/oda_file_converter\n\n"
            "It is free for non-commercial use."
        )

    dwg_path = Path(dwg_path).resolve()
    if not dwg_path.is_file():
        raise ConversionError(f"DWG file not found: {dwg_path}")

    # ODA processes entire directories, so isolate the file
    input_dir = tempfile.mkdtemp(prefix="timco_in_")
    output_dir = tempfile.mkdtemp(prefix="timco_out_")

    try:
        shutil.copy2(str(dwg_path), input_dir)

        # ODA CLI: ODAFileConverter "InDir" "OutDir" version format recurse audit
        cmd = [
            oda_exe,
            input_dir,
            output_dir,
            ODA_OUTPUT_VERSION,
            ODA_OUTPUT_FORMAT,
            "0",  # recurse: 0 = no
            "1",  # audit: 1 = yes
        ]

        CREATE_NO_WINDOW = 0x08000000
        result = subprocess.run(
            cmd,
            timeout=ODA_TIMEOUT_SECONDS,
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )

        # Find the output DXF
        dxf_name = dwg_path.stem + ".dxf"
        output_dxf = Path(output_dir) / dxf_name

        if not output_dxf.is_file():
            # Try case-insensitive search
            for f in Path(output_dir).iterdir():
                if f.suffix.lower() == ".dxf":
                    output_dxf = f
                    break
            else:
                stderr = result.stderr.decode(errors="replace").strip()
                raise ConversionError(
                    f"ODA conversion produced no DXF output.\n"
                    f"Return code: {result.returncode}\n"
                    f"{stderr}"
                )

        return output_dxf

    except ConversionError:
        raise
    except subprocess.TimeoutExpired:
        raise ConversionError(
            f"ODA conversion timed out after {ODA_TIMEOUT_SECONDS} seconds."
        )
    except FileNotFoundError:
        raise ConversionError(f"Could not run ODA File Converter at: {oda_exe}")
    except OSError as e:
        raise ConversionError(f"OS error during conversion: {e}")


class ConversionWorker(QObject):
    """Background worker for DWG→DXF conversion."""

    finished = Signal(str)  # path to DXF
    error = Signal(str)  # error message

    def __init__(self, dwg_path: Path):
        super().__init__()
        self._dwg_path = dwg_path

    def run(self) -> None:
        try:
            dxf_path = convert_dwg_to_dxf(self._dwg_path)
            self.finished.emit(str(dxf_path))
        except ConversionError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected conversion error: {e}")


def start_conversion(dwg_path: Path, on_finished, on_error) -> tuple[QThread, ConversionWorker]:
    """Start DWG→DXF conversion in a background thread.

    Returns (thread, worker) — caller must keep references alive.
    """
    thread = QThread()
    worker = ConversionWorker(dwg_path)
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)
    worker.finished.connect(on_finished)
    worker.error.connect(on_error)

    thread.start()
    return thread, worker
