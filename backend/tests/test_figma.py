"""Figma link import: link parsing, layer-name evidence, import and re-sync (Figma mocked)."""

import pikepdf
import pytest

from app.errors import ApiError
from app.figma import client as figma
from app.figma.layers import extract_shapes, parse_svg_path
from app.pdf.analyze import build_spec, detect, extract
from app.pdf.content import walk_page
from app.pdf.geometry import flatten
from tests.conftest import FIXTURES, fixture_bytes, wait_job

MM = 72 / 25.4
MARGIN = 24.0


def test_parse_link_variants():
    a = figma.parse_link("https://www.figma.com/design/AbC123/Zentra?node-id=12-34&t=x")
    assert (a.file_key, a.node_id) == ("AbC123", "12:34")
    b = figma.parse_link("https://figma.com/file/KEY/name?node-id=1%3A2")
    assert (b.file_key, b.node_id) == ("KEY", "1:2")
    c = figma.parse_link("https://www.figma.com/design/MAIN/x/branch/BR4NCH/y?node-id=5-6")
    assert c.file_key == "BR4NCH"
    with pytest.raises(ApiError) as e:
        figma.parse_link("https://www.figma.com/design/AbC123/Zentra")
    assert e.value.body.code == "FIGMA_NODE_MISSING"
    with pytest.raises(ApiError) as e:
        figma.parse_link("https://example.com/design/x?node-id=1-2")
    assert e.value.body.code == "FIGMA_LINK_INVALID"


def test_parse_svg_path():
    [pl] = parse_svg_path("M0 0L10 0L10 5Z")
    assert pl[0] == (0, 0) and pl[2] == (10, 5) and pl[-1] == (0, 0)
    [curve] = parse_svg_path("M0 0C0 10 10 10 10 0", steps=4)
    assert curve[-1] == (10, 0) and len(curve) == 5


# ---- fake Figma documents built from the synthetic fixtures ----------------------------


def svg(polys) -> str:
    return " ".join("M" + " L".join(f"{x:.3f} {y:.3f}" for x, y in pl) for pl in polys)


def vector(name, polys, color=(0.9, 0.0, 0.07)):
    xs = [x for pl in polys for x, _ in pl]
    ys = [y for pl in polys for _, y in pl]
    x0, y0 = min(xs), min(ys)
    local = [[(x - x0, y - y0) for x, y in pl] for pl in polys]
    return {
        "type": "VECTOR",
        "name": name,
        "visible": True,
        "absoluteBoundingBox": {
            "x": 1000 + x0,
            "y": 500 + y0,
            "width": max(xs) - x0,
            "height": max(ys) - y0,
        },
        "relativeTransform": [[1, 0, x0], [0, 1, y0]],
        "fills": [
            {"type": "SOLID", "color": {"r": color[0], "g": color[1], "b": color[2], "a": 1}}
        ],
        "strokes": [],
        "strokeWeight": 0,
        "fillGeometry": [{"path": svg(local), "windingRule": "NONZERO"}],
    }


def frame_doc(name, children, page):
    return {
        "type": "FRAME",
        "name": name,
        "visible": True,
        "absoluteBoundingBox": {"x": 1000, "y": 500, "width": page[0], "height": page[1]},
        "children": children,
    }


def page_size(pdf_name):
    pdf = pikepdf.open(FIXTURES / f"{pdf_name}.pdf")
    box = pdf.pages[0].mediabox
    return float(box[2]), float(box[3])


def path_polys(pdf_name, pred):
    pdf = pikepdf.open(FIXTURES / f"{pdf_name}.pdf")
    return [flatten(sp) for p in walk_page(pdf).paths if pred(p) for sp in p.subpaths]


def redline_doc():
    """figma_outlined: the whole dieline is one layer named "redline"; dims in "치수"."""
    page = page_size("figma_outlined")
    red = path_polys(
        "figma_outlined", lambda p: p.fill and len(p.subpaths) > 20 and p.fill_rgb[1] < 0.1
    )
    dims = path_polys(
        "figma_outlined", lambda p: p.fill and 2 <= len(p.subpaths) <= 20 and p.fill_rgb[1] < 0.1
    )
    return frame_doc(
        "ZENTRA 전개도",
        [
            vector("redline", red),
            {
                "type": "GROUP",
                "name": "치수",
                "visible": True,
                "children": [vector("Line 3", dims)],
            },
        ],
        page,
    )


def separate_layers_doc():
    """unnamed_solid: outline drawn on a "cut" layer, folds on a "fold" layer."""
    from tests.fixtures.synthetic.generate import CREASES, OUTLINE

    page = page_size("unnamed_solid")

    def pt(p):
        return ((p[0] + MARGIN) * MM, (p[1] + MARGIN) * MM)

    cut = [[pt(OUTLINE[i]), pt(OUTLINE[(i + 1) % len(OUTLINE)])] for i in range(len(OUTLINE))]
    fold = [[pt(a), pt(c)] for a, c in CREASES]
    return frame_doc("frame", [vector("cut", cut), vector("fold", fold)], page)


def test_redline_layer_name_is_used_and_split_by_topology():
    shapes = extract_shapes(redline_doc())
    assert {(s["layer"], s["cls"]) for s in shapes} == {("redline", "cut"), ("치수", "annotation")}
    ex = extract(fixture_bytes("figma_outlined"), design_shapes=shapes)
    spec = build_spec(ex, detect(ex))
    assert spec.separations.cut.state == "detected"
    assert spec.separations.cut.evidence == ["Figma 레이어 'redline'"]
    assert spec.separations.crease.state == "estimated"  # inner lines of the redline layer
    assert not spec.review.required and len(spec.panels) == 13
    dims = [p for p in spec.paths if p.cls == "annotation"]
    assert dims and all("Figma" in p.reason or "기술" in p.reason for p in dims)


def test_separate_cut_and_fold_layers_are_detected_by_name():
    ex = extract(
        fixture_bytes("unnamed_solid"), design_shapes=extract_shapes(separate_layers_doc())
    )
    spec = build_spec(ex, detect(ex))
    assert spec.separations.cut.evidence == ["Figma 레이어 'cut'"]
    assert spec.separations.crease.state == "detected"
    assert spec.separations.crease.evidence == ["Figma 레이어 'fold'"]
    assert len([p for p in spec.paths if p.cls == "crease"]) == 12


# ---- API ---------------------------------------------------------------------------------


@pytest.fixture
def fake_figma(monkeypatch):
    state = {
        "version": "100",
        "doc": redline_doc(),
        "pdf": fixture_bytes("figma_outlined"),
        "fetched": [],
    }

    def fetch_frame(link, version=None):
        state["fetched"].append(version)
        return figma.FigmaFrame(
            link,
            "ZENTRA",
            state["doc"]["name"],
            state["version"],
            "2026-10-16T00:00:00Z",
            state["doc"],
        )

    monkeypatch.setattr(figma, "fetch_frame", fetch_frame)
    monkeypatch.setattr(figma, "export_pdf", lambda link: state["pdf"])
    monkeypatch.setattr(figma, "file_version", lambda link: state["version"])
    monkeypatch.setattr(figma, "configured", lambda: True)
    return state


LINK = "https://www.figma.com/design/AbC123/Zentra?node-id=12-34"


def test_import_by_link(client, fake_figma):
    assert client.get("/api/figma/status").json() == {"configured": True}
    res = client.post("/api/projects/figma", json={"url": LINK})
    assert res.status_code == 202, res.json()
    pid = res.json()["project"]["id"]
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "done", job
    project = client.get(f"/api/projects/{pid}").json()
    assert project["status"] == "ready"
    assert project["name"] == "ZENTRA 전개도"
    assert project["figma"]["node_id"] == "12:34"
    assert {layer["name"] for layer in project["figma"]["layers"]} >= {"redline"}
    spec = client.get(f"/api/projects/{pid}/specification").json()
    assert spec["separations"]["cut"]["evidence"] == ["Figma 레이어 'redline'"]
    # The import also keeps the node tree for finishing selection (stable Figma ids).
    from app.storage import repo

    assert (repo.project_dir(pid) / "figma_assets.json").exists()
    assets = client.get(f"/api/projects/{pid}/assets").json()
    assert assets["source"] == "figma"


def test_import_without_token(client):
    res = client.post("/api/projects/figma", json={"url": LINK})
    assert res.status_code == 503 and res.json()["error"]["code"] == "FIGMA_TOKEN_MISSING"
    assert client.get("/api/figma/status").json() == {"configured": False}


def test_import_rejects_link_without_frame(client, fake_figma):
    res = client.post(
        "/api/projects/figma", json={"url": "https://www.figma.com/design/AbC123/Zentra"}
    )
    assert res.status_code == 400 and res.json()["error"]["code"] == "FIGMA_NODE_MISSING"


def test_older_imports_get_their_content_at_the_imported_version(client, fake_figma):
    """Projects imported before Figma content was stored get it on first use, read at the
    imported version so it matches the stored PDF even after the file has changed."""
    from app.services import pipeline
    from app.storage import repo

    res = client.post("/api/projects/figma", json={"url": LINK})
    pid = res.json()["project"]["id"]
    assert wait_job(client, res.json()["job_id"])["status"] == "done"
    (repo.project_dir(pid) / "figma_content.json").unlink()
    assert client.get(f"/api/projects/{pid}").json()["figma"]["content_ready"] is False

    fake_figma["version"] = "101"
    fake_figma["fetched"].clear()
    assert pipeline.figma_content(pid, backfill=True) is not None
    assert fake_figma["fetched"] == ["100"]
    assert client.get(f"/api/projects/{pid}").json()["figma"]["content_ready"] is True
