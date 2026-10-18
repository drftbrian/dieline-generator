"""Structural topology (M2 of the structural reference composition): panel adjacency from the
confirmed cut / crease classification only, cuts never hinge, carton recognition (straight and
reverse tuck end, crash-lock bottom recognised but unsupported), and safe failure for
ambiguous or disconnected nets. Nets are generated here from plain rectangles (units: pt at
the PDF scale, so mm = pt * 25.4 / 72)."""

from __future__ import annotations

import pytest

from app.pdf.analyze import find_panels
from app.spec.models import (
    Counts,
    PageInfo,
    ReviewState,
    SeparationItem,
    Separations,
    Specification,
    StructuralPath,
)
from app.structure import carton, topology

MM = 72 / 25.4  # pt per mm


def _path(i, cls, pts, status="confirmed"):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return StructuralPath(
        id=f"p{i}",
        cls=cls,
        status=status,
        confidence=1.0,
        provenance="user_confirmed",
        reason="test",
        polylines=[pts],
        closed=[False],
        bbox=(min(xs), min(ys), max(xs), max(ys)),
        color="#FF0000",
        dashed=False,
        width_pt=0.5,
        color_space="rgb",
        layers=[],
        source_ref=f"s#{i}",
    )


def _minus(a0, a1, holes):
    """1-D interval [a0, a1] minus the given intervals."""
    out = [(min(a0, a1), max(a0, a1))]
    for h0, h1 in holes:
        nxt = []
        for s0, s1 in out:
            if h1 <= s0 or h0 >= s1:
                nxt.append((s0, s1))
                continue
            if h0 > s0:
                nxt.append((s0, h0))
            if h1 < s1:
                nxt.append((h1, s1))
        out = nxt
    return [(s0, s1) for s0, s1 in out if s1 - s0 > 0.5]


def net(W=100, D=50, H=140, top="tuck", bottom="tuck", top_on=0, bottom_on=0, glue=15):
    """A carton net (mm in, pt out). Body: glue | W | D | W | D. ``*_on``: index (0 or 2) of the
    W panel that carries the lid. Returns rectangles and crease segments."""
    x = 50.0
    y0 = 120.0
    rects: list[tuple[float, float, float, float]] = []
    creases: list[tuple[tuple, tuple]] = []
    widths = [W, D, W, D]
    xs = [x + glue]
    for w in widths:
        xs.append(xs[-1] + w)
    if glue:
        rects.append((x, y0 + 3, x + glue, y0 + H - 3))
        creases.append(((x + glue, y0 + 3), (x + glue, y0 + H - 3)))
    for i in range(4):
        rects.append((xs[i], y0, xs[i + 1], y0 + H))
        if i:
            creases.append(((xs[i], y0), (xs[i], y0 + H)))
    diagonals = []
    for side, kind, on in (("top", top, top_on), ("bottom", bottom, bottom_on)):
        if kind == "none":
            continue
        for i in range(4):
            xa, xb = xs[i], xs[i + 1]
            hinge_y = y0 if side == "top" else y0 + H
            sgn = -1 if side == "top" else 1
            if kind == "tuck":
                if i == on:
                    depth = D
                    rects.append(
                        tuple(
                            sorted((hinge_y, hinge_y + sgn * D))
                            and (
                                xa,
                                min(hinge_y, hinge_y + sgn * D),
                                xb,
                                max(hinge_y, hinge_y + sgn * D),
                            )
                        )
                    )
                    far = hinge_y + sgn * D
                    rects.append(
                        (xa + 2, min(far, far + sgn * 15), xb - 2, max(far, far + sgn * 15))
                    )
                    creases.append(((xa + 2, far), (xb - 2, far)))
                elif i in (1, 3):
                    depth = 0.6 * D
                else:
                    continue
            else:  # crash: flaps on all four, a diagonal (glued triangle) in each W flap
                depth = 0.8 * D if i in (0, 2) else 0.5 * D
            if not (kind == "tuck" and i == on):
                rects.append(
                    (
                        xa + 1,
                        min(hinge_y, hinge_y + sgn * depth),
                        xb - 1,
                        max(hinge_y, hinge_y + sgn * depth),
                    )
                )
            creases.append(
                (
                    (xa + (0 if kind == "tuck" and i == on else 1), hinge_y),
                    (xb - (0 if kind == "tuck" and i == on else 1), hinge_y),
                )
            )
            if kind == "crash" and i in (0, 2):
                c = 0.7 * depth
                diagonals.append(((xb - 1 - c, hinge_y), (xb - 1, hinge_y + sgn * c)))
    creases += diagonals
    return rects, creases


def spec_of(rects, creases, extra=(), confirmed=True, unresolved=()):
    """A Specification from rectangles (outer cut = every rectangle edge not on a crease)."""
    paths = []
    k = MM
    for i, (a, b) in enumerate(creases):
        paths.append(_path(f"c{i}", "crease", [(a[0] * k, a[1] * k), (b[0] * k, b[1] * k)]))
    n = 0
    hor = [c for c in creases if abs(c[0][1] - c[1][1]) < 1e-6]
    ver = [c for c in creases if abs(c[0][0] - c[1][0]) < 1e-6]
    for x0, y0, x1, y1 in rects:
        for (ax, ay), (bx, by) in (
            ((x0, y0), (x1, y0)),
            ((x1, y0), (x1, y1)),
            ((x1, y1), (x0, y1)),
            ((x0, y1), (x0, y0)),
        ):
            if ay == by:
                holes = [
                    (min(c[0][0], c[1][0]), max(c[0][0], c[1][0]))
                    for c in hor
                    if abs(c[0][1] - ay) < 1e-6
                ]
                for s0, s1 in _minus(ax, bx, holes):
                    paths.append(_path(f"k{n}", "cut", [(s0 * k, ay * k), (s1 * k, ay * k)]))
                    n += 1
            else:
                holes = [
                    (min(c[0][1], c[1][1]), max(c[0][1], c[1][1]))
                    for c in ver
                    if abs(c[0][0] - ax) < 1e-6
                ]
                for s0, s1 in _minus(ay, by, holes):
                    paths.append(_path(f"k{n}", "cut", [(ax * k, s0 * k), (ax * k, s1 * k)]))
                    n += 1
    for i, (cls, a, b) in enumerate(extra):
        paths.append(
            _path(
                f"x{i}",
                cls,
                [(a[0] * k, a[1] * k), (b[0] * k, b[1] * k)],
                status="unresolved" if f"x{i}" in unresolved else "confirmed",
            )
        )
    page = PageInfo(
        index=0,
        count=1,
        width_pt=700 * k,
        height_pt=500 * k,
        width_mm=700,
        height_mm=500,
        rotation=0,
    )
    sep = SeparationItem(state="detected", required=True)
    spec = Specification(
        page=page,
        flattened=False,
        separations=Separations(cut=sep, crease=sep, artwork=sep, finish=sep),
        paths=paths,
        panels=[],
        objects=[],
        layers=[],
        review=ReviewState(required=False, reasons=[], pending=0),
        structure_confirmed=confirmed,
        counts=Counts(vectors=0, images=0, text_spans=0, fonts=[], color_spaces=[], spot_colors=[]),
    )
    spec.panels = find_panels(spec.paths, spec.page)
    return spec


def _analyze(spec):
    top = topology.analyze(spec)
    return top, carton.classify(top, spec.box)


def test_straight_tuck_end_is_recognised_with_its_dimensions():
    top, info = _analyze(spec_of(*net(top_on=0, bottom_on=0)))
    assert top.ok, [i.code for i in top.issues]
    assert len(top.components) == 1
    assert info["family"] == "rectangular_folding_carton"
    assert info["style"] == "straight_tuck_end" and info["supported"]
    body = info["body"]
    assert (
        abs(body["W_mm"] - 100) < 1.5
        and abs(body["D_mm"] - 50) < 1.5
        and abs(body["H_mm"] - 140) < 2
    )
    assert body["glue_flap"] and list(body["roles"].values()).count("W") == 2
    ends = info["ends"]
    assert ends["top"]["type"] == ends["bottom"]["type"] == "tuck_end"
    assert len(ends["top"]["dust_flaps"]) == 2 and ends["top"]["tuck_flap"]


def test_reverse_tuck_end_has_its_lids_on_opposite_panels():
    top, info = _analyze(spec_of(*net(top_on=0, bottom_on=2)))
    assert top.ok and info["style"] == "reverse_tuck_end" and info["supported"]
    assert info["ends"]["top"]["lid_on"] != info["ends"]["bottom"]["lid_on"]


def test_fold_edges_lie_on_the_crease_lines_and_join_two_panels():
    spec = spec_of(*net())
    top, _ = _analyze(spec)
    creases = [p for p in spec.paths if p.cls == "crease"]
    for e in top.folds:
        assert e.a != e.b
        # The axis is on a crease line (within a line width).
        on = any(
            min(abs(e.p0[1] - c.polylines[0][0][1]), abs(e.p0[0] - c.polylines[0][0][0])) < 1.0
            for c in creases
        )
        assert on, e
    vertical = [e for e in top.folds if e.orientation == "vertical"]
    assert len(vertical) == 4  # glue|W|D|W|D
    assert all(abs(e.length_mm - 140) < 3 or abs(e.length_mm - 134) < 3 for e in vertical)


def test_a_cut_between_two_panels_never_becomes_a_hinge():
    spec = spec_of(*net())
    top, info = _analyze(spec)
    lid = info["ends"]["top"]["lid"]
    dusts = set(info["ends"]["top"]["dust_flaps"])
    hinged = {n for n, _ in top.neighbours(lid)}
    assert not (hinged & dusts)  # lid and dust flaps only touch along cuts


def test_a_cut_where_a_body_fold_should_be_disconnects_the_net():
    rects, creases = net()
    body_fold = next(c for c in creases if c[0][0] == c[1][0] and c[0][0] > 200)
    creases = [c for c in creases if c is not body_fold]
    spec = spec_of(rects, creases)  # that edge is now drawn as a cut
    top, info = _analyze(spec)
    assert not top.ok
    assert any(i.code == "NET_DISCONNECTED" for i in top.issues)
    assert info["family"] is None and not info["supported"]


def test_crash_lock_bottom_is_recognised_but_not_supported():
    top, info = _analyze(spec_of(*net(bottom="crash")))
    assert top.ok
    assert any(e.orientation == "diagonal" for e in top.folds)
    assert info["ends"]["bottom"]["type"] == "crash_lock"
    assert info["style"] == "tuck_top_crash_lock_bottom" and not info["supported"]
    assert any("bottom" in r for r in info["reasons"])


def test_an_unresolved_line_stops_the_analysis():
    rects, creases = net()
    spec = spec_of(rects, creases, extra=[("crease", (300, 200), (300, 230))], unresolved={"x0"})
    top, info = _analyze(spec)
    assert any(i.code == "LINES_UNRESOLVED" and i.level == "error" for i in top.issues)
    assert not top.ok and not info["supported"]


def test_an_unconfirmed_structure_is_refused():
    top, _ = _analyze(spec_of(*net(), confirmed=False))
    assert any(i.code == "STRUCTURE_UNCONFIRMED" for i in top.issues) and not top.ok


def test_a_crease_on_the_outer_edge_is_reported_not_trusted():
    rects, creases = net()
    x = 50 + 15 + 100 + 50 + 100 + 50  # the right edge of the last body panel
    spec = spec_of(rects, creases, extra=[("crease", (x, 150), (x, 220))])
    top, _ = _analyze(spec)
    assert any(i.code == "CREASE_ON_OUTLINE" for i in top.issues)


def test_an_irregular_net_is_unsupported_with_reasons():
    """An L-shaped tray-like net: no W·D·W·D tube."""
    rects = [(50, 50, 150, 150), (150, 50, 250, 150), (50, 150, 150, 230)]
    creases = [((150, 50), (150, 150)), ((50, 150), (150, 150))]
    top, info = _analyze(spec_of(rects, creases))
    assert top.ok and info["family"] is None and not info["supported"] and info["reasons"]


@pytest.mark.parametrize("glue", [0, 15])
def test_with_and_without_a_glue_flap(glue):
    top, info = _analyze(spec_of(*net(glue=glue)))
    assert info["supported"] and bool(info["body"]["glue_flap"]) == bool(glue)


def test_structure_endpoint(client):
    from tests.conftest import upload

    pid, _ = upload(client, "named_spot")
    res = client.get(f"/api/projects/{pid}/structure")
    assert res.status_code == 200
    out = res.json()
    assert {"ok", "panels", "folds", "cuts", "issues", "carton", "components"} <= set(out)
    assert out["panels"] and all(p["polygon"] for p in out["panels"])
