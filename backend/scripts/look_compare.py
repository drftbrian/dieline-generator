"""Before/after of the flat render's board look: v1 (first deterministic look) against v2
(physical board), rendered from the same layers, at 100% and 400% zoom.

    cd backend && uv run python scripts/look_compare.py <project_id> [--edge 4096]
        [--out looks.png] [--data <data dir>]

Rows: overviews, then per spot (finest text, largest text, cut edge + fold, plain board):
v1 100% | v2 100% | v1 400% | v2 400%. Prints what changed on the print (must be brightness
only) and the fibre texture at full and quarter size.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flat_qa import _crop4, _fit, _label, _sheet, crop_points  # noqa: E402

CROP_100 = 320  # source px shown 1:1


def _crop1(img: Image.Image, cx: float, cy: float, size: int = CROP_100) -> Image.Image:
    x0 = int(np.clip(cx - size / 2, 0, img.width - size))
    y0 = int(np.clip(cy - size / 2, 0, img.height - size))
    return img.crop((x0, y0, x0 + size, y0 + size)).resize((size * 2, size * 2), Image.NEAREST)


def _texture(rgb: np.ndarray, mask: np.ndarray, k: int) -> float:
    """Fine detail of the board as seen at 1/k size (k x k pixels averaged, like a viewer)."""
    lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    h, w = (lum.shape[0] // k) * k, (lum.shape[1] // k) * k
    lum = lum[:h, :w].reshape(h // k, k, w // k, k).mean(axis=(1, 3))
    m = mask[:h:k, :w:k]
    hp = lum - ndimage.gaussian_filter(lum, 2)
    return float(hp[m].std()) if m.sum() > 100 else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pid")
    ap.add_argument("--edge", type=int, default=4096)
    ap.add_argument("--out", default="looks.png")
    ap.add_argument("--data")
    args = ap.parse_args()
    if args.data:
        os.environ["DATA_DIR"] = args.data

    from app.render import shading
    from app.services import pipeline, specs
    from app.spec.models import FLAT_LOOK_V1, FLAT_LOOKS
    from app.storage import repo

    pid = args.pid
    spec = specs.load(repo.project_or_404(pid))
    L = pipeline.get_layers(pid, spec, args.edge, FLAT_LOOK_V1.lighting.margin)
    parts = {k: shading.render_parts(L, FLAT_LOOKS[k]) for k in ("v1", "v2")}
    imgs = {k: Image.fromarray(shading.to8(p.rgb)) for k, p in parts.items()}
    out = Path(args.out)
    for k, im in imgs.items():
        im.save(out.with_name(f"{out.stem}_{k}.png"))

    # The print is the same in both: v2 / v1 must be one brightness ratio per pixel.
    sil = parts["v2"].sil >= 0.999
    a, b = (parts[k].rgb for k in ("v1", "v2"))
    ratio = b / np.maximum(a, 1e-3)
    inked = sil & (L.artwork[..., 3] > 0.5) & (a.min(-1) > 0.08)
    spread = float((ratio.max(-1) - ratio.min(-1))[inked].max()) if inked.any() else 0.0
    outside = ~(parts["v2"].sil > 1e-3)
    plain = ndimage.binary_erosion(sil, iterations=30) & (
        ndimage.uniform_filter(L.crease + L.artwork[..., 3], 41) < 1e-3
    )
    if plain.sum() < 1000:  # fully printed boards: anywhere away from print edges and folds
        lum = parts["v2"].print_rgb @ np.array([0.299, 0.587, 0.114], np.float32)
        flat = np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1)) < 0.01
        plain = ndimage.binary_erosion(sil & flat, iterations=30) & (
            ndimage.uniform_filter(L.crease, 41) < 1e-3
        )
    print(f"size {L.width}x{L.height}  px/mm {L.px_per_mm:.2f}")
    print(f"print colour ratio spread v2/v1 on ink (0 = brightness only): {spread:.4f}")
    print(f"background max v1/v2: {a[outside].max() * 255:.1f} / {b[outside].max() * 255:.1f}")
    for k in ("v1", "v2"):
        rgb = parts[k].rgb
        print(
            f"{k} texture std full {_texture(rgb, plain, 1):.4f}  quarter {_texture(rgb, plain, 4):.4f}"
        )

    points = crop_points(pid, L, parts["v2"].sil)
    ys, xs = np.nonzero(plain)
    if ys.size:
        points.append(("plain board", float(xs[ys.size // 2]), float(ys[ys.size // 2])))
    print("spots:", [(n, round(x), round(y)) for n, x, y in points])

    rows = [
        [_label(_fit(imgs["v1"], 900), "v1 (before)"), _label(_fit(imgs["v2"], 900), "v2 (after)")]
    ]
    for n, x, y in points:
        rows.append(
            [
                _label(_crop1(imgs["v1"], x, y), f"{n} · v1 100% (shown 2x)"),
                _label(_crop1(imgs["v2"], x, y), f"{n} · v2 100% (shown 2x)"),
                _label(_crop4(imgs["v1"], x, y), f"{n} · v1 400%"),
                _label(_crop4(imgs["v2"], x, y), f"{n} · v2 400%"),
            ]
        )
    _sheet(rows).save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
