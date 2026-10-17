"""AI-photographed surface with the PDF's own print.

The model re-photographs the carton: board fibres, ribs, sheen, fold
compression, cut edges, light. Its print is not trusted (small text comes out garbled), so we
keep only the *surface* it photographed: ``shading = photo / print``. Where print edges are
(ours, and any strong edge the model drew), the shading is unreliable and is filled in from
the surrounding board, along the board's own lines, so ribs run on through the letters. The
carton's outline is kept as photographed (cut edge, board thickness, edge light). The result
is our print x the model's surface, with the ink slightly starved in the board's valleys.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from app.render.look import DETAIL_RANGE, EDGE_RANGE, LIGHT_RANGE, LUMA, light_gain

INK_STARVE = 0.06  # max ink coverage lost in the deepest valleys of the board
PRINT_KEEP = 0.7  # how much light/texture variation is removed on type and line work
INK_FILL = 0.5  # ink partly fills the board's relief: texture under solid ink is this much softer
MAX_LINE_GAP_MM = 25  # longer gaps along a rib fall back to an isotropic fill


def outline_band(sil: np.ndarray, px_per_mm: float) -> np.ndarray:
    """The carton's cut edge, ~0.6 mm wide: board thickness and edge light live here."""
    edge = (sil > 0.001) & (sil < 0.999)
    return ndimage.binary_dilation(edge, iterations=max(1, round(0.6 * px_per_mm)))


def print_edges(print_rgb: np.ndarray, sil: np.ndarray, px_per_mm: float) -> np.ndarray:
    """Where our print has edges (glyphs, lines, logo outlines)."""
    lum = ndimage.gaussian_filter(print_rgb @ LUMA, 0.7)
    grad = np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1)) / 8
    return ndimage.binary_dilation(grad > 0.012, iterations=max(1, round(0.2 * px_per_mm)))


def _model_edges(scene: np.ndarray, solid: np.ndarray, px_per_mm: float) -> np.ndarray:
    """Strong edges the model drew (its own, possibly misplaced, print). Board texture is a
    few percent of contrast and fills the whole surface; print edges are far stronger."""
    lum = ndimage.gaussian_filter(np.log(np.clip(scene @ LUMA, 0.02, 1)), 0.7)
    grad = np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1)) / 8
    typical = float(np.median(grad[solid])) if solid.any() else 0.0
    strong = grad > max(0.035, 3.5 * typical)
    return ndimage.binary_dilation(strong, iterations=max(1, round(0.2 * px_per_mm)))


PRINT_ZONE_MM = 2.0  # around our print the model's surface is never trusted (its own text)


def _fill_blur(v: np.ndarray, valid: np.ndarray, todo: np.ndarray) -> np.ndarray:
    """Fill ``todo`` from nearby valid values (multi-scale normalised blur)."""
    out = v.copy()
    todo = todo.copy()
    w = valid.astype(np.float32)
    for sigma in (2, 4, 8, 16, 32, 64):
        if not todo.any():
            break
        num = ndimage.gaussian_filter(v * w, sigma)
        den = ndimage.gaussian_filter(w, sigma)
        ok = todo & (den > 0.15)
        out[ok] = num[ok] / den[ok]
        todo &= ~ok
    out[todo] = 1.0
    return out


def _orientation(d: np.ndarray) -> tuple[float, float, bool]:
    """(angle of the line normal in degrees, period in px, whether lines dominate)."""
    n = d.shape[0]
    win = np.outer(np.hanning(n), np.hanning(n))
    p = np.abs(np.fft.fftshift(np.fft.fft2(d * win))) ** 2
    c = n // 2
    yy, xx = np.mgrid[0:n, 0:n] - c
    r = np.hypot(xx, yy)
    p[(r < 3) | (r > c - 1)] = 0  # ignore the mean and the corners
    p = ndimage.gaussian_filter(p, 1)
    iy, ix = np.unravel_index(p.argmax(), p.shape)
    fy, fx = iy - c, ix - c
    period = n / max(math.hypot(fx, fy), 1e-6)
    # A real line pattern concentrates power at +-f; noise spreads it in a ring.
    ring = p[(r > math.hypot(fx, fy) * 0.8) & (r < math.hypot(fx, fy) * 1.2)]
    striped = p.max() > 6 * (np.median(ring) + 1e-12)
    return math.degrees(math.atan2(fy, fx)), period, bool(striped)


def line_direction(detail: np.ndarray, valid: np.ndarray) -> str | None:
    """'horizontal' or 'vertical' when the board has dominant straight lines, else None."""
    h, w = detail.shape
    n = min(512, h, w)
    best, best_score = None, -1.0
    for y in range(0, h - n + 1, max(1, n // 2)):
        for x in range(0, w - n + 1, max(1, n // 2)):
            score = float(valid[y : y + n, x : x + n].mean())
            if score > best_score:
                best, best_score = (y, x), score
    if best is None or best_score < 0.6:
        return None
    y, x = best
    patch = np.where(valid[y : y + n, x : x + n], detail[y : y + n, x : x + n], 1.0)
    angle, _, striped = _orientation(np.log(np.maximum(patch, 1e-3)))
    if not striped:
        return None
    # ``angle`` is the direction of the line *normal*; lines run perpendicular to it.
    normal = abs(
        math.degrees(math.atan2(math.sin(math.radians(angle)), math.cos(math.radians(angle))))
    )
    if abs(normal - 90) < 20:
        return "horizontal"
    if normal < 20 or normal > 160:
        return "vertical"
    return None


def _fill_rows(v: np.ndarray, valid: np.ndarray, todo: np.ndarray, max_gap: int) -> np.ndarray:
    """Fill each row's gaps by interpolating between its valid neighbours (lines run along x)."""
    out = v.copy()
    xs = np.arange(v.shape[1])
    for y in np.nonzero(todo.any(axis=1))[0]:
        good = np.nonzero(valid[y])[0]
        if good.size < 2:
            continue
        need = np.nonzero(todo[y])[0]
        right = np.searchsorted(good, need)
        left = right - 1
        inside = (left >= 0) & (right < good.size)
        need, left, right = need[inside], left[inside], right[inside]
        short = (good[right] - good[left]) <= max_gap
        need = need[short]
        if need.size:
            out[y, need] = np.interp(xs[need], good, v[y, good])
            todo[y, need] = False
    return out


def fill_along_lines(
    v: np.ndarray, valid: np.ndarray, region: np.ndarray, direction: str | None, max_gap: int
) -> np.ndarray:
    """Fill ``region & ~valid`` along the board's lines; leftovers isotropically."""
    todo = region & ~valid
    out = v
    if direction in ("horizontal", "vertical"):
        t = direction == "vertical"
        vv, va, td = (v.T, valid.T, todo.T.copy()) if t else (v, valid, todo.copy())
        filled = _fill_rows(vv, va, td, max_gap)
        out, todo = (filled.T, td.T) if t else (filled, td)
    if todo.any():
        out = _fill_blur(out, valid | (region & ~todo), todo)
    return out


def transfer(
    print_rgb: np.ndarray,
    scene: np.ndarray,
    sil: np.ndarray,
    px_per_mm: float,
    direction_hint: str | None = None,
    ink: np.ndarray | None = None,
    folds: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(gain HxWx3, print-edge mask, valley 0..1) for ``package = print x gain``.

    ``valley`` marks the board's low spots (rib valleys, fibre pits) for ink starvation.
    """
    solid = sil >= 0.999
    band = outline_band(sil, px_per_mm) & (sil > 0.001)
    light = light_gain(scene, print_rgb, solid.astype(np.float32)) @ LUMA
    ratio = (scene @ LUMA) / np.maximum(print_rgb @ LUMA, 0.03)
    raw = ratio / np.maximum(light, 1e-3)
    # Exposure-neutral: the package's overall brightness and colour stay the Figma print's;
    # only a gentle fall of light and shadow remains (no tint).
    if solid.any():
        light = light / max(float(np.median(light[solid])), 1e-3)
    light = np.clip(light, *LIGHT_RANGE)
    # Zero-mean surface detail: texture modulates around the true colour, never shifts it.
    local = ndimage.gaussian_filter(raw, max(2.0, 4 * px_per_mm))
    detail = np.clip(raw / np.maximum(local, 1e-3), *DETAIL_RANGE)
    # Cut edge as photographed (no print there): board thickness and light on the cut face.
    detail[band] = np.clip(raw[band], *EDGE_RANGE)

    # Our print's own edges (thin), and the zone around them where the model's redrawn text
    # lands even after alignment: there its surface is replaced by the board's, along the ribs.
    edges = print_edges(print_rgb, sil, px_per_mm) & solid & ~band
    zone = ndimage.binary_dilation(edges, iterations=max(2, round(PRINT_ZONE_MM * px_per_mm)))
    untrusted = (zone | _model_edges(scene, solid, px_per_mm)) & solid & ~band
    if folds is not None:
        # Fold grooves are the board's own relief: keep them as photographed.
        groove = ndimage.binary_dilation(folds > 0.3, iterations=max(3, round(1.2 * px_per_mm)))
        untrusted &= ~(groove & ~edges)
    valid = solid & ~untrusted
    direction = line_direction(detail, valid) or direction_hint
    detail = fill_along_lines(detail, valid, solid, direction, round(MAX_LINE_GAP_MM * px_per_mm))
    # Feather the filled areas so no seam shows around the print.
    soft = ndimage.gaussian_filter(untrusted.astype(np.float32), 0.8)
    detail = detail * (1 - soft) + ndimage.gaussian_filter(detail, 0.8) * soft

    # Board valleys: where the surface is locally darker than its surroundings.
    hp = detail / np.maximum(ndimage.gaussian_filter(detail, max(1.5, 0.8 * px_per_mm)), 1e-3)
    valley = np.clip((1 - hp) / 0.08, 0, 1) * solid

    if ink is not None:
        # Type and line work: the ink film partly fills the valleys, so ribs read softer
        # through letters (never as strike-throughs). Large tints keep the full relief.
        near_print = ndimage.gaussian_filter(edges.astype(np.float32), max(1.0, 0.3 * px_per_mm))
        detail = 1 + (detail - 1) * (1 - INK_FILL * np.clip(near_print * 2, 0, 1))
    # Type, logos and line work keep their exact colour: light and texture reach them only
    # faintly (a real print looks the same colour under a soft studio light). Texture eases off
    # right at the letters; light eases off over a wide, soft area so no halo outlines the type.
    edge_f = edges.astype(np.float32)
    near = np.clip(ndimage.gaussian_filter(edge_f, max(1.0, 0.3 * px_per_mm)) * 2, 0, 1)
    wide = np.clip(ndimage.gaussian_filter(edge_f, max(3.0, 4.0 * px_per_mm)) * 3, 0, 1)
    light = 1 + (light - 1) * (1 - PRINT_KEEP * wide)
    detail = 1 + (detail - 1) * (1 - PRINT_KEEP * near)
    total = light * detail
    gain = np.repeat(total[..., None], 3, axis=-1)  # same on R, G, B: no tint
    lo = LIGHT_RANGE[0] * min(DETAIL_RANGE[0], EDGE_RANGE[0])
    hi = LIGHT_RANGE[1] * max(DETAIL_RANGE[1], EDGE_RANGE[1])
    return np.clip(gain, lo, hi).astype(np.float32), untrusted, valley.astype(np.float32)
