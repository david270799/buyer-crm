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


def test_local_storage_reads_and_deletes_only_its_own_files(tmp_path):
    storage = LocalBlobStorage(tmp_path / "media")
    (tmp_path / "secret.txt").write_text("x")
    url = storage.put("orders/a.webp", b"data", "image/webp")

    assert storage.read_url(url) == b"data"
    assert storage.read_url("/media/../secret.txt") is None
    assert storage.read_url("https://example.com/a.webp") is None
    assert storage.delete_url("/media/../secret.txt") is False
    assert storage.delete_url(url) is True
    assert storage.read_url(url) is None
    assert (tmp_path / "secret.txt").exists()


def test_showcase_photo_is_a_sharp_jpeg_up_to_1mb():
    import random

    from PIL import Image

    from crm.services.image_service import process_showcase_image

    rng = random.Random(1)
    noisy = Image.new("RGB", (2400, 1800))
    noisy.putdata(
        [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(2400 * 1800)]
    )
    buffer = io.BytesIO()
    noisy.save(buffer, format="PNG")
    main, thumb, size = process_showcase_image(buffer.getvalue())
    assert main[:3] == b"\xff\xd8\xff"  # JPEG: any gallery takes it
    assert len(main) <= 1_000_000 and size[0] == size[1] and size[0] >= 1000
    assert thumb[:4] == b"RIFF"


def _viewer_screenshot() -> Image.Image:
    """A phone screenshot of a shop's photo viewer: black bars with the clock,
    «‹», «1 / 5» and the phone's buttons around a light photo of a dark shoe."""
    from PIL import ImageDraw

    shot = Image.new("RGB", (1080, 2520), (0, 0, 0))
    draw = ImageDraw.Draw(shot)
    draw.text((960, 40), "24", fill=(255, 255, 255))
    draw.line((80, 200, 60, 220, 80, 240), fill=(255, 255, 255), width=6)
    draw.rectangle((0, 648, 1079, 1727), fill=(230, 230, 230))  # the photo
    draw.rectangle((60, 1000, 1000, 1350), fill=(15, 15, 15))  # the shoe
    draw.rounded_rectangle((480, 2080, 600, 2160), 10, fill=(80, 80, 80))
    draw.text((520, 2110), "1 / 5", fill=(255, 255, 255))
    draw.line((230, 2440, 230, 2480), fill=(255, 255, 255), width=4)
    return shot


def test_photo_viewer_screenshot_loses_its_black_bars():
    """The owner (02.11.2026): «он сам всё обрезает»."""
    from crm.services.image_service import trim_screen_bars

    photo = trim_screen_bars(_viewer_screenshot())
    assert abs(photo.width - 1080) <= 10 and abs(photo.height - 1080) <= 20
    assert photo.convert("L").getpixel((5, 5)) == 230  # no black edge left
    assert photo.convert("L").getpixel((photo.width - 5, photo.height - 5)) == 230


@pytest.mark.parametrize(
    "picture",
    [
        Image.new("RGB", (900, 1600), (0, 0, 0)),  # all dark
        Image.new("RGB", (900, 1600), (250, 250, 250)),  # all light
        Image.new("RGB", (1200, 900), (40, 120, 200)),  # an ordinary photo
    ],
)
def test_other_pictures_are_not_trimmed(picture):
    from crm.services.image_service import trim_screen_bars

    assert trim_screen_bars(picture).size == picture.size


def test_a_dark_photo_with_a_light_spot_is_not_trimmed():
    from PIL import ImageDraw

    from crm.services.image_service import trim_screen_bars

    shot = Image.new("RGB", (1000, 1000), (10, 10, 10))
    ImageDraw.Draw(shot).ellipse((300, 300, 700, 700), fill=(240, 240, 240))
    assert trim_screen_bars(shot).size == shot.size  # a photo, not bars


def test_only_admin_uploads_are_trimmed(tmp_path):
    """Client photos stay whole; «Добавить фото» in the Mini App trims."""
    buffer = io.BytesIO()
    _viewer_screenshot().save(buffer, format="PNG")
    kept, _, _ = process_image(buffer.getvalue())
    trimmed, _, _ = process_image(buffer.getvalue(), trim=True)
    corner = (20, 20)
    assert Image.open(io.BytesIO(kept)).convert("L").getpixel(corner) > 245  # white padding
    assert abs(Image.open(io.BytesIO(trimmed)).convert("L").getpixel(corner) - 230) < 8
