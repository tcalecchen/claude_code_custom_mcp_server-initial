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


def test_square_box_centres_on_subject_with_margin():
    # bbox 40x20 in a 100x100 image, 5% margin -> side = round(42) = 42
    box, side, capped, shifted = server._square_box((10, 10, 50, 30), (100, 100), 0.05)

    assert side == 42
    assert capped is False
    assert shifted is True          # top would be -1, clamped to 0
    assert box == (9, 0, 51, 42)


def test_square_box_zero_margin_hugs_the_subject():
    box, side, capped, shifted = server._square_box((20, 20, 60, 40), (100, 100), 0.0)

    assert side == 40
    assert capped is False
    assert shifted is False
    assert box == (20, 10, 60, 50)


def test_square_box_clamps_against_the_right_edge():
    # 10x10 subject at the right edge, 60% margin -> side = 16, left would be 87
    box, side, capped, shifted = server._square_box((90, 45, 100, 55), (100, 100), 0.6)

    assert side == 16
    assert shifted is True
    assert box == (84, 42, 100, 58)


def test_square_box_caps_side_at_the_short_edge():
    # Subject fills a 100x60 image; a 105px square cannot come from real pixels.
    box, side, capped, shifted = server._square_box((0, 0, 100, 60), (100, 60), 0.05)

    assert side == 60
    assert capped is True
    assert shifted is False
    assert box == (20, 0, 80, 60)


def test_square_box_never_returns_a_zero_side():
    box, side, capped, shifted = server._square_box((7, 7, 8, 8), (100, 100), 0.0)

    assert side == 1
    assert box == (7, 7, 8, 8)


def test_square_box_output_is_always_square_and_inside_the_image():
    for bbox in [(0, 0, 1, 1), (95, 0, 100, 40), (0, 55, 100, 60), (40, 20, 60, 40)]:
        box, side, _, _ = server._square_box(bbox, (100, 60), 0.05)
        left, top, right, bottom = box
        assert right - left == side
        assert bottom - top == side
        assert 0 <= left and 0 <= top
        assert right <= 100 and bottom <= 60
