from contextlib import suppress
from itertools import count

from PySide6.QtCore import (
    QAbstractListModel,
    QEasingCurve,
    QModelIndex,
    QObject,
    QPoint,
    QPointF,
    QRectF,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPixmapCache,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from photo_viewer.models import MediaItem, MediaKind
from photo_viewer.thumbnails import ThumbnailCache
from photo_viewer.ui.theme import ACCENT, PLACEHOLDER

TILE_MIN, TILE_MAX, TILE_DEFAULT = 120, 320, 200
_PIXMAP_CACHE_KB = 256 * 1024
_WHEEL_ANGLE_PER_NOTCH = 120
_WHEEL_NOTCH_ROWS = 0.8
_WHEEL_ANIMATION_MS = 260
_VISIBLE_PRIORITY = 2_000_000
_NEAR_PRIORITY = 1_000_000
_PREFETCH_SCREENS = 3
_PREFETCH_DELAY_MS = 120
_WRAP_SLACK = 2  # QListView wraps a row whose tiles exactly fill the viewport
_BADGE_BACKGROUND = QColor(0, 0, 0, 150)


class _ThumbnailSignals(QObject):
    ready = Signal(str, QImage)
    failed = Signal(str)


class _ThumbnailTask(QRunnable):
    def __init__(self, item: MediaItem, cache: ThumbnailCache, signals: _ThumbnailSignals) -> None:
        super().__init__()
        self._item = item
        self._cache = cache
        self._signals = signals

    def run(self) -> None:
        key = str(self._item.path)
        try:
            self._signals.ready.emit(key, self._cache.load(self._item))
        except Exception:
            self._signals.failed.emit(key)


class _WarmTask(QRunnable):
    """Renders a thumbnail into the disk cache ahead of time, without touching the UI."""

    def __init__(self, item: MediaItem, cache: ThumbnailCache) -> None:
        super().__init__()
        self._item = item
        self._cache = cache

    def run(self) -> None:
        with suppress(Exception):  # a broken file is reported when its tile is actually requested
            self._cache.ensure(self._item)


class GalleryModel(QAbstractListModel):
    """Thumbnails are requested in three tiers: visible tiles, tiles near the screen, the rest."""

    ITEM_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, cache: ThumbnailCache, parent: QObject | None = None) -> None:
        super().__init__(parent)
        QPixmapCache.setCacheLimit(_PIXMAP_CACHE_KB)
        self._cache = cache
        self._items: list[MediaItem] = []
        self._rows: dict[str, int] = {}
        self._inflight: set[str] = set()
        self._failed: set[str] = set()
        self._prefetched: set[str] = set()
        self._priority = count()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(cache.workers)
        self._signals = _ThumbnailSignals(self)
        self._signals.ready.connect(self._on_ready)
        self._signals.failed.connect(self._on_failed)

    @property
    def items(self) -> list[MediaItem]:
        return self._items

    def set_items(self, items: list[MediaItem]) -> None:
        self._pool.clear()
        self.beginResetModel()
        self._items = items
        self._rows = {str(item.path): row for row, item in enumerate(items)}
        self._inflight.clear()
        self._failed.clear()
        self._prefetched.clear()
        self.endResetModel()
        for row, item in enumerate(items):
            self._pool.start(_WarmTask(item, self._cache), -row)

    def prefetch(self, first: int, last: int) -> None:
        """Moves the tiles around the visible rows `first..last` ahead of the background queue."""
        margin = (last - first + 1) * _PREFETCH_SCREENS
        middle = (first + last) // 2
        for row in range(max(0, first - margin), min(len(self._items), last + 1 + margin)):
            key = str(self._items[row].path)
            if key not in self._prefetched:
                self._prefetched.add(key)
                self._pool.start(_WarmTask(self._items[row], self._cache), _NEAR_PRIORITY - abs(row - middle))

    def shutdown(self) -> None:
        self._pool.clear()

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        item = self._items[index.row()]
        match role:
            case self.ITEM_ROLE:
                return item
            case Qt.ItemDataRole.DecorationRole:
                return self._pixmap(item)
            case Qt.ItemDataRole.ToolTipRole:
                return item.name
        return None

    def _pixmap(self, item: MediaItem) -> QPixmap | None:
        key = str(item.path)
        pixmap = QPixmapCache.find(key)
        if pixmap is None and key not in self._inflight and key not in self._failed:
            self._inflight.add(key)
            task = _ThumbnailTask(item, self._cache, self._signals)
            self._pool.start(task, _VISIBLE_PRIORITY + next(self._priority))
        return pixmap

    def _on_ready(self, key: str, image: QImage) -> None:
        self._inflight.discard(key)
        QPixmapCache.insert(key, QPixmap.fromImage(image))
        self._notify(key)

    def _on_failed(self, key: str) -> None:
        self._inflight.discard(key)
        self._failed.add(key)

    def _notify(self, key: str) -> None:
        row = self._rows.get(key)
        if row is not None:
            index = self.index(row)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])


class TileDelegate(QStyledItemDelegate):
    _MARGIN = 2
    _RADIUS = 6

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.tile_size = TILE_DEFAULT

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        item: MediaItem = index.data(GalleryModel.ITEM_ROLE)
        pixmap: QPixmap | None = index.data(Qt.ItemDataRole.DecorationRole)
        rect = QRectF(option.rect.adjusted(self._MARGIN, self._MARGIN, -self._MARGIN, -self._MARGIN))

        painter.save()
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(rect, self._RADIUS, self._RADIUS)
        painter.setClipPath(clip)
        if pixmap is None:
            painter.fillPath(clip, PLACEHOLDER)
        else:
            painter.drawPixmap(rect.toRect(), pixmap)

        badge_origin = rect.topLeft() + QPointF(8, 8)
        match item.kind:
            case MediaKind.LIVE:
                _paint_live_badge(painter, badge_origin)
            case MediaKind.VIDEO:
                _paint_video_badge(painter, badge_origin)

        if option.state & QStyle.StateFlag.State_Selected:
            painter.setClipping(False)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(ACCENT, 3))
            painter.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), self._RADIUS, self._RADIUS)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(self.tile_size, self.tile_size)


def _paint_live_badge(painter: QPainter, origin: QPointF) -> None:
    pill = QRectF(origin, QSize(58, 22))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_BADGE_BACKGROUND)
    painter.drawRoundedRect(pill, 11, 11)

    center = QPointF(pill.left() + 12, pill.center().y())
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(Qt.GlobalColor.white, 1.4))
    painter.drawEllipse(center, 6.5, 6.5)
    painter.drawEllipse(center, 3.2, 3.2)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(Qt.GlobalColor.white)
    painter.drawEllipse(center, 1.1, 1.1)

    font = QFont(painter.font())
    font.setPixelSize(10)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(Qt.GlobalColor.white)
    painter.drawText(pill.adjusted(24, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, "LIVE")


def _paint_video_badge(painter: QPainter, origin: QPointF) -> None:
    pill = QRectF(origin, QSize(26, 22))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_BADGE_BACKGROUND)
    painter.drawRoundedRect(pill, 11, 11)
    center = pill.center()
    triangle = QPolygonF(
        [
            QPointF(center.x() - 3, center.y() - 5),
            QPointF(center.x() - 3, center.y() + 5),
            QPointF(center.x() + 5, center.y()),
        ]
    )
    painter.setBrush(QBrush(Qt.GlobalColor.white))
    painter.drawPolygon(triangle)


class GalleryView(QListView):
    """Icon grid whose tiles are stretched so that every row fills the whole width."""

    def __init__(self, model: GalleryModel, parent=None) -> None:
        super().__init__(parent)
        self.setModel(model)
        self._delegate = TileDelegate(self)
        self._preferred_size = TILE_DEFAULT
        self.setItemDelegate(self._delegate)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)

        self._scroll_target = 0
        self._scroll_animation = QVariantAnimation(self)
        self._scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._scroll_animation.setDuration(_WHEEL_ANIMATION_MS)
        self._scroll_animation.valueChanged.connect(self.verticalScrollBar().setValue)
        self.verticalScrollBar().sliderPressed.connect(self._scroll_animation.stop)

        self._prefetch_timer = QTimer(self)
        self._prefetch_timer.setSingleShot(True)
        self._prefetch_timer.setInterval(_PREFETCH_DELAY_MS)
        self._prefetch_timer.timeout.connect(self._prefetch)
        self.verticalScrollBar().valueChanged.connect(self._prefetch_timer.start)
        model.modelReset.connect(self._prefetch_timer.start)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not event.pixelDelta().isNull():
            super().wheelEvent(event)
            return
        bar = self.verticalScrollBar()
        running = self._scroll_animation.state() is QVariantAnimation.State.Running
        origin = self._scroll_target if running else bar.value()
        notches = event.angleDelta().y() / _WHEEL_ANGLE_PER_NOTCH
        step = self._delegate.tile_size * _WHEEL_NOTCH_ROWS
        self._scroll_target = round(min(max(origin - notches * step, bar.minimum()), bar.maximum()))
        self._scroll_animation.stop()
        self._scroll_animation.setStartValue(bar.value())
        self._scroll_animation.setEndValue(self._scroll_target)
        self._scroll_animation.start()
        event.accept()

    def set_tile_size(self, preferred_size: int) -> None:
        self._preferred_size = preferred_size
        self._fit_tiles()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_tiles()

    def _prefetch(self) -> None:
        count = self.model().rowCount()
        if not count:
            return
        area = self.viewport().rect()
        first = self.indexAt(QPoint(area.left() + 1, area.top() + 1))
        last = self.indexAt(QPoint(area.right() - 1, area.bottom() - 1))
        self.model().prefetch(
            first.row() if first.isValid() else 0, last.row() if last.isValid() else count - 1
        )

    def _fit_tiles(self) -> None:
        available = self.width() - 2 * self.frameWidth() - self.verticalScrollBar().sizeHint().width()
        if available <= 0:
            return
        columns = max(1, round(available / self._preferred_size))
        size = (available - _WRAP_SLACK) // columns
        spare = available - columns * size - _WRAP_SLACK
        self.setViewportMargins(spare // 2, 0, spare - spare // 2, 0)
        if size != self._delegate.tile_size:
            self._delegate.tile_size = size
            self.setGridSize(QSize(size, size))
            self.doItemsLayout()
            self._prefetch_timer.start()
