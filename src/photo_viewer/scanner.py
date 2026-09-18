import re
from collections import defaultdict
from pathlib import Path

from photo_viewer.models import MediaItem, MediaKind

STILL_SUFFIXES = frozenset(
    {".heic", ".heif", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff", ".bmp"}
)
VIDEO_SUFFIXES = frozenset({".mov", ".mp4", ".m4v"})

_EDITED_STEM = re.compile(r"^(IMG_)E(\d+)$", re.IGNORECASE)


def scan_folder(root: Path) -> list[MediaItem]:
    groups: defaultdict[tuple[Path, str], list[Path]] = defaultdict(list)
    for path in root.rglob("*"):
        if path.suffix.lower() in STILL_SUFFIXES | VIDEO_SUFFIXES:
            groups[path.parent, _original_stem(path.stem)].append(path)

    items = [_build_item(paths) for paths in groups.values()]
    return sorted(items, key=lambda item: (item.taken_at, item.name), reverse=True)


def _original_stem(stem: str) -> str:
    return _EDITED_STEM.sub(r"\1\2", stem).lower()


def _build_item(paths: list[Path]) -> MediaItem:
    still = _preferred([p for p in paths if p.suffix.lower() in STILL_SUFFIXES])
    video = _preferred([p for p in paths if p.suffix.lower() in VIDEO_SUFFIXES])
    primary = still or video
    kind = MediaKind.VIDEO if still is None else MediaKind.LIVE if video else MediaKind.PHOTO
    return MediaItem(
        kind=kind,
        path=primary,
        live_video=video if kind is MediaKind.LIVE else None,
        taken_at=primary.stat().st_mtime,
    )


def _preferred(paths: list[Path]) -> Path | None:
    """Picks the edited version (IMG_E1234) over the original when both exist."""
    return max(paths, key=lambda p: _EDITED_STEM.match(p.stem) is not None, default=None)
