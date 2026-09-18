import os
import time
from collections import deque
from collections.abc import Callable
from enum import Enum, auto
from pathlib import Path

import comtypes
from PySide6.QtCore import QObject, QThread, Signal

from photo_viewer.i18n import tr
from photo_viewer.iphone import DeviceFile, DeviceFolder, IPhone, IPhoneNotFoundError, com_apartment
from photo_viewer.power import keep_awake

_POLL_INTERVAL_MS = 500
_FIRST_RETRY_POLLS = 2
_POLLS_BETWEEN_RECONNECTS = 6
_QUIET_TROUBLE_S = 8.0
_MAX_FILE_ATTEMPTS = 5
_EXTRA_POLLS_PER_ATTEMPT = 4
_MAX_RELISTS_PER_FOLDER = 5
_UNRESPONSIVE_AFTER_FOLDERS = 3
_SCAN_REPORT_EVERY = 25

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_QUICKTIME_BRAND = b"qt  "


class _Cancelled(Exception):
    pass


class _Unreadable(Exception):
    pass


class _StaleListing(Exception):
    """The device returned data that does not belong to the requested file."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


class _Outcome(Enum):
    COPIED = auto()
    SKIPPED = auto()
    CANCELLED = auto()


def _looks_like(name: str, head: bytes) -> bool:
    match Path(name).suffix.lower():
        case ".heic" | ".heif":
            return head[4:8] == b"ftyp" and head[8:12] != _QUICKTIME_BRAND
        case ".jpg" | ".jpeg":
            return head[:2] == b"\xff\xd8"
        case ".png":
            return head[:8] == _PNG_SIGNATURE
        case _:
            return True


class ImportThread(QThread):
    scanning = Signal(int, int)
    counts = Signal(int, int, object)
    progress = Signal(float, str)
    transfer = Signal(object, object, str)
    paused = Signal(str)
    imported = Signal(int, int, list)
    failed = Signal(str)

    def __init__(self, destination: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._destination = destination
        self._phone: IPhone | None = None
        self._folders: list[DeviceFolder] = []
        self._unreadable: list[str] = []
        self._total_files = 0
        self._total_bytes = 0
        self._present_files = 0
        self._present_bytes = 0
        self._finished_files = 0
        self._done_bytes = 0
        self._shown_fraction = 0.0
        self._trouble_since: float | None = None
        self._announced = False

    def run(self) -> None:
        try:
            with com_apartment(), keep_awake():
                try:
                    self._import_all()
                finally:
                    self._close_phone()
        except _Cancelled:
            pass
        except (IPhoneNotFoundError, OSError) as error:
            self.failed.emit(str(error))

    def _import_all(self) -> None:
        self._retrying(self._connect)
        plan = self._retrying(self._make_plan)
        object_count = sum(len(object_ids) for _, object_ids in plan)
        if not object_count:
            raise IPhoneNotFoundError(tr("import.no_photos"))
        self._take_inventory(plan, object_count)
        self._publish_counts()

        copied = skipped = 0
        for folder, object_ids in plan:
            pending = deque(object_ids)
            relists = 0
            while pending:
                object_id = pending.popleft()
                try:
                    outcome = self._import_one(folder, object_id)
                except _Unreadable:
                    self._unreadable.append(f"{folder.name}/{object_id}")
                    self._file_finished()
                except _StaleListing as stale:
                    if relists == _MAX_RELISTS_PER_FOLDER:
                        self._unreadable.append(f"{folder.name}/{stale.name}")
                        self._file_finished()
                    else:
                        relists += 1
                        pending = deque(self._relist(folder))
                else:
                    if outcome is _Outcome.CANCELLED:
                        return
                    copied += outcome is _Outcome.COPIED
                    skipped += outcome is _Outcome.SKIPPED
                    if outcome is _Outcome.COPIED:
                        self._file_finished()
        self.imported.emit(copied, skipped, self._unreadable)

    def _take_inventory(self, plan: list[tuple[DeviceFolder, list[str]]], object_count: int) -> None:
        """Counts what is on the device and what is already copied, so a resumed import shows real state."""
        scanned = 0
        for folder, object_ids in plan:
            for object_id in object_ids:
                if self.isInterruptionRequested():
                    raise _Cancelled
                file = self._describe_or_none(object_id)
                if file is not None:
                    self._total_files += 1
                    self._total_bytes += file.size
                    if self._is_current(folder, file):
                        self._present_files += 1
                        self._present_bytes += file.size
                scanned += 1
                if scanned % _SCAN_REPORT_EVERY == 0 or scanned == object_count:
                    self.scanning.emit(scanned, object_count)

    def _file_finished(self) -> None:
        self._finished_files += 1
        self._publish_counts()

    def _publish_counts(self) -> None:
        self.counts.emit(self._present_files + self._finished_files, self._total_files, self._total_bytes)

    def _describe_or_none(self, object_id: str) -> DeviceFile | None:
        for attempt in range(_MAX_FILE_ATTEMPTS):
            try:
                return self._phone.describe(object_id)
            except comtypes.COMError:
                self._wait_for_device(patience=attempt * _EXTRA_POLLS_PER_ATTEMPT)
        return None

    def _is_current(self, folder: DeviceFolder, file: DeviceFile) -> bool:
        target = self._destination / folder.name / file.name
        return target.exists() and target.stat().st_size == file.size

    def _connect(self) -> None:
        self._close_phone()
        self._phone = IPhone.connect()
        self._folders = self._phone.folders()

    def _close_phone(self) -> None:
        if self._phone is not None:
            self._phone.close()
            self._phone = None

    def _relist(self, folder: DeviceFolder) -> list[str]:
        """The device renumbered its objects: reconnect and read the folder again."""
        self._retrying(self._connect)
        return self._retrying(lambda: self._phone.object_ids(folder))

    def _make_plan(self) -> list[tuple[DeviceFolder, list[str]]]:
        """Unopenable folders are reported; if none opens at all, the device itself is unresponsive."""
        plan: list[tuple[DeviceFolder, list[str]]] = []
        unreadable: list[str] = []
        for folder in self._folders:
            try:
                plan.append((folder, self._phone.object_ids(folder)))
            except comtypes.COMError:
                unreadable.append(folder.name)
                if not plan and len(unreadable) >= _UNRESPONSIVE_AFTER_FOLDERS:
                    raise
        self._unreadable = unreadable
        return plan

    def _retrying[T](self, action: Callable[[], T]) -> T:
        while True:
            try:
                return action()
            except comtypes.COMError:
                self._wait_for_device()

    def _wait_for_device(self, patience: int = 0) -> None:
        """Reconnects quietly; the user is only told about the problem if it persists."""
        if self._trouble_since is None:
            self._trouble_since = time.monotonic()
        polls = _FIRST_RETRY_POLLS + patience
        while True:
            self._sleep(polls)
            polls = _POLLS_BETWEEN_RECONNECTS
            self._announce_persistent_trouble()
            try:
                self._connect()
            except (comtypes.COMError, IPhoneNotFoundError):
                continue
            return

    def _announce_persistent_trouble(self) -> None:
        if not self._announced and time.monotonic() - self._trouble_since >= _QUIET_TROUBLE_S:
            self._announced = True
            self.paused.emit(tr("import.paused"))

    def _sleep(self, polls: int) -> None:
        for _ in range(polls):
            if self.isInterruptionRequested():
                raise _Cancelled
            self.msleep(_POLL_INTERVAL_MS)

    def _import_one(self, folder: DeviceFolder, object_id: str) -> _Outcome:
        """Raises `_Unreadable` if the device keeps failing on this object."""
        for attempt in range(_MAX_FILE_ATTEMPTS):
            try:
                return self._transfer(folder, object_id)
            except comtypes.COMError:
                self._wait_for_device(patience=attempt * _EXTRA_POLLS_PER_ATTEMPT)
        raise _Unreadable

    def _transfer(self, folder: DeviceFolder, object_id: str) -> _Outcome:
        file = self._phone.describe(object_id)
        if self._is_current(folder, file):
            return _Outcome.SKIPPED

        self._report(file.name)
        target = self._destination / folder.name / file.name
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f"{target.name}.part")
        try:
            completed = self._write(file, partial)
        except (comtypes.COMError, _StaleListing):
            partial.unlink(missing_ok=True)
            raise
        if not completed:
            partial.unlink()
            return _Outcome.CANCELLED
        partial.replace(target)
        os.utime(target, (file.modified, file.modified))
        return _Outcome.COPIED

    def _write(self, file: DeviceFile, partial: Path) -> bool:
        """Returns False when cancelled. Raises `_StaleListing` if the received data is not this file."""
        written = 0
        try:
            with partial.open("wb") as output:
                for chunk in self._phone.read(file):
                    if self.isInterruptionRequested():
                        return False
                    if not written and not _looks_like(file.name, chunk[:12]):
                        raise _StaleListing(file.name)
                    output.write(chunk)
                    written += len(chunk)
                    self._done_bytes += len(chunk)
                    self._trouble_since, self._announced = None, False
                    self.transfer.emit(written, file.size, file.name)
                    self._report(file.name)
            if written != file.size:
                raise _StaleListing(file.name)
        except (comtypes.COMError, _StaleListing):
            self._done_bytes -= written
            raise
        return True

    def _report(self, name: str) -> None:
        """Progress only moves forward, even when a file has to be downloaded again."""
        copied = self._present_bytes + self._done_bytes
        fraction = min(copied / self._total_bytes, 1.0) if self._total_bytes else 1.0
        self._shown_fraction = max(self._shown_fraction, fraction)
        self.progress.emit(self._shown_fraction, name)
