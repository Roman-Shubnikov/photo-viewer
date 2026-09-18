from pathlib import Path

import pytest

from photo_viewer.models import MediaKind
from photo_viewer.scanner import scan_folder


def touch(root: Path, *names: str) -> None:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")


def kinds(root: Path) -> dict[str, MediaKind]:
    return {item.name: item.kind for item in scan_folder(root)}


def test_heic_with_mov_is_live_photo(tmp_path):
    touch(tmp_path, "IMG_0001.HEIC", "IMG_0001.MOV")

    (item,) = scan_folder(tmp_path)

    assert item.kind is MediaKind.LIVE
    assert item.path.name == "IMG_0001.HEIC"
    assert item.live_video.name == "IMG_0001.MOV"


def test_standalone_files_are_photo_and_video(tmp_path):
    touch(tmp_path, "IMG_0002.HEIC", "IMG_0003.MOV", "CLIP.MP4", "IMG_0004.PNG")

    assert kinds(tmp_path) == {
        "IMG_0002.HEIC": MediaKind.PHOTO,
        "IMG_0003.MOV": MediaKind.VIDEO,
        "CLIP.MP4": MediaKind.VIDEO,
        "IMG_0004.PNG": MediaKind.PHOTO,
    }


def test_edited_version_replaces_original(tmp_path):
    touch(tmp_path, "IMG_0005.HEIC", "IMG_0005.MOV", "IMG_E0005.HEIC", "IMG_E0005.MOV", "IMG_0005.AAE")

    (item,) = scan_folder(tmp_path)

    assert item.path.name == "IMG_E0005.HEIC"
    assert item.live_video.name == "IMG_E0005.MOV"


def test_edited_photo_keeps_original_live_video(tmp_path):
    touch(tmp_path, "IMG_0006.HEIC", "IMG_0006.MOV", "IMG_E0006.HEIC")

    (item,) = scan_folder(tmp_path)

    assert item.kind is MediaKind.LIVE
    assert item.path.name == "IMG_E0006.HEIC"
    assert item.live_video.name == "IMG_0006.MOV"


def test_same_name_in_different_folders_is_not_merged(tmp_path):
    touch(tmp_path, "202601_a/IMG_0007.HEIC", "202602_a/IMG_0007.MOV")

    assert sorted(kinds(tmp_path).values(), key=str) == sorted([MediaKind.PHOTO, MediaKind.VIDEO], key=str)


@pytest.mark.parametrize("name", ["IMG_0008.AAE", "notes.txt"])
def test_non_media_files_are_ignored(tmp_path, name):
    touch(tmp_path, name)

    assert scan_folder(tmp_path) == []
