from pathlib import Path

from photo_viewer.models import MediaItem, MediaKind
from photo_viewer.sorting import SortOrder, sort_items


def item(name: str, taken_at: float, size: int) -> MediaItem:
    return MediaItem(kind=MediaKind.PHOTO, path=Path(name), live_video=None, taken_at=taken_at, size=size)


ITEMS = [item("b.jpg", 20, 500), item("a.jpg", 10, 900), item("c.jpg", 30, 100), item("d.jpg", 30, 500)]


def names(order: SortOrder) -> list[str]:
    return [i.name for i in sort_items(ITEMS, order)]


def test_sort_by_date():
    assert names(SortOrder.NEWEST) == ["d.jpg", "c.jpg", "b.jpg", "a.jpg"]
    assert names(SortOrder.OLDEST) == ["a.jpg", "b.jpg", "c.jpg", "d.jpg"]


def test_sort_by_size_breaks_ties_by_name():
    assert names(SortOrder.LARGEST) == ["a.jpg", "d.jpg", "b.jpg", "c.jpg"]
    assert names(SortOrder.SMALLEST) == ["c.jpg", "b.jpg", "d.jpg", "a.jpg"]


def test_sorting_does_not_modify_the_input():
    before = list(ITEMS)

    sort_items(ITEMS, SortOrder.LARGEST)

    assert before == ITEMS
