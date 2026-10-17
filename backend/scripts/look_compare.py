"""Before/after of the flat render's board look (default v2 -> v3), rendered from the same
layers, at 100% and 400% zoom.

    cd backend && uv run python scripts/look_compare.py <project_id> [--a v2] [--b v3]
        [--edge 4096] [--out looks.png] [--data <data dir>]

Rows: overviews, then per spot -- small Korean text, the largest graphic (wordmark), a cut
corner / flap edge, a fold line, a gradient transition, plain board -- as
a 100% | b 100% | a 400% | b 400%. Prints what changed on the print (must be brightness only)
and the board texture at full and quarter size.
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

from flat_qa import _crop4, _fit, _label, _sheet  # noqa: E402

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


def spots(pid: str, L, parts) -> list[tuple[str, float, float]]:
    """Small Korean text, the largest graphic (wordmark), a cut corner, a fold line away from
    print, and a gradient transition (smooth colour change, no print edges)."""
    from app.services import pipeline

    sil = parts.sil
    h, w = sil.shape
    ox, oy = L.origin
    content = pipeline.figma_content(pid) or {}

    def centre(b):
        return ((b[0] + b[2]) / 2 - ox) * L.scale, ((b[1] + b[3]) / 2 - oy) * L.scale

    def on_board(b):
        x, y = centre(b)
        return 0 <= x < w and 0 <= y < h and sil[int(y), int(x)] > 0.5

    out = []
    hangul = [
        t
        for t in content.get("texts", [])
        if t.get("bbox") and on_board(t["bbox"]) and any("가" <= c <= "힣" for c in t["text"])
    ]
    if hangul:
        out.append(("small Korean text", *centre(min(hangul, key=lambda t: t["size"])["bbox"])))
    graphics = [g for g in content.get("graphics", []) if g.get("bbox") and on_board(g["bbox"])]
    if graphics:
        big = max(
            graphics, key=lambda g: (g["bbox"][2] - g["bbox"][0]) * (g["bbox"][3] - g["bbox"][1])
        )
        out.append(("wordmark", *centre(big["bbox"])))
    # Cut corner: the outline point with the sharpest turn (most ground around it).
    edge = (sil > 0.01) & (sil < 0.99)
    ground = ndimage.uniform_filter((sil < 0.5).astype(np.float32), 15)
    score = np.where(edge, ground, 0)
    y, x = np.unravel_index(int(score.argmax()), score.shape)
    out.append(("cut corner", float(x), float(y)))
    lum = parts.print_rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    grad = np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1)) / 8
    quiet = ndimage.uniform_filter((grad > 0.012).astype(np.float32), 41) == 0
    clear = ndimage.uniform_filter((grad > 0.012).astype(np.float32), 341) == 0  # whole crop
    inner = ndimage.binary_erosion(sil > 0.5, iterations=40)
    fold = (L.crease > 0.5) & quiet & inner
    if fold.any():
        ys, xs = np.nonzero(fold)
        out.append(("fold line", float(xs[ys.size // 2]), float(ys[ys.size // 2])))
    smooth = ndimage.gaussian_filter(grad, 8)
    trans = clear & inner & ~ndimage.binary_dilation(L.crease > 0.3, iterations=40)
    if trans.any():
        y, x = np.unravel_index(int(np.where(trans, smooth, 0).argmax()), smooth.shape)
        out.append(("gradient transition", float(x), float(y)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pid")
    ap.add_argument("--a", default="v2")
    ap.add_argument("--b", default="v3")
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
    A, B = args.a, args.b
    parts = {k: shading.render_parts(L, FLAT_LOOKS[k]) for k in (A, B)}
    imgs = {k: Image.fromarray(shading.to8(p.rgb)) for k, p in parts.items()}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for k, im in imgs.items():
        im.save(out.with_name(f"{out.stem}_{k}.png"))

    # The print is the same in both: b / a must be one brightness ratio per pixel.
    sil = parts[B].sil >= 0.999
    a, b = (parts[k].rgb for k in (A, B))
    ratio = b / np.maximum(a, 1e-3)
    inked = sil & (L.artwork[..., 3] > 0.5) & (a.min(-1) > 0.08)
    inked &= (a.max(-1) < 0.95) & (b.max(-1) < 0.95)  # unclipped
    spread = float((ratio.max(-1) - ratio.min(-1))[inked].max()) if inked.any() else 0.0
    outside = ~(parts[B].sil > 1e-3)
    plain = ndimage.binary_erosion(sil, iterations=30) & (
        ndimage.uniform_filter(L.crease + L.artwork[..., 3], 41) < 1e-3
    )
    if plain.sum() < 1000:  # fully printed boards: anywhere away from print edges and folds
        lum = parts[B].print_rgb @ np.array([0.299, 0.587, 0.114], np.float32)
        flat = np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1)) < 0.01
        plain = ndimage.binary_erosion(sil & flat, iterations=30) & (
            ndimage.uniform_filter(L.crease, 41) < 1e-3
        )
    print(f"size {L.width}x{L.height}  px/mm {L.px_per_mm:.2f}")
    print(f"print colour ratio spread {B}/{A} on ink (0 = brightness only): {spread:.4f}")
    print(f"ground max {A}/{B}: {a[outside].max() * 255:.1f} / {b[outside].max() * 255:.1f}")
    for k in (A, B):
        rgb = parts[k].rgb
        print(
            f"{k} texture std full {_texture(rgb, plain, 1):.4f}  quarter {_texture(rgb, plain, 4):.4f}"
        )

    points = spots(pid, L, parts[B])
    ys, xs = np.nonzero(plain)
    if ys.size:
        points.append(("plain board", float(xs[ys.size // 2]), float(ys[ys.size // 2])))
    print("spots:", [(n, round(x), round(y)) for n, x, y in points])

    rows = [
        [_label(_fit(imgs[A], 900), f"{A} (before)"), _label(_fit(imgs[B], 900), f"{B} (after)")]
    ]
    for n, x, y in points:
        rows.append(
            [
                _label(_crop1(imgs[A], x, y), f"{n} · {A} 100% (shown 2x)"),
                _label(_crop1(imgs[B], x, y), f"{n} · {B} 100% (shown 2x)"),
                _label(_crop4(imgs[A], x, y), f"{n} · {A} 400%"),
                _label(_crop4(imgs[B], x, y), f"{n} · {B} 400%"),
            ]
        )
    _sheet(rows).save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
