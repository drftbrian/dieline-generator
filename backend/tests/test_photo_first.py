"""Step 3, photo-first mode over the API: upload an AI photo, set its visible faces, correct it.

The "AI photo" is the project's own front panel warped into a studio shot with a hallucinated
word painted on it. No model is called (the provider would raise)."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.ai import providers
from app.services import photo_first, specs
from app.storage import repo
from app.typography import register as rg
from app.typography import restore
from tests.conftest import upload, wait_job

SIZE = (700, 800)
QUAD = np.array([[200.0, 140.0], [520.0, 165.0], [510.0, 690.0], [210.0, 720.0]])


class NoModel:
    def available(self):
        return True

    def generate(self, *a, **k):
        raise AssertionError("photo-first correction must not call a model")


def _photo(pdf: bytes, bbox, quad=QUAD) -> bytes:
    w, h = SIZE
    tex = restore.render_panel(pdf, bbox, (600, round(600 * (bbox[3] - bbox[1]) / (bbox[2] - bbox[0]))))
    H = rg.homography(quad)
    xs, ys = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
    u, v = rg.apply_h(np.linalg.inv(H), xs, ys)
    inside = (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
    img = np.ones((h, w, 3), np.float32) * 0.7
    face = rg.sample(tex, u * tex.shape[1], v * tex.shape[0]) * (1 - 0.2 * xs / w)[..., None]
    img = np.where(inside[..., None], face, img)
    out = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
    ImageDraw.Draw(out).text((260, 430), "FL0RA", fill=(250, 250, 250), font_size=48)  # hallucinated
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def photo_project(client, monkeypatch):
    monkeypatch.setattr(providers, "PROVIDER", NoModel())
    pid, job = upload(client, "named_spot")
    assert job["status"] == "done", job
    spec = specs.load(repo.project_or_404(pid))
    front = photo_first.default_faces(spec)[-1]["panel"]
    panel = next(p for p in spec.panels if p.id == front)
    _man, pdf = photo_first.source(pid, spec)
    data = _photo(pdf, panel.bbox)
    res = client.post(f"/api/projects/{pid}/candidates", files={"file": ("ai.png", data, "image/png")})
    assert res.status_code == 201, res.json()
    return pid, res.json(), front, data


def _faces(panel, quad=QUAD, jitter=(8, -6)):
    q = (quad + np.array(jitter)) / np.array(SIZE)
    return {"faces": [{"panel": panel, "quad": q.round(5).tolist()}]}


def test_candidate_upload_keeps_the_photo_and_proposes_faces(client, photo_project):
    pid, cand, front, data = photo_project
    assert cand["width"] == SIZE[0] and cand["faces"]
    assert any(f["panel"] == front for f in cand["faces"])
    assert client.get(cand["image_url"]).content == data  # byte for byte
    assert client.get(cand["thumb_url"]).status_code == 200
    panels = client.get(f"/api/projects/{pid}/candidates/panels").json()
    assert front in {p["id"] for p in panels}
    assert [c["id"] for c in client.get(f"/api/projects/{pid}/candidates").json()] == [cand["id"]]


def test_faces_are_validated(client, photo_project):
    pid, cand, front, _ = photo_project
    url = f"/api/projects/{pid}/candidates/{cand['id']}/faces"
    spec = specs.load(repo.project_or_404(pid))
    flap = next(p.id for p in spec.panels if p.id not in {q.id for q in photo_first.main_panels(spec)})
    assert client.put(url, json=_faces(flap)).json()["error"]["code"] == "FACE_PANEL_INVALID"
    dup = _faces(front)
    dup["faces"] *= 2
    assert client.put(url, json=dup).json()["error"]["code"] == "FACE_PANEL_DUPLICATE"
    bad = {"faces": [{"panel": front, "quad": [[0, 0], [1, 0], [1, 1]]}]}
    assert client.put(url, json=bad).json()["error"]["code"] == "FACE_QUAD_INVALID"
    assert client.put(url, json={"faces": []}).json()["error"]["code"] == "FACES_EMPTY"


def test_upload_rejects_non_images(client, photo_project):
    pid, *_ = photo_project
    res = client.post(f"/api/projects/{pid}/candidates", files={"file": ("x.png", b"not an image", "image/png")})
    assert res.status_code == 400 and res.json()["error"]["code"] == "CANDIDATE_INVALID"


def test_correction_job_makes_a_version_and_keeps_the_raw(client, photo_project):
    pid, cand, front, data = photo_project
    assert client.put(f"/api/projects/{pid}/candidates/{cand['id']}/faces", json=_faces(front)).status_code == 200
    out = client.post(f"/api/projects/{pid}/typography", json={"candidate_id": cand["id"]}).json()
    job = wait_job(client, out["job_id"], timeout=180)
    assert job["status"] == "done", job
    assert [s["key"] for s in job["stages"]] == ["register", "verify", "correct", "save"]
    v = client.get(f"/api/projects/{pid}/versions/{out['version_id']}").json()
    assert v["kind"] == "merge" and v["form"] == "photo_first"
    assert v["provider_label"] == "AI 사진 · Figma 글자 교정"
    typo = v["verify"]["typography"]
    assert typo["status"] in ("ok", "review_required")
    assert typo["faces"][0]["registration"]["ok"]
    for layer in ("raw", "strict", "repair_preview", "repair_masks"):
        r = client.get(f"/api/projects/{pid}/versions/{out['version_id']}/layers/{layer}")
        assert r.status_code == 200, layer
    raw = np.asarray(Image.open(io.BytesIO(client.get(
        f"/api/projects/{pid}/versions/{out['version_id']}/layers/raw").content)))
    assert np.array_equal(raw, np.asarray(Image.open(io.BytesIO(data)).convert("RGB")))
    assert client.get(cand["image_url"]).content == data  # the candidate itself never changes
    final = np.asarray(Image.open(io.BytesIO(client.get(v["image_url"]).content)).convert("RGB"))
    assert final.shape == raw.shape
    word = (slice(435, 480), slice(262, 400))  # the hallucinated word: replaced by our print
    assert np.abs(final[word].astype(int) - raw[word].astype(int)).mean() > 10


def test_unregistered_faces_fail_without_touching_the_photo(client, photo_project):
    pid, cand, front, data = photo_project
    far = np.array([[20.0, 20.0], [120.0, 20.0], [120.0, 120.0], [20.0, 120.0]])  # plain backdrop
    client.put(f"/api/projects/{pid}/candidates/{cand['id']}/faces", json=_faces(front, far, (0, 0)))
    out = client.post(f"/api/projects/{pid}/typography", json={"candidate_id": cand["id"]}).json()
    job = wait_job(client, out["job_id"], timeout=180)
    assert job["status"] == "failed"
    v = client.get(f"/api/projects/{pid}/versions/{out['version_id']}").json()
    assert v["status"] == "failed" and v["error"]["code"] == "TYPOGRAPHY_NOT_REGISTERED"
    assert client.get(cand["image_url"]).content == data


def test_candidate_delete(client, photo_project):
    pid, cand, *_ = photo_project
    assert client.delete(f"/api/projects/{pid}/candidates/{cand['id']}").status_code == 204
    assert client.get(cand["image_url"]).status_code == 404
