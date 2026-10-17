"""Physical scale, box size, Figma object placement and print-safety checks."""

import pytest

from app.figma.layers import extract_content, place
from app.pdf.analyze import build_spec, detect, extract
from app.pdf.measure import Segment, parse_box, parse_label, scale_from_marks
from app.spec.models import PDF_MM_PER_PT
from tests.conftest import fixture_bytes


def test_label_and_line_pairing():
    labels = [parse_label("100mm", (200, 0, 240, 12)), parse_label("5.2 cm", (0, 300, 30, 312))]
    segs = [
        Segment((40, 15), (415, 15)),
        Segment((40, 100), (235, 100)),
        Segment((10, 200), (10, 300)),
    ]
    # 100mm sits on the 375-long line; 5.2cm sits beside nothing long enough -> ignored
    s = scale_from_marks([lab for lab in labels if lab], segs)
    assert s is not None and s.mm_per_unit == pytest.approx(100 / 375)
    assert s.confidence == 0.75  # a single pair: plausible, not proven


def test_agreeing_marks_are_confident_and_disagreeing_are_not():
    def lab(t, x, y):
        return parse_label(t, (x, y, x + 30, y + 10))

    ok = scale_from_marks(
        [lab("100mm", 200, 8), lab("52mm", 100, 108)],
        [Segment((0, 15), (375, 15)), Segment((0, 115), (195, 115))],
    )
    assert ok.confidence == 0.95
    bad = scale_from_marks(
        [lab("100mm", 200, 8), lab("52mm", 100, 108)],
        [Segment((0, 15), (375, 15)), Segment((0, 115), (300, 115))],
    )
    assert bad.confidence == 0.6


def test_parse_box_and_units():
    assert parse_box(["젠트라 패키지 샘플", "100*52*141*"]) == (100, 52, 141)
    assert parse_box(["W 100 x 52 x 141 mm"]) == (100, 52, 141)
    assert parse_label("1.5cm", (0, 0, 1, 1)).mm == 15
    assert parse_label("Drink your zen", (0, 0, 1, 1)) is None


def test_rotated_node_lands_inside_its_box():
    # A 124x24 shape rotated -90deg (Figma vertical logo): local (0,0) -> frame (1727, 826).
    node = {
        "absoluteBoundingBox": {"x": 1000 + 1727, "y": 500 + 702, "width": 24, "height": 124},
        "relativeTransform": [[0, 1, 1727], [-1, 0, 826]],
    }
    [poly] = place(node, [{"path": "M0 0L124 0L124 24L0 24Z"}], 1000, 500)
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    assert (min(xs), min(ys), max(xs), max(ys)) == (1727, 702, 1751, 826)


@pytest.mark.parametrize("name", ["named_spot", "figma_outlined"])
def test_scale_from_the_files_own_dimension_marks(name):
    """Fixtures are drawn in real mm with a '60mm' marking: the detected scale must agree."""
    ex = extract(fixture_bytes(name))
    spec = build_spec(ex, detect(ex))
    assert spec.scale.source == "dimension_marks"
    assert spec.scale.mm_per_pt == pytest.approx(PDF_MM_PER_PT, rel=0.03)
    front = [p for p in spec.panels if abs(p.width_mm - 60) < 2 and abs(p.height_mm - 100) < 2]
    assert front, [(p.width_mm, p.height_mm) for p in spec.panels]


def test_figma_text_objects():
    frame = {
        "type": "FRAME",
        "name": "f",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 400, "height": 300},
        "children": [
            {
                "type": "TEXT",
                "id": "1:1",
                "name": "t",
                "characters": "okra",
                "style": {"fontFamily": "Figgins Sans", "fontWeight": 700, "fontSize": 5.5},
                "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1}}],
                "absoluteBoundingBox": {"x": 10, "y": 10, "width": 20, "height": 6},
            },
            {
                "type": "TEXT",
                "id": "1:2",
                "name": "d",
                "characters": "100mm",
                "style": {},
                "absoluteBoundingBox": {"x": 100, "y": 0, "width": 30, "height": 10},
            },
        ],
    }
    from app.pdf.physical import figma_objects

    content = extract_content(frame)
    objs = figma_objects(content, 100 / 375)
    assert [o.label for o in objs] == ["okra"]  # dimension labels are not artwork
    assert objs[0].detail["font"] == "Figgins Sans"
    # 5.5 units x 0.2667 mm/unit = 1.47mm cap-to-cap ~ 4.2pt in print
    assert objs[0].detail["print_pt"] == pytest.approx(4.2, abs=0.1)
