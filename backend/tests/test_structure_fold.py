"""Deterministic folding (M3): rigid hinge rotations from the fold graph, closure /
containment / intersection checks, fold states, and the server-side preview renderer."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from app.render import structure3d as s3
from app.structure import carton, fold, topology
from tests.test_structure_topology import net, spec_of


def _fold(state="closed", **kw):
    spec = spec_of(*net(**kw))
    top = topology.analyze(spec)
    info = carton.classify(top, spec.box)
    return top, info, fold.fold(top, info, state)


def _check(f, name):
    return next(c for c in f.checks if c["check"] == name)


def test_closed_straight_tuck_box_has_the_nets_dimensions_and_closes():
    _, info, f = _fold()
    assert f.ok, f.checks
    w, h, d = f.extent
    assert abs(w - 100) < 1.5 and abs(h - 140) < 1.5 and abs(d - 50) < 1.5
    assert _check(f, "tube_closure")["residual_mm"] < 1.0
    assert _check(f, "top_lid_closure")["residual_mm"] < 1.0
    assert _check(f, "bottom_lid_closure")["residual_mm"] < 1.0


def test_panels_stay_rigid():
    """Folding never stretches a panel: distances between its own points are kept."""
    _, _, f = _fold()
    for p in f.panels:
        flat = p.flat[0]
        world = p.world()[0]
        idx = list(itertools.combinations(range(0, len(flat), max(1, len(flat) // 6)), 2))
        for i, j in idx:
            assert (
                abs(np.linalg.norm(flat[i] - flat[j]) - np.linalg.norm(world[i] - world[j])) < 1e-6
            )


def test_printed_faces_end_up_outside():
    _, info, f = _fold()
    pts = np.vstack([w for p in f.panels if p.role in ("W", "D") for w in p.world()])
    centre = (pts.min(0) + pts.max(0)) / 2
    for p in f.panels:
        if p.role in ("W", "D", "lid"):
            c = np.vstack(p.world()).mean(0)
            assert p.normal() @ (c - centre) > 0, p.id  # print faces away from the box


def test_reverse_tuck_closes_with_lids_on_opposite_panels():
    _, info, f = _fold(top_on=0, bottom_on=2)
    assert f.ok and info["style"] == "reverse_tuck_end"


def test_crash_lock_bottom_folds_closed_only_and_says_so():
    _, info, f = _fold(bottom="crash")
    assert f.ok, f.checks
    assert f.notes and "근사" in f.notes[0]
    roles = {p.role for p in f.panels}
    assert {"bottom_W", "bottom_D", "lock_triangle"} <= roles
    # The top end still opens.
    _, _, g = _fold(state="open_top", bottom="crash")
    assert g.ok


def test_open_and_partial_states_move_only_the_top_end():
    _, _, closed = _fold()
    _, info, opened = _fold(state="open_top")
    top_panels = {p for f in info["ends"]["top"]["flaps"].values() for p in f["panels"]}
    for a, b in zip(closed.panels, opened.panels, strict=True):
        same = np.allclose(a.matrix, b.matrix)
        assert same == (a.id not in top_panels), a.id
    _, _, part = _fold(state="partially_open")
    assert part.ok


def test_intersections_are_detected(monkeypatch):
    """Lid and dust flaps both half closed pass through each other: impossible, reported."""
    monkeypatch.setitem(fold.TOP_ANGLES, "partially_open", (45.0, 30.0, 45.0))
    _, _, f = _fold(state="partially_open")
    hit = _check(f, "no_intersections")
    assert not hit["ok"] and hit["pairs"]


def test_unsupported_and_unknown_states_fail_safely():
    rects = [(50, 50, 150, 150), (150, 50, 250, 150), (50, 150, 150, 230)]
    creases = [((150, 50), (150, 150)), ((50, 150), (150, 150))]
    spec = spec_of(rects, creases)
    top = topology.analyze(spec)
    with pytest.raises(fold.FoldError) as e:
        fold.fold(top, carton.classify(top))
    assert e.value.code == "STRUCTURE_UNSUPPORTED" and e.value.reasons
    top, info, _ = _fold()
    with pytest.raises(fold.FoldError):
        fold.fold(top, info, "inside_out")


def test_preview_is_deterministic_and_maps_back_to_the_net():
    _, _, f = _fold()
    a = s3.render(f, s3.POSES["standing_three_quarter"], (300, 300))
    b = s3.render(f, s3.POSES["standing_three_quarter"], (300, 300))
    assert np.array_equal(a.rgba, b.rgba) and np.array_equal(a.panel, b.panel)
    # Front view: the root W panel fills most of the image, printed side visible.
    front = s3.render(f, s3.POSES["standing_front"], (300, 300))
    ids, counts = np.unique(front.panel[front.panel >= 0], return_counts=True)
    biggest = f.panels[int(ids[np.argmax(counts)])]
    assert biggest.role == "W" and front.outside[front.panel == ids[np.argmax(counts)]].all()
    # Every hit point lies on its panel in the flat net (exact texture mapping in M4). Edge
    # pixels are left out: seen at a grazing angle one pixel covers more than a millimetre.
    from scipy import ndimage

    for i, p in enumerate(f.panels):
        m = ndimage.binary_erosion(a.panel == i, iterations=2)
        if not m.any():
            continue
        xy = a.flat_xy[m]
        lo, hi = p.flat[0].min(0) - 0.5, p.flat[0].max(0) + 0.5
        assert ((xy >= lo) & (xy <= hi)).all(), p.id


@pytest.mark.parametrize("pose", list(s3.POSES))
def test_every_pose_renders(pose):
    _, _, f = _fold(state=s3.POSES[pose].default_state)
    r = s3.render(f, s3.POSES[pose], (200, 160))
    assert r.rgba.shape == (160, 200, 4) and (r.panel >= 0).mean() > 0.05


def test_fold_and_preview_endpoints(client):
    from tests.conftest import upload

    pid, _ = upload(client, "named_spot")
    res = client.get(f"/api/projects/{pid}/structure/fold")
    assert res.status_code == 200, res.json()
    out = res.json()
    assert out["ok"] and {c["check"] for c in out["checks"]} >= {
        "tube_closure",
        "containment",
        "no_intersections",
    }
    png = client.get(
        f"/api/projects/{pid}/structure/preview",
        params={"pose": "standing_front", "width": 200, "height": 200},
    )
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    bad = client.get(f"/api/projects/{pid}/structure/preview", params={"pose": "upside"})
    assert bad.status_code == 422
    bad = client.get(f"/api/projects/{pid}/structure/fold", params={"state": "inside_out"})
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "FOLD_STATE_UNKNOWN"
