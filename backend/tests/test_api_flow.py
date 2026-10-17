"""End-to-end API flows without real AI providers."""

import io

import numpy as np
from PIL import Image

from app.ai import providers
from app.ai.providers.base import GenerationResult
from tests.conftest import fixture_bytes, upload, wait_job


def test_upload_rejections(client):
    pid = client.post("/api/projects", json={"name": "x"}).json()["id"]
    for name, code in [("corrupt", "PDF_INVALID"), ("encrypted", "PDF_ENCRYPTED")]:
        res = client.post(
            f"/api/projects/{pid}/upload",
            files={"file": (f"{name}.pdf", fixture_bytes(name), "application/pdf")},
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == code
        assert res.json()["error"]["hint"]


def test_named_pdf_reaches_ready(client):
    pid, job = upload(client, "named_spot")
    assert job["status"] == "done", job
    assert [s["status"] for s in job["stages"]] == ["done"] * 6
    project = client.get(f"/api/projects/{pid}").json()
    assert project["status"] == "ready"
    assert project["source"]["sha256"]

    # The original is stored byte-for-byte.
    assert client.get(f"/api/projects/{pid}/source/file").content == fixture_bytes("named_spot")

    # The deterministic flat render is on black, like the look of step 2.
    thumb = client.get(f"/api/projects/{pid}/thumbnail")
    assert thumb.status_code == 200
    corner = np.asarray(Image.open(io.BytesIO(thumb.content)).convert("RGB"))[0, 0]
    assert corner.max() < 16, corner


def test_review_flow_for_unnamed_dieline(client):
    pid, job = upload(client, "unnamed_mixed")
    assert job["result"]["review"] is True
    assert client.get(f"/api/projects/{pid}").json()["status"] == "needs_review"
    spec = client.get(f"/api/projects/{pid}/specification").json()
    pending = [p for p in spec["paths"] if p["status"] == "unresolved"]
    assert len(pending) == 1 and pending[0]["suggested_cls"] == "artwork"

    res = client.post(f"/api/projects/{pid}/specification/confirm")
    assert res.status_code == 409 and res.json()["error"]["code"] == "REVIEW_PENDING"

    res = client.patch(
        f"/api/projects/{pid}/specification",
        json={"paths": [{"id": pending[0]["id"], "cls": "artwork"}]},
        headers={"If-Match": str(spec["version"])},
    )
    assert res.status_code == 200
    stale = client.patch(
        f"/api/projects/{pid}/specification",
        json={"panel_names": []},
        headers={"If-Match": str(spec["version"])},
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "SPEC_CONFLICT"

    job = wait_job(
        client, client.post(f"/api/projects/{pid}/specification/confirm").json()["job_id"]
    )
    assert job["status"] == "done", job
    assert client.get(f"/api/projects/{pid}").json()["status"] == "ready"


def test_manual_outline_for_pdf_without_cut(client):
    pid, job = upload(client, "artwork_only")
    spec = client.get(f"/api/projects/{pid}/specification").json()
    assert spec["review"]["reasons"] == ["cut_missing"]
    w, h = spec["page"]["width_pt"], spec["page"]["height_pt"]
    pts = [[w * 0.1, h * 0.2], [w * 0.9, h * 0.2], [w * 0.9, h * 0.8], [w * 0.1, h * 0.8]]
    res = client.patch(f"/api/projects/{pid}/specification", json={"manual_cut": {"points": pts}})
    assert res.json()["review"]["reasons"] == []
    job = wait_job(
        client, client.post(f"/api/projects/{pid}/specification/confirm").json()["job_id"]
    )
    assert job["status"] == "done", job


def test_multipage_asks_for_page(client):
    pid, job = upload(client, "multipage")
    assert job["result"] == {"needs_page": True, "page_count": 2}
    assert client.get(f"/api/projects/{pid}").json()["status"] == "needs_page"
    job = wait_job(
        client, client.post(f"/api/projects/{pid}/analyze", json={"page": 1}).json()["job_id"]
    )
    assert job["status"] == "done"
    assert client.get(f"/api/projects/{pid}").json()["status"] == "ready"


def _png(color=(200, 50, 50), size=(64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def test_references_crud(client):
    pid, _ = upload(client, "named_spot")
    ids = []
    for c in [(255, 0, 0), (0, 255, 0)]:
        res = client.post(
            f"/api/projects/{pid}/references", files={"file": ("r.png", _png(c), "image/png")}
        )
        assert res.status_code == 201
        assert res.json()["analysis_status"] == "skipped"  # no Claude key in tests
        assert res.json()["analysis"] is None
        ids.append(res.json()["id"])
    bad = client.post(
        f"/api/projects/{pid}/references", files={"file": ("x.png", b"nope", "image/png")}
    )
    assert bad.json()["error"]["code"] == "REFERENCE_INVALID"
    assert client.get(f"/api/projects/{pid}/references/{ids[0]}/image").status_code == 200
    assert client.delete(f"/api/projects/{pid}/references/{ids[1]}").status_code == 204
    assert [r["id"] for r in client.get(f"/api/projects/{pid}/references").json()] == ids[:1]


def test_ai_features_report_missing_keys(client):
    pid, _ = upload(client, "named_spot")
    res = client.post(f"/api/projects/{pid}/generate", json={})
    assert res.status_code == 503 and res.json()["error"]["code"] == "PROVIDER_UNAVAILABLE"
    rid = client.post(
        f"/api/projects/{pid}/references", files={"file": ("r.png", _png(), "image/png")}
    ).json()["id"]
    res = client.post(f"/api/projects/{pid}/references/{rid}/analyze")
    assert res.status_code == 503 and res.json()["error"]["code"] == "CLAUDE_UNAVAILABLE"


class FakeProvider:
    """Returns a scene that also scribbles over the package, like a misbehaving model."""

    name = "gemini"

    def __init__(self):
        self.requests = []

    def available(self):
        return True

    def generate(self, req, model_id):
        self.requests.append(req)
        rng = np.random.default_rng(0)
        noise = rng.integers(0, 255, (req.height // 2, req.width // 2, 3), dtype=np.uint8)
        return GenerationResult(Image.fromarray(noise), {"fake": True})


class ShiftingProvider(FakeProvider):
    """Returns Image 1 with everything moved a few pixels: like a model that redrew the print."""

    def generate(self, req, model_id):
        self.requests.append(req)
        moved = np.roll(np.asarray(req.images[0][1].convert("RGB")), (3, 4), axis=(0, 1))
        return GenerationResult(Image.fromarray(moved), {"fake": True})


def test_a_result_that_alters_the_print_is_never_delivered(client, monkeypatch):
    from app.services import pipeline

    # Simulate a broken restore: the model's own (moved) image reaches the package.
    def leaky(base_img, sil, raw, pid, spec, long_edge):
        h, w = base_img.shape[:2]
        scene = np.asarray(pipeline.cover(raw, w, h))
        return pipeline.Composited(scene, base_img[..., :3], np.ones((h, w, 3), np.float32))

    monkeypatch.setattr(providers, "PROVIDER", ShiftingProvider())
    monkeypatch.setattr(pipeline, "composite", leaky)
    pid, _ = upload(client, "named_spot")
    res = client.post(f"/api/projects/{pid}/generate", json={})
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "failed" and job["error"]["code"] == "ARTWORK_MISMATCH"
    [v] = client.get(f"/api/projects/{pid}/history").json()["versions"]
    assert v["status"] == "failed" and v["error"]["code"] == "ARTWORK_MISMATCH"
    assert v["image_url"] is None and v["download_url"] is None


def test_flat_render_protects_artwork(client, monkeypatch):
    from app.services.pipeline import FLAT_LOOK_IMAGE

    fake = FakeProvider()
    monkeypatch.setattr(providers, "PROVIDER", fake)
    pid, _ = upload(client, "named_spot")
    res = client.post(f"/api/projects/{pid}/generate", json={})
    assert res.status_code == 202, res.json()
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "done", (
        job.get("error"),
        client.get(f"/api/projects/{pid}/history").json()["versions"][0]["verify"],
    )
    assert [s["key"] for s in job["stages"]] == ["render", "model", "composite", "verify"]

    # Image 1 = our exact print, Image 2 = the fixed look reference; Master Prompt A.
    req = fake.requests[0]
    assert [label.split(" — ")[0] for label, _ in req.images] == ["Image 1", "Image 2"]
    look = np.asarray(Image.open(FLAT_LOOK_IMAGE).convert("RGB"))
    assert np.array_equal(np.asarray(req.images[1][1]), look)
    assert req.prompt.startswith("# MASTER PROMPT — FIGMA TO PHOTOREALISTIC PACKAGING DIELINE")
    assert "$" not in req.prompt

    [v] = client.get(f"/api/projects/{pid}/history").json()["versions"]
    assert v["number"] == 1 and v["status"] == "done"
    assert v["kind"] == "flat" and v["legacy"] is False
    # Even though the fake model painted over everything, the print is the PDF render;
    # only the scene's broad light and the board's surface may reach it.
    assert v["verify"]["match"] is True and v["verify"]["detail_match"] >= 0.98, str(v["verify"])
    assert client.get(f"/api/projects/{pid}/versions/{v['id']}").json()["id"] == v["id"]
    dl = client.get(v["download_url"])
    assert dl.status_code == 200 and dl.headers["content-type"] == "image/png"
    assert 'filename="named_spot_v1_flat.png"' in dl.headers["content-disposition"]
    assert client.delete(f"/api/projects/{pid}/versions/{v['id']}").status_code == 204
    assert client.get(f"/api/projects/{pid}/history").json()["versions"] == []


def test_project_lifecycle(client):
    pid, _ = upload(client, "named_spot")
    assert (
        client.patch(f"/api/projects/{pid}", json={"name": "새 이름"}).json()["name"] == "새 이름"
    )
    assert len(client.get("/api/projects").json()) == 1
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/projects/{pid}").json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_idempotent_create(client):
    h = {"Idempotency-Key": "abc"}
    a = client.post("/api/projects", json={"name": "x"}, headers=h).json()
    b = client.post("/api/projects", json={"name": "x"}, headers=h).json()
    assert a["id"] == b["id"]


def _old_version(pid: str, vid: str, **fields) -> dict:
    """A version row as an earlier version of the app wrote it."""
    from app.storage import repo

    return repo.insert(
        "versions",
        {
            "id": vid,
            "project_id": pid,
            "number": 1,
            "parent_id": None,
            "status": "done",
            "provider": "openai",
            "model_id": "gpt-image-2.5-sunburst",
            "mode": "artwork_locked",
            "settings_json": {"material": {"preset": "kraft", "gsm": 350}, "finishes": []},
            "reference_ids": [],
            "spec_version": 1,
            "job_id": None,
            "usage_json": {"cost_krw": 320},
            "verify_json": {"protected_px": 1, "changed_px": 0, "changed_ratio": 0, "match": True},
            "frame_json": {"origin": [0, 0], "size": [100, 100]},
            "error_json": None,
            "starred": 0,
            "name": None,
            "deleted_at": None,
            "created_at": repo.now(),
            **fields,
        },
    )


def test_restart_fails_versions_that_were_generating(client):
    from app.jobs import runner

    pid, _ = upload(client, "named_spot")
    _old_version(pid, "ver_orphan", status="running", provider="gemini", job_id="job_gone")
    runner.reap_orphans()
    [v] = client.get(f"/api/projects/{pid}/history").json()["versions"]
    assert v["status"] == "failed" and v["error"]["code"] == "JOB_INTERRUPTED"


def test_old_versions_still_load_as_legacy(client):
    pid, _ = upload(client, "named_spot")
    _old_version(pid, "ver_openai")
    _old_version(pid, "ver_scene", number=2, provider="gemini", kind="scene", status="failed")
    a, b = client.get(f"/api/projects/{pid}/history").json()["versions"]
    assert a["legacy"] and a["provider_label"] == "openai (legacy)" and a["kind"] == "flat"
    assert b["legacy"] and b["kind"] == "merge" and b["image_url"] is None
