"""The dieline as a structure: panels (polygons, sizes), the fold edges that join them (a panel
adjacency graph), the cut contacts that separate them, and what could not be resolved.

Only the confirmed classification of the structural review is used (``spec.paths`` with
``cls`` cut / crease); line colour is never read. A fold edge exists only where a crease line
separates two different panels; a cut never becomes a hinge, even between two panels. Lines
that do not fit (a crease on the outer edge, a crease inside one panel, an unresolved line)
become issues instead of guesses.

Panels are the regions between cut and crease lines inside the board (openings cut out), the
same rule as ``pdf.analyze.find_panels``, matched to the spec's panels by their boxes, so ids
and names stay those of the structural review.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
from scipy import ndimage

from app.pdf.geometry import Raster, simplify_loop, trace_loops
from app.render.layers import _closed_polys, board, package_bbox
from app.spec.models import Specification

PX_PER_MM = 8.0  # labelling resolution
MAX_EDGE = 6000
LINE_MM = 0.35  # drawn width of a line barrier
MIN_SEGMENT_PT = 1.0  # shorter structural pieces are joints, not lines
MIN_RUN_MM = 1.5  # shorter fold or contact runs are corner noise
AXIS_TOL_DEG = 1.0  # horizontal / vertical within this


@dataclass
class PanelNode:
    id: str
    name: str
    name_provenance: str
    bbox: tuple[float, float, float, float]  # page units
    polygon: list[list[tuple[float, float]]]  # outline (and holes), page units, traced
    area_mm2: float
    width_mm: float
    height_mm: float


@dataclass
class FoldEdge:
    id: str
    a: str  # panel ids; the axis runs p0 -> p1
    b: str
    p0: tuple[float, float]  # page units, on the crease line itself
    p1: tuple[float, float]
    length_mm: float
    orientation: str  # horizontal | vertical | diagonal
    side_a: int  # +1 / -1: which side of p0 -> p1 panel a lies on (left normal = +1)
    paths: list[str]  # crease path ids


@dataclass
class CutContact:
    a: str
    b: str  # same as a for a slit inside one panel
    length_mm: float
    paths: list[str]


@dataclass
class Issue:
    level: str  # error | warning
    code: str
    message: str  # Korean
    paths: list[str] = field(default_factory=list)
    panels: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


@dataclass
class Topology:
    panels: list[PanelNode]
    folds: list[FoldEdge]
    cuts: list[CutContact]
    issues: list[Issue]
    mm_per_unit: float
    components: list[list[str]]  # panels connected by folds

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def neighbours(self, pid: str) -> list[tuple[str, FoldEdge]]:
        out = []
        for e in self.folds:
            if e.a == pid:
                out.append((e.b, e))
            elif e.b == pid:
                out.append((e.a, e))
        return out

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "mm_per_unit": self.mm_per_unit,
            "panels": [asdict(p) for p in self.panels],
            "folds": [asdict(e) for e in self.folds],
            "cuts": [asdict(c) for c in self.cuts],
            "components": self.components,
            "issues": [asdict(i) for i in self.issues],
        }


def _raster(spec: Specification) -> Raster:
    x0, y0, x1, y1 = package_bbox(spec)
    pad = 0.02 * max(x1 - x0, y1 - y0) + 2
    mm = spec.scale.mm_per_pt
    scale = min(PX_PER_MM * mm, MAX_EDGE / max(x1 - x0 + 2 * pad, y1 - y0 + 2 * pad))
    return Raster(x1 - x0 + 2 * pad, y1 - y0 + 2 * pad, scale, origin=(x0 - pad, y0 - pad))


def _segments(spec: Specification, cls: str) -> list[tuple[str, tuple, tuple]]:
    out = []
    for p in spec.paths:
        if p.cls != cls:
            continue
        for pl in p.polylines:
            for q0, q1 in zip(pl, pl[1:], strict=False):
                if math.dist(q0, q1) >= MIN_SEGMENT_PT:
                    out.append((p.id, tuple(q0), tuple(q1)))
    return out


def _orientation(p0, p1) -> str:
    ang = math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0])) % 180
    if min(ang, 180 - ang) <= AXIS_TOL_DEG:
        return "horizontal"
    if abs(ang - 90) <= AXIS_TOL_DEG:
        return "vertical"
    return "diagonal"


def _probe(
    labels: np.ndarray, r: Raster, seg, step_px: float, off_px: float
) -> list[tuple[float, int, int]]:
    """Samples along a segment: (t in 0..1, label on the left, label on the right)."""
    _, q0, q1 = seg
    (x0, y0), (x1, y1) = r.px(q0), r.px(q1)
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 1:
        return []
    dx, dy = (x1 - x0) / length, (y1 - y0) / length
    nx, ny = dy, -dx  # left normal in image coordinates
    n = max(2, int(length / step_px))
    h, w = labels.shape
    out = []
    margin = (off_px + 2) / length  # stay clear of the joints at both ends
    for t in np.linspace(0, 1, n + 1):
        if t < margin or t > 1 - margin:
            continue
        px, py = x0 + dx * length * t, y0 + dy * length * t
        lx, ly = int(px + nx * off_px), int(py + ny * off_px)
        rx, ry = int(px - nx * off_px), int(py - ny * off_px)
        if not (0 <= ly < h and 0 <= lx < w and 0 <= ry < h and 0 <= rx < w):
            continue
        out.append((float(t), int(labels[ly, lx]), int(labels[ry, rx])))
    return out


def _runs(samples, key):
    """Consecutive samples with the same key -> (key, t0, t1, count). A run reaching the first
    or last sample extends to the segment's end (the probe skips the joints there); between two
    runs the boundary is half way between their samples."""
    runs = []
    for i, (t, la, lb) in enumerate(samples):
        k = key(la, lb)
        if runs and runs[-1][0] == k:
            runs[-1][2] = t
            runs[-1][3] += 1
            runs[-1][5] = i
        else:
            runs.append([k, t, t, 1, i, i])
    last = len(samples) - 1
    out = []
    for k, t0, t1, cnt, i0, i1 in runs:
        t0 = 0.0 if i0 == 0 else (samples[i0 - 1][0] + t0) / 2
        t1 = 1.0 if i1 == last else (t1 + samples[i1 + 1][0]) / 2
        out.append((k, t0, t1, cnt))
    return out


def analyze(spec: Specification) -> Topology:
    issues: list[Issue] = []
    mm = spec.scale.mm_per_pt
    if not spec.structure_confirmed:
        issues.append(
            Issue(
                "error", "STRUCTURE_UNCONFIRMED", "구조 확인(칼선·접는 선 검토)을 먼저 마쳐주세요."
            )
        )
    unresolved = [
        p.id
        for p in spec.paths
        if p.status == "unresolved"
        and (p.cls in ("cut", "crease") or p.suggested_cls in ("cut", "crease"))
    ]
    if unresolved:
        issues.append(
            Issue(
                "error",
                "LINES_UNRESOLVED",
                f"칼선인지 접는 선인지 확정되지 않은 선이 {len(unresolved)}개 있습니다.",
                paths=unresolved,
            )
        )
    cut_polys = _closed_polys(spec, "cut")
    r = _raster(spec)
    line_px = max(2.0, LINE_MM / mm * r.scale)
    if not cut_polys:
        issues.append(Issue("error", "CUT_MISSING", "칼선(외곽선)이 없습니다."))
        return Topology([], [], [], issues, mm, [])
    inside = board(r, cut_polys)
    walls = r.lines(
        [pl for p in spec.paths if p.cls in ("cut", "crease") for pl in p.polylines], line_px
    )
    labels, n = ndimage.label(inside & ~walls)
    total = int((labels > 0).sum())
    areas = ndimage.sum_labels(np.ones_like(labels), labels, index=np.arange(1, n + 1))
    keep = {i + 1 for i, a in enumerate(areas) if a >= 0.005 * total}
    labels[~np.isin(labels, list(keep))] = 0

    # Components -> the spec's panels (by box overlap), so ids and names stay the review's.
    boxes = {}
    for lab, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None or lab not in keep:
            continue
        ys, xs = sl
        ox, oy = r.origin
        boxes[lab] = (
            ox + xs.start / r.scale,
            oy + ys.start / r.scale,
            ox + xs.stop / r.scale,
            oy + ys.stop / r.scale,
        )

    def iou(a, b):
        ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        inter = ix * iy
        ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
        return inter / ua if ua > 0 else 0.0

    lab_of: dict[int, str] = {}
    used = set()
    for p in spec.panels:
        best = max(boxes, key=lambda lab: iou(boxes[lab], p.bbox), default=None)
        if best is None or iou(boxes[best], p.bbox) < 0.6 or best in used:
            issues.append(
                Issue(
                    "error",
                    "PANEL_UNMATCHED",
                    f"'{p.name}' 패널의 영역을 다시 찾지 못했습니다.",
                    panels=[p.id],
                )
            )
            continue
        used.add(best)
        lab_of[best] = p.id
    for lab in boxes:
        if lab not in lab_of:
            lab_of[lab] = f"region{lab}"
    unnamed = [p for p in lab_of.values() if p.startswith("region")]
    if unnamed:
        issues.append(
            Issue(
                "warning",
                "REGION_UNNAMED",
                f"구조 검토에 없는 영역이 {len(unnamed)}개 있습니다.",
                panels=unnamed,
            )
        )

    by_id = {p.id: p for p in spec.panels}
    nodes = []
    for lab, pid in lab_of.items():
        m = labels == lab
        # The region stops at the line barriers: grow it back by half a line so the outline
        # sits on the lines themselves.
        grown = ndimage.binary_dilation(m, iterations=max(1, int(round(line_px / 2))))
        polys = []
        for pts in trace_loops(grown):
            pts = simplify_loop(pts, 0.75)
            if len(pts) >= 3:
                polys.append(
                    [
                        (round(r.origin[0] + c / r.scale, 2), round(r.origin[1] + rr / r.scale, 2))
                        for rr, c in pts
                    ]
                )
        x0, y0, x1, y1 = boxes[lab]
        sp = by_id.get(pid)
        nodes.append(
            PanelNode(
                id=pid,
                name=sp.name if sp else pid,
                name_provenance=sp.name_provenance if sp else "extracted",
                bbox=tuple(round(v, 1) for v in boxes[lab]),
                polygon=polys,
                area_mm2=round(float(m.sum()) / r.scale**2 * mm * mm, 1),
                width_mm=round((x1 - x0) * mm, 1),
                height_mm=round((y1 - y0) * mm, 1),
            )
        )

    off = line_px / 2 + 2
    step = max(1.0, 0.5 / mm * r.scale)  # a sample every 0.5 mm
    min_run = MIN_RUN_MM / mm  # page units

    # Folds: crease runs with a different panel on each side.
    raw: dict[tuple, list] = {}
    for seg in _segments(spec, "crease"):
        pid_, q0, q1 = seg
        seglen = math.dist(q0, q1)
        for (la, lb), t0, t1, cnt in _runs(_probe(labels, r, seg, step, off), lambda a, b: (a, b)):
            if (t1 - t0) * seglen < min_run or cnt < 3:
                continue
            p0 = (q0[0] + (q1[0] - q0[0]) * t0, q0[1] + (q1[1] - q0[1]) * t0)
            p1 = (q0[0] + (q1[0] - q0[0]) * t1, q0[1] + (q1[1] - q0[1]) * t1)
            if la and lb and la != lb:
                a, b = lab_of[la], lab_of[lb]
                key = (min(a, b), max(a, b), _orientation(q0, q1))
                raw.setdefault(key, []).append((p0, p1, a, pid_))
            elif la and lb and la == lb:
                issues.append(
                    Issue(
                        "warning",
                        "CREASE_INSIDE_PANEL",
                        "패널 안에서 끝나는 접는 선이 있습니다 (경첩이 아님).",
                        paths=[pid_],
                        panels=[lab_of[la]],
                    )
                )
            elif la or lb:
                issues.append(
                    Issue(
                        "warning",
                        "CREASE_ON_OUTLINE",
                        "바깥 테두리에 접는 선이 있습니다. 칼선이어야 할 수 있어요.",
                        paths=[pid_],
                        panels=[lab_of[la or lb]],
                    )
                )
    folds = []
    for (a, b, orient), parts in sorted(raw.items()):
        # One fold per panel pair and direction. The axis is the line of its longest run; the
        # other runs only extend it, and one that is off that line (a stepped hinge) is reported.
        main = max(parts, key=lambda pt: math.dist(pt[0], pt[1]))
        p0 = np.array(main[0])
        d = np.array(main[1]) - p0
        d = d / (np.linalg.norm(d) or 1)
        nrm0 = np.array([d[1], -d[0]])
        pts = np.array([q for pt in parts for q in (pt[0], pt[1])])
        offsets = np.abs((pts - p0) @ nrm0) * mm
        if offsets.max() > 0.3:
            issues.append(
                Issue(
                    "warning",
                    "FOLD_NOT_COLLINEAR",
                    f"한 경첩의 접는 선이 {offsets.max():.1f}mm 어긋난 두 줄로 그려져 있습니다. "
                    "가장 긴 줄을 경첩으로 씁니다.",
                    paths=sorted({pt[3] for pt in parts}),
                    panels=[a, b],
                    detail={"offset_mm": round(float(offsets.max()), 2), "axis_path": main[3]},
                )
            )
        t = (pts - p0) @ d
        lo, hi = p0 + d * t.min(), p0 + d * t.max()
        # Which side panel ``a`` is on: left normal of lo -> hi in page coordinates (y down).
        mid = (lo + hi) / 2
        nrm = np.array([d[1], -d[0]])
        side = 0
        for la_off in (+1, -1):
            q = mid + nrm * la_off * (off + 1) / r.scale
            x, y = r.px(tuple(q))
            if 0 <= int(y) < labels.shape[0] and 0 <= int(x) < labels.shape[1]:
                if lab_of.get(int(labels[int(y), int(x)])) == a:
                    side = la_off
        folds.append(
            FoldEdge(
                id=f"fold{len(folds) + 1}",
                a=a,
                b=b,
                p0=(round(float(lo[0]), 2), round(float(lo[1]), 2)),
                p1=(round(float(hi[0]), 2), round(float(hi[1]), 2)),
                length_mm=round(float(np.linalg.norm(hi - lo)) * mm, 1),
                orientation=orient,
                side_a=side,
                paths=sorted({pt[3] for pt in parts}),
            )
        )

    # Cuts between panels: contacts that are never hinges.
    contacts: dict[tuple, list] = {}
    for seg in _segments(spec, "cut"):
        pid_, q0, q1 = seg
        seglen = math.dist(q0, q1)
        for (la, lb), t0, t1, cnt in _runs(_probe(labels, r, seg, step, off), lambda a, b: (a, b)):
            if not (la and lb) or (t1 - t0) * seglen < min_run or cnt < 3:
                continue
            a, b = sorted((lab_of[la], lab_of[lb]))
            contacts.setdefault((a, b), []).append(((t1 - t0) * seglen * mm, pid_))
    cuts = [
        CutContact(a, b, round(sum(x[0] for x in v), 1), sorted({x[1] for x in v}))
        for (a, b), v in sorted(contacts.items())
    ]

    # Connectivity through folds only.
    ids = [nd.id for nd in nodes]
    parent = {i: i for i in ids}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for e in folds:
        parent[find(e.a)] = find(e.b)
    groups: dict[str, list[str]] = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)
    components = sorted(groups.values(), key=len, reverse=True)
    if len(components) > 1:
        issues.append(
            Issue(
                "error",
                "NET_DISCONNECTED",
                f"접는 선으로 이어지지 않은 패널 묶음이 {len(components)}개입니다 "
                "(칼선으로만 맞닿은 패널은 경첩이 될 수 없어요).",
                panels=[p for c in components[1:] for p in c],
                detail={"components": components},
            )
        )
    curved = [
        p.id
        for p in spec.paths
        if p.cls == "crease"
        and any(len(pl) > 2 for pl in p.polylines)
        and len(
            {
                _orientation(a, b)
                for pl in p.polylines
                for a, b in zip(pl, pl[1:], strict=False)
                if math.dist(a, b) >= MIN_SEGMENT_PT
            }
        )
        > 1
    ]
    if curved:
        issues.append(
            Issue(
                "warning",
                "CREASE_NOT_STRAIGHT",
                "곧지 않은 접는 선이 있습니다 (곡선 접기는 지원하지 않아요).",
                paths=curved,
            )
        )
    # De-duplicate repeated per-segment warnings.
    seen, uniq = set(), []
    for i in issues:
        k = (i.code, tuple(i.paths), tuple(i.panels))
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    return Topology(nodes, folds, cuts, uniq, mm, components)
