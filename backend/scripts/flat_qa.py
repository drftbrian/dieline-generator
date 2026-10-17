"""QA montage of a step 2 flat render (DIELINE_RENDERING_FIX.md, P4).

    cd backend && uv run python scripts/flat_qa.py <project_id> <version_id> [--compare <vid>]
        [--out qa.png] [--data <data dir>]

Panels: (a) source page, (b) deterministic render, (c) model raw (if any), (d) gain heatmap
(final / print, achromatic), (e) final, then 400% crops of the finest text, the largest text
(logo) and a cut edge with a fold, for this version and for ``--compare``. Sizes, crops and the
verify numbers are printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PANEL = 640  # long edge of the overview panels
CROP = 160  # crop size in source pixels (shown at 4x)


def _fit(img: Image.Image, edge: int = PANEL) -> Image.Image:
    im = img.convert("RGB").copy()
    im.thumbnail((edge, edge))
    return im


def _label(img: Image.Image, text: str) -> Image.Image:
    out = Image.new("RGB", (img.width, img.height + 22), (40, 40, 40))
    out.paste(img, (0, 22))
    ImageDraw.Draw(out).text((6, 4), text, fill=(235, 235, 235))
    return out


def _crop4(img: Image.Image, cx: float, cy: float, size: int = CROP) -> Image.Image:
    """``size`` px around (cx, cy) in ``img`` pixels, shown at 400% (nearest: true pixels)."""
    x0 = int(np.clip(cx - size / 2, 0, img.width - size))
    y0 = int(np.clip(cy - size / 2, 0, img.height - size))
    return img.crop((x0, y0, x0 + size, y0 + size)).resize((size * 4, size * 4), Image.NEAREST)


def _sheet(rows: list[list[Image.Image]], bg=(25, 25, 25)) -> Image.Image:
    w = max(sum(i.width for i in r) + 8 * (len(r) + 1) for r in rows)
    h = sum(max(i.height for i in r) for r in rows) + 8 * (len(rows) + 1)
    out = Image.new("RGB", (w, h), bg)
    y = 8
    for r in rows:
        x = 8
        for i in r:
            out.paste(i, (x, y))
            x += i.width + 8
        y += max(i.height for i in r) + 8
    return out


def crop_points(pid: str, L, sil: np.ndarray) -> list[tuple[str, float, float]]:
    """Where to look closely: finest text, largest text (logo), a cut edge next to a fold."""
    from app.services import pipeline

    h, w = sil.shape
    content = pipeline.figma_content(pid) or {}
    texts = [t for t in content.get("texts", []) if t.get("bbox") and not t.get("technical")]
    ox, oy = L.origin

    def centre(t):
        x0, y0, x1, y1 = t["bbox"]
        return ((x0 + x1) / 2 - ox) * L.scale, ((y0 + y1) / 2 - oy) * L.scale

    def on_board(t):
        x, y = centre(t)
        return 0 <= x < w and 0 <= y < h and sil[int(y), int(x)] > 0.5

    texts = [t for t in texts if on_board(t)]
    points = []
    if texts:
        fine = min(texts, key=lambda t: t.get("size") or 99)
        big = max(texts, key=lambda t: t.get("size") or 0)
        points += [("finest text", *centre(fine)), ("largest text", *centre(big))]
    edge = (sil > 0.01) & (sil < 0.99)
    near_fold = ndimage.binary_dilation(L.crease > 0.3, iterations=round(4 * L.px_per_mm))
    ys, xs = np.nonzero(edge & near_fold) if (edge & near_fold).any() else np.nonzero(edge)
    if ys.size:
        points.append(("cut edge + fold", float(xs[ys.size // 2]), float(ys[ys.size // 2])))
    return points


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pid")
    ap.add_argument("vid")
    ap.add_argument("--compare")
    ap.add_argument("--out", default="flat_qa.png")
    ap.add_argument("--data")
    args = ap.parse_args()
    if args.data:
        os.environ["DATA_DIR"] = args.data

    from app.render import shading
    from app.services import pipeline, specs
    from app.spec.models import FLAT_LOOK
    from app.storage import repo

    pid, vid = args.pid, args.vid
    pdir = repo.project_dir(pid)
    vdir = pdir / "versions"
    v = repo.get("versions", vid) or {}
    final = Image.open(vdir / f"{vid}.png").convert("RGB")
    w, h = final.size
    spec = specs.load(repo.project_or_404(pid))
    L = pipeline.get_layers(pid, spec, max(w, h), FLAT_LOOK.lighting.margin)
    parts = shading.render_parts(L, FLAT_LOOK)
    print8 = shading.to8(parts.print_rgb)
    print(f"final {w}x{h}  layers {L.width}x{L.height}  px/mm {L.px_per_mm:.2f}")

    f = np.asarray(final).astype(np.float32) / 255
    b = print8.astype(np.float32) / 255
    ratio = (f @ [0.299, 0.587, 0.114]) / np.maximum(b @ [0.299, 0.587, 0.114], 0.03)
    ratio = np.where(parts.sil >= 0.999, ratio, 1.0)
    heat = np.clip((ratio - 0.85) / 0.25, 0, 1)
    heat_img = Image.fromarray((np.stack([heat, heat, heat], -1) * 255).astype(np.uint8))

    overview = [
        _label(_fit(Image.open(pdir / "page.png")), "(a) source page"),
        _label(_fit(Image.open(vdir / f"{vid}_deterministic.png")), "(b) deterministic")
        if (vdir / f"{vid}_deterministic.png").exists()
        else None,
        _label(_fit(Image.open(vdir / f"{vid}_raw.png")), "(c) model raw")
        if (vdir / f"{vid}_raw.png").exists()
        else None,
        _label(_fit(heat_img), "(d) gain 0.85..1.10"),
        _label(_fit(final), f"(e) final {vid}"),
    ]
    overview = [p for p in overview if p is not None]

    points = crop_points(pid, L, parts.sil)
    print("crops (px, 160x160 shown at 400%):", [(n, round(x), round(y)) for n, x, y in points])

    rows = [overview]
    rows.append([_label(_crop4(final, x, y), f"{n} 400% {vid}") for n, x, y in points])
    if args.compare:
        old = Image.open(vdir / f"{args.compare}.png").convert("RGB")
        k = old.width / w  # the older render may be smaller: same physical spot
        rows.append(
            [
                _label(
                    _crop4(old, x * k, y * k, max(16, round(CROP * k))).resize(
                        (CROP * 4, CROP * 4), Image.NEAREST
                    ),
                    f"{n} 400% {args.compare}",
                )
                for n, x, y in points
            ]
        )
        rows[0].append(_label(_fit(old), f"before {args.compare}"))
    _sheet(rows).save(args.out)
    print("verify", json.dumps(v.get("verify_json"), ensure_ascii=False))
    print("saved", args.out)


if __name__ == "__main__":
    main()
