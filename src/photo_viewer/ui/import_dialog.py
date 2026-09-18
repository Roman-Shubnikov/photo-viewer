import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from photo_viewer.i18n import tr
from photo_viewer.importer import ImportThread

_PROGRESS_STEPS = 10_000
_SPEED_WINDOW_S = 4.0
_TEXT_REFRESH_MS = 100
_STATUS_LINES = 3
_KIB = 1024
_MIB = _KIB**2
_GIB = _KIB**3


def _format_size(size: float) -> str:
    if size >= _GIB:
        return f"{size / _GIB:.1f} {tr('unit.gb')}"
    if size >= _MIB:
        return f"{size / _MIB:.0f} {tr('unit.mb')}"
    return f"{size / _KIB:.0f} {tr('unit.kb')}"


class ImportDialog(QDialog):
    def __init__(self, destination: Path | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("import.title"))
        self.setMinimumWidth(520)
        self._thread: ImportThread | None = None
        self._finished = False

        intro = QLabel(tr("import.intro"))
        intro.setObjectName("muted")
        intro.setWordWrap(True)

        self._destination = QLineEdit(str(destination or ""))
        self._destination.setReadOnly(True)
        self._destination.setPlaceholderText(tr("import.no_folder"))
        self._browse_button = QPushButton(tr("import.choose_folder"))
        self._browse_button.clicked.connect(self._choose_destination)
        destination_row = QHBoxLayout()
        destination_row.addWidget(self._destination, 1)
        destination_row.addWidget(self._browse_button)

        self._progress = QProgressBar()
        self._progress.setRange(0, _PROGRESS_STEPS)
        self._progress.setTextVisible(False)
        self._progress.hide()
        self._counts_label = QLabel()
        self._counts_label.setObjectName("muted")
        self._file_progress = QProgressBar()
        self._file_progress.setRange(0, _PROGRESS_STEPS)
        self._file_progress.setTextVisible(False)
        self._file_progress.setFixedHeight(4)
        self._file_progress.hide()
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._transfer_label = QLabel()
        self._transfer_label.setObjectName("muted")
        self._transfer_name = ""
        self._samples: deque[tuple[float, int]] = deque()
        self._counts = (0, 0, 0)
        self._counts_changed = False
        self._fraction = 0.0
        self._latest_scan: tuple[int, int] | None = None
        self._latest_progress: tuple[float, str] | None = None
        self._latest_transfer: tuple[int, int, float] | None = None
        self._text_timer = QTimer(self)
        self._text_timer.setInterval(_TEXT_REFRESH_MS)
        self._text_timer.timeout.connect(self._refresh_text)
        self._keep_layout_stable()

        self._action_button = QPushButton(tr("import.start"))
        self._action_button.setObjectName("primary")
        self._action_button.clicked.connect(self._on_action)
        cancel_button = QPushButton(tr("common.cancel"))
        cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(self._action_button)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(intro)
        layout.addWidget(QLabel(tr("import.save_to")))
        layout.addLayout(destination_row)
        layout.addWidget(self._progress)
        layout.addWidget(self._status)
        layout.addWidget(self._counts_label)
        layout.addWidget(self._file_progress)
        layout.addWidget(self._transfer_label)
        layout.addLayout(buttons)

        self._refresh_action_button()
        if destination is None:
            QTimer.singleShot(0, self._choose_destination)

    @property
    def destination(self) -> Path:
        return Path(self._destination.text())

    def reject(self) -> None:
        if self._thread is not None:
            self._thread.requestInterruption()
            self._thread.wait()
        super().reject()

    def _choose_destination(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, tr("import.choose_destination"), self._destination.text()
        )
        if chosen:
            self._destination.setText(chosen)
            self._refresh_action_button()

    def _on_action(self) -> None:
        if self._finished:
            self.accept()
        else:
            self._start()

    def _start(self) -> None:
        self._set_running(True)
        self._text_timer.start()
        self._show_status(tr("import.connecting"), "muted")
        self._thread = ImportThread(self.destination, self)
        self._thread.scanning.connect(self._on_scanning)
        self._thread.counts.connect(self._on_counts)
        self._thread.progress.connect(self._on_progress)
        self._thread.transfer.connect(self._on_transfer)
        self._thread.imported.connect(self._on_imported)
        self._thread.paused.connect(lambda message: self._show_status(message, "warning"))
        self._thread.failed.connect(self._on_failed)
        self._thread.finished.connect(lambda: self._set_running(False))
        self._thread.start()

    def _can_proceed(self) -> bool:
        return self._finished or bool(self._destination.text())

    def _refresh_action_button(self) -> None:
        self._action_button.setEnabled(self._can_proceed())

    def _set_running(self, running: bool) -> None:
        self._action_button.setEnabled(not running and self._can_proceed())
        self._destination.setEnabled(not running)
        self._browse_button.setEnabled(not running)
        self._progress.setVisible(running or self._finished)

    def _on_scanning(self, done: int, total: int) -> None:
        self._progress.setValue(0)
        self._latest_scan = (done, total)

    def _on_counts(self, done: int, total: int, total_bytes: int) -> None:
        self._counts = (done, total, total_bytes)
        self._counts_changed = True

    def _on_progress(self, fraction: float, name: str) -> None:
        self._progress.setValue(round(fraction * _PROGRESS_STEPS))
        self._fraction = fraction
        self._latest_progress = (fraction, name)
        if name != self._transfer_name:
            self._transfer_name = name
            self._samples.clear()

    def _on_transfer(self, done: int, size: int, name: str) -> None:
        now = time.monotonic()
        self._samples.append((now, done))
        while now - self._samples[0][0] > _SPEED_WINDOW_S:
            self._samples.popleft()
        first_time, first_done = self._samples[0]
        speed = (done - first_done) / (now - first_time) if now > first_time else 0
        self._file_progress.setVisible(True)
        self._file_progress.setValue(round(done / max(size, 1) * _PROGRESS_STEPS))
        self._latest_transfer = (done, size, speed)

    def _refresh_text(self) -> None:
        """Texts are refreshed on a fixed beat instead of on every chunk of data."""
        if self._latest_scan is not None:
            done, total = self._latest_scan
            self._show_status(tr("import.scanning", done=done, total=total), "muted")
            self._latest_scan = None
        self._refresh_counts()
        if self._latest_progress is not None:
            fraction, name = self._latest_progress
            self._show_status(f"{fraction:.1%} · {name}", "muted")
            self._latest_progress = None
        if self._latest_transfer is not None:
            done, size, speed = self._latest_transfer
            self._transfer_label.setText(
                tr(
                    "import.transfer",
                    done=_format_size(done),
                    size=_format_size(size),
                    speed=_format_size(speed),
                )
            )
            self._latest_transfer = None

    def _refresh_counts(self) -> None:
        done, total, total_bytes = self._counts
        if not total or not (self._counts_changed or self._latest_progress is not None):
            return
        self._counts_changed = False
        self._counts_label.setText(
            tr(
                "import.counts",
                done=done,
                total=total,
                left=max(total - done, 0),
                size=_format_size(total_bytes * (1 - self._fraction)),
            )
        )

    def _reset_transfer(self) -> None:
        self._text_timer.stop()
        self._latest_scan = self._latest_progress = self._latest_transfer = None
        self._transfer_name = ""
        self._samples.clear()
        self._file_progress.hide()
        self._transfer_label.clear()

    def _keep_layout_stable(self) -> None:
        """Hidden or empty rows keep their space, so the dialog never resizes while importing."""
        for widget in (self._progress, self._file_progress):
            policy = widget.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            widget.setSizePolicy(policy)
        line = self.fontMetrics().lineSpacing()
        self._status.setMinimumHeight(_STATUS_LINES * line)
        self._status.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._transfer_label.setMinimumHeight(line)
        self._counts_label.setMinimumHeight(line)

    def _on_imported(self, copied: int, skipped: int, unreadable: list[str]) -> None:
        self._finished = True
        self._fraction = 1.0
        self._counts_changed = True
        self._refresh_counts()
        self._reset_transfer()
        self._progress.setValue(_PROGRESS_STEPS)
        message = tr("import.done", copied=copied, skipped=skipped)
        if unreadable:
            message += "\n" + tr("import.unreadable", items=", ".join(unreadable))
        self._show_status(message, "warning" if unreadable else "muted")
        self._action_button.setText(tr("import.open_gallery"))

    def _on_failed(self, message: str) -> None:
        self._progress.hide()
        self._reset_transfer()
        self._show_status(message, "error")

    def _show_status(self, message: str, style: str) -> None:
        self._status.setText(message)
        if self._status.objectName() != style:
            self._status.setObjectName(style)
            self._status.style().unpolish(self._status)
            self._status.style().polish(self._status)
