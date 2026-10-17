"""Asset selection for finishing: Figma node tree, exact outlined-vector masks registered with
the render (counters, clipping), hit-testing with parent cycling, structural exclusions, and the
PDF-only fallback. Synthetic Figma data only (no network)."""

import io

import numpy as np
import pytest
from PIL import Image

from app.finishing import assets as fa
from tests.conftest import upload


def ring_svg(size: float) -> str:
    """A ring (letter-O-like) with a real counter, as Figma exports outlined shapes."""
    s, r1, r2 = size, size / 2, size / 4
    c = s / 2
    d = (
        f"M{c - r1} {c}a{r1} {r1} 0 1 0 {2 * r1} 0a{r1} {r1} 0 1 0 {-2 * r1} 0Z"
        f"M{c - r2} {c}a{r2} {r2} 0 1 1 {2 * r2} 0a{r2} {r2} 0 1 1 {-2 * r2} 0Z"
    )
    return (
        f'<svg width="{s}" height="{s}" viewBox="0 0 {s} {s}" fill="none" '
        f'xmlns="http://www.w3.org/2000/svg"><path fill-rule="evenodd" d="{d}" fill="#111"/></svg>'
    )


def rect_svg(w: float, h: float) -> str:
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" fill="none" '
        f'xmlns="http://www.w3.org/2000/svg"><rect width="{w}" height="{h}" fill="#C00"/></svg>'
    )


def node(nid, name, kind, x, y, w, h, children=(), **extra):
    return {
        "id": nid,
        "name": name,
        "type": kind,
        "absoluteBoundingBox": {"x": x, "y": y, "width": w, "height": h},
        "children": list(children),
        **extra,
    }


@pytest.fixture
def project(client):
    """named_spot (page 680 x 658 pt, board 68..612) with a synthetic Figma asset tree."""
    pid, _ = upload(client, "named_spot")
    ring = node("1:2", "Logo O", "VECTOR", 400, 120, 60, 60)
    group = node("1:1", "Logo group", "GROUP", 400, 120, 60, 60, [ring])
    bar = node("1:4", "Bar", "RECTANGLE", 400, 165, 60, 10)
    clipper = node("1:3", "Clip frame", "FRAME", 380, 140, 40, 40, [bar], clipsContent=True)
    dims = node("1:5", "100mm", "TEXT", 300, 75, 40, 10, characters="100mm", style={})
    die = node("1:6", "Dieline", "VECTOR", 70, 70, 540, 520)
    hidden = node("1:7", "Hidden", "VECTOR", 300, 300, 20, 20, visible=False)
    title = node(
        "1:8", "Title", "TEXT", 380, 200, 100, 20, characters="TITLE", style={"fontFamily": "X"}
    )
    frame = node("0:1", "Frame", "FRAME", 0, 0, 680.315, 657.638)
    frame["children"] = [group, clipper, dims, die, hidden, title]
    fa.save_tree(pid, frame)
    fa.svg_path(pid, "1:1").write_text(ring_svg(60))
    fa.svg_path(pid, "1:2").write_text(ring_svg(60))
    fa.svg_path(pid, "1:4").write_text(rect_svg(60, 10))
    fa.svg_path(pid, "1:8").write_text(rect_svg(100, 20))
    return pid


def _assets(client, pid):
    res = client.get(f"/api/projects/{pid}/assets")
    assert res.status_code == 200, res.json()
    return res.json()


def test_tree_ids_relations_and_exclusions(client, project):
    out = _assets(client, project)
    by = {a["id"]: a for a in out["assets"]}
    assert out["source"] == "figma"
    assert by["1:1"]["children"] == ["1:2"] and by["1:2"]["parent"] == "1:1"
    assert by["1:2"]["kind"] == "vector" and by["1:1"]["kind"] == "group"
    assert by["1:2"]["exact"] is True
    # Never finishing targets: dimension labels, technical (dieline) layers, hidden nodes.
    assert by["1:5"]["selectable"] is False and by["1:5"]["technical"] is True
    assert by["1:6"]["selectable"] is False and by["1:6"]["technical"] is True
    assert "1:7" not in by
    assert by["1:2"]["selectable"] and by["1:8"]["selectable"]


def _mask(client, pid, aid):
    res = client.get(f"/api/projects/{pid}/assets/{aid}/mask", params={"style": "fill"})
    assert res.status_code == 200, res.text
    return np.asarray(Image.open(io.BytesIO(res.content)))[..., 3].astype(np.float32) / 255


def _px(frame, x, y):
    return (
        int((y - frame["origin"][1]) / frame["size"][1] * frame["height"]),
        int((x - frame["origin"][0]) / frame["size"][0] * frame["width"]),
    )


def test_masks_follow_the_vector_shape_with_counters(client, project):
    fr = _assets(client, project)["frame"]
    m = _mask(client, project, "1:2")
    assert m[_px(fr, 430, 150)] == 0  # the ring's counter (hole) is not part of the mask
    assert m[_px(fr, 404, 150)] > 0.3  # on the ring
    assert m[_px(fr, 395, 150)] == 0  # outside the shape
    # Not a box: the box corners around the ring are empty.
    assert m[_px(fr, 402, 122)] == 0


def test_clipping_ancestors_cut_the_mask(client, project):
    fr = _assets(client, project)["frame"]
    m = _mask(client, project, "1:4")
    assert m[_px(fr, 410, 170)] > 0.3  # inside the clip frame
    assert m[_px(fr, 440, 170)] == 0  # the bar beyond the clip frame is clipped away


def test_hit_returns_innermost_first_and_misses_holes(client, project):
    on_ring = client.post(f"/api/projects/{project}/assets/hit", json={"x": 404, "y": 150})
    assert on_ring.json()["candidates"][:2] == ["1:2", "1:1"]  # child, then its group
    in_hole = client.post(f"/api/projects/{project}/assets/hit", json={"x": 430, "y": 150})
    assert "1:2" not in in_hole.json()["candidates"]
    on_label = client.post(f"/api/projects/{project}/assets/hit", json={"x": 320, "y": 80})
    assert "1:5" not in on_label.json()["candidates"]


def test_technical_assets_have_no_mask(client, project):
    res = client.get(f"/api/projects/{project}/assets/1:6/mask")
    assert res.status_code == 409 and res.json()["error"]["code"] == "ASSET_NOT_SELECTABLE"


def test_pdf_only_projects_select_their_own_objects(client):
    pid, _ = upload(client, "named_spot")
    out = _assets(client, pid)
    assert out["source"] == "pdf"
    assert all(a["exact"] is False for a in out["assets"])
    assert all(a["id"].startswith("pdf:") for a in out["assets"])


def test_assets_need_a_confirmed_structure(client):
    pid, _ = upload(client, "unnamed_mixed")  # needs structural review first
    res = client.get(f"/api/projects/{pid}/assets")
    assert res.status_code == 409
