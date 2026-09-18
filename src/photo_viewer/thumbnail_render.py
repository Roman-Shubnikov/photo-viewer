"""Thumbnail rendering that runs in worker processes, so it must not import Qt."""

import os
from pathlib import Path

import cv2
import numpy as np
import pillow_heif
from PIL import Image, ImageOps

_JPEG_QUALITY = 88
_EXIF_ORIENTATION = 0x0112
_SIXTEEN_TO_EIGHT_BIT = 1 / 256
_ORIENTATION_TRANSFORMS = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


def init_worker() -> None:
    pillow_heif.register_heif_opener()
    pillow_heif.options.DECODE_THREADS = 1


def render_thumbnail(source: str, target: str, is_video: bool, size: int) -> None:
    image = _video_thumbnail(source, size) if is_video else _photo_thumbnail(source, size)
    partial = Path(f"{target}.{os.getpid()}.tmp")
    image.convert("RGB").save(partial, "JPEG", quality=_JPEG_QUALITY)
    partial.replace(target)


def _photo_thumbnail(source: str, size: int) -> Image.Image:
    with Image.open(source) as photo:
        photo.draft("RGB", (size * 2, size * 2))
        transform = _ORIENTATION_TRANSFORMS.get(photo.getexif().get(_EXIF_ORIENTATION))
        square = _square(photo, size)
    return square.transpose(transform) if transform else square


def _video_thumbnail(source: str, size: int) -> Image.Image:
    capture = cv2.VideoCapture(source)
    try:
        decoded, frame = capture.read()
    finally:
        capture.release()
    if not decoded:
        raise OSError(f"Cannot decode video {source}")
    if frame.dtype != np.uint8:
        frame = cv2.convertScaleAbs(frame, alpha=_SIXTEEN_TO_EIGHT_BIT)
    return _square(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), size)


def _square(image: Image.Image, size: int) -> Image.Image:
    return ImageOps.fit(image, (size, size), Image.Resampling.BOX)
