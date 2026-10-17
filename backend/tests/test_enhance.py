"""Post-render AI material enhancement (ai_material) of a finished deterministic render: the model
sees only a blank board, the source render is never changed, every candidate is verified and a
bad one is rejected with the original kept."""

import hashlib
import io
import json

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.ai import providers
from app.ai.providers.base import GenerationResult
from app.storage import repo
from tests.conftest import upload, wait_job
from tests.test_api_flow import FakeProvider


class LitBoard(FakeProvider):
    """A well-behaved model: Image 1 back, under a soft overhead light."""

    def generate(self, req, model_id):
        self.requests.append(req)
        img = np.asarray(req.images[0][1].convert("RGB")).astype(np.float32)
        h, w = img.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w]
        r2 = ((xx - w / 2) / w) ** 2 + ((yy - h / 2) / h) ** 2
        light = (1.02 - 0.08 * r2)[..., None]
        return GenerationResult(Image.fromarray(np.clip(img * light, 0, 255).astype(np.uint8)))


class ShiftedBoard(FakeProvider):
    """Moves the whole sheet by 4% of the frame: a misplaced board."""

    def generate(self, req, model_id):
        self.requests.append(req)
        img = np.asarray(req.images[0][1].convert("RGB"))
        dy, dx = (round(0.04 * n) for n in img.shape[:2])
        return GenerationResult(Image.fromarray(np.roll(img, (dy, dx), axis=(0, 1))))


class ScribbledBoard(FakeProvider):
    """Prints made-up text and lines on the blank board: new structure and markings."""

    def generate(self, req, model_id):
        self.requests.append(req)
        img = req.images[0][1].convert("RGB").copy()
        d = ImageDraw.Draw(img)
        w, h = img.size
        for i in range(30):
            y = int(h * (0.3 + 0.4 * i / 30))
            d.line([(int(w * 0.3), y), (int(w * 0.7), y)], fill=(40, 40, 40), width=3)
            d.text((int(w * 0.32), y - 12), "LOREM IPSUM 123", fill=(20, 20, 20))
        return GenerationResult(img)


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.fromarray(np.full((60, 80, 3), 200, np.uint8)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def source(client):
    """A project with a finished deterministic v3 render (the enhancement source)."""
    pid, _ = upload(client, "named_spot")
    res = client.post(f"/api/projects/{pid}/generate", json={})
    assert wait_job(client, res.json()["job_id"])["status"] == "done"
    vid = res.json()["version_id"]
    path = repo.project_dir(pid) / "versions" / f"{vid}.png"
    return pid, vid, path, hashlib.sha256(path.read_bytes()).hexdigest()


def _enhance(client, pid, vid, **body):
    res = client.post(f"/api/projects/{pid}/versions/{vid}/enhance", json=body)
    assert res.status_code == 202, res.json()
    job = wait_job(client, res.json()["job_id"])
    v = client.get(f"/api/projects/{pid}/versions/{res.json()['version_id']}").json()
    return job, v


def _img(pid, name):
    return np.asarray(Image.open(repo.project_dir(pid) / "versions" / name).convert("RGB"))


def test_enhance_makes_a_new_verified_version_and_keeps_the_source(client, source, monkeypatch):
    fake = LitBoard()
    monkeypatch.setattr(providers, "PROVIDER", fake)
    pid, src_vid, src_path, src_sha = source
    job, v = _enhance(client, pid, src_vid, strength=1.0)
    assert job["status"] == "done", (job.get("error"), v.get("verify"))
    assert [s["key"] for s in job["stages"]] == [
        "prepare",
        "model",
        "register",
        "extract",
        "composite",
        "verify",
    ]
    # A new version; the source file is byte-identical and still listed as it was.
    assert v["id"] != src_vid and v["kind"] == "flat" and v["legacy"] is False
    assert v["enhancement"]["source_version_id"] == src_vid
    assert v["enhancement"]["strength"] == 1.0 and v["enhancement"]["reference_id"] is None
    assert hashlib.sha256(src_path.read_bytes()).hexdigest() == src_sha
    check = v["verify"]
    assert check["match"] and all(check["checks"].values()), check
    assert check["source_unchanged"] is True and check["edge_sharpness"] >= 0.97
    assert check["outside_echo_px"] == 0 and check["print_ghost"] < 0.2

    final, src = _img(pid, f"{v['id']}.png"), _img(pid, f"{src_vid}.png")
    assert final.shape == src.shape  # same dimensions
    assert not np.array_equal(final, src)  # the light did something
    ratio = (final.astype(np.float32).sum(-1) + 3) / (src.astype(np.float32).sum(-1) + 3)
    assert np.abs(ratio - 1).max() <= 0.065  # bounded

    # The model saw a blank board (no print) and, by default, the bundled look photo.
    req = fake.requests[0]
    assert [label.split(" — ")[0] for label, _ in req.images] == ["Image 1", "Image 2"]
    assert req.prompt.startswith("# Nano Banana Pro — BLANK PAPERBOARD MATERIAL STUDY")
    blank = _img(pid, f"{v['id']}_blank.png").astype(np.float32)
    board = blank.max(-1) > 128
    assert blank[board].std() < 6  # an even blank board: no text, graphics or logos

    # Diagnostics for reproducibility.
    vdir = repo.project_dir(pid) / "versions"
    for name in ("source", "blank", "raw", "registered", "light", "detail"):
        assert (vdir / f"{v['id']}_{name}.png").exists(), name
    for name in ("light", "detail"):
        assert (vdir / f"{v['id']}_{name}.npy").exists(), name
    manifest = json.loads((vdir / f"{v['id']}_enhance.json").read_text())
    assert manifest["model_id"] and manifest["reference"] == "flat_look.png"
    assert manifest["strength"] == 1.0 and manifest["source_sha256"] == src_sha


def test_strength_scales_and_maps_are_reused_without_the_model(client, source, monkeypatch):
    fake = LitBoard()
    monkeypatch.setattr(providers, "PROVIDER", fake)
    pid, src_vid, _, _ = source
    _, first = _enhance(client, pid, src_vid, strength=1.0)
    assert len(fake.requests) == 1
    job, zero = _enhance(client, pid, src_vid, strength=0.0, maps_from=first["id"])
    assert job["status"] == "done", job.get("error")
    assert len(fake.requests) == 1  # no new model call
    assert [s["status"] for s in job["stages"]][1:4] == ["skipped"] * 3
    assert np.array_equal(_img(pid, f"{zero['id']}.png"), _img(pid, f"{src_vid}.png"))
    _, half = _enhance(client, pid, src_vid, strength=0.5, maps_from=first["id"])
    full, src = (_img(pid, f"{x}.png").astype(np.float32) for x in (first["id"], src_vid))
    mid = _img(pid, f"{half['id']}.png").astype(np.float32)
    assert np.abs(mid - src).mean() < np.abs(full - src).mean()


def test_a_selected_reference_is_sent(client, source, monkeypatch):
    fake = LitBoard()
    monkeypatch.setattr(providers, "PROVIDER", fake)
    pid, src_vid, _, _ = source
    rid = client.post(
        f"/api/projects/{pid}/references", files={"file": ("ref.png", _png_bytes(), "image/png")}
    ).json()["id"]
    job, v = _enhance(client, pid, src_vid, reference_id=rid)
    assert job["status"] == "done", job.get("error")
    ref = np.asarray(Image.open(repo.project_dir(pid) / "refs" / f"{rid}.png").convert("RGB"))
    assert np.array_equal(np.asarray(fake.requests[0].images[1][1]), ref)
    assert v["enhancement"]["reference_id"] == rid


@pytest.mark.parametrize(
    ("provider", "reason"),
    [(ShiftedBoard, "board_shifted"), (ScribbledBoard, "invented_structure")],
)
def test_a_bad_candidate_is_rejected_and_the_original_kept(
    client, source, monkeypatch, provider, reason
):
    monkeypatch.setattr(providers, "PROVIDER", provider())
    pid, src_vid, src_path, src_sha = source
    job, v = _enhance(client, pid, src_vid)
    assert job["status"] == "failed" and job["error"]["code"] == "ENHANCE_REJECTED"
    assert reason in job["error"]["details"]["reasons"], job["error"]
    assert v["status"] == "failed" and v["image_url"] is None and v["download_url"] is None
    assert hashlib.sha256(src_path.read_bytes()).hexdigest() == src_sha
    original = client.get(f"/api/projects/{pid}/versions/{src_vid}").json()
    assert original["status"] == "done" and original["image_url"]


def _ghost_maps(scene, blank, L):
    """A broken extraction: a displaced copy of the print in the detail map."""
    from app.render import shading

    lum = shading.print_surface(L, shading.FLAT_LOOK.material) @ np.array(
        [0.299, 0.587, 0.114], np.float32
    )
    ghost = np.roll(lum, (3, 4), axis=(0, 1))
    return {"light": np.ones_like(lum), "detail": (0.05 * (ghost - lum)).astype(np.float32)}


def test_glyph_shaped_appearance_never_reaches_the_print(client, source, monkeypatch):
    """Even a broken extraction cannot ghost the type: detail is kept off the print."""
    from app.services import enhance

    monkeypatch.setattr(providers, "PROVIDER", LitBoard())
    monkeypatch.setattr(enhance, "extract", _ghost_maps)
    pid, src_vid, src_path, src_sha = source
    job, v = _enhance(client, pid, src_vid, strength=1.0)
    if job["status"] == "done":
        check = v["verify"]
        assert check["print_ghost"] < 0.2 and check["print_echo"] < 0.3, check
        assert check["edge_sharpness"] >= 0.97
    else:
        assert job["error"]["code"] == "ENHANCE_REJECTED"
    assert hashlib.sha256(src_path.read_bytes()).hexdigest() == src_sha


def test_ghosted_typography_is_caught_by_verification(client, source, monkeypatch):
    """If the protection itself broke, verification still rejects the ghost."""
    from app.services import enhance

    def unprotected(parts, maps, strength, protect, effects=None):
        return (parts.gain * (1 + strength * maps["detail"] * (parts.sil >= 0.999))).astype(
            np.float32
        )

    monkeypatch.setattr(providers, "PROVIDER", LitBoard())
    monkeypatch.setattr(enhance, "extract", _ghost_maps)
    monkeypatch.setattr(enhance, "apply", unprotected)
    pid, src_vid, src_path, src_sha = source
    job, v = _enhance(client, pid, src_vid, strength=1.0)
    assert job["status"] == "failed" and job["error"]["code"] == "ENHANCE_REJECTED"
    assert "no_halo" in job["error"]["details"]["reasons"], job["error"]
    assert v["image_url"] is None
    assert hashlib.sha256(src_path.read_bytes()).hexdigest() == src_sha


def test_only_finished_deterministic_renders_can_be_enhanced(client, source, monkeypatch):
    monkeypatch.setattr(providers, "PROVIDER", LitBoard())
    pid, src_vid, _, _ = source
    # An AI-appearance render is not a source.
    res = client.post(f"/api/projects/{pid}/generate", json={"mode": "ai_appearance"})
    ai_vid = res.json()["version_id"]
    wait_job(client, res.json()["job_id"])
    res = client.post(f"/api/projects/{pid}/versions/{ai_vid}/enhance", json={})
    assert res.status_code == 409 and res.json()["error"]["code"] == "ENHANCE_SOURCE_INVALID"
    # Nor is an enhancement itself.
    _, enh = _enhance(client, pid, src_vid)
    res = client.post(f"/api/projects/{pid}/versions/{enh['id']}/enhance", json={})
    assert res.status_code == 409


def test_a_new_enhancement_needs_the_model_key_but_reapplying_does_not(client, source, monkeypatch):
    pid, src_vid, _, _ = source
    res = client.post(f"/api/projects/{pid}/versions/{src_vid}/enhance", json={})
    assert res.status_code == 503 and res.json()["error"]["code"] == "PROVIDER_UNAVAILABLE"
    monkeypatch.setattr(providers, "PROVIDER", LitBoard())
    _, first = _enhance(client, pid, src_vid)

    class Off(LitBoard):
        def available(self):
            return False

    monkeypatch.setattr(providers, "PROVIDER", Off())
    job, _ = _enhance(client, pid, src_vid, strength=0.3, maps_from=first["id"])
    assert job["status"] == "done", job.get("error")


# ---- phase 2: paper appearance, across package types ---------------------------------------


def _package(kind: str):
    """A synthetic package (board with a hole and two folds) printed white, dark, as a
    full-bleed gradient, or text-dense."""
    from app.pdf.geometry import Raster
    from app.render.layers import Layers, board

    r = Raster(300, 200, 4.0)
    sq = lambda x0, y0, x1, y1: [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]  # noqa: E731
    sil = board(r, [sq(10, 10, 290, 190), sq(140, 90, 160, 110)]).astype(np.float32)
    h, w = sil.shape
    crease = np.zeros((h, w), np.float32)
    crease[:, round(100 * 4)] = crease[:, round(200 * 4)] = 1
    art = np.zeros((h, w, 4), np.float32)
    if kind == "dark":
        art[...] = (0.08, 0.09, 0.12, 1.0)
    elif kind == "gradient":
        t = np.linspace(0, 1, w, dtype=np.float32)[None, :, None]
        art[..., :3] = (0.85, 0.82, 0.1) * (1 - t) + (0.8, 0.8, 0.8) * t
        art[..., 3] = 1.0
    elif kind == "text":
        yy, xx = np.mgrid[0:h, 0:w]
        glyphs = ((xx // 3) % 4 == 0) & ((yy // 9) % 2 == 0) & (yy > 80) & (yy < 700)
        art[glyphs] = (0.1, 0.1, 0.1, 1.0)
    L = Layers(w, h, 4.0, (0.0, 0.0), art, sil, crease, mm_per_pt=25.4 / 72)
    return L


def _model_photo(blank: np.ndarray, L, marks: bool) -> np.ndarray:
    """What a model might return: our blank board, softly lit, with paper mottling, and (when
    ``marks``) stray lines and letters it drew."""
    h, w = blank.shape[:2]
    rng = np.random.default_rng(5)
    from scipy import ndimage as nd

    mottle = nd.gaussian_filter(rng.standard_normal((h, w)), 2.0 * L.px_per_mm)
    mottle = mottle / mottle.std() * 0.02
    yy, xx = np.mgrid[0:h, 0:w]
    light = 1.02 - 0.06 * (((xx - w / 2) / w) ** 2 + ((yy - h / 2) / h) ** 2)
    scene = blank * (light * (1 + mottle))[..., None]
    if marks:
        scene[300:304, 150:900] *= 0.3
        scene[500:530, 600:640] *= 0.4
    return np.clip(scene, 0, 1).astype(np.float32)


@pytest.mark.parametrize("kind", ["white", "dark", "gradient", "text"])
@pytest.mark.parametrize("marks", [False, True])
def test_paper_appearance_is_restrained_and_keeps_the_print(kind, marks):
    from app.render import look, shading
    from app.services import enhance

    L = _package(kind)
    look_v3 = shading.FLAT_LOOK
    parts = shading.render_parts(L, look_v3)
    blank = shading.render_parts(enhance.blank_layers(L), look_v3).rgb
    scene = _model_photo(blank, L, marks)
    maps = enhance.extract(scene, blank, L)
    d = maps["detail"]
    assert np.abs(d).max() <= enhance.DETAIL_MAX + 1e-6
    on = d != 0
    if on.any():
        assert d[on].std() <= enhance.DETAIL_STD + 1e-6
    assert not d[parts.sil < 0.999].any()  # never on the cut, openings or ground
    if marks:  # nothing taken from where the model drew
        drawn = enhance.model_marks(scene, L)
        assert np.abs(d[drawn]).max() < 1e-6

    protect = enhance.protected_zone(L)
    regions = []  # synthetic: no Figma colours
    applied, gain = enhance.fit_strength(parts, maps, 1.0, protect, regions, L.px_per_mm)
    board = np.clip(parts.print_rgb * gain[..., None], 0, 1)
    s = parts.sil[..., None]
    final = shading.to8(parts.background * (1 - s) + board * s)
    source = shading.to8(parts.rgb)
    check = look.verify_flat(
        final,
        shading.to8(parts.print_rgb),
        parts.sil,
        gain,
        L.artwork[..., 3],
        background=shading.hex_rgb(look_v3.lighting.background_color),
        px_per_mm=L.px_per_mm,
    )
    extra = enhance.enhancement_checks(final, source, parts, L)
    assert applied > 0, (kind, marks)  # some AI appearance survives
    assert check["match"], (kind, marks, check)
    assert all(extra["checks"].values()), (kind, marks, extra)
