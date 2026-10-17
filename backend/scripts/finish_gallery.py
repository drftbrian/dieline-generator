"""Comparison gallery for the finish renderers: every catalogue finish on a test card (logo disc,
bold type-like bars, a thin-line ring) under the top and the raking light, next to the local
reference photos of that finish when there are any. Images are written to OUT only (the photos
are not ours to commit).

    uv run python scripts/finish_gallery.py OUT_DIR
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.finishing import catalog
from app.render.finishing import material
from app.services.finish_realism import reference_photos

H, W = 360, 520
PPM = 8.0  # px per mm: the card is 65 x 45 mm


def card() -> tuple[np.ndarray, np.ndarray]:
    """Print (light warm board with a dark navy band) and the finish mask."""
    img = Image.new("RGB", (W, H), (236, 232, 224))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 230, W, H], fill=(28, 40, 70))
    m = Image.new("L", (W, H), 0)
    dm = ImageDraw.Draw(m)
    dm.ellipse([40, 40, 200, 200], fill=255)
    dm.ellipse([95, 95, 145, 145], fill=0)  # a counter
    for i, x in enumerate(range(240, 480, 46)):
        dm.rectangle([x, 60 + 6 * i, x + 30, 190], fill=255)
    dm.ellipse([250, 250, 470, 340], outline=255, width=4)  # thin line over the dark band
    dm.rectangle([60, 260, 200, 320], fill=255)  # a solid on the dark band
    return np.asarray(img).astype(np.float32) / 255, np.asarray(m).astype(np.float32) / 255


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "finish-gallery")
    out.mkdir(parents=True, exist_ok=True)
    base, m = card()
    scene = material.Scene(px_per_mm=PPM, full=(H, W))
    rows = []
    for f in catalog.FINISHES:
        params = catalog.defaults(f.id)
        tiles = []
        for light in ("top", "raking"):
            r, _ = material.render(base, [(f, params, m)], material.lighting(scene, light))
            tiles.append(Image.fromarray((np.clip(r, 0, 1) * 255).astype(np.uint8)))
        for _, photo in reference_photos(f.id, limit=2):
            ph = photo.copy()
            ph.thumbnail((W, H))
            tile = Image.new("RGB", (W, H), "white")
            tile.paste(ph, ((W - ph.width) // 2, (H - ph.height) // 2))
            tiles.append(tile)
        row = Image.new("RGB", (W * 4 + 30, H + 28), "white")
        ImageDraw.Draw(row).text((6, 6), f"{f.id}  (top | raking | photos)", fill="black")
        for i, t in enumerate(tiles[:4]):
            row.paste(t, (i * (W + 10), 28))
        row.save(out / f"{f.id}.jpg", quality=88)
        rows.append(row)
    sheet = Image.new("RGB", (rows[0].width, sum(r.height for r in rows)), "white")
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    sheet.thumbnail((2400, 20000))
    sheet.save(out / "gallery.jpg", quality=85)
    print(f"{len(rows)} finishes -> {out}")


if __name__ == "__main__":
    main()
