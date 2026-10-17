"""Prompt templates fill completely, and the Figma strings reach them verbatim."""

import json
import re

import pytest

from app.ai import prompts
from app.services import brief, merge, pipeline, specs
from app.storage import repo
from tests.conftest import upload

FLAT_KEYS = ["figma_url", "dims", "panels", "fonts", "logos", "colours", "texts_by_panel"]
MERGE_KEYS = [
    "figma_url",
    "form_rule",
    "category",
    "dims",
    "colours",
    "texts_by_face",
    "reference_sections",
    "camera",
    "light",
]


@pytest.mark.parametrize(("name", "keys"), [("flat_render", FLAT_KEYS), ("merge", MERGE_KEYS)])
def test_templates_name_exactly_these_placeholders(name, keys):
    found = set(re.findall(r"\$(\w+)", (prompts.DIR / f"{name}.md").read_text()))
    assert found == set(keys)
    out = prompts.render(name, **{k: f"<{k}>" for k in keys})
    assert "$" not in out and all(f"<{k}>" in out for k in keys)
    with pytest.raises(KeyError):
        prompts.render(name, **{k: "x" for k in keys[1:]})  # one left unfilled


TEXT = 'NATURE\'S "Best" — 100% 유기농\nLine two'
VERBATIM = '"NATURE\'S "Best" — 100% 유기농 / Line two"'

READING = {
    "schema": 2,
    "category": "product_packaging",
    "summary": "흰 배경 위에 선 박스",
    "sections": [
        {"key": k, "title_ko": k, "text_en": f"About {k}."}
        for k in (
            "structure",
            "typography",
            "color",
            "material",
            "background_styling",
            "brand_mood",
            "extras",
        )
    ],
    "packaging_form": "folded",
    "camera": {
        "azimuth": 25,
        "elevation": 12,
        "lens_mm": 50,
        "placement": [0.3, 0.2, 0.7, 0.85],
        "aspect_ratio": "4:5",
    },
    "light": {
        "key_azimuth": 315,
        "key_elevation": 40,
        "quality": "soft",
        "shadow": "Soft shadow to the lower right.",
        "temperature": "neutral",
    },
    "prompt_en": "A carton on a white sweep.",
}


def _figma_texts(pid):
    """Pretend the project came from Figma: one text on the front panel."""
    spec = specs.load(repo.project_or_404(pid))
    faces = merge.carton3d.map_faces(spec.panels, spec.box)
    a, b, c, d = faces["front"]
    cx, cy = (a + c) / 2, (b + d) / 2
    content = {
        "texts": [
            {
                "id": "1:1",
                "text": TEXT,
                "font": "Pretendard",
                "weight": 700,
                "size": 12,
                "color": "#1A2B3C",
                "bbox": [cx - 10, cy - 4, cx + 10, cy + 4],
                "technical": False,
            },
            {
                "id": "1:2",
                "text": "TECH NOTE",
                "font": "Arial",
                "size": 6,
                "color": "#FF0000",
                "bbox": [cx - 10, cy + 6, cx + 10, cy + 9],
                "technical": True,
            },
        ],
        "graphics": [
            {
                "id": "2:1",
                "name": "Brand Logo",
                "generic_name": False,
                "bbox": [a + 2, b + 2, a + 20, b + 10],
                "color": "#C0FFEE",
                "polygons": [],
            }
        ],
        "segments": [],
    }
    (repo.project_dir(pid) / "figma_content.json").write_text(json.dumps(content))
    repo.update("projects", pid, figma_json={"url": "https://www.figma.com/design/abc?node-id=1-2"})
    return spec


def test_figma_strings_reach_both_prompts_verbatim(client):
    pid, _ = upload(client, "named_spot")
    spec = _figma_texts(pid)
    b = brief.figma_brief(pid, spec)
    assert VERBATIM in b.texts_by_panel and VERBATIM in b.texts_by_face
    assert "TECH NOTE" not in b.texts_by_panel  # technical layers are not print
    assert "front panel" in b.texts_by_face
    assert "Pretendard 700" in b.fonts and "Brand Logo" in b.logos
    assert "#1A2B3C" in b.colours and "#C0FFEE" in b.colours

    flat = pipeline.flat_prompt(pid, spec)
    assert VERBATIM in flat and "https://www.figma.com/design/abc" in flat and "$" not in flat
    for form in ("flat", "folded"):
        text = merge.merge_prompt(pid, spec, READING, form)
        assert VERBATIM in text and merge.FORM_RULES[form] in text and "$" not in text
        assert "About background_styling." in text and "azimuth 25 deg" in text


def test_pdf_only_projects_fall_back_to_the_pdf_text(client):
    pid, _ = upload(client, "named_spot")
    spec = specs.load(repo.project_or_404(pid))
    b = brief.figma_brief(pid, spec)
    assert b.figma_url == "(not a Figma import)"
    assert b.panels != "(none)" and "mm" in b.dims
    assert "$" not in pipeline.flat_prompt(pid, spec)
