"""Deterministic board, light and background of the flat render.

Same parameters always produce the same pixels. Artwork color is only *lit*, never redrawn:
every operation on the printed surface is a per-pixel multiply/add over the PDF render, so
typography, logos and layout stay exactly where the PDF put them.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from app.render.layers import Layers
from app.spec.models import FLAT_LOOK, Look

# Soft, even studio light: neutral colour, a faint fall-off across the sheet.
GRADIENT = 0.05
AMBIENT = 0.86


def hex_rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)


def light_dir(angle_deg: float) -> tuple[float, float]:
    """Unit vector pointing *toward* the light in image coords (0deg = top, clockwise)."""
    a = math.radians(angle_deg)
    return math.sin(a), -math.cos(a)


def value_noise(h: int, w: int, cell_px: float, seed: int = 7) -> np.ndarray:
    """Deterministic smooth noise in [-1, 1], fixed to the package's physical scale."""
    cell_px = max(1.0, cell_px)
    gh, gw = int(h / cell_px) + 2, int(w / cell_px) + 2
    rng = np.random.default_rng(seed)
    grid = rng.uniform(-1, 1, (gh, gw)).astype(np.float32)
    up = ndimage.zoom(grid, cell_px, order=1)
    return up[:h, :w] if up.shape[0] >= h and up.shape[1] >= w else np.resize(up, (h, w))


def crease_relief(L: Layers, m, light: tuple[float, float]) -> np.ndarray:
    """Brightness offset of the folds (negative = darker), from ``Material.crease_depth``."""
    k = m.crease_depth / 100
    width = max(1.0, 0.5 * m.caliper_mm * L.px_per_mm)
    valley = ndimage.gaussian_filter(L.crease, width)
    valley = valley / max(float(valley.max()), 1e-6)
    gy, gx = np.gradient(valley)
    # Height is -valley, so a wall's normal points along +grad(valley); lit where it meets
    # the light.
    facing = (gx * light[0] + gy * light[1]) * width
    return k * (0.18 * np.clip(facing, -1, 1) - 0.07 * valley)


def shift(m: np.ndarray, dx: float, dy: float) -> np.ndarray:
    return ndimage.shift(m, (dy, dx), order=1, mode="constant", cval=0.0)


def print_surface(L: Layers, m, alpha: np.ndarray | None = None) -> np.ndarray:
    """The print on the bare board (HxWx3 float), before any texture or light.
    ``alpha`` overrides the ink coverage (e.g. ink starved in the board's valleys)."""
    paper = hex_rgb(m.base_color)
    art_rgb = L.artwork[..., :3]
    art_a = L.artwork[..., 3:4] if alpha is None else alpha[..., None]
    return paper * (1 - art_a) + art_rgb * art_a


def render(
    L: Layers, look: Look = FLAT_LOOK, *, transparent: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    """Return (RGBA uint8 image, package alpha float32). Package alpha marks protected pixels."""
    m, li = look.material, look.lighting
    H, W = L.height, L.width
    sil = L.silhouette
    surface = print_surface(L, m)

    # Paper texture: amplitude from the texture value, softened by roughness.
    if m.texture > 0:
        noise = value_noise(H, W, cell_px=0.35 * L.px_per_mm)
        fine = value_noise(H, W, cell_px=0.12 * L.px_per_mm, seed=11)
        amp = (m.texture / 100) * 0.07 * (0.5 + 0.5 * m.roughness / 100)
        surface = surface * (1 + (0.7 * noise + 0.3 * fine)[..., None] * amp)

    # Creases: a pressed-in valley about one board thickness wide. The wall facing the light
    # catches it, the far wall is shaded, and the bottom is slightly compressed (darker).
    if m.crease_depth > 0:
        surface = surface * (1 + crease_relief(L, m, light_dir(li.light_angle))[..., None])

    intensity = li.light_intensity / 100
    dx, dy = light_dir(li.light_angle)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    cx, cy = W / 2, H / 2
    g = ((xx - cx) * dx + (yy - cy) * dy) / max(W, H)
    shade = (AMBIENT + 0.18 * intensity) * (1 + GRADIENT * intensity * 2 * g)
    surface = surface * shade[..., None]

    # Broad specular sheen from the paper's reflectivity and roughness.
    hx, hy = cx + dx * 0.35 * W, cy + dy * 0.35 * H
    r = (0.25 + 0.6 * m.roughness / 100) * max(W, H)
    d2 = ((xx - hx) ** 2 + (yy - hy) ** 2) / (r * r)
    surface = surface + ((m.reflectivity / 100) * 0.16 * intensity * np.exp(-d2))[..., None]

    # Board edge: thin highlight on the light-facing edge, so the cut reads against black.
    t_px = max(0.6, m.caliper_mm * L.px_per_mm)
    edge = sil - shift(sil, dx * 1.0, dy * 1.0)
    surface = np.clip(surface + (np.clip(edge, 0, 1) * 0.06)[..., None], 0, 1)

    # Contact shadow: soft, offset away from the light, scaled by board thickness.
    off = 0.6 + 1.2 * t_px
    shadow = ndimage.gaussian_filter(shift(sil, -dx * off, -dy * off), max(1.2, 2.5 * t_px) * 1.6)
    shadow = np.clip(shadow * (li.shadow_strength / 100) * 0.5, 0, 1) * (1 - sil)

    if transparent:
        alpha = np.clip(sil + shadow, 0, 1)
        rgb = np.where(
            alpha[..., None] > 0, surface * sil[..., None] / np.maximum(alpha, 1e-6)[..., None], 0
        )
        out = np.concatenate([rgb, alpha[..., None]], axis=-1)
    else:
        background = np.broadcast_to(hex_rgb(li.background_color), (H, W, 3))
        background = background * (1 - shadow[..., None])
        rgb = background * (1 - sil[..., None]) + surface * sil[..., None]
        out = np.concatenate([rgb, np.ones((H, W, 1), np.float32)], axis=-1)

    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), sil
