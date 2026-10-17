"""Structural dieline classification.

Classification works on *line pieces* (one per subpath of a line-like path), because design
tools often put the whole dieline — outer cut and inner folds — into one path of one color.
Figma, for example, exports every line as a thin filled shape (an "outlined stroke"), so a
line-like path is either a thin stroke or a fill whose shapes are all thin.

Order of evidence, strongest first:
1. Spot-color and layer (OCG) names that match ``rules.RULES``.
2. Topology: the connected network of line pieces that encloses the largest area is the
   dieline. Pieces on its outer boundary are cuts; pieces inside it are creases. Line pieces
   outside it are technical marks (dimensions); stray pieces inside it need a human.

Printed artwork is never suppressed on a guess: a thin red line inside the carton that is not
part of the dieline stays ``unresolved`` (suggested: artwork).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from app.pdf import rules
from app.pdf.content import PaintedPath
from app.pdf.geometry import Polyline, Raster, cut_silhouette, flatten, outside_region, sample_along
from app.spec.models import PathClass, PathStatus, Provenance

MAX_LINE_PT = 2.5  # thicker strokes/shapes are printed artwork, not technical lines
AUTO_THRESHOLD = 0.7  # below this, a path needs user confirmation


@dataclass
class Classified:
    """One classified piece: a whole painted path, or one subpath of a line-like path."""

    path: PaintedPath
    polylines: list[Polyline]
    cls: PathClass
    status: PathStatus
    confidence: float
    provenance: Provenance
    reason: str
    suggested: PathClass | None = None
    named_by: str | None = None  # the spot/layer name that decided it
    sub: int | None = None  # subpath index when the path was split into pieces
    line_like: bool = False
    width: float = 1.0  # line thickness in points
    closed_loop: bool = False  # a closed ring enclosing an area (window, hole)
    from_fill: bool = False  # an outlined stroke (thin filled shape), e.g. Figma exports

    @property
    def source_ref(self) -> str:
        return f"{self.path.stream}#{self.path.op_index}"

    @property
    def id(self) -> str:
        return f"p{self.path.index}" if self.sub is None else f"p{self.path.index}.{self.sub}"

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        pts = [p for pl in self.polylines for p in pl]
        if not pts:
            return self.path.bbox
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))


@dataclass
class Classification:
    items: list[Classified]
    cut_evidence: str  # "named" | "geometry" | "none"
    cut_closed: bool
    hidden_layers: set[str] = field(default_factory=set)


def _name_evidence(p: PaintedPath) -> tuple[PathClass, str] | None:
    for cs in (p.stroke_cs if p.stroke else None, p.fill_cs if p.fill else None):
        if cs and cs.startswith("Separation:"):
            spot = cs.split(":", 1)[1]
            cls = rules.match(spot)
            if cls:
                return cls, f"별색 '{spot}'"
    for layer in reversed(p.ocgs):
        cls = rules.match(layer)
        if cls:
            return cls, f"레이어 '{layer}'"
    for layer in p.design_layers:
        cls = rules.match(layer)
        if cls:
            return cls, f"Figma 레이어 '{layer}'"
    return None


# ---- line-like detection ---------------------------------------------------------------


def _area(pl: Polyline) -> float:
    return (
        abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pl, pl[1:] + pl[:1], strict=True)))
        / 2
    )


def _perimeter(pl: Polyline) -> float:
    return sum(math.dist(a, b) for a, b in zip(pl, pl[1:] + pl[:1], strict=True))


def _thin_width(pl: Polyline) -> float:
    """Thickness of a closed shape, 2·area/perimeter (exact for long thin rectangles)."""
    per = _perimeter(pl)
    return 0.0 if per == 0 else 2 * _area(pl) / per


def _ring_width(polys: list[Polyline]) -> float | None:
    """Thickness of an even-odd filled region (e.g. an outlined closed stroke: outer + inner contour)."""
    pts = [p for pl in polys for p in pl]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    w, h = max(xs) - min(xs) + 4, max(ys) - min(ys) + 4
    scale = min(4.0, 3000 / max(w, h))
    r = Raster(w, h, scale, origin=(min(xs) - 2, min(ys) - 2))
    region = np.zeros((r.h, r.w), bool)
    for pl in polys:
        region ^= r.fill([pl])
    if not region.any():
        return 0.0
    half = np.percentile(ndimage.distance_transform_edt(region)[region], 95)
    return 2 * half / scale


def _centerline(pl: Polyline, width: float) -> tuple[Polyline, bool]:
    """Straight thin shape -> its center segment; anything else stays the closed outline."""
    pts = np.array(pl, float)
    if len(pts) < 3:
        return pl, False
    mean = pts.mean(axis=0)
    _, vecs = np.linalg.eigh(np.cov((pts - mean).T))
    major, minor = vecs[:, 1], vecs[:, 0]
    if np.abs((pts - mean) @ minor).max() <= max(0.75, width):
        proj = (pts - mean) @ major
        a, b = mean + major * proj.min(), mean + major * proj.max()
        return [(round(a[0], 2), round(a[1], 2)), (round(b[0], 2), round(b[1], 2))], False
    closed = pl if pl[0] == pl[-1] else pl + [pl[0]]
    return closed, True


def _pieces(p: PaintedPath, polys: list[Polyline]) -> list[tuple[Polyline, float, bool]] | None:
    """Split a line-like path into (polyline, width, closed_loop) pieces, or None if it isn't one."""
    if p.stroke_only and p.line_width <= MAX_LINE_PT:
        return [
            (pl, p.line_width, closed and _area(pl) >= 100)
            for pl, closed in zip(polys, p.closed, strict=False)
        ]
    if not p.fill or p.stroke:
        return None
    widths = [_thin_width(pl) for pl in polys]
    if all(w <= MAX_LINE_PT for w in widths):
        out = []
        for pl, w in zip(polys, widths, strict=True):
            length = _perimeter(pl) / 2
            if w > 0 and length < 3 * w:
                return None  # a small dot or square, not a line
            line, loop = _centerline(pl, w)
            out.append((line, max(w, 0.3), loop and _area(pl) >= 100))
        return out
    if len(polys) <= 4:  # outlined closed shape: outer + inner contour of one ring
        w = _ring_width(polys)
        if w is not None and w <= MAX_LINE_PT:
            return [(pl if pl[0] == pl[-1] else pl + [pl[0]], max(w, 0.3), True) for pl in polys]
    return None


# ---- topology --------------------------------------------------------------------------


@dataclass
class Network:
    pieces: set[int]  # ids of pieces in the dieline network
    outside: np.ndarray  # pixels outside the dieline
    labels: dict[int, int]  # piece id -> raster component


def _sample(c: Classified, raster: Raster) -> list[tuple[float, float]]:
    return [raster.px(q) for pl in c.polylines for q in sample_along(pl, 2.0)]


def _find_network(pieces: list[Classified], raster: Raster) -> Network | None:
    """The connected group of line pieces that encloses the largest area."""
    if not pieces:
        return None
    ink = raster.lines(
        [pl for c in pieces for pl in c.polylines], width_px=max(2.0, 1.2 * raster.scale)
    )
    # Dilate only to decide connectivity (outlined joins leave hairline gaps); inside/outside
    # uses the undilated lines so narrow slits between flaps stay open.
    labels, n = ndimage.label(ndimage.binary_dilation(ink, iterations=1))
    piece_label: dict[int, int] = {}
    for c in pieces:
        hits = [
            labels[int(y), int(x)]
            for x, y in _sample(c, raster)
            if 0 <= int(y) < raster.h and 0 <= int(x) < raster.w
        ]
        hits = [h for h in hits if h]
        piece_label[id(c)] = max(set(hits), key=hits.count) if hits else 0

    best, best_area, best_outside = 0, 0.0, None
    for k, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        ys, xs = sl
        if (ys.stop - ys.start) * (xs.stop - xs.start) < 0.01 * labels.size:
            continue  # too small to enclose a carton
        walls = (labels == k) & ink
        outside = outside_region(walls)
        enclosed = (~outside).sum() - walls.sum()
        if enclosed > best_area:
            best, best_area, best_outside = k, enclosed, outside
    if best_outside is None or best_area < 0.01 * labels.size:
        return None
    members = {id(c) for c in pieces if piece_label[id(c)] == best}
    return Network(members, best_outside, piece_label)


def _frac(pts, mask: np.ndarray, raster: Raster) -> float:
    if not pts:
        return 0.0
    hit = 0
    for x, y in pts:
        xi, yi = int(x), int(y)
        if 0 <= yi < raster.h and 0 <= xi < raster.w and mask[yi, xi]:
            hit += 1
    return hit / len(pts)


def _looks_dashed(path: PaintedPath, pieces: list[Classified]) -> bool:
    """Stroke dash pattern, or outlined dashes: 4+ short, aligned bars of similar length."""
    if path.dashed:
        return True
    mine = [c for c in pieces if c.path is path]
    bars = [c.polylines[0] for c in mine if _straight(c)]
    # Outlined text glyphs are curved outlines or a few unrelated bars; dashes are not.
    if len(mine) < 4 or len(bars) < 0.8 * len(mine):
        return False
    lengths = np.array([math.dist(a, b) for a, b in bars])
    if np.median(lengths) > 12 or lengths.std() > 0.5 * lengths.mean():
        return False
    angles = np.array([math.atan2(b[1] - a[1], b[0] - a[0]) % math.pi for a, b in bars])
    spread = np.abs(np.angle(np.exp(2j * (angles - angles[0])))).max() / 2
    if spread >= math.radians(8):
        return False
    # ...and the bars sit on one line.
    centers = np.array([((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in bars])
    direction = np.array([math.cos(angles[0]), math.sin(angles[0])])
    normal = np.array([-direction[1], direction[0]])
    offsets = (centers - centers.mean(axis=0)) @ normal
    if np.abs(offsets).max() > 2.0:
        return False
    # ...spread out along that line (a glyph's strokes overlap; dashes leave gaps).
    along = np.array([p @ direction for a, b in bars for p in (np.array(a), np.array(b))])
    return bool(along.max() - along.min() >= 3 * np.median(lengths))


def _straight(c: Classified) -> bool:
    return len(c.polylines) == 1 and len(c.polylines[0]) == 2


def _split_by_topology(
    pieces: list[Classified], raster: Raster, *, inner_reason: str, named: bool
) -> tuple[Network | None, np.ndarray | None]:
    """Outer boundary -> cut, inside -> crease. Returns the network and silhouette."""
    net = _find_network(pieces, raster)
    if net is None:
        return None, None
    near_out = ndimage.binary_dilation(net.outside, iterations=3)
    silhouette = ~net.outside
    grown = ndimage.binary_dilation(silhouette, iterations=2)
    network_paths = {c.path.index for c in pieces if id(c) in net.pieces}
    provenance = "extracted"
    for c in pieces:
        pts = _sample(c, raster)
        if id(c) in net.pieces:
            if _frac(pts, near_out, raster) >= 0.6:
                _set(
                    c,
                    "cut",
                    "auto",
                    0.97 if named else 0.8,
                    c.reason if named else "외곽선 → 칼선으로 판단",
                    provenance,
                )
            else:
                _set(c, "crease", "auto", 0.9 if named else 0.75, inner_reason, provenance)
        elif _frac(pts, grown, raster) < 0.5:
            if c.from_fill and not (_straight(c) or _looks_dashed(c.path, pieces)):
                _set(c, "artwork", "auto", 0.85, "칼선 바깥의 채움 도형", provenance)
            else:
                _set(
                    c,
                    "annotation",
                    "auto",
                    0.75,
                    "칼선 바깥의 기술 표시(치수 등)로 추정",
                    provenance,
                )
        elif c.path.index in network_paths or _looks_dashed(c.path, pieces):
            # Same compound shape as the dieline, or a dashed line inside it: a fold.
            _set(c, "crease", "auto", 0.7, "칼선 안쪽 선 → 접는선으로 추정", provenance)
        elif c.from_fill:
            # A thin filled shape that isn't part of the dieline is printed (outlined text, rules).
            _set(
                c, "artwork", "auto", 0.85, "칼선과 연결되지 않은 채움 도형 → 인쇄 요소", provenance
            )
        elif c.closed_loop:
            _unresolved(c, "cut", "안쪽 칼선(창·구멍)일 수 있음")
        else:
            _unresolved(c, "artwork", "외곽과 연결되지 않아 인쇄 요소일 가능성")
    return net, silhouette


# ---- main ------------------------------------------------------------------------------


def classify(paths: list[PaintedPath], page_w: float, page_h: float) -> Classification:
    items: list[Classified] = []
    for p in paths:
        polys = [flatten(sp) for sp in p.subpaths]
        named = _name_evidence(p)
        split = _pieces(p, polys)
        if split is None:
            cls, why = named if named else ("artwork", "인쇄 요소 (채움 또는 굵은 선)")
            items.append(
                Classified(
                    p,
                    polys,
                    cls,
                    "auto",
                    0.97 if named else 0.9,
                    "extracted",
                    why,
                    cls,
                    named_by=why if named else None,
                )
            )
            continue
        for k, (pl, width, loop) in enumerate(split):
            cls, why = named if named else ("artwork", "인쇄 요소 (채움 또는 굵은 선)")
            items.append(
                Classified(
                    p,
                    [pl],
                    cls,
                    "auto",
                    0.97 if named else 0.9,
                    "extracted",
                    why,
                    cls,
                    named_by=why if named else None,
                    sub=k if len(split) > 1 else None,
                    line_like=True,
                    from_fill=not p.stroke,
                    width=width,
                    closed_loop=loop,
                )
            )

    scale = min(2.0, 2400 / max(page_w, page_h))
    raster = Raster(page_w, page_h, scale)
    named_cut = [c for c in items if c.named_by and c.cls == "cut"]
    named_crease = any(c.named_by and c.cls == "crease" for c in items)
    unnamed_lines = [c for c in items if not c.named_by and c.line_like]

    if named_cut:
        silhouette = None
        if not named_crease and all(c.line_like for c in named_cut):
            # One separation holds the whole dieline: split it by topology.
            _, silhouette = _split_by_topology(
                named_cut,
                raster,
                inner_reason="칼선 분판 안쪽 선 → 접는선으로 판단",
                named=True,
            )
        if silhouette is None:
            silhouette = cut_silhouette(raster, [pl for c in named_cut for pl in c.polylines])
        grown = ndimage.binary_dilation(silhouette, iterations=2)
        for c in unnamed_lines:
            if _frac(_sample(c, raster), grown, raster) <= 0.5:
                _set(c, "annotation", "auto", 0.75, "칼선 바깥의 기술 표시로 추정")
            elif _looks_dashed(c.path, unnamed_lines):
                _set(c, "crease", "auto", 0.72, "칼선 안쪽 점선 → 접는선으로 추정")
            else:
                _set(c, "artwork", "auto", 0.85, "칼선 분판이 따로 있어 인쇄 요소로 판단")
        closed = silhouette.mean() > 0.01
        return Classification(items, "named", bool(closed), _hidden_layers(items))

    net, _ = _split_by_topology(
        unnamed_lines, raster, inner_reason="외곽선 안쪽 선 → 접는선으로 판단", named=False
    )
    if net is None:
        # No enclosing network: leave every line as printed artwork (cut is "missing").
        for c in unnamed_lines:
            _set(c, "artwork", "auto", 0.9, "인쇄 요소 (채움 또는 굵은 선)")
        return Classification(items, "none", False, _hidden_layers(items))
    return Classification(items, "geometry", True, _hidden_layers(items))


def _set(
    c: Classified,
    cls: PathClass,
    status: PathStatus,
    conf: float,
    reason: str,
    provenance: Provenance = "extracted",
) -> None:
    c.cls, c.status, c.confidence, c.reason, c.provenance = cls, status, conf, reason, provenance
    c.suggested = cls


def _unresolved(c: Classified, suggested: PathClass, reason: str) -> None:
    # Keep it printing until a human decides (never remove artwork on a guess).
    c.cls, c.status, c.confidence, c.reason, c.suggested = (
        "artwork",
        "unresolved",
        0.5,
        reason,
        suggested,
    )


def _hidden_layers(items: list[Classified]) -> set[str]:
    """Layers whose *name* marks them as non-printing (dieline, info...): hide all their content."""
    hidden: set[str] = set()
    for c in items:
        for layer in c.path.ocgs:
            cls = rules.match(layer)
            if cls in ("cut", "crease", "annotation", "bleed", "finish"):
                hidden.add(layer)
    return hidden
