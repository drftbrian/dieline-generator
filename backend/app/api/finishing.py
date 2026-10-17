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
from app.finishing import catalog, compose
from app.finishing import spec as fspec
from app.render import shading
from app.render.layers import structure_key
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


def _version(pid: str, vid: str) -> dict:
    v = repo.get("versions", vid)
    if (
        v is None
        or v["project_id"] != pid
        or v["status"] != "done"
        or (v.get("kind") or "flat") != "flat"
        or ((v.get("settings_json") or {}).get("flat_mode") == "finished")
    ):
        raise ApiError(
            404, "VERSION_NOT_FOUND", "후가공 미리보기에 쓸 플랫 렌더를 찾을 수 없습니다."
        )
    return v


def overlay(pid: str, spec, vid: str, fin: fspec.FinishingSpec) -> tuple[bytes, dict]:
    """RGBA PNG of only the finished pixels, at the version image's own resolution and over
    its own pixels (so the canvas keeps the full-resolution render everywhere else), cropped to
    the changed area. Returns the PNG and where it sits (page pt and image pixels)."""
    c = compose.compose(pid, spec, vid, fin)
    h, w = c.image.shape[:2]
    ox, oy = c.origin
    buf = io.BytesIO()
    if c.box is None:
        Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(buf, "PNG")
        return buf.getvalue(), {"origin": (ox, oy), "size": (0.0, 0.0), "px": (0, 0, 0, 0, w, h)}
    y0, x0, y1, x1 = c.box
    rgba = np.dstack([shading.to8(c.finished), np.where(c.changed, 255, 0).astype(np.uint8)])
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", compress_level=1)
    s = c.scale
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
