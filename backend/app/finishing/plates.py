"""Finishing plates for the printer: one vector PDF per finish, in the source page's
coordinates (so it registers with the dieline and the print), with the art in 100% K, plus the
dieline as its own guide file and the specification as JSON.

The plates are drawn from the same geometry as the preview (``compose``): Figma assets are the
node's outlined SVG (recoloured to black, clipped like the preview by its clipping ancestors and
its own clip-paths and masks), sheet and panel targets are the board and the panel boxes, and
everything is clipped to the board (openings cut out) grown by ``BLEED_MM``, so a finish that
runs to a cut edge keeps a little bleed for the die-cut tolerance. Inside the board a plate is
the preview's mask (``plate_coverage`` + tests compare them). PDF-only assets have no vectors:
their mask is embedded as a bitmap and listed as approximate. A Figma asset whose outline is not
available is left out and listed as missing, never guessed from the printed ink.

The dieline is not on the plates: a layer named "do not print" still prints on a RIP that
ignores optional content, so cut and fold lines go in ``dieline.pdf`` (same page, same
coordinates) for checking registration.
"""

from __future__ import annotations

import io
import json
import math
import re
import zipfile

import numpy as np
import pymupdf
from PIL import Image
from scipy import ndimage

from app.errors import ApiError
from app.finishing import assets as fa
from app.finishing import catalog, masks
from app.finishing import spec as fspec
from app.render.layers import _closed_polys, board, frame, package_bbox, structure_key
from app.services import pipeline
from app.spec.models import FLAT_LOOK, PDF_MM_PER_PT, Specification
from app.storage import repo

BLACK = (0, 0, 0)
DIELINE = (1, 0, 1)  # magenta, in the separate guide file
APPROX_EDGE = 6000  # px, long edge of the raster used for PDF-only (approximate) assets
BLEED_MM = 1.0  # past the cut: a finish running to the edge survives die-cut tolerance
TRACE_PX_PER_MM = 8  # resolution of the board outline used as the plates' clip
TRACE_MAX_EDGE = 6000
TRACE_TOL_PX = 0.5  # outline simplification
# How far the traced clip may sit from the true bleed line (one trace pixel + simplification).
# It only moves the bleed's outer edge, outside the board; the board itself is the preview's.
OUTLINE_TOL_MM = (1 + TRACE_TOL_PX) / TRACE_PX_PER_MM

_COLOUR = re.compile(r'(fill|stroke|stop-color)\s*=\s*"(?!none)[^"]*"')
_STYLE = re.compile(r"(fill|stroke|stop-color)\s*:\s*(?!none)[^;\"]+")
_OPACITY = re.compile(r'(fill-opacity|stroke-opacity|opacity)\s*=\s*"[^"]*"')
_RGB_BLACK = re.compile(rb"(?<![\d.])0 0 0 (rg|RG)(?![A-Za-z])")


def black_svg(svg: str) -> str:
    """The SVG with every paint set to 100% black and opacities removed (a plate is solid)."""
    svg = _COLOUR.sub(lambda m: f'{m.group(1)}="#000000"', svg)
    svg = _STYLE.sub(lambda m: f"{m.group(1)}:#000000", svg)
    return _OPACITY.sub("", svg)


# ---- the board as vectors ----------------------------------------------------------------


def _loops(b: np.ndarray) -> list[np.ndarray]:
    """Closed outlines of a binary image along pixel edges, as (row, col) corner points. Holes
    come out as their own loops; filled even-odd they give back exactly the pixel set."""
    p = np.pad(b, 1)
    ins = p[1:-1, 1:-1]
    w1 = b.shape[1] + 1
    starts, ends = [], []
    for edge, (ra, ca, rb, cb) in (
        (ins & ~p[:-2, 1:-1], (0, 0, 0, 1)),  # top: left -> right
        (ins & ~p[1:-1, 2:], (0, 1, 1, 1)),  # right: down
        (ins & ~p[2:, 1:-1], (1, 1, 1, 0)),  # bottom: right -> left
        (ins & ~p[1:-1, :-2], (1, 0, 0, 0)),  # left: up
    ):
        r, c = np.nonzero(edge)
        starts.append((r + ra) * w1 + c + ca)
        ends.append((r + rb) * w1 + c + cb)
    s, e = np.concatenate(starts), np.concatenate(ends)
    nxt: dict[int, list[int]] = {}
    for a, z in zip(s.tolist(), e.tolist(), strict=True):
        nxt.setdefault(a, []).append(z)
    loops = []
    while nxt:
        v0 = next(iter(nxt))
        loop, v = [v0], v0
        while True:
            outs = nxt.get(v)
            if not outs:
                break
            z = outs.pop()
            if not outs:
                del nxt[v]
            if z == v0:
                break
            loop.append(z)
            v = z
        pts = np.array([(q // w1, q % w1) for q in loop], np.float64)
        loops.append(pts)
    return loops


def _simplify(pts: np.ndarray, tol: float) -> np.ndarray:
    """Ramer-Douglas-Peucker on a closed loop (staircases become their diagonals)."""
    if len(pts) <= 4:
        return pts
    far = int(np.argmax(((pts - pts[0]) ** 2).sum(1)))
    keep = np.zeros(len(pts), bool)
    keep[[0, far]] = True
    ring = np.vstack([pts, pts[:1]])
    stack = [(0, far), (far, len(pts))]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        a, b = ring[i], ring[j]
        seg = ring[i + 1 : j]
        d = b - a
        n = math.hypot(*d)
        if n == 0:
            dist = np.hypot(*(seg - a).T)
        else:
            dist = np.abs(d[0] * (seg[:, 1] - a[1]) - d[1] * (seg[:, 0] - a[0])) / n
        k = int(np.argmax(dist))
        if dist[k] > tol:
            m = i + 1 + k
            keep[m % len(pts)] = True
            stack += [(i, m), (m, j)]
    return pts[keep]


def board_outline(
    spec: Specification, bleed_mm: float = BLEED_MM
) -> list[list[tuple[float, float]]]:
    """The board (the same silhouette the render and the preview use: openings cut out) grown
    by ``bleed_mm``, as closed loops in page pt, to be filled even-odd."""
    cut = _closed_polys(spec, "cut")
    if not cut:
        w, h = spec.page.width_pt, spec.page.height_pt
        return [[(0, 0), (w, 0), (w, h), (0, h)]]
    x0, y0, x1, y1 = package_bbox(spec)
    size_mm = max(x1 - x0, y1 - y0) * spec.scale.mm_per_pt
    long_edge = min(TRACE_MAX_EDGE, math.ceil(size_mm * TRACE_PX_PER_MM))
    raster, _ = frame(spec, long_edge, FLAT_LOOK.lighting.margin)
    b = board(raster, cut)
    if bleed_mm > 0:
        r = bleed_mm / spec.scale.mm_per_pt * raster.scale
        b = ndimage.distance_transform_edt(~b) <= r
    ox, oy = raster.origin
    out = []
    for pts in _loops(b):
        pts = _simplify(pts, TRACE_TOL_PX)
        if len(pts) >= 3:
            out.append([(ox + col / raster.scale, oy + row / raster.scale) for row, col in pts])
    return out


def _clip_to(doc, page, loops: list[list[tuple[float, float]]]) -> None:
    """Clip everything drawn on ``page`` so far to ``loops`` (even-odd), as a PDF clip path."""
    page.clean_contents()
    xrefs = page.get_contents()
    body = b"\n".join(doc.xref_stream(x) or b"" for x in xrefs)
    tm = page.transformation_matrix
    ops = []
    for pl in loops:
        pts = [pymupdf.Point(x, y) * tm for x, y in pl]
        ops.append(f"{pts[0].x:.3f} {pts[0].y:.3f} m")
        ops += [f"{p.x:.3f} {p.y:.3f} l" for p in pts[1:]]
        ops.append("h")
    clip = ("q\n" + "\n".join(ops) + "\nW* n\n").encode()
    doc.update_stream(xrefs[0], clip + body + b"\nQ\n")
    for x in xrefs[1:]:
        doc.update_stream(x, b"")


def _to_k(doc) -> None:
    """DeviceRGB black -> 100% K in every content stream (pages and forms), so the plate's art
    is one solid separation rather than a rich black a RIP might build from four inks."""
    for x in range(1, doc.xref_length()):
        if not doc.xref_is_stream(x):
            continue
        sub = doc.xref_get_key(x, "Subtype")[1]
        if sub not in ("null", "/Form"):
            continue  # images, fonts, ICC profiles
        data = doc.xref_stream(x)
        if not data or b" rg" not in data and b" RG" not in data:
            continue
        new = _RGB_BLACK.sub(lambda m: b"0 0 0 1 k" if m.group(1) == b"rg" else b"0 0 0 1 K", data)
        if new != data:
            doc.update_stream(x, new)


# ---- plates ------------------------------------------------------------------------------


def _dieline_pdf(spec: Specification) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=spec.page.width_pt, height=spec.page.height_pt)
    shape = page.new_shape()
    for pl in _closed_polys(spec, "cut"):
        shape.draw_polyline([pymupdf.Point(*p) for p in pl])
    shape.finish(color=DIELINE, width=0.25, closePath=False)
    creases = _closed_polys(spec, "crease")
    if creases:
        for pl in creases:
            shape.draw_polyline([pymupdf.Point(*p) for p in pl])
        shape.finish(color=DIELINE, width=0.25, dashes="[3 2] 0", closePath=False)
    shape.commit()
    return doc.tobytes(deflate=True)


def physical_factor(spec: Specification) -> float:
    """Page units -> PDF points at real size. A print-ready PDF is already in points (1.0); a
    Figma export is in pixels, which the project's ruler (``spec.scale``, e.g. dimension marks)
    turns into millimetres. Plates and the dieline are written at real size, so a printer's
    software reads the carton's true dimensions (Zentra: 1920 px page = 512 mm, not 677 mm)."""
    return spec.scale.mm_per_pt / PDF_MM_PER_PT


def _to_physical(pdf: bytes, spec: Specification, metadata: dict | None = None) -> bytes:
    """The one-page PDF scaled by ``physical_factor`` (vectors kept: the page becomes a form)."""
    k = physical_factor(spec)
    src = pymupdf.open(stream=pdf, filetype="pdf")
    if abs(k - 1) < 1e-6:
        out = src
    else:
        out = pymupdf.open()
        page = out.new_page(width=spec.page.width_pt * k, height=spec.page.height_pt * k)
        page.show_pdf_page(page.rect, src, 0)
    if metadata:
        out.set_metadata(metadata)
    return out.tobytes(deflate=True)


REASONS = {  # Korean, for the panel and PREFLIGHT.txt
    "removed": "Figma에서 지워졌거나 찾을 수 없는 요소",
    "no_outline": "원본 벡터(아웃라인)를 받지 못한 요소",
    "svg_clip_box": "Figma 마스크·잘라내기 모양을 상자로 근사한 요소",
    "pdf_bitmap": "PDF 원본에서 만든 비트맵(근사치) 요소",
    "panel_removed": "구조가 바뀌어 없어진 패널",
    "scale_unverified": "실제 크기(mm)를 확인하지 못했습니다. 구조 확인에서 치수나 mm 비율을 지정하세요",
}


def _classify(t: fspec.Target, tree: dict, svgs: dict, panels: dict) -> tuple[str, str | None]:
    """("exact" | "approximate" | "missing", reason) of one target's plate geometry."""
    if t.kind == "sheet":
        return "exact", None
    if t.kind == "panel":
        return ("exact", None) if t.id in panels else ("missing", "panel_removed")
    asset = tree.get(t.id or "")
    if asset is None:
        return "missing", "removed"
    if t.id in svgs:
        return ("exact", None) if masks.svg_exact(svgs[t.id]) else ("approximate", "svg_clip_box")
    if not asset.get("exact"):
        return "approximate", "pdf_bitmap"
    return "missing", "no_outline"  # never guessed from the printed ink


def _context(pid: str, spec: Specification, fin: fspec.FinishingSpec):
    _, tree_list = fa.project_assets(pid, spec)
    tree = {a["id"]: a for a in tree_list}
    enabled = [a for a in fin.assignments if a.enabled]
    ids = [t.id for a in enabled for t in a.targets if t.kind == "asset" and t.id]
    svgs = fa.node_svgs(pid, [i for i in ids if tree.get(i, {}).get("exact")])
    return tree, enabled, svgs, {p.id: p for p in spec.panels}


def preflight(pid: str, spec: Specification, fin: fspec.FinishingSpec) -> dict:
    """Whether every target's plate geometry is the exact source geometry. Any approximate or
    missing target makes the plates a draft: a production export is refused (409), a draft
    export is marked as such in every file name, the PDFs' metadata and the manifest."""
    tree, enabled, svgs, panels = _context(pid, spec, fin)
    issues = []
    # The plates are written at real size: that size must come from a ruler, not a guess.
    figma_units = bool((repo.get("projects", pid) or {}).get("figma_json"))
    sc = spec.scale
    # A print-ready PDF's points are physical; Figma pixels need a ruler (dimension marks or
    # a user value), and a weak ruler reading is not enough either.
    guessed = sc.source == "pdf_units" and figma_units
    weak = sc.source == "dimension_marks" and sc.confidence < 0.9
    if guessed or weak:
        issues.append(
            {
                "assignment_id": "",
                "finish": "",
                "target": "scale",
                "name": "실제 크기",
                "status": "approximate",
                "reason": "scale_unverified",
                "message": REASONS["scale_unverified"],
            }
        )
    for a in enabled:
        for t in a.targets:
            status, reason = _classify(t, tree, svgs, panels)
            if status != "exact":
                name = (tree.get(t.id or "") or {}).get("name") or t.id or t.kind
                issues.append(
                    {
                        "assignment_id": a.id,
                        "finish": a.finish,
                        "target": t.id or t.kind,
                        "name": name,
                        "status": status,
                        "reason": reason,
                        "message": REASONS[reason or "removed"],
                    }
                )
    return {"exact": not issues, "issues": issues}


def self_check(pdf: bytes, spec: Specification, allow_images: bool) -> list[str]:
    """Automated preflight of one plate PDF: the source page size, no optional-content layers
    (nothing hidden that could print), art only in 100% K (no RGB paint), no embedded images
    unless the plate is an approximate draft. Returns the problems found (empty = passed)."""
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    out = []
    if len(doc) != 1:
        out.append(f"pages={len(doc)}")
    page = doc[0]
    k = physical_factor(spec)
    if (
        abs(page.rect.width - spec.page.width_pt * k) > 0.01
        or abs(page.rect.height - spec.page.height_pt * k) > 0.01
    ):
        out.append("page_size")
    if doc.get_ocgs():
        out.append("optional_content_layers")
    streams = b"".join(
        doc.xref_stream(x) or b""
        for x in range(1, doc.xref_length())
        if doc.xref_is_stream(x) and doc.xref_get_key(x, "Subtype")[1] in ("null", "/Form")
    )
    if re.search(rb"(?<![\d.])[\d.]+ [\d.]+ [\d.]+ (rg|RG)(?![A-Za-z])", streams):
        out.append("rgb_paint")
    if page.get_drawings() and b"0 0 0 1 k" not in streams:
        out.append("no_k_fill")
    if page.get_images() and not allow_images:
        out.append("embedded_images")
    return out


def build(pid: str, spec: Specification, fin: fspec.FinishingSpec, draft: bool = False) -> bytes:
    """The plates ZIP. Production (``draft=False``) requires exact geometry for every target
    and a clean ``self_check`` of every plate, else 409; ``draft=True`` always builds, marked
    as not for production everywhere."""
    pre = preflight(pid, spec, fin)
    if not draft and not pre["exact"]:
        raise ApiError(
            409,
            "PLATES_NOT_VERIFIED",
            "근사치이거나 빠진 모양이 있어 생산용 판 파일을 만들 수 없습니다.",
            hint="해당 요소를 Figma에서 단순한 벡터로 바꾸거나 후가공을 다시 지정하세요. "
            "확인용으로는 '검토용 초안'을 받을 수 있습니다.",
            details={"issues": pre["issues"]},
        )
    tree, enabled, svgs, panels = _context(pid, spec, fin)
    groups: dict[str, list[fspec.Assignment]] = {}
    for a in sorted(enabled, key=lambda a: a.order):
        groups.setdefault(a.finish, []).append(a)
    outline = board_outline(spec)
    prefix = "DRAFT_" if draft else ""

    out = io.BytesIO()
    manifest = {
        "schema": 3,
        "status": "DRAFT_NOT_FOR_PRODUCTION" if draft else "exact_geometry_needs_printer_preflight",
        "finishing_revision": fin.revision,
        "page_pt": [
            round(spec.page.width_pt * physical_factor(spec), 3),
            round(spec.page.height_pt * physical_factor(spec), 3),
        ],
        "source_page_units": [spec.page.width_pt, spec.page.height_pt],
        "physical_factor": round(physical_factor(spec), 6),
        "scale_source": spec.scale.source,
        "scale_confidence": spec.scale.confidence,
        "page_mm": [
            round(spec.page.width_pt * spec.scale.mm_per_pt, 3),
            round(spec.page.height_pt * spec.scale.mm_per_pt, 3),
        ],
        "mm_per_pt": spec.scale.mm_per_pt,
        "bleed_mm": BLEED_MM,
        "dieline": f"{prefix}dieline.pdf",
        "preflight_issues": pre["issues"],
        "plates": [],
    }
    failed: dict[str, list[str]] = {}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for fid, assignments in groups.items():
            f = catalog.finish(fid)
            doc = pymupdf.open()
            page = doc.new_page(width=spec.page.width_pt, height=spec.page.height_pt)
            approx: list[str] = []
            missing: list[str] = []
            targets = []
            for a in assignments:
                for t in a.targets:
                    targets.append({"kind": t.kind, "id": t.id})
                    status, reason = _classify(t, tree, svgs, panels)
                    if status == "missing":
                        missing.append(t.id or t.kind)
                    elif t.kind == "sheet":
                        page.draw_rect(page.rect, color=None, fill=BLACK)
                    elif t.kind == "panel":
                        page.draw_rect(pymupdf.Rect(*panels[t.id].bbox), color=None, fill=BLACK)
                    elif reason == "pdf_bitmap":
                        _bitmap(page, pid, spec, tree[t.id])
                        approx.append(t.id)
                    else:
                        asset = tree[t.id]
                        masks.place_svg(
                            page, black_svg(svgs[t.id]), asset["bbox"], asset.get("clip")
                        )
                        if status == "approximate":
                            approx.append(t.id)
            _clip_to(doc, page, outline)
            _to_k(doc)
            label = f"{f.label_en} ({fid}), finishing revision {fin.revision}"
            pdf = _to_physical(
                doc.tobytes(deflate=True),
                spec,
                {
                    "title": ("DRAFT - NOT FOR PRODUCTION - " if draft else "") + label,
                    "subject": "DRAFT: approximate or missing geometry, see PREFLIGHT.txt"
                    if draft
                    else "Finishing plate, 100% K, registered to the source page; "
                    "printer preflight required",
                    "creator": "Dieline Generator",
                },
            )
            problems = self_check(pdf, spec, allow_images=bool(approx))
            if problems:
                failed[fid] = problems
            name = f"{prefix}{fid.replace('.', '_')}.pdf"
            z.writestr(name, pdf)
            manifest["plates"].append(
                {
                    "file": name,
                    "finish": fid,
                    "label_ko": f.label_ko,
                    "label_en": f.label_en,
                    "targets": targets,
                    "params": [a.params for a in assignments],
                    "approximate_assets": approx,
                    "missing_targets": missing,
                    "self_check": problems or "passed",
                }
            )
        if failed and not draft:
            raise ApiError(
                409,
                "PLATES_SELF_CHECK_FAILED",
                "판 파일 자동 점검에 실패해 생산용으로 내보낼 수 없습니다.",
                details={"failed": failed},
            )
        z.writestr(f"{prefix}dieline.pdf", _to_physical(_dieline_pdf(spec), spec))
        z.writestr("finishing.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        z.writestr("README.txt", (DRAFT_NOTE if draft else "") + README)
        if draft:
            lines = [
                f"- [{i['status']}] {i['finish']} / {i['name']} ({i['target']}): {i['message']}"
                for i in pre["issues"]
            ]
            z.writestr("PREFLIGHT.txt", DRAFT_NOTE + "\n".join(lines) + "\n")
    return out.getvalue()


def _bitmap(page, pid: str, spec: Specification, asset: dict) -> None:
    """A PDF-only asset: its mask as a black image with alpha (approximate)."""
    raster, _ = frame(spec, APPROX_EDGE, FLAT_LOOK.lighting.margin)
    layers = pipeline.get_layers(pid, spec, APPROX_EDGE, FLAT_LOOK.lighting.margin)
    m = masks.asset_mask(
        pid, spec, asset, APPROX_EDGE, layers.silhouette, None, structure_key(spec), lambda: layers
    )
    ys, xs = np.nonzero(m > 0.02)
    if not ys.size:
        return
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    a = (np.clip(m[y0:y1, x0:x1], 0, 1) * 255).astype(np.uint8)
    img = Image.merge(
        "RGBA", [Image.new("L", (a.shape[1], a.shape[0]), 0)] * 3 + [Image.fromarray(a)]
    )
    buf = io.BytesIO()
    img.save(buf, "PNG")
    ox, oy = raster.origin
    s = raster.scale
    page.insert_image(
        pymupdf.Rect(ox + x0 / s, oy + y0 / s, ox + x1 / s, oy + y1 / s), stream=buf.getvalue()
    )


def plate_coverage(pdf: bytes, spec: Specification, long_edge: int) -> np.ndarray:
    """A plate rasterised on the flat render's frame at ``long_edge`` (HxW 0..1): the same
    pixel grid as the preview's masks, for comparing the two."""
    raster, crop = frame(spec, long_edge, FLAT_LOOK.lighting.margin)
    page = pymupdf.open(stream=pdf, filetype="pdf")[0]
    k = physical_factor(spec)  # the plate is at real size: back to the source's units
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(raster.scale / k, raster.scale / k),
        clip=pymupdf.Rect(*(v * k for v in crop)) & page.rect,
        alpha=True,
        annots=False,
    )
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., -1]
    dx = pix.x - round(raster.origin[0] * raster.scale)
    dy = pix.y - round(raster.origin[1] * raster.scale)
    return masks._place(a.astype(np.float32) / 255, raster.h, raster.w, dy, dx)


def compare(pid: str, spec: Specification, vid: str, fin: fspec.FinishingSpec) -> list[dict]:
    """Each plate of ``fin`` against the preview's masks of the same finish on version ``vid``
    (the same pixel grid): pixels where they disagree inside the board, away from the
    anti-aliased edges (``wrong_px``, must be 0), plate pixels farther out than the bleed
    (``beyond_bleed_px``, must be 0), and the overlap (``iou``) inside the board."""
    from app.finishing import compose

    c = compose.compose(pid, spec, vid, fin)
    h, w = c.image.shape[:2]
    prev: dict[str, np.ndarray] = {}
    if c.box is not None:
        y0, x0, y1, x1 = c.box
        for f, _, m in c.stack:
            full = prev.setdefault(f.id, np.zeros((h, w), np.float32))
            full[y0:y1, x0:x1] = np.maximum(full[y0:y1, x0:x1], m)
    exact = preflight(pid, spec, fin)["exact"]
    z = zipfile.ZipFile(io.BytesIO(build(pid, spec, fin, draft=not exact)))
    manifest = json.loads(z.read("finishing.json"))
    sil = masks.board(spec, max(h, w), structure_key(spec)) > 0.5
    raster, _ = frame(spec, max(h, w), FLAT_LOOK.lighting.margin)
    bleed_px = (BLEED_MM + OUTLINE_TOL_MM) / spec.scale.mm_per_pt * raster.scale
    beyond = ndimage.distance_transform_edt(~sil) > bleed_px + 1
    sil_edge = ndimage.binary_dilation(sil, iterations=2) & ~ndimage.binary_erosion(
        sil, iterations=2
    )
    out = []
    for p in manifest["plates"]:
        plate = plate_coverage(z.read(p["file"]), spec, max(h, w)) > 0.5
        a = prev.get(p["finish"], np.zeros((h, w), np.float32)) > 0.5
        edge = ndimage.binary_dilation(a, iterations=2) & ~ndimage.binary_erosion(a, iterations=2)
        edge |= sil_edge
        inside = sil & ~edge
        union = int(((a | plate) & inside).sum())
        out.append(
            {
                "finish": p["finish"],
                "file": p["file"],
                "preview_px": int(a.sum()),
                "plate_px": int(plate.sum()),
                "wrong_px": int(((a ^ plate) & inside).sum()),
                "beyond_bleed_px": int((plate & beyond).sum()),
                "iou": round(int(((a & plate) & inside).sum()) / union, 4) if union else 1.0,
                "px_per_mm": round(raster.scale / spec.scale.mm_per_pt, 3),
                "approximate_assets": p["approximate_assets"],
                "missing_targets": p["missing_targets"],
            }
        )
    return out


DRAFT_NOTE = """!!! 검토용 초안 (DRAFT) — 생산에 쓰지 마세요 / NOT FOR PRODUCTION !!!
아래 요소의 모양이 근사치이거나 빠져 있어, 이 판은 화면 미리보기·원본과 정확히 같다는 보장이
없습니다. 파일 이름과 PDF 정보에 DRAFT가 붙어 있습니다.

"""


README = """후가공 판 파일 (Dieline Generator)

- 후가공마다 PDF 한 장: 박·형압·부분 UV 등 해당 후가공이 들어갈 자리만 K 100%로 그렸습니다.
- 판과 dieline.pdf는 실제 크기(mm)로 저장됩니다(finishing.json의 page_mm). Figma처럼 픽셀 단위인
  원본은 physical_factor만큼 확대·축소되어 있으니, 원본 PDF와 겹칠 때는 같은 비율로 맞추세요.
  판끼리와 dieline.pdf는 그대로 겹칩니다.
- 판은 종이 모양(창·구멍은 뚫린 채)대로 잘려 있고, 칼선 밖으로 1mm 여유(bleed)가 있습니다.
- 칼선(실선)과 접는 선(점선)은 판에 넣지 않고 dieline.pdf에 따로 담았습니다(마젠타). 판 위에
  겹쳐서 위치만 확인하세요.
- finishing.json: 후가공 종류, 대상, 세부 값(깊이 mm 등), 근사치(approximate_assets)와
  빠진 대상(missing_targets).
- approximate_assets: PDF 원본에서 만든 비트맵이거나, Figma 마스크·잘라내기 모양을 상자로 근사한
  요소입니다. missing_targets: 원본 벡터를 찾지 못해 판에서 빠진 요소입니다. 둘 다 꼭 확인하세요.
- status가 exact_geometry_needs_printer_preflight면 모든 대상이 원본 벡터 그대로라는 뜻이지,
  생산 승인이 아닙니다. self_check는 쪽 크기·K 100%·레이어 없음을 자동 확인한 결과입니다.
- 이 파일은 화면 미리보기와 같은 모양을 담은 작업용 판입니다. 최소 선 굵기·칼선 거리·트래핑 같은
  제조 기준은 인쇄소마다 다르니, 앱의 '제조 점검'을 참고해 인쇄소와 확인하세요.
"""
