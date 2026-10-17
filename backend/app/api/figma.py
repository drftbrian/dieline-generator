"""Import a package frame by Figma link (step 1)."""

from __future__ import annotations

import hashlib
import json
import logging

from fastapi import APIRouter, Request

from app.api.deps import idempotent_replay, project_out, remember
from app.api.schemas import FigmaImportIn, FigmaStatus, SourceOut, UploadOut
from app.config import get_settings
from app.figma import client as figma
from app.figma.layers import extract_content, extract_shapes, summarize
from app.finishing import assets as finishing_assets
from app.jobs import runner
from app.pdf.validate import validate_pdf
from app.services import pipeline
from app.storage import repo

log = logging.getLogger(__name__)
router = APIRouter(tags=["figma"])


@router.get("/figma/status", response_model=FigmaStatus)
def status() -> FigmaStatus:
    return FigmaStatus(configured=figma.configured())


def _import(link: figma.FigmaLink) -> UploadOut:
    frame = figma.fetch_frame(link)
    data = figma.export_pdf(link)
    info = validate_pdf(data, get_settings().max_upload_mb)
    shapes = extract_shapes(frame.document)

    pid = repo.new_id("prj")
    title = frame.node_name or frame.file_name or "Figma"
    figma_json = {
        "url": figma.frame_url(link),
        "file_key": link.file_key,
        "node_id": link.node_id,
        "file_name": frame.file_name,
        "node_name": frame.node_name,
        "version": frame.version,
        "last_modified": frame.last_modified,
        "layers": summarize(shapes),
    }
    source = SourceOut(
        filename=f"{frame.node_name or 'figma'}.pdf",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        page_count=info.page_count,
        width_mm=round(info.width_pt * 25.4 / 72, 1),
        height_mm=round(info.height_pt * 25.4 / 72, 1),
        uploaded_at=repo.now(),
    )
    repo.insert(
        "projects",
        {
            "id": pid,
            "name": title,
            "status": "analyzing",
            "source_json": source.model_dump(),
            "spec_json": None,
            "spec_version": 0,
            "error_json": None,
            "figma_json": figma_json,
            "created_at": repo.now(),
            "updated_at": repo.now(),
        },
    )
    repo.write_source_once(pid, data)
    (repo.project_dir(pid) / "figma_shapes.json").write_text(json.dumps(shapes))
    (repo.project_dir(pid) / "figma_content.json").write_text(
        json.dumps(extract_content(frame.document), ensure_ascii=False)
    )
    try:  # selectable assets for finishing; rebuilt on demand if this fails
        finishing_assets.save_tree(pid, frame.document)
    except Exception:  # noqa: BLE001 - never block an import on the finishing tree
        log.warning("finishing asset tree not saved for %s", pid, exc_info=True)
    job = runner.create(pid, "analyze")
    runner.submit(job, lambda ctx: pipeline.run_analyze(ctx, None))
    return UploadOut(project=project_out(repo.project_or_404(pid)), job_id=job["id"])


@router.post("/projects/figma", response_model=UploadOut, status_code=202)
def import_from_figma(body: FigmaImportIn, request: Request):
    if replay := idempotent_replay(request, "figma_import"):
        return replay
    out = _import(figma.parse_link(body.url))
    remember(request, "figma_import", 202, out.model_dump(mode="json"))
    return out
