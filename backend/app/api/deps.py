"""Shared helpers for routers: serializers and idempotency."""

from __future__ import annotations

import json

from fastapi import Request
from fastapi.responses import JSONResponse

from app.ai.models import IMAGE_MODEL
from app.api.schemas import (
    EnhancementOut,
    FinishedOut,
    ProjectOut,
    ReferenceAnalysis,
    ReferenceOut,
    SourceOut,
    VersionOut,
)
from app.errors import ErrorBody
from app.services.merge import REFERENCE_SCHEMA, is_stale
from app.services.pipeline import PIPELINE
from app.storage import repo


def project_out(p: dict) -> ProjectOut:
    pid = p["id"]
    versions = repo.query(
        "SELECT number, starred, status, id FROM versions WHERE project_id = ? AND deleted_at IS NULL "
        "ORDER BY number DESC",
        [pid],
    )
    job = repo.query(
        "SELECT id FROM jobs WHERE project_id = ? AND type IN ('analyze', 'render') "
        "AND status IN ('pending', 'running') ORDER BY created_at DESC LIMIT 1",
        [pid],
    )
    thumb = None
    pdir = repo.project_dir(pid)
    if (
        (pdir / "flat.jpg").exists()
        or (pdir / "thumb.jpg").exists()
        or any(v["status"] == "done" for v in versions)
    ):
        thumb = f"/api/projects/{pid}/thumbnail?v={p['updated_at']}"
    return ProjectOut(
        id=pid,
        name=p["name"],
        status=p["status"],
        source=SourceOut(**p["source_json"]) if p.get("source_json") else None,
        spec_version=p["spec_version"],
        thumbnail_url=thumb,
        version_count=len(versions),
        latest_version=versions[0]["number"] if versions else None,
        active_job_id=job[0]["id"] if job else None,
        figma=(
            {
                **p["figma_json"],
                "content_ready": (repo.project_dir(pid) / "figma_content.json").exists(),
            }
            if p.get("figma_json")
            else None
        ),
        error=ErrorBody(**p["error_json"]) if p.get("error_json") else None,
        created_at=p["created_at"],
        updated_at=p["updated_at"],
    )


def reference_out(r: dict) -> ReferenceOut:
    pid, rid = r["project_id"], r["id"]
    analysis = r.get("analysis_json") or {}
    current = analysis.get("schema") == REFERENCE_SCHEMA
    return ReferenceOut(
        id=rid,
        filename=r["filename"],
        width=r["width"],
        height=r["height"],
        analysis_status="stale" if is_stale(r) else r["analysis_status"],
        analysis=ReferenceAnalysis.model_validate(analysis) if current else None,
        image_url=f"/api/projects/{pid}/references/{rid}/image",
        thumb_url=f"/api/projects/{pid}/references/{rid}/thumb",
        created_at=r["created_at"],
    )


def is_legacy(v: dict) -> bool:
    """Made before the 3-step app: another provider, a scene mockup, another look."""
    return (v.get("settings_json") or {}).get("pipeline") != PIPELINE


def version_out(v: dict) -> VersionOut:
    pid, vid = v["project_id"], v["id"]
    done = v["status"] == "done"
    params = v.get("scene_json") or {}
    kind = "merge" if v.get("kind") in ("merge", "scene") else "flat"  # scene: old mockups
    model = IMAGE_MODEL if v["provider"] == IMAGE_MODEL.provider else None
    settings = v.get("settings_json") or {}
    image = f"/api/projects/{pid}/versions/{vid}/image"
    return VersionOut(
        id=vid,
        number=v["number"],
        kind=kind,
        legacy=is_legacy(v),
        status=v["status"],
        provider_label=(
            "구조 합성 · 코드 렌더"
            if settings.get("merge_mode") == "structural" and not settings.get("harmonize")
            else f"{model.label} · 구조 합성 AI 조화"
            if model and settings.get("merge_mode") == "structural"
            else "후가공 · 코드 렌더"
            if settings.get("flat_mode") == "finished" and not settings.get("ai")
            else f"{model.label} · 후가공 AI 사실감"
            if model and settings.get("flat_mode") == "finished"
            else "코드 렌더 (AI 없음)"
            if settings.get("flat_mode") == "deterministic"
            else f"{model.label} · AI 재질 보정"
            if model and settings.get("flat_mode") == "ai_material"
            else model.label
            if model
            else f"{v['provider']} (legacy)"
        ),
        model_id=v["model_id"],
        flat_version_id=v.get("flat_version_id") if kind == "merge" else None,
        reference_id=params.get("reference_id") if kind == "merge" else None,
        form=params.get("form") if kind == "merge" else None,
        enhancement=EnhancementOut(
            source_version_id=settings["source_version_id"],
            strength=settings["strength"],
            reference_id=settings.get("reference_id"),
            maps_from=settings.get("maps_from"),
            phase=settings.get("phase", 1),
            source_image_url=f"/api/projects/{pid}/versions/{settings['source_version_id']}/image",
            user_prompt=settings.get("user_prompt"),
            spec=settings.get("spec"),
            notes=settings.get("notes") or [],
        )
        if settings.get("flat_mode") == "ai_material"
        else None,
        finishing=FinishedOut(
            source_version_id=settings["source_version_id"],
            finishing_revision=settings["finishing_revision"],
            ai=bool(settings.get("ai")),
            strength=settings.get("strength", 0.0),
            source_image_url=f"/api/projects/{pid}/versions/{settings['source_version_id']}/image",
        )
        if settings.get("flat_mode") == "finished"
        else None,
        verify=v.get("verify_json"),
        frame=v.get("frame_json"),
        error=ErrorBody(**v["error_json"]) if v.get("error_json") else None,
        job_id=v["job_id"],
        image_url=image if done else None,
        thumb_url=f"/api/projects/{pid}/versions/{vid}/thumb" if done else None,
        download_url=f"{image}?download=1" if done else None,
        created_at=v["created_at"],
    )


def idempotent_replay(request: Request, scope: str) -> JSONResponse | None:
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None
    rows = repo.query("SELECT * FROM idempotency WHERE key = ? AND scope = ?", [key, scope])
    if rows:
        return JSONResponse(status_code=rows[0]["status"], content=rows[0]["body"])
    return None


def remember(request: Request, scope: str, status: int, body: dict) -> None:
    key = request.headers.get("Idempotency-Key")
    if key:
        repo.execute(
            "INSERT OR IGNORE INTO idempotency (key, scope, status, body, created_at) VALUES (?, ?, ?, ?, ?)",
            [key, scope, status, json.dumps(body, ensure_ascii=False), repo.now()],
        )
