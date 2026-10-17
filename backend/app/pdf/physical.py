"""Physical accuracy: real-world scale, box size, panel sizes and text/graphic objects from the
design tool.

Inputs come from the Figma node tree when the project was imported by link, otherwise from
the PDF itself (text lines + technical line pieces). Everything here is measured, never
generated; results carry their evidence so the UI can show *why* a number is what it is.
"""

from __future__ import annotations

from collections import Counter

from app.pdf.dieline import Classification
from app.pdf.measure import Label, Segment, parse_box, parse_label, scale_from_marks
from app.spec.models import (
    PDF_MM_PER_PT,
    ArtObject,
    BoxDims,
    PhysicalScale,
    Specification,
)

# ---- scale & box -------------------------------------------------------------------------


def _labels(texts: list[tuple[str, tuple]]) -> list[Label]:
    return [lab for text, bbox in texts if (lab := parse_label(text, bbox))]


def _pdf_segments(cl: Classification) -> list[Segment]:
    """Straight technical lines in the PDF (a dashed line = one path of many dashes)."""
    by_path: dict[int, list] = {}
    for c in cl.items:
        if c.line_like and c.cls in ("annotation", "artwork"):
            by_path.setdefault(c.path.index, []).append(c)
    segs = []
    for items in by_path.values():
        xs = [x for c in items for pl in c.polylines for x, _ in pl]
        ys = [y for c in items for pl in c.polylines for _, y in pl]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if h < 3 and w >= 20:
            y = (min(ys) + max(ys)) / 2
            segs.append(Segment((min(xs), y), (max(xs), y)))
        elif w < 3 and h >= 20:
            x = (min(xs) + max(xs)) / 2
            segs.append(Segment((x, min(ys)), (x, max(ys))))
    return segs


def detect_scale(
    texts: list[tuple[str, tuple]], segments: list[Segment]
) -> tuple[PhysicalScale, BoxDims | None]:
    box_vals = parse_box([t for t, _ in texts])
    box = (
        BoxDims(width_mm=box_vals[0], depth_mm=box_vals[1], height_mm=box_vals[2])
        if box_vals
        else None
    )
    found = scale_from_marks(_labels(texts), segments)
    if found:
        return PhysicalScale(
            mm_per_pt=found.mm_per_unit,
            source="dimension_marks",
            confidence=found.confidence,
            evidence=found.evidence,
        ), box
    return PhysicalScale(), box


def scale_inputs(design: dict | None, text_lines: list[dict], cl: Classification):
    if design:
        texts = [(t["text"], tuple(t["bbox"])) for t in design["texts"]]
        segs = [Segment(tuple(s["a"]), tuple(s["b"])) for s in design["segments"]]
    else:
        texts = [(t["text"], tuple(t["bbox"])) for t in text_lines]
        segs = _pdf_segments(cl)
    return texts, segs


def _body_height_pt(spec: Specification) -> float | None:
    """The carton body: the panel height most panels share (side/front/back/side)."""
    if not spec.panels:
        return None
    tall = max(p.bbox[3] - p.bbox[1] for p in spec.panels)
    heights = [
        round(p.bbox[3] - p.bbox[1]) for p in spec.panels if p.bbox[3] - p.bbox[1] > 0.5 * tall
    ]
    if not heights:
        return None
    return float(Counter(heights).most_common(1)[0][0])


def refresh(spec: Specification, design: dict | None) -> None:
    """Recompute everything that depends on scale, structure or design content."""
    # A known box size calibrates files that have no dimension marks.
    if spec.scale.source == "pdf_units" and spec.box:
        body = _body_height_pt(spec)
        if body:
            spec.scale = PhysicalScale(
                mm_per_pt=spec.box.height_mm / body,
                source="dimension_marks",
                confidence=0.7,
                evidence=[f"규격 높이 {spec.box.height_mm:g}mm ↔ 몸통 패널 {body:.0f}"],
            )
    k = spec.scale.mm_per_pt
    for p in spec.panels:
        w, h = p.bbox[2] - p.bbox[0], p.bbox[3] - p.bbox[1]
        p.width_mm, p.height_mm = round(w * k, 1), round(h * k, 1)
        p.area_mm2 = round((p.area_pt2 or p.area_mm2 / PDF_MM_PER_PT**2) * k * k, 1)
    for o in spec.objects:
        if o.kind == "text" and o.detail.get("size"):
            o.detail["print_pt"] = round(o.detail["size"] * k / PDF_MM_PER_PT, 1)


# ---- objects from Figma -----------------------------------------------------------------


def _color_name(hex_: str | None) -> str:
    if not hex_:
        return "색 없음"
    r, g, b = (int(hex_[i : i + 2], 16) for i in (1, 3, 5))
    if min(r, g, b) > 240:
        return "흰색"
    if max(r, g, b) < 30:
        return "검정"
    return hex_


def figma_objects(design: dict, mm_per_pt: float) -> list[ArtObject]:
    objs: list[ArtObject] = []
    for i, t in enumerate(design["texts"]):
        if t.get("technical") or not t["text"].strip() or parse_label(t["text"], t["bbox"]):
            continue  # dimension labels are marks, not artwork
        objs.append(
            ArtObject(
                id=f"ftext{i + 1}",
                kind="text",
                label=" ".join(t["text"].split())[:40],
                bbox=tuple(t["bbox"]),
                color=t.get("color"),
                detail={
                    "font": t.get("font"),
                    "weight": t.get("weight"),
                    "size": t.get("size"),
                    "print_pt": round((t.get("size") or 0) * mm_per_pt / PDF_MM_PER_PT, 1),
                    "figma_node": t["id"],
                },
            )
        )
    for i, g in enumerate(design["graphics"]):
        w = (g["bbox"][2] - g["bbox"][0]) * mm_per_pt
        h = (g["bbox"][3] - g["bbox"][1]) * mm_per_pt
        label = f"그래픽 · {_color_name(g.get('color'))}" if g["generic_name"] else g["name"]
        objs.append(
            ArtObject(
                id=f"fnode{i + 1}",
                kind="vector",
                label=f"{label} · {w:.0f}×{h:.0f}mm",
                bbox=tuple(g["bbox"]),
                color=g.get("color"),
                detail={"figma_node": g["id"], "figma_name": g["name"]},
            )
        )
    return objs
