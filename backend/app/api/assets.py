"""Selectable design assets for finishing: the asset list, per-asset mask/outline images aligned
with the flat render's frame, and point hit-testing on exact masks."""

from __future__ import annotations

import io

import numpy as np
from fastapi import APIRouter, BackgroundTasks, Response
from PIL import Image
from pydantic import BaseModel

from app.errors import ApiError
from app.finishing import assets as fa
from app.finishing import masks
from app.render.layers import frame, structure_key
from app.services import pipeline, specs
from app.spec.models import FLAT_LOOK
from app.storage import repo

router = APIRouter(tags=["assets"])

PREVIEW_EDGE = 1400  # masks for selection display; the frame below maps them onto the canvas


class FrameOut(BaseModel):
    origin: list[float]  # page pt at the mask image's top-left
    size: list[float]  # page pt covered by the mask image
    width: int  # mask image pixels
    height: int


class AssetOut(BaseModel):
    id: str  # Figma node id, or "pdf:<object>" for PDF-only projects
    name: str
    type: str
    kind: str  # text | vector | group | image
    parent: str | None
    children: list[str]
    depth: int
    bbox: list[float]  # page pt
    panel: str | None
    selectable: bool
    technical: bool
    exact: bool  # mask from source vectors (False: from printed ink, approximate)
    text: str | None = None
    color: str | None = None


class AssetsOut(BaseModel):
    source: str  # "figma" | "pdf"
    frame: FrameOut
    assets: list[AssetOut]


class HitIn(BaseModel):
    x: float  # page pt
    y: float


class HitOut(BaseModel):
    candidates: list[str]  # topmost/innermost first; cycle through for overlaps


def _ready(pid: str):
    project = repo.project_or_404(pid)
    if project["status"] != "ready":
        raise ApiError(
            409,
            "STRUCTURE_UNCONFIRMED",
            "패키지 구조를 먼저 확인해주세요.",
            hint="구조 확인을 마친 뒤 요소를 선택할 수 있습니다.",
        )
    return specs.load(project)


def _frame(spec) -> FrameOut:
    raster, crop = frame(spec, PREVIEW_EDGE, FLAT_LOOK.lighting.margin)
    return FrameOut(
        origin=[crop[0], crop[1]],
        size=[crop[2] - crop[0], crop[3] - crop[1]],
        width=raster.w,
        height=raster.h,
    )


def _prefetch(pid: str, ids: list[str]) -> None:
    """Fetch the outlined SVGs of every selectable asset once, so hovering and clicking do not
    wait on Figma (best effort: a failure only means the first hit fetches on demand)."""
    try:
        fa.node_svgs(pid, ids)
    except ApiError:
        pass


@router.get("/projects/{pid}/assets", response_model=AssetsOut)
def list_assets(pid: str, background: BackgroundTasks) -> AssetsOut:
    spec = _ready(pid)
    source, tree = fa.project_assets(pid, spec)
    if source == "figma":
        missing = [
            a["id"] for a in tree if a["selectable"] and not fa.svg_path(pid, a["id"]).exists()
        ]
        if missing:
            background.add_task(_prefetch, pid, missing)
    return AssetsOut(
        source=source,
        frame=_frame(spec),
        assets=[AssetOut(**{k: a.get(k) for k in AssetOut.model_fields}) for a in tree],
    )


def _mask(pid: str, spec, asset: dict, svgs: dict | None = None) -> np.ndarray | None:
    """The asset's mask, or None when a Figma asset's vector geometry is unavailable (never
    guessed from the printed ink: that fallback is for PDF-only projects)."""
    layers = pipeline.get_layers(pid, spec, PREVIEW_EDGE, FLAT_LOOK.lighting.margin)
    svg = None
    if asset.get("exact"):
        svg = (svgs if svgs is not None else fa.node_svgs(pid, [asset["id"]])).get(asset["id"])
        if svg is None:
            return None
    return masks.asset_mask(pid, spec, asset, PREVIEW_EDGE, layers, svg, structure_key(spec))


def _asset(pid: str, spec, aid: str) -> dict:
    _, tree = fa.project_assets(pid, spec)
    asset = next((a for a in tree if a["id"] == aid), None)
    if asset is None:
        raise ApiError(404, "ASSET_NOT_FOUND", "요소를 찾을 수 없습니다.")
    return asset


@router.get("/projects/{pid}/assets/{aid}/mask")
def asset_mask_png(pid: str, aid: str, style: str = "outline", color: str = "2563EB"):
    """The asset's mask as a transparent PNG over the frame (``FrameOut``): ``outline`` for the
    selection highlight, ``fill`` for a tinted fill."""
    spec = _ready(pid)
    asset = _asset(pid, spec, aid)
    if not asset["selectable"]:
        raise ApiError(409, "ASSET_NOT_SELECTABLE", "이 요소는 후가공 대상으로 선택할 수 없습니다.")
    m = _mask(pid, spec, asset)
    if m is None:
        raise ApiError(
            503,
            "ASSET_GEOMETRY_UNAVAILABLE",
            "이 요소의 벡터 모양을 Figma에서 받지 못했습니다.",
            hint="FIGMA_TOKEN과 네트워크를 확인한 뒤 다시 시도해주세요.",
        )
    a = masks.outline(m, 2) if style == "outline" else m * 0.45
    rgb = [int(color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    img = np.zeros(m.shape + (4,), np.uint8)
    img[..., :3] = rgb
    img[..., 3] = (np.clip(a, 0, 1) * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "PNG", optimize=True)
    return Response(
        buf.getvalue(), media_type="image/png", headers={"Cache-Control": "max-age=3600"}
    )


@router.post("/projects/{pid}/assets/hit", response_model=HitOut)
def hit(pid: str, body: HitIn) -> HitOut:
    """Selectable assets under a page point, by their exact masks: innermost (deepest, then
    smallest) first, so repeated clicks / cycling can reach parents and overlapped assets."""
    spec = _ready(pid)
    _, tree = fa.project_assets(pid, spec)
    near = [
        a
        for a in tree
        if a["selectable"]
        and a["bbox"][0] - 1 <= body.x <= a["bbox"][2] + 1
        and a["bbox"][1] - 1 <= body.y <= a["bbox"][3] + 1
    ]
    if not near:
        return HitOut(candidates=[])
    fr = _frame(spec)
    px = int((body.x - fr.origin[0]) / fr.size[0] * fr.width)
    py = int((body.y - fr.origin[1]) / fr.size[1] * fr.height)
    svgs = fa.node_svgs(pid, [a["id"] for a in near if a.get("exact")])
    r = 3  # a few pixels of tolerance around thin strokes
    hits = []
    for a in near:
        m = _mask(pid, spec, a, svgs)
        if m is None:
            continue
        win = m[max(0, py - r) : py + r + 1, max(0, px - r) : px + r + 1]
        if win.size and float(win.max()) > 0.5:
            area = (a["bbox"][2] - a["bbox"][0]) * (a["bbox"][3] - a["bbox"][1])
            hits.append((-a["depth"], area, a["id"]))
    return HitOut(candidates=[i for _, _, i in sorted(hits)])
