#!/usr/bin/env python3
"""
MCP Image Tools Server

An MCP server that provides image processing tools:
- fetch_toy_image: Download toy-related images from the web
- resize_image: Resize images to specified dimensions
- remove_background_as_png: Remove image background keeping main object
"""

import logging
import os
import random
import time
from collections import Counter, deque
from typing import Optional
import requests
from PIL import Image, ImageChops, ImageFilter

from mcp.server.fastmcp import FastMCP

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("image-tools-server")

# Create server instance
mcp = FastMCP("image-tools-server")


def _search_images(search_term: str, max_results: int):
    """Search for images across multiple backends with retry + exponential backoff.

    The legacy `duckduckgo-search` library hit a single endpoint and got 403
    rate-limited constantly. `ddgs` is its maintained successor and rotates
    across several search backends; we additionally retry with backoff and fall
    back through backends so a throttled backend doesn't fail the whole request.
    """
    # Prefer the maintained `ddgs` package; fall back to the old name if present.
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS  # legacy fallback

    backends = ["duckduckgo", "bing", "brave", "google", "yahoo", "auto"]
    last_error = None

    for attempt in range(4):
        for backend in backends:
            try:
                with DDGS() as ddgs:
                    try:
                        # ddgs (new) API: first arg is `query`, supports `backend`.
                        gen = ddgs.images(
                            query=search_term,
                            region="wt-wt",
                            safesearch="moderate",
                            max_results=max_results,
                            backend=backend,
                        )
                    except TypeError:
                        # Legacy duckduckgo-search API: `keywords`, no `backend`.
                        gen = ddgs.images(
                            keywords=search_term,
                            region="wt-wt",
                            safesearch="moderate",
                            max_results=max_results,
                        )
                    results = list(gen)
                    if results:
                        return results
            except Exception as e:  # rate limit, backend error, etc.
                last_error = e
                logger.warning(
                    "Image search failed (attempt %d, backend %s): %s",
                    attempt + 1, backend, e,
                )
                continue
        # Exponential backoff between full rounds: 1s, 2s, 4s.
        if attempt < 3:
            time.sleep(2 ** attempt)

    if last_error is not None:
        raise last_error
    return []

@mcp.tool()
async def fetch_toy_image(keyword: str, count: int = 3, output_dir: str = "./images", max_search_results: int = 20) -> str:
    """Download toy-related images from the web using DuckDuckGo image search."""
    
    # Ensure keyword includes "toy" for better results
    search_term = f"toy {keyword}" if not keyword.lower().startswith("toy") else keyword
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        results = []
        downloaded_count = 0

        # Multi-backend search with retry + exponential backoff (see _search_images).
        all_results = _search_images(search_term, max_search_results)

        # Randomly shuffle and select from available results
        if all_results:
            random.shuffle(all_results)
            selected_results = all_results[:min(count * 3, len(all_results))]  # Select up to 3x count for backup
        else:
            selected_results = []

        for i, result in enumerate(selected_results):
            if downloaded_count >= count:
                break

            try:
                image_url = result.get("image")
                if not image_url:
                    continue

                # Download image
                response = requests.get(image_url, timeout=10, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                response.raise_for_status()

                # Determine file extension
                content_type = response.headers.get('content-type', '')
                if 'jpeg' in content_type or 'jpg' in content_type:
                    ext = 'jpg'
                elif 'png' in content_type:
                    ext = 'png'
                elif 'gif' in content_type:
                    ext = 'gif'
                else:
                    ext = 'jpg'  # Default

                # Save image
                filename = f"{keyword.replace(' ', '_')}_{downloaded_count + 1}.{ext}"
                filepath = os.path.join(output_dir, filename)

                with open(filepath, 'wb') as f:
                    f.write(response.content)

                results.append(f"Downloaded: {filepath}")
                downloaded_count += 1

            except Exception as e:
                logger.warning(f"Failed to download image {i}: {str(e)}")
                continue

        if downloaded_count == 0:
            return "No images were successfully downloaded."

        result_text = f"Successfully downloaded {downloaded_count} toy images for '{keyword}':\n" + "\n".join(results)
        return result_text

    except ImportError:
        return "Error: image search library not available. Please install it with: pip install ddgs"
    except Exception as e:
        return f"Error fetching images: {str(e)}"

@mcp.tool()
async def resize_image(image_path: str, width: int, height: int, output_path: Optional[str] = None, maintain_aspect: bool = False) -> str:
    """Resize an image to specified dimensions."""
    
    if not os.path.exists(image_path):
        return f"Error: Image file not found: {image_path}"
    
    try:
        # Open image
        with Image.open(image_path) as img:
            original_size = img.size
            
            if maintain_aspect:
                # Calculate aspect ratio preserving resize
                img.thumbnail((width, height), Image.Resampling.LANCZOS)
                resized_img = img
            else:
                # Direct resize
                resized_img = img.resize((width, height), Image.Resampling.LANCZOS)
            
            # Determine output path
            if not output_path:
                name, ext = os.path.splitext(image_path)
                output_path = f"{name}_resized{ext}"
            
            # Save resized image
            resized_img.save(output_path, quality=95)
            
            result_text = f"Image resized successfully!\n"
            result_text += f"Original size: {original_size[0]}x{original_size[1]}\n"
            result_text += f"New size: {resized_img.size[0]}x{resized_img.size[1]}\n"
            result_text += f"Saved to: {output_path}"
            
            return result_text
            
    except Exception as e:
        return f"Error resizing image: {str(e)}"

def _parse_color(value: str):
    """Parse "#rrggbb", "rrggbb" or "r,g,b" into an (r, g, b) tuple."""
    text = value.strip().lstrip("#")
    if "," in text:
        parts = [int(p) for p in text.split(",")]
        if len(parts) != 3:
            raise ValueError(f"Expected 3 comma-separated channels, got: {value}")
    elif len(text) == 6:
        parts = [int(text[i:i + 2], 16) for i in (0, 2, 4)]
    else:
        raise ValueError(f"Unrecognised colour: {value}")
    for p in parts:
        if not 0 <= p <= 255:
            raise ValueError(f"Channel out of range in: {value}")
    return tuple(parts)


def _estimate_bg_color(img: Image.Image):
    """Guess the background colour from the most common shade along the border."""
    width, height = img.size
    step = max(1, max(width, height) // 200)

    border = []
    for x in range(0, width, step):
        border.append(img.getpixel((x, 0)))
        border.append(img.getpixel((x, height - 1)))
    for y in range(0, height, step):
        border.append(img.getpixel((0, y)))
        border.append(img.getpixel((width - 1, y)))

    # Bucket into 16-level bins so near-identical shades count as one colour,
    # then average the actual pixels of the winning bin.
    def bucket(px):
        return (px[0] // 16, px[1] // 16, px[2] // 16)

    winner = Counter(bucket(px) for px in border).most_common(1)[0][0]
    members = [px for px in border if bucket(px) == winner]
    return tuple(sum(px[i] for px in members) // len(members) for i in range(3))


def _border_connected(mask: Image.Image, max_side: int = 400) -> Image.Image:
    """Keep only the parts of `mask` that connect to the image border.

    Runs the flood fill on a downscaled copy (Python-level BFS is the one part
    that cannot be pushed into PIL's C layer), then scales the result back up
    and dilates it slightly so the full-resolution mask isn't clipped.
    Background-coloured areas fully enclosed by the subject stay opaque.
    """
    width, height = mask.size
    scale = min(1.0, max_side / max(width, height))
    sw, sh = max(1, int(width * scale)), max(1, int(height * scale))

    small = bytearray(mask.resize((sw, sh), Image.NEAREST).tobytes())
    reached = bytearray(sw * sh)
    queue = deque()

    def seed(i):
        if small[i] and not reached[i]:
            reached[i] = 255
            queue.append(i)

    for x in range(sw):
        seed(x)
        seed((sh - 1) * sw + x)
    for y in range(sh):
        seed(y * sw)
        seed(y * sw + sw - 1)

    while queue:
        i = queue.popleft()
        x = i % sw
        if x > 0:
            seed(i - 1)
        if x < sw - 1:
            seed(i + 1)
        if i >= sw:
            seed(i - sw)
        if i < (sh - 1) * sw:
            seed(i + sw)

    grown = (
        Image.frombytes("L", (sw, sh), bytes(reached))
        .resize((width, height), Image.NEAREST)
        .filter(ImageFilter.MaxFilter(3))
    )
    return ImageChops.multiply(mask, grown)


@mcp.tool()
async def remove_background_as_png(
    image_path: str,
    output_path: Optional[str] = None,
    tolerance: int = 30,
    bg_color: Optional[str] = None,
    keep_enclosed: bool = True,
) -> str:
    """Remove the background of an image and save it as a PNG with transparency.

    Args:
        image_path: Image to process.
        output_path: Destination PNG. Defaults to "<name>_no_bg.png".
        tolerance: Per-channel distance from the background colour that still
            counts as background (0-255). Raise it for noisy/JPEG backgrounds.
        bg_color: Background colour as "#rrggbb" or "r,g,b". Auto-detected from
            the image border when omitted.
        keep_enclosed: Keep background-coloured areas that are fully enclosed by
            the subject (e.g. white eyes on a white backdrop) opaque.
    """

    if not os.path.exists(image_path):
        return f"Error: Image file not found: {image_path}"

    if not 0 <= tolerance <= 255:
        return f"Error: tolerance must be between 0 and 255, got {tolerance}"

    started = time.time()

    try:
        with Image.open(image_path) as opened:
            img = opened.convert("RGBA")

        rgb = img.convert("RGB")

        if bg_color:
            try:
                target = _parse_color(bg_color)
            except ValueError as e:
                return f"Error: {e}"
        else:
            target = _estimate_bg_color(rgb)

        # Per-channel lookup tables run inside PIL's C layer, so this stays fast
        # even on multi-megapixel images (the old per-pixel Python loop took
        # ~35s on a 3815x3815 photo).
        channel_masks = [
            channel.point(lambda v, t=t: 255 if abs(v - t) <= tolerance else 0)
            for channel, t in zip(rgb.split(), target)
        ]
        bg_mask = ImageChops.multiply(
            ImageChops.multiply(channel_masks[0], channel_masks[1]), channel_masks[2]
        )

        if keep_enclosed:
            bg_mask = _border_connected(bg_mask)

        # Soften the cut by a sub-pixel amount so edges are not stair-stepped,
        # and keep any transparency the source image already had.
        alpha = ImageChops.invert(bg_mask).filter(ImageFilter.GaussianBlur(0.6))
        img.putalpha(ImageChops.multiply(img.getchannel("A"), alpha))

        if not output_path:
            name, _ = os.path.splitext(image_path)
            output_path = f"{name}_no_bg.png"

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        img.save(output_path, "PNG")

        histogram = img.getchannel("A").histogram()
        total = img.width * img.height
        transparent_pct = 100.0 * histogram[0] / total

        result = "Background removed successfully!\n"
        result += f"Background colour: rgb{target}"
        result += " (auto-detected)\n" if not bg_color else " (specified)\n"
        result += f"Tolerance: {tolerance}\n"
        result += f"Made transparent: {transparent_pct:.1f}% of pixels\n"
        result += f"Elapsed: {time.time() - started:.2f}s\n"
        result += f"Saved to: {output_path}"
        if transparent_pct < 1.0:
            result += (
                "\nHint: almost nothing was removed - try a higher tolerance "
                "or pass bg_color explicitly."
            )
        elif transparent_pct > 95.0:
            result += (
                "\nHint: nearly everything was removed - try a lower tolerance."
            )
        return result

    except Exception as e:
        return f"Error removing background: {str(e)}"


if __name__ == "__main__":
    mcp.run()
