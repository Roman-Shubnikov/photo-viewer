from enum import Enum, auto

from photo_viewer.models import MediaItem


class SortOrder(Enum):
    NEWEST = auto()
    OLDEST = auto()
    LARGEST = auto()
    SMALLEST = auto()


def sort_items(items: list[MediaItem], order: SortOrder) -> list[MediaItem]:
    """Sorts by date or by size; items that tie are ordered by file name."""
    match order:
        case SortOrder.NEWEST:
            return sorted(items, key=lambda item: (item.taken_at, item.name), reverse=True)
        case SortOrder.OLDEST:
            return sorted(items, key=lambda item: (item.taken_at, item.name))
        case SortOrder.LARGEST:
            return sorted(items, key=lambda item: (item.size, item.name), reverse=True)
        case SortOrder.SMALLEST:
            return sorted(items, key=lambda item: (item.size, item.name))
