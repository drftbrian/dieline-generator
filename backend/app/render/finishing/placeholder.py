"""Milestone-3 placeholder finishing preview: simple deterministic effects, one per optical model,
so the finishing UI and data can be exercised before the physical material renderers (M4/M5)
replace these functions. Not a realism claim.

Contract kept by the real renderers too: everything outside the assignments' masks is the
source render, unchanged; masks come only from source geometry.
"""

from __future__ import annotations

import colorsys

import numpy as np
from scipy import ndimage

from app.finishing import catalog

RELIEF_BAND_PX = 6  # emboss/deboss shading reaches just past the shape (its shoulder)

# Layer order (manufacturing-plausible default; refined from research in M4/M5).
LAYER = {
    "uncoated": 0,
    "clearcoat": 1,
    "metal": 2,
    "pigment": 2,
    "holographic": 2,
    "relief": 3,
    "dome": 4,
}


def _rgb(hexv: str | None, fallback=(0.8, 0.8, 0.8)) -> np.ndarray:
    if not hexv:
        return np.array(fallback, np.float32)
    h = hexv.lstrip("#")
    return np.array([int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)


def _bbox_ramp(m: np.ndarray, angle: float = 0.6) -> np.ndarray:
    """0..1 diagonal ramp across the mask's own bounding box (stand-in for reflections)."""
    ys, xs = np.nonzero(m > 0.01)
    if not ys.size:
        return np.zeros_like(m)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    yy, xx = np.mgrid[0 : m.shape[0], 0 : m.shape[1]].astype(np.float32)
    t = (xx - x0) / max(1, x1 - x0) * angle + (yy - y0) / max(1, y1 - y0) * (1 - angle)
    return np.clip(t, 0, 1)


def apply(img: np.ndarray, m: np.ndarray, f: catalog.Finish, params: dict) -> np.ndarray:
    """One placeholder effect inside mask ``m`` (HxW 0..1) on ``img`` (HxWx3 float)."""
    a = m[..., None]
    if f.model in ("metal", "pigment", "holographic"):
        if f.model == "holographic":
            t = _bbox_ramp(m)
            hue = np.stack(
                [np.array(colorsys.hsv_to_rgb(h, 0.35, 0.95)) for h in np.linspace(0, 1, 64)]
            )
            col = hue[(t * 63).astype(int)].astype(np.float32)
        else:
            base = _rgb(f.color)
            if f.model == "metal":
                t = _bbox_ramp(m)[..., None]
                col = base * (0.55 + 0.6 * t)
            else:
                col = np.broadcast_to(base, img.shape)
        return img * (1 - a) + np.clip(col, 0, 1) * a
    if f.model == "relief":
        sign = -1.0 if f.id.endswith("deboss") else 1.0
        h = ndimage.gaussian_filter(m, 2.0) * sign
        gy, gx = np.gradient(h)
        shade = 1 + 6.0 * (-gx - gy) * params.get("depth_mm", 0.3)
        return np.clip(img * shade[..., None], 0, 1)
    if f.model == "clearcoat":
        gloss = params.get("gloss", 0.7) * (1 - params.get("roughness", 0.1))
        streak = np.exp(-(((_bbox_ramp(m) - 0.35) / 0.12) ** 2))[..., None]
        return np.clip(img + a * gloss * 0.25 * streak, 0, 1)
    if f.model == "uncoated":
        return np.clip(img * (1 - 0.06 * a) + 0.04 * a, 0, 1)
    if f.model == "dome":
        d = ndimage.distance_transform_edt(m > 0.5)
        dome = np.clip(d / max(1.0, float(d.max())), 0, 1)[..., None]
        return np.clip(img + a * 0.35 * params.get("highlight", 0.7) * dome**3, 0, 1)
    return img


def render(base: np.ndarray, layers: list[tuple[catalog.Finish, dict, np.ndarray]]) -> np.ndarray:
    """``base`` HxWx3 float (the source render) with the enabled assignments, in layer order."""
    out = base.copy()
    for f, params, m in sorted(layers, key=lambda x: LAYER.get(x[0].model, 9)):
        if not m.any():
            continue
        # Only the finish's own area (plus the relief shoulder band) may change; everything
        # else keeps the source pixels bit for bit.
        region = m > 0
        if f.model == "relief":
            region = ndimage.binary_dilation(region, iterations=RELIEF_BAND_PX)
        new = apply(out, m, f, params).astype(np.float32)
        out = np.where(region[..., None], new, out)
    return out
