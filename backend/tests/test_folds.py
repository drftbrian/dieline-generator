"""v4 physical fold scores (render/folds.py): orientation-aware relief from the exact crease
lines, confined to the folds, the same at any resolution, never a slit, glow or halo, and the
print, cut and fold geometry untouched."""

import hashlib

import numpy as np
import pytest
from scipy import ndimage

from app.pdf.geometry import Raster
from app.render import folds, shading
from app.render.layers import Layers, board
from app.spec.models import FLAT_LOOKS, flat_look

V3_SHA = "40f7cfc931a01235cfbb527d6f4a001c3f3cfee1980549aa5bf5da0912bd7013"
MM_PER_PT = 25.4 / 72


def sheet(scale: float, folds_pt: list) -> Layers:
    """A 120 x 80 mm board (in pt) with the given crease polylines, at ``scale`` px per pt."""
    r = Raster(340, 227, scale)
    sq = [(10, 10), (330, 10), (330, 217), (10, 217), (10, 10)]
    sil = board(r, [sq]).astype(np.float32)
    crease = (r.lines(folds_pt, width_px=max(1.0, scale * 0.7)) > 0).astype(np.float32)
    h, w = sil.shape
    crease = crease[:h, :w]
    art = np.zeros((h, w, 4), np.float32)
    return Layers(w, h, scale, (0.0, 0.0), art, sil, crease, mm_per_pt=MM_PER_PT)


H_FOLD = [[(10, 60), (330, 60)]]
V_FOLD = [[(120, 10), (120, 217)]]
D_FOLD = [[(200, 30), (300, 190)]]


def profile(L: Layers, gain: np.ndarray, axis: int, at_pt: float, half_mm: float = 3.0):
    """Mean gain across a fold, every 0.1 mm from -half_mm..half_mm (mm-sampled)."""
    px = L.px_per_mm
    c = at_pt * L.scale
    offs = np.arange(-half_mm, half_mm + 1e-9, 0.1)
    pos = c + offs * px
    if axis == 0:  # horizontal fold: sample along y, average over x
        band = gain[:, int(0.3 * L.width) : int(0.4 * L.width)].mean(axis=1)
    else:  # vertical fold: sample along x
        band = gain[int(0.5 * L.height) : int(0.6 * L.height), :].mean(axis=0)
    return np.interp(pos, np.arange(band.size), band)


def test_v1_v2_v3_are_unchanged():
    from app.pdf.analyze import build_spec, detect, extract
    from app.render.layers import build_layers
    from tests.conftest import fixture_bytes

    src = fixture_bytes("named_spot")
    ex = extract(src)
    L = build_layers(src, build_spec(ex, detect(ex)), 1024, 12)
    rgb = shading.render_parts(L, FLAT_LOOKS["v3"]).rgb
    assert hashlib.sha256(shading.to8(rgb).tobytes()).hexdigest() == V3_SHA


def test_folds_react_to_their_own_orientation():
    L = sheet(4.0, H_FOLD + V_FOLD)
    from_left = folds.fold_maps(L, folds.FOLD_PRESETS["medium"], 270).gain
    v = profile(L, from_left, 1, 120)
    hz = profile(L, from_left, 0, 60)
    n = v.size // 2
    # Light from the left: the vertical fold has a lit side and a shaded side (the groove's
    # far wall faces the light) ...
    assert v[n + 3 : n + 12].max() > 1.02 and v[n - 12 : n - 3].min() < 0.99
    # ... while the horizontal fold, edge-on to that light, is symmetric.
    assert np.abs(hz[:n] - hz[::-1][:n]).max() < 0.004
    from_top = folds.fold_maps(L, folds.FOLD_PRESETS["medium"], 0).gain
    hz_top = profile(L, from_top, 0, 60)
    assert hz_top[n + 3 : n + 12].max() > 1.02  # now the horizontal fold has the lit side


def test_diagonal_folds_have_no_staircase():
    L = sheet(4.0, D_FOLD)
    fm = folds.fold_maps(L, folds.FOLD_PRESETS["medium"], 315)
    # Sample the gain on the fold centre line at many points along it: it stays even.
    t = np.linspace(0.2, 0.8, 200)
    x = (200 + 100 * t) * L.scale
    y = (30 + 160 * t) * L.scale
    on = ndimage.map_coordinates(fm.gain, [y, x], order=1)
    assert on.std() < 0.006 and on.mean() < 0.97
    # And the height field is smooth: no pixel-to-pixel steps.
    assert np.abs(np.diff(fm.height, axis=1)).max() < 0.25 * folds.FOLD_PRESETS["medium"].depth_mm


@pytest.mark.parametrize("preset", ["low", "medium", "high"])
def test_folds_are_visible_but_never_slits_or_glows(preset):
    L = sheet(4.0, H_FOLD + V_FOLD + D_FOLD)
    fm = folds.fold_maps(L, folds.FOLD_PRESETS[preset], 315)
    on = L.silhouette >= 0.999
    g = fm.gain[on]
    assert folds.GAIN_LIMITS[0] <= g.min() and g.max() <= folds.GAIN_LIMITS[1]
    # Measurably visible within the folds, not a global brightness change.
    near = ndimage.binary_dilation(fm.mask, iterations=round(1.0 * L.px_per_mm)) & on
    assert fm.gain[near].max() - fm.gain[near].min() > 0.04
    # Confined: nothing beyond ~3 mm from a fold, and nothing off the board.
    far = ~ndimage.binary_dilation(fm.mask, iterations=round(3.0 * L.px_per_mm))
    assert np.abs(fm.gain[far & on] - 1).max() < 2e-3
    assert np.all(fm.gain[L.silhouette < 0.999] == 1)


def test_fold_relief_is_the_same_at_any_resolution():
    small, big = sheet(3.0, V_FOLD), sheet(6.0, V_FOLD)
    p = folds.FOLD_PRESETS["medium"]
    a = profile(small, folds.fold_maps(small, p, 315).gain, 1, 120)
    b = profile(big, folds.fold_maps(big, p, 315).gain, 1, 120)
    assert np.abs(a - b).max() < 0.02  # mm-scaled: same shape and depth


def test_crossing_folds_merge_without_a_dark_blob():
    L = sheet(4.0, H_FOLD + V_FOLD)
    fm = folds.fold_maps(L, folds.FOLD_PRESETS["medium"], 315)
    cx, cy = round(120 * L.scale), round(60 * L.scale)
    r = round(1.0 * L.px_per_mm)
    cross = fm.gain[cy - r : cy + r, cx - r : cx + r].min()
    single = fm.gain[round(L.height * 0.7), cx - r : cx + r].min()  # same vertical fold, alone
    assert cross > single - 0.02  # not darker where the folds meet


def test_v4_keeps_geometry_print_and_sharpness():
    from app.pdf.analyze import build_spec, detect, extract
    from app.render import look
    from app.render.layers import build_layers
    from tests.conftest import fixture_bytes

    src = fixture_bytes("named_spot")
    ex = extract(src)
    L = build_layers(src, build_spec(ex, detect(ex)), 1400, 12)
    v3 = shading.render_parts(L, FLAT_LOOKS["v3"])
    v4 = shading.render_parts(L, flat_look("v4", "medium"))
    # Cut, openings, folds and print: identical inputs; only the board's brightness differs.
    assert np.array_equal(v3.sil, v4.sil) and np.array_equal(v3.print_rgb, v4.print_rgb)
    assert np.array_equal(v3.background, v4.background)
    fm = folds.fold_maps(L, folds.FOLD_PRESETS["medium"], 315)
    assert np.array_equal(fm.mask, L.crease > 0.5)  # fold geometry is the crease raster
    # No new holes or gaps: the board never gets anywhere near the ground's darkness.
    solid = v4.sil >= 0.999
    assert v4.rgb[solid].max(-1).min() > 0.5 * v3.rgb[solid].max(-1).min()
    # Brightness only: same colour ratio on R, G, B wherever v3 and v4 differ.
    inked = solid & (L.artwork[..., 3] > 0.5) & (v3.rgb.min(-1) > 0.08)
    inked &= (v3.rgb.max(-1) < 0.95) & (v4.rgb.max(-1) < 0.95)
    ratio = v4.rgb / np.maximum(v3.rgb, 1e-3)
    assert (ratio.max(-1) - ratio.min(-1))[inked].max() < 1e-3
    # Verified like any flat render (print, halo, ground, texture, colours).
    final = shading.to8(v4.rgb)
    check = look.verify_flat(
        final,
        shading.to8(v4.print_rgb),
        v4.sil,
        v4.gain,
        L.artwork[..., 3],
        background=shading.hex_rgb(FLAT_LOOKS["v4"].lighting.background_color),
        px_per_mm=L.px_per_mm,
    )
    assert check["match"], check
    # Text sharpness does not decrease.
    from app.services import enhance

    extra = enhance.enhancement_checks(final, shading.to8(v3.rgb), v4, L)
    assert extra["edge_sharpness"] >= 0.97, extra


def test_v4_is_reproducible():
    L = sheet(4.0, H_FOLD + V_FOLD + D_FOLD)
    a = shading.render_parts(L, flat_look("v4")).rgb
    b = shading.render_parts(L, flat_look("v4")).rgb
    assert np.array_equal(a, b)


def test_v4_can_be_rendered_through_the_api(client):
    from tests.conftest import upload, wait_job

    pid, _ = upload(client, "named_spot")
    for preset in ("low", "high"):
        res = client.post(
            f"/api/projects/{pid}/generate", json={"look": "v4", "fold_preset": preset}
        )
        job = wait_job(client, res.json()["job_id"])
        assert job["status"] == "done", job.get("error")
        v = client.get(f"/api/projects/{pid}/versions/{res.json()['version_id']}").json()
        assert v["verify"]["look"] == "v4" and v["verify"]["fold_preset"] == preset
        assert v["verify"]["match"] is True
