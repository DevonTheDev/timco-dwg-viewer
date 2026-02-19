"""Layer management panel with checkboxes, filter, and presets."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPixmap, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)

from ezdxf.colors import DXF_DEFAULT_COLORS, int2rgb

from app.config import PRESETS_DIR
from app.models import LayerInfo, LayerPreset

# ACI color 7 is white on dark backgrounds — swap to light gray so the swatch is visible
_SWATCH_SIZE = 12


def _aci_to_qcolor(aci: int) -> QColor:
    """Convert a DXF ACI color index to a QColor."""
    if aci < 0 or aci > 255:
        aci = 7
    raw = DXF_DEFAULT_COLORS[aci]
    rgb = int2rgb(raw)
    # ACI 7 is pure white — make it light gray so the swatch shows on white backgrounds
    if aci == 7:
        return QColor(200, 200, 200)
    return QColor(rgb.r, rgb.g, rgb.b)


def _make_swatch_icon(color: QColor) -> QIcon:
    """Create a small colored square icon for a layer."""
    pm = QPixmap(_SWATCH_SIZE, _SWATCH_SIZE)
    pm.fill(color)
    return QIcon(pm)


class LayerManagerWidget(QWidget):
    """Panel for toggling DXF layer visibility with presets."""

    visibility_changed = Signal(set)  # set of visible layer names

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layers: dict[str, LayerInfo] = {}
        self._checkboxes: dict[str, QCheckBox] = {}

        self._build_ui()
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # Filter
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter layers...")
        self._filter_edit.textChanged.connect(self._apply_filter)
        main_layout.addWidget(self._filter_edit)

        # Select All / None / Invert buttons
        btn_row = QHBoxLayout()
        self._btn_all = QPushButton("All")
        self._btn_none = QPushButton("None")
        self._btn_invert = QPushButton("Invert")
        self._btn_all.clicked.connect(self._select_all)
        self._btn_none.clicked.connect(self._select_none)
        self._btn_invert.clicked.connect(self._select_invert)
        btn_row.addWidget(self._btn_all)
        btn_row.addWidget(self._btn_none)
        btn_row.addWidget(self._btn_invert)
        main_layout.addLayout(btn_row)

        # Scrollable checkbox area
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_widget = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_widget)
        self._scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll_area.setWidget(self._scroll_widget)
        main_layout.addWidget(self._scroll_area, stretch=1)

        # Presets section
        main_layout.addWidget(QLabel("Presets:"))
        self._preset_combo = QComboBox()
        main_layout.addWidget(self._preset_combo)

        preset_btn_row = QHBoxLayout()
        self._btn_load = QPushButton("Load")
        self._btn_save = QPushButton("Save")
        self._btn_delete = QPushButton("Delete")
        self._btn_load.clicked.connect(self._load_preset)
        self._btn_save.clicked.connect(self._save_preset)
        self._btn_delete.clicked.connect(self._delete_preset)
        preset_btn_row.addWidget(self._btn_load)
        preset_btn_row.addWidget(self._btn_save)
        preset_btn_row.addWidget(self._btn_delete)
        main_layout.addLayout(preset_btn_row)

        self._refresh_preset_list()
        self._set_controls_enabled(False)

    def set_layers(self, layers: dict[str, LayerInfo]) -> None:
        """Populate the panel with layers from a loaded drawing."""
        # Only include layers that actually have entities
        self._layers = {
            name: info for name, info in layers.items()
            if info.entity_count > 0
        }
        self._rebuild_checkboxes()
        self._set_controls_enabled(True)

    def _rebuild_checkboxes(self) -> None:
        """Rebuild all layer checkboxes with color swatches."""
        # Clear existing — remove from layout first, then delete
        for cb in self._checkboxes.values():
            self._scroll_layout.removeWidget(cb)
            cb.deleteLater()
        self._checkboxes.clear()

        # Sort layers alphabetically
        for name in sorted(self._layers.keys()):
            info = self._layers[name]
            label = f"{name} ({info.entity_count})"
            cb = QCheckBox(label)
            cb.setChecked(info.is_visible)
            cb.setIcon(_make_swatch_icon(_aci_to_qcolor(info.color)))
            cb.stateChanged.connect(self._on_checkbox_changed)
            self._scroll_layout.addWidget(cb)
            self._checkboxes[name] = cb

        self._apply_filter()

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._filter_edit.setEnabled(enabled)
        self._btn_all.setEnabled(enabled)
        self._btn_none.setEnabled(enabled)
        self._btn_invert.setEnabled(enabled)
        self._btn_load.setEnabled(enabled)
        self._btn_save.setEnabled(enabled)
        self._btn_delete.setEnabled(enabled)

    def _apply_filter(self) -> None:
        text = self._filter_edit.text().lower()
        for name, cb in self._checkboxes.items():
            cb.setVisible(text == "" or text in name.lower())

    def _get_visible_layers(self) -> set[str]:
        return {name for name, cb in self._checkboxes.items() if cb.isChecked()}

    def _emit_visibility(self) -> None:
        self.visibility_changed.emit(self._get_visible_layers())

    def _on_checkbox_changed(self) -> None:
        self._emit_visibility()

    def hide_layer(self, layer_name: str) -> None:
        """Uncheck a layer by name (called from viewer right-click)."""
        cb = self._checkboxes.get(layer_name)
        if cb and cb.isChecked():
            cb.setChecked(False)  # triggers stateChanged → _emit_visibility

    # Selection helpers
    def _select_all(self) -> None:
        for cb in self._checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
        self._emit_visibility()

    def _select_none(self) -> None:
        for cb in self._checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self._emit_visibility()

    def _select_invert(self) -> None:
        for cb in self._checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(not cb.isChecked())
            cb.blockSignals(False)
        self._emit_visibility()

    # Presets
    def _refresh_preset_list(self) -> None:
        self._preset_combo.clear()
        for path in sorted(PRESETS_DIR.glob("*.json")):
            self._preset_combo.addItem(path.stem, str(path))

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        # Sanitize: remove characters that are invalid in Windows filenames
        name = "".join(c for c in name if c not in r'\/:*?"<>|')
        if not name:
            return
        preset = LayerPreset(
            name=name,
            visible_layers=self._get_visible_layers(),
        )
        path = PRESETS_DIR / f"{name}.json"
        path.write_text(
            json.dumps({"name": preset.name, "visible_layers": sorted(preset.visible_layers)}, indent=2),
            encoding="utf-8",
        )
        self._refresh_preset_list()
        # Select the newly saved preset
        idx = self._preset_combo.findText(name)
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)

    def _load_preset(self) -> None:
        path_str = self._preset_combo.currentData()
        if not path_str:
            return
        path = Path(path_str)
        if not path.is_file():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        visible = set(data.get("visible_layers", []))

        for name, cb in self._checkboxes.items():
            cb.blockSignals(True)
            cb.setChecked(name in visible)
            cb.blockSignals(False)

        self._emit_visibility()

    def _delete_preset(self) -> None:
        path_str = self._preset_combo.currentData()
        if not path_str:
            return
        path = Path(path_str)
        name = path.stem
        reply = QMessageBox.question(
            self,
            "Delete Preset",
            f"Delete preset '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            path.unlink(missing_ok=True)
            self._refresh_preset_list()
