"""Deterministic board, light and background of the flat render.

Same parameters always produce the same pixels. Artwork color is only *lit*, never redrawn:
inside the board the image is ``clip(print x gain)`` with one achromatic gain per pixel, so
typography, logos, gradients and layout stay exactly where and how the PDF put them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from app.render.layers import Layers
from app.spec.models import FLAT_LOOK, Look

# Soft, even studio light: neutral colour, a faint fall-off across the sheet.
GRADIENT = 0.04
EXPOSURE = 0.975  # white board reads as paper white, not a glowing #FFF
# Paper fibres: ``Material.texture`` 20 peaks at about +-1.4% brightness, the same on R, G, B.
TEXTURE_PER_UNIT = 0.25
INK_DAMP = 0.7  # fibres show this much less through ink
EDGE_LIGHT = 0.04  # hairline catch-light on the light-facing cut edge
# A fold score as in the reference photo, measured across a fold there: a thin groove about
# 12% darker and next to it a bead about 6% brighter, together ~1.5 mm wide.
CREASE_GROOVE = 0.10
CREASE_BEAD = 0.05


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
    """Brightness offset of the folds (negative = darker), from ``Material.crease_depth``.

    A fold score photographed from above (reference photo): a thin shaded groove and, about
    one board thickness beside it, the bright far wall. Depth 30 gives -10% / +5%.
    """
    k = m.crease_depth / 30
    t = max(0.6, m.caliper_mm * L.px_per_mm)  # board thickness in px

    def line(mask: np.ndarray, sigma: float) -> np.ndarray:
        v = ndimage.gaussian_filter(mask, sigma)
        return v / max(float(v.max()), 1e-6)

    groove = line(L.crease, max(0.6, 0.35 * t))
    # The groove's far wall faces the light, so the bright bead sits away from the light.
    bead = line(shift(L.crease, -light[0] * 1.2 * t, -light[1] * 1.2 * t), max(0.8, 0.5 * t))
    return k * (CREASE_BEAD * bead - CREASE_GROOVE * groove)


def shift(m: np.ndarray, dx: float, dy: float) -> np.ndarray:
    return ndimage.shift(m, (dy, dx), order=1, mode="constant", cval=0.0)


def print_surface(L: Layers, m, alpha: np.ndarray | None = None) -> np.ndarray:
    """The print on the bare board (HxWx3 float), before any texture or light.
    ``alpha`` overrides the ink coverage (e.g. ink starved in the board's valleys)."""
    paper = hex_rgb(m.base_color)
    art_rgb = L.artwork[..., :3]
    art_a = L.artwork[..., 3:4] if alpha is None else alpha[..., None]
    return paper * (1 - art_a) + art_rgb * art_a


@dataclass
class Parts:
    """The flat render, split so the print can be checked against it.

    Inside the board ``rgb = clip(print_rgb x gain)`` exactly; outside it is the background with
    the contact shadow. ``gain`` is achromatic (one value for R, G and B): paper fibres, folds,
    light and the cut edge only change how bright the print looks, never its colour or shape.
    """

    rgb: np.ndarray  # HxWx3 float, final colour
    sil: np.ndarray  # HxW float, board coverage (anti-aliased)
    gain: np.ndarray  # HxW float, achromatic paper/light gain on the print
    print_rgb: np.ndarray  # HxWx3 float, the PDF print on bare board
    shadow: np.ndarray  # HxW float, contact shadow outside the board
    background: np.ndarray  # HxWx3 float, the ground with the contact shadow


def paper_gain(L: Layers, look: Look = FLAT_LOOK) -> np.ndarray:
    """Achromatic gain over the board: fine fibres, fold scores, soft light, edge catch-light.

    Everything is multiplicative and the same on R, G and B, so it can only lighten or darken
    the print a little; it never blurs, moves or tints it.
    """
    if look.style == "v2":
        return physical_gain(L, look)
    m, li = look.material, look.lighting
    H, W = L.height, L.width
    gain = np.ones((H, W), np.float32)

    # Paper fibres: fine and low-amplitude, at the board's physical scale (0.1-0.35 mm). Under
    # ink the fibres read softer (the ink film fills them), so type stays clean.
    if m.texture > 0:
        noise = 0.7 * value_noise(H, W, cell_px=0.35 * L.px_per_mm)
        noise += 0.3 * value_noise(H, W, cell_px=0.12 * L.px_per_mm, seed=11)
        amp = m.texture / 100 * TEXTURE_PER_UNIT * (0.5 + 0.5 * m.roughness / 100)
        gain *= 1 + noise * amp * (1 - INK_DAMP * L.artwork[..., 3])

    # Creases: a narrow, shallow score about one board thickness wide.
    light = light_dir(li.light_angle)
    if m.crease_depth > 0:
        gain *= 1 + crease_relief(L, m, light)

    # Soft, even studio light: a gentle fall-off across the sheet, no hot spot or sheen.
    intensity = li.light_intensity / 100
    dx, dy = light
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    g = ((xx - W / 2) * dx + (yy - H / 2) * dy) / max(W, H)
    gain *= EXPOSURE * (1 + GRADIENT * intensity * 2 * g)

    # Cut edge: a hairline catch-light on the light-facing side, so the cut reads against black.
    edge = np.clip(L.silhouette - shift(L.silhouette, dx, dy), 0, 1)
    gain *= 1 + EDGE_LIGHT * edge
    return gain.astype(np.float32)


# ---- v2: physical board ---------------------------------------------------------------
# Measured against the reference photo (prompts/flat_look.png) and real matte board: fibres
# show only at close range, the cut edge reads as a hair of board thickness, folds are soft
# scored channels, the light is an even overhead softbox.

FIBRE_STD = 0.005  # fibre texture std at full size (Material.texture 20); ~4x less at 1/4 size
FIBRE_LENGTH_MM = 0.35  # fibres lie along the machine direction (horizontal)
FIBRE_WIDTH_MM = 0.03
EDGE_RIM_MM = 0.35  # how far in from the cut the board's thickness shows
EDGE_SHADE = 0.035  # the rounded cut edge, a little darker
EDGE_LIT = 0.02  # ... and a little lighter where it faces the light
SCORE_GROOVE = 0.08  # fold score: soft channel
SCORE_SHOULDER = 0.035  # its far wall catching the light
SOFTBOX_FALLOFF = 0.02  # overhead softbox: corners this much darker than the centre


def fibre_texture(L: Layers, m) -> np.ndarray:
    """Zero-mean paper fibres (HxW): fine grain plus short fibres along the machine direction.
    Nothing coarser than ~1 mm survives, so it cannot read as clouds or mottling."""
    H, W = L.height, L.width
    px = L.px_per_mm
    rng = np.random.default_rng(23)
    grain = ndimage.gaussian_filter(rng.standard_normal((H, W), np.float32), max(0.5, 0.04 * px))
    fibres = ndimage.gaussian_filter(
        rng.standard_normal((H, W), np.float32),
        (max(0.5, FIBRE_WIDTH_MM * px), max(0.8, FIBRE_LENGTH_MM * px)),
    )
    tex = grain / max(float(grain.std()), 1e-6) + 0.6 * fibres / max(float(fibres.std()), 1e-6)
    tex -= ndimage.gaussian_filter(tex, max(2.0, 1.0 * px))  # no mottling above ~1 mm
    return tex / max(float(tex.std()), 1e-6) * FIBRE_STD * (m.texture / 20)


def edge_rim(L: Layers, m, light: tuple[float, float]) -> np.ndarray:
    """Brightness offset of the cut edge: the board's thickness, seen from straight above, is a
    hair-thin rounded rim just inside the cut. Never outside the board: the cut stays exact."""
    px = L.px_per_mm
    inside = L.silhouette > 0.5
    depth = ndimage.distance_transform_edt(inside).astype(np.float32)
    rim_px = max(1.0, EDGE_RIM_MM * px * m.caliper_mm / 0.46)
    rim = np.exp(-depth / rim_px) * inside
    # Which way the edge faces: the outward normal from the blurred silhouette.
    soft = ndimage.gaussian_filter(L.silhouette, max(1.0, rim_px))
    gy, gx = np.gradient(soft)
    norm = np.maximum(np.hypot(gx, gy), 1e-6)
    facing = np.clip(-(gx * light[0] + gy * light[1]) / norm, 0, 1)
    return rim * (EDGE_LIT * facing - EDGE_SHADE)


def score_relief(L: Layers, m, light: tuple[float, float]) -> np.ndarray:
    """A fold score: a soft pressed channel with its far wall catching the light. Smooth
    transitions (no hard line); only darkens a few percent, so it never reads as a cut."""
    k = m.crease_depth / 30
    t = max(0.6, m.caliper_mm * L.px_per_mm)

    def line(mask: np.ndarray, sigma: float) -> np.ndarray:
        v = ndimage.gaussian_filter(mask, sigma)
        return v / max(float(v.max()), 1e-6)

    groove = line(L.crease, max(0.8, 0.6 * t))
    shoulder = line(shift(L.crease, -light[0] * 1.3 * t, -light[1] * 1.3 * t), max(1.0, 0.8 * t))
    return k * (SCORE_SHOULDER * shoulder - SCORE_GROOVE * groove)


def print_edge_zone(L: Layers, m) -> np.ndarray:
    """0..1 near the edges of the print (glyphs, logos, lines), 0 on flat tints and paper."""
    lum = print_surface(L, m) @ np.array([0.299, 0.587, 0.114], np.float32)
    lum = ndimage.gaussian_filter(lum, 0.7)
    grad = np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1)) / 8
    zone = (grad > 0.012).astype(np.float32)
    return np.clip(ndimage.gaussian_filter(zone, max(1.0, 0.15 * L.px_per_mm)) * 3, 0, 1)


def softbox(L: Layers) -> np.ndarray:
    """Even overhead light: a very gentle fall-off from the centre of the sheet."""
    H, W = L.height, L.width
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r2 = ((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2
    return 1 - SOFTBOX_FALLOFF * r2 / 2


def physical_gain(L: Layers, look: Look) -> np.ndarray:
    m, li = look.material, look.lighting
    light = light_dir(li.light_angle)
    gain = np.full((L.height, L.width), EXPOSURE, np.float32)
    if m.texture > 0:
        # Fibres show through flat tints and gradients (thin ink), but ease off right at type,
        # logos and line work so every edge of the print stays clean.
        gain *= 1 + fibre_texture(L, m) * (1 - INK_DAMP * print_edge_zone(L, m))
    if m.crease_depth > 0:
        gain *= 1 + score_relief(L, m, light)
    gain *= 1 + edge_rim(L, m, light)
    gain *= softbox(L)
    return gain.astype(np.float32)


def contact_shadow(L: Layers, look: Look = FLAT_LOOK) -> np.ndarray:
    """A narrow shadow just outside the cut, from the exact silhouette (never from a model)."""
    m, li = look.material, look.lighting
    dx, dy = light_dir(li.light_angle)
    t_px = max(0.6, m.caliper_mm * L.px_per_mm)
    off = 0.6 + 1.2 * t_px
    shadow = ndimage.gaussian_filter(
        shift(L.silhouette, -dx * off, -dy * off), max(1.2, 2.5 * t_px)
    )
    return np.clip(shadow * (li.shadow_strength / 100) * 0.5, 0, 1) * (1 - L.silhouette)


def render_parts(L: Layers, look: Look = FLAT_LOOK) -> Parts:
    sil = L.silhouette
    print_rgb = print_surface(L, look.material)
    gain = paper_gain(L, look)
    board = np.clip(print_rgb * gain[..., None], 0, 1)
    shadow = contact_shadow(L, look)
    background = np.broadcast_to(
        hex_rgb(look.lighting.background_color) * (1 - shadow[..., None]), print_rgb.shape
    ).astype(np.float32)
    rgb = background * (1 - sil[..., None]) + board * sil[..., None]
    return Parts(rgb.astype(np.float32), sil, gain, print_rgb, shadow, background)


def to8(rgb: np.ndarray) -> np.ndarray:
    return (np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8)


def render(
    L: Layers, look: Look = FLAT_LOOK, *, transparent: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    """Return (RGBA uint8 image, package alpha float32). Package alpha marks protected pixels."""
    p = render_parts(L, look)
    H, W = L.height, L.width
    if transparent:
        alpha = np.clip(p.sil + p.shadow, 0, 1)
        board = np.clip(p.print_rgb * p.gain[..., None], 0, 1)
        rgb = np.where(
            alpha[..., None] > 0, board * p.sil[..., None] / np.maximum(alpha, 1e-6)[..., None], 0
        )
        out = np.concatenate([rgb, alpha[..., None]], axis=-1)
    else:
        out = np.concatenate([p.rgb, np.ones((H, W, 1), np.float32)], axis=-1)
    return to8(out), p.sil
