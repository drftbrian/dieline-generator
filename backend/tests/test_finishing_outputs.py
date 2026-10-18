"""Finishing outputs beyond the preview: the light sweep, the printer's plates and the
manufacturing checks; and a finished version used in step 3."""

import io
import json
import zipfile

import pymupdf
from PIL import Image

from tests.conftest import wait_job
from tests.test_assets import project  # noqa: F401  (fixture: synthetic Figma tree)


def _put(client, pid, base, assignments):
    res = client.put(
        f"/api/projects/{pid}/finishing", json={"base_revision": base, "assignments": assignments}
    )
    assert res.status_code == 200, res.json()
    return res.json()


def _flat(client, pid):
    res = client.post(f"/api/projects/{pid}/generate", json={})
    assert wait_job(client, res.json()["job_id"])["status"] == "done"
    return res.json()["version_id"]


def asset(fid, *ids, **params):
    return {"finish": fid, "targets": [{"kind": "asset", "id": i} for i in ids], "params": params}


def test_light_sweep_is_an_animation(client, project):  # noqa: F811
    pid = project
    vid = _flat(client, pid)
    _put(client, pid, 0, [asset("foil.gold", "1:2")])
    for light in ("top", "raking"):
        res = client.get(
            f"/api/projects/{pid}/finishing/sweep", params={"version_id": vid, "light": light}
        )
        assert res.status_code == 200 and res.headers["content-type"] == "image/gif"
        gif = Image.open(io.BytesIO(res.content))
        assert gif.n_frames >= 8
    raking = client.get(
        f"/api/projects/{pid}/finishing/preview", params={"version_id": vid, "light": "raking"}
    )
    top = client.get(f"/api/projects/{pid}/finishing/preview", params={"version_id": vid})
    assert raking.status_code == 200 and raking.content != top.content


def test_plates_are_black_vectors_in_page_coordinates(client, project):  # noqa: F811
    pid = project
    spec = _put(
        client,
        pid,
        0,
        [
            asset("foil.gold", "1:2"),
            asset("relief.emboss", "1:8"),
            {"finish": "surface.matte_lamination", "targets": [{"kind": "sheet"}]},
        ],
    )
    from tests.test_finishing_plates import confirm_scale

    confirm_scale(client, pid)
    res = client.get(f"/api/projects/{pid}/finishing/plates")
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(res.content))
    names = set(z.namelist())
    assert {
        "foil_gold.pdf",
        "relief_emboss.pdf",
        "surface_matte_lamination.pdf",
        "dieline.pdf",
    } <= names
    manifest = json.loads(z.read("finishing.json"))
    assert manifest["finishing_revision"] == spec["revision"]
    doc = pymupdf.open(stream=z.read("foil_gold.pdf"), filetype="pdf")
    page = doc[0]
    # The ring is drawn as vectors where it sits on the source page, in 100% K.
    fills = [d for d in page.get_drawings() if d.get("fill") is not None]
    streams = b"".join(
        doc.xref_stream(x) or b"" for x in range(1, doc.xref_length()) if doc.xref_is_stream(x)
    )
    assert fills and b"0 0 0 1 k" in streams and b" rg" not in streams  # (MuPDF shows K as RGB)
    box = pymupdf.Rect()
    for d in fills:
        box |= d["rect"]
    assert abs(box.x0 - 400) < 2 and abs(box.y0 - 120) < 2 and abs(box.x1 - 460) < 2
    # The dieline is a separate guide file: a "do not print" layer still prints on some RIPs.
    assert not doc.get_ocgs()


def test_manufacturing_checks(client, project):  # noqa: F811
    pid = project
    _put(
        client,
        pid,
        0,
        [
            {"finish": "surface.gloss_lamination", "targets": [{"kind": "sheet"}]},
            asset("coating.spot_uv", "1:2"),
            asset("relief.emboss", "1:8", depth_mm=0.8),
        ],
    )
    out = client.get(f"/api/projects/{pid}/finishing/warnings").json()
    codes = {w["code"] for w in out["warnings"]}
    assert "UV_ON_GLOSS" in codes and "DEEP_RELIEF_LAMINATED" in codes
    for w in out["warnings"]:
        assert w["message"] and w["level"] in ("error", "warning", "info")


def test_a_finished_version_can_be_merged(client, project, monkeypatch):  # noqa: F811
    from app.storage import repo

    pid = project
    vid = _flat(client, pid)
    _put(client, pid, 0, [asset("foil.gold", "1:2")])
    res = client.post(f"/api/projects/{pid}/versions/{vid}/finish", json={})
    assert wait_job(client, res.json()["job_id"])["status"] == "done"
    fin = repo.get("versions", res.json()["version_id"])
    assert fin["frame_json"]  # carries the frame the merge cuts the faces through
    from app.api.generate import _flat_version

    assert _flat_version(pid, fin["id"])["id"] == fin["id"]
