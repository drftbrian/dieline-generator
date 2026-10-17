"""Finishing plates for the printer: one vector PDF per finish, in the source page's
coordinates (so it registers with the dieline and the print), with the art in 100% black and
the dieline on a non-printing optional-content layer; plus the specification as JSON.

Figma assets are the node's outlined SVG recoloured to black (vectors, exact). PDF-only assets
have no vectors: their mask is embedded as a 1200 dpi bitmap and listed as approximate. Sheet
and panel targets are the board outline and panel rectangles.
"""

from __future__ import annotations

import io
import json
import re
import zipfile

import numpy as np
import pymupdf
from PIL import Image

from app.finishing import assets as fa
from app.finishing import catalog, masks
from app.finishing import spec as fspec
from app.render.layers import _closed_polys, frame, structure_key
from app.services import pipeline
from app.spec.models import FLAT_LOOK, Specification

BLACK = (0, 0, 0)
DIELINE = (1, 0, 1)  # magenta, on a non-printing layer
APPROX_EDGE = 6000  # px, long edge of the raster used for PDF-only (approximate) assets

_COLOUR = re.compile(r'(fill|stroke|stop-color)\s*=\s*"(?!none)[^"]*"')
_STYLE = re.compile(r"(fill|stroke|stop-color)\s*:\s*(?!none)[^;\"]+")
_OPACITY = re.compile(r'(fill-opacity|stroke-opacity|opacity)\s*=\s*"[^"]*"')


def black_svg(svg: str) -> str:
    """The SVG with every paint set to 100% black and opacities removed (a plate is solid)."""
    svg = _COLOUR.sub(lambda m: f'{m.group(1)}="#000000"', svg)
    svg = _STYLE.sub(lambda m: f"{m.group(1)}:#000000", svg)
    return _OPACITY.sub("", svg)


def _dieline(doc, page, spec: Specification) -> None:
    ocg = doc.add_ocg("Dieline (do not print)", on=True)
    shape = page.new_shape()
    for pl in _closed_polys(spec, "cut"):
        shape.draw_polyline([pymupdf.Point(*p) for p in pl])
    shape.finish(color=DIELINE, width=0.25, closePath=False, oc=ocg)
    creases = _closed_polys(spec, "crease")
    if creases:
        for pl in creases:
            shape.draw_polyline([pymupdf.Point(*p) for p in pl])
        shape.finish(color=DIELINE, width=0.25, dashes="[3 2] 0", closePath=False, oc=ocg)
    shape.commit()


def _sheet(page, spec: Specification) -> None:
    shape = page.new_shape()
    for pl in _closed_polys(spec, "cut"):
        if len(pl) >= 3:
            shape.draw_polyline([pymupdf.Point(*p) for p in pl])
    shape.finish(fill=BLACK, color=None, even_odd=True, closePath=True)
    shape.commit()


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

    out = io.BytesIO()
    manifest = {
        "schema": 1,
        "finishing_revision": fin.revision,
        "page_pt": [spec.page.width_pt, spec.page.height_pt],
        "mm_per_pt": spec.scale.mm_per_pt,
        "plates": [],
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for fid, assignments in groups.items():
            f = catalog.finish(fid)
            doc = pymupdf.open()
            page = doc.new_page(width=spec.page.width_pt, height=spec.page.height_pt)
            approx: list[str] = []
            targets = []
            for a in assignments:
                for t in a.targets:
                    targets.append({"kind": t.kind, "id": t.id})
                    if t.kind == "sheet":
                        _sheet(page, spec)
                    elif t.kind == "panel" and t.id in panels:
                        page.draw_rect(pymupdf.Rect(*panels[t.id].bbox), color=None, fill=BLACK)
                    elif t.kind == "asset" and t.id in tree:
                        asset = tree[t.id]
                        if t.id in svgs:
                            masks.place_svg(
                                page, black_svg(svgs[t.id]), asset["bbox"], asset.get("clip")
                            )
                        else:
                            _bitmap(page, pid, spec, asset)
                            approx.append(t.id)
            _dieline(doc, page, spec)
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
                }
            )
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


README = """후가공 판 파일 (Dieline Generator)

- 후가공마다 PDF 한 장: 박·형압·부분 UV 등 해당 후가공이 들어갈 자리만 검정 100%로 그렸습니다.
- 좌표는 원본 전개도 페이지와 같아서 인쇄 파일·칼선과 그대로 겹칩니다.
- 칼선(실선)과 접는 선(점선)은 'Dieline (do not print)' 레이어에 마젠타로 들어 있습니다. 출력하지 마세요.
- finishing.json: 후가공 종류, 대상, 세부 값(깊이 mm 등).
- approximate_assets에 적힌 요소는 PDF 원본에서 만든 비트맵(1200dpi 상당)이라 근사치입니다.
- 최소 선 굵기·칼선 거리 같은 기준은 인쇄소마다 다릅니다. 앱의 '제조 점검'을 참고해 인쇄소와 확인하세요.
"""
