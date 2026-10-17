"""Step 2 (flat render) and step 3 (reference merge), and the jobs that run them."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request, Response

from app.ai import providers
from app.ai.models import IMAGE_MODEL
from app.api.deps import idempotent_replay, is_legacy, remember
from app.api.schemas import GenerateIn, GenerateOut, JobOut, MergeIn
from app.config import get_settings
from app.errors import ApiError
from app.jobs import runner
from app.jobs.runner import Cancelled, JobContext
from app.services import merge, pipeline, specs
from app.storage import repo

router = APIRouter(tags=["generate"])


def _check_can_start(project: dict, needs_model: bool = True) -> None:
    if project["status"] != "ready":
        raise ApiError(
            409,
            "STRUCTURE_UNCONFIRMED",
            "패키지 구조를 먼저 확인해주세요.",
            hint="구조 확인 화면에서 남은 항목을 확정해주세요.",
        )
    if needs_model and not providers.PROVIDER.available():
        raise ApiError(
            503,
            "PROVIDER_UNAVAILABLE",
            "Gemini API 키가 설정되지 않았습니다.",
            hint="backend/.env에 GEMINI_API_KEY를 추가하세요.",
        )
    if runner.active_count("generate", "merge") >= get_settings().max_concurrent_generations:
        raise ApiError(
            429,
            "TOO_MANY_GENERATIONS",
            "생성이 이미 여러 개 진행 중입니다.",
            hint="진행 중인 생성이 끝난 뒤 시작할 수 있습니다.",
        )


def _start(
    pid: str,
    job_type: str,
    work: Callable[[JobContext, str], dict],
    settings: dict | None = None,
    **fields,
) -> GenerateOut:
    """A new version row plus the background job that fills it."""
    spec = specs.load(repo.project_or_404(pid))
    number = (
        repo.query(
            "SELECT COALESCE(MAX(number), 0) AS n FROM versions WHERE project_id = ?", [pid]
        )[0]["n"]
        + 1
    )
    job = runner.create(pid, job_type)
    vid = repo.new_id("ver")
    repo.insert(
        "versions",
        {
            "id": vid,
            "project_id": pid,
            "number": number,
            "parent_id": None,
            "status": "running",
            "provider": IMAGE_MODEL.provider,
            "model_id": IMAGE_MODEL.model_id,
            "mode": "artwork_locked",
            "settings_json": {"pipeline": pipeline.PIPELINE, **(settings or {})},
            "spec_version": spec.version,
            "job_id": job["id"],
            "usage_json": None,
            "verify_json": None,
            "frame_json": None,
            "error_json": None,
            "starred": 0,
            "name": None,
            "deleted_at": None,
            "created_at": repo.now(),
            **fields,
        },
    )

    def run(ctx: JobContext):
        try:
            return work(ctx, vid)
        except Cancelled:
            repo.execute("DELETE FROM versions WHERE id = ?", [vid])
            raise
        except ApiError as e:
            repo.update("versions", vid, status="failed", error_json=e.body.model_dump())
            raise
        except Exception:
            repo.update(
                "versions",
                vid,
                status="failed",
                error_json={
                    "code": "GENERATION_FAILED",
                    "message": "생성에 실패했습니다.",
                    "hint": "다시 시도해주세요.",
                    "details": {},
                },
            )
            raise

    runner.submit(job, run)
    return GenerateOut(job_id=job["id"], version_id=vid)


@router.post("/projects/{pid}/generate", response_model=GenerateOut, status_code=202)
def generate(pid: str, request: Request, body: GenerateIn | None = None):
    """Step 2: the flat, unfolded render in the fixed look (deterministic by default)."""
    if replay := idempotent_replay(request, f"generate:{pid}"):
        return replay
    mode = (body.mode if body else None) or get_settings().flat_render_mode
    _check_can_start(repo.project_or_404(pid), needs_model=mode == "ai_appearance")
    out = _start(
        pid,
        "generate",
        lambda ctx, vid: pipeline.run_generate(ctx, vid, mode),
        kind="flat",
        reference_ids=[],
        settings={"flat_mode": mode},
    )
    remember(request, f"generate:{pid}", 202, out.model_dump())
    return out


def _flat_version(pid: str, vid: str | None) -> dict:
    """The approved flat render to merge: the given one, or the latest successful one."""
    if vid is None:
        rows = repo.query(
            "SELECT * FROM versions WHERE project_id = ? AND status = 'done' "
            "AND deleted_at IS NULL AND COALESCE(kind, 'flat') = 'flat' ORDER BY number DESC",
            [pid],
        )
        flat = next((v for v in rows if not is_legacy(v)), None)
        if flat is None:
            raise ApiError(
                409,
                "FLAT_VERSION_MISSING",
                "합성할 플랫 렌더가 없습니다.",
                hint="② 플랫 렌더를 먼저 생성해주세요.",
            )
        return flat
    v = repo.get("versions", vid)
    if (
        v is None
        or v["project_id"] != pid
        or v["deleted_at"]
        or v["status"] != "done"
        or (v.get("kind") or "flat") != "flat"
        or is_legacy(v)
        or not v.get("frame_json")
    ):
        raise ApiError(
            409,
            "FLAT_VERSION_INVALID",
            "이 버전으로는 합성할 수 없습니다.",
            hint="완료된 ② 플랫 렌더를 선택해주세요.",
        )
    return v


@router.post("/projects/{pid}/merge", response_model=GenerateOut, status_code=202)
def start_merge(pid: str, body: MergeIn, request: Request):
    """Step 3: our packaging in place of the packaging in the reference photo."""
    if replay := idempotent_replay(request, f"merge:{pid}"):
        return replay
    project = repo.project_or_404(pid)
    _check_can_start(project)
    ref = repo.get("refs", body.reference_id)
    if ref is not None and ref["project_id"] != pid:
        ref = None
    reading = merge.reference_reading(ref)
    flat = _flat_version(pid, body.flat_version_id)
    form = body.form
    if form == "auto":
        form = "flat" if reading.get("packaging_form") == "flat" else "folded"
    if form == "folded":
        merge.faces_or_409(specs.load(project))
    out = _start(
        pid,
        "merge",
        merge.run_merge,
        kind="merge",
        reference_ids=[body.reference_id],
        flat_version_id=flat["id"],
        scene_json={"reference_id": body.reference_id, "form": form},
    )
    remember(request, f"merge:{pid}", 202, out.model_dump())
    return out


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str) -> JobOut:
    job = repo.get("jobs", job_id)
    if job is None:
        raise ApiError(404, "JOB_NOT_FOUND", "작업을 찾을 수 없습니다.")
    return JobOut(**job)


@router.post("/jobs/{job_id}/cancel", status_code=204)
def cancel_job(job_id: str) -> Response:
    job = repo.get("jobs", job_id)
    if job is None:
        raise ApiError(404, "JOB_NOT_FOUND", "작업을 찾을 수 없습니다.")
    if job["status"] in ("pending", "running"):
        repo.update("jobs", job_id, cancel_requested=1)
    return Response(status_code=204)
