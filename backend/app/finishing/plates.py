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

from app.finishing import assets as fa
from app.finishing import catalog, masks
from app.finishing import spec as fspec
from app.render.layers import _closed_polys, board, frame, package_bbox, structure_key
from app.services import pipeline
from app.spec.models import FLAT_LOOK, Specification

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


def build(pid: str, spec: Specification, fin: fspec.FinishingSpec) -> bytes:
    _, tree_list = fa.project_assets(pid, spec)
    tree = {a["id"]: a for a in tree_list}
    enabled = [a for a in fin.assignments if a.enabled]
    ids = [t.id for a in enabled for t in a.targets if t.kind == "asset" and t.id]
    svgs = fa.node_svgs(pid, [i for i in ids if tree.get(i, {}).get("exact")])
    panels = {p.id: p for p in spec.panels}
    groups: dict[str, list[fspec.Assignment]] = {}
    for a in sorted(enabled, key=lambda a: a.order):
        groups.setdefault(a.finish, []).append(a)
    outline = board_outline(spec)

    out = io.BytesIO()
    manifest = {
        "schema": 2,
        "finishing_revision": fin.revision,
        "page_pt": [spec.page.width_pt, spec.page.height_pt],
        "mm_per_pt": spec.scale.mm_per_pt,
        "bleed_mm": BLEED_MM,
        "dieline": "dieline.pdf",
        "plates": [],
    }
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
                    if t.kind == "sheet":
                        page.draw_rect(page.rect, color=None, fill=BLACK)
                    elif t.kind == "panel" and t.id in panels:
                        page.draw_rect(pymupdf.Rect(*panels[t.id].bbox), color=None, fill=BLACK)
                    elif t.kind == "asset" and t.id in tree:
                        asset = tree[t.id]
                        if t.id in svgs:
                            masks.place_svg(
                                page, black_svg(svgs[t.id]), asset["bbox"], asset.get("clip")
                            )
                            if not masks.svg_exact(svgs[t.id]):
                                approx.append(t.id)
                        elif not asset.get("exact"):
                            _bitmap(page, pid, spec, asset)
                            approx.append(t.id)
                        else:
                            missing.append(t.id)  # no outline: never guessed from the ink
                    else:
                        missing.append(t.id or t.kind)
            _clip_to(doc, page, outline)
            _to_k(doc)
            name = f"{fid.replace('.', '_')}.pdf"
            z.writestr(name, doc.tobytes(deflate=True))
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
                }
            )
        z.writestr("dieline.pdf", _dieline_pdf(spec))
        z.writestr("finishing.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        z.writestr("README.txt", README)
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
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(raster.scale, raster.scale),
        clip=pymupdf.Rect(*crop) & page.rect,
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
    z = zipfile.ZipFile(io.BytesIO(build(pid, spec, fin)))
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


README = """후가공 판 파일 (Dieline Generator)

- 후가공마다 PDF 한 장: 박·형압·부분 UV 등 해당 후가공이 들어갈 자리만 K 100%로 그렸습니다.
- 좌표는 원본 전개도 페이지와 같아서 인쇄 파일·칼선과 그대로 겹칩니다.
- 판은 종이 모양(창·구멍은 뚫린 채)대로 잘려 있고, 칼선 밖으로 1mm 여유(bleed)가 있습니다.
- 칼선(실선)과 접는 선(점선)은 판에 넣지 않고 dieline.pdf에 따로 담았습니다(마젠타). 판 위에
  겹쳐서 위치만 확인하세요.
- finishing.json: 후가공 종류, 대상, 세부 값(깊이 mm 등), 근사치(approximate_assets)와
  빠진 대상(missing_targets).
- approximate_assets: PDF 원본에서 만든 비트맵이거나, Figma 마스크·잘라내기 모양을 상자로 근사한
  요소입니다. missing_targets: 원본 벡터를 찾지 못해 판에서 빠진 요소입니다. 둘 다 꼭 확인하세요.
- 이 파일은 화면 미리보기와 같은 모양을 담은 작업용 판입니다. 최소 선 굵기·칼선 거리·트래핑 같은
  제조 기준은 인쇄소마다 다르니, 앱의 '제조 점검'을 참고해 인쇄소와 확인하세요.
"""
