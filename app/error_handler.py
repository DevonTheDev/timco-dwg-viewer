"""Global error handling with local crash logging."""

from __future__ import annotations

import logging
import platform
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from app.config import APP_NAME, APP_VERSION

logger = logging.getLogger(__name__)

LOG_DIR = Path.home() / ".timco-dwg-viewer" / "logs"


def _build_error_report(exc_type, exc_value, exc_tb) -> str:
    """Build a detailed error report string."""
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
    tb_text = "".join(tb_lines)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    report = (
        f"TIMCO DWG VIEWER — ERROR REPORT\n"
        f"{'=' * 60}\n"
        f"\n"
        f"Timestamp:    {now}\n"
        f"App Version:  {APP_VERSION}\n"
        f"Python:       {sys.version}\n"
        f"Platform:     {platform.platform()}\n"
        f"Machine:      {platform.machine()}\n"
        f"OS Release:   {platform.version()}\n"
        f"User:         {platform.node()}\n"
        f"\n"
        f"EXCEPTION\n"
        f"{'-' * 60}\n"
        f"Type:    {exc_type.__name__}\n"
        f"Message: {exc_value}\n"
        f"\n"
        f"FULL TRACEBACK\n"
        f"{'-' * 60}\n"
        f"{tb_text}\n"
    )

    # Try to include ezdxf and PySide6 versions
    try:
        import ezdxf
        report += f"ezdxf:        {ezdxf.__version__}\n"
    except Exception:
        pass
    try:
        import PySide6
        report += f"PySide6:      {PySide6.__version__}\n"
    except Exception:
        pass

    return report


def _save_crash_log(report: str) -> Path | None:
    """Save the error report to a local log file."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = LOG_DIR / f"crash_{timestamp}.txt"
        log_file.write_text(report, encoding="utf-8")
        return log_file
    except Exception:
        return None


def _show_error_dialog(report: str, log_file: Path | None) -> None:
    """Show a user-friendly error popup."""
    app = QApplication.instance()
    if app is None:
        # No Qt app running — just print
        print(report, file=sys.stderr)
        return

    log_note = ""
    if log_file:
        log_note = f"\n\nA detailed log has been saved to:\n{log_file}"

    QMessageBox.critical(
        None,
        f"{APP_NAME} — Unexpected Error",
        "An unexpected error occurred.\n\n"
        "An error report has been saved locally.\n\n"
        "We apologise for the inconvenience. You can try reopening\n"
        f"the application.{log_note}",
    )


def global_exception_handler(exc_type, exc_value, exc_tb) -> None:
    """Top-level exception handler wired into sys.excepthook."""
    # Don't intercept KeyboardInterrupt
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    report = _build_error_report(exc_type, exc_value, exc_tb)

    # Log to stderr and file
    logger.critical("Unhandled exception:\n%s", report)
    log_file = _save_crash_log(report)

    # Show dialog
    try:
        _show_error_dialog(report, log_file)
    except Exception:
        # If the dialog itself fails, at least print
        print(report, file=sys.stderr)


def setup_logging() -> None:
    """Configure application-wide logging."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_file = LOG_DIR / "timco_dwg_viewer.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )


def install() -> None:
    """Install the global error handler and set up logging."""
    setup_logging()
    sys.excepthook = global_exception_handler
