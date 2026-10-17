"""Finishing specification (M3): catalogue API, validated versioned saves with conflict detection,
revisions, and the placeholder preview's contract (only the masks change; fully reversible)."""

import io

import numpy as np
import pytest
from PIL import Image

from tests.conftest import wait_job
from tests.test_assets import project  # noqa: F401  (fixture: synthetic Figma tree)


def _save(client, pid, base, assignments):
    return client.put(
        f"/api/projects/{pid}/finishing", json={"base_revision": base, "assignments": assignments}
    )


def gold(targets=("1:2",), **params):
    return {
        "finish": "foil.gold",
        "targets": [{"kind": "asset", "id": t} for t in targets],
        "params": params,
    }


def test_catalogue_lists_categories_and_finishes(client):
    out = client.get("/api/finishing/catalog").json()
    assert {c["id"] for c in out["categories"]} == {"foil", "relief", "surface", "coating", "dome"}
    by = {f["id"]: f for f in out["finishes"]}
    assert by["foil.gold"]["label_ko"] == "금박" and by["foil.gold"]["scope"] == "selective"
    assert by["surface.matte_lamination"]["scope"] == "surface"
    assert by["coating.raised_uv"]["available"] is False
    assert any(p["id"] == "depth_mm" for p in by["relief.emboss"]["params"])


def test_saves_are_versioned_validated_and_clamped(client, project):  # noqa: F811
    pid = project
    assert client.get(f"/api/projects/{pid}/finishing").json()["revision"] == 0
    r1 = _save(client, pid, 0, [gold(roughness=9)])
    assert r1.status_code == 200, r1.json()
    spec = r1.json()
    assert spec["revision"] == 1 and spec["schema"] == 1
    a = spec["assignments"][0]
    assert a["params"]["roughness"] == 0.6  # clamped to the catalogue bound
    assert a["params"]["reflectivity"] == 0.9  # default filled in
    assert a["id"].startswith("fin_") and a["created_at"] and a["enabled"]
    # Second save with a surface finish on the whole sheet.
    matte = {"finish": "surface.matte_lamination", "targets": [{"kind": "sheet"}]}
    r2 = _save(client, pid, 1, [a, matte])
    assert r2.status_code == 200 and r2.json()["revision"] == 2
    # Earlier revisions stay retrievable; the current one is the latest.
    old = client.get(f"/api/projects/{pid}/finishing/revisions/1").json()
    assert len(old["assignments"]) == 1
    assert len(client.get(f"/api/projects/{pid}/finishing").json()["assignments"]) == 2


def test_stale_saves_conflict_instead_of_overwriting(client, project):  # noqa: F811
    pid = project
    assert _save(client, pid, 0, [gold()]).status_code == 200
    stale = _save(client, pid, 0, [])
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "FINISHING_CONFLICT"
    assert len(client.get(f"/api/projects/{pid}/finishing").json()["assignments"]) == 1


@pytest.mark.parametrize(
    ("assignment", "code"),
    [
        ({"finish": "foil.nope", "targets": [{"kind": "asset", "id": "1:2"}]}, "FINISH_UNKNOWN"),
        (
            {"finish": "coating.raised_uv", "targets": [{"kind": "asset", "id": "1:2"}]},
            "FINISH_UNAVAILABLE",
        ),
        (
            {"finish": "surface.gloss_lamination", "targets": [{"kind": "asset", "id": "1:2"}]},
            "FINISHING_SCOPE",
        ),
        ({"finish": "foil.gold", "targets": [{"kind": "sheet"}]}, "FINISHING_SCOPE"),
        (
            {"finish": "foil.gold", "targets": [{"kind": "asset", "id": "1:6"}]},
            "FINISHING_TARGET_INVALID",
        ),
        (
            {"finish": "foil.gold", "targets": [{"kind": "asset", "id": "9:9"}]},
            "FINISHING_TARGET_INVALID",
        ),
        ({"finish": "foil.gold", "targets": []}, "FINISHING_NO_TARGET"),
        (
            {"finish": "foil.gold", "targets": [{"kind": "asset", "id": "1:8", "range": [0, 2]}]},
            "FINISHING_RANGE_UNSUPPORTED",
        ),
        (
            {"finish": "surface.uncoated", "targets": [{"kind": "panel", "id": "nope"}]},
            "FINISHING_TARGET_INVALID",
        ),
    ],
)
def test_invalid_assignments_are_refused(client, project, assignment, code):  # noqa: F811
    res = _save(client, project, 0, [assignment])
    assert res.status_code == 422 and res.json()["error"]["code"] == code, res.json()


def _preview(client, pid, vid, revision=None):
    params = {"version_id": vid}
    if revision is not None:
        params["revision"] = revision
    res = client.get(f"/api/projects/{pid}/finishing/preview", params=params)
    assert res.status_code == 200, res.text
    return np.asarray(Image.open(io.BytesIO(res.content)).convert("RGB")).astype(int), res.headers


def _px(headers, shape, x, y):
    ox, oy = (float(v) for v in headers["x-frame-origin"].split(","))
    sx, sy = (float(v) for v in headers["x-frame-size"].split(","))
    return int((y - oy) / sy * shape[0]), int((x - ox) / sx * shape[1])


def test_preview_changes_only_the_masks_and_is_reversible(client, project):  # noqa: F811
    pid = project
    res = client.post(f"/api/projects/{pid}/generate", json={})
    vid = res.json()["version_id"]
    assert wait_job(client, res.json()["job_id"])["status"] == "done"
    before, h = _preview(client, pid, vid)  # revision 0: no finishes
    assert _save(client, pid, 0, [gold()]).status_code == 200
    after, _ = _preview(client, pid, vid)
    diff = np.abs(after - before).max(-1) > 0
    assert diff.any()
    assert not diff[_px(h, diff.shape, 430, 150)]  # the ring's counter stays the source
    assert diff[_px(h, diff.shape, 404, 150)]  # the ring itself is foiled
    ys, xs = np.nonzero(diff)
    y0, x0 = _px(h, diff.shape, 400, 120)
    y1, x1 = _px(h, diff.shape, 460, 180)
    assert ys.min() >= y0 - 1 and ys.max() <= y1 + 1 and xs.min() >= x0 - 1 and xs.max() <= x1 + 1
    # Hidden (disabled) finish = the original again; removing it too.
    spec = client.get(f"/api/projects/{pid}/finishing").json()
    off = dict(spec["assignments"][0], enabled=False)
    assert _save(client, pid, 1, [off]).status_code == 200
    assert np.array_equal(_preview(client, pid, vid)[0], before)
    assert _save(client, pid, 2, []).status_code == 200
    assert np.array_equal(_preview(client, pid, vid)[0], before)
    # Any saved revision can be previewed again.
    assert np.array_equal(_preview(client, pid, vid, revision=1)[0], after)
