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
from app.finishing import catalog
from app.finishing import spec as fspec
from app.render import shading
from app.render.finishing import placeholder
from app.services import pipeline
from app.spec.models import FLAT_LOOK, flat_look
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

_cache: OrderedDict[tuple, bytes] = OrderedDict()
_lock = threading.Lock()


def target_mask(pid, spec, t: fspec.Target, tree: dict, layers, svgs: dict) -> np.ndarray | None:
    sil = layers.silhouette
    if t.kind == "sheet":
        return (sil > 0.001).astype(np.float32) * np.clip(sil, 0, 1)
    if t.kind == "panel":
        p = next((p for p in spec.panels if p.id == t.id), None)
        if p is None:
            return None
        ox, oy = layers.origin
        x0, y0, x1, y1 = (
            int(round((v - o) * layers.scale))
            for v, o in zip(p.bbox, (ox, oy, ox, oy), strict=True)
        )
        m = np.zeros_like(sil)
        m[max(0, y0) : max(0, y1), max(0, x0) : max(0, x1)] = 1
        return m * np.clip(sil, 0, 1)
    asset = tree.get(t.id or "")
    if asset is None:
        return None
    return assets_api._mask(pid, spec, asset, svgs)


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


@router.get("/projects/{pid}/finishing/preview")
def finishing_preview(pid: str, version_id: str, revision: int | None = None):
    """The flat version's look at preview resolution with the finishing revision applied
    (placeholder effects in this milestone). Headers give the frame in page pt."""
    spec = assets_api._ready(pid)
    v = _version(pid, version_id)
    fin = fspec.load(pid) if revision is None else fspec.load_revision(pid, revision)
    settings = v.get("settings_json") or {}
    look = flat_look(settings.get("flat_look") or "v3", settings.get("fold_preset") or "medium")
    key = (pid, version_id, fin.revision, look.style, look.fold_preset)
    fr = assets_api._frame(spec)
    headers = {
        "X-Frame-Origin": f"{fr.origin[0]},{fr.origin[1]}",
        "X-Frame-Size": f"{fr.size[0]},{fr.size[1]}",
        "Cache-Control": "no-store",
    }
    with _lock:
        if key in _cache:
            return Response(_cache[key], media_type="image/png", headers=headers)
    layers = pipeline.get_layers(pid, spec, assets_api.PREVIEW_EDGE, FLAT_LOOK.lighting.margin)
    base = shading.render_parts(layers, look).rgb
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
        ms = [target_mask(pid, spec, t, tree, layers, svgs) for t in a.targets]
        ms = [m for m in ms if m is not None]
        if ms:
            stack.append((catalog.finish(a.finish), a.params, np.maximum.reduce(ms)))
    out = placeholder.render(base, stack)
    buf = io.BytesIO()
    Image.fromarray(shading.to8(out)).save(buf, "PNG")
    with _lock:
        _cache[key] = buf.getvalue()
        while len(_cache) > 32:
            _cache.popitem(last=False)
    return Response(buf.getvalue(), media_type="image/png", headers=headers)
