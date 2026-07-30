"""Unit tests for the image helpers in server.py."""

import asyncio

from PIL import Image, ImageChops, ImageDraw

import server


def _white_bg_with_square(size=(20, 20)):
    """20x20 white image with an opaque dark square at bbox (5, 5, 15, 15).

    PIL's rectangle() is inclusive of x1/y1, so (5, 5, 14, 14) is what yields
    a getbbox() of (5, 5, 15, 15).
    """
    img = Image.new("RGB", size, (255, 255, 255))
    ImageDraw.Draw(img).rectangle((5, 5, 14, 14), fill=(10, 20, 30))
    return img


def test_background_mask_marks_background_white_and_subject_black():
    rgb = _white_bg_with_square()

    mask = server._background_mask(rgb, (255, 255, 255), 10)

    assert mask.mode == "L"
    assert mask.getpixel((0, 0)) == 255      # background corner
    assert mask.getpixel((10, 10)) == 0      # inside the subject


def test_background_mask_inverted_gives_subject_bbox():
    rgb = _white_bg_with_square()

    mask = server._background_mask(rgb, (255, 255, 255), 10)

    assert ImageChops.invert(mask).getbbox() == (5, 5, 15, 15)


def test_background_mask_needs_all_three_channels_within_tolerance():
    # Pure red differs from white on two channels; it must NOT read as
    # background even though the red channel matches exactly.
    rgb = Image.new("RGB", (4, 4), (255, 0, 0))

    mask = server._background_mask(rgb, (255, 255, 255), 10)

    assert mask.getpixel((0, 0)) == 0


def test_remove_background_still_works_after_extraction(tmp_path):
    """Regression guard: the extraction must not change existing behaviour."""
    source = tmp_path / "subject.png"
    _white_bg_with_square().save(source)
    destination = tmp_path / "subject_no_bg.png"

    report = asyncio.run(
        server.remove_background_as_png(str(source), str(destination), tolerance=10)
    )

    assert "Background removed successfully!" in report
    with Image.open(destination) as out:
        alpha = out.convert("RGBA").getchannel("A")
    assert alpha.getpixel((0, 0)) == 0        # background became transparent
    assert alpha.getpixel((10, 10)) == 255    # subject stayed opaque
