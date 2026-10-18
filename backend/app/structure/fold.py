"""Fold a recognised carton net into 3D by rigid hinge rotations, deterministically.

The net lies in its own flat frame: millimetres, X right, Y up (the dieline's y flipped), the
printed (outside) face toward +Z. Folding is a tree over the topology's fold edges, rooted at a
W body panel: each child panel turns about its crease axis by that fold's angle, away from the
print side (toward -Z), so the print ends up outside. A panel's transform is its parent's
transform times its own hinge rotation, so every panel stays rigid and keeps its exact size;
nothing is placed by estimation.

Closed layers do not occupy one plane: panels that sit under others (dust flaps, the tuck flap,
the glue flap, the crash-lock flaps) are moved inward by board thickness, so the box renders
without z-fighting.

Fold states:
- **closed:** everything at its closed angle.
- **open_top / partially_open:** the top end only.

A crash-lock bottom (decision B1) is modelled only closed: its four flaps turn in and the glued
triangles lie flat on them. This is an approximation of the set-up carton, not a fold
sequence, and is reported as such.

Validation:
- **Tube closure:** the free edge of the last body panel meets the glue hinge.
- **Lid closure:** the lid's far edge meets the opposite W panel.
- **Containment:** no panel leaves the box.

Problems are returned, never hidden.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from app.spec.models import FLAT_LOOK
from app.structure.topology import FoldEdge, Topology

CLOSE_TOL_MM = 1.5  # closure residual allowed (die and drawing tolerance)
CONTAIN_TOL_MM = 2.0

STATES = ("closed", "open_top", "partially_open")
# Angles (degrees) of the top end per state: (lid, tuck, dust flaps).
TOP_ANGLES = {
    "closed": (90.0, 90.0, 90.0),
    "open_top": (-25.0, 0.0, -10.0),
    # Dust flaps stay up (slightly out) while the lid is half shut: at 45 / 45 they would pass
    # through each other (the intersection check catches it).
    "partially_open": (50.0, 20.0, -10.0),
}
PIERCE_TOL_MM = 1.5  # an edge must pass this far through a panel to count as an intersection


class FoldError(Exception):
    def __init__(self, code: str, message: str, reasons: list[str] | None = None):
        super().__init__(message)
        self.code, self.message, self.reasons = code, message, reasons or []


@dataclass
class FoldedPanel:
    id: str
    name: str
    role: str  # W | D | glue | lid | tuck | dust | bottom_W | bottom_D | lock_triangle | ...
    flat: list[np.ndarray]  # loops, Nx2 mm in the flat frame (X right, Y up)
    matrix: np.ndarray  # 4x4: flat frame (x, y, 0, 1) -> world (mm)
    layer: int

    def world(self) -> list[np.ndarray]:
        out = []
        for loop in self.flat:
            pts = np.c_[loop, np.zeros(len(loop)), np.ones(len(loop))]
            out.append((pts @ self.matrix.T)[:, :3])
        return out

    def normal(self) -> np.ndarray:
        """World normal of the printed (outside) face."""
        n = self.matrix[:3, :3] @ np.array([0.0, 0.0, 1.0])
        return n / np.linalg.norm(n)


@dataclass
class Folded:
    state: str
    panels: list[FoldedPanel]
    dims_mm: tuple[float, float, float]  # W, D, H
    checks: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    extent: np.ndarray | None = None  # the folded body's size along world x, y, z (mm)

    @property
    def ok(self) -> bool:
        return all(c["ok"] for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "ok": self.ok,
            "dims_mm": [round(v, 2) for v in self.dims_mm],
            "checks": self.checks,
            "notes": self.notes,
            "panels": [
                {
                    "id": p.id,
                    "name": p.name,
                    "role": p.role,
                    "layer": p.layer,
                    "matrix": np.round(p.matrix, 5).tolist(),
                    "world": [np.round(w, 3).tolist() for w in p.world()],
                }
                for p in self.panels
            ],
        }


def _rot(axis_p: np.ndarray, axis_u: np.ndarray, deg: float) -> np.ndarray:
    """4x4 rotation by ``deg`` about the line through ``axis_p`` with direction ``axis_u``."""
    u = axis_u / np.linalg.norm(axis_u)
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    x, y, z = u
    R = np.array(
        [
            [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
            [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
            [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
        ]
    )
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = axis_p - R @ axis_p
    return M


def _flat(pt, mm: float) -> np.ndarray:
    return np.array([pt[0] * mm, -pt[1] * mm, 0.0])


def roles_of(info: dict) -> dict[str, str]:
    roles = dict(info["body"]["roles"])
    for side, end in info["ends"].items():
        if end["type"] == "tuck_end":
            roles[end["lid"]] = "lid"
            if end.get("tuck_flap"):
                roles[end["tuck_flap"]] = "tuck"
            for d in end.get("dust_flaps") or []:
                roles[d] = "dust"
        elif end["type"] == "crash_lock":
            for root, f in end["flaps"].items():
                roles[root] = "bottom_W" if f["role_of_body"] == "W" else "bottom_D"
                for p in f["panels"]:
                    if p != root:
                        roles[p] = "lock_triangle"
        for p in [p for f in end.get("flaps", {}).values() for p in f["panels"]]:
            roles.setdefault(p, f"{side}_flap")
    return roles


def fold(top: Topology, info: dict, state: str = "closed") -> Folded:
    if state not in STATES:
        raise FoldError("FOLD_STATE_UNKNOWN", f"알 수 없는 접힘 상태입니다: {state}")
    if not top.ok or not info.get("family"):
        raise FoldError(
            "STRUCTURE_UNSUPPORTED", "접을 수 있는 구조로 확인되지 않았습니다.", info.get("reasons")
        )
    if not info.get("supported"):
        raise FoldError(
            "STRUCTURE_UNSUPPORTED", "지원하지 않는 상자 구조입니다.", info.get("reasons")
        )
    ends = info["ends"]
    if state != "closed" and not any(e["type"] == "tuck_end" for e in ends.values()):
        raise FoldError("FOLD_STATE_UNSUPPORTED", "이 구조는 닫힌 상태만 지원합니다.")
    mm = top.mm_per_unit
    roles = roles_of(info)
    body = info["body"]
    W, D, H = body["W_mm"], body["D_mm"], body["H_mm"]
    caliper = FLAT_LOOK.material.caliper_mm
    top_side = "top" if body["orientation"] == "vertical" else "left"
    top_end = ends.get(top_side, {})
    # Root: the W panel that carries the top lid (else the first W panel).
    root = top_end.get("lid_on") or next(p for p, r in body["roles"].items() if r == "W")
    lid_a, tuck_a, dust_a = TOP_ANGLES[state]
    top_panels = {p for f in top_end.get("flaps", {}).values() for p in f["panels"]}

    def angle(e: FoldEdge, child: str) -> float:
        r = roles.get(child, "")
        if child in top_panels:
            return {"lid": lid_a, "tuck": tuck_a, "dust": dust_a}.get(r, 90.0)
        if r == "lock_triangle":
            return 180.0  # glued flat onto its flap
        return 90.0

    nodes = {p.id: p for p in top.panels}
    flat_loops = {
        p.id: [np.array([[x * mm, -y * mm] for x, y in loop]) for loop in p.polygon]
        for p in top.panels
    }
    matrix: dict[str, np.ndarray] = {root: np.eye(4)}
    order = [root]
    i = 0
    while i < len(order):
        parent = order[i]
        i += 1
        for child, e in top.neighbours(parent):
            if child in matrix:
                continue
            a, b = _flat(e.p0, mm), _flat(e.p1, mm)
            u = b - a
            # Fold away from the print side: choose the sense that sends the child's centre to -Z.
            c = np.r_[flat_loops[child][0].mean(0), 0.0, 1.0] if flat_loops.get(child) else None
            sense = 1.0
            if c is not None:
                probe = _rot(a, u, 10.0) @ c
                sense = 1.0 if probe[2] < 0 else -1.0
            matrix[child] = matrix[parent] @ _rot(a, u, sense * angle(e, child))
            order.append(child)
    missing = [p.id for p in top.panels if p.id not in matrix]
    if missing:
        raise FoldError("NET_DISCONNECTED", "접는 선으로 이어지지 않은 패널이 있습니다.", missing)

    # Move the closed box so the body sits at x 0..W, y 0..H, z -D..0 relative to its root's
    # flat frame (the root panel stays where it is on the net; only the whole is re-centred).
    layer_of = {
        "W": 0,
        "D": 0,
        "lid": 0,
        "dust": 1,
        "tuck": 1,
        "glue": 1,
        "bottom_W": 0,
        "lock_triangle": 2,
        "bottom_D": 3,
    }
    for end in ends.values():
        if end["type"] == "crash_lock":
            # The two big flaps interlock: the one on the root's side stays outermost.
            for r, f in end["flaps"].items():
                if f["role_of_body"] == "W":
                    layer_of[r] = 0 if f["on"] == root else 1
    panels = []
    for pid in order:
        role = roles.get(pid, "flap")
        layer = layer_of.get(pid, layer_of.get(role, 1))
        panels.append(FoldedPanel(pid, nodes[pid].name, role, flat_loops[pid], matrix[pid], layer))
    body_ids = [p for p, r in body["roles"].items() if r in ("W", "D")]
    body_pts = np.vstack([w for p in panels if p.id in body_ids for w in p.world()])
    centre = (body_pts.min(0) + body_pts.max(0)) / 2
    # Board thickness: under-layers move toward the box's inside, along their own normal.
    for p in panels:
        if p.layer and (state == "closed" or p.id not in top_panels):
            n = p.normal()
            pc = np.vstack(p.world()).mean(0)
            inward = -n if n @ (pc - centre) > 0 else n
            T = np.eye(4)
            T[:3, 3] = inward * caliper * p.layer
            p.matrix = T @ p.matrix
    shift = np.eye(4)
    shift[:3, 3] = -centre
    for p in panels:
        p.matrix = shift @ p.matrix
    folded = Folded(state, panels, (W, D, H))
    folded.extent = body_pts.max(0) - body_pts.min(0)
    if ends.get("bottom", {}).get("type") == "crash_lock":
        folded.notes.append(
            "자동 잠금 바닥은 닫힌 모양의 근사입니다(날개 4개를 안쪽으로 접고 접착 삼각형을 겹쳐 놓음). "
            "접는 과정·열린 바닥은 지원하지 않습니다."
        )
    _validate(folded, top, info, top_panels)
    return folded


def _edge_far(nodes, pid: str, from_fold: FoldEdge, mm: float) -> np.ndarray:
    """Two points (flat frame) on the edge of panel ``pid`` opposite the fold ``from_fold``."""
    x0, y0, x1, y1 = nodes[pid].bbox
    a, b = np.array(from_fold.p0), np.array(from_fold.p1)
    if from_fold.orientation == "vertical":
        x = x1 if abs(a[0] - x0) < abs(a[0] - x1) else x0
        ya, yb = sorted((a[1], b[1]))
        pts = [(x, ya + 0.1 * (yb - ya)), (x, yb - 0.1 * (yb - ya))]
    else:
        y = y1 if abs(a[1] - y0) < abs(a[1] - y1) else y0
        xa, xb = sorted((a[0], b[0]))
        pts = [(xa + 0.1 * (xb - xa), y), (xb - 0.1 * (xb - xa), y)]
    return np.array([_flat(p, mm) for p in pts])


def _dist_to_line(pts: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    u = (b - a) / np.linalg.norm(b - a)
    rel = pts - a
    return float(np.max(np.linalg.norm(rel - np.outer(rel @ u, u), axis=1)))


def _apply(M: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return (np.c_[pts, np.ones(len(pts))] @ M.T)[:, :3]


def _validate(f: Folded, top: Topology, info: dict, top_panels: set) -> None:
    mm = top.mm_per_unit
    nodes = {p.id: p for p in top.panels}
    M = {p.id: p.matrix for p in f.panels}
    body = info["body"]
    chain = [p for p in body["panels"] if body["roles"][p] != "glue"]
    glue = body.get("glue_flap")
    folds_between = {frozenset((e.a, e.b)): e for e in top.folds}
    # Tube closure: the free edge at one end of the chain meets the other end.
    first, last = chain[0], chain[-1]
    if glue:
        hinge = folds_between[
            frozenset(
                (glue, body["panels"][1] if body["panels"][0] == glue else body["panels"][-2])
            )
        ]
        hinge_panel = hinge.b if hinge.a == glue else hinge.a
        free_panel = last if hinge_panel == first else first
    else:
        hinge = folds_between[frozenset((chain[0], chain[1]))]
        hinge_panel, free_panel = first, last
    inner = folds_between[frozenset((free_panel, chain[-2] if free_panel == last else chain[1]))]
    far = _apply(M[free_panel], _edge_far(nodes, free_panel, inner, mm))
    a, b = _apply(M[hinge_panel], np.array([_flat(hinge.p0, mm), _flat(hinge.p1, mm)]))
    gap = _dist_to_line(far, a, b)
    f.checks.append(
        {"check": "tube_closure", "residual_mm": round(gap, 2), "ok": gap <= CLOSE_TOL_MM}
    )
    # Lid closure (closed tuck ends): the lid's far edge meets the opposite W panel's edge.
    if f.state == "closed":
        for side, end in info["ends"].items():
            if end["type"] != "tuck_end":
                continue
            lid, on = end["lid"], end["lid_on"]
            hinge_lid = folds_between[frozenset((lid, on))]
            far_lid = _apply(M[lid], _edge_far(nodes, lid, hinge_lid, mm))
            opposite = next(p for p in chain if body["roles"][p] == "W" and p != on)
            # The opposite W panel's edge on this side: its fold-parallel edge nearest the lid side.
            x0, y0, x1, y1 = nodes[opposite].bbox
            if hinge_lid.orientation == "horizontal":
                y = y0 if side in ("top", "left") else y1
                edge = np.array([_flat((x0, y), mm), _flat((x1, y), mm)])
            else:
                x = x0 if side in ("top", "left") else x1
                edge = np.array([_flat((x, y0), mm), _flat((x, y1), mm)])
            e0, e1 = _apply(M[opposite], edge)
            gap = _dist_to_line(far_lid, e0, e1)
            f.checks.append(
                {
                    "check": f"{side}_lid_closure",
                    "residual_mm": round(gap, 2),
                    "ok": gap <= CLOSE_TOL_MM,
                }
            )
    # Containment: closed parts stay inside the body's box (plus tolerance).
    half = f.extent / 2 + CONTAIN_TOL_MM
    out = []
    for p in f.panels:
        if f.state != "closed" and p.id in top_panels:
            continue
        pts = np.vstack(p.world())
        if np.any(np.abs(pts) > half + 1e-6):
            out.append(p.id)
    f.checks.append({"check": "containment", "outside_panels": out, "ok": not out})
    hinged = {frozenset((e.a, e.b)) for e in top.folds}
    hits = _intersections(f, hinged)
    f.checks.append({"check": "no_intersections", "pairs": hits, "ok": not hits})


def _area(q: np.ndarray) -> float:
    return (
        abs(float(np.dot(q[:, 0], np.roll(q[:, 1], -1)) - np.dot(q[:, 1], np.roll(q[:, 0], -1))))
        / 2
    )


def _inside(pt: np.ndarray, poly: np.ndarray) -> bool:
    x, y = pt
    xs, ys = poly[:, 0], poly[:, 1]
    xs2, ys2 = np.roll(xs, -1), np.roll(ys, -1)
    dy = np.where(ys2 == ys, 1e-12, ys2 - ys)
    cross = ((ys > y) != (ys2 > y)) & (x < (xs2 - xs) * (y - ys) / dy + xs)
    return bool(cross.sum() % 2)


def _edge_dist(pt: np.ndarray, poly: np.ndarray) -> float:
    a, b = poly, np.roll(poly, -1, axis=0)
    ab = b - a
    t = np.clip(((pt - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-12), 0, 1)
    return float(np.min(np.linalg.norm(a + ab * t[:, None] - pt, axis=1)))


def _intersections(f: Folded, hinged: set) -> list[list[str]]:
    """Pairs of panels where an edge of one passes through the other: more than PIERCE_TOL_MM
    on both sides of its plane, and inside its outline by more than that. Physically
    impossible. Hinged neighbours and stacked layers (parallel planes) never count."""
    out: list[list[str]] = []
    outers = {p.id: max(p.flat, key=_area) for p in f.panels}
    for A in f.panels:
        ring = outers[A.id]
        wa = (np.c_[ring, np.zeros(len(ring)), np.ones(len(ring))] @ A.matrix.T)[:, :3]
        a0, a1 = wa, np.roll(wa, -1, axis=0)
        for B in f.panels:
            if A.id == B.id or frozenset((A.id, B.id)) in hinged:
                continue
            nB, oB = B.normal(), B.matrix[:3, 3]
            d0, d1 = (a0 - oB) @ nB, (a1 - oB) @ nB
            pierce = (d0 * d1 < 0) & (np.abs(d0) > PIERCE_TOL_MM) & (np.abs(d1) > PIERCE_TOL_MM)
            if not pierce.any():
                continue
            t = d0[pierce] / (d0[pierce] - d1[pierce])
            pts = a0[pierce] + (a1[pierce] - a0[pierce]) * t[:, None]
            local = (np.c_[pts, np.ones(len(pts))] @ np.linalg.inv(B.matrix).T)[:, :2]
            poly = outers[B.id]
            if any(_inside(q, poly) and _edge_dist(q, poly) > PIERCE_TOL_MM for q in local):
                pair = sorted((A.id, B.id))
                if pair not in out:
                    out.append(pair)
    return out
