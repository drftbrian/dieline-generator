"""Folding the dieline into a box and photographing it: geometry and exact print."""

import numpy as np

from app.render import carton3d
from app.render.look import delta_e


def _tex(h, w, seed):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    t = np.stack([xx / w, yy / h, np.full((h, w), 0.5)], -1).astype(np.float32)
    t[h // 3 : h // 3 + 10, w // 4 : 3 * w // 4] = rng.random(3)  # a "text" bar
    return t


def test_front_view_reproduces_the_front_print():
    tex = {"front": _tex(400, 280, 1), "right": _tex(400, 140, 2), "top": _tex(140, 280, 3)}
    cam = carton3d.Camera(azimuth=0, elevation=0, lens_mm=135, placement=(0.2, 0.1, 0.8, 0.9))
    r = carton3d.render(tex, (70, 35, 100), cam, (600, 600))
    front = r.face == carton3d.FACES.index("front")
    assert front.sum() > 0.9 * (r.face >= 0).sum()  # straight on: (almost) only the front
    # Sampling the print back through the UVs gives the same colours.
    ys, xs = np.nonzero(front)
    inner = (
        (r.uv[ys, xs, 0] > 0.05)
        & (r.uv[ys, xs, 0] < 0.95)
        & (r.uv[ys, xs, 1] > 0.05)
        & (r.uv[ys, xs, 1] < 0.95)
    )
    ys, xs = ys[inner], xs[inner]
    t = tex["front"]
    want = t[
        (r.uv[ys, xs, 1] * (t.shape[0] - 1)).astype(int),
        (r.uv[ys, xs, 0] * (t.shape[1] - 1)).astype(int),
    ]
    assert float(np.median(delta_e(r.rgba[ys, xs, :3], want))) < 1.5


def test_three_quarter_view_shows_three_faces_in_proportion():
    tex = {f: _tex(200, 200, i) for i, f in enumerate(carton3d.FACES)}
    cam = carton3d.Camera(azimuth=35, elevation=20)
    r = carton3d.render(tex, (100, 52, 141), cam, (800, 800))
    shown = {carton3d.FACES[i] for i in np.unique(r.face) if i >= 0}
    assert shown == {"front", "right", "top"}
    # Front edge lengths in the image follow W:H = 100:141 (perspective within ~15%).
    tl, tr, br, bl = r.corners["front"]
    ratio = np.linalg.norm(tr - tl) / np.linalg.norm(bl - tl)
    assert abs(ratio - 100 / 141 * np.cos(np.radians(35))) < 0.15
    cam_left = carton3d.Camera(azimuth=-35, elevation=20)
    r2 = carton3d.render(tex, (100, 52, 141), cam_left, (400, 400))
    assert {carton3d.FACES[i] for i in np.unique(r2.face) if i >= 0} == {"front", "left", "top"}


def test_faces_are_found_on_an_unnamed_dieline():
    from app.pdf.analyze import build_spec, detect, extract
    from tests.conftest import fixture_bytes

    ex = extract(fixture_bytes("named_spot"))
    spec = build_spec(ex, detect(ex))
    faces = carton3d.map_faces(spec.panels)
    assert {"front", "back", "left", "right", "top"} <= faces.keys()
    W, D, H = carton3d.dims_from(faces, 25.4 / 72)
    assert abs(W - 59.4) < 1 and abs(D - 29.5) < 1 and abs(H - 99.5) < 1
