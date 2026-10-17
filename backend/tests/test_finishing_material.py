"""Finish material renderers (M4): only the finish's own region changes, results are
deterministic and the same in any crop, and each material reads the way the reference photos
measured (warm gold, lit relief side brighter than the far side)."""

import numpy as np
import pytest

from app.finishing import catalog
from app.render.finishing import material

H, W = 240, 320
SCENE = material.Scene(px_per_mm=10.0, full=(H, W))


def _base() -> np.ndarray:
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    return np.dstack([0.6 + 0.3 * xx / W, 0.7 * np.ones_like(xx), 0.5 + 0.2 * yy / H])


def _disc(cy=120, cx=160, r=50) -> np.ndarray:
    yy, xx = np.mgrid[0:H, 0:W]
    return np.clip(r + 0.5 - np.hypot(yy - cy, xx - cx), 0, 1).astype(np.float32)


def _stack(fid: str, m: np.ndarray, **params):
    return [(catalog.finish(fid), catalog.clamp_params(fid, params), m)]


def test_no_finishes_is_the_source():
    base = _base()
    out, changed = material.render(base, [], SCENE)
    assert np.array_equal(out, base) and not changed.any()


@pytest.mark.parametrize(
    "fid",
    [
        "foil.gold",
        "foil.silver",
        "relief.emboss",
        "relief.deboss",
        "coating.spot_uv",
        "surface.matte_lamination",
        "surface.gloss_lamination",
        "surface.uncoated",
        "foil.black",
        "foil.red_metallic",
        "foil.black_matte",
        "foil.white",
        "foil.holographic",
        "coating.raised_uv",
        "dome.epoxy",
    ],
)
def test_only_the_region_changes_and_is_deterministic(fid):
    base, m = _base(), _disc()
    out, changed = material.render(base, _stack(fid, m), SCENE)
    assert np.array_equal(out[~changed], base[~changed])
    assert np.abs(out - base).max() > 0.01  # it does something
    if catalog.finish(fid).model == "relief":  # the shape plus its shoulder, no further
        assert changed[m > 0].all() and changed.sum() < (m > 0).sum() * 1.6
    else:
        assert np.array_equal(changed, m > 0)
    again, _ = material.render(base, _stack(fid, m), SCENE)
    assert np.array_equal(out, again)


def test_a_crop_renders_like_the_full_image():
    base, m = _base(), _disc()
    full, _ = material.render(base, _stack("foil.gold", m), SCENE)
    y0, x0 = 40, 60
    scene = material.Scene(px_per_mm=10.0, offset=(y0, x0), full=(H, W))
    crop, _ = material.render(base[y0:220, x0:300], _stack("foil.gold", m[y0:220, x0:300]), scene)
    assert np.allclose(crop, full[y0:220, x0:300], atol=1e-5)


def test_gold_is_warm_and_varies_like_a_mirror():
    base, m = _base(), _disc()
    out, _ = material.render(base, _stack("foil.gold", m), SCENE)
    inside = out[m > 0.99]
    assert (inside[:, 0] > inside[:, 2] + 0.1).mean() > 0.95  # warm everywhere
    lum = inside @ material.LUMA
    assert lum.max() - lum.min() > 0.3  # a highlight sweep and darker room reflections


def test_emboss_lit_side_is_brighter_than_the_far_side():
    base, m = np.full((H, W, 3), 0.8, np.float32), _disc()
    out, _ = material.render(base, _stack("relief.emboss", m), SCENE)
    # Light from the top-left (315°): the top-left shoulder faces it.
    lit = out[120 - 37, 160 - 37].mean()
    far = out[120 + 37, 160 + 37].mean()
    assert lit > 0.8 > far


def test_raking_light_shows_relief_more():
    base, m = np.full((H, W, 3), 0.8, np.float32), _disc()
    top, _ = material.render(base, _stack("relief.emboss", m), SCENE)
    rake, _ = material.render(base, _stack("relief.emboss", m), material.lighting(SCENE, "raking"))
    assert np.abs(rake - base).max() > np.abs(top - base).max() * 1.5


def test_dark_metals_keep_their_colour_and_pigments_are_flat():
    base, m = _base(), _disc()
    black, _ = material.render(base, _stack("foil.black", m), SCENE)
    red, _ = material.render(base, _stack("foil.red_metallic", m), SCENE)
    matte, _ = material.render(base, _stack("foil.black_matte", m), SCENE)
    inside = m > 0.99
    assert np.median(black[inside] @ material.LUMA) < 0.25  # 먹박 is black, not silver
    assert (red[inside][:, 0] > red[inside][:, 1] + 0.1).mean() > 0.9
    lum = matte[inside] @ material.LUMA
    assert lum.max() - lum.min() < 0.1  # pigment foil: no mirror sweep


def test_holographic_shifts_colour_across_the_shape():
    base, m = _base(), _disc()
    out, _ = material.render(base, _stack("foil.holographic", m), SCENE)
    hues = out[m > 0.99]
    assert np.ptp(hues[:, 0] - hues[:, 2]) > 0.1


def test_dome_magnifies_and_catches_light():
    yy, xx = np.mgrid[0:H, 0:W]
    stripes = np.dstack([((xx // 6) % 2).astype(np.float32) * 0.6 + 0.2] * 3)
    m = _disc()
    out, changed = material.render(stripes, _stack("dome.epoxy", m), SCENE)
    assert np.array_equal(out[~changed], stripes[~changed])
    assert (out[m > 0.99] @ material.LUMA).max() > 0.9  # a specular highlight on the lens
