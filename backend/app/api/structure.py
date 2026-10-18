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
