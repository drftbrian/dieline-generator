"""Structural topology of a project's dieline (panel graph, folds, carton type): the
structure-first base of the structural reference composition. Read-only."""

from __future__ import annotations

import threading
from collections import OrderedDict

from fastapi import APIRouter

from app.services import specs
from app.storage import repo
from app.structure import carton, topology

router = APIRouter(tags=["structure"])

_cache: OrderedDict[tuple, dict] = OrderedDict()
_lock = threading.Lock()


@router.get("/projects/{pid}/structure")
def get_structure(pid: str) -> dict:
    """The panel adjacency graph (folds only where a crease separates two panels; cuts never
    hinge), structural issues, and the recognised carton type with what is supported."""
    spec = specs.load(repo.project_or_404(pid))
    key = (pid, spec.version)
    with _lock:
        hit = _cache.get(key)
    if hit is None:
        top = topology.analyze(spec)
        hit = {
            "spec_version": spec.version,
            **top.to_dict(),
            "carton": carton.classify(top, spec.box),
        }
        with _lock:
            _cache[key] = hit
            while len(_cache) > 16:
                _cache.popitem(last=False)
    return hit


def _folded(pid: str, state: str):
    from app.errors import ApiError
    from app.structure import fold

    spec = specs.load(repo.project_or_404(pid))
    top = topology.analyze(spec)
    info = carton.classify(top, spec.box)
    try:
        return fold.fold(top, info, state)
    except fold.FoldError as e:
        raise ApiError(
            409,
            e.code,
            e.message,
            hint="구조 검토에서 칼선·접는 선을 확인해주세요.",
            details={"reasons": e.reasons},
        ) from None


@router.get("/projects/{pid}/structure/fold")
def get_fold(pid: str, state: str = "closed") -> dict:
    """The carton folded deterministically from its fold graph: per panel its role, layer and
    4x4 transform (flat-net mm -> world mm) and folded outline, plus the closure, containment
    and intersection checks. 409 when the structure is not supported."""
    return _folded(pid, state).to_dict()


@router.get("/projects/{pid}/structure/preview")
def get_preview(
    pid: str,
    pose: str = "standing_three_quarter",
    state: str | None = None,
    azimuth: float | None = None,
    elevation: float | None = None,
    width: int = 900,
    height: int = 900,
):
    """A structural preview PNG of the folded carton (panels coloured by role, inside faces as
    plain board). Server-rendered and deterministic: the same pixels as the export path."""
    from fastapi import Response

    from app.errors import ApiError
    from app.render import structure3d

    p = structure3d.POSES.get(pose)
    if p is None:
        raise ApiError(422, "POSE_UNKNOWN", f"알 수 없는 자세입니다: {pose}")
    folded = _folded(pid, state or p.default_state)
    w, h = max(64, min(width, 2048)), max(64, min(height, 2048))
    r = structure3d.render(folded, p, (w, h), azimuth=azimuth, elevation=elevation)
    return Response(
        structure3d.to_png(r), media_type="image/png", headers={"Cache-Control": "no-store"}
    )
