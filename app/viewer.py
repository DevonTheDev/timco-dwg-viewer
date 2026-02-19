"""DXF viewer widget using ezdxf's PyQtBackend rendering pipeline."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPointF, QEvent
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QMenu,
    QVBoxLayout,
    QWidget,
)

import ezdxf
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.pyqt import PyQtBackend
from ezdxf.addons.drawing.config import Configuration
from ezdxf.addons.drawing.properties import LayoutProperties
from ezdxf.entities import DXFGraphic

from app.config import BACKGROUND_COLOR, ZOOM_FACTOR

# Max wheel-zoom steps in either direction from the fit level.
# 300 steps at 1.15× per step ≈ 10^18× range — more than enough.
MAX_ZOOM_STEPS = 300

# Zoom step threshold above which antialiasing is disabled for performance.
AA_DISABLE_THRESHOLD = 50

# Padding factor for scene rect (fraction of drawing size added on each side).
SCENE_PADDING_FACTOR = 0.5

# Data key used on QGraphicsItems to store their source layer name
LAYER_DATA_KEY = 0


class TaggingScene(QGraphicsScene):
    """QGraphicsScene that automatically tags every added item with a layer name."""

    def __init__(self):
        super().__init__()
        self._current_layer: str | None = None

    def addItem(self, item) -> None:
        super().addItem(item)
        if self._current_layer is not None:
            item.setData(LAYER_DATA_KEY, self._current_layer)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        item.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)


class TaggingFrontend(Frontend):
    """Frontend subclass that tells the scene which layer is being drawn."""

    def __init__(self, ctx, out, config, scene: TaggingScene):
        super().__init__(ctx, out, config=config)
        self._tagging_scene = scene

    def override_properties(self, entity: DXFGraphic, properties) -> None:
        self._tagging_scene._current_layer = entity.dxf.get("layer", "0")


class CADGraphicsView(QGraphicsView):
    """QGraphicsView with pan (left-drag or middle-drag), wheel zoom, and
    right-click layer identification."""

    hide_layer_requested = Signal(str)  # layer name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHints(
            self.renderHints()
            | self.renderHints().__class__.Antialiasing
            | self.renderHints().__class__.SmoothPixmapTransform
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QColor(BACKGROUND_COLOR))
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate
        )
        self._middle_dragging = False
        self._middle_last_pos = QPointF()
        self._zoom_step = 0  # relative to fit level
        self._aa_enabled = True  # tracks whether antialiasing is active

    # ── Select mode ──────────────────────────────────────────

    def set_select_mode(self, enabled: bool) -> None:
        """Toggle between rubber-band selection and scroll-hand pan."""
        if enabled:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Delete:
            scene = self.scene()
            if scene:
                for item in scene.selectedItems():
                    scene.removeItem(item)
            event.accept()
        else:
            super().keyPressEvent(event)

    # ── Right-click context menu ─────────────────────────────

    def contextMenuEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        if item is None:
            return

        # Walk up to parent if this item has no layer tag (e.g. child of a group)
        layer = item.data(LAYER_DATA_KEY)
        while layer is None and item.parentItem():
            item = item.parentItem()
            layer = item.data(LAYER_DATA_KEY)

        if not layer:
            return

        menu = QMenu(self)
        hide_action = menu.addAction(f"Hide layer: {layer}")
        chosen = menu.exec(event.globalPos())
        if chosen == hide_action:
            self.hide_layer_requested.emit(layer)

    # ── Middle-mouse-button pan ──────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._middle_dragging = True
            self._middle_last_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._middle_dragging:
            delta = event.position() - self._middle_last_pos
            self._middle_last_pos = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._middle_dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def focusOutEvent(self, event) -> None:
        """Reset middle-drag state if the view loses focus (e.g. Alt+Tab)."""
        if self._middle_dragging:
            self._middle_dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().focusOutEvent(event)

    # ── Wheel zoom ───────────────────────────────────────────

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Zoom in/out anchored under the mouse cursor."""
        if event.angleDelta().y() > 0:
            if self._zoom_step < MAX_ZOOM_STEPS:
                self.scale(ZOOM_FACTOR, ZOOM_FACTOR)
                self._zoom_step += 1
        else:
            if self._zoom_step > -MAX_ZOOM_STEPS:
                self.scale(1.0 / ZOOM_FACTOR, 1.0 / ZOOM_FACTOR)
                self._zoom_step -= 1
        self._update_aa()

    def do_zoom_in(self) -> None:
        """Single zoom-in step (for toolbar button)."""
        if self._zoom_step < MAX_ZOOM_STEPS:
            self.scale(ZOOM_FACTOR, ZOOM_FACTOR)
            self._zoom_step += 1

    def do_zoom_out(self) -> None:
        """Single zoom-out step (for toolbar button)."""
        if self._zoom_step > -MAX_ZOOM_STEPS:
            self.scale(1.0 / ZOOM_FACTOR, 1.0 / ZOOM_FACTOR)
            self._zoom_step -= 1

    # ── Antialiasing toggle ────────────────────────────────

    def _update_aa(self) -> None:
        """Disable antialiasing at high zoom for performance; re-enable when low."""
        should_aa = self._zoom_step < AA_DISABLE_THRESHOLD
        if should_aa != self._aa_enabled:
            self._aa_enabled = should_aa
            self.setRenderHint(QPainter.RenderHint.Antialiasing, should_aa)
            self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, should_aa)

    # ── Fit ──────────────────────────────────────────────────

    def fit_drawing(self) -> None:
        """Fit the entire scene into the view, correcting DXF Y-up to screen Y-down."""
        scene = self.scene()
        if scene and not scene.itemsBoundingRect().isEmpty():
            self.fitInView(scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.scale(1, -1)  # DXF Y-up → screen Y-down
            self._zoom_step = 0
            self._update_aa()


class DXFViewerWidget(QWidget):
    """Widget that renders a DXF document with layer filtering."""

    render_started = Signal()
    render_finished = Signal()
    hide_layer_requested = Signal(str)  # bubbled up from the view

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc: ezdxf.document.Drawing | None = None
        self._visible_layers: set[str] | None = None  # None = all visible
        self._flipped = False

        self._view = CADGraphicsView()
        self._scene = TaggingScene()
        self._view.setScene(self._scene)

        # Bubble the view's hide signal up
        self._view.hide_layer_requested.connect(self.hide_layer_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

    @property
    def view(self) -> CADGraphicsView:
        return self._view

    def set_document(self, doc: ezdxf.document.Drawing) -> None:
        """Set the DXF document and render it."""
        self._doc = doc
        self._visible_layers = None
        self._render()

    def set_visible_layers(self, layers: set[str]) -> None:
        """Update which layers are visible and re-render."""
        self._visible_layers = layers
        self._render()

    def _render(self) -> None:
        """Render the current document with layer filtering."""
        if self._doc is None:
            return

        self.render_started.emit()

        msp = self._doc.modelspace()

        # Force all layers on in the document so the RenderContext doesn't
        # suppress entities from layers marked "off" in the DXF file.
        # Our filter_func is the sole authority on layer visibility.
        for layer_entry in self._doc.layers:
            layer_entry.on()

        ctx = RenderContext(self._doc)

        new_scene = TaggingScene()
        new_scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        backend = PyQtBackend(new_scene)

        config = Configuration(
            lineweight_scaling=0.5,
        )

        # Set dark background
        layout_props = LayoutProperties.from_layout(msp)
        layout_props.set_colors(BACKGROUND_COLOR)

        frontend = TaggingFrontend(ctx, backend, config=config, scene=new_scene)

        visible = self._visible_layers

        def layer_filter(entity: DXFGraphic) -> bool:
            if visible is None:
                return True
            return entity.dxf.get("layer", "0") in visible

        frontend.draw_layout(
            msp,
            finalize=True,
            filter_func=layer_filter,
            layout_properties=layout_props,
        )
        new_scene._current_layer = None

        old_scene = self._view.scene()
        self._view.setScene(new_scene)
        self._scene = new_scene
        if old_scene and old_scene is not new_scene:
            old_scene.deleteLater()

        # Expand the scene rect so users can pan past drawing edges.
        self._apply_scene_padding(new_scene)

        self.render_finished.emit()

    @staticmethod
    def _apply_scene_padding(scene: TaggingScene) -> None:
        """Expand the scene rect so users can pan past drawing edges."""
        items_rect = scene.itemsBoundingRect()
        if items_rect.isEmpty():
            return
        pad_w = items_rect.width() * SCENE_PADDING_FACTOR
        pad_h = items_rect.height() * SCENE_PADDING_FACTOR
        scene.setSceneRect(items_rect.adjusted(-pad_w, -pad_h, pad_w, pad_h))

    def fit_drawing(self) -> None:
        self._apply_scene_padding(self._scene)
        self._view.fit_drawing()
        # Re-apply the user's manual flip on top of the default correction
        if self._flipped:
            self._view.scale(1, -1)

    def zoom_in(self) -> None:
        self._view.do_zoom_in()

    def zoom_out(self) -> None:
        self._view.do_zoom_out()

    def flip_vertical(self) -> None:
        """Flip the view upside-down (toggles)."""
        self._flipped = not self._flipped
        self._view.scale(1, -1)

    @property
    def is_flipped(self) -> bool:
        return self._flipped
