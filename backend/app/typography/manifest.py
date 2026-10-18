"""The authoritative text/logo manifest (``figma_typography_manifest.json``).

Every printed text and vector graphic comes from the Figma tree (or the PDF objects of a
PDF-only project), never from a photograph. Each item carries its exact string and font
properties, its panel and panel-local position in millimetres (the fold geometry's units),
a role (hero / secondary / regulatory) and where its exact geometry comes from:

- ``pdf_outline``: glyphs drawn from outlines embedded in the artwork PDF (Figma exports text
  as Type3 outline fonts) or a vector graphic in it. Rendered by MuPDF, never re-typeset.
- ``svg_outline``: an outlined SVG of the node is cached as well.
- ``unresolved``: a font that is not embedded and no outline. The item is never re-drawn with a
  look-alike typeface; the user has to supply outlined text.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

import pymupdf

from app.spec.models import Panel, Specification

SCHEMA = 1
HERO_PT = 14.0  # text this size or larger is primary branding
REGULATORY_PT = 7.5  # this size or smaller is regulatory copy
GRAPHIC_MAX_PANEL = 0.4  # a "graphic" covering more of its panel is a background, not a logo


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _overlap(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def panel_of(panels: list[Panel], bbox) -> tuple[Panel | None, float]:
    """The panel holding most of ``bbox``, and the fraction of ``bbox`` inside it."""
    best, frac = None, 0.0
    a = _area(bbox) or 1e-9
    for p in panels:
        f = _overlap(bbox, p.bbox) / a
        if f > frac:
            best, frac = p, f
    if best is None:  # a zero-area box (a line): by its centre
        cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        for p in panels:
            if p.bbox[0] <= cx <= p.bbox[2] and p.bbox[1] <= cy <= p.bbox[3]:
                return p, 1.0
    return best, frac


def embedded_fonts(pdf: bytes) -> dict[str, bool]:
    """Font name -> its glyph outlines are in the file (Type3 procedures or an embedded file)."""
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    out = {}
    for _xref, ext, ftype, basefont, name, _enc, *_ in doc[0].get_fonts(full=True):
        ok = ftype == "Type3" or ext != "n/a"
        for key in (basefont, name):
            if key:
                out[key] = ok
    return out


def text_fonts(pdf: bytes, bbox) -> list[str]:
    """Fonts of the PDF text spans whose box lies mostly inside ``bbox`` (page points)."""
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    fonts = set()
    clip = pymupdf.Rect(*bbox) + (-1, -1, 1, 1)
    for block in doc[0].get_text("dict", clip=clip)["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if span["text"].strip() and _overlap(span["bbox"], bbox) >= 0.5 * _area(span["bbox"]):
                    fonts.add(span["font"])
    return sorted(fonts)


def _graphic_roots(assets: list[dict], panels: list[Panel]) -> list[dict]:
    """Maximal non-text subtrees: a logo is one item, not its 40 vector pieces."""
    by_id = {a["id"]: a for a in assets}
    has_text: dict[str, bool] = {}

    def texty(a: dict) -> bool:
        if a["id"] not in has_text:
            has_text[a["id"]] = a["kind"] == "text" or any(
                texty(by_id[c]) for c in a.get("children", []) if c in by_id
            )
        return has_text[a["id"]]

    def eligible(a: dict) -> bool:
        if a["kind"] not in ("vector", "group", "image") or a.get("technical") or texty(a):
            return False
        p, frac = panel_of(panels, a["bbox"])
        return p is not None and frac >= 0.5 and _area(a["bbox"]) <= GRAPHIC_MAX_PANEL * _area(p.bbox)

    roots = []
    for a in assets:
        parent = by_id.get(a.get("parent") or "")
        if eligible(a) and not (parent and eligible(parent)):
            roots.append(a)
    return roots


def build(
    spec: Specification,
    assets: list[dict],
    pdf: bytes,
    has_svg: Callable[[str], bool],
    source_version: str | None = None,
) -> dict:
    """The manifest for every printed text and graphic that lies on a panel."""
    mm = spec.scale.mm_per_pt
    fonts_ok = embedded_fonts(pdf)
    items = []
    texts = [a for a in assets if a["kind"] == "text" and not a.get("technical")]
    for a in texts + _graphic_roots(assets, spec.panels):
        if a.get("selectable") is False and a["kind"] == "text":
            continue  # dimension labels and text off the board
        panel, frac = panel_of(spec.panels, a["bbox"])
        if panel is None or frac < 0.5:
            continue
        x0, y0, x1, y1 = a["bbox"]
        is_text = a["kind"] == "text"
        size = a.get("size")
        fonts = text_fonts(pdf, a["bbox"]) if is_text else []
        if not is_text:
            geometry = "pdf_outline"
        elif fonts and all(fonts_ok.get(f, f.startswith("Type3")) for f in fonts):
            geometry = "pdf_outline"
        elif has_svg(a["id"]):
            geometry = "svg_outline"
        elif not fonts:
            geometry = "pdf_outline"  # no live text in the PDF: the glyphs were outlined to paths
        else:
            geometry = "unresolved"
        if is_text:
            role = "hero" if (size or 0) >= HERO_PT else "regulatory" if (size or 99) <= REGULATORY_PT else "secondary"
        else:
            role = "logo" if _area(a["bbox"]) >= 0.02 * _area(panel.bbox) else "graphic"
        record = {
            "id": a["id"],
            "kind": "text" if is_text else "graphic",
            "name": a.get("name"),
            "text": a.get("text") if is_text else None,
            "font": a.get("font"),
            "weight": a.get("weight"),
            "size_pt": size,
            "letter_spacing": a.get("letter_spacing"),  # not extracted from Figma yet: None
            "line_height": a.get("line_height"),
            "align": a.get("align"),
            "color": a.get("color"),
            "opacity": a.get("opacity", 1.0),
            "pdf_fonts": fonts,
            "bbox_pt": [round(v, 2) for v in a["bbox"]],
            "panel_id": panel.id,
            "panel_name": panel.name,
            "spans_panels": frac < 0.98,
            "panel_mm": [
                round((x0 - panel.bbox[0]) * mm, 2),
                round((y0 - panel.bbox[1]) * mm, 2),
                round((x1 - panel.bbox[0]) * mm, 2),
                round((y1 - panel.bbox[1]) * mm, 2),
            ],
            "height_mm": round((y1 - y0) * mm, 2),
            "role": role,
            "geometry": geometry,
            "svg_outline": has_svg(a["id"]),
        }
        record["hash"] = hashlib.sha1(
            json.dumps(
                [record[k] for k in ("id", "text", "font", "weight", "size_pt", "color", "bbox_pt")],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()[:12]
        items.append(record)
    return {
        "schema": SCHEMA,
        "source_version": source_version,
        "spec_version": spec.version,
        "mm_per_pt": mm,
        "panels": [
            {"id": p.id, "name": p.name, "bbox_pt": list(p.bbox), "width_mm": p.width_mm, "height_mm": p.height_mm}
            for p in spec.panels
        ],
        "items": items,
        "unresolved": [i["id"] for i in items if i["geometry"] == "unresolved"],
    }
