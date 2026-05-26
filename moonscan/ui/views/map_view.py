"""
Graphical maps for the three navigable levels.

All three maps share the same underlying rendering — nodes (rounded rects with
title + subtitle) and edges (lines between nodes) on a QGraphicsScene with
pan + zoom. The differences are purely in what data they load and how they
color their nodes.

  - UniverseMapView:   nodes = regions,  edges = inter-region stargate links
  - RegionMapView:     nodes = systems,  edges = stargates inside the region
  - ConstellationMapView: nodes = systems, edges = stargates inside the constellation

Each view emits `node_clicked(int)` (region_id or system_id) which the main
window wires to drill-down.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsScene, QGraphicsView, QStyleOptionGraphicsItem,
    QWidget,
)

from ... import theme
from ...static_db import StaticDB


# ---------------------------------------------------------------------------
# Shared node rendering
# ---------------------------------------------------------------------------

@dataclass
class NodeSpec:
    """Everything the renderer needs to draw one map node."""
    node_id: int          # region_id or system_id, passed back on click
    title: str            # top line (region name / system name)
    subtitle: str = ""    # bottom line (counts, region tag, etc.)
    scanned: int = 0
    total: int = 0
    pos_x: float = 0.0    # raw EVE coords (any scale); projected to scene later
    pos_y: float = 0.0
    highlight: bool = False   # draw an accent ring (e.g. user's constellation)
    inactive: bool = False    # render dim (no progress, no assignment)


class MapNode(QGraphicsItem):
    """One rounded-rect node. Width/height set by the view to fit its data."""

    def __init__(self, spec: NodeSpec, width: float, height: float):
        super().__init__()
        self.spec = spec
        self.w = width
        self.h = height
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self._hover = False
        self.setZValue(10)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def boundingRect(self) -> QRectF:
        return QRectF(-self.w / 2, -self.h / 2, self.w, self.h)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        rect = self.boundingRect()
        s = self.spec

        if s.inactive:
            fill = theme.STATUS_OUT
        elif s.total > 0:
            fill = theme.progress_color(s.scanned, s.total)
        else:
            fill = theme.STATUS_OUT

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Border
        if self._hover or self.isSelected():
            pen = QPen(theme.ACCENT, 2.0)
        elif s.highlight:
            pen = QPen(theme.ACCENT, 1.6)
        else:
            pen = QPen(theme.MAP_NODE_BORDER, 1.0)
        painter.setPen(pen)
        painter.setBrush(QBrush(fill.darker(135)))
        painter.drawRoundedRect(rect, 6, 6)

        # Progress fill (clipped)
        if s.total > 0 and not s.inactive:
            ratio = min(1.0, s.scanned / s.total)
            bar = QRectF(rect.x(), rect.y(), rect.width() * ratio, rect.height())
            clip = QPainterPath()
            clip.addRoundedRect(rect, 6, 6)
            painter.save()
            painter.setClipPath(clip)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(fill))
            painter.drawRect(bar)
            painter.restore()
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 6, 6)

        # Text
        title_color = theme.TEXT_BRIGHT if not s.inactive else theme.TEXT_DIM
        sub_color = theme.TEXT if not s.inactive else theme.DISABLED
        font = QFont()
        font.setPointSize(9 if self.w < 100 else 10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(title_color)
        if s.subtitle:
            title_rect = QRectF(rect.x() + 6, rect.y() + 2, rect.width() - 12, rect.height() / 2 - 1)
        else:
            title_rect = rect.adjusted(6, 0, -6, 0)
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            s.title,
        )
        if s.subtitle:
            font.setBold(False)
            font.setPointSize(8 if self.w < 100 else 9)
            painter.setFont(font)
            painter.setPen(sub_color)
            sub_rect = QRectF(rect.x() + 6, rect.y() + rect.height() / 2, rect.width() - 12, rect.height() / 2 - 2)
            painter.drawText(
                sub_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                s.subtitle,
            )

    def hoverEnterEvent(self, event):
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, event):
        self._hover = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            scene = self.scene()
            if isinstance(scene, GraphMapScene):
                scene.node_clicked.emit(self.spec.node_id)
        super().mousePressEvent(event)


class GraphMapScene(QGraphicsScene):
    node_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(theme.MAP_BG))


class GraphMapView(QGraphicsView):
    """Generic pan + zoom graph view. Subclasses populate nodes/edges."""

    node_clicked = Signal(int)

    # Subclasses can override
    NODE_W = 130.0
    NODE_H = 44.0
    SCENE_W = 1400.0
    SCENE_H = 900.0
    SCENE_MARGIN = 100.0

    def __init__(self, static_db: StaticDB, parent=None):
        super().__init__(parent)
        self.static_db = static_db
        self._scene = GraphMapScene(self)
        self.setScene(self._scene)
        self._scene.node_clicked.connect(self.node_clicked.emit)

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setStyleSheet(f"background-color: {theme.MAP_BG.name()}; border: 0;")
        self._populated = False
        self._needs_initial_fit = False
        # Identity-based render caching: if we're asked to show the same
        # data we already have, skip the re-render so the user's zoom/pan
        # is preserved. mark_dirty() forces the next show to re-render.
        self._last_identity: object = None
        self._dirty: bool = True

        # Floating zoom controls (anchored to top-right of viewport)
        self._zoom_controls = _ZoomControls(self)
        self._zoom_controls.zoom_in.connect(lambda: self.scale(1.25, 1.25))
        self._zoom_controls.zoom_out.connect(lambda: self.scale(1 / 1.25, 1 / 1.25))
        self._zoom_controls.zoom_fit.connect(self.fit_view)

    def mark_dirty(self) -> None:
        """Force the next show_* call to re-render even if the identity matches."""
        self._dirty = True

    def _should_render(self, identity: object) -> bool:
        """Subclasses call this at the top of their show_* method.
        Returns False if we can keep the current scene (preserves zoom/pan)."""
        if self._dirty or identity != self._last_identity or not self._populated:
            self._dirty = False
            self._last_identity = identity
            return True
        return False

    def _populate(self, nodes: list[NodeSpec], edges: list[tuple[int, int]]) -> None:
        self._scene.clear()
        if not nodes:
            self._populated = False
            return

        # Project node positions to scene coordinates
        xs = [n.pos_x for n in nodes]
        ys = [n.pos_y for n in nodes]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        sw = self.SCENE_W - 2 * self.SCENE_MARGIN
        sh = self.SCENE_H - 2 * self.SCENE_MARGIN

        def project(x: float, y: float) -> QPointF:
            sx = self.SCENE_MARGIN + ((x - xmin) / (xmax - xmin) * sw if xmax > xmin else sw / 2)
            sy = self.SCENE_MARGIN + ((y - ymin) / (ymax - ymin) * sh if ymax > ymin else sh / 2)
            return QPointF(sx, self.SCENE_H - sy)

        positions: dict[int, QPointF] = {}
        for n in nodes:
            positions[n.node_id] = project(n.pos_x, n.pos_y)

        for a, b in edges:
            pa = positions.get(a)
            pb = positions.get(b)
            if pa is None or pb is None:
                continue
            line = self._scene.addLine(
                pa.x(), pa.y(), pb.x(), pb.y(),
                QPen(theme.MAP_EDGE_IN, 1.2),
            )
            line.setZValue(1)

        for n in nodes:
            p = positions[n.node_id]
            node = MapNode(n, self.NODE_W, self.NODE_H)
            node.setPos(p)
            self._scene.addItem(node)

        self._scene.setSceneRect(QRectF(
            -50, -50,
            self.SCENE_W + 100, self.SCENE_H + 100,
        ))
        self._populated = True
        # Defer fit until the view has actual geometry; if we're already visible
        # we can fit immediately, otherwise the first showEvent will do it.
        if self.viewport().width() > 0:
            self.fit_view()
        else:
            self._needs_initial_fit = True

    def fit_view(self) -> None:
        if self._populated:
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self._needs_initial_fit = False

    def showEvent(self, event):
        super().showEvent(event)
        if self._needs_initial_fit:
            self.fit_view()
        self._zoom_controls.reposition()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._zoom_controls.reposition()
        # Intentionally NO refit here — preserves the user's zoom/pan

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.25 if event.angleDelta().y() > 0 else 1 / 1.25
        self.scale(factor, factor)


class _ZoomControls(QWidget):
    """Floating +/-/fit buttons anchored to top-right of the parent view."""
    zoom_in = Signal()
    zoom_out = Signal()
    zoom_fit = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"background: {theme.BG_ALT.name()}; "
            f"border: 1px solid {theme.BORDER.name()}; "
            f"border-radius: 4px;"
        )
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QToolTip  # local import
        h = QHBoxLayout(self)
        h.setContentsMargins(2, 2, 2, 2)
        h.setSpacing(0)

        def mkbtn(label: str, tooltip: str, signal):
            b = QPushButton(label)
            b.setFixedSize(28, 24)
            b.setFlat(True)
            b.setToolTip(tooltip)
            b.setStyleSheet(
                f"QPushButton {{ color: {theme.TEXT.name()}; background: transparent; "
                f"border: none; font-weight: bold; }}"
                f"QPushButton:hover {{ background: {theme.ACCENT_DIM.name()}; }}"
            )
            b.clicked.connect(signal.emit)
            return b

        h.addWidget(mkbtn("−", "Zoom out", self.zoom_out))
        h.addWidget(mkbtn("⛶", "Fit to view", self.zoom_fit))
        h.addWidget(mkbtn("+", "Zoom in", self.zoom_in))
        self.adjustSize()
        self.raise_()

    def reposition(self) -> None:
        if self.parent() is None:
            return
        parent: QWidget = self.parent()  # type: ignore[assignment]
        margin = 8
        x = parent.width() - self.width() - margin
        self.move(max(margin, x), margin)
        self.raise_()


# ---------------------------------------------------------------------------
# Universe map — all 70 navigable regions
# ---------------------------------------------------------------------------

class UniverseMapView(GraphMapView):
    NODE_W = 110.0
    NODE_H = 30.0
    SCENE_W = 1800.0
    SCENE_H = 1300.0

    def show_universe(self, user_region_id: int | None = None) -> None:
        if not self._should_render(("universe", user_region_id)):
            return
        positions = self.static_db.region_positions()
        regions = self.static_db.regions_with_positions()
        nodes: list[NodeSpec] = []
        for r in regions:
            pos = positions.get(r["region_id"])
            if pos is None:
                continue
            spec = NodeSpec(
                node_id=r["region_id"],
                title=r["name"],
                subtitle="",
                pos_x=pos[0],
                pos_y=pos[1],
                highlight=(r["region_id"] == user_region_id),
                inactive=False,
            )
            nodes.append(spec)
        edges = self.static_db.region_connections()
        self._populate(nodes, edges)


# ---------------------------------------------------------------------------
# Region map — all systems in a region
# ---------------------------------------------------------------------------

class RegionMapView(GraphMapView):
    NODE_W = 75.0
    NODE_H = 28.0
    SCENE_W = 1600.0
    SCENE_H = 1200.0

    def show_region(
        self,
        region_id: int,
        user_constellation_id: int | None = None,
        scan_counts: dict[int, tuple[int, int]] | None = None,
        assigned_system_ids: set[int] | None = None,
    ) -> None:
        scan_counts = scan_counts or {}
        assigned_system_ids = assigned_system_ids or set()
        identity = (
            "region", region_id, user_constellation_id,
            frozenset(assigned_system_ids),
            frozenset((k, v) for k, v in scan_counts.items()),
        )
        if not self._should_render(identity):
            return

        systems = self.static_db.systems_in_region(region_id)
        nodes: list[NodeSpec] = []
        for s in systems:
            if s["x_2d"] is None or s["y_2d"] is None:
                continue
            in_assignment = s["system_id"] in assigned_system_ids
            in_user_constellation = (
                user_constellation_id is not None
                and s["constellation_id"] == user_constellation_id
            )
            scanned, total = scan_counts.get(s["system_id"], (0, 0))
            if not in_assignment:
                total = 0
            nodes.append(NodeSpec(
                node_id=s["system_id"],
                title=s["name"],
                subtitle=(f"{scanned} / {total}" if total > 0 else ""),
                scanned=scanned,
                total=total,
                pos_x=s["x_2d"],
                pos_y=s["y_2d"],
                highlight=in_user_constellation,
                inactive=not in_user_constellation and not in_assignment,
            ))

        # Stargates: only edges whose endpoints are both rendered
        rendered = {n.node_id for n in nodes}
        edges = [
            (a, b)
            for a, b in self.static_db.stargates_in_region(region_id)
            if a in rendered and b in rendered
        ]
        self._populate(nodes, edges)


# ---------------------------------------------------------------------------
# Constellation map — current "level 1" view
# ---------------------------------------------------------------------------

class ConstellationMapView(GraphMapView):
    NODE_W = 130.0
    NODE_H = 44.0
    SCENE_W = 900.0
    SCENE_H = 600.0

    def show_constellation(
        self,
        constellation_id: int,
        scan_counts: dict[int, tuple[int, int]],
        assigned_system_ids: set[int],
    ) -> None:
        identity = (
            "constellation", constellation_id,
            frozenset(assigned_system_ids),
            frozenset((k, v) for k, v in scan_counts.items()),
        )
        if not self._should_render(identity):
            return

        systems = self.static_db.systems_in_constellation(constellation_id)
        nodes: list[NodeSpec] = []
        for s in systems:
            # Use 2D coords if present; fall back to 3D (x, z) for K-space edge cases
            if s["x"] is None:
                continue
            # Try the 2D coords first
            two_d = self.static_db.system_2d(s["system_id"])
            if two_d is not None:
                px, py = two_d
            else:
                px, py = s["x"], s["z"]
            scanned, total = scan_counts.get(s["system_id"], (0, 0))
            in_assignment = s["system_id"] in assigned_system_ids
            if not in_assignment:
                total = 0
            nodes.append(NodeSpec(
                node_id=s["system_id"],
                title=s["name"],
                subtitle=(f"{scanned} / {total}" if total > 0 else "(not assigned)"),
                scanned=scanned,
                total=total,
                pos_x=px,
                pos_y=py,
                highlight=False,
                inactive=not in_assignment,
            ))

        in_const_ids = {n.node_id for n in nodes}
        edges = [
            (a, b)
            for a, b in self.static_db.stargates_in_constellation(constellation_id)
            if a in in_const_ids and b in in_const_ids
        ]
        self._populate(nodes, edges)
