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


def test_one_outline_on_pure_black(flat):
    pid, v = flat
    img = _image(pid, v["id"]).astype(int)
    # The board is light; everything that is not board is exactly the black background.
    board = ndimage.binary_fill_holes(img.max(-1) > 0)
    labels, n = ndimage.label(board)
    sizes = np.bincount(labels.ravel())[1:]
    assert (sizes > 0.01 * board.sum()).sum() == 1  # exactly one package, no echo or copy
    ring = ndimage.binary_dilation(board, iterations=6) & ~board
    assert img[ring].max() == 0  # no glow, grey cast or invented edge around it
    assert v["verify"]["outside_echo_px"] == 0 and v["verify"]["background_max"] == 0


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
