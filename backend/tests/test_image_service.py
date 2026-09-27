import io
import random

import pytest
from PIL import Image

from crm.domain.enums import Role
from crm.domain.errors import PermissionDeniedError, ValidationError
from crm.services.common import Actor
from crm.services.image_service import (
    MAIN_MAX_SIDE,
    MAIN_TARGET_BYTES,
    THUMB_MAX_SIDE,
    ImageService,
    process_image,
)
from crm.storage.blobs import LocalBlobStorage, MemoryBlobStorage


def _jpeg(width, height, noise=False, exif_orientation=None) -> bytes:
    image = Image.new("RGB", (width, height))
    if noise:
        rnd = random.Random(1)
        image.putdata(
            [
                (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                for _ in range(width * height)
            ]
        )
    else:
        for x in range(0, width, 8):
            for y in range(0, height, 8):
                image.paste((x * 255 // width, y * 255 // height, 120), (x, y, x + 8, y + 8))
    buffer = io.BytesIO()
    exif = None
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
    image.save(buffer, format="JPEG", quality=95, exif=exif if exif else b"")
    return buffer.getvalue()


def _open(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def test_large_photo_becomes_standard_webp_within_target():
    main, thumb, size = process_image(_jpeg(4000, 3000))
    main_img, thumb_img = _open(main), _open(thumb)
    assert main_img.format == thumb_img.format == "WEBP"
    assert max(main_img.size) == MAIN_MAX_SIDE
    assert main_img.size == size == (1280, 960)  # proportions kept
    assert len(main) <= MAIN_TARGET_BYTES
    assert max(thumb_img.size) == THUMB_MAX_SIDE


def test_hard_to_compress_photo_is_shrunk_until_it_fits():
    main, _, size = process_image(_jpeg(1600, 1200, noise=True))
    assert len(main) <= MAIN_TARGET_BYTES * 1.05 or max(size) <= 480
    assert size[0] / size[1] == pytest.approx(4 / 3, rel=0.02)


def test_small_image_is_not_upscaled():
    _, _, size = process_image(_jpeg(300, 200))
    assert size == (300, 200)


def test_transparent_png_gets_white_background():
    image = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    main, _, _ = process_image(buffer.getvalue())
    assert _open(main).convert("RGB").getpixel((25, 25)) == pytest.approx((255, 255, 255), abs=3)


def test_exif_rotation_is_applied():
    _, _, size = process_image(_jpeg(400, 200, exif_orientation=6))  # rotate 90°
    assert size == (200, 400)


@pytest.mark.parametrize("data", [b"", b"not an image", b"\x89PNG\r\n\x1a\nbroken"])
def test_non_images_are_rejected(data):
    with pytest.raises(ValidationError):
        process_image(data)


def test_store_writes_two_files_and_requires_admin(tmp_path):
    from conftest import FakeClock

    storage = MemoryBlobStorage()
    service = ImageService(storage, FakeClock())
    stored = service.store(Actor.mini_app(1, Role.ADMIN), _jpeg(800, 600))
    assert stored.photo_url.endswith(".webp") and stored.thumbnail_url.endswith("_thumb.webp")
    assert len(storage.files) == 2
    assert all(ctype == "image/webp" for _, ctype in storage.files.values())
    with pytest.raises(PermissionDeniedError):
        service.store(Actor.mini_app(2, Role.CLIENT), _jpeg(10, 10))


def test_local_storage_stays_inside_root(tmp_path):
    storage = LocalBlobStorage(tmp_path / "media")
    assert storage.put("a/b.webp", b"x", "image/webp") == "/media/a/b.webp"
    assert (tmp_path / "media" / "a" / "b.webp").read_bytes() == b"x"
    with pytest.raises(ValueError):
        storage.put("../escape.webp", b"x", "image/webp")
