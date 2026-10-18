"""Step 2 (flat render) and step 3 (reference merge), and the jobs that run them."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request, Response

from app.ai import providers
from app.ai.models import IMAGE_MODEL
from app.api.deps import idempotent_replay, is_legacy, remember
from app.api.schemas import (
    ComposeIn,
    EnhanceIn,
    EnhanceInterpretIn,
    EnhanceInterpretOut,
    FinishIn,
    GenerateIn,
    GenerateOut,
    JobOut,
    MergeIn,
)
from app.config import get_settings
from app.errors import ApiError
from app.finishing import spec as fspec
from app.jobs import runner
from app.jobs.runner import Cancelled, JobContext
from app.services import (
    enhance,
    enhance_prompt,
    finish_realism,
    merge,
    pipeline,
    specs,
    structural_merge,
)
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
    if (
        runner.active_count("generate", "merge", "enhance", "finish", "compose")
        >= get_settings().max_concurrent_generations
    ):
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
    look = (body.look if body else None) or get_settings().flat_look
    fold = (body.fold_preset if body else None) or get_settings().flat_fold_preset
    _check_can_start(repo.project_or_404(pid), needs_model=mode == "ai_appearance")
    out = _start(
        pid,
        "generate",
        lambda ctx, vid: pipeline.run_generate(ctx, vid, mode, look, fold),
        kind="flat",
        reference_ids=[],
        settings={"flat_mode": mode, "flat_look": look}
        | ({"fold_preset": fold} if look == "v4" else {}),
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


@router.post("/projects/{pid}/compose", response_model=GenerateOut, status_code=202)
def start_compose(pid: str, body: ComposeIn, request: Request):
    """Step 3, structural mode: the deterministic composition of our folded carton(s) in the
    reference scene, then optionally the AI harmonization (``harmonize``)."""
    if replay := idempotent_replay(request, f"compose:{pid}"):
        return replay
    project = repo.project_or_404(pid)
    _check_can_start(project, needs_model=body.harmonize)
    ref = repo.get("refs", body.reference_id)
    if ref is None or ref["project_id"] != pid:
        raise ApiError(404, "REFERENCE_NOT_FOUND", "레퍼런스를 찾을 수 없습니다.")
    flat = _flat_version(pid, body.flat_version_id)
    scene = structural_merge.load_scene(pid, body.reference_id)
    if not any(i.get("enabled", True) for i in scene.get("instances", [])):
        raise ApiError(
            409,
            "SCENE_EMPTY",
            "레퍼런스에서 교체할 패키지가 없습니다.",
            hint="'패키지 찾기'를 누르거나 직접 지정해주세요.",
        )
    structural_merge._structure(specs.load(project))  # unsupported structures stop here (409)
    out = _start(
        pid,
        "compose",
        structural_merge.run_structural,
        settings={
            "merge_mode": "structural",
            "harmonize": body.harmonize,
            "strength": body.strength,
        },
        kind="merge",
        reference_ids=[body.reference_id],
        flat_version_id=flat["id"],
        scene_json={
            "reference_id": body.reference_id,
            "form": "structural",
            "scene": scene,
            "harmonize": body.harmonize,
            "strength": body.strength,
        },
    )
    remember(request, f"compose:{pid}", 202, out.model_dump())
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


def _enhance_source(pid: str, vid: str) -> dict:
    """A finished deterministic flat render of this project (the only thing we enhance)."""
    v = repo.get("versions", vid)
    settings = (v or {}).get("settings_json") or {}
    if (
        v is None
        or v["project_id"] != pid
        or v["deleted_at"]
        or v["status"] != "done"
        or (v.get("kind") or "flat") != "flat"
        or is_legacy(v)
        or settings.get("flat_mode") != "deterministic"
    ):
        raise ApiError(
            409,
            "ENHANCE_SOURCE_INVALID",
            "AI 보정은 완료된 코드 렌더(②, AI 없음)에만 할 수 있습니다.",
            hint="② 플랫 렌더를 먼저 만들고 그 버전을 선택해주세요.",
        )
    return v


@router.post("/projects/{pid}/versions/{vid}/enhance", response_model=GenerateOut, status_code=202)
def start_enhance(pid: str, vid: str, body: EnhanceIn, request: Request):
    """Optional AI material enhancement of a finished deterministic render. Makes a new
    version; the source render is never changed. ``maps_from`` re-applies an earlier
    enhancement's maps at a new strength without calling the model."""
    if replay := idempotent_replay(request, f"enhance:{pid}:{vid}"):
        return replay
    project = repo.project_or_404(pid)
    source = _enhance_source(pid, vid)
    if body.maps_from:
        prev = repo.get("versions", body.maps_from)
        prev_settings = (prev or {}).get("settings_json") or {}
        if (
            prev is None
            or prev["project_id"] != pid
            or prev["status"] != "done"
            or prev_settings.get("flat_mode") != "ai_material"
            or prev_settings.get("source_version_id") != vid
            or not (repo.project_dir(pid) / "versions" / f"{prev['id']}_light.npy").exists()
        ):
            raise ApiError(
                409,
                "ENHANCE_MAPS_MISSING",
                "다시 적용할 AI 보정 결과를 찾을 수 없습니다.",
                hint="같은 원본의 완료된 AI 보정 버전을 선택해주세요.",
            )
    # Priority 1/2 before anything runs: the prompt is read into a spec, and any protected
    # operation is refused here, server-side, whatever the client did.
    reading = enhance_prompt.permitted(
        enhance_prompt.interpret(body.user_prompt), body.confirm_allowed_only
    )
    if body.reference_id and repo.get("refs", body.reference_id) is None:
        raise ApiError(404, "REFERENCE_NOT_FOUND", "레퍼런스를 찾을 수 없습니다.")
    _check_can_start(project, needs_model=not body.maps_from)
    out = _start(
        pid,
        "enhance",
        enhance.run_enhance,
        kind="flat",
        reference_ids=[body.reference_id] if body.reference_id else [],
        flat_version_id=vid,
        settings={
            "flat_mode": "ai_material",
            "flat_look": source["settings_json"].get("flat_look", "v3"),
            "fold_preset": source["settings_json"].get("fold_preset", "medium"),
            "source_version_id": vid,
            "strength": body.strength,
            "reference_id": body.reference_id,
            "maps_from": body.maps_from,
            "phase": enhance.PHASE,
            "user_prompt": reading.prompt or None,
            "spec": reading.spec.model_dump(),
            "operations": [o.model_dump() for o in reading.operations],
            "notes": reading.notes,
            "reader": reading.reader,
        },
    )
    remember(request, f"enhance:{pid}:{vid}", 202, out.model_dump())
    return out


@router.post("/projects/{pid}/versions/{vid}/finish", response_model=GenerateOut, status_code=202)
def start_finish(pid: str, vid: str, body: FinishIn, request: Request):
    """Save a flat render with a finishing revision baked in as a new version (usable in ③),
    optionally with "AI 사실감" on the foil / relief / spot-UV areas. The source render and the
    finishing specification are never changed."""
    if replay := idempotent_replay(request, f"finish:{pid}:{vid}"):
        return replay
    project = repo.project_or_404(pid)
    v = repo.get("versions", vid)
    settings = (v or {}).get("settings_json") or {}
    if (
        v is None
        or v["project_id"] != pid
        or v["deleted_at"]
        or v["status"] != "done"
        or (v.get("kind") or "flat") != "flat"
        or is_legacy(v)
        or settings.get("flat_mode") not in ("deterministic", "ai_material")
    ):
        raise ApiError(
            409,
            "FINISH_SOURCE_INVALID",
            "후가공 버전은 완료된 ② 플랫 렌더에서만 만들 수 있습니다.",
            hint="후가공이 없는 플랫 렌더 버전을 선택해주세요.",
        )
    fin = fspec.load(pid) if body.revision is None else fspec.load_revision(pid, body.revision)
    if not any(a.enabled for a in fin.assignments):
        raise ApiError(
            409,
            "FINISHING_EMPTY",
            "적용된 후가공이 없습니다.",
            hint="후가공을 하나 이상 적용한 뒤 저장해주세요.",
        )
    _check_can_start(project, needs_model=body.ai)
    out = _start(
        pid,
        "finish",
        finish_realism.run_finish,
        kind="flat",
        reference_ids=[],
        flat_version_id=vid,
        settings={
            "flat_mode": "finished",
            "flat_look": settings.get("flat_look", "v3"),
            "fold_preset": settings.get("fold_preset", "medium"),
            "source_version_id": vid,
            "finishing_revision": fin.revision,
            "ai": body.ai,
            "strength": body.strength,
            "light": body.light,
        },
    )
    remember(request, f"finish:{pid}:{vid}", 202, out.model_dump())
    return out


@router.post("/projects/{pid}/enhance/interpret", response_model=EnhanceInterpretOut)
def interpret_enhance_prompt(pid: str, body: EnhanceInterpretIn) -> EnhanceInterpretOut:
    """Read an enhancement prompt without running anything: what it becomes, and whether it
    asks for protected changes (the same reading the enhance endpoint enforces)."""
    repo.project_or_404(pid)
    reading = enhance_prompt.interpret(body.user_prompt)
    forbidden = reading.forbidden
    appearance = [o for o in reading.operations if o.category in enhance_prompt.APPEARANCE_CATS]
    return EnhanceInterpretOut(
        prompt=reading.prompt,
        blocked=bool(forbidden),
        message=enhance_prompt.PROTECTED_MESSAGE if forbidden else None,
        can_run_allowed_only=bool(forbidden) and bool(appearance),
        operations=[o.model_dump() for o in reading.operations],
        spec=reading.spec,
        notes=reading.notes,
        reader=reading.reader,
    )
