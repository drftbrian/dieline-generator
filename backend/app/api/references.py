"""Reference photos for step 3 (merge), read by Claude with prompts/reference_guide.md."""

from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, File, Response, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

from app.ai import claude
from app.api.deps import reference_out
from app.api.schemas import ReferenceOut
from app.config import get_settings
from app.errors import ApiError
from app.services.merge import REFERENCE_SCHEMA, is_stale
from app.storage import repo

router = APIRouter(prefix="/projects/{pid}/references", tags=["references"])
log = logging.getLogger(__name__)
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ref")

ALLOWED = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
MAX_REFERENCES = 12


def _rows(pid: str) -> list[dict]:
    return repo.query(
        "SELECT * FROM refs WHERE project_id = ? ORDER BY position, created_at", [pid]
    )


def _ref(pid: str, rid: str) -> dict:
    r = repo.get("refs", rid)
    if r is None or r["project_id"] != pid:
        raise ApiError(404, "REFERENCE_NOT_FOUND", "레퍼런스를 찾을 수 없습니다.")
    return r


def _start_analysis(rid: str) -> None:
    repo.update("refs", rid, analysis_status="pending")
    _pool.submit(_analyze, rid)


@router.get("", response_model=list[ReferenceOut])
def list_references(pid: str) -> list[ReferenceOut]:
    repo.project_or_404(pid)
    rows = _rows(pid)
    if claude.available():
        # Readings from an earlier version of the app are read again, once, in the background.
        for r in rows:
            if is_stale(r):
                _start_analysis(r["id"])
                r["analysis_status"] = "pending"
    return [reference_out(r) for r in rows]


@router.post("", response_model=ReferenceOut, status_code=201)
async def upload_reference(pid: str, file: UploadFile = File(...)) -> ReferenceOut:
    repo.project_or_404(pid)
    if len(_rows(pid)) >= MAX_REFERENCES:
        raise ApiError(
            409,
            "REFERENCE_LIMIT",
            f"최대 {MAX_REFERENCES}개까지 추가할 수 있습니다.",
            hint="기존 레퍼런스를 삭제한 뒤 추가해주세요.",
        )
    data = await file.read()
    limit = get_settings().max_reference_mb
    if len(data) > limit * 1024 * 1024:
        raise ApiError(
            413,
            "REFERENCE_TOO_LARGE",
            f"이미지가 {limit}MB를 넘습니다.",
            hint="더 작은 이미지를 사용해주세요.",
        )
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ApiError(
            400,
            "REFERENCE_INVALID",
            "이미지를 읽을 수 없습니다.",
            hint="PNG, JPEG, WebP 파일만 지원합니다.",
        ) from e
    if img.format not in ALLOWED:
        raise ApiError(
            400,
            "REFERENCE_FORMAT",
            "지원하지 않는 이미지 형식입니다.",
            hint="PNG, JPEG, WebP 파일만 지원합니다.",
        )

    rid = repo.new_id("ref")
    rdir = repo.project_dir(pid) / "refs"
    rdir.mkdir(exist_ok=True)
    rgb = img.convert("RGB")
    rgb.save(rdir / f"{rid}.png")
    thumb = rgb.copy()
    thumb.thumbnail((320, 320))
    thumb.save(rdir / f"{rid}_thumb.jpg", "JPEG", quality=85)
    position = max((r["position"] for r in _rows(pid)), default=-1) + 1
    repo.insert(
        "refs",
        {
            "id": rid,
            "project_id": pid,
            "filename": file.filename or "reference",
            "mime": ALLOWED[img.format],
            "width": img.width,
            "height": img.height,
            "role": None,
            "role_source": None,
            "note": "",
            "summary": None,
            "analysis_status": "pending" if claude.available() else "skipped",
            "position": position,
            "created_at": repo.now(),
        },
    )
    if claude.available():
        _pool.submit(_analyze, rid)
    return reference_out(_ref(pid, rid))


def _analyze(rid: str) -> None:
    """Claude's reading: category, its seven sections, packaging form, camera and light."""
    r = repo.get("refs", rid)
    if r is None:
        return
    try:
        img = Image.open(repo.project_dir(r["project_id"]) / "refs" / f"{rid}.png")
        result = claude.analyze_reference(img)
        if repo.get("refs", rid) is None:
            return  # deleted while Claude was reading it
        repo.update(
            "refs",
            rid,
            summary=result.summary,
            analysis_status="done",
            analysis_json={"schema": REFERENCE_SCHEMA, **result.model_dump()},
        )
    except Exception as e:  # noqa: BLE001 - shown as "failed"; it can be read again
        log.warning("reference analysis failed: %s", e)
        repo.update("refs", rid, analysis_status="failed")


@router.post("/{rid}/analyze", response_model=ReferenceOut, status_code=202)
def reanalyze_reference(pid: str, rid: str) -> ReferenceOut:
    """Read the reference again (Claude, paid)."""
    _ref(pid, rid)
    if not claude.available():
        raise ApiError(
            503,
            "CLAUDE_UNAVAILABLE",
            "Claude API 키가 설정되지 않았습니다.",
            hint="backend/.env에 ANTHROPIC_API_KEY를 추가하세요.",
        )
    _start_analysis(rid)
    return reference_out(_ref(pid, rid))


@router.delete("/{rid}", status_code=204)
def delete_reference(pid: str, rid: str) -> Response:
    _ref(pid, rid)
    repo.execute("DELETE FROM refs WHERE id = ?", [rid])
    for suffix in (".png", "_thumb.jpg"):
        (repo.project_dir(pid) / "refs" / f"{rid}{suffix}").unlink(missing_ok=True)
    return Response(status_code=204)


@router.get("/{rid}/image")
def reference_image(pid: str, rid: str):
    path = repo.project_dir(pid) / "refs" / f"{rid}.png"
    if not path.exists():
        raise ApiError(404, "REFERENCE_NOT_FOUND", "레퍼런스를 찾을 수 없습니다.")
    return FileResponse(path, media_type="image/png")


@router.get("/{rid}/thumb")
def reference_thumb(pid: str, rid: str):
    path = repo.project_dir(pid) / "refs" / f"{rid}_thumb.jpg"
    if not path.exists():
        raise ApiError(404, "REFERENCE_NOT_FOUND", "레퍼런스를 찾을 수 없습니다.")
    return FileResponse(path, media_type="image/jpeg")
