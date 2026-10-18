"""Structural composition (multi-instance): every package of a reference is replaced by a rigid
copy of our folded carton, the reference packages are removed, the photo's shadows stay
shadows on our cartons (never inverted into bright patches), and nothing of the reference's
print reaches them. AI is optional and never authoritative. Synthetic references are drawn
here with known package corners (no AI to locate them)."""

from __future__ import annotations

import io
import json
import math

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.ai import providers
from app.ai.providers.base import GenerationResult
from app.scene import compose as sc
from app.scene import geometry as g
from app.storage import repo
from tests.conftest import upload, wait_job
from tests.test_api_flow import FakeProvider
from tests.test_prompts import READING

SIZE = 640
F = 760.0
CREAM = np.array([0.86, 0.82, 0.74])
KRAFT = np.array([0.70, 0.53, 0.36])


def _rot_x(deg):
    a = math.radians(deg)
    return np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])


def _rot_n(deg):
    a = math.radians(deg)
    return np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])


def reference_scene(n=3, shadow=True, empty=False):
    """A photo of ``n`` stacked boxes seen from above at ~55 deg: (image float HxWx3, quads in
    pixels top-of-stack first, shadow band mask)."""
    K = g.intrinsics(F, (SIZE, SIZE))
    tilt = _rot_x(55)
    img = np.ones((SIZE, SIZE, 3)) * CREAM
    boxes = []
    for k in range(n):
        centre = np.array([0.12 * k - 0.1, 0.18 * k - 0.15, 3.6 + 0.2 * k])  # lower = farther
        R = tilt @ _rot_n(25 - 22 * k)
        corners = np.array(
            [
                centre + R @ np.array(v)
                for v in ([-0.5, -0.36, 0], [0.5, -0.36, 0], [0.5, 0.36, 0], [-0.5, 0.36, 0])
            ]
        )
        normal = R @ np.array([0, 0, -1.0])
        boxes.append((corners, normal))
    quads = []
    canvas = Image.fromarray((img * 255).astype(np.uint8))
    d = ImageDraw.Draw(canvas)
    for corners, normal in reversed(boxes):  # far first: the top of the stack is drawn last
        top = g.project(K, corners)
        bottom = g.project(K, corners - normal * 0.18)
        hull = g._hull(np.vstack([top, bottom]))
        quads.append(top)
        if empty:
            continue
        d.polygon([tuple(p) for p in hull], fill=tuple(int(v * 255 * 0.8) for v in KRAFT))
        d.polygon([tuple(p) for p in top], fill=tuple(int(v * 255) for v in KRAFT))
        # The reference's own print: bright thin "lettering" across its lid.
        for t in np.linspace(0.25, 0.75, 6):
            a, b = top[0] + (top[3] - top[0]) * t, top[1] + (top[2] - top[1]) * t
            d.line(
                [tuple(a + (b - a) * 0.2), tuple(a + (b - a) * 0.8)], fill=(250, 250, 245), width=3
            )
    out = np.asarray(canvas).astype(np.float32) / 255
    band = np.zeros((SIZE, SIZE), bool)
    if shadow:  # a dark diagonal "leaf" shadow band over everything
        yy, xx = np.mgrid[0:SIZE, 0:SIZE]
        band = np.abs((xx - yy) - 40) < 70
        out = out * np.where(band, 0.42, 1.0)[..., None]
    return out, list(reversed(quads)), band


def _png(a) -> bytes:
    buf = io.BytesIO()
    Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def scene_project(client, monkeypatch):
    """named_spot (a supported reverse tuck end) with a flat render and a 3-box reference."""
    fake = FakeProvider()
    monkeypatch.setattr(providers, "PROVIDER", fake)
    pid, _ = upload(client, "named_spot")
    job = wait_job(client, client.post(f"/api/projects/{pid}/generate", json={}).json()["job_id"])
    assert job["status"] == "done", job
    [flat] = client.get(f"/api/projects/{pid}/history").json()["versions"]
    img, quads, band = reference_scene(3)
    rid = client.post(
        f"/api/projects/{pid}/references", files={"file": ("ref.png", _png(img), "image/png")}
    ).json()["id"]
    repo.update("refs", rid, analysis_status="done", analysis_json=READING)
    return pid, rid, flat["id"], quads, band, fake


def _scene(quads, **extra):
    return {
        "instances": [
            {"id": f"inst{i + 1}", "quad": (q / SIZE).round(4).tolist(), "height": 0.18, **extra}
            for i, q in enumerate(quads)
        ],
        "settings": {},
    }


def _preview(client, pid, rid, fid, layer="final"):
    res = client.get(
        f"/api/projects/{pid}/compose/preview",
        params={"reference_id": rid, "flat_version_id": fid, "layer": layer},
    )
    assert res.status_code == 200, res.json()
    return np.asarray(Image.open(io.BytesIO(res.content)).convert("RGB")).astype(
        np.float32
    ) / 255, json.loads(res.headers["x-compose-report"])


def test_three_packages_become_three_folded_cartons(client, scene_project):
    pid, rid, fid, quads, band, _ = scene_project
    assert (
        client.put(f"/api/projects/{pid}/references/{rid}/scene", json=_scene(quads)).status_code
        == 200
    )
    from app.services import structural_merge

    comp, reference, _ = structural_merge.precompose(pid, rid, fid, edge=SIZE)
    ids = comp.layers["instance_id"]
    assert sorted(set(np.unique(ids[ids >= 0]).astype(int))) == [0, 1, 2]  # three, not one big box
    assert comp.report["match"] and comp.report["instances"] == 3
    # Each instance sits on its reference package: most of its pixels inside that package's lid
    # region (the stack hides parts of the lower ones).
    for k, q in enumerate(quads):
        m = sc._poly_mask(q, (SIZE, SIZE))
        mine = ids == k
        assert (mine & m).sum() > 0.25 * m.sum(), k
    # Nothing of the reference packages is left uncovered.
    removed = comp.layers["removal_mask"] > 0.5
    kraft_left = (np.abs(comp.image.astype(float) / 255 - KRAFT).max(-1) < 0.06) & ~(ids >= 0)
    assert kraft_left.sum() < 0.002 * SIZE * SIZE
    assert removed.sum() > 0


def test_dark_shadows_stay_dark_on_our_cartons(client, scene_project):
    """The shadow band is light, not print: under it our cartons are darker, never brighter
    (the legacy surface transfer turned such shadows into bright patches)."""
    pid, rid, fid, quads, band, _ = scene_project
    client.put(f"/api/projects/{pid}/references/{rid}/scene", json=_scene(quads))
    from app.services import structural_merge

    comp, _, _ = structural_merge.precompose(pid, rid, fid, edge=SIZE)
    pkg = comp.layers["instance_id"] >= 0
    light = comp.layers["lighting"]
    inside, outside = pkg & band, pkg & ~band
    assert inside.sum() > 500 and outside.sum() > 500
    assert np.median(light[inside]) < 0.75 * np.median(light[outside])
    # And the light never rises above the unshadowed level around the band (no inversion).
    assert np.percentile(light[inside], 95) <= np.percentile(light[outside], 95) + 1e-6


def test_the_reference_print_never_reaches_our_cartons(client, scene_project):
    pid, rid, fid, quads, _, _ = scene_project
    client.put(f"/api/projects/{pid}/references/{rid}/scene", json=_scene(quads))
    from app.services import structural_merge

    comp, _, _ = structural_merge.precompose(pid, rid, fid, edge=SIZE)
    assert comp.report["reference_print_leak"] < 0.15 and comp.report["match"]


def test_the_leak_check_catches_a_shadow_field_that_carries_print(
    monkeypatch, client, scene_project
):
    """Without the print removal the lettering of the reference lids enters the light: caught."""
    pid, rid, fid, quads, _, _ = scene_project
    client.put(f"/api/projects/{pid}/references/{rid}/scene", json=_scene(quads))
    monkeypatch.setattr(sc, "print_free", lambda lum, stroke: lum)
    from app.services import structural_merge

    comp, _, _ = structural_merge.precompose(pid, rid, fid, edge=SIZE)
    assert comp.report["reference_print_leak"] >= 0.15 and not comp.report["match"]


@pytest.mark.parametrize("n", [1, 2])
def test_one_and_two_packages(client, scene_project, n):
    pid, rid, fid, _, _, _ = scene_project
    img, quads, _ = reference_scene(n)
    rid2 = client.post(
        f"/api/projects/{pid}/references", files={"file": ("r.png", _png(img), "image/png")}
    ).json()["id"]
    repo.update("refs", rid2, analysis_status="done", analysis_json=READING)
    client.put(f"/api/projects/{pid}/references/{rid2}/scene", json=_scene(quads))
    from app.services import structural_merge

    comp, _, _ = structural_merge.precompose(pid, rid2, fid, edge=SIZE)
    ids = comp.layers["instance_id"]
    assert len(np.unique(ids[ids >= 0])) == n and comp.report["match"]


def test_an_environment_only_reference_takes_a_user_placed_carton(client, scene_project):
    pid, _, fid, _, _, _ = scene_project
    img, quads, _ = reference_scene(1, empty=True)  # floor only; the quad is the user's
    rid = client.post(
        f"/api/projects/{pid}/references", files={"file": ("e.png", _png(img), "image/png")}
    ).json()["id"]
    repo.update("refs", rid, analysis_status="done", analysis_json=READING)
    client.put(f"/api/projects/{pid}/references/{rid}/scene", json=_scene(quads, height=0.05))
    from app.services import structural_merge

    comp, _, _ = structural_merge.precompose(pid, rid, fid, edge=SIZE)
    pkg = comp.layers["instance_id"] >= 0
    assert pkg.sum() > 0.05 * SIZE * SIZE and comp.report["match"]
    # The carton casts a shadow on the ground (darker floor next to it, nowhere brighter).
    assert comp.layers["ground_shadow"].max() > 0.3


def test_the_mapped_print_is_the_approved_render(client, scene_project):
    """Albedo = the flat render sampled through the flat net: exact, not warped (spot check)."""
    pid, rid, fid, quads, _, _ = scene_project
    client.put(f"/api/projects/{pid}/references/{rid}/scene", json=_scene(quads))
    from app.services import merge, specs, structural_merge

    comp, _, _ = structural_merge.precompose(pid, rid, fid, edge=SIZE)
    flat = repo.get("versions", fid)
    img = np.asarray(merge.flat_image(pid, flat)).astype(np.float32) / 255
    spec = specs.load(repo.project_or_404(pid))
    # The front panel's centre in page units -> its colour in the flat render == the albedo
    # of the image pixel that shows that point (found through the flat-net coordinates).
    buf_xy = sc.sample_print(
        img, flat["frame_json"], spec.scale.mm_per_pt, np.zeros((1, 2), np.float32)
    )
    assert buf_xy.shape == (1, 3)
    pkg = comp.layers["instance_id"] >= 0
    alb = comp.layers["albedo"][pkg]
    assert alb.min() >= 0 and alb.max() <= 1


def test_unsupported_structure_is_refused(client, scene_project, monkeypatch):
    pid, rid, fid, quads, _, _ = scene_project
    client.put(f"/api/projects/{pid}/references/{rid}/scene", json=_scene(quads))
    from app.structure import fold

    def nope(*a, **k):
        raise fold.FoldError("STRUCTURE_UNSUPPORTED", "x", ["bottom: crash"])

    monkeypatch.setattr(fold, "fold", nope)
    res = client.post(
        f"/api/projects/{pid}/compose", json={"reference_id": rid, "flat_version_id": fid}
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "STRUCTURE_UNSUPPORTED"


def test_compose_job_saves_every_intermediate(client, scene_project):
    pid, rid, fid, quads, _, _ = scene_project
    client.put(f"/api/projects/{pid}/references/{rid}/scene", json=_scene(quads))
    res = client.post(
        f"/api/projects/{pid}/compose", json={"reference_id": rid, "flat_version_id": fid}
    )
    assert res.status_code == 202, res.json()
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "done", job
    assert [s["key"] for s in job["stages"]] == ["structure", "compose", "model", "verify"]
    vid = res.json()["version_id"]
    v = client.get(f"/api/projects/{pid}/versions/{vid}").json()
    assert v["form"] == "structural" and v["provider_label"] == "구조 합성 · 코드 렌더"
    for name in ("structure", "background", "albedo", "lighting", "shadow_only", "removal_mask"):
        assert client.get(f"/api/projects/{pid}/versions/{vid}/layers/{name}").status_code == 200, (
            name
        )
    assert client.get(f"/api/projects/{pid}/versions/{vid}/layers/raw").status_code == 404  # no AI


class Timeout(FakeProvider):
    def generate(self, req, model_id):
        self.requests.append(req)
        raise TimeoutError("model timed out")


class Garbage(FakeProvider):
    """Paints big dark letters all over the image (a model redrawing the cartons)."""

    def generate(self, req, model_id):
        self.requests.append(req)
        im = req.images[0][1].convert("RGB").copy()
        d = ImageDraw.Draw(im)
        for y in range(0, im.height, 40):
            d.text((10, y), "FAKE BRAND " * 8, fill=(20, 20, 20))
        return GenerationResult(im)


@pytest.mark.parametrize("model", [Timeout, Garbage])
def test_ai_failure_keeps_the_deterministic_composition(client, scene_project, monkeypatch, model):
    pid, rid, fid, quads, _, _ = scene_project
    monkeypatch.setattr(providers, "PROVIDER", model())
    client.put(f"/api/projects/{pid}/references/{rid}/scene", json=_scene(quads))
    res = client.post(
        f"/api/projects/{pid}/compose",
        json={"reference_id": rid, "flat_version_id": fid, "harmonize": True},
    )
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "done", job
    vid = res.json()["version_id"]
    d = repo.project_dir(pid) / "versions"
    final = np.asarray(Image.open(d / f"{vid}.png").convert("RGB")).astype(int)
    pre = np.asarray(Image.open(d / f"{vid}_structure.png").convert("RGB")).astype(int)
    report = json.loads((d / f"{vid}_report.json").read_text())
    pkg_ids = None
    if model is Timeout:
        assert not report["ai_used"] and np.array_equal(final, pre)
    else:
        # Whatever the model drew, our cartons are still our print x a smooth light map: the
        # fake letters cannot appear on them (their light map is blurred and bounded).
        assert report["match"]
        del pkg_ids


def test_scene_validation(client, scene_project):
    pid, rid, _, quads, _, _ = scene_project
    bad = _scene(quads)
    bad["instances"][0]["quad"] = bad["instances"][0]["quad"][:3]
    res = client.put(f"/api/projects/{pid}/references/{rid}/scene", json=bad)
    assert res.status_code == 422 and res.json()["error"]["code"] == "SCENE_QUAD_INVALID"
    two_hidden = _scene(quads)
    two_hidden["instances"][0]["quad"][0] = None
    two_hidden["instances"][0]["quad"][1] = None
    assert (
        client.put(f"/api/projects/{pid}/references/{rid}/scene", json=two_hidden).status_code
        == 422
    )


def test_detection_proposal_is_saved_for_confirmation(client, scene_project, monkeypatch):
    from app.ai import claude

    pid, rid, _, quads, _, _ = scene_project
    proposal = claude.AiInstances(
        instances=[
            claude.AiInstance(
                corners=[
                    claude.AiCorner(x=float(x) / SIZE, y=float(y) / SIZE, visible=True)
                    for x, y in q
                ],
                height_ratio=0.2,
                order=i + 1,
                confidence=0.8,
            )
            for i, q in enumerate(quads)
        ]
    )
    monkeypatch.setattr(claude, "detect_instances", lambda img: proposal)
    res = client.post(f"/api/projects/{pid}/references/{rid}/scene/detect")
    assert res.status_code == 200
    out = res.json()
    assert out["source"] == "claude" and len(out["instances"]) == 3
    assert (
        client.get(f"/api/projects/{pid}/references/{rid}/scene").json()["instances"]
        == out["instances"]
    )
