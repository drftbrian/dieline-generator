"""Manufacturing checks for a finishing specification.

Limits are the research defaults in ``docs/research/postpress/manufacturing-constraints.md``
(each sourced there); a printer's own limits may differ, so these are advice, never a block.
Geometry is measured on the same source masks the renderer uses, at >= 10 px/mm.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from app.finishing import assets as fa
from app.finishing import catalog, compose, masks
from app.finishing import spec as fspec
from app.render.layers import _closed_polys, frame, package_bbox, structure_key
from app.spec.models import FLAT_LOOK, Specification

PX_PER_MM = 10.0
PT_PER_MM = 72 / 25.4
GLUE_WORDS = ("접착", "풀칠", "풀 ", "glue")

# Per model: (min line mm warn, min line mm error, min gap mm, min text pt).
LIMITS = {
    "metal": (0.3, 0.2, 0.3, 8.0),
    "pigment": (0.3, 0.2, 0.3, 8.0),
    "holographic": (0.3, 0.2, 0.3, 8.0),
    "relief": (0.5, 0.3, 1.0, 10.0),
    "clearcoat": (0.3, 0.2, 1.0, 8.0),  # selective UV / varnish (reverse lines 1 mm)
    "dome": (5.0, 3.0, 6.0, None),
}
EDGE_MM = 3.0  # from cut lines and creases
MAX_SOLID_MM = 30.0  # foil solids wider than this may show grain / pinholes
MIN_DOME_MM = 10.0
MAX_UV_COVER = 0.30


def _w(level, code, message, hint=None, a=None, measured=None, limit=None) -> dict:
    return {
        "assignment_id": a.id if a else None,
        "finish": a.finish if a else None,
        "level": level,
        "code": code,
        "message": message,
        "hint": hint,
        "measured": None if measured is None else round(float(measured), 2),
        "limit": limit,
    }


def _ridge_widths(m: np.ndarray, ppm: float) -> np.ndarray:
    """Local stroke widths (mm) along the medial ridge of a binary shape."""
    if not m.any():
        return np.zeros(0)
    d = ndimage.distance_transform_edt(m)
    ridge = (d >= ndimage.maximum_filter(d, 3)) & m & (d > 0.5)
    return 2 * d[ridge] / ppm


def _gaps(m: np.ndarray, ppm: float, min_gap_mm: float) -> list[float]:
    """Widths (mm) of narrow spaces between parts of a shape: what closing the shape by
    ``min_gap_mm`` fills in, kept only where it forms a strip at least 1 mm long (a concave
    corner also fills a little, but only as a tiny wedge)."""
    r = max(1, int(round(min_gap_mm / 2 * ppm)))
    disk = ndimage.iterate_structure(ndimage.generate_binary_structure(2, 1), r)
    filled = ndimage.binary_closing(m, structure=disk) & ~m
    if not filled.any():
        return []
    labels, n = ndimage.label(filled)
    d = ndimage.distance_transform_edt(~m)
    min_area = max(min_gap_mm, 0.3) * 1.0 * ppm * ppm
    out = []
    for i, sl in enumerate(ndimage.find_objects(labels), start=1):
        comp = labels[sl] == i
        if comp.sum() >= min_area:
            out.append(2 * float(np.median(d[sl][comp])) / ppm + 1 / ppm)
    return out


def check(pid: str, spec: Specification, fin: fspec.FinishingSpec) -> list[dict]:
    enabled = [a for a in fin.assignments if a.enabled]
    if not enabled:
        return []
    x0, y0, x1, y1 = package_bbox(spec)
    long_mm = max(x1 - x0, y1 - y0) * spec.scale.mm_per_pt * 1.2
    edge = int(min(6000, max(2048, math.ceil(PX_PER_MM * long_mm))))
    raster, _ = frame(spec, edge, FLAT_LOOK.lighting.margin)
    ppm = raster.scale / spec.scale.mm_per_pt
    skey = structure_key(spec)
    sil = masks.board(spec, edge, skey)
    board = sil > 0.5
    cut_edge = board ^ ndimage.binary_erosion(board)
    creases = _closed_polys(spec, "crease")
    crease = raster.lines(creases, width_px=1.0) & board if creases else np.zeros_like(board)
    dist_cut = ndimage.distance_transform_edt(~cut_edge) / ppm
    dist_crease = ndimage.distance_transform_edt(~crease) / ppm if crease.any() else None
    glue = np.zeros_like(board)
    for p in spec.panels:
        if any(w in f"{p.name} " for w in GLUE_WORDS):
            gx0, gy0, gx1, gy1 = (
                int(round((v - o) * raster.scale))
                for v, o in zip(p.bbox, (*raster.origin, *raster.origin), strict=True)
            )
            glue[max(0, gy0) : max(0, gy1), max(0, gx0) : max(0, gx1)] = True
    glue &= board

    _, tree_list = fa.project_assets(pid, spec)
    tree = {a["id"]: a for a in tree_list}
    ids = [t.id for a in enabled for t in a.targets if t.kind == "asset" and t.id]
    svgs = fa.node_svgs(pid, [i for i in ids if tree.get(i, {}).get("exact")])

    out: list[dict] = []
    shapes: dict[str, np.ndarray] = {}
    for a in enabled:
        f = catalog.finish(a.finish)
        ms = [
            compose.target_mask(pid, spec, t, tree, sil, svgs, edge, (raster.origin, raster.scale))
            for t in a.targets
        ]
        ms = [m for m in ms if m is not None]
        if not ms:
            continue
        m = np.maximum.reduce(ms) > 0.5
        shapes[a.id] = m
        if f.scope == "surface" or all(t.kind != "asset" for t in a.targets):
            if glue.any() and (m & glue).any():
                level = (
                    "error" if f.model == "clearcoat" and "lamination" not in f.id else "warning"
                )
                out.append(
                    _w(
                        level,
                        "GLUE_FLAP_COATED",
                        "접착 날개에 코팅이 덮입니다. 코팅된 면은 풀이 잘 붙지 않아요.",
                        "인쇄소에 접착 날개는 코팅을 빼달라고(녹아웃) 요청하세요.",
                        a,
                    )
                )
            continue
        lim = LIMITS.get(f.model)
        if lim is None:
            continue
        warn_w, err_w, min_gap, min_pt = lim
        widths = _ridge_widths(m, ppm)
        if widths.size:
            thin = float(np.percentile(widths, 10))  # stroke ends taper: not the width
            if thin < err_w:
                out.append(
                    _w(
                        "error",
                        "LINE_TOO_THIN",
                        f"가장 가는 선이 약 {thin:.2f} mm라 {f.label_ko}이(가) 끊기거나 빠질 수 있어요.",
                        f"선 굵기를 {warn_w} mm 이상으로 두껍게 해주세요.",
                        a,
                        thin,
                        warn_w,
                    )
                )
            elif thin < warn_w:
                out.append(
                    _w(
                        "warning",
                        "LINE_THIN",
                        f"가장 가는 선이 약 {thin:.2f} mm로 권장({warn_w} mm)보다 가늘어요.",
                        None,
                        a,
                        thin,
                        warn_w,
                    )
                )
        gaps = _gaps(m, ppm, min_gap)
        if gaps:
            narrow = min(gaps)
            if narrow < min_gap:
                out.append(
                    _w(
                        "warning",
                        "GAP_NARROW",
                        f"요소 사이·글자 속 빈 공간이 약 {narrow:.2f} mm라 메워질(뭉칠) 수 있어요.",
                        f"간격을 {min_gap} mm 이상으로 벌려주세요.",
                        a,
                        narrow,
                        min_gap,
                    )
                )
        if min_pt:
            sizes = [
                (tree[t.id].get("size") or 0) * spec.scale.mm_per_pt * PT_PER_MM
                for t in a.targets
                if t.kind == "asset" and tree.get(t.id, {}).get("kind") == "text"
            ]
            small = [s for s in sizes if 0 < s < min_pt]
            if small:
                out.append(
                    _w(
                        "warning",
                        "TEXT_SMALL",
                        f"글자 크기가 약 {min(small):.1f} pt로 {f.label_ko}에는 작아요.",
                        f"{min_pt:g} pt 이상을 권장해요.",
                        a,
                        min(small),
                        min_pt,
                    )
                )
        near_cut = float(dist_cut[m].min()) if m.any() else 99
        if near_cut < EDGE_MM:
            out.append(
                _w(
                    "warning",
                    "NEAR_CUT",
                    f"칼선에서 {near_cut:.1f} mm 떨어져 있어요. 재단 오차로 잘리거나 어긋날 수 있어요.",
                    f"칼선에서 {EDGE_MM:g} mm 이상 안쪽에 두세요.",
                    a,
                    near_cut,
                    EDGE_MM,
                )
            )
        if dist_crease is not None and m.any():
            crosses = bool((m & crease).any())
            near = float(dist_crease[m].min())
            if crosses and f.model in ("relief", "clearcoat", "metal", "holographic", "pigment"):
                out.append(
                    _w(
                        "error" if f.model in ("relief", "clearcoat") else "warning",
                        "CROSSES_FOLD",
                        f"{f.label_ko}이(가) 접는 선을 가로질러요. 접을 때 갈라지거나 터질 수 있어요.",
                        "접는 선을 피하도록 위치를 옮겨주세요.",
                        a,
                    )
                )
            elif near < EDGE_MM:
                out.append(
                    _w(
                        "info",
                        "NEAR_FOLD",
                        f"접는 선에서 {near:.1f} mm 떨어져 있어요.",
                        f"{EDGE_MM:g} mm 이상 떨어뜨리면 안전해요.",
                        a,
                        near,
                        EDGE_MM,
                    )
                )
        if glue.any() and (m & glue).any():
            out.append(
                _w(
                    "error",
                    "ON_GLUE_FLAP",
                    f"{f.label_ko}이(가) 접착 날개 위에 있어요. 풀이 붙지 않아요.",
                    "접착 날개 밖으로 옮겨주세요.",
                    a,
                )
            )
        inscribed = 2 * float(ndimage.distance_transform_edt(m).max()) / ppm
        if f.model in ("metal", "holographic", "pigment") and inscribed > MAX_SOLID_MM:
            out.append(
                _w(
                    "info",
                    "LARGE_SOLID",
                    f"넓은 면({inscribed:.0f} mm)의 박은 기포·얼룩이 생기기 쉬워요.",
                    "인쇄소와 2회 압착 여부를 상의하세요.",
                    a,
                    inscribed,
                    MAX_SOLID_MM,
                )
            )
        if f.model == "dome" and inscribed < MIN_DOME_MM:
            out.append(
                _w(
                    "warning",
                    "DOME_SMALL",
                    f"에폭시가 올라갈 부분이 {inscribed:.1f} mm로 작아 볼록하게 서지 않아요.",
                    f"{MIN_DOME_MM:g} mm 이상의 덩어리 모양에 쓰세요.",
                    a,
                    inscribed,
                    MIN_DOME_MM,
                )
            )

    out += _combinations(enabled, shapes, board)
    return out


def _combinations(enabled, shapes, board) -> list[dict]:
    out = []
    by = {a.id: catalog.finish(a.finish) for a in enabled}
    # Finishes applied to the sheet or panels (the base the selective ones sit on).
    surface = {a.finish for a in enabled if any(t.kind != "asset" for t in a.targets)}
    gloss_base = {"surface.gloss_lamination", "coating.flood_uv", "coating.varnish_gloss"}
    for a in enabled:
        f = by[a.id]
        if f.id in ("coating.spot_uv", "coating.raised_uv"):
            if "surface.uncoated" in surface:
                out.append(
                    _w(
                        "error",
                        "UV_ON_UNCOATED",
                        "무코팅 종이 위의 부분 UV는 번져요.",
                        "무광 라미네이팅 위에 부분 UV를 올리세요.",
                        a,
                    )
                )
            elif surface & gloss_base:
                out.append(
                    _w(
                        "warning",
                        "UV_ON_GLOSS",
                        "유광 코팅 위의 부분 UV는 차이가 거의 보이지 않아요.",
                        "바탕을 무광 라미네이팅으로 바꾸면 부분 UV가 살아나요.",
                        a,
                    )
                )
            m = shapes.get(a.id)
            if m is not None and board.any() and m.sum() / board.sum() > MAX_UV_COVER:
                out.append(
                    _w(
                        "warning",
                        "UV_COVERAGE",
                        f"부분 UV가 면적의 {m.sum() / board.sum():.0%}를 덮어요 (권장 30% 이하).",
                        None,
                        a,
                        m.sum() / board.sum() * 100,
                        MAX_UV_COVER * 100,
                    )
                )
            for b in enabled:
                if by[b.id].model in ("metal", "holographic") and b.id in shapes and a.id in shapes:
                    if (shapes[a.id] & shapes[b.id]).any():
                        out.append(
                            _w(
                                "warning",
                                "UV_OVER_FOIL",
                                f"부분 UV가 {by[b.id].label_ko}과 겹쳐요. 정합이 어려워 인쇄소 확인이 필요해요.",
                                None,
                                a,
                            )
                        )
        if (
            f.model == "relief"
            and float(a.params.get("depth_mm", 0)) > 0.4
            and surface
            & {
                "surface.gloss_lamination",
                "surface.matte_lamination",
                "surface.soft_touch",
            }
        ):
            out.append(
                _w(
                    "warning",
                    "DEEP_RELIEF_LAMINATED",
                    "라미네이팅 위의 깊은 형압(0.4 mm 초과)은 어깨가 하얗게 터질 수 있어요.",
                    "깊이를 0.4 mm 이하로 줄이세요.",
                    a,
                    float(a.params.get("depth_mm", 0)),
                    0.4,
                )
            )
        if f.model in ("metal", "holographic", "pigment") and surface & {
            "surface.gloss_lamination",
            "surface.matte_lamination",
            "surface.soft_touch",
        }:
            out.append(
                _w(
                    "info",
                    "FOIL_ON_LAMINATE",
                    "라미네이팅 위에 박을 찍으려면 라미네이팅용 박이 필요해요.",
                    "인쇄소에 라미 위 박 가능 여부를 확인하세요.",
                    a,
                )
            )
    return out
