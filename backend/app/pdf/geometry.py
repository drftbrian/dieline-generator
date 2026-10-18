"""Path flattening and rasterization helpers shared by analysis and rendering."""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from app.pdf.content import Point, Segment

Polyline = list[tuple[float, float]]


def flatten(subpath: list[Segment], steps: int = 12) -> Polyline:
    pts: Polyline = []
    for seg in subpath:
        if not pts:
            pts.append(seg[1])
        if seg[0] == "L":
            pts.append(seg[2])
        else:
            p0, c1, c2, p1 = seg[1:]
            for i in range(1, steps + 1):
                t = i / steps
                u = 1 - t
                pts.append(
                    (
                        u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p1[0],
                        u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p1[1],
                    )
                )
    return [(round(x, 2), round(y, 2)) for x, y in pts]


class Raster:
    """Maps page points to pixels for a given scale and page-space crop origin."""

    def __init__(self, width_pt: float, height_pt: float, scale: float, origin: Point = (0, 0)):
        self.scale = scale
        self.origin = origin
        self.w = max(1, int(round(width_pt * scale)))
        self.h = max(1, int(round(height_pt * scale)))

    def px(self, p: Point) -> tuple[float, float]:
        return ((p[0] - self.origin[0]) * self.scale, (p[1] - self.origin[1]) * self.scale)

    def lines(self, polylines: list[Polyline], width_px: float = 1.0) -> np.ndarray:
        img = Image.new("L", (self.w, self.h), 0)
        draw = ImageDraw.Draw(img)
        for pl in polylines:
            if len(pl) >= 2:
                draw.line([self.px(p) for p in pl], fill=255, width=max(1, int(round(width_px))))
        return np.asarray(img) > 0

    def fill(self, polylines: list[Polyline]) -> np.ndarray:
        img = Image.new("L", (self.w, self.h), 0)
        draw = ImageDraw.Draw(img)
        for pl in polylines:
            if len(pl) >= 3:
                draw.polygon([self.px(p) for p in pl], fill=255)
        return np.asarray(img) > 0


def outside_region(walls: np.ndarray) -> np.ndarray:
    """Pixels reachable from the image border without crossing ``walls``."""
    free = ~walls
    labels, _ = ndimage.label(free)
    border = np.unique(np.concatenate([labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]]))
    border = border[border > 0]
    return np.isin(labels, border)


def cut_silhouette(
    raster: Raster, polylines: list[Polyline], line_pt: float = 0.5, gap_pt: float = 3.0
) -> np.ndarray:
    """Area enclosed by cut lines, tolerating hairline gaps between pieces.

    Design tools often leave gaps of a fraction of a point where outlined curve and line pieces
    meet. The walls are grown to bridge gaps up to ``gap_pt``, the enclosed area is found, then
    shrunk back by the same amount, so the silhouette edge stays on the drawn line.
    """
    walls = raster.lines(polylines, width_px=max(2.0, raster.scale * line_pt))
    r = max(1, math.ceil(gap_pt / 2 * raster.scale))
    enclosed = ~outside_region(ndimage.binary_dilation(walls, iterations=r))
    return ndimage.binary_erosion(enclosed, iterations=r, border_value=0) | (walls & enclosed)


def sample_along(pl: Polyline, spacing: float) -> list[Point]:
    out: list[Point] = []
    for (x0, y0), (x1, y1) in zip(pl, pl[1:], strict=False):
        n = max(1, int(np.hypot(x1 - x0, y1 - y0) / spacing))
        for i in range(n + 1):
            t = i / n
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return out


def to_hex(rgb: tuple[float, float, float] | None) -> str:
    if rgb is None:
        return "#000000"
    r, g, b = (max(0, min(255, int(round(c * 255)))) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def trace_loops(b: np.ndarray) -> list[np.ndarray]:
    """Closed outlines of a binary image along pixel edges, as (row, col) corner points. Holes
    come out as their own loops; filled even-odd they give back exactly the pixel set."""
    p = np.pad(b, 1)
    ins = p[1:-1, 1:-1]
    w1 = b.shape[1] + 1
    starts, ends = [], []
    for edge, (ra, ca, rb, cb) in (
        (ins & ~p[:-2, 1:-1], (0, 0, 0, 1)),  # top: left -> right
        (ins & ~p[1:-1, 2:], (0, 1, 1, 1)),  # right: down
        (ins & ~p[2:, 1:-1], (1, 1, 1, 0)),  # bottom: right -> left
        (ins & ~p[1:-1, :-2], (1, 0, 0, 0)),  # left: up
    ):
        r, c = np.nonzero(edge)
        starts.append((r + ra) * w1 + c + ca)
        ends.append((r + rb) * w1 + c + cb)
    s, e = np.concatenate(starts), np.concatenate(ends)
    nxt: dict[int, list[int]] = {}
    for a, z in zip(s.tolist(), e.tolist(), strict=True):
        nxt.setdefault(a, []).append(z)
    loops = []
    while nxt:
        v0 = next(iter(nxt))
        loop, v = [v0], v0
        while True:
            outs = nxt.get(v)
            if not outs:
                break
            z = outs.pop()
            if not outs:
                del nxt[v]
            if z == v0:
                break
            loop.append(z)
            v = z
        pts = np.array([(q // w1, q % w1) for q in loop], np.float64)
        loops.append(pts)
    return loops


def simplify_loop(pts: np.ndarray, tol: float) -> np.ndarray:
    """Ramer-Douglas-Peucker on a closed loop (staircases become their diagonals)."""
    if len(pts) <= 4:
        return pts
    far = int(np.argmax(((pts - pts[0]) ** 2).sum(1)))
    keep = np.zeros(len(pts), bool)
    keep[[0, far]] = True
    ring = np.vstack([pts, pts[:1]])
    stack = [(0, far), (far, len(pts))]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        a, b = ring[i], ring[j]
        seg = ring[i + 1 : j]
        d = b - a
        n = math.hypot(*d)
        if n == 0:
            dist = np.hypot(*(seg - a).T)
        else:
            dist = np.abs(d[0] * (seg[:, 1] - a[1]) - d[1] * (seg[:, 0] - a[0])) / n
        k = int(np.argmax(dist))
        if dist[k] > tol:
            m = i + 1 + k
            keep[m % len(pts)] = True
            stack += [(i, m), (m, j)]
    return pts[keep]
