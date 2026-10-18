"""Step 3, structural mode: the packages of a reference (instances) and a fast deterministic
preview of the composition. The full composition (and optional AI) runs as a job
(``POST /projects/{pid}/compose``)."""

from __future__ import annotations

import io
import json

import numpy as np
from fastapi import APIRouter, Response
from PIL import Image
from pydantic import BaseModel

from app.errors import ApiError
from app.services import structural_merge
from app.storage import repo

router = APIRouter(tags=["scene"])

PREVIEW_EDGE = 1024
LAYERS = (
    "placement",
    "removal_mask",
    "background",
    "albedo",
    "lighting",
    "shadow_only",
    "photo_shadow_field",
    "cast_shadow",
    "ground_shadow",
)


class SceneIn(BaseModel):
    instances: list[dict]
    settings: dict = {}


def _ref(pid: str, rid: str) -> dict:
    ref = repo.get("refs", rid)
    if ref is None or ref["project_id"] != pid:
        raise ApiError(404, "REFERENCE_NOT_FOUND", "레퍼런스를 찾을 수 없습니다.")
    return ref


@router.get("/projects/{pid}/references/{rid}/scene")
def get_scene(pid: str, rid: str) -> dict:
    """The packages to replace in this reference (normalised quads), as saved."""
    _ref(pid, rid)
    return structural_merge.load_scene(pid, rid)


@router.put("/projects/{pid}/references/{rid}/scene")
def put_scene(pid: str, rid: str, body: SceneIn) -> dict:
    """Save the user's instances (count, which are enabled, corners, size, rotation...)."""
    _ref(pid, rid)
    prev = structural_merge.load_scene(pid, rid)
    return structural_merge.save_scene(
        pid,
        rid,
        {
            "source": "user" if prev.get("instances") else "user",
            "instances": body.instances,
            "settings": body.settings,
        },
    )


@router.post("/projects/{pid}/references/{rid}/scene/detect")
def detect_scene(pid: str, rid: str) -> dict:
    """Claude proposes the reference's packages (one quad each); the user confirms or edits."""
    _ref(pid, rid)
    return structural_merge.detect(pid, rid)


@router.get("/projects/{pid}/compose/preview")
def compose_preview(pid: str, reference_id: str, flat_version_id: str, layer: str = "final"):
    """A fast deterministic preview (no AI) at PREVIEW_EDGE: the composition or one of its
    diagnostic layers. ``X-Compose-Report`` carries the checks and estimates."""
    if layer != "final" and layer not in LAYERS:
        raise ApiError(422, "LAYER_UNKNOWN", f"알 수 없는 레이어입니다: {layer}")
    comp, _, _ = structural_merge.precompose(pid, reference_id, flat_version_id, edge=PREVIEW_EDGE)
    if layer == "final":
        img = comp.image
    else:
        a = np.asarray(comp.layers[layer], np.float32)
        if a.ndim == 2:
            a = np.repeat(a[..., None], 3, -1)
        img = (np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "PNG")
    report = {
        k: comp.report[k]
        for k in ("match", "instances", "lens_mm_35eq", "ambient", "light", "reference_print_leak")
        if k in comp.report
    }
    return Response(
        buf.getvalue(),
        media_type="image/png",
        headers={
            "X-Compose-Report": json.dumps(report, default=float),
            "Cache-Control": "no-store",
        },
    )


@router.get("/projects/{pid}/versions/{vid}/layers/{name}")
def version_layer(pid: str, vid: str, name: str):
    """A saved intermediate of a structural composition (deterministic precomposition, model
    output, layers)."""
    v = repo.get("versions", vid)
    if v is None or v["project_id"] != pid:
        raise ApiError(404, "VERSION_NOT_FOUND", "버전을 찾을 수 없습니다.")
    files = {
        "structure": f"{vid}_structure.png",
        "raw": f"{vid}_raw.png",
        **{n: f"{vid}_layer_{n}.png" for n in LAYERS},
    }
    if name not in files:
        raise ApiError(422, "LAYER_UNKNOWN", f"알 수 없는 레이어입니다: {name}")
    p = repo.project_dir(pid) / "versions" / files[name]
    if not p.exists():
        raise ApiError(404, "LAYER_MISSING", "이 버전에는 해당 중간 결과가 없습니다.")
    return Response(p.read_bytes(), media_type="image/png", headers={"Cache-Control": "no-store"})
