from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path


class MediaKind(Enum):
    PHOTO = auto()
    LIVE = auto()
    VIDEO = auto()


@dataclass(frozen=True, slots=True)
class MediaItem:
    kind: MediaKind
    path: Path
    live_video: Path | None
    taken_at: float
    size: int

    @property
    def name(self) -> str:
        return self.path.name
