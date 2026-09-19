from enum import StrEnum

from PySide6.QtCore import QLocale, QObject, QSettings, Signal


class Language(StrEnum):
    ENGLISH = "en"
    RUSSIAN = "ru"


_LANGUAGE_KEY = "ui/language"
_COLUMN = {Language.ENGLISH: 0, Language.RUSSIAN: 1}

_TEXTS: dict[str, tuple[str, str]] = {
    "app.title": ("Photo Viewer", "Фотогалерея"),
    "language.switch": ("Русский", "English"),
    "common.cancel": ("Cancel", "Отмена"),
    "main.open_folder": ("Open folder…", "Открыть папку…"),
    "main.import": ("Import from iPhone…", "Импорт с iPhone…"),
    "menu.open": ("Open", "Открыть"),
    "menu.show_in_explorer": ("Show in Explorer", "Показать в проводнике"),
    "main.open_folder_title": ("Open folder", "Открыть папку"),
    "main.empty_title": (
        "Open a folder with photos copied from your iPhone",
        "Откройте папку с фото, скопированными с iPhone",
    ),
    "main.empty_hint": (
        "or import everything straight from the connected device",
        "или импортируйте всё прямо с подключённого устройства",
    ),
    "main.empty_folder": ("No photos or videos found in {folder}", "В папке {folder} нет фото и видео"),
    "main.summary": ("Items: {total} · Live Photos: {live}", "Элементов: {total} · Live Photos: {live}"),
    "sort.label": ("Sort by", "Сортировка"),
    "sort.newest": ("Date: newest first", "Дата: сначала новые"),
    "sort.oldest": ("Date: oldest first", "Дата: сначала старые"),
    "sort.largest": ("Size: largest first", "Размер: сначала большие"),
    "sort.smallest": ("Size: smallest first", "Размер: сначала маленькие"),
    "viewer.title": ("Viewer", "Просмотр"),
    "viewer.loading": ("Loading…", "Загрузка…"),
    "viewer.cannot_display": ("This file cannot be displayed", "Не удаётся показать этот файл"),
    "import.title": ("Import from iPhone", "Импорт с iPhone"),
    "import.intro": (
        "Connect the iPhone with a cable, unlock it and tap “Trust”.\n"
        "Live Photos are copied together with their video. Files that are already in the "
        "destination are skipped, so the import can be repeated or resumed.\n\n"
        "Tip: an iPhone that locks stops sending photos. Before starting, open Settings → "
        "Display & Brightness → Auto-Lock and choose Never (restore it afterwards).",
        "Подключите iPhone кабелем, разблокируйте его и нажмите «Доверять».\n"
        "Live Photo копируются вместе с видео. Файлы, которые уже есть в папке назначения, "
        "пропускаются, поэтому импорт можно повторять и продолжать.\n\n"
        "Совет: заблокированный iPhone перестаёт отдавать фото. Перед стартом откройте "
        "Настройки → Экран и яркость → Автоблокировка и выберите «Никогда» (потом верните обратно).",
    ),
    "import.choose_folder": ("Choose folder…", "Выбрать папку…"),
    "import.no_folder": ("Choose where to save the photos", "Выберите, куда сохранить фото"),
    "import.save_to": ("Save to", "Сохранить в"),
    "import.choose_destination": ("Choose destination", "Выберите папку назначения"),
    "import.start": ("Start import", "Начать импорт"),
    "import.open_gallery": ("Open gallery", "Открыть галерею"),
    "import.scanning": (
        "Checking files on the iPhone: {done} of {total}",
        "Проверка файлов на iPhone: {done} из {total}",
    ),
    "import.connecting": ("Connecting to iPhone…", "Подключение к iPhone…"),
    "import.done": (
        "Done: {copied} new files copied, {skipped} already present.",
        "Готово: скопировано новых файлов — {copied}, уже были на месте — {skipped}.",
    ),
    "import.unreadable": (
        "The iPhone refused to give these items (they are skipped): {items}",
        "iPhone не отдал эти объекты (они пропущены): {items}",
    ),
    "import.transfer": ("{done} of {size} · {speed}/s", "{done} из {size} · {speed}/с"),
    "unit.kb": ("KB", "КБ"),
    "unit.mb": ("MB", "МБ"),
    "unit.gb": ("GB", "ГБ"),
    "import.counts": (
        "Files ready: {done} of {total} · {left} left · {size} to go",
        "Готово файлов: {done} из {total} · осталось {left} · ещё {size}",
    ),
    "import.wrong_data": (
        "The iPhone is sending data that belongs to other files, so nothing was saved for them.\n"
        "Restart the iPhone (or unplug and replug the cable) and start the import again — "
        "files that are already copied will be skipped.",
        "iPhone отдаёт данные, которые принадлежат другим файлам, поэтому для них ничего не сохранено.\n"
        "Перезагрузите iPhone (или переподключите кабель) и запустите импорт заново — "
        "уже скопированные файлы будут пропущены.",
    ),
    "import.paused": (
        "Import paused: the iPhone stopped responding. Unlock it — the import will resume automatically.\n"
        "To stop it from locking again: Settings → Display & Brightness → Auto-Lock → Never.",
        "Импорт приостановлен: iPhone перестал отвечать. Разблокируйте его — импорт продолжится сам.\n"
        "Чтобы он снова не блокировался: Настройки → Экран и яркость → Автоблокировка → Никогда.",
    ),
    "import.no_photos": (
        "No photos found. Unlock the iPhone and tap “Trust”.",
        "Фото не найдены. Разблокируйте iPhone и нажмите «Доверять».",
    ),
    "import.not_found": (
        "iPhone not found. Connect it with a cable, unlock it and tap “Trust”.",
        "iPhone не найден. Подключите его кабелем, разблокируйте и нажмите «Доверять».",
    ),
}


class Translator(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._language = Language.ENGLISH

    @property
    def language(self) -> Language:
        return self._language

    def load(self) -> None:
        saved = QSettings().value(_LANGUAGE_KEY, type=str)
        self._language = Language(saved) if saved else _system_language()

    def toggle(self) -> None:
        self._language = Language.RUSSIAN if self._language is Language.ENGLISH else Language.ENGLISH
        QSettings().setValue(_LANGUAGE_KEY, self._language.value)
        self.changed.emit()


def _system_language() -> Language:
    russian = QLocale.system().language() == QLocale.Language.Russian
    return Language.RUSSIAN if russian else Language.ENGLISH


translator = Translator()


def tr(key: str, **params: object) -> str:
    text = _TEXTS[key][_COLUMN[translator.language]]
    return text.format(**params) if params else text
