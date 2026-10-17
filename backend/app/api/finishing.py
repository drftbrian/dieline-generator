"""Finishing studio: the catalogue, the project's finishing specification (versioned saves with
conflict detection), and a preview of a flat version with the finishes applied."""

from __future__ import annotations

import io
import threading
from collections import OrderedDict

import numpy as np
from fastapi import APIRouter, Response
from PIL import Image
from pydantic import BaseModel

from app.api import assets as assets_api
from app.errors import ApiError
from app.finishing import assets as fa
from app.finishing import catalog, masks
from app.finishing import spec as fspec
from app.render import shading
from app.render.finishing import material
from app.render.layers import frame, structure_key
from app.services import pipeline
from app.spec.models import FLAT_LOOK
from app.storage import repo

router = APIRouter(tags=["finishing"])


# ---- catalogue -----------------------------------------------------------------------------


class ParamOut(BaseModel):
    id: str
    label_ko: str
    label_en: str
    min: float
    max: float
    default: float
    unit: str
    note: str


class FinishOut(BaseModel):
    id: str
    category: str
    label_ko: str
    label_en: str
    model: str
    scope: str  # selective | surface | both
    color: str | None
    available: bool
    note: str
    params: list[ParamOut]


class CategoryOut(BaseModel):
    id: str
    label_ko: str
    label_en: str


class CatalogOut(BaseModel):
    categories: list[CategoryOut]
    finishes: list[FinishOut]


@router.get("/finishing/catalog", response_model=CatalogOut)
def get_catalog() -> CatalogOut:
    return CatalogOut(
        categories=[
            CategoryOut(id=k, label_ko=v[0], label_en=v[1]) for k, v in catalog.CATEGORIES.items()
        ],
        finishes=[
            FinishOut(
                id=f.id,
                category=f.category,
                label_ko=f.label_ko,
                label_en=f.label_en,
                model=f.model,
                scope=f.scope,
                color=f.color,
                available=f.available,
                note=f.note,
                params=[ParamOut(**p.__dict__) for p in f.params],
            )
            for f in catalog.FINISHES
        ],
    )


# ---- specification -------------------------------------------------------------------------


class FinishingSaveIn(BaseModel):
    base_revision: int  # the revision this edit started from (0 = none yet)
    assignments: list[fspec.Assignment]


@router.get("/projects/{pid}/finishing", response_model=fspec.FinishingSpec)
def get_finishing(pid: str) -> fspec.FinishingSpec:
    repo.project_or_404(pid)
    return fspec.load(pid)


@router.get("/projects/{pid}/finishing/revisions/{revision}", response_model=fspec.FinishingSpec)
def get_finishing_revision(pid: str, revision: int) -> fspec.FinishingSpec:
    repo.project_or_404(pid)
    return fspec.load_revision(pid, revision)


@router.put("/projects/{pid}/finishing", response_model=fspec.FinishingSpec)
def save_finishing(pid: str, body: FinishingSaveIn) -> fspec.FinishingSpec:
    """Save the whole specification as a new revision (the client keeps undo/redo history)."""
    spec = assets_api._ready(pid)
    _, tree = fa.project_assets(pid, spec)
    checked = fspec.validate(body.assignments, tree, {p.id for p in spec.panels})
    return fspec.save(pid, body.base_revision, checked)


# ---- preview -------------------------------------------------------------------------------

_cache: OrderedDict[tuple, tuple[bytes, dict]] = OrderedDict()
_lock = threading.Lock()
CROP_PAD_MM = 2.5  # around the finish regions: room for relief shoulders and blurs


def target_mask(
    pid, spec, t: fspec.Target, tree: dict, sil: np.ndarray, svgs: dict, long_edge: int, scale_of
) -> np.ndarray | None:
    """The target's mask on the version's frame (``sil`` = the board at that resolution)."""
    if t.kind == "sheet":
        return (sil > 0.001).astype(np.float32) * np.clip(sil, 0, 1)
    if t.kind == "panel":
        p = next((p for p in spec.panels if p.id == t.id), None)
        if p is None:
            return None
        (ox, oy), scale = scale_of
        x0, y0, x1, y1 = (
            int(round((v - o) * scale)) for v, o in zip(p.bbox, (ox, oy, ox, oy), strict=True)
        )
        m = np.zeros_like(sil)
        m[max(0, y0) : max(0, y1), max(0, x0) : max(0, x1)] = 1
        return m * np.clip(sil, 0, 1)
    asset = tree.get(t.id or "")
    if asset is None:
        return None
    svg = None
    if asset.get("exact"):
        svg = svgs.get(asset["id"])
        if svg is None:
            return None  # never guessed from the printed ink for Figma assets
    return masks.asset_mask(
        pid,
        spec,
        asset,
        long_edge,
        sil,
        svg,
        structure_key(spec),
        lambda: pipeline.get_layers(pid, spec, long_edge, FLAT_LOOK.lighting.margin),
    )


def _version(pid: str, vid: str) -> dict:
    v = repo.get("versions", vid)
    if (
        v is None
        or v["project_id"] != pid
        or v["status"] != "done"
        or (v.get("kind") or "flat") != "flat"
    ):
        raise ApiError(
            404, "VERSION_NOT_FOUND", "후가공 미리보기에 쓸 플랫 렌더를 찾을 수 없습니다."
        )
    return v


def overlay(pid: str, spec, vid: str, fin: fspec.FinishingSpec) -> tuple[bytes, dict]:
    """RGBA PNG of only the finished pixels, at the version image's own resolution and over
    its own pixels (so the canvas keeps the full-resolution render everywhere else), cropped to
    the changed area. Returns the PNG and the crop's frame in page pt."""
    path = repo.project_dir(pid) / "versions" / f"{vid}.png"
    if not path.exists():
        raise ApiError(
            404, "VERSION_NOT_FOUND", "후가공 미리보기에 쓸 플랫 렌더를 찾을 수 없습니다."
        )
    img = np.asarray(Image.open(path).convert("RGB"))
    h, w = img.shape[:2]
    long_edge = max(h, w)
    raster, crop = frame(spec, long_edge, FLAT_LOOK.lighting.margin)
    if (raster.h, raster.w) != (h, w):
        raise ApiError(
            409,
            "VERSION_STALE",
            "이 플랫 렌더는 지금 구조와 맞지 않습니다.",
            hint="플랫 렌더를 다시 생성한 뒤 후가공을 확인해주세요.",
        )
    sil = masks.board(spec, long_edge, structure_key(spec))
    _, tree_list = fa.project_assets(pid, spec)
    tree = {a["id"]: a for a in tree_list}
    asset_ids = [
        t.id for a in fin.assignments if a.enabled for t in a.targets if t.kind == "asset" and t.id
    ]
    svgs = fa.node_svgs(pid, [i for i in asset_ids if tree.get(i, {}).get("exact")])
    stack = []
    for a in sorted(fin.assignments, key=lambda a: a.order):
        if not a.enabled:
            continue
        ms = [
            target_mask(pid, spec, t, tree, sil, svgs, long_edge, (raster.origin, raster.scale))
            for t in a.targets
        ]
        ms = [m for m in ms if m is not None]
        if ms:
            stack.append((catalog.finish(a.finish), a.params, np.maximum.reduce(ms)))
    ox, oy = raster.origin
    union = np.zeros((h, w), bool)
    for _, _, m in stack:
        union |= m > 0
    ys, xs = np.nonzero(union)
    if not ys.size:
        buf = io.BytesIO()
        Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(buf, "PNG")
        return buf.getvalue(), {"origin": (ox, oy), "size": (0.0, 0.0), "px": (0, 0, 0, 0, w, h)}
    # Work on the finishes' bounding box only (plus room for the relief shoulder).
    px_per_mm = raster.scale / spec.scale.mm_per_pt
    pad = int(CROP_PAD_MM * px_per_mm) + 8
    y0, x0 = max(0, int(ys.min()) - pad), max(0, int(xs.min()) - pad)
    y1, x1 = min(h, int(ys.max()) + 1 + pad), min(w, int(xs.max()) + 1 + pad)
    base = img[y0:y1, x0:x1].astype(np.float32) / 255
    scene = material.Scene(px_per_mm=px_per_mm, offset=(y0, x0), full=(h, w))
    out, changed = material.render(base, [(f, p, m[y0:y1, x0:x1]) for f, p, m in stack], scene)
    rgba = np.dstack([shading.to8(out), np.where(changed, 255, 0).astype(np.uint8)])
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", compress_level=1)
    s = raster.scale
    return buf.getvalue(), {
        "origin": (ox + x0 / s, oy + y0 / s),
        "size": ((x1 - x0) / s, (y1 - y0) / s),
        "px": (x0, y0, x1 - x0, y1 - y0, w, h),
    }


@router.get("/projects/{pid}/finishing/preview")
def finishing_preview(pid: str, version_id: str, revision: int | None = None):
    """Transparent PNG of the finished pixels of a flat version (material renderers; holographic,
    pigment foil, uncoated and dome are still placeholders), at the version's full resolution. Lay it over the version image at the frame the
    headers give (page pt); everywhere it is transparent the version image is unchanged."""
    spec = assets_api._ready(pid)
    _version(pid, version_id)
    fin = fspec.load(pid) if revision is None else fspec.load_revision(pid, revision)
    key = (pid, version_id, fin.revision, structure_key(spec))
    with _lock:
        hit = _cache.get(key)
    if hit is None:
        hit = overlay(pid, spec, version_id, fin)
        with _lock:
            _cache[key] = hit
            while len(_cache) > 16:
                _cache.popitem(last=False)
    png, fr = hit
    headers = {
        "X-Frame-Origin": f"{fr['origin'][0]},{fr['origin'][1]}",
        "X-Frame-Size": f"{fr['size'][0]},{fr['size'][1]}",
        # x, y, w, h of the overlay inside the version image, and that image's w, h (pixels).
        "X-Overlay-Rect": ",".join(str(v) for v in fr["px"]),
        "Cache-Control": "no-store",
    }
    return Response(png, media_type="image/png", headers=headers)
