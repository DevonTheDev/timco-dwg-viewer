"""Main application window wiring all components together."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal, QObject
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QWidget,
)

from app.config import (
    APP_NAME,
    APP_VERSION,
    EXPORT_FILE_FILTER,
    LOGO_PATH,
    OPEN_FILE_FILTER,
    TIMCO_DARK_GREEN,
    TIMCO_GREEN,
    TIMCO_YELLOW,
)
from app.converter import start_conversion
from app.exporter import export_all_layers, export_filtered_dxf, suggest_output_path
from app.layer_manager import LayerManagerWidget
from app.models import DrawingDocument
from app.utils.settings import (
    add_recent_file,
    get_last_directory,
    get_recent_files,
    set_last_directory,
)
from app.viewer import DXFViewerWidget

_CAD_EXTENSIONS = {".dwg", ".dxf"}


class _UpdateCheckWorker(QObject):
    """Runs the update check off the main thread."""

    finished = Signal(object)  # UpdateInfo | None

    def run(self):
        from app.updater import check_for_update

        self.finished.emit(check_for_update())


class UpdateBanner(QWidget):
    """A dismissible banner shown when an update is available."""

    update_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background: {TIMCO_YELLOW}; border-bottom: 2px solid #E0A800;"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)

        self._label = QLabel()
        self._label.setStyleSheet(f"color: {TIMCO_DARK_GREEN}; font-weight: bold; font-size: 13px; border: none;")
        layout.addWidget(self._label, 1)

        self._btn_update = QPushButton("Update Now")
        self._btn_update.setStyleSheet(
            f"background: {TIMCO_GREEN}; color: white; font-weight: bold;"
            " border: none; border-radius: 3px; padding: 4px 16px; font-size: 12px;"
        )
        self._btn_update.clicked.connect(self.update_requested.emit)
        layout.addWidget(self._btn_update)

        btn_dismiss = QPushButton("Dismiss")
        btn_dismiss.setStyleSheet(
            f"background: transparent; color: {TIMCO_DARK_GREEN}; font-weight: bold;"
            " border: none; padding: 4px 8px; font-size: 12px;"
        )
        btn_dismiss.clicked.connect(self.hide)
        layout.addWidget(btn_dismiss)

        self.hide()

    def show_update(self, version: str) -> None:
        self._label.setText(f"A new version (v{version}) is available!")
        self.show()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 900)
        self.setAcceptDrops(True)

        # Window icon
        if LOGO_PATH.is_file():
            self.setWindowIcon(QIcon(str(LOGO_PATH)))

        self._document: DrawingDocument | None = None
        self._dxf_path: Path | None = None  # path to the loaded DXF (may be temp)
        self._dxf_temp_dir: Path | None = None  # temp dir to clean up on next load
        self._original_path: Path | None = None  # original file the user opened
        self._conversion_thread = None
        self._conversion_worker = None
        self._loading = False  # guard against re-entrant loads
        self._pending_update = None  # UpdateInfo when an update is available
        self._update_thread = None

        self._apply_style()
        self._build_update_banner()
        self._build_menu_bar()
        self._build_toolbar()
        self._build_central()
        self._build_status_bar()

        # Connect layer panel to viewer
        self._layer_manager.visibility_changed.connect(self._on_layers_changed)
        self._viewer.hide_layer_requested.connect(self._layer_manager.hide_layer)

        # Auto-check for updates after the window is shown
        QTimer.singleShot(1500, self._check_for_updates)

    def _apply_style(self) -> None:
        """Apply Timco brand styling."""
        self.setStyleSheet(f"""
            QToolBar {{
                background: {TIMCO_GREEN};
                border: none;
                padding: 4px;
                spacing: 6px;
            }}
            QToolBar QToolButton {{
                background: {TIMCO_YELLOW};
                color: {TIMCO_DARK_GREEN};
                border: 1px solid {TIMCO_DARK_GREEN};
                border-radius: 3px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 13px;
            }}
            QToolBar QToolButton:hover {{
                background: #FFD040;
            }}
            QToolBar QToolButton:pressed {{
                background: #E0A800;
            }}
            QToolBar QToolButton:disabled {{
                background: #B0B0B0;
                color: #707070;
                border-color: #909090;
            }}
            QStatusBar {{
                background: {TIMCO_DARK_GREEN};
                color: white;
                font-size: 12px;
            }}
            QStatusBar QLabel {{
                color: white;
            }}
            QMenuBar {{
                background: {TIMCO_DARK_GREEN};
                color: white;
            }}
            QMenuBar::item:selected {{
                background: {TIMCO_GREEN};
            }}
            QMenu {{
                background: white;
                color: black;
            }}
            QMenu::item:selected {{
                background: {TIMCO_GREEN};
                color: white;
            }}
        """)

    # ── Update banner ────────────────────────────────────────

    def _build_update_banner(self) -> None:
        self._update_banner = UpdateBanner(self)
        self._update_banner.update_requested.connect(self._apply_update)

    # ── Menu bar ─────────────────────────────────────────────

    def _build_menu_bar(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")

        act_open = file_menu.addAction("&Open File...")
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self._open_file)

        self._recent_menu = file_menu.addMenu("Recent Files")
        self._refresh_recent_menu()

        file_menu.addSeparator()

        act_export = file_menu.addAction("&Export DXF...")
        act_export.setShortcut(QKeySequence("Ctrl+E"))
        act_export.triggered.connect(self._export)

        # Help menu
        help_menu = mb.addMenu("&Help")

        act_updates = help_menu.addAction("Check for &Updates...")
        act_updates.triggered.connect(self._manual_update_check)

        help_menu.addSeparator()

        act_about = help_menu.addAction("&About")
        act_about.triggered.connect(self._show_about)

    def _refresh_recent_menu(self) -> None:
        self._recent_menu.clear()
        files = get_recent_files()

        # Prune paths that no longer exist
        valid = [f for f in files if Path(f).is_file()]
        if len(valid) != len(files):
            from app.utils.settings import get_settings
            get_settings().setValue("recent_files", valid)
            files = valid

        if not files:
            no_recent = self._recent_menu.addAction("(no recent files)")
            no_recent.setEnabled(False)
            return

        for filepath in files:
            p = Path(filepath)
            action = self._recent_menu.addAction(p.name)
            action.setToolTip(str(p))
            action.triggered.connect(lambda checked=False, path=p: self._open_path(path))

        self._recent_menu.addSeparator()
        clear_action = self._recent_menu.addAction("Clear Recent Files")
        clear_action.triggered.connect(self._clear_recent)

    def _clear_recent(self) -> None:
        from app.utils.settings import get_settings
        get_settings().setValue("recent_files", [])
        self._refresh_recent_menu()

    # ── Toolbar ──────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        self._act_open = QAction("Open File", self)
        self._act_open.triggered.connect(self._open_file)
        tb.addAction(self._act_open)

        tb.addSeparator()

        self._act_fit = QAction("Fit", self)
        self._act_fit.setShortcut(QKeySequence("Ctrl+0"))
        self._act_fit.triggered.connect(self._fit)
        tb.addAction(self._act_fit)

        self._act_zoom_in = QAction("Zoom +", self)
        self._act_zoom_in.setShortcut(QKeySequence.StandardKey.ZoomIn)
        self._act_zoom_in.triggered.connect(self._zoom_in)
        tb.addAction(self._act_zoom_in)

        self._act_zoom_out = QAction("Zoom -", self)
        self._act_zoom_out.setShortcut(QKeySequence.StandardKey.ZoomOut)
        self._act_zoom_out.triggered.connect(self._zoom_out)
        tb.addAction(self._act_zoom_out)

        self._act_flip = QAction("Flip", self)
        self._act_flip.setShortcut(QKeySequence("Ctrl+F"))
        self._act_flip.setCheckable(True)
        self._act_flip.triggered.connect(self._flip)
        tb.addAction(self._act_flip)

        tb.addSeparator()

        self._act_export = QAction("Export DXF", self)
        self._act_export.triggered.connect(self._export)
        self._act_export.setEnabled(False)
        tb.addAction(self._act_export)

    # ── Central: splitter with layer panel + viewer ──────────

    def _build_central(self) -> None:
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        self._layer_manager = LayerManagerWidget()
        self._layer_manager.setMinimumWidth(200)
        self._layer_manager.setMaximumWidth(400)

        self._viewer = DXFViewerWidget()

        self._splitter.addWidget(self._layer_manager)
        self._splitter.addWidget(self._viewer)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([250, 1150])

        self.setCentralWidget(self._splitter)

    # ── Status bar ───────────────────────────────────────────

    def _build_status_bar(self) -> None:
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        self._progress = QProgressBar()
        self._progress.setMaximumWidth(200)
        self._progress.setVisible(False)
        self._status_bar.addPermanentWidget(self._progress)

        self._version_label = QLabel(f"v{APP_VERSION}")
        self._version_label.setStyleSheet("color: #AAAAAA; padding-right: 8px;")
        self._status_bar.addPermanentWidget(self._version_label)

        self._status_bar.showMessage("Ready — open a DWG or DXF file")

    def _update_status(self) -> None:
        if self._document:
            name = self._document.file_path.name
            n_layers = len(self._document.layers)
            n_entities = self._document.total_entities
            self._status_bar.showMessage(
                f"{name}  |  {n_layers} layers  |  {n_entities:,} entities"
            )

    # ── Drag and drop ────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    suffix = Path(url.toLocalFile()).suffix.lower()
                    if suffix in _CAD_EXTENSIONS:
                        event.acceptProposedAction()
                        return

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                if path.suffix.lower() in _CAD_EXTENSIONS:
                    self._open_path(path)
                    return  # open the first valid file

    # ── Open file ────────────────────────────────────────────

    def _open_file(self) -> None:
        last_dir = get_last_directory()
        path, _ = QFileDialog.getOpenFileName(
            self, "Open CAD File", last_dir, OPEN_FILE_FILTER
        )
        if not path:
            return
        self._open_path(Path(path))

    def _open_path(self, file_path: Path) -> None:
        """Open a DWG or DXF file by path (used by dialog, recent menu, and drag-drop)."""
        # Block re-entrant opens during conversion or loading
        if self._loading:
            return
        if self._conversion_thread and self._conversion_thread.isRunning():
            return

        if not file_path.is_file():
            QMessageBox.warning(self, "File Not Found", f"File no longer exists:\n{file_path}")
            return

        set_last_directory(str(file_path.parent))
        add_recent_file(str(file_path))
        self._refresh_recent_menu()

        if file_path.suffix.lower() == ".dwg":
            self._convert_and_load(file_path)
        else:
            self._load_dxf(file_path)

    def _convert_and_load(self, dwg_path: Path) -> None:
        """Convert DWG to DXF in background, then load."""
        self._original_path = dwg_path
        self._set_loading(True, f"Converting {dwg_path.name}...")

        self._conversion_thread, self._conversion_worker = start_conversion(
            dwg_path,
            on_finished=self._on_conversion_finished,
            on_error=self._on_conversion_error,
        )

    def _on_conversion_finished(self, dxf_path: str) -> None:
        self._set_loading(False)
        self._load_dxf(Path(dxf_path), display_path=self._original_path)

    def _on_conversion_error(self, error_msg: str) -> None:
        self._set_loading(False)
        QMessageBox.critical(self, "Conversion Error", error_msg)

    def _load_dxf(self, path: Path, display_path: Path | None = None) -> None:
        """Load a DXF file into the viewer."""
        import shutil

        self._loading = True
        self._set_loading(True, f"Loading {path.name}...")
        QApplication.processEvents()

        # Clean up the temp directory from a previous DWG conversion
        old_temp = self._dxf_temp_dir
        self._dxf_temp_dir = None

        try:
            self._document = DrawingDocument.from_dxf(path)
            self._document.file_path = display_path or path
            self._dxf_path = path
            self._original_path = display_path or path
        except Exception as e:
            self._set_loading(False)
            self._loading = False
            QMessageBox.critical(self, "Load Error", f"Failed to load DXF:\n{e}")
            return

        # Track temp dir if the DXF lives in one (from DWG conversion)
        if path.parent.name.startswith("timco_out_"):
            self._dxf_temp_dir = path.parent

        # Safe to clean up the old temp dir now that the new doc is loaded
        if old_temp and old_temp.is_dir():
            shutil.rmtree(old_temp, ignore_errors=True)

        self._layer_manager.set_layers(self._document.layers)
        self._viewer.set_document(self._document.doc)
        self._act_export.setEnabled(True)

        self._set_loading(False)
        self._loading = False
        self._update_status()
        self.setWindowTitle(f"{self._document.file_path.name} — {APP_NAME}")

        # Fit after the scene is populated (delayed so geometry settles)
        QTimer.singleShot(100, self._viewer.fit_drawing)

    # ── Layer toggling ───────────────────────────────────────

    def _on_layers_changed(self, visible_layers: set[str]) -> None:
        self._viewer.set_visible_layers(visible_layers)

    # ── Zoom controls ────────────────────────────────────────

    def _fit(self) -> None:
        self._viewer.fit_drawing()

    def _zoom_in(self) -> None:
        self._viewer.zoom_in()

    def _zoom_out(self) -> None:
        self._viewer.zoom_out()

    def _flip(self) -> None:
        self._viewer.flip_vertical()

    # ── Export ────────────────────────────────────────────────

    def _export(self) -> None:
        if not self._document or not self._dxf_path:
            return

        # Ask: export all layers or only visible?
        msg = QMessageBox(self)
        msg.setWindowTitle("Export DXF")
        msg.setText("How would you like to export?")
        msg.setInformativeText(
            "Choose whether to include all layers or only the "
            "layers currently visible in the viewer."
        )
        btn_visible = msg.addButton("Visible Layers Only", QMessageBox.ButtonRole.AcceptRole)
        btn_all = msg.addButton("All Layers", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton(QMessageBox.StandardButton.Cancel)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == btn_visible:
            visible = self._layer_manager._get_visible_layers()
        elif clicked == btn_all:
            visible = None  # sentinel: export everything
        else:
            return

        suggested = suggest_output_path(self._document.file_path)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export DXF", str(suggested), EXPORT_FILE_FILTER
        )
        if not path:
            return

        try:
            if visible is None:
                # All layers — just copy/save the original DXF as-is
                export_all_layers(self._dxf_path, Path(path))
            else:
                export_filtered_dxf(self._dxf_path, Path(path), visible)
            self._status_bar.showMessage(f"Exported to {Path(path).name}", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n{e}")

    # ── Updates ───────────────────────────────────────────────

    def _check_for_updates(self) -> None:
        """Run update check in a background thread."""
        self._update_thread = QThread()
        self._update_worker = _UpdateCheckWorker()
        self._update_worker.moveToThread(self._update_thread)
        self._update_thread.started.connect(self._update_worker.run)
        self._update_worker.finished.connect(self._on_update_check_done)
        self._update_worker.finished.connect(self._update_thread.quit)
        self._update_thread.start()

    def _on_update_check_done(self, info) -> None:
        """Called when the background update check completes."""
        if info is None:
            return
        self._pending_update = info
        self._update_banner.show_update(info.version)

    def _manual_update_check(self) -> None:
        """User-triggered update check (Help menu)."""
        # Don't stack up multiple checks — ignore if one is already running
        if hasattr(self, "_manual_update_thread") and self._manual_update_thread and self._manual_update_thread.isRunning():
            return

        self._status_bar.showMessage("Checking for updates...")

        thread = QThread()
        worker = _UpdateCheckWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        # Keep references alive
        self._manual_update_thread = thread
        self._manual_update_worker = worker

        def on_done(info):
            thread.quit()
            thread.wait()
            if info is None:
                QMessageBox.information(
                    self, "Up to Date",
                    f"You are running the latest version (v{APP_VERSION}).",
                )
                self._status_bar.showMessage("No updates available.", 3000)
            else:
                self._pending_update = info
                self._update_banner.show_update(info.version)
                self._status_bar.showMessage(f"Update v{info.version} available!", 3000)

        worker.finished.connect(on_done)
        thread.start()

    def _apply_update(self) -> None:
        """Download and apply the pending update."""
        if not self._pending_update:
            return

        reply = QMessageBox.question(
            self,
            "Update Available",
            f"Download and install v{self._pending_update.version}?\n\n"
            "The application will close and restart automatically.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from app.updater import UpdateProgressDialog

        # Close the main window, then show a small progress dialog
        self.hide()

        dialog = UpdateProgressDialog(self._pending_update)
        dialog.start()
        dialog.exec()

        # If we get here, the update failed and the dialog was dismissed
        self.show()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h3>{APP_NAME}</h3>"
            f"<p>Version {APP_VERSION}</p>"
            f"<p>Built by Timco Engineering</p>",
        )

    # ── Layout override for banner positioning ────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Position the update banner at the top of the window, below menu/toolbar
        if hasattr(self, "_update_banner"):
            toolbar_bottom = 0
            for tb in self.findChildren(QToolBar):
                geo = tb.geometry()
                toolbar_bottom = max(toolbar_bottom, geo.bottom())
            menubar_bottom = self.menuBar().geometry().bottom()
            top = max(toolbar_bottom, menubar_bottom) + 1
            self._update_banner.setGeometry(0, top, self.width(), 36)
            self._update_banner.raise_()

    # ── Helpers ───────────────────────────────────────────────

    def _set_loading(self, loading: bool, message: str = "") -> None:
        self._progress.setVisible(loading)
        if loading:
            self._progress.setRange(0, 0)  # indeterminate
            self._status_bar.showMessage(message)
        self._act_open.setEnabled(not loading)
