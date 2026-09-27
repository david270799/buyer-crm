"""Standardised product and parcel photos.

Every image is re-encoded to WebP: the main picture fits into 1280×1280
(proportions kept, never upscaled) and is compressed to roughly 80–120 KB,
plus a 400 px thumbnail for lists. Originals are not kept.
"""

import io
import uuid
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from crm.domain.errors import ValidationError
from crm.services.common import Actor, Clock, require_admin
from crm.storage.blobs import BlobStorage

MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_INPUT_PIXELS = 50_000_000  # decompression-bomb guard

MAIN_MAX_SIDE = 1280
THUMB_MAX_SIDE = 400
MAIN_TARGET_BYTES = 120_000
THUMB_TARGET_BYTES = 30_000
MIN_QUALITY, MAX_QUALITY = 45, 85
_MIN_SIDE_WHEN_SHRINKING = 480


@dataclass(frozen=True)
class StoredImage:
    photo_url: str
    thumbnail_url: str
    photo_bytes: int
    thumbnail_bytes: int
    width: int
    height: int


def _open(data: bytes) -> Image.Image:
    if not data:
        raise ValidationError("Пустой файл.")
    if len(data) > MAX_INPUT_BYTES:
        raise ValidationError("Файл больше 20 МБ.")
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > MAX_INPUT_PIXELS:
            raise ValidationError("Слишком большое изображение.")
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValidationError("Файл не похож на изображение (нужен JPG, PNG или WebP).") from None
    image = ImageOps.exif_transpose(image)  # respect phone camera orientation
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _fit(image: Image.Image, max_side: int) -> Image.Image:
    copy = image.copy()
    copy.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)  # keeps ratio, no upscale
    return copy


def _webp(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=quality, method=4)
    return buffer.getvalue()


def _encode(image: Image.Image, max_side: int, target_bytes: int) -> tuple[bytes, Image.Image]:
    """Highest quality that fits the target; shrink the picture only if needed.

    One probe at the minimum quality decides whether the current size can fit
    at all; if it can, a short binary search finds the best quality.
    """
    current = _fit(image, max_side)
    while True:
        smallest = _webp(current, MIN_QUALITY)
        if len(smallest) <= target_bytes:
            best, low, high = smallest, MIN_QUALITY + 1, MAX_QUALITY
            while low <= high:
                quality = (low + high) // 2
                candidate = _webp(current, quality)
                if len(candidate) <= target_bytes:
                    best, low = candidate, quality + 1
                else:
                    high = quality - 1
            return best, current
        if max(current.size) <= _MIN_SIDE_WHEN_SHRINKING:
            return smallest, current  # smallest acceptable, slightly over target
        current = _fit(current, max(_MIN_SIDE_WHEN_SHRINKING, int(max(current.size) * 0.8)))


def process_image(data: bytes) -> tuple[bytes, bytes, tuple[int, int]]:
    image = _open(data)
    main, main_image = _encode(image, MAIN_MAX_SIDE, MAIN_TARGET_BYTES)
    thumb, _ = _encode(main_image, THUMB_MAX_SIDE, THUMB_TARGET_BYTES)
    return main, thumb, main_image.size


class ImageService:
    def __init__(self, storage: BlobStorage, clock: Clock):
        self._storage = storage
        self._clock = clock

    def store(self, actor: Actor, data: bytes, folder: str = "images") -> StoredImage:
        require_admin(actor)
        main, thumb, (width, height) = process_image(data)
        month = self._clock.now().strftime("%Y/%m")
        name = uuid.uuid4().hex
        base = f"{folder}/{month}/{name}"
        photo_url = self._storage.put(f"{base}.webp", main, "image/webp")
        thumbnail_url = self._storage.put(f"{base}_thumb.webp", thumb, "image/webp")
        return StoredImage(photo_url, thumbnail_url, len(main), len(thumb), width, height)
