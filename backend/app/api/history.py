"""Generated versions: flat renders (step 2) and reference merges (step 3)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse

from app.api.deps import version_out
from app.api.schemas import HistoryOut, VersionOut
from app.errors import ApiError
from app.storage import repo

router = APIRouter(tags=["history"])


def _version(pid: str, vid: str) -> dict:
    v = repo.get("versions", vid)
    if v is None or v["project_id"] != pid:
        raise ApiError(404, "VERSION_NOT_FOUND", "버전을 찾을 수 없습니다.")
    return v


@router.get("/projects/{pid}/history", response_model=HistoryOut)
def history(pid: str) -> HistoryOut:
    repo.project_or_404(pid)
    rows = repo.query(
        "SELECT * FROM versions WHERE project_id = ? AND deleted_at IS NULL ORDER BY number", [pid]
    )
    return HistoryOut(versions=[version_out(v) for v in rows])


@router.get("/projects/{pid}/versions/{vid}", response_model=VersionOut)
def get_version(pid: str, vid: str) -> VersionOut:
    return version_out(_version(pid, vid))


@router.delete("/projects/{pid}/versions/{vid}", status_code=204)
def delete_version(pid: str, vid: str) -> Response:
    v = _version(pid, vid)
    if v["status"] == "running":
        raise ApiError(
            409,
            "VERSION_RUNNING",
            "생성 중인 버전은 삭제할 수 없습니다.",
            hint="생성을 취소하거나 완료된 뒤 삭제해주세요.",
        )
    repo.update("versions", vid, deleted_at=repo.now())
    repo.update("projects", pid, updated_at=repo.now())  # refresh the thumbnail cache key
    return Response(status_code=204)


@router.get("/projects/{pid}/versions/{vid}/image")
def version_image(pid: str, vid: str, download: bool = False):
    """The result PNG; ``?download=1`` saves it as ``<project>_v<n>_<flat|merge>.png``."""
    v = _version(pid, vid)
    path = repo.project_dir(pid) / "versions" / f"{vid}.png"
    if not path.exists():
        raise ApiError(404, "VERSION_IMAGE_MISSING", "결과 이미지가 아직 없습니다.")
    if not download:
        return FileResponse(path, media_type="image/png")
    name = re.sub(r"[^\w가-힣\-]+", "_", repo.project_or_404(pid)["name"]).strip("_") or "dieline"
    kind = "merge" if v.get("kind") in ("merge", "scene") else "flat"
    return FileResponse(path, media_type="image/png", filename=f"{name}_v{v['number']}_{kind}.png")


@router.get("/projects/{pid}/versions/{vid}/thumb")
def version_thumb(pid: str, vid: str):
    _version(pid, vid)
    path = repo.project_dir(pid) / "versions" / f"{vid}_thumb.jpg"
    if not path.exists():
        raise ApiError(404, "VERSION_IMAGE_MISSING", "결과 이미지가 아직 없습니다.")
    return FileResponse(path, media_type="image/jpeg")
