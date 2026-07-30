"""End-to-end tests for the crop_to_square MCP tool."""

import asyncio

from PIL import Image, ImageDraw

import server


def run(**kwargs):
    return asyncio.run(server.crop_to_square(**kwargs))


def _alpha_subject_png(path, size=(40, 30), box=(5, 5, 14, 14)):
    """Save an RGBA PNG whose opaque region is `box` (inclusive coords)."""
    img = Image.new("RGBA", size, (255, 255, 255, 0))
    alpha = Image.new("L", size, 0)
    ImageDraw.Draw(alpha).rectangle(box, fill=255)
    img.putalpha(alpha)
    img.save(path)
    return path


def _opaque_subject_jpeg(path, size=(40, 30), box=(5, 5, 14, 14)):
    img = Image.new("RGB", size, (255, 255, 255))
    ImageDraw.Draw(img).rectangle(box, fill=(10, 20, 30))
    img.save(path, "JPEG", quality=95)
    return path


def test_crops_a_square_from_the_alpha_subject(tmp_path):
    source = _alpha_subject_png(tmp_path / "toy.png")
    destination = tmp_path / "out.png"

    report = run(image_path=str(source), output_path=str(destination), margin=0.2)

    assert "Cropped to square successfully!" in report
    assert "alpha channel" in report
    with Image.open(destination) as out:
        assert out.size == (12, 12)       # round(10 * 1.2)
        assert out.mode == "RGBA"


def test_defaults_output_to_name_square_png(tmp_path):
    source = _alpha_subject_png(tmp_path / "toy.png")

    report = run(image_path=str(source))

    expected = tmp_path / "toy_square.png"
    assert expected.exists()
    assert str(expected) in report


def test_opaque_jpeg_falls_back_to_background_detection(tmp_path):
    source = _opaque_subject_jpeg(tmp_path / "toy.jpg")

    report = run(image_path=str(source), tolerance=40, margin=0.2)

    assert "background colour" in report
    assert "auto-detected" in report
    with Image.open(tmp_path / "toy_square.png") as out:
        assert out.size[0] == out.size[1]


def test_output_is_png_even_from_a_jpeg_source(tmp_path):
    source = _opaque_subject_jpeg(tmp_path / "toy.jpg")

    run(image_path=str(source), tolerance=40)

    with Image.open(tmp_path / "toy_square.png") as out:
        assert out.format == "PNG"


def test_reports_when_the_side_is_capped_at_the_short_edge(tmp_path):
    # 36x30 subject in a 40x30 frame: no 36px square of real pixels exists.
    # The two transparent columns on each side matter - a subject filling the
    # frame edge to edge would leave alpha fully opaque and route this image
    # down the background-colour path instead of the alpha path.
    source = _alpha_subject_png(tmp_path / "wide.png", size=(40, 30), box=(2, 0, 37, 29))

    report = run(image_path=str(source), margin=0.0)

    assert "capped at the image's short edge" in report
    with Image.open(tmp_path / "wide_square.png") as out:
        assert out.size == (30, 30)


def test_reports_when_the_window_shifts_off_centre(tmp_path):
    # Subject hugs the left edge, so the square cannot be centred on it.
    source = _alpha_subject_png(tmp_path / "edge.png", size=(40, 30), box=(0, 10, 9, 19))

    report = run(image_path=str(source), margin=0.6)

    assert "shifted inward" in report


def test_errors_when_the_file_is_missing(tmp_path):
    report = run(image_path=str(tmp_path / "nope.png"))

    assert report.startswith("Error:")
    assert "not found" in report


def test_errors_on_out_of_range_tolerance(tmp_path):
    source = _alpha_subject_png(tmp_path / "toy.png")

    report = run(image_path=str(source), tolerance=300)

    assert report.startswith("Error:")
    assert "tolerance" in report


def test_errors_on_negative_margin(tmp_path):
    source = _alpha_subject_png(tmp_path / "toy.png")

    report = run(image_path=str(source), margin=-0.1)

    assert report.startswith("Error:")
    assert "margin" in report


def test_errors_on_malformed_bg_color(tmp_path):
    source = _opaque_subject_jpeg(tmp_path / "toy.jpg")

    report = run(image_path=str(source), bg_color="not-a-colour")

    assert report.startswith("Error:")


def test_errors_when_no_subject_is_found(tmp_path):
    source = tmp_path / "blank.jpg"
    Image.new("RGB", (40, 30), (255, 255, 255)).save(source)

    report = run(image_path=str(source), tolerance=10)

    assert report.startswith("Error:")
    assert "tolerance" in report      # the hint tells the user what to change
