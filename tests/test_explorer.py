from pathlib import PureWindowsPath

from photo_viewer.explorer import explorer_command


def test_path_with_spaces_and_commas_is_quoted_for_explorer():
    path = PureWindowsPath(r"G:\iphone photos\202603_a\IMG_1,2.HEIC")

    assert explorer_command(path) == r'explorer /select,"G:\iphone photos\202603_a\IMG_1,2.HEIC"'
