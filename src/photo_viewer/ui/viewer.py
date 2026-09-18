from contextlib import suppress
from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPointF,
    QRectF,
    QRunnable,
    QSize,
    QSizeF,
    Qt,
    QThreadPool,
    QUrl,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QPainter, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoSink
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from photo_viewer.explorer import reveal_in_explorer
from photo_viewer.i18n import tr
from photo_viewer.imaging import load_photo
from photo_viewer.models import MediaItem, MediaKind
from photo_viewer.ui.theme import BACKGROUND, MUTED

_FADE_IN_MS = 160
_FADE_OUT_MS = 280


class _PhotoSignals(QObject):
    loaded = Signal(int, QImage)


class _PhotoTask(QRunnable):
    def __init__(self, token: int, path: Path, signals: _PhotoSignals) -> None:
        super().__init__()
        self._token = token
        self._path = path
        self._signals = signals

    def run(self) -> None:
        try:
            image = load_photo(self._path)
        except Exception:
            image = QImage()
        with suppress(RuntimeError):  # the viewer may have been closed while the photo was loading
            self._signals.loaded.emit(self._token, image)


class PhotoCanvas(QWidget):
    """Shows a photo and, on top of it, video frames whose opacity can be animated."""

    clicked = Signal()
    video_hidden = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._scaled = QPixmap()
        self._message = ""
        self._frame = QImage()
        self._video_opacity = 0.0
        self._fade = QVariantAnimation(self)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade.valueChanged.connect(self._set_video_opacity)
        self._fade.finished.connect(self._on_fade_finished)

    def show_message(self, message: str) -> None:
        self._pixmap = QPixmap()
        self._scaled = QPixmap()
        self._message = message
        self.update()

    def show_image(self, image: QImage) -> None:
        self._pixmap = QPixmap.fromImage(image)
        self._scaled = QPixmap()
        self._message = ""
        self.update()

    def show_video_frame(self, frame: QImage) -> None:
        self._frame = frame
        if self._video_opacity > 0:
            self.update()

    def fade_video_to(self, opacity: float, duration_ms: int) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._video_opacity)
        self._fade.setEndValue(opacity)
        self._fade.setDuration(duration_ms)
        self._fade.start()

    def clear_video(self) -> None:
        self._fade.stop()
        self._frame = QImage()
        self._video_opacity = 0.0
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.clicked.emit()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), BACKGROUND)
        if self._pixmap.isNull() and self._frame.isNull():
            painter.setPen(MUTED)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message)
            return
        if not self._pixmap.isNull():
            self._paint_photo(painter)
        if self._video_opacity > 0 and not self._frame.isNull():
            painter.setOpacity(self._video_opacity)
            painter.drawImage(self._fit(self._frame.size()), self._frame)

    def _paint_photo(self, painter: QPainter) -> None:
        target = self._fit(self._pixmap.size())
        ratio = self.devicePixelRatioF()
        physical = target.size().toSize() * ratio
        if self._scaled.size() != physical:
            self._scaled = self._pixmap.scaled(
                physical, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self._scaled.setDevicePixelRatio(ratio)
        painter.drawPixmap(target.topLeft(), self._scaled)

    def _fit(self, source: QSize) -> QRectF:
        size = QSizeF(source).scaled(QSizeF(self.size()), Qt.AspectRatioMode.KeepAspectRatio)
        origin = QPointF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2)
        return QRectF(origin, size)

    def _set_video_opacity(self, value: float) -> None:
        self._video_opacity = value
        self.update()

    def _on_fade_finished(self) -> None:
        if self._video_opacity == 0:
            self.video_hidden.emit()


class SeekSlider(QSlider):
    """Horizontal slider that jumps to the clicked position instead of paging towards it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            value = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), round(event.position().x()), self.width()
            )
            self.setValue(value)
            self.sliderMoved.emit(value)
        super().mousePressEvent(event)


def _format_time(milliseconds: int) -> str:
    minutes, seconds = divmod(max(milliseconds, 0) // 1000, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


class ClickableVideoWidget(QVideoWidget):
    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.clicked.emit()


class _LiveState(Enum):
    IDLE = auto()
    PLAYING = auto()
    FADING_OUT = auto()


class ViewerWindow(QDialog):
    def __init__(self, items: list[MediaItem], row: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("viewer.title"))
        self.setStyleSheet(f"QDialog {{ background: {BACKGROUND.name()}; }}")
        self._items = items
        self._row = row
        self._token = 0
        self._live_state = _LiveState.IDLE
        self._photo_signals = _PhotoSignals(self)
        self._photo_signals.loaded.connect(self._on_photo_loaded)

        self._canvas = PhotoCanvas()
        self._video = ClickableVideoWidget()
        self._canvas.clicked.connect(self._on_click)
        self._canvas.video_hidden.connect(self._on_video_hidden)
        self._video.clicked.connect(self._on_click)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._canvas)
        self._stack.addWidget(self._video)

        self._live_sink = QVideoSink(self)
        self._live_sink.videoFrameChanged.connect(self._on_live_frame)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(QAudioOutput(self))
        self._player.mediaStatusChanged.connect(self._on_media_status)

        self._caption = QLabel()
        self._caption.setObjectName("muted")
        self._live_button = self._make_button("● LIVE", self._toggle_live, primary=True)
        explorer_button = self._make_button(tr("menu.show_in_explorer"), self._reveal_in_explorer)
        previous_button = self._make_button("‹", lambda: self._show_row(self._row - 1))
        next_button = self._make_button("›", lambda: self._show_row(self._row + 1))

        self._transport = self._build_transport()

        bar = QHBoxLayout()
        bar.setContentsMargins(16, 8, 16, 12)
        bar.addWidget(self._live_button)
        bar.addWidget(explorer_button)
        bar.addWidget(self._caption, 1, Qt.AlignmentFlag.AlignCenter)
        bar.addWidget(previous_button)
        bar.addWidget(next_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._stack, 1)
        layout.addWidget(self._transport)
        layout.addLayout(bar)

        self.resize(QSize(1280, 860))
        self._show_row(row)

    @property
    def row(self) -> int:
        return self._row

    def keyPressEvent(self, event: QKeyEvent) -> None:
        match event.key():
            case Qt.Key.Key_Left:
                self._show_row(self._row - 1)
            case Qt.Key.Key_Right:
                self._show_row(self._row + 1)
            case Qt.Key.Key_Space:
                self._on_click()
            case _:
                super().keyPressEvent(event)

    def done(self, result: int) -> None:
        self._player.stop()
        super().done(result)

    def _build_transport(self) -> QWidget:
        self._play_button = self._make_button("▶", self._toggle_pause)
        self._play_button.setFixedWidth(44)
        self._elapsed = QLabel(_format_time(0))
        self._total = QLabel(_format_time(0))
        for label in (self._elapsed, self._total):
            label.setObjectName("muted")
        self._seek = SeekSlider()
        self._seek.sliderMoved.connect(self._player.setPosition)
        self._seek.sliderReleased.connect(lambda: self._player.setPosition(self._seek.value()))
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_playback_state)

        transport = QWidget()
        row = QHBoxLayout(transport)
        row.setContentsMargins(16, 8, 16, 0)
        row.setSpacing(12)
        row.addWidget(self._play_button)
        row.addWidget(self._elapsed)
        row.addWidget(self._seek, 1)
        row.addWidget(self._total)
        return transport

    def _on_position(self, position: int) -> None:
        self._elapsed.setText(_format_time(position))
        if not self._seek.isSliderDown():
            self._seek.setValue(position)

    def _on_duration(self, duration: int) -> None:
        self._seek.setRange(0, duration)
        self._total.setText(_format_time(duration))

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        self._play_button.setText("❚❚" if state is QMediaPlayer.PlaybackState.PlayingState else "▶")

    def _make_button(self, text: str, handler, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(handler)
        if primary:
            button.setObjectName("primary")
        return button

    def _reveal_in_explorer(self) -> None:
        reveal_in_explorer(self._items[self._row].path)

    def _show_row(self, row: int) -> None:
        if not 0 <= row < len(self._items):
            return
        self._row = row
        item = self._items[row]
        self._token += 1
        self._caption.setText(f"{item.name}   ·   {row + 1} / {len(self._items)}")
        self._live_button.setVisible(item.kind is MediaKind.LIVE)
        self._transport.setVisible(item.kind is MediaKind.VIDEO)
        self._player.stop()
        self._canvas.clear_video()
        self._live_state = _LiveState.IDLE

        if item.kind is MediaKind.VIDEO:
            self._play_video(item.path)
            return
        self._show_photo(item)
        if item.live_video is not None:
            self._prepare_live(item.live_video)

    def _show_photo(self, item: MediaItem) -> None:
        self._stack.setCurrentWidget(self._canvas)
        self._canvas.show_message(tr("viewer.loading"))
        task = _PhotoTask(self._token, item.path, self._photo_signals)
        QThreadPool.globalInstance().start(task)

    def _on_photo_loaded(self, token: int, image: QImage) -> None:
        if token != self._token:
            return
        if image.isNull():
            self._canvas.show_message(tr("viewer.cannot_display"))
        else:
            self._canvas.show_image(image)

    def _play_video(self, path: Path) -> None:
        self._player.setVideoOutput(self._video)
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._stack.setCurrentWidget(self._video)
        self._player.play()

    def _prepare_live(self, path: Path) -> None:
        """Loads the clip paused, so the first frame is ready and playback starts without a gap."""
        self._player.setVideoSink(self._live_sink)
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.pause()

    def _on_click(self) -> None:
        kind = self._items[self._row].kind
        if kind is MediaKind.LIVE:
            self._toggle_live()
        elif kind is MediaKind.VIDEO:
            self._toggle_pause()

    def _toggle_live(self) -> None:
        if self._live_state is _LiveState.PLAYING:
            self._player.pause()
            self._fade_out_live()
        else:
            self._live_state = _LiveState.PLAYING
            self._player.play()
            self._canvas.fade_video_to(1.0, _FADE_IN_MS)

    def _toggle_pause(self) -> None:
        if self._player.isPlaying():
            self._player.pause()
        else:
            self._player.play()

    def _fade_out_live(self) -> None:
        self._live_state = _LiveState.FADING_OUT
        self._canvas.fade_video_to(0.0, _FADE_OUT_MS)

    def _on_live_frame(self, frame: QVideoFrame) -> None:
        image = frame.toImage()
        if image.isNull():
            return
        self._canvas.show_video_frame(image)
        if self._live_state is _LiveState.PLAYING:
            remaining = self._player.duration() - frame.startTime() // 1000
            if remaining <= _FADE_OUT_MS:
                self._fade_out_live()

    def _on_video_hidden(self) -> None:
        if self._live_state is _LiveState.FADING_OUT:
            self._live_state = _LiveState.IDLE
            self._player.pause()
            self._player.setPosition(0)

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status is QMediaPlayer.MediaStatus.EndOfMedia and self._live_state is _LiveState.PLAYING:
            self._fade_out_live()
