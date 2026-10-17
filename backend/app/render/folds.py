"""Physical fold scores for the v4 look: a height field from the exact crease geometry, its
surface normals, and a soft directional light on them.

A score is a narrow pressed groove with a slightly raised, rounded shoulder on each side that
blends back into the flat board within a couple of millimetres. Seen from directly above under
a soft studio light, the groove is occluded (a little darker), the shoulder facing the light
catches it and the one facing away is shaded. Everything is computed in millimetres from
``Layers.px_per_mm``, so it looks the same at any output size, and only as an achromatic gain:
the print is never moved, blurred or tinted, and a fold never becomes a dark slit.

Height profile across a fold at distance ``d`` (mm) from the crease line:

    h(d) = -depth * exp(-d^2 / 2 g^2) + shoulder * exp(-(d - s)^2 / 2 w^2)   (mm)

Distances come from the exact crease raster (a Euclidean distance transform), so crossing folds
merge into one smooth surface (no doubled dark spots), angled and curved folds are shaded by
their own normal, and fold ends taper out instead of stopping as blunt marks.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from app.render.layers import Layers

EDGE_FADE_MM = 0.5  # relief eases to flat this close to the cut
GAIN_LIMITS = (0.86, 1.07)
CROSSING_EASE = 0.5  # share of the shadow taken back where folds cross  # a fold only shades the board; it never reads as a slit or glow


@dataclass(frozen=True)
class FoldParams:
    depth_mm: float = 0.032  # groove depth (a fraction of a 0.46 mm board)
    groove_mm: float = 0.30  # groove half-width (sigma); visible crease ~0.6-0.9 mm
    shoulder_mm: float = 0.013  # shoulder rise
    shoulder_at_mm: float = 0.55  # distance of the shoulder crest from the fold line
    shoulder_width_mm: float = 0.45  # shoulder softness (sigma); blends out within ~2 mm
    occlusion: float = 0.05  # groove darkening (ambient occlusion) at full depth
    shadow: float = 1.0  # strength of the shaded side (directional)
    highlight: float = 0.8  # strength of the lit side (matte diffuse catch-light)
    light_elevation_deg: float = 30.0  # soft key light: low enough to model the relief
    hinge_boost: float = 0.25  # extra relief where a fold hinges a small flap
    softness_px: float = 0.7  # final smoothing of the height field (anti-staircase)


FOLD_PRESETS: dict[str, FoldParams] = {
    "low": FoldParams(depth_mm=0.022, shoulder_mm=0.009, occlusion=0.035, highlight=0.6),
    "medium": FoldParams(),
    "high": FoldParams(depth_mm=0.045, shoulder_mm=0.018, occlusion=0.065, highlight=0.9),
}


@dataclass
class FoldMaps:
    mask: np.ndarray  # HxW bool, the crease lines
    height: np.ndarray  # HxW mm, 0 = flat board, negative = pressed in
    normals: np.ndarray  # HxWx3 unit surface normals (x right, y down, z up)
    shadow: np.ndarray  # HxW >= 0, how much darker (occlusion + facing away from the light)
    highlight: np.ndarray  # HxW >= 0, how much lighter (facing the light)
    gain: np.ndarray  # HxW, 1 + highlight - shadow, on the board only


def light_vector(angle_deg: float, elevation_deg: float) -> np.ndarray:
    """Unit vector toward the light: azimuth like ``shading.light_dir`` (0 = top, clockwise)
    in image coordinates (y down), raised by ``elevation_deg`` above the board."""
    a, e = np.radians(angle_deg), np.radians(elevation_deg)
    return np.array([np.sin(a) * np.cos(e), -np.cos(a) * np.cos(e), np.sin(e)], np.float32)


def _density(line: np.ndarray, px: float) -> np.ndarray:
    """Fold-line density relative to one straight fold (~2 mm scale): 1 along a fold, ~0.5 at
    a free end, above 1 where folds cross or run close together."""
    sigma = max(1.0, 2.0 * px)
    density = ndimage.gaussian_filter(line.astype(np.float32), sigma)
    # A long straight line of this raster's width has density width / (sqrt(2 pi) sigma).
    width = max(1.0, float(line.sum()) / max(1.0, _length_px(line)))
    straight = width / (np.sqrt(2 * np.pi) * sigma)
    return density / max(straight, 1e-6)


def _length_px(line: np.ndarray) -> float:
    """Approximate centre-line length of a rasterized line set (its skeleton pixel count)."""
    thin = line & ~ndimage.binary_erosion(line)
    return max(1.0, float(thin.sum()) / 2)


def _hinges(L: Layers, line: np.ndarray, px: float) -> np.ndarray:
    """0..1 near folds that hinge a small flap onto a large panel (tuck flaps, dust flaps,
    glue tabs): there the board is worked harder and the score reads a little stronger."""
    board = L.silhouette >= 0.5
    folds = ndimage.binary_dilation(line, iterations=max(1, round(0.5 * px)))
    labels, n = ndimage.label(board & ~folds)
    if n < 2:
        return np.zeros(line.shape, np.float32)
    areas = ndimage.sum(np.ones_like(labels), labels, range(1, n + 1))
    small = np.isin(labels, 1 + np.nonzero(areas < 0.3 * areas.max())[0])
    near_small = ndimage.binary_dilation(small, iterations=max(2, round(2.0 * px)))
    # Share of the nearby fold lines that are hinges: 1 along a hinge, easing off at its ends.
    sigma = max(1.0, 1.0 * px)
    hinge = ndimage.gaussian_filter((line & near_small).astype(np.float32), sigma)
    every = ndimage.gaussian_filter(line.astype(np.float32), sigma)
    return np.where(every > 1e-4, hinge / np.maximum(every, 1e-4), 0).astype(np.float32)


def fold_maps(L: Layers, p: FoldParams, light_angle: float) -> FoldMaps:
    px = L.px_per_mm
    line = L.crease > 0.5
    board = L.silhouette >= 0.999
    h, w = L.height, L.width
    if not line.any():
        flat = np.zeros((h, w), np.float32)
        normals = np.zeros((h, w, 3), np.float32)
        normals[..., 2] = 1
        return FoldMaps(line, flat, normals, flat, flat, np.ones((h, w), np.float32))

    d = ndimage.distance_transform_edt(~line).astype(np.float32) / px  # mm to the crease
    groove = np.exp(-(d**2) / (2 * p.groove_mm**2))
    shoulder = np.exp(-((d - p.shoulder_at_mm) ** 2) / (2 * p.shoulder_width_mm**2))
    density = _density(line, px)
    # A score fades out toward a free end and never doubles where folds cross.
    amp = np.clip(density, 0, 1) * (1 + p.hinge_boost * _hinges(L, line, px))
    crossing = np.clip(density - 1, 0, 1)
    height = amp * (-p.depth_mm * groove + p.shoulder_mm * shoulder)
    # Ease to flat over the last half millimetre before the cut: no step at the board edge
    # (which would read as a steep wall), and nothing at all off the board.
    to_cut = ndimage.distance_transform_edt(L.silhouette > 0.5).astype(np.float32) / px
    edge_fade = np.clip(to_cut / EDGE_FADE_MM, 0, 1)
    height *= edge_fade * edge_fade * (3 - 2 * edge_fade)  # smoothstep
    height = ndimage.gaussian_filter(height, p.softness_px).astype(np.float32)
    height *= board

    # Normals from the height gradient, per mm (x right, y down, z up).
    gy, gx = np.gradient(height)
    gx, gy = gx * px, gy * px
    norm = np.sqrt(gx * gx + gy * gy + 1)
    normals = np.stack([-gx / norm, -gy / norm, 1 / norm], axis=-1).astype(np.float32)

    # Lambert on the relief, relative to flat board: > 0 faces the light, < 0 faces away.
    lv = light_vector(light_angle, p.light_elevation_deg)
    lit = (normals @ lv) / lv[2] - 1
    occlusion = p.occlusion * np.clip(-height / max(p.depth_mm, 1e-6), 0, 1)
    highlight = (p.highlight * np.clip(lit, 0, None)).astype(np.float32)
    shadow = p.shadow * np.clip(-lit, 0, None) + occlusion
    # Where folds cross, their shaded walls would add into a dark corner: blend them into one.
    shadow = (shadow * (1 - CROSSING_EASE * crossing)).astype(np.float32)
    gain = np.clip(1 + (highlight - shadow) * board, *GAIN_LIMITS).astype(np.float32)
    return FoldMaps(line, height, normals, shadow * board, highlight * board, gain)
