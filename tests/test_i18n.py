import re

import pytest

from photo_viewer.i18n import _TEXTS, Language, tr, translator


@pytest.fixture(autouse=True)
def restore_language():
    original = translator._language
    yield
    translator._language = original


def test_every_text_has_matching_placeholders_in_both_languages():
    for english, russian in _TEXTS.values():
        assert set(re.findall(r"{(\w+)}", english)) == set(re.findall(r"{(\w+)}", russian))


def test_tr_uses_current_language_and_formats_parameters():
    translator._language = Language.ENGLISH
    assert tr("import.done", copied=3, skipped=1) == "Done: 3 new files copied, 1 already present."

    translator._language = Language.RUSSIAN
    assert tr("import.done", copied=3, skipped=1).startswith("Готово")
