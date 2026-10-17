"""Scene light on the package, folds, verification."""

import numpy as np
from scipy import ndimage

from app.pdf.analyze import build_spec, detect, extract
from app.render.layers import build_layers
from app.render.look import verify
from app.render.shading import crease_relief, light_dir
from app.spec.models import Material
from tests.conftest import fixture_bytes


def _layers():
    src = fixture_bytes("named_spot")
    ex = extract(src)
    return build_layers(src, build_spec(ex, detect(ex)), 700, 10)


def test_folds_catch_the_light_on_one_wall():
    L = _layers()
    m = Material(crease_depth=60)
    r = crease_relief(L, m, light_dir(270))  # light from the left
    line = L.crease > 0.5
    # On vertical folds: the wall facing the light (right of the fold centre) is brighter.
    gx = np.gradient(ndimage.gaussian_filter(L.crease, 1.0), axis=1)
    near = ndimage.binary_dilation(line, iterations=3) & ~line
    assert r[near & (gx < -1e-3)].mean() > r[near & (gx > 1e-3)].mean()
    assert not crease_relief(L, Material(crease_depth=0), light_dir(270)).any()


def test_model_surface_reaches_the_package_but_its_print_does_not():
    from app.render.shading import print_surface
    from app.render.surface import transfer

    L = _layers()
    h, w = L.height, L.width
    sil = L.silhouette
    pr = print_surface(L, Material())
    yy, xx = np.mgrid[0:h, 0:w]
    ribs = 1 + 0.05 * np.sin(2 * np.pi * yy / 5)  # the board the model photographed
    # The model redrew the print a few pixels off, with wrong contrast: that must not leak.
    moved = np.roll(print_surface(L, Material()), (2, 3), axis=(0, 1))
    scene = np.clip((0.5 * pr + 0.5 * moved) * (0.9 * ribs)[..., None], 0, 1)
    gain, edges, valley = transfer(pr, scene, sil, L.px_per_mm)
    pkg = np.clip(pr * gain, 0, 1)

    board = ndimage.binary_erosion((sil > 0.999) & ~edges, iterations=3)
    g = gain.mean(-1)
    hp = g - ndimage.gaussian_filter(g, 3)
    # Ribs came through (alignment may shift their phase by a pixel or two: paper has no fixed
    # position, so allow for it).
    best = max(
        np.corrcoef(hp[board], (np.roll(ribs, k, axis=0) - ribs.mean())[board])[0, 1]
        for k in range(-3, 4)
    )
    assert best > 0.8

    to8 = lambda a: (np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)  # noqa: E731
    final = to8(pr)
    final[sil > 0.999] = to8(pkg)[sil > 0.999]
    ok = verify(final, to8(pr), sil, gain, edges, scene)
    assert ok["match"], ok
    assert ok["print_ghost"] < 0.3


def test_ribs_continue_through_the_print():
    from app.render.surface import fill_along_lines

    h, w = 120, 400
    yy, xx = np.mgrid[0:h, 0:w]
    ribs = 1 + 0.05 * np.sin(2 * np.pi * yy / 5)
    mask = np.zeros((h, w), bool)
    mask[20:100, 150:250] = True  # a block of text over the ribs
    everywhere = np.ones((h, w), bool)
    holed = np.where(mask, 1.0, ribs)
    along = fill_along_lines(holed, ~mask, everywhere, "horizontal", 200)
    blur = fill_along_lines(holed, ~mask, everywhere, None, 200)
    truth = (ribs - 1)[mask]
    assert np.corrcoef((along - 1)[mask], truth)[0, 1] > 0.8
    assert np.corrcoef((blur - 1)[mask], truth)[0, 1] < 0.3


def test_cut_edge_is_kept_and_ink_starving_is_bounded():
    from app.render.shading import print_surface
    from app.render.surface import INK_STARVE, outline_band, transfer

    L = _layers()
    sil = L.silhouette
    pr = print_surface(L, Material())
    h, w = L.height, L.width
    yy = np.mgrid[0:h, 0:w][0]
    ribs = 1 + 0.05 * np.sin(2 * np.pi * yy / 5)
    edge_light = np.where(outline_band(sil, L.px_per_mm), 1.3, 1.0)  # light on the cut face
    scene = np.clip(pr * (0.85 * ribs * edge_light)[..., None], 0, 1)
    gain, edges, valley = transfer(pr, scene, sil, L.px_per_mm)
    band = outline_band(sil, L.px_per_mm) & (sil > 0.999)
    assert not edges[band].any()  # the cut edge is never filled in
    assert (
        gain.mean(-1)[band].mean()
        > gain.mean(-1)[ndimage.binary_erosion(sil > 0.999, iterations=20)].mean()
    )
    assert 0 <= valley.min() and valley.max() <= 1 and valley.mean() > 0.05
    flat_gain, _, flat_valley = transfer(pr, np.clip(pr * 0.85, 0, 1), sil, L.px_per_mm)
    inner = ndimage.binary_erosion(sil > 0.999, iterations=10)
    assert flat_valley[inner].max() < 0.2  # flat board: (almost) no starving
    starved = L.artwork[..., 3] * (1 - INK_STARVE * valley)
    assert (L.artwork[..., 3] - starved).max() <= INK_STARVE + 1e-6


def test_print_colours_hold_under_a_dark_tinted_scene():
    from app.render.look import delta_e
    from app.render.shading import print_surface
    from app.render.surface import transfer

    L = _layers()
    sil = L.silhouette
    pr = print_surface(L, Material())
    h, w = L.height, L.width
    yy = np.mgrid[0:h, 0:w][0]
    ribs = 1 + 0.05 * np.sin(2 * np.pi * yy / 5)
    tint = np.array([1.0, 0.85, 0.7], np.float32)  # a warm, 40% darker scene
    scene = np.clip(pr * (0.6 * ribs)[..., None] * tint, 0, 1)
    gain, _, _ = transfer(pr, scene, sil, L.px_per_mm)
    pkg = np.clip(pr * gain, 0, 1)
    solid = ndimage.binary_erosion(sil > 0.999, iterations=12)
    assert np.allclose(gain[..., 0], gain[..., 2])  # no tint
    assert abs(float(np.median(gain[..., 0][solid])) - 1) < 0.02  # exposure-neutral
    assert float(np.median(delta_e(pkg[solid], pr[solid]))) < 3
    assert float(gain[..., 0][solid].std()) > 0.005  # the board texture is still there


def test_text_the_model_drew_off_position_leaves_no_ghost():
    from app.render import surface
    from app.render.shading import print_surface

    L = _layers()
    sil = L.silhouette
    pr = print_surface(L, Material())
    # The model redrew the print 4 px down and 8 px right, softly (like its garbled text).
    moved = np.roll(pr, (4, 8), axis=(0, 1))
    scene = np.clip(0.9 * (0.6 * pr + 0.4 * moved), 0, 1)
    solid = ndimage.binary_erosion(sil > 0.999, iterations=12)
    _, untrusted, _ = surface.transfer(pr, scene, sil, L.px_per_mm)
    # Every edge of the model's displaced text lies where its surface is replaced by board.
    lum = ndimage.gaussian_filter(moved.mean(-1), 0.7)
    their = (np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1)) / 8 > 0.012) & solid
    assert their.sum() > 100
    assert (untrusted & their).sum() / their.sum() > 0.98
