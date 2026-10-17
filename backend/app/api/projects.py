"""Projects, source PDF (from a Figma import or an upload), analysis and the specification."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, File, Header, Request, Response, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import idempotent_replay, project_out, remember
from app.api.schemas import (
    AnalyzeIn,
    FrameOut,
    JobRef,
    ProjectCreate,
    ProjectOut,
    ProjectPatch,
    SourceOut,
    SpecPatch,
    UploadOut,
)
from app.config import get_settings
from app.errors import ApiError
from app.jobs import runner
from app.pdf import analyze, physical
from app.pdf.validate import validate_pdf
from app.render.layers import frame
from app.services import pipeline, specs
from app.spec.models import FLAT_LOOK, BoxDims, PhysicalScale, Specification, StructuralPath
from app.storage import repo

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects() -> list[ProjectOut]:
    rows = repo.query("SELECT * FROM projects ORDER BY updated_at DESC")
    return [project_out(p) for p in rows]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, request: Request):
    if replay := idempotent_replay(request, "create_project"):
        return replay
    p = {
        "id": repo.new_id("prj"),
        "name": body.name.strip(),
        "status": "uploading",
        "source_json": None,
        "spec_json": None,
        "spec_version": 0,
        "error_json": None,
        "created_at": repo.now(),
        "updated_at": repo.now(),
    }
    repo.insert("projects", p)
    out = project_out(p)
    remember(request, "create_project", 201, out.model_dump(mode="json"))
    return out


@router.get("/{pid}", response_model=ProjectOut)
def get_project(pid: str) -> ProjectOut:
    return project_out(repo.project_or_404(pid))


@router.patch("/{pid}", response_model=ProjectOut)
def rename_project(pid: str, body: ProjectPatch) -> ProjectOut:
    repo.project_or_404(pid)
    repo.update("projects", pid, name=body.name.strip(), updated_at=repo.now())
    return project_out(repo.project_or_404(pid))


@router.delete("/{pid}", status_code=204)
def delete_project(pid: str) -> Response:
    repo.project_or_404(pid)
    repo.execute("DELETE FROM projects WHERE id = ?", [pid])
    repo.remove_project_files(pid)
    pipeline.drop_cache(pid)
    return Response(status_code=204)


# ---- source --------------------------------------------------------------------------


@router.post("/{pid}/upload", response_model=UploadOut, status_code=202)
async def upload_source(pid: str, request: Request, file: UploadFile = File(...)):
    if replay := idempotent_replay(request, f"upload:{pid}"):
        return replay
    project = repo.project_or_404(pid)
    if project["source_json"]:
        raise ApiError(
            409,
            "SOURCE_EXISTS",
            "이 프로젝트에는 이미 원본 PDF가 있습니다.",
            hint="다른 PDF는 새 프로젝트로 업로드해주세요.",
        )
    data = await file.read()
    info = validate_pdf(data, get_settings().max_upload_mb)
    repo.write_source_once(pid, data)
    source = SourceOut(
        filename=file.filename or "source.pdf",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        page_count=info.page_count,
        width_mm=round(info.width_pt * 25.4 / 72, 1),
        height_mm=round(info.height_pt * 25.4 / 72, 1),
        uploaded_at=repo.now(),
    )
    repo.update(
        "projects", pid, source_json=source.model_dump(), status="analyzing", updated_at=repo.now()
    )
    job = runner.create(pid, "analyze")
    runner.submit(job, lambda ctx: pipeline.run_analyze(ctx, None))
    out = UploadOut(project=project_out(repo.project_or_404(pid)), job_id=job["id"])
    remember(request, f"upload:{pid}", 202, out.model_dump(mode="json"))
    return out


@router.get("/{pid}/source", response_model=SourceOut)
def get_source(pid: str) -> SourceOut:
    p = repo.project_or_404(pid)
    if not p["source_json"]:
        raise ApiError(404, "SOURCE_MISSING", "원본 PDF가 아직 업로드되지 않았습니다.")
    return SourceOut(**p["source_json"])


@router.get("/{pid}/source/file")
def get_source_file(pid: str, download: bool = False):
    p = repo.project_or_404(pid)
    path = repo.source_path(pid)
    if not path.exists():
        raise ApiError(404, "SOURCE_MISSING", "원본 PDF가 아직 업로드되지 않았습니다.")
    name = (p["source_json"] or {}).get("filename", "source.pdf")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=name if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/{pid}/thumbnail")
def get_thumbnail(pid: str):
    repo.project_or_404(pid)
    pdir = repo.project_dir(pid)
    starred = repo.query(
        "SELECT id FROM versions WHERE project_id = ? AND status = 'done' AND deleted_at IS NULL "
        "ORDER BY starred DESC, number DESC LIMIT 1",
        [pid],
    )
    candidates = ([pdir / "versions" / f"{starred[0]['id']}_thumb.jpg"] if starred else []) + [
        pdir / "flat.jpg",
        pdir / "thumb.jpg",
    ]
    for c in candidates:
        if c.exists():
            return FileResponse(c, media_type="image/jpeg")
    raise ApiError(404, "THUMBNAIL_MISSING", "썸네일이 아직 없습니다.")


@router.get("/{pid}/page-image")
def get_page_image(pid: str):
    repo.project_or_404(pid)
    path = repo.project_dir(pid) / "page.png"
    if not path.exists():
        raise ApiError(404, "PAGE_IMAGE_MISSING", "원본 미리보기가 아직 준비되지 않았습니다.")
    return FileResponse(path, media_type="image/png")


# ---- analysis & specification ------------------------------------------------------


@router.post("/{pid}/analyze", response_model=JobRef, status_code=202)
def start_analyze(pid: str, body: AnalyzeIn) -> JobRef:
    p = repo.project_or_404(pid)
    if not p["source_json"]:
        raise ApiError(
            409,
            "SOURCE_MISSING",
            "원본 PDF가 아직 업로드되지 않았습니다.",
            hint="PDF를 먼저 업로드해주세요.",
        )
    job = runner.create(pid, "analyze")
    runner.submit(job, lambda ctx: pipeline.run_analyze(ctx, body.page))
    return JobRef(job_id=job["id"])


@router.get("/{pid}/specification", response_model=Specification)
def get_specification(pid: str, response: Response) -> Specification:
    spec = specs.load(repo.project_or_404(pid))
    response.headers["ETag"] = str(spec.version)
    return spec


@router.patch("/{pid}/specification", response_model=Specification)
def patch_specification(
    pid: str,
    body: SpecPatch,
    response: Response,
    if_match: str | None = Header(None),
) -> Specification:
    project = repo.project_or_404(pid)
    spec = specs.load(project)
    structure_changed = False

    if body.paths:
        by_id = {p.id: p for p in spec.paths}
        for u in body.paths:
            path = by_id.get(u.id)
            if path is None:
                raise ApiError(404, "PATH_NOT_FOUND", f"경로 {u.id}를 찾을 수 없습니다.")
            # User decisions outrank everything below them in the trust order.
            path.cls, path.status, path.provenance = u.cls, "confirmed", "user_confirmed"
        structure_changed = True
    if body.remove_paths:
        removable = {p.id for p in spec.paths if p.source_ref.startswith("manual:")}
        bad = set(body.remove_paths) - removable
        if bad:
            raise ApiError(
                400,
                "PATH_NOT_REMOVABLE",
                "PDF에서 추출한 경로는 삭제할 수 없습니다.",
                hint="분류를 '인쇄 요소'로 바꿔주세요.",
                details={"ids": sorted(bad)},
            )
        spec.paths = [p for p in spec.paths if p.id not in body.remove_paths]
        structure_changed = True
    if body.manual_cut:
        n = sum(1 for p in spec.paths if p.source_ref.startswith("manual:")) + 1
        pts = [(round(x, 2), round(y, 2)) for x, y in body.manual_cut.points]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        spec.paths.append(
            StructuralPath(
                id=f"m{n}",
                cls="cut",
                status="confirmed",
                suggested_cls="cut",
                confidence=1.0,
                provenance="user_confirmed",
                reason="사용자가 직접 지정한 외곽선",
                polylines=[pts + [pts[0]]],
                closed=[True],
                bbox=(min(xs), min(ys), max(xs), max(ys)),
                color="#E5333F",
                dashed=False,
                width_pt=0.5,
                color_space="manual",
                layers=[],
                source_ref=f"manual:{n}",
            )
        )
        structure_changed = True
    if body.panel_names:
        names = {p.id: p.name for p in body.panel_names}
        for panel in spec.panels:
            if panel.id in names:
                panel.name, panel.name_provenance = names[panel.id], "user_confirmed"
    if body.box is not None:
        spec.box = BoxDims(**body.box.model_dump(), source="user")
        if spec.scale.source != "user" and spec.scale.confidence < 0.9:
            spec.scale = PhysicalScale()  # re-derive from the box in refresh()
    if body.mm_per_pt is not None:
        spec.scale = PhysicalScale(
            mm_per_pt=body.mm_per_pt, source="user", confidence=1.0, evidence=["사용자 입력"]
        )
    if body.box is not None or body.mm_per_pt is not None:
        physical.refresh(spec, pipeline.figma_content(pid))
        pipeline.drop_cache(pid)

    if structure_changed:
        spec.review, _ = analyze.review_state(spec.paths, spec.page)
        spec.structure_confirmed = False
        spec.panels = []
        repo.update("projects", pid, status="needs_review", updated_at=repo.now())

    expected = int(if_match) if if_match and if_match.isdigit() else None
    spec = specs.save(pid, spec, expected)
    response.headers["ETag"] = str(spec.version)
    return spec


@router.post("/{pid}/specification/confirm", response_model=JobRef, status_code=202)
def confirm_structure(pid: str) -> JobRef:
    project = repo.project_or_404(pid)
    spec = specs.load(project)
    spec.review, closed = analyze.review_state(spec.paths, spec.page)
    if spec.review.pending:
        raise ApiError(
            409,
            "REVIEW_PENDING",
            f"확인이 필요한 항목이 {spec.review.pending}개 남았습니다.",
            hint="남은 항목을 분류한 뒤 확정해주세요.",
        )
    if "cut_missing" in spec.review.reasons:
        raise ApiError(
            409,
            "CUT_MISSING",
            "외곽 칼선이 지정되지 않았습니다.",
            hint="외곽선을 클릭해 지정하거나 직접 그려주세요.",
        )
    if not closed:
        raise ApiError(
            409,
            "CUT_OPEN",
            "칼선이 닫혀 있지 않습니다.",
            hint="빠진 칼선 구간을 지정하거나 외곽선을 직접 그려주세요.",
        )
    for p in spec.paths:
        if p.status == "auto":
            p.status = "confirmed"
    spec.structure_confirmed = True
    spec.review.required = False
    spec.review.reasons = []
    specs.save(pid, spec)
    repo.update("projects", pid, status="rendering", updated_at=repo.now())
    job = runner.create(pid, "render")
    runner.submit(job, pipeline.run_render)
    return JobRef(job_id=job["id"])


@router.get("/{pid}/frame", response_model=FrameOut)
def get_frame(pid: str, margin: int | None = None) -> FrameOut:
    """Page-space rectangle covered by flat renders, so overlays line up with the PDF."""
    spec = specs.load(repo.project_or_404(pid))
    m = FLAT_LOOK.lighting.margin if margin is None else margin
    _, crop = frame(spec, 1000, m)
    return FrameOut(origin=(crop[0], crop[1]), size=(crop[2] - crop[0], crop[3] - crop[1]))
