"""Step 2 flat render fidelity (DIELINE_RENDERING_FIX.md, P4): one exact outline on black,
print registered and unblurred, no halo, subtle neutral paper, folds as scores, colours held,
native-resolution vectors and reproducible output; the image model can only add gentle light."""

import hashlib

import numpy as np
import pytest
from PIL import Image
from scipy import ndimage

from app.ai import providers
from app.ai.providers.base import GenerationResult
from app.render import shading
from app.render.layers import build_layers
from app.spec.models import FLAT_LOOK
from app.storage import repo
from tests.conftest import fixture_bytes, upload, wait_job
from tests.test_api_flow import FakeProvider


def _flat(client, pid, **body):
    res = client.post(f"/api/projects/{pid}/generate", json=body)
    assert res.status_code == 202, res.json()
    job = wait_job(client, res.json()["job_id"])
    v = client.get(f"/api/projects/{pid}/versions/{res.json()['version_id']}").json()
    return job, v


def _image(pid, vid, suffix=""):
    return np.asarray(Image.open(repo.project_dir(pid) / "versions" / f"{vid}{suffix}.png"))


@pytest.fixture
def flat(client):
    pid, _ = upload(client, "named_spot")
    job, v = _flat(client, pid)
    assert job["status"] == "done", job.get("error")
    return pid, v


def test_one_outline_on_a_black_ground(flat):
    from app.spec.models import FLAT_LOOK

    pid, v = flat
    img = _image(pid, v["id"]).astype(int)
    ground = int(round(shading.hex_rgb(FLAT_LOOK.lighting.background_color).max() * 255))
    assert ground <= 5  # reads as black
    # The board is light; everything that is not board is the ground or its shadow.
    board = ndimage.binary_fill_holes(img.max(-1) > ground + 10)
    labels, n = ndimage.label(board)
    sizes = np.bincount(labels.ravel())[1:]
    assert (sizes > 0.01 * board.sum()).sum() == 1  # exactly one package, no echo or copy
    ring = ndimage.binary_dilation(board, iterations=6) & ~ndimage.binary_dilation(
        board, iterations=2
    )
    assert img[ring].max() <= ground  # no glow, grey cast or invented edge around it
    assert v["verify"]["outside_echo_px"] == 0


def test_print_is_registered_sharp_and_haloless(flat):
    pid, v = flat
    check = v["verify"]
    assert check["match"] and all(check["checks"].values()), check
    assert check["residual"] <= 1.5  # final == print x achromatic gain, 8-bit rounding only
    assert check["detail_match"] >= 0.98
    assert check["print_ghost"] < 0.2 and check["print_echo"] < 0.3

    final = _image(pid, v["id"]).astype(np.float32) / 255
    det = _image(pid, v["id"], "_deterministic").astype(np.float32) / 255
    assert np.array_equal(final, det)  # deterministic mode: nothing but the vector render
    # Edges are as sharp as the print's own: no blur of type or line work.
    lum = final @ [0.299, 0.587, 0.114]
    grad = np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1))
    assert np.percentile(grad, 99.9) > 1.0


def test_paper_is_subtle_and_neutral(flat):
    pid, v = flat
    check = v["verify"]
    assert check["texture_std"] <= 0.012 and check["cloud_std"] <= 0.004
    assert check["paper_chroma"] <= 1.0  # same gain on R, G and B: no colour cast
    assert check["colour_delta_e_median"] <= 3 and check["colour_delta_e_max"] <= 6


def test_render_is_reproducible(client, flat):
    pid, v = flat
    _, again = _flat(client, pid)
    digest = [hashlib.sha256(_image(pid, x["id"]).tobytes()).hexdigest() for x in (v, again)]
    assert digest[0] == digest[1]


def _layers(edge):
    from app.pdf.analyze import build_spec, detect, extract

    src = fixture_bytes("named_spot")
    ex = extract(src)
    return build_layers(src, build_spec(ex, detect(ex)), edge, 10)


def test_folds_are_scores_not_strokes():
    L = _layers(1400)
    r = shading.crease_relief(
        L, FLAT_LOOK.material, shading.light_dir(FLAT_LOOK.lighting.light_angle)
    )
    on = L.crease > 0.5
    assert on.any()
    # A shallow groove with a bead beside it: a few percent, never a printed line.
    assert -0.15 < r[on].mean() < 0
    assert r.max() > 0.02 and r.min() > -0.15
    far = ~ndimage.binary_dilation(on, iterations=20)
    assert np.abs(r[far]).max() < 1e-3  # nothing away from the folds


def test_higher_resolution_comes_from_the_vectors():
    """The 2x render has real extra detail, not an upscaled 1x render."""
    small, big = _layers(700), _layers(1400)
    s = shading.to8(shading.render_parts(small).rgb).astype(np.float32) / 255
    b = shading.to8(shading.render_parts(big).rgb).astype(np.float32) / 255
    up = np.asarray(
        Image.fromarray((s * 255).astype(np.uint8)).resize(b.shape[1::-1], Image.LANCZOS)
    ).astype(np.float32)
    up /= 255

    def detail(x):
        lum = x @ [0.299, 0.587, 0.114]
        return float(np.abs(lum - ndimage.gaussian_filter(lum, 1)).mean())

    assert detail(b) > 1.2 * detail(up)


class LitProvider(FakeProvider):
    """Returns Image 1 as given, under a soft light from the left: a well-behaved model."""

    def generate(self, req, model_id):
        self.requests.append(req)
        img = np.asarray(req.images[0][1].convert("RGB")).astype(np.float32)
        x = np.linspace(1.04, 0.97, img.shape[1])[None, :, None]
        return GenerationResult(Image.fromarray(np.clip(img * x, 0, 255).astype(np.uint8)))


class KraftProvider(FakeProvider):
    """Repaints the board brown kraft, off by a few pixels, on a grey ground."""

    def generate(self, req, model_id):
        self.requests.append(req)
        img = np.asarray(req.images[0][1].convert("RGB")).astype(np.float32)
        board = img.max(-1) > 0
        out = np.full_like(img, 60.0)
        out[board] = (180, 150, 110)
        return GenerationResult(Image.fromarray(np.roll(out, (5, 7), (0, 1)).astype(np.uint8)))


def test_ai_light_is_gentle_and_never_reaches_outside(client, monkeypatch):
    monkeypatch.setattr(providers, "PROVIDER", LitProvider())
    pid, _ = upload(client, "named_spot")
    job, v = _flat(client, pid, mode="ai_appearance")
    assert job["status"] == "done", job.get("error")
    check = v["verify"]
    assert check["ai_used"] is True and check["match"], check
    assert check["outside_echo_px"] == 0 and check["print_ghost"] < 0.2
    final = _image(pid, v["id"]).astype(np.float32)
    det = _image(pid, v["id"], "_deterministic").astype(np.float32)
    lit = det.max(-1) > 0
    ratio = (final.sum(-1)[lit] + 1) / (det.sum(-1)[lit] + 1)
    assert 0.94 < ratio.min() and ratio.max() < 1.05  # only a gentle light


def test_a_repainted_board_is_not_used(client, monkeypatch):
    monkeypatch.setattr(providers, "PROVIDER", KraftProvider())
    pid, _ = upload(client, "named_spot")
    job, v = _flat(client, pid, mode="ai_appearance")
    assert job["status"] == "done", job.get("error")
    check = v["verify"]
    # The model's board is a different colour on a grey ground and shifted: its light is
    # either rejected or clamped; the print, outline and black ground stay ours.
    assert check["match"] and check["outside_echo_px"] == 0, check
    final = _image(pid, v["id"]).astype(np.float32)
    det = _image(pid, v["id"], "_deterministic").astype(np.float32)
    assert np.abs(final - det).max() <= 0.05 * 255 + 1
    assert final[det.max(-1) == 0].max() == 0


# ---- board look v2 (physical board) against v1 (first look, kept for comparison) ----------

V1_SHA = "81bfe2628261ce96e8c10cd9a27b52771401ae99ffc0b83adad9cd5cb6e7e9e7"


def _looks(edge=1024):
    from app.spec.models import FLAT_LOOK_V1, FLAT_LOOKS

    L = _layers_margin(edge, FLAT_LOOK_V1.lighting.margin)
    return L, {k: shading.render_parts(L, FLAT_LOOKS[k]) for k in ("v1", "v2", "v3")}


def _layers_margin(edge, margin):
    from app.pdf.analyze import build_spec, detect, extract

    src = fixture_bytes("named_spot")
    ex = extract(src)
    return build_layers(src, build_spec(ex, detect(ex)), edge, margin)


V2_SHA = "36ed2520a720082167c69355792cdc8c93cfdd46eaa03af55d2df1896d361b57"


def test_v1_and_v2_looks_are_kept_unchanged():
    from app.spec.models import FLAT_LOOKS

    L = _layers_margin(1024, 12)
    for key, sha in (("v1", V1_SHA), ("v2", V2_SHA)):
        rgb = shading.render_parts(L, FLAT_LOOKS[key]).rgb
        assert hashlib.sha256(shading.to8(rgb).tobytes()).hexdigest() == sha, key


def test_v2_changes_brightness_only_and_keeps_geometry():
    L, parts = _looks(1400)
    a, b = parts["v1"], parts["v2"]
    assert np.array_equal(a.sil, b.sil) and np.array_equal(a.print_rgb, b.print_rgb)
    # Inked pixels away from 0 and 1 (a channel clipped at white has no ratio to compare).
    inked = (b.sil >= 0.999) & (L.artwork[..., 3] > 0.5) & (a.rgb.min(-1) > 0.08)
    inked &= (a.rgb.max(-1) < 0.95) & (b.rgb.max(-1) < 0.95)
    ratio = b.rgb / np.maximum(a.rgb, 1e-3)
    assert (ratio.max(-1) - ratio.min(-1))[inked].max() < 1e-3  # no tint, no redraw
    outside = b.sil <= 1e-3
    assert b.rgb[outside].max() == 0  # solid black ground
    assert 0.85 < b.gain[b.sil >= 0.999].min() and b.gain.max() < 1.05


def test_v2_fibres_show_close_up_not_at_viewing_size():
    from app.spec.models import FLAT_LOOK

    L = _layers_margin(1400, 12)
    tex = shading.fibre_texture(L, FLAT_LOOK.material)

    def at(k):
        h, w = (tex.shape[0] // k) * k, (tex.shape[1] // k) * k
        v = tex[:h, :w].reshape(h // k, k, w // k, k).mean(axis=(1, 3))
        return float((v - ndimage.gaussian_filter(v, 2)).std())

    assert at(1) > 0.002  # detectable at high zoom (about half a grey level and more)
    assert at(4) < 0.002 and at(4) < 0.5 * at(1)  # fades at normal viewing size
    # No mottling: nothing left at 1-10 mm.
    px = L.px_per_mm
    band = ndimage.gaussian_filter(tex, px) - ndimage.gaussian_filter(tex, 10 * px)
    assert float(band.std()) < 0.0005


def test_v2_edge_is_a_hair_of_board_thickness():
    from app.spec.models import FLAT_LOOK

    L = _layers_margin(1400, 12)
    rim = shading.edge_rim(L, FLAT_LOOK.material, shading.light_dir(315))
    d = ndimage.distance_transform_edt(L.silhouette > 0.5)
    assert np.abs(rim[L.silhouette <= 0.5]).max() == 0  # never outside the cut
    assert -0.05 < rim.min() and rim.max() < 0.03  # restrained: no outline or glow
    assert np.abs(rim[d > 2 * L.px_per_mm]).max() < 0.005  # gone within ~2 mm


def test_v2_folds_are_soft_scores_never_cuts():
    from app.spec.models import FLAT_LOOK

    L = _layers_margin(1400, 12)
    r = shading.score_relief(L, FLAT_LOOK.material, shading.light_dir(315))
    on = L.crease > 0.5
    assert -0.1 < r.min() and r[on].mean() < 0 and r.max() > 0.01
    # Smooth: no step between neighbouring pixels bigger than a couple of percent.
    assert np.abs(np.diff(r, axis=0)).max() < 0.03 and np.abs(np.diff(r, axis=1)).max() < 0.03


def test_v2_light_is_even_overhead():
    _, parts = _looks(1400)
    g = parts["v2"].gain
    solid = parts["v2"].sil >= 0.999
    h, w = g.shape
    left, right = g[:, : w // 2][solid[:, : w // 2]], g[:, w // 2 :][solid[:, w // 2 :]]
    top, bottom = g[: h // 2][solid[: h // 2]], g[h // 2 :][solid[h // 2 :]]
    assert abs(np.median(left) - np.median(right)) < 0.005  # no directional light
    assert abs(np.median(top) - np.median(bottom)) < 0.005


def test_look_can_be_chosen_per_render(client):
    pid, _ = upload(client, "named_spot")
    job, v1 = _flat(client, pid, look="v1")
    assert job["status"] == "done" and v1["verify"]["look"] == "v1"
    job, v2 = _flat(client, pid, look="v2")
    assert job["status"] == "done" and v2["verify"]["look"] == "v2", v2["verify"]
    assert v2["verify"]["match"] is True
    job, v3 = _flat(client, pid)
    assert job["status"] == "done" and v3["verify"]["look"] == "v3", v3["verify"]
    assert v3["verify"]["match"] is True


# ---- v3: finishing pass -------------------------------------------------------------------


def test_v3_print_and_geometry_are_v2s():
    L, parts = _looks(1400)
    a, b = parts["v2"], parts["v3"]
    assert np.array_equal(a.sil, b.sil) and np.array_equal(a.print_rgb, b.print_rgb)
    solid = b.sil >= 0.999
    inked = solid & (L.artwork[..., 3] > 0.5) & (a.rgb.min(-1) > 0.08)
    inked &= (a.rgb.max(-1) < 0.95) & (b.rgb.max(-1) < 0.95)
    ratio = b.rgb / np.maximum(a.rgb, 1e-3)
    assert (ratio.max(-1) - ratio.min(-1))[inked].max() < 1e-3  # brightness only
    assert np.abs(b.gain[solid] / a.gain[solid] - 1).max() < 0.06  # a finishing pass


def test_v3_contact_shadow_shows_and_stays_tight():
    from app.spec.models import FLAT_LOOK

    L, parts = _looks(1400)
    p = parts["v3"]
    ground = shading.hex_rgb(FLAT_LOOK.lighting.background_color).max()
    d = ndimage.distance_transform_edt(p.sil < 0.001)
    outside = p.sil < 0.001
    lum = p.rgb.max(-1)
    near = outside & (d <= 0.2 * L.px_per_mm)
    far = outside & (d > 3 * L.px_per_mm)
    assert lum[near].mean() < 0.5 * ground  # visibly darker right at the cut
    assert np.allclose(lum[far], ground, atol=1e-6)  # gone within ~3 mm: no drop shadow
    assert lum[outside].max() <= ground + 1e-6  # never lighter than the ground


def test_v3_edge_tone_is_only_the_cut_pixel_of_the_outer_edge():
    L, parts = _looks(1400)
    p = parts["v3"]
    tone = shading.hex_rgb(shading.EDGE_TONE)
    marked = np.all(np.isclose(p.background, tone, atol=1e-6), axis=-1)
    assert marked.any()
    assert np.all((p.sil[marked] > 0.001) & (p.sil[marked] < 0.999))  # edge pixels only
    assert marked.sum() < 0.02 * (p.sil > 0.5).sum()  # thin
    holes = (p.sil < 0.5) & ~shading.exterior_ground(L)
    if holes.any():  # openings inside the sheet keep a black edge
        assert not (marked & ndimage.binary_dilation(holes, iterations=2)).any()


def test_v3_panels_differ_a_little_and_fade_at_folds():
    L = _layers_margin(1400, 12)
    plane = shading.panel_planes(L)
    board = L.silhouette >= 0.5
    assert np.abs(plane).max() < 0.012  # about +-0.5%, never a visible step
    assert plane[board].std() > 0.001  # but there is a difference
    # Smooth on the board (it is only applied there): no jump between neighbouring pixels.
    inner = ndimage.binary_erosion(board, iterations=2)
    step = np.abs(np.diff(plane, axis=1))[inner[:, 1:] & inner[:, :-1]]
    assert step.max() < 0.002


def test_v3_scores_are_deeper_but_still_delicate():
    from app.spec.models import FLAT_LOOK

    L = _layers_margin(1400, 12)
    v2 = shading.score_relief(L, FLAT_LOOK.material, shading.light_dir(315))
    v3 = shading.V3_SCORE * v2
    assert v3.min() < v2.min() and v3.min() > -0.12  # deeper, never a dark seam
