"""Step 3: our approved flat render (or the carton folded from it) in place of the reference's
packaging, with a fake image model. The print is always composited back and verified."""

import io

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from app.ai import claude, providers
from app.services import merge
from app.storage import repo
from tests.conftest import upload, wait_job
from tests.test_api_flow import FakeProvider
from tests.test_prompts import READING


def _ref_png() -> bytes:
    rng = np.random.default_rng(3)
    buf = io.BytesIO()
    Image.fromarray(rng.integers(0, 255, (90, 120, 3), dtype=np.uint8)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def ready(client, monkeypatch):
    """A project with an approved flat render and a reference Claude has read."""
    fake = FakeProvider()
    monkeypatch.setattr(providers, "PROVIDER", fake)
    pid, _ = upload(client, "named_spot")
    job = wait_job(client, client.post(f"/api/projects/{pid}/generate", json={}).json()["job_id"])
    assert job["status"] == "done", job
    [flat] = client.get(f"/api/projects/{pid}/history").json()["versions"]
    png = _ref_png()
    rid = client.post(
        f"/api/projects/{pid}/references", files={"file": ("ref.png", png, "image/png")}
    ).json()["id"]
    repo.update("refs", rid, analysis_status="done", analysis_json=READING)
    fake.requests.clear()
    return pid, rid, flat, fake, png


def _merge(client, pid, **body):
    return client.post(f"/api/projects/{pid}/merge", json=body)


@pytest.mark.parametrize("form", ["flat", "folded"])
def test_merge_sends_our_render_and_the_reference_and_keeps_the_print(client, ready, form):
    pid, rid, flat, fake, png = ready
    ref = client.get(f"/api/projects/{pid}/references").json()[0]
    assert ref["analysis_status"] == "done" and ref["analysis"]["packaging_form"] == "folded"

    res = _merge(client, pid, reference_id=rid, form=form)
    assert res.status_code == 202, res.json()
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "done", job
    assert [s["key"] for s in job["stages"]] == ["prepare", "model", "composite", "verify"]

    req = fake.requests[0]
    labels = [label.split(" — ")[0] for label, _ in req.images]
    assert labels == (
        ["Image A", "Image B"] if form == "flat" else ["Image A", "Image B", "Image C"]
    )
    # The reference goes to the model as uploaded: same pixels, same size.
    sent = np.asarray(req.images[1][1])
    assert np.array_equal(sent, np.asarray(Image.open(io.BytesIO(png)).convert("RGB")))
    assert req.prompt.startswith("# MASTER PROMPT — EXACT FIGMA-TO-PACKAGING MOCKUP GENERATION")
    assert merge.FORM_RULES[form] in req.prompt
    if form == "folded":
        assert (req.width, req.height) == (2048, 1536)  # the reference's aspect (4:3)

    versions = client.get(f"/api/projects/{pid}/history").json()["versions"]
    v = versions[-1]
    assert v["kind"] == "merge" and v["form"] == form and v["legacy"] is False
    assert v["reference_id"] == rid and v["flat_version_id"] == flat["id"]
    # The fake model painted noise over everything: the delivered print is ours, verified.
    assert v["verify"]["match"] is True and v["verify"]["detail_match"] >= 0.98, v["verify"]
    vdir = repo.project_dir(pid) / "versions"
    assert (vdir / f"{v['id']}_structure.png").exists() and (vdir / f"{v['id']}_raw.png").exists()


def test_auto_form_follows_the_reading(client, ready):
    pid, rid, _, _, _ = ready
    repo.update("refs", rid, analysis_json={**READING, "packaging_form": "flat"})
    job = wait_job(client, _merge(client, pid, reference_id=rid).json()["job_id"])
    assert job["status"] == "done", job
    assert client.get(f"/api/projects/{pid}/history").json()["versions"][-1]["form"] == "flat"


def test_a_merge_whose_print_moved_is_never_delivered(client, ready, monkeypatch):
    pid, rid, _, _, _ = ready
    real = merge.composite

    def leaky(c, r, raw, size, pid_):
        comp = real(c, r, raw, size, pid_)
        comp.image = np.roll(comp.image, (2, 3), axis=(0, 1))
        return comp

    monkeypatch.setattr(merge, "composite", leaky)
    job = wait_job(client, _merge(client, pid, reference_id=rid, form="folded").json()["job_id"])
    assert job["status"] == "failed" and job["error"]["code"] == "ARTWORK_MISMATCH"
    v = client.get(f"/api/projects/{pid}/history").json()["versions"][-1]
    assert v["error"]["code"] == "ARTWORK_MISMATCH" and v["image_url"] is None
    assert (repo.project_dir(pid) / "versions" / f"{v['id']}_rejected.png").exists()


def test_a_stale_reference_returns_409(client, ready):
    pid, rid, _, _, _ = ready
    # A reading from the earlier app: other sections, roles, CMF; no schema 2.
    old = {"category": "product_packaging", "sections": [], "palette": [], "prompt_en": "x"}
    repo.update("refs", rid, analysis_json=old)
    assert client.get(f"/api/projects/{pid}/references").json()[0]["analysis_status"] == "stale"
    res = _merge(client, pid, reference_id=rid)
    assert res.status_code == 409 and res.json()["error"]["code"] == "REFERENCE_STALE"


def test_merge_needs_a_current_flat_render(client, ready):
    pid, rid, flat, _, _ = ready
    # A render from the earlier app (another look) is never the flat render of a merge.
    repo.update("versions", flat["id"], settings_json={"material": {"preset": "kraft"}})
    res = _merge(client, pid, reference_id=rid, flat_version_id=flat["id"])
    assert res.status_code == 409 and res.json()["error"]["code"] == "FLAT_VERSION_INVALID"
    res = _merge(client, pid, reference_id=rid)
    assert res.status_code == 409 and res.json()["error"]["code"] == "FLAT_VERSION_MISSING"
    res = _merge(client, pid, reference_id="ref_nope")
    assert res.status_code == 404


def test_reference_reading_matches_its_category():
    data = {k: v for k, v in READING.items() if k != "schema"}
    claude.AiReference.model_validate(data)
    wrong = {**data, "category": "person"}  # product sections under the person category
    with pytest.raises(ValidationError):
        claude.AiReference.model_validate(wrong)


def test_reference_reading_is_stored_with_its_schema(client, monkeypatch):
    from app.api import references

    pid, _ = upload(client, "named_spot")
    data = {k: v for k, v in READING.items() if k != "schema"}
    monkeypatch.setattr(claude, "available", lambda: True)
    monkeypatch.setattr(
        claude, "analyze_reference", lambda img: claude.AiReference.model_validate(data)
    )
    monkeypatch.setattr(references._pool, "submit", lambda fn, *a: fn(*a))  # run inline
    ref = client.post(
        f"/api/projects/{pid}/references", files={"file": ("r.png", _ref_png(), "image/png")}
    ).json()
    out = client.get(f"/api/projects/{pid}/references").json()[0]
    assert out["id"] == ref["id"] and out["analysis_status"] == "done"
    assert out["analysis"]["category"] == "product_packaging"
    assert [s["key"] for s in out["analysis"]["sections"]][0] == "structure"
    assert repo.get("refs", ref["id"])["analysis_json"]["schema"] == 2
