from pathlib import Path

from PySide6.QtCore import QModelIndex, QPoint, QSettings, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from photo_viewer.explorer import reveal_in_explorer
from photo_viewer.i18n import tr, translator
from photo_viewer.models import MediaItem, MediaKind
from photo_viewer.scanner import scan_folder
from photo_viewer.sorting import SortOrder, sort_items
from photo_viewer.thumbnails import ThumbnailCache
from photo_viewer.ui.gallery import TILE_DEFAULT, TILE_MAX, TILE_MIN, GalleryModel, GalleryView
from photo_viewer.ui.import_dialog import ImportDialog
from photo_viewer.ui.viewer import ViewerWindow

_LIBRARY_KEY = "library/folder"
_IMPORT_KEY = "import/folder"
_SORT_KEY = "gallery/sort"
_SORT_TEXTS = {
    SortOrder.NEWEST: "sort.newest",
    SortOrder.OLDEST: "sort.oldest",
    SortOrder.LARGEST: "sort.largest",
    SortOrder.SMALLEST: "sort.smallest",
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.resize(1200, 800)
        self._settings = QSettings()
        self._folder: Path | None = None
        self._scanned: list[MediaItem] = []

        cache_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation))
        self._thumbnails = ThumbnailCache(cache_dir / "thumbnails")
        self._thumbnails.warm_up()
        self._model = GalleryModel(self._thumbnails, self)
        self._gallery = GalleryView(self._model)
        self._gallery.activated.connect(self._open_viewer)
        self._gallery.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._gallery.customContextMenuRequested.connect(self._show_tile_menu)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_empty_page())
        self._pages.addWidget(self._gallery)
        self.setCentralWidget(self._pages)
        self._build_toolbar()

        translator.changed.connect(self._retranslate)
        self._retranslate()

        last_folder = self._settings.value(_LIBRARY_KEY, type=str)
        if last_folder and Path(last_folder).is_dir():
            self._load_folder(Path(last_folder))
        else:
            QTimer.singleShot(0, self._choose_folder)

    def closeEvent(self, event) -> None:
        self._model.shutdown()
        self._thumbnails.close()
        super().closeEvent(event)

    def _build_empty_page(self) -> QWidget:
        self._empty_title = QLabel()
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_title.setStyleSheet("font-size: 18px;")
        self._empty_hint = QLabel()
        self._empty_hint.setObjectName("muted")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._open_button = QPushButton()
        self._open_button.clicked.connect(self._choose_folder)
        self._import_button = QPushButton()
        self._import_button.setObjectName("primary")
        self._import_button.clicked.connect(self._import_from_iphone)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(14)
        layout.addWidget(self._empty_title)
        layout.addWidget(self._empty_hint)
        layout.addWidget(self._open_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._import_button, alignment=Qt.AlignmentFlag.AlignCenter)
        return page

    def _build_toolbar(self) -> None:
        toolbar = self._toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._open_action = QAction(self)
        self._open_action.setShortcut(QKeySequence.StandardKey.Open)
        self._open_action.triggered.connect(self._choose_folder)
        self._import_action = QAction(self)
        self._import_action.setShortcut(QKeySequence("Ctrl+I"))
        self._import_action.triggered.connect(self._import_from_iphone)
        self._language_action = QAction(self)
        self._language_action.triggered.connect(translator.toggle)
        toolbar.addAction(self._open_action)
        toolbar.addAction(self._import_action)
        toolbar.addSeparator()
        self._sort_label = QLabel()
        self._sort_label.setObjectName("muted")
        toolbar.addWidget(self._sort_label)
        toolbar.addWidget(self._build_sort_combo())

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addAction(self._language_action)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(TILE_MIN, TILE_MAX)
        slider.setValue(TILE_DEFAULT)
        slider.setFixedWidth(160)
        slider.valueChanged.connect(self._gallery.set_tile_size)
        toolbar.addWidget(slider)

    def _build_sort_combo(self) -> QComboBox:
        self._sort_combo = QComboBox()
        for order in SortOrder:
            self._sort_combo.addItem("", order)
        saved = self._settings.value(_SORT_KEY, SortOrder.NEWEST.name, type=str)
        self._sort_combo.setCurrentIndex(max(self._sort_combo.findData(SortOrder[saved]), 0))
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        return self._sort_combo

    def _on_sort_changed(self) -> None:
        self._settings.setValue(_SORT_KEY, self._sort_order().name)
        self._apply_sort()

    def _sort_order(self) -> SortOrder:
        return self._sort_combo.currentData()

    def _apply_sort(self) -> None:
        self._model.set_items(sort_items(self._scanned, self._sort_order()))
        self._gallery.scrollToTop()

    def _retranslate(self) -> None:
        self._sort_label.setText(tr("sort.label"))
        for index in range(self._sort_combo.count()):
            self._sort_combo.setItemText(index, tr(_SORT_TEXTS[self._sort_combo.itemData(index)]))
        self._open_action.setText(tr("main.open_folder"))
        self._import_action.setText(tr("main.import"))
        self._language_action.setText(tr("language.switch"))
        self._open_button.setText(tr("main.open_folder"))
        self._import_button.setText(tr("main.import"))
        self._empty_title.setText(tr("main.empty_title"))
        self._toolbar.layout().invalidate()
        self._refresh_folder_texts()

    def _refresh_folder_texts(self) -> None:
        items = self._model.items
        if self._folder is None:
            self.setWindowTitle(tr("app.title"))
            self._empty_hint.setText(tr("main.empty_hint"))
            return
        live_count = sum(item.kind is MediaKind.LIVE for item in items)
        self.setWindowTitle(f"{tr('app.title')} — {self._folder}")
        self.statusBar().showMessage(tr("main.summary", total=len(items), live=live_count))
        if items:
            self._empty_hint.setText(tr("main.empty_hint"))
        else:
            self._empty_hint.setText(tr("main.empty_folder", folder=self._folder))

    def _choose_folder(self) -> None:
        start = self._settings.value(_LIBRARY_KEY, str(Path.home() / "Pictures"), type=str)
        chosen = QFileDialog.getExistingDirectory(self, tr("main.open_folder_title"), start)
        if chosen:
            self._load_folder(Path(chosen))

    def _load_folder(self, folder: Path) -> None:
        self._settings.setValue(_LIBRARY_KEY, str(folder))
        self._folder = folder
        self._scanned = scan_folder(folder)
        self._model.set_items(sort_items(self._scanned, self._sort_order()))
        self._refresh_folder_texts()
        if self._model.items:
            self._pages.setCurrentWidget(self._gallery)
        else:
            self._pages.setCurrentIndex(0)

    def _import_from_iphone(self) -> None:
        saved = self._settings.value(_IMPORT_KEY, type=str)
        dialog = ImportDialog(Path(saved) if saved else None, self)
        if dialog.exec():
            self._settings.setValue(_IMPORT_KEY, str(dialog.destination))
            self._load_folder(dialog.destination)

    def _show_tile_menu(self, position: QPoint) -> None:
        index = self._gallery.indexAt(position)
        if not index.isValid():
            return
        self._gallery.setCurrentIndex(index)
        item = self._model.items[index.row()]
        menu = QMenu(self)
        menu.addAction(tr("menu.open"), lambda: self._open_viewer(index))
        menu.addAction(tr("menu.show_in_explorer"), lambda: reveal_in_explorer(item.path))
        menu.exec(self._gallery.viewport().mapToGlobal(position))

    def _open_viewer(self, index: QModelIndex) -> None:
        viewer = ViewerWindow(self._model.items, index.row(), self)
        viewer.finished.connect(lambda: self._gallery.setCurrentIndex(self._model.index(viewer.row)))
        viewer.showMaximized()
