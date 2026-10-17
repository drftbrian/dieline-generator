"""Checks against synthetic PDFs with known geometry."""

import json

import numpy as np
import pymupdf
import pytest

from app.pdf.analyze import build_spec, detect, extract, find_panels
from app.render.layers import build_layers, frame
from tests.conftest import FIXTURES, fixture_bytes


def truth(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.truth.json").read_text())


ALL = [
    "named_spot",
    "ocg_layers",
    "unnamed_mixed",
    "artwork_only",
    "named_single_sep",
    "unnamed_solid",
    "figma_outlined",
]


def expected_pieces(name: str) -> list[tuple[int, int | None, str]]:
    """(painted path index, subpath index or None, class) for every expected piece."""
    out = []
    for i, want in enumerate(truth(name)["paths"]):
        if isinstance(want, list):
            out += [(i, k, cls) for k, cls in enumerate(want)]
        else:
            out.append((i, None, want))
    return out


def pieces(name: str):
    cl = detect(extract(fixture_bytes(name)))
    by_path: dict[int, list] = {}
    for c in cl.items:
        by_path.setdefault(c.path.index, []).append(c)
    return cl, by_path


@pytest.mark.parametrize("name", ALL)
def test_every_piece_matches_truth_or_waits_for_review(name):
    _, by_path = pieces(name)
    for i, k, want in expected_pieces(name):
        got = by_path[i] if k is None else [by_path[i][k]]
        for g in got:
            if g.status == "unresolved":
                assert g.suggested == want, (i, k, want, g.reason)
            else:
                assert g.cls == want, (i, k, want, g.cls, g.reason)


def test_red_artwork_is_never_silently_removed():
    """The thin red line inside the carton must not be auto-classified as a cut (FR-03)."""
    for name in ["named_spot", "unnamed_mixed", "unnamed_solid"]:
        _, by_path = pieces(name)
        for i, _k, want in expected_pieces(name):
            if want == "artwork":
                for g in by_path[i]:
                    assert not (g.cls == "cut" and g.status != "unresolved")


@pytest.mark.parametrize("name", ["named_single_sep", "unnamed_solid", "figma_outlined"])
def test_outer_line_is_cut_and_inner_lines_are_creases(name):
    """One color / one separation for the whole dieline: topology splits cut from crease."""
    spec = build_spec(*_ex_cl(name))
    assert spec.separations.cut.state in ("detected", "estimated")
    assert spec.separations.crease.state == "estimated"
    # Panels are computed once review is cleared; count them from the classified lines directly.
    assert len(find_panels(spec.paths, spec.page)) == 13
    pending = [p for p in spec.paths if p.status == "unresolved"]
    if name == "unnamed_solid":  # only the red trap line inside the carton asks a human
        assert len(pending) == 1 and pending[0].suggested_cls == "artwork"
    else:
        assert not spec.review.required, spec.review


def test_named_separations_are_detected():
    spec = build_spec(*_ex_cl("named_spot"))
    assert spec.separations.cut.state == "detected"
    assert spec.separations.crease.state == "detected"
    assert spec.separations.finish.state == "detected"
    assert any("SpotUV" in e for e in spec.separations.finish.evidence)
    assert not spec.review.required
    assert len(spec.panels) == 13


def test_review_reasons():
    assert build_spec(*_ex_cl("unnamed_mixed")).review.reasons == ["uncertain_paths"]
    assert build_spec(*_ex_cl("artwork_only")).review.reasons == ["cut_missing"]
    flat = build_spec(*_ex_cl("flattened"))
    assert flat.flattened and flat.review.reasons == ["cut_missing"]


@pytest.mark.parametrize("name", ["named_spot", "figma_outlined"])
def test_silhouette_matches_truth_outline(name):
    src = fixture_bytes(name)
    spec = build_spec(*_ex_cl(name))
    layers = build_layers(src, spec, 1200, 10)
    mm = 72 / 25.4
    poly = [(x * mm, y * mm) for x, y in truth(name)["outline_mm"]]
    from app.pdf.geometry import Raster

    raster, _ = frame(spec, 1200, 10)
    expected = Raster(
        raster.w / raster.scale, raster.h / raster.scale, raster.scale, raster.origin
    ).fill([poly])
    got = layers.silhouette > 0.5
    iou = (got & expected).sum() / (got | expected).sum()
    assert iou > 0.99, iou


def test_artwork_pixels_come_from_the_pdf():
    """Inside the cut, artwork equals a plain render of the original PDF, except exactly where
    non-printing paths (dielines, finish separations) were drawn."""
    from scipy import ndimage

    from app.pdf.geometry import Raster

    name = "named_spot"
    src = fixture_bytes(name)
    spec = build_spec(*_ex_cl(name))
    layers = build_layers(src, spec, 1000, 10)
    raster, crop = frame(spec, 1000, 10)
    page = pymupdf.open(stream=src, filetype="pdf")[0]
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(raster.scale, raster.scale), clip=pymupdf.Rect(*crop), alpha=False
    )
    ref = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).astype(float) / 255
    h, w = layers.height, layers.width
    ref = ref[:h, :w]

    r = Raster(raster.w / raster.scale, raster.h / raster.scale, raster.scale, raster.origin)
    hidden = [p for p in spec.paths if p.cls != "artwork"]
    lines = r.lines([pl for p in hidden for pl in p.polylines], width_px=3)
    fills = r.fill([pl for p in hidden if p.cls == "finish" for pl in p.polylines])
    excluded = ndimage.binary_dilation(lines | fills, iterations=2)[:h, :w]

    inside = (layers.silhouette > 0.999) & ~excluded
    diff = np.abs(ref - layers.artwork[..., :3]).max(-1)[inside]
    assert inside.sum() > 0.3 * inside.size
    assert np.percentile(diff, 99.5) < 0.02, np.percentile(diff, 99.5)


def _ex_cl(name):
    ex = extract(fixture_bytes(name))
    return ex, detect(ex)


@pytest.mark.parametrize("margin", [10, 45])
def test_artwork_stays_registered_when_frame_extends_past_page(margin):
    """A wide margin pushes the mockup frame outside the page; PyMuPDF clamps that render, and
    the artwork must still land exactly where the PDF's own path geometry says it is."""
    import io

    import pikepdf
    from scipy import ndimage

    from app.pdf.content import walk_page
    from app.pdf.geometry import Raster, flatten

    name = "named_spot"
    src = fixture_bytes(name)
    spec = build_spec(*_ex_cl(name))
    logo = next(o for o in spec.objects if o.label.startswith("흰색"))
    layers = build_layers(src, spec, 900, margin)
    if margin == 45:
        assert layers.origin[0] < 0 or layers.origin[1] < 0  # frame really leaves the page
    # The logo filled from its path geometry, independent of the render.
    walk = walk_page(pikepdf.open(io.BytesIO(src)), spec.page.index)
    polys = [
        flatten(sp)
        for p in walk.paths
        if f"{p.stream}#{p.op_index}" in logo.path_ids
        for sp in p.subpaths
    ]
    r = Raster(
        layers.width / layers.scale, layers.height / layers.scale, layers.scale, layers.origin
    )
    mask = np.zeros((r.h, r.w), bool)
    for pl in polys:
        mask ^= r.fill([pl])
    mask = mask[: layers.height, : layers.width]
    white = (layers.artwork[..., :3].min(-1) > 0.96) & (layers.artwork[..., 3] > 0.9)
    assert (mask & white).sum() / (mask | white).sum() > 0.85  # edges anti-alias differently
    # Registration: the centers agree to within a pixel (a shifted render is off by many).
    my, mx = np.argwhere(mask).mean(axis=0)
    wy, wx = np.argwhere(white & ndimage.binary_dilation(mask, iterations=3)).mean(axis=0)
    assert abs(my - wy) < 1 and abs(mx - wx) < 1, (my - wy, mx - wx)
