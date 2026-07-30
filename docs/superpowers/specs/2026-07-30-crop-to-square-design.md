# crop_to_square — Content-Aware Square Crop

**Date:** 2026-07-30
**Status:** Approved, ready for implementation planning

## Goal

Add one MCP tool to `server.py` that crops an image to a square centred on its
subject. Subject detection is content-aware: use the alpha channel when the image
carries real transparency, otherwise fall back to background-colour detection via
the existing `_estimate_bg_color`.

Only this one mode ships. No `center` / `pad` mode selector, no scaling parameter
(chain the existing `resize_image` for that).

## Tool Signature

```python
@mcp.tool()
async def crop_to_square(
    image_path: str,
    output_path: Optional[str] = None,
    margin: float = 0.05,
    tolerance: int = 30,
    bg_color: Optional[str] = None,
) -> str
```

| Parameter | Meaning |
|---|---|
| `image_path` | Image to crop. |
| `output_path` | Destination PNG. Defaults to `<name>_square.png`. |
| `margin` | Extra breathing room around the subject, as a fraction of its longest side. `0.05` = 5%. |
| `tolerance` | Per-channel distance from the background colour that still counts as background (0–255). Only used on the opaque fallback path. |
| `bg_color` | Background colour as `#rrggbb` or `r,g,b`. Auto-detected from the border when omitted. Only used on the opaque fallback path. |

`tolerance` and `bg_color` keep exactly the same semantics as in
`remove_background_as_png`, so the two tools read consistently.

Output is always PNG with alpha preserved, so chaining
`remove_background_as_png` → `crop_to_square` does not silently drop transparency.

## Subject Detection

Two paths, selected automatically from the source image:

**Alpha path** — taken when `img.getchannel("A").getextrema()[0] < 255`, i.e. the
image has at least one non-opaque pixel.

```python
subject = alpha.point(lambda v: 255 if v > ALPHA_THRESHOLD else 0)
bbox = subject.getbbox()
```

`ALPHA_THRESHOLD = 8` is a module-level constant, not a parameter. Its job is to
discard the near-transparent fringe left by the Gaussian feather in
`remove_background_as_png`; there is no use case for tuning it from the outside.

**Opaque fallback path** — taken when every pixel is fully opaque.

```python
target = _parse_color(bg_color) if bg_color else _estimate_bg_color(rgb)
bbox = ImageChops.invert(_background_mask(rgb, target, tolerance)).getbbox()
```

The fallback deliberately does **not** call `_border_connected`. Background-coloured
regions fully enclosed by the subject are by definition inside the subject's outer
extent, so they cannot change the bounding box. Running the flood fill would cost
time and buy nothing. (This differs from `remove_background_as_png`, where enclosed
regions matter because every pixel's alpha is written individually.)

If `getbbox()` returns `None` — the whole image reads as background, or is fully
transparent — return an error string suggesting a different `tolerance` or an
explicit `bg_color`.

## Refactor: `_background_mask`

Extract the channel-LUT mask construction currently inlined in
`remove_background_as_png` into a shared helper:

```python
def _background_mask(rgb: Image.Image, target, tolerance: int) -> Image.Image:
    """Build a mask of pixels within `tolerance` of `target` on every channel."""
    channel_masks = [
        channel.point(lambda v, t=t: 255 if abs(v - t) <= tolerance else 0)
        for channel, t in zip(rgb.split(), target)
    ]
    return ImageChops.multiply(
        ImageChops.multiply(channel_masks[0], channel_masks[1]), channel_masks[2]
    )
```

`remove_background_as_png` then calls this helper instead of building the mask
inline. Pure code movement — identical operations, identical order, no behaviour
change. This keeps the per-channel LUT approach in exactly one place; the
performance note in `CLAUDE.md` (never reintroduce a `getpixel`/`putpixel` loop)
continues to apply to it.

## Crop Geometry

```
bbox_w, bbox_h = bbox width and height
cx, cy         = bbox centre
side = round(max(bbox_w, bbox_h) * (1 + margin))
side = max(1, min(side, min(W, H)))            # shrink to the short edge if needed
left = clamp(round(cx - side / 2), 0, W - side)
top  = clamp(round(cy - side / 2), 0, H - side)
img.crop((left, top, left + side, top + side))
```

Two consequences, both intentional:

- **`side` is capped at the image's short edge.** A subject spanning more than the
  short edge cannot be enclosed in a square drawn from real pixels, so the crop
  tightens instead of padding.
- **The window is clamped inside the image.** For a subject near an edge, the
  square slides inward, so the subject is no longer exactly centred. This is
  preferred over padding transparent or background-coloured pixels: the output is
  always `side x side` and 100% real source pixels.

## Error Handling

Follows the existing convention in `server.py` — return a descriptive string, do
not raise. `crop_to_square` returns an error for:

- `image_path` does not exist
- `tolerance` outside 0–255
- `margin` negative
- `bg_color` unparseable (surface the `ValueError` from `_parse_color`)
- `getbbox()` returned `None`

## Success Report

On success, return a multi-line summary covering:

- Detection method: `alpha channel`, `background colour (auto-detected)`, or
  `background colour (specified)`
- Original size and detected subject bbox
- Output side length and crop origin
- **Explicitly note when `side` was capped at the short edge, and when the window
  was clamped away from the subject centre.** These are the two cases where a user
  would otherwise think the tool failed to centre the subject.
- Elapsed time and output path

## Verification

This repository has no test suite (no `tests/`, no pytest dependency). Per
`CLAUDE.md`, verification uses the documented manual path. A Docker build is a
build, not a passing test, and will not be reported as one.

1. `docker build -t mcp-toy-image-tools-server .`
2. The MCP `initialize` handshake smoke test from `CLAUDE.md`
3. Exercise the tool against real files in `./images/`, covering three cases:
   - an already-background-removed PNG → alpha path
   - a solid-background JPEG → opaque fallback path
   - an image whose subject fills the frame → triggers the short-edge cap
4. Confirm `remove_background_as_png` still behaves identically after the
   `_background_mask` extraction.

## Documentation

Update `CLAUDE.md`: add `crop_to_square` to the MCP tools list, and note in the
Image Processing Pipeline section that the shared `_background_mask` helper backs
both background-colour-based tools.
