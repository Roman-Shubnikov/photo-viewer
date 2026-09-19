from pathlib import Path

import pytest

from photo_viewer.explorer import reveal_in_explorer


def test_missing_file_raises_instead_of_opening_a_random_folder(tmp_path):
    with pytest.raises(OSError):
        reveal_in_explorer(Path(tmp_path / "does not exist.jpg"))
