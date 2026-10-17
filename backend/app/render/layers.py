"""Static render layers built from the PDF once per structure.

- ``artwork``: RGBA of the printed design only (dieline/annotation/finish separations suppressed
  in a working copy; the original PDF is untouched), rendered by PyMuPDF from vector data.
- ``silhouette``: anti-aliased coverage of the board: inside the outer cut line, minus the
  openings (closed cut loops inside it: windows, holes, slots).
- ``crease``: crease line coverage, used for a subtle physical fold mark.

Pixel framing: the package bounding box plus ``margin`` percent on every side.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass

import numpy as np
import pymupdf
from scipy import ndimage

from app.pdf.geometry import Raster, cut_silhouette
from app.pdf.rewrite import artwork_only_pdf
from app.spec.models import Specification

SUPERSAMPLE = 2
log = logging.getLogger(__name__)


@dataclass
class Layers:
    width: int
    height: int
    scale: float  # px per pt
    origin: tuple[float, float]  # page-space point at pixel (0, 0)
    artwork: np.ndarray  # HxWx4 float32, straight alpha
    silhouette: np.ndarray  # HxW float32
    crease: np.ndarray  # HxW float32
    mm_per_pt: float = 25.4 / 72  # physical scale (Figma exports are not 1pt = 1/72in)

    @property
    def px_per_mm(self) -> float:
        return self.scale / self.mm_per_pt


def structure_key(spec: Specification) -> str:
    payload = [(p.source_ref, p.cls) for p in spec.paths]
    return hashlib.sha1(json.dumps(payload).encode()).hexdigest()[:12]


def _closed_polys(spec: Specification, cls: str) -> list[list[tuple[float, float]]]:
    out = []
    for p in spec.paths:
        if p.cls != cls:
            continue
        for pl, closed in zip(p.polylines, p.closed + [False] * len(p.polylines), strict=False):
            out.append(pl + [pl[0]] if closed and pl and pl[0] != pl[-1] else pl)
    return out


def package_bbox(spec: Specification) -> tuple[float, float, float, float]:
    pts = [pt for pl in _closed_polys(spec, "cut") for pt in pl]
    if not pts:
        return (0, 0, spec.page.width_pt, spec.page.height_pt)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def frame(
    spec: Specification, long_edge_px: int, margin_pct: int
) -> tuple[Raster, tuple[float, float, float, float]]:
    x0, y0, x1, y1 = package_bbox(spec)
    pad = max(x1 - x0, y1 - y0) * margin_pct / 100
    w_pt, h_pt = (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad
    scale = long_edge_px / max(w_pt, h_pt)
    # Snap the frame to the device pixel grid so the PDF renders 1:1 with no resampling:
    # MuPDF places pixel (0, 0) at floor(x * scale), so the origin must be a whole pixel.
    ox = math.floor((x0 - pad) * scale) / scale
    oy = math.floor((y0 - pad) * scale) / scale
    w_px = math.ceil(((x1 + pad) - ox) * scale)
    h_px = math.ceil(((y1 + pad) - oy) * scale)
    # Snapping can add a pixel; trim it from the margin so exports are exactly the asked size.
    w_px, h_px = min(w_px, long_edge_px), min(h_px, long_edge_px)
    crop = (ox, oy, ox + w_px / scale, oy + h_px / scale)
    return Raster(w_px / scale, h_px / scale, scale, origin=(ox, oy)), crop


def _coverage(fn, raster: Raster) -> np.ndarray:
    """Rasterize at SUPERSAMPLE x and box-filter down for anti-aliased coverage."""
    big = Raster(
        raster.w / raster.scale, raster.h / raster.scale, raster.scale * SUPERSAMPLE, raster.origin
    )
    m = fn(big).astype(np.float32)
    h, w = raster.h * SUPERSAMPLE, raster.w * SUPERSAMPLE
    m = m[:h, :w]
    if m.shape != (h, w):
        m = np.pad(m, ((0, h - m.shape[0]), (0, w - m.shape[1])))
    return m.reshape(raster.h, SUPERSAMPLE, raster.w, SUPERSAMPLE).mean(axis=(1, 3))


def build_layers(
    source: bytes,
    spec: Specification,
    long_edge_px: int,
    margin_pct: int,
    artwork_pdf: bytes | None = None,
) -> Layers:
    raster, crop = frame(spec, long_edge_px, margin_pct)
    page_index = spec.page.index

    if artwork_pdf is None:
        artwork_pdf = make_artwork_pdf(source, spec)
    doc = pymupdf.open(stream=artwork_pdf, filetype="pdf")
    page = doc[0]
    clip = pymupdf.Rect(*crop)
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(raster.scale, raster.scale), clip=clip, alpha=True, annots=False
    )
    art = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    # The frame can extend past the page (margin around a carton near the edge); PyMuPDF
    # clamps the clip to the page, so place the render at the pixel origin it reports.
    dx = pix.x - round(raster.origin[0] * raster.scale)
    dy = pix.y - round(raster.origin[1] * raster.scale)
    art = _exact(art, raster.h, raster.w, dy, dx).astype(np.float32) / 255.0
    rgb = art[..., :3]
    a = art[..., 3:4]
    # PyMuPDF returns premultiplied color with alpha; un-premultiply.
    art = np.concatenate([np.where(a > 0, rgb / np.maximum(a, 1e-6), 0), a], axis=-1)
    art = np.clip(art, 0, 1)

    cut = _closed_polys(spec, "cut")

    def sil_fn(r: Raster):
        return board(r, cut)

    silhouette = _coverage(sil_fn, raster) if cut else np.ones((raster.h, raster.w), np.float32)
    art[..., 3] *= silhouette  # clip artwork (and its bleed) to the cut

    creases = _closed_polys(spec, "crease")
    crease = (
        _coverage(lambda r: r.lines(creases, width_px=max(1.0, r.scale * 0.7)), raster)
        if creases
        else np.zeros((raster.h, raster.w), np.float32)
    ) * silhouette

    del page_index
    return Layers(
        raster.w,
        raster.h,
        raster.scale,
        raster.origin,
        art,
        silhouette,
        crease,
        mm_per_pt=spec.scale.mm_per_pt,
    )


def make_artwork_pdf(source: bytes, spec: Specification) -> bytes:
    from app.pdf import rules

    # One PDF operator can hold several pieces (a whole dieline in one shape). Suppress it when
    # most of its pieces are non-printing; a rare mixed operator is logged, never half-drawn.
    votes: dict[str, list[int]] = {}
    for p in spec.paths:
        if "#" in p.source_ref:
            v = votes.setdefault(p.source_ref, [0, 0])
            v[0 if p.cls != "artwork" else 1] += 1
    hidden_refs = {ref for ref, (tech, art) in votes.items() if tech > art}
    for ref, (tech, art) in votes.items():
        if tech and art:
            log.info("operator %s mixes %d technical and %d printed pieces", ref, tech, art)
    hidden_layers = {
        layer.name
        for layer in spec.layers
        if layer.role in ("cut", "crease", "annotation", "bleed", "finish")
        or rules.match(layer.name) in ("cut", "crease", "annotation", "bleed", "finish")
    }
    return artwork_only_pdf(source, spec.page.index, hidden_refs, hidden_layers)


def board(r: Raster, cut: list[list[tuple[float, float]]]) -> np.ndarray:
    """The board: the area the outer cut line encloses, minus every closed cut loop that lies
    wholly inside it (an opening: the background shows through). ``cut_silhouette`` alone
    fills such loops in, since it only floods from the image border."""
    sil = cut_silhouette(r, cut)
    total = int(sil.sum())
    if not total:
        return sil
    margin = max(1, math.ceil(2 * r.scale))  # 2 pt: a loop touching the outline is not inside
    for pl in cut:
        if len(pl) < 4 or math.dist(pl[0], pl[-1]) > 1.0:
            continue  # not closed
        hole = r.fill([pl])
        n = int(hole.sum())
        # The outline's own contour (or the inner contour of an outlined stroke) encloses
        # nearly all of the board; an opening is a small part of it, surrounded by board.
        if n == 0 or n > 0.5 * total:
            continue
        ring = ndimage.binary_dilation(hole, iterations=margin) & ~hole
        if sil[ring].all():
            sil &= ~hole
    return sil


def _exact(img: np.ndarray, h: int, w: int, dy: int = 0, dx: int = 0) -> np.ndarray:
    """Paste the render at (dy, dx) in an h x w frame. Never resample: artwork pixels must be
    the PDF render's own."""
    out = np.zeros((h, w, img.shape[2]), img.dtype)
    y0, x0 = max(0, dy), max(0, dx)
    sy, sx = max(0, -dy), max(0, -dx)
    hh = min(h - y0, img.shape[0] - sy)
    ww = min(w - x0, img.shape[1] - sx)
    if hh > 0 and ww > 0:
        out[y0 : y0 + hh, x0 : x0 + ww] = img[sy : sy + hh, sx : sx + ww]
    return out
