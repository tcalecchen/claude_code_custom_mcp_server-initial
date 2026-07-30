# crop_to_square Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `crop_to_square` MCP tool that crops an image to a square centred on its subject, detecting the subject from the alpha channel when present and from background-colour detection otherwise.

**Architecture:** Three new pure-ish helpers in `server.py` — `_background_mask` (extracted from `remove_background_as_png`), `_subject_bbox` (picks the alpha or background-colour path and returns a bounding box), and `_square_box` (pure integer geometry, no PIL) — composed by one new `@mcp.tool()` async function. Splitting the geometry out as a PIL-free function is what makes the clamping and short-edge-cap edge cases unit-testable.

**Tech Stack:** Python 3.11 (Docker) / 3.13 (local dev), Pillow, FastMCP (`mcp` SDK), pytest 8 (dev-only), Docker.

**Spec:** `docs/superpowers/specs/2026-07-30-crop-to-square-design.md`

## Global Constraints

- `requirements.txt` stays minimal — **pytest must not go in it.** Test dependencies live in a new `requirements-dev.txt` so they never enter the Docker image.
- All full-resolution image work stays in PIL's C layer (channel LUTs via `.point()`, `ImageChops`, `getbbox()`). **Never** introduce a per-pixel `getpixel`/`putpixel` loop over a full-size image. `getpixel` in tests on 20x20 synthetic images is fine.
- Tools return descriptive error **strings**, they do not raise. Follow the existing pattern in `server.py`.
- Default output path is `<name>_square.png`, a sibling of the input — matching `resize_image` and `remove_background_as_png`. (`CLAUDE.md` mentions `./images/` as a default; that applies to `fetch_toy_image`, which generates files from nothing. Transform tools write next to their input.)
- Output is always PNG so alpha survives chaining from `remove_background_as_png`.
- `ALPHA_THRESHOLD = 8` is a module-level constant, never a tool parameter.
- `images/` is in `.gitignore`. Tests must build synthetic images in `tmp_path` and must not depend on any file in `images/`.
- Every test value is chosen to avoid `.5` rounding boundaries, so Python's banker's rounding in `round()` is never load-bearing in an assertion.
- Commit messages end with:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `server.py` | Modify | All MCP tools and image helpers. Existing repo convention is a single module; keep it. |
| `requirements-dev.txt` | Create | Dev-only test dependencies. Never referenced by the Dockerfile. |
| `conftest.py` (repo root) | Create | Empty-but-commented file. Its presence at the root is what makes pytest prepend the repo root to `sys.path`, so `import server` resolves from `tests/`. |
| `tests/test_image_helpers.py` | Create | Unit tests for `_background_mask`, `_subject_bbox`, `_square_box`, plus the `remove_background_as_png` regression test. |
| `tests/test_crop_to_square.py` | Create | End-to-end tests for the `crop_to_square` tool: output geometry, default naming, report text, error paths. |
| `.gitignore` | Modify | Add `__pycache__/` and `.pytest_cache/`. |
| `CLAUDE.md` | Modify | Document the new tool and the shared helper. |

---

## Task 0: Branch and local dev setup

**Files:**
- Create: `requirements-dev.txt`, `conftest.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing
- Produces: a working `pytest` invocation that can `import server`

Working directly on a branch, **not** a git worktree. Per `CLAUDE.md`, a worktree would need its own `.mcp.json` absolute paths and its own Docker image tag; that setup cost is not worth it for a single-module change.

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feat/crop-to-square
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```text
# Dev-only dependencies. NOT installed into the Docker image - the Dockerfile
# only ever reads requirements.txt, which stays minimal on purpose.
pytest>=8.0
```

- [ ] **Step 3: Create `conftest.py` at the repo root**

```python
"""Present so pytest prepends the repo root to sys.path.

With pytest's default "prepend" import mode, the directory inserted into
sys.path is the test file's first non-package parent - i.e. `tests/`, which
would leave `import server` unresolvable. A root-level conftest.py makes
pytest insert the repo root as well. Intentionally empty otherwise.
"""
```

- [ ] **Step 4: Append the ignore entries to `.gitignore`**

The current file's last line is `images/` **with no trailing newline** — add one before appending, or `images/__pycache__/` will be written as a single broken line.

Resulting file:

```text
venv/
.venv-markitdown/
images/
__pycache__/
.pytest_cache/
```

- [ ] **Step 5: Install dependencies locally**

`mcp` is the only missing piece locally (Pillow 11.1.0 and pytest 8.3.4 are already present), but install both files so the environment is reproducible:

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

- [ ] **Step 6: Verify pytest can import the server module**

```bash
python -c "import server; print('import OK')"
pytest --collect-only -q
```

Expected: `import OK`, and pytest reports `no tests ran` / collects 0 items **without** an import error. If `import server` fails, fix that before writing any test — every task below depends on it.

- [ ] **Step 7: Commit**

```bash
git add requirements-dev.txt conftest.py .gitignore
git commit -m "$(cat <<'EOF'
chore: add dev-only pytest setup

pytest goes in requirements-dev.txt, not requirements.txt, so it never
enters the Docker image. Root conftest.py puts the repo root on sys.path
so tests can import server.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 1: Extract `_background_mask`

**Files:**
- Modify: `server.py` — insert helper after `_estimate_bg_color` (ends line 236); replace the inline mask block at lines 333-339
- Test: `tests/test_image_helpers.py` (create)

**Interfaces:**
- Consumes: `_estimate_bg_color`, `_parse_color`, `_border_connected` (all existing)
- Produces: `_background_mask(rgb: Image.Image, target: tuple[int, int, int], tolerance: int) -> Image.Image` — an `"L"`-mode mask, 255 where the pixel is within `tolerance` of `target` on **every** channel, 0 elsewhere. Task 3 consumes this.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_image_helpers.py`:

```python
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
```

Note on the regression test: `remove_background_as_png` is `async` and decorated with `@mcp.tool()`. FastMCP's decorator registers the function and returns it unchanged, so `asyncio.run(...)` on it works and needs no `pytest-asyncio`. If that ever stops holding, the collection error will be obvious and immediate.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_image_helpers.py -v
```

Expected: the three `_background_mask` tests FAIL with `AttributeError: module 'server' has no attribute '_background_mask'`. `test_remove_background_still_works_after_extraction` PASSES already — that is correct and intended; it is a guard, not a driver.

- [ ] **Step 3: Add the helper to `server.py`**

Insert immediately after `_estimate_bg_color` (i.e. after line 236, before `_border_connected`):

```python
def _background_mask(rgb: Image.Image, target, tolerance: int) -> Image.Image:
    """Mask of pixels within `tolerance` of `target` on every channel.

    Per-channel lookup tables run inside PIL's C layer, so this stays fast even
    on multi-megapixel images (the old per-pixel Python loop took ~35s on a
    3815x3815 photo). Never replace this with a getpixel/putpixel loop.
    """
    channel_masks = [
        channel.point(lambda v, t=t: 255 if abs(v - t) <= tolerance else 0)
        for channel, t in zip(rgb.split(), target)
    ]
    return ImageChops.multiply(
        ImageChops.multiply(channel_masks[0], channel_masks[1]), channel_masks[2]
    )
```

- [ ] **Step 4: Rewire `remove_background_as_png` to call it**

Replace lines 330-339 (the comment plus the `channel_masks` / `bg_mask` block) with:

```python
        bg_mask = _background_mask(rgb, target, tolerance)
```

Everything from `if keep_enclosed:` onward is untouched. This is pure code movement — same operations, same order.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
pytest tests/test_image_helpers.py -v
```

Expected: all 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_image_helpers.py
git commit -m "$(cat <<'EOF'
refactor: extract _background_mask helper

Pure code movement out of remove_background_as_png so the channel-LUT mask
construction lives in one place, ready for crop_to_square to reuse.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `_square_box` geometry

**Files:**
- Modify: `server.py` — insert after `_border_connected` (currently ends line 284)
- Test: `tests/test_image_helpers.py` (append)

**Interfaces:**
- Consumes: nothing (no PIL, pure integer arithmetic)
- Produces: `_square_box(bbox, image_size, margin) -> tuple[tuple[int, int, int, int], int, bool, bool]`, returning `(box, side, capped, shifted)` where `box` is `(left, top, right, bottom)` suitable for `Image.crop`, `side` is the square's edge length, `capped` is True when `side` was limited by the image's short edge, and `shifted` is True when the window had to slide away from the subject centre. Task 4 consumes this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_image_helpers.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_image_helpers.py -v -k square_box
```

Expected: all 6 FAIL with `AttributeError: module 'server' has no attribute '_square_box'`.

- [ ] **Step 3: Write the implementation**

Insert into `server.py` after `_border_connected`:

```python
def _square_box(bbox, image_size, margin: float):
    """Square crop box centred on `bbox`, clamped to stay inside the image.

    Returns (box, side, capped, shifted):
      box     - (left, top, right, bottom) for Image.crop
      side    - the square's edge length
      capped  - side was limited by the image's short edge
      shifted - the window slid away from the subject centre to stay in bounds

    The result is always a pure crop of real pixels: nothing is ever padded in.
    """
    left0, top0, right0, bottom0 = bbox
    width, height = image_size

    side = round(max(right0 - left0, bottom0 - top0) * (1 + margin))
    limit = min(width, height)
    capped = side > limit
    side = max(1, min(side, limit))

    wanted_left = round((left0 + right0) / 2 - side / 2)
    wanted_top = round((top0 + bottom0) / 2 - side / 2)
    left = min(max(wanted_left, 0), width - side)
    top = min(max(wanted_top, 0), height - side)
    shifted = (left, top) != (wanted_left, wanted_top)

    return (left, top, left + side, top + side), side, capped, shifted
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_image_helpers.py -v
```

Expected: all 10 PASS (4 from Task 1 + 6 here).

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_image_helpers.py
git commit -m "$(cat <<'EOF'
feat: add _square_box crop geometry helper

PIL-free integer arithmetic so the clamping and short-edge-cap edge cases
are directly unit-testable.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `_subject_bbox` detection

**Files:**
- Modify: `server.py` — add `ALPHA_THRESHOLD` constant near the top (after the `mcp = FastMCP(...)` line, currently line 27); add `_subject_bbox` after `_square_box`
- Test: `tests/test_image_helpers.py` (append)

**Interfaces:**
- Consumes: `_background_mask` (Task 1), `_parse_color`, `_estimate_bg_color`
- Produces: `_subject_bbox(img: Image.Image, tolerance: int, bg_color: Optional[str]) -> tuple[Optional[tuple[int, int, int, int]], str]`. `img` must be RGBA. Returns `(bbox, method)`; `bbox` is `None` when no subject was found. `method` is a human-readable description for the tool's report. Raises `ValueError` from `_parse_color` on a malformed `bg_color`. Task 4 consumes this.

- [ ] **Step 1: Write the failing tests**

First add `pytest` to the import block at the top of `tests/test_image_helpers.py`
(one test below asserts on a raised exception):

```python
import asyncio

import pytest
from PIL import Image, ImageChops, ImageDraw

import server
```

Then append:

```python
def _transparent_bg_with_square(size=(20, 20)):
    """RGBA image whose only opaque region is bbox (5, 5, 15, 15).

    Pixel (2, 2) gets alpha 4 - the kind of near-transparent fringe the
    Gaussian feather in remove_background_as_png leaves behind. It sits below
    ALPHA_THRESHOLD and must not widen the bbox.
    """
    img = Image.new("RGBA", size, (255, 255, 255, 0))
    alpha = Image.new("L", size, 0)
    ImageDraw.Draw(alpha).rectangle((5, 5, 14, 14), fill=255)
    alpha.putpixel((2, 2), 4)
    img.putalpha(alpha)
    return img


def test_subject_bbox_uses_alpha_when_image_has_transparency():
    bbox, method = server._subject_bbox(_transparent_bg_with_square(), 30, None)

    assert bbox == (5, 5, 15, 15)      # (2, 2) fringe excluded by ALPHA_THRESHOLD
    assert "alpha" in method


def test_subject_bbox_falls_back_to_auto_detected_background():
    img = _white_bg_with_square().convert("RGBA")

    bbox, method = server._subject_bbox(img, 10, None)

    assert bbox == (5, 5, 15, 15)
    assert "auto-detected" in method


def test_subject_bbox_honours_explicit_bg_color():
    img = _white_bg_with_square().convert("RGBA")

    bbox, method = server._subject_bbox(img, 10, "#ffffff")

    assert bbox == (5, 5, 15, 15)
    assert "specified" in method


def test_subject_bbox_returns_none_when_everything_is_background():
    img = Image.new("RGBA", (20, 20), (255, 255, 255, 255))

    bbox, _ = server._subject_bbox(img, 10, None)

    assert bbox is None


def test_subject_bbox_rejects_a_malformed_bg_color():
    img = _white_bg_with_square().convert("RGBA")

    with pytest.raises(ValueError):
        server._subject_bbox(img, 10, "not-a-colour")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_image_helpers.py -v -k subject_bbox
```

Expected: all 5 FAIL with `AttributeError: module 'server' has no attribute '_subject_bbox'`.

- [ ] **Step 3: Add the constant**

In `server.py`, after `mcp = FastMCP("image-tools-server")`:

```python
# Alpha values at or below this count as fully transparent when locating a
# subject. Its job is to discard the near-transparent fringe left by the
# Gaussian feather in remove_background_as_png. Deliberately not a tool
# parameter - there is no use case for tuning it from outside.
ALPHA_THRESHOLD = 8
```

- [ ] **Step 4: Write the implementation**

Insert into `server.py` after `_square_box`:

```python
def _subject_bbox(img: Image.Image, tolerance: int, bg_color: Optional[str]):
    """Locate the subject in an RGBA image.

    Returns (bbox, method). `bbox` is (left, top, right, bottom), or None when
    the whole image reads as background. `method` describes how the subject was
    found, for the tool's report.

    Uses the alpha channel when the image carries real transparency, otherwise
    falls back to background-colour detection. The fallback deliberately skips
    _border_connected: background-coloured regions enclosed by the subject are
    inside its outer extent by definition, so they cannot move the bounding box
    and the flood fill would cost time for nothing.
    """
    alpha = img.getchannel("A")
    if alpha.getextrema()[0] < 255:
        subject = alpha.point(lambda v: 255 if v > ALPHA_THRESHOLD else 0)
        return subject.getbbox(), "alpha channel"

    rgb = img.convert("RGB")
    if bg_color:
        target = _parse_color(bg_color)
        method = f"background colour rgb{target} (specified)"
    else:
        target = _estimate_bg_color(rgb)
        method = f"background colour rgb{target} (auto-detected)"

    subject = ImageChops.invert(_background_mask(rgb, target, tolerance))
    return subject.getbbox(), method
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
pytest tests/test_image_helpers.py -v
```

Expected: all 15 PASS.

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_image_helpers.py
git commit -m "$(cat <<'EOF'
feat: add _subject_bbox content-aware subject detection

Alpha channel when the image has real transparency, background-colour
detection otherwise. Skips _border_connected - enclosed background cannot
change the outer bounding box.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: The `crop_to_square` tool

**Files:**
- Modify: `server.py` — add the tool after `remove_background_as_png`, before the `if __name__ == "__main__":` block
- Test: `tests/test_crop_to_square.py` (create)

**Interfaces:**
- Consumes: `_subject_bbox` (Task 3), `_square_box` (Task 2)
- Produces: the `crop_to_square` MCP tool. Nothing downstream consumes it in code; Task 5 documents it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_crop_to_square.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_crop_to_square.py -v
```

Expected: all 11 FAIL with `AttributeError: module 'server' has no attribute 'crop_to_square'`.

- [ ] **Step 3: Write the implementation**

Insert into `server.py` after `remove_background_as_png`, before `if __name__ == "__main__":`:

```python
@mcp.tool()
async def crop_to_square(
    image_path: str,
    output_path: Optional[str] = None,
    margin: float = 0.05,
    tolerance: int = 30,
    bg_color: Optional[str] = None,
) -> str:
    """Crop an image to a square centred on its subject.

    The subject is located from the alpha channel when the image carries real
    transparency, and from background-colour detection otherwise. The result is
    always a pure crop: the square is clamped inside the image and its side is
    capped at the short edge, so no pixels are ever padded in.

    Args:
        image_path: Image to crop.
        output_path: Destination PNG. Defaults to "<name>_square.png".
        margin: Breathing room around the subject, as a fraction of its longest
            side (0.05 = 5%).
        tolerance: Per-channel distance from the background colour that still
            counts as background (0-255). Opaque images only.
        bg_color: Background colour as "#rrggbb" or "r,g,b". Auto-detected from
            the image border when omitted. Opaque images only.
    """

    if not os.path.exists(image_path):
        return f"Error: Image file not found: {image_path}"

    if not 0 <= tolerance <= 255:
        return f"Error: tolerance must be between 0 and 255, got {tolerance}"

    if margin < 0:
        return f"Error: margin must not be negative, got {margin}"

    started = time.time()

    try:
        with Image.open(image_path) as opened:
            img = opened.convert("RGBA")

        try:
            bbox, method = _subject_bbox(img, tolerance, bg_color)
        except ValueError as e:
            return f"Error: {e}"

        if bbox is None:
            return (
                "Error: no subject found - the whole image reads as background. "
                "Try a lower tolerance or pass bg_color explicitly."
            )

        box, side, capped, shifted = _square_box(bbox, img.size, margin)
        cropped = img.crop(box)

        if not output_path:
            name, _ = os.path.splitext(image_path)
            output_path = f"{name}_square.png"

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        cropped.save(output_path, "PNG")

        result = "Cropped to square successfully!\n"
        result += f"Subject detected from: {method}\n"
        result += f"Original size: {img.width}x{img.height}\n"
        result += f"Subject bbox: {bbox[0]},{bbox[1]} to {bbox[2]},{bbox[3]}\n"
        result += f"Output: {side}x{side} at offset {box[0]},{box[1]}\n"
        if capped:
            result += (
                f"Note: side length capped at the image's short edge "
                f"({min(img.size)}px) - the subject is too large for a square "
                "of real pixels to enclose it.\n"
            )
        if shifted:
            result += (
                "Note: crop window shifted inward to stay inside the image, so "
                "the subject is not exactly centred.\n"
            )
        result += f"Elapsed: {time.time() - started:.2f}s\n"
        result += f"Saved to: {output_path}"
        return result

    except Exception as e:
        return f"Error cropping image: {str(e)}"
```

- [ ] **Step 4: Run the full suite to verify everything passes**

```bash
pytest tests/ -v
```

Expected: 26 PASS (15 helpers + 11 tool), 0 failures.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_crop_to_square.py
git commit -m "$(cat <<'EOF'
feat: add crop_to_square MCP tool

Content-aware square crop: alpha-channel subject bbox with a
background-colour fallback, clamped so the output is always a pure crop of
real pixels.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Container verification and documentation

**Files:**
- Modify: `CLAUDE.md` — the MCP tools list, the Image Processing Pipeline section, and the Superpowers TDD note
- Test: manual, in the container

Unit tests run against the local interpreter. This task confirms the tool actually works inside the Docker image the MCP client runs, and against real photographs rather than synthetic 40x30 blocks. **A successful `docker build` is a build, not a passing test — do not report it as one.**

- [ ] **Step 1: Rebuild the image**

```bash
docker build -t mcp-toy-image-tools-server .
```

Expected: build succeeds. Confirm `requirements-dev.txt` was **not** installed — `pytest` must not appear in the build log's pip output.

- [ ] **Step 2: Run the MCP initialize handshake smoke test**

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
  | docker run --rm -i mcp-toy-image-tools-server
```

Expected: a JSON result containing `"serverInfo":{"name":"image-tools-server",...}`. A `crop_to_square` syntax error would surface here as a non-zero exit with a traceback.

- [ ] **Step 3: Confirm the tool is advertised**

```bash
printf '%s\n%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | docker run --rm -i mcp-toy-image-tools-server
```

Expected: the `tools/list` response lists `crop_to_square` alongside the three existing tools, with `margin`, `tolerance`, and `bg_color` in its input schema.

- [ ] **Step 4: Exercise it against real images**

Reconnect the server in Claude Code (`/mcp` → reconnect `image-tools-server-docker`), then run all three paths against files in `./images/`:

```text
crop_to_square on images/cute-robot-1-round-nobg.png   -> alpha path
crop_to_square on images/cute-robot-1-round.png        -> background-colour fallback
crop_to_square on images/coffee-bean-nobg.png          -> alpha path, different aspect
```

For each, confirm: the output is square, the report names the expected detection method, and — by opening the PNG — the subject is actually framed sensibly with no background band on one side. If the fallback path mis-frames a photo, that is a `tolerance` tuning observation to report, not necessarily a bug.

- [ ] **Step 5: Update `CLAUDE.md`**

Three edits:

1. Under **MCP Tools Available**, append:

```markdown
- `crop_to_square` - Crops an image to a square centred on its subject (alpha
  bbox, falling back to background-colour detection)
```

2. Under **Image Processing Pipeline**, add:

```markdown
- Background-colour masking lives in one place: `_background_mask` builds the
  per-channel LUT mask shared by `remove_background_as_png` and
  `crop_to_square`'s opaque fallback path.
- `crop_to_square` never pads. The square's side is capped at the image's short
  edge and the window is clamped inside the frame, so the output is always real
  pixels — the report says so explicitly when either limit kicks in.
- `crop_to_square`'s fallback path skips `_border_connected` on purpose:
  enclosed background regions sit inside the subject's outer extent, so they
  cannot move the bounding box.
```

3. Under **Superpowers Skills → Project-specific adaptations**, the
   `test-driven-development` paragraph currently says there is no test suite.
   Replace its opening claim with the current state:

```markdown
**`test-driven-development` — there is a partial test suite.** `tests/` covers
the image helpers and `crop_to_square` via pytest (`pip install -r
requirements-dev.txt`, then `pytest tests/ -v`). `pytest` is deliberately kept
out of `requirements.txt` so it never enters the Docker image. There is no
coverage for `fetch_toy_image` (it hits the network) or for the MCP transport
layer, so for changes in those areas substitute the container verification path:
```

Keep the existing numbered Docker/handshake list that follows, and keep the
"State explicitly which of the two you are doing" sentence.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: document crop_to_square and the pytest setup

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Final full-suite run before handoff**

```bash
pytest tests/ -v
```

Expected: 26 PASS. Then use `superpowers:finishing-a-development-branch` to decide how `feat/crop-to-square` gets integrated.

---

## Self-Review Notes

Checked against `docs/superpowers/specs/2026-07-30-crop-to-square-design.md`:

| Spec section | Covered by |
|---|---|
| Tool signature | Task 4 Step 3 |
| Alpha path + `ALPHA_THRESHOLD` | Task 3 (constant Step 3, impl Step 4, fringe test Step 1) |
| Opaque fallback, no `_border_connected` | Task 3 Step 4 + docstring rationale |
| `getbbox()` returns None | Task 3 test + Task 4 error path |
| `_background_mask` refactor | Task 1 |
| Crop geometry, cap, clamp | Task 2 |
| Error handling (5 cases) | Task 4 Step 1 tests 7-11 |
| Success report incl. cap/shift notes | Task 4 Step 3 + tests 5-6 |
| Verification (build, handshake, real images, regression) | Task 5 + Task 1 Step 1 regression test |
| Documentation | Task 5 Step 5 |

Naming is consistent across tasks: `_background_mask`, `_subject_bbox`,
`_square_box`, `ALPHA_THRESHOLD`, `crop_to_square`. The `(box, side, capped,
shifted)` tuple returned by `_square_box` is destructured identically in Task 2's
tests and Task 4's implementation.
