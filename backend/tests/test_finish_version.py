"""Finished flat versions: a flat render with the finishing revision baked in as a new version,
optionally with "AI 사실감" (the model's picture of each finish area only lends a bounded
light/texture map inside the finish's own mask). The source render never changes."""

import hashlib
import json

import numpy as np
from PIL import Image

from app.ai import providers
from app.ai.providers.base import GenerationResult
from app.services import finish_realism
from app.storage import repo
from tests.conftest import wait_job
from tests.test_api_flow import FakeProvider
from tests.test_assets import project  # noqa: F401  (fixture: synthetic Figma tree)


class Sheen(FakeProvider):
    """A well-behaved model: Image 1 back with a soft diagonal sheen (same shapes)."""

    def generate(self, req, model_id):
        self.requests.append(req)
        img = np.asarray(req.images[0][1].convert("RGB")).astype(np.float32)
        h, w = img.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w]
        light = (0.9 + 0.2 * (xx / w + yy / h) / 2)[..., None]
        return GenerationResult(Image.fromarray(np.clip(img * light, 0, 255).astype(np.uint8)))


class Moved(FakeProvider):
    """Redraws the area shifted: the shapes no longer line up with ours."""

    def generate(self, req, model_id):
        self.requests.append(req)
        img = np.asarray(req.images[0][1].convert("RGB"))
        return GenerationResult(Image.fromarray(np.roll(img, img.shape[1] // 5, axis=1)))


def _ready(client, pid):
    res = client.post(f"/api/projects/{pid}/generate", json={})
    assert wait_job(client, res.json()["job_id"])["status"] == "done"
    vid = res.json()["version_id"]
    gold = {"finish": "foil.gold", "targets": [{"kind": "asset", "id": "1:2"}]}
    put = client.put(
        f"/api/projects/{pid}/finishing", json={"base_revision": 0, "assignments": [gold]}
    )
    assert put.status_code == 200
    path = repo.project_dir(pid) / "versions" / f"{vid}.png"
    return vid, path, hashlib.sha256(path.read_bytes()).hexdigest()


def _finish(client, pid, vid, **body):
    res = client.post(f"/api/projects/{pid}/versions/{vid}/finish", json=body)
    assert res.status_code == 202, res.json()
    job = wait_job(client, res.json()["job_id"])
    v = client.get(f"/api/projects/{pid}/versions/{res.json()['version_id']}").json()
    return job, v


def _img(pid, vid, suffix=""):
    path = repo.project_dir(pid) / "versions" / f"{vid}{suffix}.png"
    return np.asarray(Image.open(path).convert("RGB")).astype(int)


def test_finished_version_bakes_in_the_preview(client, project):  # noqa: F811
    pid = project
    vid, path, sha = _ready(client, pid)
    job, v = _finish(client, pid, vid)
    assert job["status"] == "done", job.get("error")
    assert [s["key"] for s in job["stages"]] == ["compose", "model", "verify"]
    assert v["finishing"]["source_version_id"] == vid and v["finishing"]["ai"] is False
    assert v["provider_label"] == "후가공 · 코드 렌더"
    assert v["verify"]["match"] and v["verify"]["checks"]["outside_unchanged"]
    # Same pixels as the preview overlay over the source.
    out, src = _img(pid, v["id"]), _img(pid, vid)
    preview = client.get(f"/api/projects/{pid}/finishing/preview", params={"version_id": vid})
    x, y, w, h, _, _ = (int(n) for n in preview.headers["x-overlay-rect"].split(","))
    import io

    ov = np.asarray(Image.open(io.BytesIO(preview.content)).convert("RGBA")).astype(int)
    expect = src.copy()
    a = ov[..., 3] > 0
    expect[y : y + h, x : x + w][a] = ov[..., :3][a]
    assert np.array_equal(out, expect)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha  # source untouched
    # A finished version is not a finishing source again, nor previewed with finishes.
    again = client.post(f"/api/projects/{pid}/versions/{v['id']}/finish", json={})
    assert again.status_code == 409 and again.json()["error"]["code"] == "FINISH_SOURCE_INVALID"
    prev = client.get(f"/api/projects/{pid}/finishing/preview", params={"version_id": v["id"]})
    assert prev.status_code == 404


def test_ai_realism_changes_only_inside_the_finish(client, project, monkeypatch):  # noqa: F811
    fake = Sheen()
    monkeypatch.setattr(providers, "PROVIDER", fake)
    pid = project
    vid, path, sha = _ready(client, pid)
    job, v = _finish(client, pid, vid, ai=True, strength=1.0)
    assert job["status"] == "done", job.get("error")
    assert v["verify"]["ai_used"] is True, v["verify"]
    assert "AI 사실감" in v["provider_label"]
    det = _img(pid, v["id"], "_deterministic")
    out, src = _img(pid, v["id"]), _img(pid, vid)
    assert not np.array_equal(out, det)  # the model's light reached the foil
    # Outside what the deterministic finish changed, it is the source, pixel for pixel.
    changed = np.abs(det - src).max(-1) > 0
    assert np.array_equal(out[~changed], src[~changed])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
    # The model saw our render of the area first; the raw prompt names the finish.
    req = fake.requests[0]
    assert "Gold foil" in req.prompt and req.images[0][0].startswith("Image 1")
    manifest = json.loads(
        (repo.project_dir(pid) / "versions" / f"{v['id']}_finishing.json").read_text()
    )
    assert manifest["areas"][0]["used"] is True and manifest["finishing_revision"] == 1


def test_misaligned_ai_picture_keeps_the_deterministic_finish(client, project, monkeypatch):  # noqa: F811
    monkeypatch.setattr(providers, "PROVIDER", Moved())
    pid = project
    vid, _, _ = _ready(client, pid)
    job, v = _finish(client, pid, vid, ai=True)
    assert job["status"] == "done"
    assert v["verify"]["ai_used"] is False and v["verify"]["ai_reason"] == "areas_rejected"
    assert np.array_equal(_img(pid, v["id"]), _img(pid, v["id"], "_deterministic"))


def test_no_finishes_is_refused(client, project):  # noqa: F811
    pid = project
    res = client.post(f"/api/projects/{pid}/generate", json={})
    assert wait_job(client, res.json()["job_id"])["status"] == "done"
    out = client.post(f"/api/projects/{pid}/versions/{res.json()['version_id']}/finish", json={})
    assert out.status_code == 409 and out.json()["error"]["code"] == "FINISHING_EMPTY"


def test_reference_photos_match_hangul_names(tmp_path, monkeypatch):
    import unicodedata

    from app.config import get_settings

    for name in ("후가공_금박.jpg", "후가공_은박.jpg"):
        Image.new("RGB", (8, 8)).save(tmp_path / unicodedata.normalize("NFD", name))
    monkeypatch.setattr(get_settings(), "finish_reference_dir", tmp_path)
    got = finish_realism.reference_photos("foil.gold")
    assert [n for n, _ in got] == ["후가공_금박.jpg"]
    assert finish_realism.reference_photos("surface.matte_lamination") == []


class Washed(FakeProvider):
    """Same shapes, but flattened tones (a dull, washed-out foil): further from real photos."""

    def generate(self, req, model_id):
        self.requests.append(req)
        img = np.asarray(req.images[0][1].convert("RGB")).astype(np.float32)
        return GenerationResult(Image.fromarray((0.55 * img + 0.45 * 190).astype(np.uint8)))


def test_ai_that_is_not_closer_to_real_photos_is_not_adopted(client, project, monkeypatch):  # noqa: F811
    monkeypatch.setattr(providers, "PROVIDER", Washed())
    pid = project
    vid, _, _ = _ready(client, pid)
    job, v = _finish(client, pid, vid, ai=True, strength=1.0)
    assert job["status"] == "done"
    manifest = json.loads(
        (repo.project_dir(pid) / "versions" / f"{v['id']}_finishing.json").read_text()
    )
    area = manifest["areas"][0]
    assert area["used"] is False and area["reason"] == "not_better", area
    before, after = area["photo_distance"]
    assert after > before
