"""Measure finish appearance from local reference photos and write the numbers the finishing
renderers use (``app/render/finishing/calibration.json``).

The photos are the user's study set (``backend/image learning/``, never committed); only the
measured numbers are saved. Each entry names a photo and a hand-picked crop (fractions of the
image) around the finish, plus how to tell finish pixels from the surrounding print.

    uv run python scripts/finish_calibrate.py ["backend/image learning"]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "render" / "finishing" / "calibration.json"

# (file, crop x0, y0, x1, y1 as fractions, selector)
GOLD = [
    ("후가공_금박.png", (0.30, 0.28, 0.64, 0.78), "chroma"),
    ("후가공_금박2.jpeg", (0.10, 0.08, 0.68, 0.80), "chroma"),
    ("후가공_금박.jpg", (0.55, 0.30, 0.98, 1.00), "chroma"),
]
SILVER = [
    ("후가공_은박.jpg", (0.42, 0.28, 0.80, 0.55), "contrast"),
    ("후가공_은박2.jpeg", (0.50, 0.18, 0.85, 0.45), "contrast"),
]
RELIEF = [  # blind emboss / deboss on white board
    ("후가공_엠보싱3.jpg", (0.30, 0.15, 0.75, 0.85)),
    ("후가공_디보싱2.jpeg", (0.20, 0.10, 0.85, 0.80)),
    ("후가공_엠보싱.jpg", (0.10, 0.15, 0.90, 0.85)),
]
SPOT_UV = [("후가공_부분(Uv)코팅3.jpg", (0.25, 0.20, 0.85, 0.95))]  # gloss on matte black


def _load(folder: Path, name: str, box) -> np.ndarray:
    im = Image.open(folder / name).convert("RGB")
    w, h = im.size
    x0, y0, x1, y1 = box
    crop = im.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
    return np.asarray(crop).astype(np.float32) / 255


def _lum(rgb: np.ndarray) -> np.ndarray:
    return rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)


def _chroma(rgb: np.ndarray) -> np.ndarray:
    return rgb.max(-1) - rgb.min(-1)


def metal(folder: Path, entries) -> dict:
    """Foil pixels' tone range (shadow / body / highlight), body colour and chroma; each photo
    counts once (a large, brightly lit stripe must not outweigh a small logo)."""
    rows = []
    for name, box, sel in entries:
        c = _load(folder, name, box)
        L, C = _lum(c), _chroma(c)
        if sel == "chroma":  # gold: warm, saturated pixels (hue between orange and yellow)
            r, g, b = c[..., 0], c[..., 1], c[..., 2]
            m = (C > 0.12) & (r >= g) & (g > b) & ((g - b) > 0.5 * (r - b))
        else:  # silver: neutral pixels far from the crop's median (the board is mid-tone)
            med = np.median(L)
            m = (C < 0.08) & (np.abs(L - med) > 0.08)
        L, col, C = L[m], c[m], C[m]
        body = (L > np.percentile(L, 30)) & (L < np.percentile(L, 70))
        rows.append(
            [*np.percentile(L, [5, 50, 98]), *col[body].mean(0), float(np.median(C)), L.size]
        )
    a = np.array(rows)
    mean = a[:, :7].mean(0)
    return {
        "shadow": round(float(mean[0]), 3),
        "body": round(float(mean[1]), 3),
        "highlight": round(float(mean[2]), 3),
        "body_rgb": [round(float(v), 3) for v in mean[3:6]],
        "chroma": round(float(mean[6]), 3),
        "photos": len(rows),
        "samples": int(a[:, 7].sum()),
    }


def relief(folder: Path, entries) -> dict:
    """Highlight / shadow of the relief's flanks relative to the plain board around it."""
    hi, lo = [], []
    for name, box in entries:
        L = _lum(_load(folder, name, box))
        # The board's own slow shading (light falloff) is not relief: remove a wide blur.
        from scipy import ndimage

        base = ndimage.gaussian_filter(L, max(L.shape) / 12)
        d = L - base
        hi.append(float(np.percentile(d, 99.5)))
        lo.append(float(np.percentile(d, 0.5)))
    return {"highlight": round(float(np.mean(hi)), 3), "shadow": round(float(np.mean(lo)), 3)}


def gloss_on_matte(folder: Path, entries) -> dict:
    """Spot UV on a dark matte print: how bright the gloss streaks get over the matte base."""
    out = []
    for name, box in entries:
        c = _load(folder, name, box)
        L, C = _lum(c), _chroma(c)
        dark = L[(C < 0.08) & (L < 0.35)]
        out.append((float(np.percentile(dark, 50)), float(np.percentile(L[C < 0.08], 99))))
    base, peak = np.mean(out, 0)
    return {"matte_base": round(float(base), 3), "gloss_peak": round(float(peak), 3)}


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "image learning"
    data = {
        "source": "local reference photos (not in the repository); numbers only",
        "gold": metal(folder, GOLD),
        "silver": metal(folder, SILVER),
        "relief": relief(folder, RELIEF),
        "spot_uv": gloss_on_matte(folder, SPOT_UV),
    }
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
