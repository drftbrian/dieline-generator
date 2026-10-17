"""Load/save the specification with optimistic versioning."""

from __future__ import annotations

from app.errors import ApiError
from app.spec.models import Specification
from app.storage import repo


def load(project: dict) -> Specification:
    if not project.get("spec_json"):
        raise ApiError(
            409,
            "SPEC_NOT_READY",
            "패키지 구조 분석이 아직 끝나지 않았습니다.",
            hint="분석이 끝날 때까지 기다려주세요.",
        )
    spec = Specification.model_validate(project["spec_json"])
    spec.version = project["spec_version"]
    return spec


def save(pid: str, spec: Specification, expected_version: int | None = None) -> Specification:
    project = repo.project_or_404(pid)
    if expected_version is not None and expected_version != project["spec_version"]:
        raise ApiError(
            409,
            "SPEC_CONFLICT",
            "다른 곳에서 먼저 변경되었습니다.",
            hint="최신 내용을 불러온 뒤 다시 시도해주세요.",
            details={"current_version": project["spec_version"]},
        )
    spec.version = project["spec_version"] + 1
    repo.update(
        "projects",
        pid,
        spec_json=spec.model_dump(mode="json"),
        spec_version=spec.version,
        updated_at=repo.now(),
    )
    return spec
