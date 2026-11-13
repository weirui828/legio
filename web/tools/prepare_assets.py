#!/usr/bin/env python3
"""Normalise the generated images in design/prototypes/ui/assets-src/ into web/assets/.

One-off tool, not part of the app. Needs Pillow + numpy (the app itself is
stdlib-only and ships the output of this script committed).

    python3 web/tools/prepare_assets.py

What it does:
  * trims transparent padding around sprites
  * cuts the flat-white backgrounds of desk.png, soldiers.png, icons.png
  * slices soldiers.png (4 columns) and icons.png (4x2) into named files
  * resizes to 2x the CSS display height
  * writes WebP (alpha preserved) and web/assets/manifest.json
  * the two backgrounds are converted to WebP at native size
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

SRC = Path(__file__).resolve().parents[2] / "design" / "prototypes" / "ui" / "assets-src"
OUT = Path(__file__).resolve().parents[1] / "assets"

# name -> target height in device pixels (2x the CSS display height)
HEIGHTS = {
    "tent": 460, "tent-open": 460, "tent-alt-1": 460, "tent-alt-2": 460,
    "tent-warped": 460,
    "board": None,          # keep native width (already wide)
    "note": 400,
    "desk": 460,
    "seal": 72,
    "hearts-sparkles": 300,
    "logo": 128,
    "avatar": 104,
    "mascot-eagle": 112,
    "soldier": 108,
    "icon": 56,
}
ROLES = ["tesserarius", "signifer", "fabri", "probator", "medicus", "mensor",
         "librator", "primus-pilus"]
for _r in ROLES:
    HEIGHTS[f"role-{_r}"] = 300
    HEIGHTS[f"role-{_r}-working"] = 680

# the icon sheet, row by row: [tent, helmet, laurel, chat] / [bell, coin, heart, level]
ICON_NAMES = ["castra", "milites", "legiones", "nuntii",
              "bell", "coin", "heart", "level"]


def alpha_bbox(im: Image.Image) -> tuple[int, int, int, int]:
    """bbox of non-transparent pixels, or the full image."""
    if im.mode not in ("RGBA", "LA"):
        return (0, 0, im.width, im.height)
    return im.split()[-1].getbbox() or (0, 0, im.width, im.height)


def trim(im: Image.Image, pad: int = 4) -> Image.Image:
    x0, y0, x1, y1 = alpha_bbox(im)
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(im.width, x1 + pad), min(im.height, y1 + pad)
    return im.crop((x0, y0, x1, y1))


def scale_to_height(im: Image.Image, height: int | None, width: int | None = None) -> Image.Image:
    if height is None:
        return im
    w = round(im.width * height / im.height)
    return im.resize((w, height), Image.LANCZOS)


def cut_white(im: Image.Image, tol: int = 14, band_px: int = 5,
              softness: float = 36.0) -> Image.Image:
    """Turn a flat-white background into transparency, without a white fringe.

    Flood-fills from the border (tolerance ``tol``), then treats the two or
    three anti-aliased pixels next to that background as a soft edge: their
    alpha comes from how far they are from white, and the white that was mixed
    into them is subtracted back out (un-premultiplied). Without this the desk
    keeps a visible 1-2px white outline on a cream floor.
    """
    import numpy as np
    from PIL import ImageFilter

    rgb = im.convert("RGB")
    arr = np.asarray(rgb).astype(np.float32)
    height, width = arr.shape[:2]
    distance = 255.0 - arr.min(axis=2)

    work = rgb.copy()
    marker = (1, 2, 3)
    for seed in ((0, 0), (width - 1, 0), (0, height - 1),
                 (width - 1, height - 1)):
        if work.getpixel(seed) == marker:
            continue
        ImageDraw.floodfill(work, seed, marker, thresh=tol)
    background = (np.asarray(work) == marker).all(axis=2)

    grown = Image.fromarray((background * 255).astype(np.uint8)).filter(
        ImageFilter.MaxFilter(band_px * 2 + 1))
    band = (np.asarray(grown) > 0) & ~background

    alpha = np.where(background, 0.0, 255.0).astype(np.float32)
    smooth = np.clip(distance / softness, 0, 1) ** 0.85 * 255.0
    alpha[band] = np.minimum(alpha[band], smooth[band])
    alpha[background] = 0.0

    coverage = np.clip(alpha / 255.0, 0, 1)
    out = arr.copy()
    for channel in range(3):
        out[..., channel] = np.where(
            band,
            np.clip((arr[..., channel] - (1 - coverage) * 255.0)
                    / np.maximum(coverage, 0.02), 0, 255),
            arr[..., channel])

    result = Image.fromarray(
        np.dstack([out, alpha[..., None]]).astype(np.uint8), "RGBA")
    result.putalpha(result.getchannel("A").filter(ImageFilter.GaussianBlur(0.5)))
    return result


def head_crop(im: Image.Image) -> Image.Image:
    """A square avatar from a working sprite: head, shoulders, a bit of prop."""
    im = im.convert("RGBA")
    width, height = im.size
    crop = im.crop((int(width * 0.30), int(height * 0.12),
                    int(width * 0.78), int(height * 0.48)))
    box = crop.getchannel("A").getbbox()
    if box:
        crop = crop.crop(box)
    side = max(crop.width, crop.height)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(crop, ((side - crop.width) // 2,
                                  (side - crop.height) // 2))
    return canvas.resize((96, 96), Image.LANCZOS)


def save(im: Image.Image, name: str, quality: int = 86) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.webp"
    im.save(path, "WEBP", quality=quality, method=6)
    return {"file": path.name, "w": im.width, "h": im.height}


def process_sprite(name: str, im: Image.Image, height: int | None = None) -> dict:
    im = trim(im)
    im = scale_to_height(im, height if height is not None else HEIGHTS.get(name))
    return save(im, name)


def split_bands(arr, axis: int, min_band: int = 8) -> list[tuple[int, int]]:
    """Find runs of non-blank pixels along an axis (numpy boolean array)."""
    import numpy as np
    if axis == 0:
        filled = arr.any(axis=1)
    else:
        filled = arr.any(axis=0)
    bands, start = [], None
    for i, on in enumerate(filled):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if i - start >= min_band:
                bands.append((start, i))
            start = None
    if start is not None and len(filled) - start >= min_band:
        bands.append((start, len(filled)))
    return bands


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}

    # backgrounds
    for name in ("camp-ground", "tent-interior"):
        im = Image.open(SRC / f"{name}.jpg").convert("RGB")
        path = OUT / f"{name}.webp"
        im.save(path, "WEBP", quality=82, method=6)
        manifest[name] = {"file": path.name, "w": im.width, "h": im.height}

    # plain alpha sprites
    for name in ("tent", "tent-open", "tent-alt-1", "tent-alt-2", "tent-warped",
                 "board", "note", "desk", "seal", "hearts-sparkles", "logo",
                 "avatar", "mascot-eagle"):
        src = SRC / f"{name}.png"
        im = Image.open(src).convert("RGBA")
        if name in ("desk",):
            im = cut_white(im)
        manifest[name] = process_sprite(name, im)

    # the cast, standing and working
    for role in ROLES:
        for suffix in ("", "-working"):
            name = f"role-{role}{suffix}"
            im = Image.open(SRC / f"{name}.png").convert("RGBA")
            manifest[name] = process_sprite(name, im)
            if suffix == "-working":
                # a 48px avatar for the notes on the board
                manifest[f"head-{role}"] = save(head_crop(im),
                                                f"head-{role}", quality=88)

    # soldiers sheet -> four cutouts
    import numpy as np
    soldiers = cut_white(Image.open(SRC / "soldiers.png").convert("RGBA"))
    arr = np.asarray(soldiers)[:, :, 3] > 8
    cols = split_bands(arr, axis=1, min_band=20)
    for i, (x0, x1) in enumerate(cols[:4], 1):
        cell = soldiers.crop((x0, 0, x1, soldiers.height))
        cell = trim(cell)
        cell = scale_to_height(cell, HEIGHTS["soldier"])
        manifest[f"soldier-{i}"] = save(cell, f"soldier-{i}")

    # icons sheet -> eight cutouts, row-major
    icons = cut_white(Image.open(SRC / "icons.png").convert("RGBA"))
    arr = np.asarray(icons)[:, :, 3] > 8
    rows = split_bands(arr, axis=0, min_band=20)
    index = 0
    for y0, y1 in rows[:2]:
        band = arr[y0:y1, :]
        cols = split_bands(band, axis=1, min_band=20)
        for x0, x1 in cols[:4]:
            cell = icons.crop((x0, y0, x1, y1))
            cell = trim(cell)
            cell = scale_to_height(cell, HEIGHTS["icon"])
            icon_name = ICON_NAMES[index]
            manifest[f"icon-{icon_name}"] = save(cell, f"icon-{icon_name}")
            index += 1
    manifest["_meta"] = {"source": "design/prototypes/ui/assets-src", "scale": "2x css"}

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{len(manifest) - 1} assets -> {OUT}")


if __name__ == "__main__":
    main()
