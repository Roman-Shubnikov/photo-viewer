from pathlib import Path

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from PySide6.QtGui import QImage

register_heif_opener()


def to_qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    return QImage(rgba.tobytes(), width, height, width * 4, QImage.Format.Format_RGBA8888).copy()


def load_photo(path: Path) -> QImage:
    with Image.open(path) as source:
        return to_qimage(ImageOps.exif_transpose(source))
