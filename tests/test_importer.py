import comtypes
import pytest
from PySide6.QtCore import QCoreApplication

from photo_viewer import importer
from photo_viewer.iphone import DeviceFile, DeviceFolder

CONTENT = b"\x00\x00\x00\x18ftypheic" + b"x" * 988
FOLDER = DeviceFolder("f1", "202601_a")
BAD_FOLDER = DeviceFolder("f2", "202602_a")


def com_error() -> comtypes.COMError:
    return comtypes.COMError(-2147024726, "busy", (None, None, None, 0, None))


class FakePhone:
    """Three photos in one folder; `IMG_2.HEIC` fails once mid-transfer, then behaves."""

    failures_left = 1

    @classmethod
    def connect(cls) -> "FakePhone":
        return cls()

    def close(self) -> None:
        pass

    def folders(self) -> list[DeviceFolder]:
        return [FOLDER, BAD_FOLDER]

    def object_ids(self, folder: DeviceFolder) -> list[str]:
        if folder is BAD_FOLDER:
            raise com_error()
        return ["o1", "o2", "o3"]

    def describe(self, object_id: str) -> DeviceFile:
        return DeviceFile(object_id, f"IMG_{object_id[1:]}.HEIC", len(CONTENT), 1_700_000_000.0)

    def read(self, file: DeviceFile):
        yield CONTENT[:500]
        if file.name == "IMG_2.HEIC" and FakePhone.failures_left:
            FakePhone.failures_left -= 1
            raise com_error()
        yield CONTENT[500:]


class BrokenFilePhone(FakePhone):
    """`IMG_2.HEIC` can never be read."""

    def read(self, file: DeviceFile):
        if file.name == "IMG_2.HEIC":
            raise com_error()
        yield CONTENT


class ShiftedPhone(FakePhone):
    """The first session serves another file's data (a video) for every request; later sessions are fine."""

    sessions = 0

    @classmethod
    def connect(cls) -> "ShiftedPhone":
        cls.sessions += 1
        phone = cls()
        phone.shifted = cls.sessions == 1
        return phone

    def read(self, file: DeviceFile):
        if self.shifted:
            yield b"\x00\x00\x00\x14ftypqt  " + b"v" * 400
        else:
            yield CONTENT


class AlwaysWrongDataPhone(FakePhone):
    """Every request is answered with another file's data, in every session."""

    def read(self, file: DeviceFile):
        yield b"\x00\x00\x00\x14ftypqt  " + b"v" * 400


@pytest.fixture
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


def run_import(monkeypatch, tmp_path, phone_class, quiet_seconds=0.0):
    monkeypatch.setattr(importer, "IPhone", phone_class)
    monkeypatch.setattr(importer, "_QUIET_TROUBLE_S", quiet_seconds)
    monkeypatch.setattr(importer, "_POLL_INTERVAL_MS", 1)
    monkeypatch.setattr(importer, "_POLLS_BETWEEN_RECONNECTS", 1)
    thread = importer.ImportThread(tmp_path)
    events = {"paused": [], "imported": [], "failed": [], "counts": []}
    thread.paused.connect(events["paused"].append)
    thread.imported.connect(lambda *result: events["imported"].append(result))
    thread.failed.connect(events["failed"].append)
    thread.counts.connect(lambda *values: events["counts"].append(values))
    thread.run()
    return events


def copied_files(tmp_path):
    return {p.name: p.read_bytes() for p in (tmp_path / "202601_a").glob("*.HEIC")}


def test_import_pauses_on_device_error_and_resumes(qt_app, tmp_path, monkeypatch):
    events = run_import(monkeypatch, tmp_path, FakePhone)

    assert len(events["paused"]) == 1
    assert events["failed"] == []
    assert events["imported"] == [(3, 0, ["202602_a"])]
    assert set(copied_files(tmp_path).values()) == {CONTENT}
    assert not list(tmp_path.rglob("*.part"))


def test_short_device_hiccup_is_retried_without_bothering_the_user(qt_app, tmp_path, monkeypatch):
    events = run_import(monkeypatch, tmp_path, FakePhone, quiet_seconds=60.0)

    assert events["paused"] == []
    assert events["imported"] == [(3, 0, ["202602_a"])]
    assert set(copied_files(tmp_path).values()) == {CONTENT}


def test_permanently_unreadable_file_is_skipped_and_reported(qt_app, tmp_path, monkeypatch):
    events = run_import(monkeypatch, tmp_path, BrokenFilePhone)

    assert events["imported"] == [(2, 0, ["202602_a", "202601_a/o2"])]
    assert not list(tmp_path.rglob("*.part"))


def test_second_run_skips_files_already_copied(qt_app, tmp_path, monkeypatch):
    run_import(monkeypatch, tmp_path, BrokenFilePhone)

    events = run_import(monkeypatch, tmp_path, FakePhone)

    assert events["imported"] == [(1, 2, ["202602_a"])]


def test_data_that_belongs_to_another_file_is_never_saved(qt_app, tmp_path, monkeypatch):
    ShiftedPhone.sessions = 0

    events = run_import(monkeypatch, tmp_path, ShiftedPhone)

    assert events["imported"] == [(3, 0, ["202602_a"])]
    assert copied_files(tmp_path) == {f"IMG_{i}.HEIC": CONTENT for i in (1, 2, 3)}
    assert ShiftedPhone.sessions == 2
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize(
    ("name", "head", "expected"),
    [
        ("a.HEIC", b"\x00\x00\x00\x18ftypheic", True),
        ("a.HEIC", b"\x00\x00\x00\x14ftypqt  ", False),
        ("a.JPG", b"\xff\xd8\xff\xe0" + b"\x00" * 8, True),
        ("a.JPG", b"\x00\x00\x00\x18ftypheic", False),
        ("a.PNG", b"\x89PNG\r\n\x1a\n" + b"\x00" * 4, True),
        ("a.MOV", b"anything", True),
    ],
)
def test_signature_matches_extension(name, head, expected):
    assert importer._looks_like(name, head) is expected


def test_file_counts_start_at_zero_and_end_with_everything_ready(qt_app, tmp_path, monkeypatch):
    events = run_import(monkeypatch, tmp_path, FakePhone)

    assert events["counts"][0] == (0, 3, 3 * len(CONTENT))
    assert events["counts"][-1] == (3, 3, 3 * len(CONTENT))
    done = [values[0] for values in events["counts"]]
    assert done == sorted(done)


def test_files_the_device_refuses_still_count_as_finished(qt_app, tmp_path, monkeypatch):
    events = run_import(monkeypatch, tmp_path, BrokenFilePhone)

    assert events["counts"][-1][:2] == (3, 3)


def test_resumed_import_counts_files_that_are_already_there(qt_app, tmp_path, monkeypatch):
    run_import(monkeypatch, tmp_path, BrokenFilePhone)

    events = run_import(monkeypatch, tmp_path, FakePhone)

    assert events["counts"][0] == (2, 3, 3 * len(CONTENT))
    assert events["counts"][-1] == (3, 3, 3 * len(CONTENT))


def test_progress_of_a_resumed_import_starts_where_it_left_off(qt_app, tmp_path, monkeypatch):
    run_import(monkeypatch, tmp_path, BrokenFilePhone)
    fractions = []
    monkeypatch.setattr(importer, "IPhone", FakePhone)
    thread = importer.ImportThread(tmp_path)
    thread.progress.connect(lambda fraction, name: fractions.append(fraction))

    thread.run()

    assert fractions[0] == pytest.approx(2 / 3, abs=0.01)
    assert fractions[-1] == pytest.approx(1.0)
    assert fractions == sorted(fractions)


def test_import_stops_with_a_clear_message_when_the_device_keeps_sending_wrong_data(
    qt_app, tmp_path, monkeypatch
):
    events = run_import(monkeypatch, tmp_path, AlwaysWrongDataPhone)

    assert events["imported"] == []
    assert len(events["failed"]) == 1
    assert "Restart the iPhone" in events["failed"][0] or "Перезагрузите" in events["failed"][0]
    assert copied_files(tmp_path) == {}
    assert not list(tmp_path.rglob("*.part"))
