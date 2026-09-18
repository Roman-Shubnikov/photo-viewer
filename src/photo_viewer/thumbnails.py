import hashlib
import os
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from threading import Lock

from PySide6.QtGui import QImage

from photo_viewer.models import MediaItem, MediaKind
from photo_viewer.thumbnail_render import init_worker, render_thumbnail

THUMBNAIL_SIZE = 512
_MIN_WORKERS = 2
_CORES_LEFT_FOR_UI = 4


class ThumbnailCache:
    """Square thumbnails persisted on disk and rendered by a pool of worker processes."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._directory = directory
        self._pool: ProcessPoolExecutor | None = None
        self._jobs: dict[Path, Future[None]] = {}
        self._workers = max(_MIN_WORKERS, (os.cpu_count() or _MIN_WORKERS) - _CORES_LEFT_FOR_UI)
        self._lock = Lock()

    @property
    def workers(self) -> int:
        return self._workers

    def ensure(self, item: MediaItem) -> Path:
        """Returns the thumbnail file, rendering it first if it is not cached yet."""
        target = self._directory / f"{_fingerprint(item.path)}.jpg"
        if not target.exists():
            try:
                self._job_for(item, target).result()
            except BrokenProcessPool:
                self.close()
                raise
        return target

    def load(self, item: MediaItem) -> QImage:
        image = QImage(str(self.ensure(item)))
        if image.isNull():
            raise OSError(f"Unreadable thumbnail for {item.path}")
        return image

    def warm_up(self) -> None:
        """Starts the worker processes ahead of the first request."""
        with self._lock:
            pool = self._pool_locked()
        for _ in range(self._workers):
            pool.submit(int)

    def close(self) -> None:
        with self._lock:
            if self._pool is not None:
                self._pool.shutdown(wait=False, cancel_futures=True)
                self._pool = None
            self._jobs.clear()

    def _job_for(self, item: MediaItem, target: Path) -> Future[None]:
        """Concurrent requests for the same thumbnail share one rendering job."""
        with self._lock:
            job = self._jobs.get(target)
            if job is not None:
                return job
            job = self._pool_locked().submit(
                render_thumbnail, str(item.path), str(target), item.kind is MediaKind.VIDEO, THUMBNAIL_SIZE
            )
            self._jobs[target] = job
        job.add_done_callback(lambda _: self._forget(target))
        return job

    def _forget(self, target: Path) -> None:
        with self._lock:
            self._jobs.pop(target, None)

    def _pool_locked(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(self._workers, initializer=init_worker)
        return self._pool


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return hashlib.sha1(f"{path}|{stat.st_size}|{stat.st_mtime_ns}|{THUMBNAIL_SIZE}".encode()).hexdigest()
