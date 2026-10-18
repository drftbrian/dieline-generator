"""Visible-face registration: where a source panel lies in a generated photograph.

A face is a plane, so its image is a homography of the flat panel. Starting from a rough quad
(the user's corners, a detection proposal or the structural pose), the four corners are refined
coarse-to-fine to maximise the normalised cross-correlation of *gradient magnitudes* between
the source panel and the photo resampled onto the panel. Gradients make the match insensitive
to the photo's light, colour cast and shadows; wrong or extra lettering in the photo lowers the
score but rarely moves the optimum, because most of the panel (edges of the gradient, the
other text, the logo) still agrees.

``H`` maps normalised panel coordinates (u, v in [0, 1], v down) to photo pixels, so one
registration serves any raster of the panel.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage, optimize

from app.render.carton3d import _homography

LUMA = np.array([0.299, 0.587, 0.114], np.float32)
UNIT = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)  # TL TR BR BL
LEVELS = (160, 320, 640)  # panel long edges of the coarse-to-fine pyramid
BORDER = 0.03  # panel fraction ignored at every edge (fold rounding, edge highlights)
MIN_NCC = 0.45  # below this the face is not registered (review required)
STRUCTURE_PCT = 85  # source pixels above this gradient percentile are its structure
MAX_SHIFT = 0.08  # a corner moving more than this fraction of the face diagonal: rejected


@dataclass
class Registration:
    face_id: str
    quad: np.ndarray  # 4x2 photo px: panel TL, TR, BR, BL
    H: np.ndarray  # normalised panel (u, v) -> photo px
    ncc_initial: float
    ncc: float
    corner_shift_px: float  # largest corner move from the starting quad
    ok: bool
    reason: str | None = None

    def report(self) -> dict:
        return {
            "face_id": self.face_id,
            "quad_px": [[round(float(x), 2), round(float(y), 2)] for x, y in self.quad],
            "ncc_initial": round(self.ncc_initial, 4),
            "ncc": round(self.ncc, 4),
            "corner_shift_px": round(self.corner_shift_px, 2),
            "confidence": round(max(0.0, min(1.0, (self.ncc - MIN_NCC) / (1 - MIN_NCC))), 3),
            "ok": self.ok,
            "reason": self.reason,
        }


def luminance(rgb: np.ndarray) -> np.ndarray:
    return (rgb[..., :3] @ LUMA).astype(np.float32)


def homography(quad: np.ndarray) -> np.ndarray:
    H = _homography(UNIT, np.asarray(quad, float))
    return H / H[2, 2]


def apply_h(H: np.ndarray, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    w = H[2, 0] * u + H[2, 1] * v + H[2, 2]
    return (H[0, 0] * u + H[0, 1] * v + H[0, 2]) / w, (H[1, 0] * u + H[1, 1] * v + H[1, 2]) / w


def panel_grid(shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Normalised (u, v) of the pixel centres of a panel raster of ``shape`` (h, w)."""
    h, w = shape
    return np.meshgrid((np.arange(w) + 0.5) / w, (np.arange(h) + 0.5) / h)


def sample(img: np.ndarray, x: np.ndarray, y: np.ndarray, order: int = 1) -> np.ndarray:
    """Bilinear sample of ``img`` at pixel coordinates (pixel centres at +0.5)."""
    coords = [y - 0.5, x - 0.5]
    if img.ndim == 2:
        return ndimage.map_coordinates(img, coords, order=order, mode="nearest").astype(np.float32)
    return np.stack(
        [ndimage.map_coordinates(img[..., c], coords, order=order, mode="nearest") for c in range(img.shape[2])],
        axis=-1,
    ).astype(np.float32)


def to_panel(photo: np.ndarray, H: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """The photo resampled onto a panel raster of ``shape``."""
    u, v = panel_grid(shape)
    x, y = apply_h(H, u, v)
    return sample(photo, x, y)


def inside(H: np.ndarray, shape: tuple[int, int], photo_shape: tuple[int, int]) -> np.ndarray:
    u, v = panel_grid(shape)
    x, y = apply_h(H, u, v)
    return (x >= 0) & (y >= 0) & (x <= photo_shape[1]) & (y <= photo_shape[0])


def _gradmag(lum: np.ndarray, sigma: float) -> np.ndarray:
    return ndimage.gaussian_gradient_magnitude(lum, sigma).astype(np.float32)


def _ncc(a: np.ndarray, b: np.ndarray, m: np.ndarray) -> float:
    a, b = a[m], b[m]
    if a.size < 64:
        return -1.0
    a = a - a.mean()
    b = b - b.mean()
    d = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / d) if d > 0 else -1.0


def _resize(lum: np.ndarray, w: int) -> np.ndarray:
    """``lum`` resized to width ``w`` (anti-aliased)."""
    h = max(8, round(lum.shape[0] * w / lum.shape[1]))
    zoom = (h / lum.shape[0], w / lum.shape[1])
    pre = ndimage.gaussian_filter(lum, [max(0.0, 0.5 / z - 0.5) for z in zoom])
    return ndimage.zoom(pre, zoom, order=1).astype(np.float32)


def _interior(shape: tuple[int, int]) -> np.ndarray:
    h, w = shape
    m = np.zeros(shape, bool)
    bh, bw = max(1, round(h * BORDER)), max(1, round(w * BORDER))
    m[bh : h - bh, bw : w - bw] = True
    return m


def _level(photo_lum: np.ndarray, tex_lum: np.ndarray, face_w: float, edge: int):
    """One pyramid level: the panel at long edge ``edge`` and the photo at about its density."""
    lw = max(8, min(tex_lum.shape[1], round(edge * tex_lum.shape[1] / max(tex_lum.shape))))
    tex = _resize(tex_lum, lw)
    f = max(1, int(face_w / lw))
    ph = photo_lum if f == 1 else _resize(photo_lum, photo_lum.shape[1] // f)
    scale = np.array([photo_lum.shape[1] / ph.shape[1], photo_lum.shape[0] / ph.shape[0]])
    g_t = _gradmag(tex, 1.0)
    # Compare only near the source's own structure (lettering, graphics, colour edges): an edge
    # the source does not have (a shadow, an occluder, the model's extra marks) cannot pull the
    # fit, it can only lower the score.
    structure = ndimage.binary_dilation(g_t > np.percentile(g_t, STRUCTURE_PCT), iterations=2)
    interior = _interior(tex.shape) & structure

    def score(quad: np.ndarray) -> float:
        H = homography(quad / scale)
        g_p = _gradmag(to_panel(ph, H, tex.shape), 1.0)
        return _ncc(g_t, g_p, interior & inside(H, tex.shape, ph.shape))

    return score, scale


def refine(face_id: str, photo_lum: np.ndarray, tex_lum: np.ndarray, quad0) -> Registration:
    """Refine ``quad0`` (photo px, panel TL TR BR BL) so the source panel matches the photo."""
    quad0 = np.asarray(quad0, float)
    quad = quad0.copy()
    face_w = max(np.linalg.norm(quad0[1] - quad0[0]), np.linalg.norm(quad0[2] - quad0[3]))
    for edge in LEVELS:
        score, scale = _level(photo_lum, tex_lum, face_w, edge)
        base = quad.copy()
        res = optimize.minimize(
            lambda p, base=base, score=score, scale=scale: -score(base + p.reshape(4, 2) * scale),
            np.zeros(8),
            method="Powell",
            options={"xtol": 0.05, "ftol": 1e-5, "direc": np.eye(8) * 2.0},
        )
        quad = base + res.x.reshape(4, 2) * scale
    ncc0, ncc = score(quad0), score(quad)
    shift = float(np.linalg.norm(quad - quad0, axis=1).max())
    diag = float(np.linalg.norm(quad0[2] - quad0[0]))
    reason = None
    if ncc < MIN_NCC:
        reason = f"panel does not match the photo (gradient NCC {ncc:.2f} < {MIN_NCC})"
    elif shift > MAX_SHIFT * diag:
        reason = f"corners moved {shift:.0f}px (> {MAX_SHIFT:.0%} of the face): starting quad is wrong"
    return Registration(face_id, quad, homography(quad), ncc0, ncc, shift, reason is None, reason)
