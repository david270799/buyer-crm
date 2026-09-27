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


def test_large_photo_becomes_square_webp_within_target():
    main, thumb, size = process_image(_jpeg(4000, 3000))
    main_img, thumb_img = _open(main), _open(thumb)
    assert main_img.format == thumb_img.format == "WEBP"
    assert main_img.size == size == (MAIN_MAX_SIDE, MAIN_MAX_SIDE)
    assert 20_000 < len(main) <= MAIN_TARGET_BYTES
    assert thumb_img.size == (THUMB_MAX_SIDE, THUMB_MAX_SIDE)


def test_whole_picture_is_kept_centred_on_white():
    # A red 400×200 picture with a blue stripe across the middle.
    image = Image.new("RGB", (400, 200), (200, 30, 30))
    image.paste((20, 40, 220), (0, 90, 400, 110))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    main, _, size = process_image(buffer.getvalue())

    square = _open(main).convert("RGB")
    assert size == (400, 400)
    assert square.getpixel((200, 20)) == pytest.approx((255, 255, 255), abs=8)  # white padding
    assert square.getpixel((200, 120)) == pytest.approx((200, 30, 30), abs=12)
    assert square.getpixel((200, 200)) == pytest.approx((20, 40, 220), abs=12)  # centred stripe
    assert square.getpixel((3, 120)) == pytest.approx((200, 30, 30), abs=12)  # full width kept


def test_hard_to_compress_photo_is_shrunk_until_it_fits():
    main, _, size = process_image(_jpeg(2400, 1800, noise=True))
    assert len(main) <= MAIN_TARGET_BYTES * 1.05 or max(size) <= 480
    assert size[0] == size[1]


def test_small_image_is_not_upscaled():
    _, _, size = process_image(_jpeg(300, 200))
    assert size == (300, 300)


def test_transparent_png_gets_white_background():
    image = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    main, _, _ = process_image(buffer.getvalue())
    assert _open(main).convert("RGB").getpixel((25, 25)) == pytest.approx((255, 255, 255), abs=3)


def test_exif_rotation_is_applied():
    # A 400×200 JPEG marked "rotate 90°" is a portrait photo: padding goes left and right.
    image = Image.new("RGB", (400, 200), (250, 250, 250))
    image.paste((10, 10, 10), (0, 0, 400, 100))  # dark top half before rotation
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6
    image.save(buffer, format="JPEG", quality=95, exif=exif)

    main, _, size = process_image(buffer.getvalue())

    square = _open(main).convert("RGB")
    assert size == (400, 400)
    # Rotated to portrait: white padding left and right, the dark half on the right.
    assert square.getpixel((40, 200))[0] > 240 and square.getpixel((260, 200))[0] < 60


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
    # Photos of the client's own orders are stored by the intake on their behalf.
    client_photo = service.store(Actor.telegram(2, Role.CLIENT), _jpeg(10, 10), folder="orders")
    assert "/orders/" in client_photo.photo_url or client_photo.photo_url.startswith(
        "memory://orders"
    )


def test_local_storage_stays_inside_root(tmp_path):
    storage = LocalBlobStorage(tmp_path / "media")
    assert storage.put("a/b.webp", b"x", "image/webp") == "/media/a/b.webp"
    assert (tmp_path / "media" / "a" / "b.webp").read_bytes() == b"x"
    with pytest.raises(ValueError):
        storage.put("../escape.webp", b"x", "image/webp")
