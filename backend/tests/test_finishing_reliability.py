"""Finishing data stays consistent: concurrent saves never both win, writes are atomic and
recoverable, and the masks, previews and checks always follow the current source geometry
(changed outlines, changed nodes, removed nodes) instead of a cached copy."""

import io
import threading

import numpy as np
import pytest
from PIL import Image

from app.errors import ApiError
from app.finishing import assets as fa
from app.finishing import spec as fspec
from app.storage import repo
from tests.conftest import wait_job
from tests.test_assets import node, project, rect_svg, ring_svg  # noqa: F401


def gold(*ids):
    return fspec.Assignment(
        finish="foil.gold", targets=[fspec.Target(kind="asset", id=i) for i in ids]
    )


def _put(client, pid, base, assignments):
    return client.put(
        f"/api/projects/{pid}/finishing", json={"base_revision": base, "assignments": assignments}
    )


# ---- concurrent saves ----------------------------------------------------------------------


def test_two_saves_from_the_same_revision_cannot_both_win(client, project):  # noqa: F811
    pid = project
    results: list = []
    barrier = threading.Barrier(8)

    def save(i):
        barrier.wait()
        try:
            results.append(fspec.save(pid, 0, [gold("1:2").model_copy(update={"id": f"fin_{i}"})]))
        except ApiError as e:
            results.append(e)

    threads = [threading.Thread(target=save, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    won = [r for r in results if isinstance(r, fspec.FinishingSpec)]
    lost = [r for r in results if isinstance(r, ApiError)]
    assert len(won) == 1 and len(lost) == 7
    assert all(e.status_code == 409 and e.body.code == "FINISHING_CONFLICT" for e in lost)
    assert all(e.body.details["current_revision"] == 1 for e in lost)
    current = fspec.load(pid)
    assert current.revision == 1 and current.assignments[0].id == won[0].assignments[0].id


def test_a_writer_in_another_process_is_also_a_conflict(client, project):  # noqa: F811
    """The in-process lock does not see other processes: the exclusive revision file does."""
    pid = project
    fspec.save(pid, 0, [gold("1:2")])
    d = repo.project_dir(pid) / fspec.REV_DIR
    (d / "rev-2.json").write_text(
        (d / "rev-1.json").read_text().replace('"revision": 1', '"revision": 2')
    )
    with pytest.raises(ApiError) as e:
        fspec._save(pid, 1, [gold("1:8")])  # bypass the lock: as if racing from elsewhere
    assert e.value.status_code == 409 and e.value.body.details["current_revision"] == 2


def test_rapid_saves_and_retry_after_conflict(client, project):  # noqa: F811
    pid = project
    rev = 0
    for i in range(10):
        res = _put(
            client,
            pid,
            rev,
            [
                {
                    "finish": "foil.gold",
                    "targets": [{"kind": "asset", "id": "1:2"}],
                    "params": {},
                    "id": "fin_a",
                    "order": i,
                }
            ],
        )
        assert res.status_code == 200, res.json()
        rev = res.json()["revision"]
    assert rev == 10
    # A stale tab: 409 with the current revision, then the retry on it goes through.
    stale = _put(client, pid, 3, [])
    assert stale.status_code == 409 and stale.json()["error"]["details"]["current_revision"] == 10
    again = _put(client, pid, 10, [])
    assert again.status_code == 200 and again.json()["revision"] == 11


def test_a_failed_write_leaves_the_last_good_state(client, project, monkeypatch):  # noqa: F811
    pid = project
    fspec.save(pid, 0, [gold("1:2")])

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(fspec.os, "link", boom)
    with pytest.raises(OSError):
        fspec.save(pid, 1, [gold("1:8")])
    monkeypatch.undo()
    cur = fspec.load(pid)
    assert cur.revision == 1 and cur.assignments[0].targets[0].id == "1:2"
    d = repo.project_dir(pid)
    assert not list(d.glob("**/.*.tmp"))  # no stray temporary files
    assert fspec.save(pid, 1, [gold("1:8")]).revision == 2


def test_reload_after_an_interrupted_save_uses_the_revision_file(client, project):  # noqa: F811
    """Crash between the revision file and the finishing.json copy: the revision wins."""
    pid = project
    fspec.save(pid, 0, [gold("1:2")])
    d = repo.project_dir(pid)
    old = (d / fspec.FILE).read_text()
    fspec.save(pid, 1, [gold("1:8")])
    (d / fspec.FILE).write_text(old)  # as if the copy never happened
    cur = fspec.load(pid)
    assert cur.revision == 2 and cur.assignments[0].targets[0].id == "1:8"
    assert fspec.save(pid, 2, []).revision == 3
    assert client.get(f"/api/projects/{pid}/finishing").json()["revision"] == 3


def test_separate_projects_save_independently(client, project):  # noqa: F811
    from tests.conftest import upload

    other, _ = upload(client, "named_spot")
    barrier = threading.Barrier(2)
    out = {}

    def save(pid):
        barrier.wait()
        out[pid] = fspec.save(pid, 0, []).revision

    ts = [threading.Thread(target=save, args=(p,)) for p in (project, other)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert out == {project: 1, other: 1}


# ---- source geometry changes --------------------------------------------------------------


def _flat(client, pid):
    res = client.post(f"/api/projects/{pid}/generate", json={})
    assert wait_job(client, res.json()["job_id"])["status"] == "done"
    return res.json()["version_id"]


def _overlay_alpha(client, pid, vid):
    res = client.get(f"/api/projects/{pid}/finishing/preview", params={"version_id": vid})
    assert res.status_code == 200
    rect = tuple(int(v) for v in res.headers["x-overlay-rect"].split(","))
    a = np.asarray(Image.open(io.BytesIO(res.content)).convert("RGBA"))[..., 3]
    return rect, int((a > 0).sum())


def test_a_changed_outline_refreshes_mask_preview_and_plates(client, project):  # noqa: F811
    pid = project
    vid = _flat(client, pid)
    assert (
        _put(
            client, pid, 0, [{"finish": "foil.gold", "targets": [{"kind": "asset", "id": "1:2"}]}]
        ).status_code
        == 200
    )
    rect1, area1 = _overlay_alpha(client, pid, vid)
    mask1 = client.get(f"/api/projects/{pid}/assets/1:2/mask", params={"style": "fill"}).content
    # The vector is edited (the ring becomes a solid square) and its outline re-exported.
    fa.svg_path(pid, "1:2").write_text(rect_svg(60, 60))
    rect2, area2 = _overlay_alpha(client, pid, vid)
    assert area2 > area1 * 1.2  # the counter and the corners are now foil: not the old mask
    assert (
        client.get(f"/api/projects/{pid}/assets/1:2/mask", params={"style": "fill"}).content
        != mask1
    )
    # Unchanged geometry reuses the cache: the same request twice gives the same bytes.
    assert _overlay_alpha(client, pid, vid) == (rect2, area2)


def test_a_changed_text_node_box_is_followed(client, project):  # noqa: F811
    """Edited text: new glyph outline and a new box in the tree."""
    pid = project
    vid = _flat(client, pid)
    assert (
        _put(
            client, pid, 0, [{"finish": "foil.gold", "targets": [{"kind": "asset", "id": "1:8"}]}]
        ).status_code
        == 200
    )
    rect1, _ = _overlay_alpha(client, pid, vid)
    tree = fa.figma_tree(pid)
    for a in tree:
        if a["id"] == "1:8":
            a["bbox"] = [380, 200, 440, 220]  # shorter text
    import json

    (repo.project_dir(pid) / fa.TREE_FILE).write_text(json.dumps(tree))
    fa.svg_path(pid, "1:8").write_text(rect_svg(60, 20))
    rect2, _ = _overlay_alpha(client, pid, vid)
    assert rect2[2] < rect1[2]  # narrower overlay: the new glyphs, not the cached ones


def test_a_removed_node_is_reported_and_never_reattached(client, project):  # noqa: F811
    import json

    pid = project
    vid = _flat(client, pid)
    keep = {"id": "fin_keep", "finish": "foil.gold", "targets": [{"kind": "asset", "id": "1:2"}]}
    lost = {
        "id": "fin_lost",
        "finish": "relief.emboss",
        "targets": [{"kind": "asset", "id": "1:8"}],
    }
    assert _put(client, pid, 0, [keep, lost]).status_code == 200
    tree = [a for a in fa.figma_tree(pid) if a["id"] != "1:8"]
    (repo.project_dir(pid) / fa.TREE_FILE).write_text(json.dumps(tree))
    fa.svg_path(pid, "1:8").unlink()
    # The checks say so, on that assignment.
    warns = client.get(f"/api/projects/{pid}/finishing/warnings").json()["warnings"]
    missing = [w for w in warns if w["code"] == "TARGET_MISSING"]
    assert [w["assignment_id"] for w in missing] == ["fin_lost"] and missing[0]["level"] == "error"
    # The preview still works (without it); other edits still save, the lost target is kept
    # as it was (not moved to another node), and it cannot be newly added anywhere.
    assert _overlay_alpha(client, pid, vid)[1] > 0
    keep["params"] = {}
    res = _put(client, pid, 1, [keep, lost])
    assert res.status_code == 200
    saved = {a["id"]: a for a in res.json()["assignments"]}
    assert saved["fin_lost"]["targets"] == [{"kind": "asset", "id": "1:8", "range": None}]
    fresh = {"finish": "coating.spot_uv", "targets": [{"kind": "asset", "id": "1:8"}]}
    res = _put(client, pid, 2, [keep, lost, fresh])
    assert res.status_code == 422 and res.json()["error"]["code"] == "FINISHING_TARGET_INVALID"


def test_outlines_from_another_file_version_are_dropped(client, project):  # noqa: F811
    pid = project
    repo.update(
        "projects",
        pid,
        figma_json={"file_key": "k", "node_id": "0:1", "url": "u", "version": "v2"},
    )
    d = repo.project_dir(pid)
    (d / fa.VERSION_FILE).write_text("v1")  # made from an older version of the file
    fa.svg_path(pid, "1:2").write_text(ring_svg(60))

    class Frame:
        document = node("0:1", "Frame", "FRAME", 0, 0, 680.315, 657.638)

    import app.figma.client as figma

    calls = []
    orig = figma.fetch_frame

    def fetch(link, version=None):
        calls.append(version)
        return Frame()

    figma.fetch_frame = fetch
    try:
        assert fa.figma_tree(pid) == []  # rebuilt from the project's own version
    finally:
        figma.fetch_frame = orig
    assert calls == ["v2"] and not fa.svg_path(pid, "1:2").exists()
    assert (d / fa.VERSION_FILE).read_text() == "v2"
