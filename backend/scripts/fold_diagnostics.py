"""v4 fold diagnostics: v3 and v4 renders, the fold mask, height, normal, shadow and highlight
maps, a v4-v3 difference heatmap, and 400% crops (horizontal fold, vertical fold, flap hinge,
fold intersection/endpoint, text near a fold) for v3 and the low / medium / high presets.

    cd backend && uv run python scripts/fold_diagnostics.py <project_id> [--edge 4096]
        [--out-dir folds_qa] [--data <data dir>]
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


def _gray(v: np.ndarray, lo: float, hi: float) -> Image.Image:
    g = (np.clip((v - lo) / max(hi - lo, 1e-9), 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(np.dstack([g] * 3))


def fold_spots(L, sil: np.ndarray, print_rgb: np.ndarray) -> list[tuple[str, float, float]]:
    """A horizontal fold, a vertical fold, a flap hinge, an intersection or endpoint, and text
    close to a fold (all on the board, away from the cut)."""
    px = L.px_per_mm
    line = L.crease > 0.5
    inner = ndimage.binary_erosion(sil >= 0.999, iterations=round(4 * px))
    gy, gx = np.gradient(ndimage.gaussian_filter(line.astype(np.float32), 2))
    horiz = line & (np.abs(gy) > 2 * np.abs(gx)) & inner
    vert = line & (np.abs(gx) > 2 * np.abs(gy)) & inner
    # Intersection: where a horizontal and a vertical fold meet; else a fold end.
    near = round(1.5 * px)
    junction = (
        ndimage.binary_dilation(line & (np.abs(gy) > 2 * np.abs(gx)), iterations=near)
        & ndimage.binary_dilation(line & (np.abs(gx) > 2 * np.abs(gy)), iterations=near)
        & line
        & (sil >= 0.999)
    )
    if not junction.any():
        ends = ndimage.uniform_filter(line.astype(np.float32), round(2 * px))
        junction = line & (ends < 0.6 * float(np.median(ends[line]))) & (sil >= 0.999)
    lum = print_rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    text = np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1)) / 8 > 0.05
    to_text = ndimage.distance_transform_edt(~text)
    cand = line & inner & (to_text > 1.0 * px)  # the closest fold point that is not on text
    near_text = np.zeros_like(line)
    if cand.any():
        d = np.where(cand, to_text, np.inf)
        near_text.flat[int(d.argmin())] = True
    from app.render import folds

    hinge = (folds._hinges(L, line, px) > 0.8) & line & inner
    out = []
    for name, m in (
        ("horizontal fold", horiz),
        ("vertical fold", vert),
        ("flap hinge", hinge),
        ("intersection / endpoint", junction),
        ("text near fold", near_text),
    ):
        ys, xs = np.nonzero(m)
        if ys.size:
            i = ys.size // 2
            out.append((name, float(xs[i]), float(ys[i])))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pid")
    ap.add_argument("--edge", type=int, default=4096)
    ap.add_argument("--out-dir", default="folds_qa")
    ap.add_argument("--data")
    args = ap.parse_args()
    if args.data:
        os.environ["DATA_DIR"] = args.data

    from app.render import folds, shading
    from app.services import pipeline, specs
    from app.spec.models import FLAT_LOOKS, flat_look
    from app.storage import repo

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    spec = specs.load(repo.project_or_404(args.pid))
    L = pipeline.get_layers(args.pid, spec, args.edge, FLAT_LOOKS["v3"].lighting.margin)
    v3 = shading.render_parts(L, FLAT_LOOKS["v3"])
    renders = {"v3": Image.fromarray(shading.to8(v3.rgb))}
    for preset in ("low", "medium", "high"):
        p = shading.render_parts(L, flat_look("v4", preset))
        renders[f"v4 {preset}"] = Image.fromarray(shading.to8(p.rgb))
    renders["v3"].save(out / "1_v3.png")
    renders["v4 medium"].save(out / "2_v4_medium.png")

    look = flat_look("v4", "medium")
    fm = folds.fold_maps(L, folds.FOLD_PRESETS["medium"], look.lighting.light_angle)
    Image.fromarray((fm.mask * 255).astype(np.uint8)).save(out / "3_fold_mask.png")
    depth = folds.FOLD_PRESETS["medium"].depth_mm
    _gray(fm.height, -depth, depth).save(out / "4_fold_height.png")
    Image.fromarray(((fm.normals * 0.5 + 0.5) * 255).astype(np.uint8)).save(
        out / "5_fold_normals.png"
    )
    _gray(fm.shadow, 0, 0.12).save(out / "6_fold_shadow.png")
    _gray(fm.highlight, 0, 0.07).save(out / "7_fold_highlight.png")
    a = np.asarray(renders["v3"]).astype(np.float32) @ [0.299, 0.587, 0.114]
    b = np.asarray(renders["v4 medium"]).astype(np.float32) @ [0.299, 0.587, 0.114]
    ratio = (b + 1) / (a + 1)
    heat = np.zeros(ratio.shape + (3,), np.float32)
    heat[..., 0] = np.clip((ratio - 1) / 0.08, 0, 1)  # red: v4 lighter
    heat[..., 2] = np.clip((1 - ratio) / 0.08, 0, 1)  # blue: v4 darker
    Image.fromarray((heat * 255).astype(np.uint8)).save(out / "8_difference_v4_vs_v3.png")
    board = v3.sil >= 0.999
    away = ~ndimage.binary_dilation(fm.mask, iterations=round(4 * L.px_per_mm))
    print(f"size {L.width}x{L.height} px/mm {L.px_per_mm:.2f}")
    print(
        f"v4/v3 on board: {ratio[board].min():.3f}..{ratio[board].max():.3f}; "
        f"away from folds (>4 mm): {np.abs(ratio[board & away] - 1).max():.4f}"
    )

    spots = fold_spots(L, v3.sil, v3.print_rgb)
    print("spots:", [(n, round(x), round(y)) for n, x, y in spots])
    rows = [[_label(_fit(renders[k], 700), k) for k in renders]]
    for n, x, y in spots:
        rows.append([_label(_crop4(renders[k], x, y), f"{n} · {k} 400%") for k in renders])
    _sheet(rows).save(out / "9_crops_400.png")
    print("saved", out)


if __name__ == "__main__":
    main()
