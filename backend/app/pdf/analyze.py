"""PDF -> Packaging Specification.

Split into stages so the job runner can report progress and isolate failures.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import pikepdf
import pymupdf
from scipy import ndimage

from app.pdf import physical, rules
from app.pdf.content import WalkResult, walk_page
from app.pdf.dieline import Classification, Classified, classify
from app.pdf.geometry import Raster, to_hex
from app.spec.models import (
    ArtObject,
    Counts,
    LayerInfo,
    PageInfo,
    Panel,
    ReviewState,
    SeparationItem,
    Separations,
    Specification,
    StructuralPath,
)

PT_TO_MM = 25.4 / 72


@dataclass
class Extraction:
    page: PageInfo
    walk: WalkResult
    text_lines: list[dict]
    images: list[dict]
    fonts: list[dict]
    flattened: bool
    design: dict | None = None  # Figma content (texts, graphics, lines) when imported by link


def extract(
    source: bytes,
    page_index: int = 0,
    design_shapes: list[dict] | None = None,
    design_content: dict | None = None,
) -> Extraction:
    doc = pymupdf.open(stream=source, filetype="pdf")
    page = doc[page_index]
    rect = page.rect
    info = PageInfo(
        index=page_index,
        count=doc.page_count,
        width_pt=round(rect.width, 3),
        height_pt=round(rect.height, 3),
        width_mm=round(rect.width * PT_TO_MM, 1),
        height_mm=round(rect.height * PT_TO_MM, 1),
        rotation=page.rotation,
    )
    text_lines = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text_lines.append(
                {
                    "text": "".join(s["text"] for s in spans).strip(),
                    "bbox": tuple(round(v, 2) for v in line["bbox"]),
                    "color": f"#{spans[0]['color']:06X}",
                    "font": spans[0]["font"],
                    "size": round(spans[0]["size"], 1),
                }
            )
    images = []
    for im in page.get_image_info(xrefs=True):
        x0, y0, x1, y1 = im["bbox"]
        w_in = max((x1 - x0) / 72, 1e-6)
        images.append(
            {
                "bbox": (round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
                "dpi": round(im["width"] / w_in),
                "colorspace": im.get("colorspace"),
                "xref": im.get("xref"),
            }
        )
    fonts = [{"name": f[3], "embedded": f[1] != "n/a"} for f in page.get_fonts()]

    pdf = pikepdf.open(io.BytesIO(source))
    walk = walk_page(pdf, page_index)
    if design_shapes:
        from app.figma.layers import apply_design_layers

        apply_design_layers(walk.paths, design_shapes, rect.width, rect.height)

    page_area = rect.width * rect.height
    covering = any(
        (im["bbox"][2] - im["bbox"][0]) * (im["bbox"][3] - im["bbox"][1]) > 0.8 * page_area
        for im in images
    )
    flattened = covering and len(walk.paths) == 0 and not text_lines
    return Extraction(info, walk, text_lines, images, fonts, flattened, design_content)


def detect(ex: Extraction) -> Classification:
    return classify(ex.walk.paths, ex.page.width_pt, ex.page.height_pt)


def separations(ex: Extraction, cl: Classification) -> Separations:
    def evidence(cls: str) -> tuple[int, list[str]]:
        items = [c for c in cl.items if c.cls == cls]
        # A name counts as evidence only for the class it names: a fold split out of a
        # "Die" separation is an inference, not a detected crease separation.
        names = sorted(
            {c.named_by for c in items if c.named_by and _named_class(c.named_by) == cls}
        )
        return len(items), names

    n_cut, cut_names = evidence("cut")
    if cut_names:
        cut = SeparationItem(state="detected", required=True, path_count=n_cut, evidence=cut_names)
    elif n_cut:
        cut = SeparationItem(
            state="estimated", required=True, path_count=n_cut, evidence=["외곽 형태로 추정"]
        )
    else:
        cut = SeparationItem(state="missing", required=True)

    n_cr, cr_names = evidence("crease")
    if cr_names:
        crease = SeparationItem(
            state="detected", required=False, path_count=n_cr, evidence=cr_names
        )
    elif n_cr:
        crease = SeparationItem(
            state="estimated", required=False, path_count=n_cr, evidence=["칼선 안쪽 선으로 추정"]
        )
    else:
        crease = SeparationItem(state="absent_optional", required=False)

    vectors = len({c.path.index for c in cl.items if c.cls == "artwork"})  # paths, not pieces
    art_ev = [f"벡터 {vectors}", f"이미지 {len(ex.images)}"]
    art_ev.append(f"텍스트 {len(ex.text_lines)}줄" if ex.text_lines else "텍스트 아웃라인/없음")
    artwork = SeparationItem(
        state="detected" if (vectors or ex.images or ex.text_lines) else "missing",
        required=True,
        path_count=vectors,
        evidence=art_ev,
    )

    # Finishing separations (spot UV, white ink, ...) are detected and reported, never rendered.
    names = sorted({c.named_by for c in cl.items if c.cls == "finish" and c.named_by})
    refs = {c.source_ref for c in cl.items if c.cls == "finish" and c.named_by}
    finish = SeparationItem(
        state="detected" if names else "absent_optional",
        required=False,
        path_count=len(refs),
        evidence=names,
    )
    return Separations(cut=cut, crease=crease, artwork=artwork, finish=finish)


def _named_class(named_by: str) -> str | None:
    name = named_by.split("'")[1] if "'" in named_by else named_by
    return rules.match(name)


def structural_paths(cl: Classification) -> list[StructuralPath]:
    """Pieces the user may need to see or classify: everything but plain filled artwork."""
    out = []
    for c in cl.items:
        p = c.path
        # Printed shapes stay out of the review list, including outlined text glyphs.
        if c.cls == "artwork" and c.status != "unresolved" and (not c.line_like or c.from_fill):
            continue
        rgb = p.stroke_rgb if p.stroke else p.fill_rgb
        out.append(
            StructuralPath(
                id=c.id,
                cls=c.cls,
                status=c.status,
                suggested_cls=c.suggested,
                confidence=round(c.confidence, 2),
                provenance=c.provenance,
                reason=c.reason,
                polylines=c.polylines,
                closed=[len(pl) > 2 and pl[0] == pl[-1] for pl in c.polylines]
                if c.sub is not None or c.line_like
                else p.closed,
                bbox=tuple(round(v, 2) for v in c.bbox),
                color=to_hex(rgb),
                dashed=p.dashed,
                width_pt=round(c.width if c.line_like else p.line_width, 2),
                color_space=p.stroke_cs if p.stroke else p.fill_cs,
                layers=p.ocgs,
                source_ref=c.source_ref,
                subpath=c.sub,
            )
        )
    return out


def silhouette_mask(paths: list[StructuralPath], raster: Raster) -> np.ndarray:
    """Area enclosed by the cut outline (lines included)."""
    from app.pdf.geometry import cut_silhouette

    cut_lines = [pl for p in paths if p.cls == "cut" for pl in p.polylines]
    if not cut_lines:
        return np.zeros((raster.h, raster.w), bool)
    return cut_silhouette(raster, cut_lines)


def is_closed(mask: np.ndarray) -> bool:
    return bool(mask.mean() > 0.01)


def find_panels(paths: list[StructuralPath], page: PageInfo) -> list[Panel]:
    scale = min(2.0, 2400 / max(page.width_pt, page.height_pt))
    raster = Raster(page.width_pt, page.height_pt, scale)
    sil = silhouette_mask(paths, raster)
    if not is_closed(sil):
        return []
    cuts = raster.lines([pl for p in paths if p.cls == "cut" for pl in p.polylines], 3)
    creases = raster.lines([pl for p in paths if p.cls == "crease" for pl in p.polylines], 3)
    interior = sil & ~cuts & ~creases
    labels, n = ndimage.label(interior)
    panels: list[Panel] = []
    total = interior.sum()
    for i, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        area_px = (labels[sl] == i).sum()
        if area_px < 0.005 * total:
            continue
        y, x = sl
        bbox = (x.start / scale, y.start / scale, x.stop / scale, y.stop / scale)
        panels.append(
            Panel(
                id=f"panel{len(panels) + 1}",
                name=f"패널 {len(panels) + 1}",
                name_provenance="extracted",
                bbox=tuple(round(v, 1) for v in bbox),
                area_mm2=round(area_px / scale**2 * PT_TO_MM**2, 1),
                area_pt2=round(area_px / scale**2, 1),
            )
        )
    panels.sort(key=lambda p: (round(p.bbox[1] / 20), p.bbox[0]))
    for i, p in enumerate(panels, start=1):
        p.id, p.name = f"panel{i}", f"패널 {i}"
    return panels


def art_objects(ex: Extraction, cl: Classification) -> list[ArtObject]:
    objs: list[ArtObject] = []
    for i, t in enumerate(ex.text_lines):
        objs.append(
            ArtObject(
                id=f"text{i + 1}",
                kind="text",
                label=t["text"][:32],
                bbox=t["bbox"],
                color=t["color"],
                detail={"font": t["font"], "size": t["size"]},
            )
        )
    for i, im in enumerate(ex.images):
        objs.append(
            ArtObject(
                id=f"image{i + 1}",
                kind="image",
                label=f"이미지 {i + 1} ({im['dpi']}dpi)",
                bbox=im["bbox"],
                detail={"dpi": im["dpi"]},
            )
        )

    # Group filled artwork paths: same color, same layer, touching bboxes -> one object
    # (an outlined logo becomes one selectable thing instead of one per glyph).
    seen: set[int] = set()
    fills = []
    for c in cl.items:
        if c.cls == "artwork" and c.path.fill and not c.line_like and c.path.index not in seen:
            seen.add(c.path.index)
            fills.append(c)
    page_area = ex.page.width_pt * ex.page.height_pt
    fills = [c for c in fills if _area(c.path.bbox) < 0.25 * page_area]
    parent = list(range(len(fills)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a in range(len(fills)):
        for b in range(a + 1, len(fills)):
            pa, pb = fills[a].path, fills[b].path
            # Letter spacing scales with glyph size, so the merge gap does too; very different
            # sizes (a big logo next to a block of small text) are separate objects.
            gap = max(6.0, 0.5 * min(pa.bbox[3] - pa.bbox[1], pb.bbox[3] - pb.bbox[1]))
            areas = sorted((max(_area(pa.bbox), 1e-6), max(_area(pb.bbox), 1e-6)))
            if (
                to_hex(pa.fill_rgb) == to_hex(pb.fill_rgb)
                and pa.ocgs == pb.ocgs
                and areas[1] / areas[0] <= 4
                and _near(pa.bbox, pb.bbox, gap)
            ):
                parent[find(a)] = find(b)
    groups: dict[int, list[Classified]] = {}
    for i, c in enumerate(fills):
        groups.setdefault(find(i), []).append(c)
    for n, members in enumerate(sorted(groups.values(), key=lambda g: g[0].path.index), start=1):
        color = to_hex(members[0].path.fill_rgb)
        objs.append(
            ArtObject(
                id=f"vector{n}",
                kind="vector",
                label=f"{_color_name(color)} 벡터 {len(members)}개",
                bbox=_union([m.path.bbox for m in members]),
                color=color,
                path_ids=[m.source_ref for m in members],
            )
        )
    return objs


def review_state(paths: list[StructuralPath], page: PageInfo) -> tuple[ReviewState, bool]:
    reasons = []
    pending = sum(1 for p in paths if p.status == "unresolved")
    if pending:
        reasons.append("uncertain_paths")
    has_cut = any(p.cls == "cut" for p in paths)
    closed = False
    if not has_cut:
        reasons.append("cut_missing")
    else:
        scale = min(1.0, 1600 / max(page.width_pt, page.height_pt))
        closed = is_closed(silhouette_mask(paths, Raster(page.width_pt, page.height_pt, scale)))
        if not closed:
            reasons.append("cut_open")
    return ReviewState(required=bool(reasons), reasons=reasons, pending=pending), closed


def layer_info(ex: Extraction, cl: Classification) -> list[LayerInfo]:
    counts: dict[str, int] = {}
    for c in cl.items:
        for layer in c.path.ocgs:
            counts[layer] = counts.get(layer, 0) + 1
    return [
        LayerInfo(name=n, path_count=counts.get(n, 0), role=rules.match(n))
        for n in ex.walk.ocg_names
    ]


def build_spec(ex: Extraction, cl: Classification) -> Specification:
    seps = separations(ex, cl)
    paths = structural_paths(cl)
    review, _ = review_state(paths, ex.page)
    panels = find_panels(paths, ex.page) if not review.required else []
    texts, segments = physical.scale_inputs(ex.design, ex.text_lines, cl)
    scale, box = physical.detect_scale(texts, segments)
    if ex.design:
        # Figma knows the real objects: exact text runs and named graphics replace the
        # PDF guesses (same-color fill groups, text lines); embedded images stay.
        objs = physical.figma_objects(ex.design, scale.mm_per_pt)
        objs += [o for o in art_objects(ex, cl) if o.kind == "image"]
    else:
        objs = art_objects(ex, cl)
    objects = inside_cut(objs, paths, ex.page)
    spec = Specification(
        page=ex.page,
        flattened=ex.flattened,
        separations=seps,
        paths=paths,
        panels=panels,
        objects=objects,
        layers=layer_info(ex, cl),
        review=review,
        structure_confirmed=not review.required,
        counts=Counts(
            vectors=len(ex.walk.paths),
            images=len(ex.images),
            text_spans=len(ex.text_lines),
            fonts=sorted({f["name"] for f in ex.fonts}),
            color_spaces=sorted(ex.walk.color_spaces),
            spot_colors=sorted(ex.walk.spot_names),
        ),
        scale=scale,
        box=box,
    )
    physical.refresh(spec, ex.design)
    return spec


def inside_cut(
    objs: list[ArtObject], paths: list[StructuralPath], page: PageInfo
) -> list[ArtObject]:
    """Drop objects outside the carton outline (dimension labels, slug text)."""
    scale = min(1.0, 1600 / max(page.width_pt, page.height_pt))
    raster = Raster(page.width_pt, page.height_pt, scale)
    sil = silhouette_mask(paths, raster)
    if not is_closed(sil):
        return objs
    keep = []
    for o in objs:
        cx, cy = raster.px(((o.bbox[0] + o.bbox[2]) / 2, (o.bbox[1] + o.bbox[3]) / 2))
        if 0 <= int(cy) < raster.h and 0 <= int(cx) < raster.w and sil[int(cy), int(cx)]:
            keep.append(o)
    return keep


def hidden_for_render(
    spec: Specification, walk_hidden_layers: set[str]
) -> tuple[set[str], set[str]]:
    refs = {p.source_ref for p in spec.paths if p.cls != "artwork" and "#" in p.source_ref}
    return refs, walk_hidden_layers


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _near(a, b, gap: float) -> bool:
    return not (a[2] + gap < b[0] or b[2] + gap < a[0] or a[3] + gap < b[1] or b[3] + gap < a[1])


def _union(boxes) -> tuple[float, float, float, float]:
    return (
        round(min(b[0] for b in boxes), 2),
        round(min(b[1] for b in boxes), 2),
        round(max(b[2] for b in boxes), 2),
        round(max(b[3] for b in boxes), 2),
    )


def _color_name(hex_: str) -> str:
    r, g, b = (int(hex_[i : i + 2], 16) for i in (1, 3, 5))
    spread = max(r, g, b) - min(r, g, b)
    if min(r, g, b) > 240:
        return "흰색"
    if max(r, g, b) < 30:
        return "검정"
    if spread < 12 and 30 <= max(r, g, b) <= 220:
        return "회색"
    return hex_
