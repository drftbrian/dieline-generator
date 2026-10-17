"""Finishing masks from source geometry, pixel-aligned with the flat render.

Figma assets: the node's outlined SVG (exact glyphs, counters, compound paths) is placed on a
blank page at the node's frame-relative bounds and rasterised with the same scale, clip and
pixel origin as the artwork layer (``render.layers.build_layers``), so mask and print register
exactly. Clipping ancestors are applied; the mask never leaves the board (silhouette).

PDF-only projects: the printed ink inside the object's box (for text, ink close to the text's
colour) - approximate where objects overlap, reported as ``exact: False``.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

import numpy as np
import pymupdf

from app.render import look
from app.render.layers import Layers, frame
from app.spec.models import FLAT_LOOK, Specification

CACHE: OrderedDict[tuple, np.ndarray] = OrderedDict()
CACHE_SIZE = 256
_lock = threading.Lock()


def _place(alpha: np.ndarray, h: int, w: int, dy: int, dx: int) -> np.ndarray:
    out = np.zeros((h, w), np.float32)
    y0, x0 = max(0, dy), max(0, dx)
    sy, sx = max(0, -dy), max(0, -dx)
    hh = min(h - y0, alpha.shape[0] - sy)
    ww = min(w - x0, alpha.shape[1] - sx)
    if hh > 0 and ww > 0:
        out[y0 : y0 + hh, x0 : x0 + ww] = alpha[sy : sy + hh, sx : sx + ww]
    return out


def svg_coverage(
    svg: str, bbox: list[float], clip: list[float] | None, spec: Specification, long_edge: int
) -> np.ndarray:
    """Anti-aliased coverage (HxW, 0..1) of an outlined SVG placed at ``bbox`` (page pt)."""
    raster, crop = frame(spec, long_edge, FLAT_LOOK.lighting.margin)
    src = pymupdf.open(stream=svg.encode("utf-8"), filetype="svg")
    pdf = pymupdf.open("pdf", src.convert_to_pdf())
    doc = pymupdf.open()
    page = doc.new_page(width=spec.page.width_pt, height=spec.page.height_pt)
    target = pymupdf.Rect(*bbox)
    if clip:  # clipping ancestors: draw only the visible part, at its own place
        visible = target & pymupdf.Rect(*clip)
        if visible.is_empty:
            return np.zeros((raster.h, raster.w), np.float32)
        sw, sh = pdf[0].rect.width, pdf[0].rect.height
        kx, ky = sw / max(target.width, 1e-6), sh / max(target.height, 1e-6)
        src = pymupdf.Rect(
            (visible.x0 - target.x0) * kx,
            (visible.y0 - target.y0) * ky,
            (visible.x1 - target.x0) * kx,
            (visible.y1 - target.y0) * ky,
        )
        page.show_pdf_page(visible, pdf, 0, clip=src, keep_proportion=False)
        target = visible
    else:
        page.show_pdf_page(target, pdf, 0, keep_proportion=False)
    region = (target + (-1, -1, 1, 1)) & pymupdf.Rect(*crop)
    if region.is_empty:
        return np.zeros((raster.h, raster.w), np.float32)
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(raster.scale, raster.scale), clip=region, alpha=True, annots=False
    )
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., 3]
    dx = pix.x - round(raster.origin[0] * raster.scale)
    dy = pix.y - round(raster.origin[1] * raster.scale)
    cov = _place(a.astype(np.float32) / 255, raster.h, raster.w, dy, dx)
    # Foil, UV and relief are deposited where the shape is, not thinned by the source's opacity:
    # normalise the shape's interior to 1, keep the anti-aliased edge.
    inside = cov[cov > 0.02]
    peak = float(np.percentile(inside, 99)) if inside.size else 1.0
    return np.clip(cov / max(peak, 1e-3), 0, 1)


def ink_coverage(L: Layers, bbox: list[float], color: str | None) -> np.ndarray:
    """PDF-only fallback: printed ink inside the box (close to ``color`` when given)."""
    ox, oy = L.origin
    x0 = max(0, int((bbox[0] - ox) * L.scale))
    y0 = max(0, int((bbox[1] - oy) * L.scale))
    x1 = min(L.width, int(np.ceil((bbox[2] - ox) * L.scale)))
    y1 = min(L.height, int(np.ceil((bbox[3] - oy) * L.scale)))
    out = np.zeros((L.height, L.width), np.float32)
    if x1 <= x0 or y1 <= y0:
        return out
    a = L.artwork[y0:y1, x0:x1, 3]
    if color:
        hexv = color.lstrip("#")[:6]
        target = np.array([int(hexv[i : i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)
        close = look.delta_e(L.artwork[y0:y1, x0:x1, :3], target) < 15
        a = a * close
    out[y0:y1, x0:x1] = a
    return out


def asset_mask(
    pid: str,
    spec: Specification,
    asset: dict,
    long_edge: int,
    layers: Layers,
    svg: str | None,
    structure: str,
) -> np.ndarray:
    """The finishing mask of one asset (HxW 0..1), on the board only. Cached in memory."""
    key = (pid, structure, long_edge, asset["id"], asset.get("exact"))
    with _lock:
        if key in CACHE:
            CACHE.move_to_end(key)
            return CACHE[key]
    if svg is not None:
        m = svg_coverage(svg, asset["bbox"], asset.get("clip"), spec, long_edge)
    else:
        m = ink_coverage(layers, asset["bbox"], asset.get("color"))
    m = (m * (layers.silhouette > 0.001)).astype(np.float32)
    with _lock:
        CACHE[key] = m
        while len(CACHE) > CACHE_SIZE:
            CACHE.popitem(last=False)
    return m


def outline(m: np.ndarray, width: int = 2) -> np.ndarray:
    """A thin outline of a mask (for the selection highlight)."""
    from scipy import ndimage

    solid = m > 0.5
    return (ndimage.binary_dilation(solid, iterations=width) & ~solid).astype(np.float32)
