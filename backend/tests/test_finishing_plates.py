"""The printer's plates draw the same geometry as the preview: inside the board a plate equals
the preview's mask of that finish (registration, counters, clipping, irregular outlines,
openings, panels near folds, several assignments), outside it only the bleed. The dieline is a
separate guide file, never on a plate; the art is one K separation; a Figma asset without its
outline is reported, never guessed from the print."""

import io
import json
import zipfile

import numpy as np
import pymupdf
import pytest

from app.errors import ApiError
from app.finishing import assets as fa
from app.finishing import compose, masks, plates, svgclip
from app.finishing import spec as fspec
from app.render.layers import frame, structure_key
from app.services import specs
from app.spec.models import FLAT_LOOK, StructuralPath
from app.storage import repo
from tests.conftest import wait_job
from tests.test_assets import project  # noqa: F401  (fixture: synthetic Figma tree)


def _flat(client, pid):
    res = client.post(f"/api/projects/{pid}/generate", json={})
    assert wait_job(client, res.json()["job_id"])["status"] == "done"
    return res.json()["version_id"]


def _spec(pid):
    """The project's spec with its ruler confirmed by the user (named_spot's one dimension
    mark reads at confidence 0.75, which the plates' size gate rightly refuses)."""
    spec = specs.load(repo.project_or_404(pid))
    spec.scale = spec.scale.model_copy(update={"source": "user", "confidence": 1.0})
    return spec


def confirm_scale(client, pid):
    """As a user would in the structural review: confirm the mm-per-unit ratio."""
    spec = specs.load(repo.project_or_404(pid))
    res = client.patch(
        f"/api/projects/{pid}/specification", json={"mm_per_pt": spec.scale.mm_per_pt}
    )
    assert res.status_code == 200, res.json()


def _fin(*assignments) -> fspec.FinishingSpec:
    return fspec.FinishingSpec(
        revision=1,
        assignments=[
            fspec.Assignment(finish=f, targets=[fspec.Target(kind=k, id=i) for k, i in ts], order=n)
            for n, (f, ts) in enumerate(assignments)
        ],
    )


def _preview_masks(pid, spec, vid, fin) -> tuple[dict[str, np.ndarray], tuple[int, int]]:
    """Per finish, the union of the preview's masks on the full version frame."""
    c = compose.compose(pid, spec, vid, fin)
    h, w = c.image.shape[:2]
    out: dict[str, np.ndarray] = {}
    if c.box is not None:
        y0, x0, y1, x1 = c.box
        for f, _, m in c.stack:
            full = out.setdefault(f.id, np.zeros((h, w), np.float32))
            full[y0:y1, x0:x1] = np.maximum(full[y0:y1, x0:x1], m)
    return out, (h, w)


def _plates(pid, spec, fin, draft=False) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(plates.build(pid, spec, fin, draft=draft)))


def assert_same_geometry(pid, spec, vid, fin) -> dict:
    """Plate == preview inside the board (up to the anti-aliased edge), and nothing on a plate
    beyond the board's bleed (``plates.compare``). Returns per-finish IoU."""
    found = plates.compare(pid, spec, vid, fin)
    for r in found:
        assert r["wrong_px"] == 0 and r["beyond_bleed_px"] == 0, r
    return {r["finish"]: r["iou"] for r in found}


def test_plates_match_the_preview_for_assets_panels_and_sheet(client, project):  # noqa: F811
    pid = project
    vid = _flat(client, pid)
    spec = _spec(pid)
    panel = spec.panels[0].id
    fin = _fin(
        ("foil.gold", [("asset", "1:2")]),  # ring with a counter
        ("foil.gold", [("asset", "1:8")]),  # a second assignment of the same finish
        ("relief.emboss", [("asset", "1:4")]),  # clipped by its frame ancestor
        ("coating.spot_uv", [("asset", "1:1")]),  # a group
        ("surface.matte_lamination", [("panel", panel)]),
        ("surface.gloss_lamination", [("sheet", None)]),
    )
    scores = assert_same_geometry(pid, spec, vid, fin)
    assert set(scores) == {
        "foil.gold",
        "relief.emboss",
        "coating.spot_uv",
        "surface.matte_lamination",
        "surface.gloss_lamination",
    }
    assert min(scores.values()) > 0.97, scores


def test_panel_plates_follow_the_irregular_outline(client, project):  # noqa: F811
    """named_spot's panels are boxes, the carton is not (tuck and dust flaps): the panel plate
    must stop at the cut like the preview, not fill its box."""
    pid = project
    vid = _flat(client, pid)
    spec = _spec(pid)
    for p in spec.panels:
        fin = _fin(("surface.matte_lamination", [("panel", p.id)]))
        assert_same_geometry(pid, spec, vid, fin)
    # The box of some panel does leave the board (else this test would prove nothing).
    sil = masks.board(spec, 1000, structure_key(spec)) > 0.5
    raster, _ = frame(spec, 1000, FLAT_LOOK.lighting.margin)
    leaks = []
    for p in spec.panels:
        x0, y0, x1, y1 = (
            int((v - o) * raster.scale)
            for v, o in zip(p.bbox, (*raster.origin, *raster.origin), strict=True)
        )
        leaks.append((~sil[y0:y1, x0:x1]).mean())
    assert max(leaks) > 0.02


def _with_opening(spec, box):
    """The spec with an extra closed cut loop (a window) at ``box`` (page pt)."""
    x0, y0, x1, y1 = box
    loop = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    s = spec.model_copy(deep=True)
    s.paths.append(
        StructuralPath(
            id="window",
            cls="cut",
            status="confirmed",
            suggested_cls="cut",
            confidence=1.0,
            provenance="user_confirmed",
            reason="test window",
            polylines=[loop],
            closed=[True],
            bbox=box,
            color="#E5333F",
            dashed=False,
            width_pt=0.5,
            color_space="manual",
            layers=[],
            source_ref="manual:window",
        )
    )
    return s


def test_openings_are_cut_out_of_every_plate(client, project):  # noqa: F811
    pid = project
    vid = _flat(client, pid)
    spec = _spec(pid)
    # A window through the ring logo and the panel under it.
    win = _with_opening(spec, (415, 135, 445, 165))
    panel = next(
        p for p in win.panels if p.bbox[0] <= 430 <= p.bbox[2] and p.bbox[1] <= 150 <= p.bbox[3]
    )
    fin = _fin(
        ("foil.gold", [("asset", "1:2")]),
        ("surface.gloss_lamination", [("panel", panel.id)]),
        ("coating.flood_uv", [("sheet", None)]),
    )
    assert_same_geometry(pid, win, vid, fin)
    z = _plates(pid, win, fin)
    lam = plates.plate_coverage(z.read("surface_gloss_lamination.pdf"), win, 2000)
    raster, _ = frame(win, 2000, FLAT_LOOK.lighting.margin)
    cy = int((150 - raster.origin[1]) * raster.scale)
    cx = int((430 - raster.origin[0]) * raster.scale)
    assert lam[cy, cx] == 0  # the window's middle: more than the bleed from its edge


def test_plates_register_on_the_page_in_k_without_the_dieline(client, project):  # noqa: F811
    pid = project
    spec = _spec(pid)
    fin = _fin(("foil.gold", [("asset", "1:2")]))
    z = _plates(pid, spec, fin)
    doc = pymupdf.open(stream=z.read("foil_gold.pdf"), filetype="pdf")
    page = doc[0]
    k = plates.physical_factor(spec)  # real size (here 0.99999: the ruler reads ~PDF points)
    assert abs(page.rect.width - spec.page.width_pt * k) < 1e-3
    assert abs(page.rect.height - spec.page.height_pt * k) < 1e-3
    box = pymupdf.Rect()
    for d in page.get_drawings():
        box |= d["rect"]
    assert abs(box.x0 - 400) < 0.5 and abs(box.y0 - 120) < 0.5
    assert abs(box.x1 - 460) < 0.5 and abs(box.y1 - 180) < 0.5
    # No guide on the plate: no layers, no stroked lines, nothing magenta.
    assert not doc.get_ocgs()
    assert all(d.get("color") is None for d in page.get_drawings())
    streams = b"".join(
        doc.xref_stream(x) or b"" for x in range(1, doc.xref_length()) if doc.xref_is_stream(x)
    )
    assert b"0 0 0 1 k" in streams and b" rg" not in streams
    die = pymupdf.open(stream=z.read("dieline.pdf"), filetype="pdf")[0]
    strokes = [d for d in die.get_drawings() if d.get("color")]
    assert strokes and all(tuple(d["color"]) == (1.0, 0.0, 1.0) for d in strokes)
    manifest = json.loads(z.read("finishing.json"))
    assert manifest["bleed_mm"] == plates.BLEED_MM and manifest["dieline"] == "dieline.pdf"


def test_a_figma_asset_without_its_outline_is_reported_not_guessed(client, project):  # noqa: F811
    pid = project
    spec = _spec(pid)
    fa.svg_path(pid, "1:8").unlink()  # the export failed (and Figma is not reachable in tests)
    fin = _fin(("foil.gold", [("asset", "1:2"), ("asset", "1:8")]))
    with pytest.raises(ApiError) as e:  # never a production export with a hole in it
        _plates(pid, spec, fin)
    assert e.value.body.code == "PLATES_NOT_VERIFIED"
    z = _plates(pid, spec, fin, draft=True)
    plate = json.loads(z.read("finishing.json"))["plates"][0]
    assert plate["missing_targets"] == ["1:8"] and plate["approximate_assets"] == []
    page = pymupdf.open(stream=z.read("DRAFT_foil_gold.pdf"), filetype="pdf")[0]
    assert not page.get_images()  # no bitmap guessed from the printed ink


CLIPPED = (
    '<svg width="60" height="60" viewBox="0 0 60 60" fill="none" '
    'xmlns="http://www.w3.org/2000/svg">'
    '<g clip-path="url(#c0)"><circle cx="30" cy="30" r="30" fill="#E1B12C"/></g>'
    '<defs><clipPath id="c0"><rect width="30" height="60" fill="white"/></clipPath></defs></svg>'
)
MASKED = (
    '<svg width="60" height="60" viewBox="0 0 60 60" fill="none" '
    'xmlns="http://www.w3.org/2000/svg">'
    '<mask id="m0" style="mask-type:alpha" maskUnits="userSpaceOnUse" x="0" y="0" width="60" '
    'height="60"><circle cx="30" cy="30" r="20" fill="#D9D9D9"/></mask>'
    '<g mask="url(#m0)"><rect width="60" height="60" fill="#E1B12C"/></g>'
    '<rect x="0" y="0" width="5" height="5" fill="#000"/></svg>'
)


def test_clip_paths_and_masks_inside_an_svg_are_honoured(client, project):  # noqa: F811
    pid = project
    vid = _flat(client, pid)
    spec = _spec(pid)
    fa.svg_path(pid, "1:2").write_text(CLIPPED)  # left half of a disc
    fin = _fin(("foil.gold", [("asset", "1:2")]))
    assert_same_geometry(pid, spec, vid, fin)
    prev, _ = _preview_masks(pid, spec, vid, fin)
    raster, _ = frame(spec, max(prev["foil.gold"].shape), FLAT_LOOK.lighting.margin)

    def at(x, y):
        return prev["foil.gold"][
            int((y - raster.origin[1]) * raster.scale), int((x - raster.origin[0]) * raster.scale)
        ]

    assert at(415, 150) > 0.5 and at(445, 150) == 0  # the hidden right half gets no foil
    assert [p.exact for p in svgclip.pieces(CLIPPED)] == [True, True]
    # A non-rectangular mask is approximated by its box and reported as such.
    assert not masks.svg_exact(MASKED)
    boxes = [p.clip for p in svgclip.pieces(MASKED)]
    assert None in boxes and (10, 10, 50, 50) in boxes
    fa.svg_path(pid, "1:2").write_text(MASKED)
    z = _plates(pid, spec, fin, draft=True)
    assert json.loads(z.read("finishing.json"))["plates"][0]["approximate_assets"] == ["1:2"]


def test_svg_transforms_compose_into_the_clip_box():
    svg = (
        '<svg width="100" height="50" viewBox="0 0 200 100" xmlns="http://www.w3.org/2000/svg">'
        '<g transform="translate(20 10)"><g clip-path="url(#c)" transform="scale(2)">'
        '<rect width="100" height="100"/></g></g>'
        '<defs><clipPath id="c"><rect x="5" y="5" width="10" height="20"/></clipPath></defs></svg>'
    )
    clipped = [p for p in svgclip.pieces(svg) if p.clip is not None]
    # viewBox halves everything: ((20 + 2*5) / 2, (10 + 2*5) / 2) .. ((20 + 2*15) / 2, (10 + 2*25) / 2)
    assert clipped[0].clip == (15.0, 10.0, 25.0, 30.0) and clipped[0].exact


# ---- production preflight ------------------------------------------------------------------


def test_exact_plates_export_for_production_with_a_clean_self_check(client, project):  # noqa: F811
    pid = project
    spec = _spec(pid)
    z = _plates(
        pid, spec, _fin(("foil.gold", [("asset", "1:2")]), ("relief.emboss", [("asset", "1:8")]))
    )
    m = json.loads(z.read("finishing.json"))
    assert m["status"] == "exact_geometry_needs_printer_preflight" and m["preflight_issues"] == []
    assert all(p["self_check"] == "passed" for p in m["plates"])
    assert not any(n.startswith("DRAFT_") or n == "PREFLIGHT.txt" for n in z.namelist())
    # Physical size: the manifest's millimetres are the page in the project's own scale.
    assert m["page_mm"][0] == round(spec.page.width_pt * spec.scale.mm_per_pt, 3)
    doc = pymupdf.open(stream=z.read("foil_gold.pdf"), filetype="pdf")
    assert "DRAFT" not in doc.metadata["title"] and "100% K" in doc.metadata["subject"]


def test_unverified_plates_are_refused_for_production_but_exportable_as_a_marked_draft(
    client,
    project,  # noqa: F811
):
    pid = project
    confirm_scale(client, pid)
    fa.svg_path(pid, "1:2").write_text(MASKED)  # a non-box mask: approximated
    body = {
        "base_revision": 0,
        "assignments": [{"finish": "foil.gold", "targets": [{"kind": "asset", "id": "1:2"}]}],
    }
    assert client.put(f"/api/projects/{pid}/finishing", json=body).status_code == 200
    pre = client.get(f"/api/projects/{pid}/finishing/preflight").json()
    assert pre["exact"] is False
    assert [(i["target"], i["status"], i["reason"]) for i in pre["issues"]] == [
        ("1:2", "approximate", "svg_clip_box")
    ]
    res = client.get(f"/api/projects/{pid}/finishing/plates")
    assert res.status_code == 409 and res.json()["error"]["code"] == "PLATES_NOT_VERIFIED"
    assert res.json()["error"]["details"]["issues"][0]["target"] == "1:2"
    draft = client.get(f"/api/projects/{pid}/finishing/plates", params={"draft": True})
    assert draft.status_code == 200
    assert "DRAFT" in draft.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(draft.content))
    names = set(z.namelist())
    assert {"DRAFT_foil_gold.pdf", "DRAFT_dieline.pdf", "PREFLIGHT.txt"} <= names
    assert not any(n.endswith(".pdf") and not n.startswith("DRAFT_") for n in names)
    m = json.loads(z.read("finishing.json"))
    assert m["status"] == "DRAFT_NOT_FOR_PRODUCTION"
    assert z.read("README.txt").decode().startswith("!!! 검토용 초안 (DRAFT)")
    doc = pymupdf.open(stream=z.read("DRAFT_foil_gold.pdf"), filetype="pdf")
    assert doc.metadata["title"].startswith("DRAFT - NOT FOR PRODUCTION")
    # The preview is not affected.
    assert client.get(f"/api/projects/{pid}/finishing").json()["revision"] == 1


def test_self_check_catches_rgb_layers_and_wrong_size(client, project):  # noqa: F811
    pid = project
    spec = _spec(pid)
    doc = pymupdf.open()
    page = doc.new_page(width=100, height=100)
    page.draw_rect(pymupdf.Rect(10, 10, 20, 20), color=None, fill=(0, 0, 0))
    doc.add_ocg("Dieline (do not print)", on=True)
    problems = plates.self_check(doc.tobytes(), spec, allow_images=False)
    assert {"page_size", "optional_content_layers", "rgb_paint", "no_k_fill"} <= set(problems)


def test_plates_are_written_at_real_size_and_need_a_confirmed_ruler(client, project):  # noqa: F811
    """A Figma page is in pixels: its plates must be scaled to millimetres (Zentra: 1920 px =
    512 mm, which Illustrator would otherwise read as 677 mm), and only from a ruler that is
    not a guess."""
    pid = project
    weak = specs.load(repo.project_or_404(pid))  # one dimension mark: confidence 0.75
    pre = plates.preflight(pid, weak, _fin(("foil.gold", [("asset", "1:2")])))
    assert [i["reason"] for i in pre["issues"]] == ["scale_unverified"]
    # A Figma-like scale: 0.2667 mm per unit (Zentra's dimension marks).
    spec = _spec(pid)
    spec.scale = spec.scale.model_copy(update={"mm_per_pt": 0.26666666666666666})
    z = _plates(pid, spec, _fin(("foil.gold", [("asset", "1:2")])))
    m = json.loads(z.read("finishing.json"))
    k = 0.26666666666666666 / (25.4 / 72)
    assert abs(m["physical_factor"] - k) < 1e-6
    for name in ("foil_gold.pdf", "dieline.pdf"):
        page = pymupdf.open(stream=z.read(name), filetype="pdf")[0]
        width_mm = page.rect.width * 25.4 / 72
        assert abs(width_mm - spec.page.width_pt * 0.26666666666666666) < 0.01, name
    # The ring (60 units at x=400..460) lands at 400k..460k pt, i.e. 60 units * 0.2667 mm wide.
    page = pymupdf.open(stream=z.read("foil_gold.pdf"), filetype="pdf")[0]
    box = pymupdf.Rect()
    for d in page.get_drawings():
        box |= d["rect"]
    assert abs(box.x0 - 400 * k) < 0.5 and abs(box.width * 25.4 / 72 - 16.0) < 0.15
