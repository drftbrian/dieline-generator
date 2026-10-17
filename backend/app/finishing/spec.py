"""The finishing specification: non-destructive, versioned project data, never written into the
Figma source or the render.

Stored next to the project as ``finishing.json`` (current) and ``finishing/rev-<n>.json`` (every
saved revision, for reload, render provenance and history). A save names the revision it was
edited from; a stale base is a conflict, never a silent overwrite.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.errors import ApiError
from app.finishing import catalog
from app.storage import repo

SCHEMA = 1
FILE = "finishing.json"
REV_DIR = "finishing"


class Target(BaseModel):
    kind: Literal["asset", "panel", "sheet"]
    id: str | None = None  # asset (Figma node / pdf object) or panel id; None for the sheet
    # Reserved: character range inside a text asset. Not offered until glyph-level masks exist.
    range: tuple[int, int] | None = None


class Assignment(BaseModel):
    id: str = Field(default_factory=lambda: "fin_" + secrets.token_hex(5))
    finish: str  # catalogue id, e.g. "foil.gold"
    targets: list[Target]
    params: dict[str, float] = {}
    order: int = 0  # stack order within its layer (render/finishing decides the layer)
    enabled: bool = True
    created_at: str | None = None
    updated_at: str | None = None


class FinishingSpec(BaseModel):
    schema_version: int = Field(SCHEMA, alias="schema")
    revision: int = 0
    assignments: list[Assignment] = []
    updated_at: str | None = None

    model_config = {"populate_by_name": True}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def migrate(data: dict) -> dict:
    """Bring stored data up to SCHEMA (no older schema exists yet)."""
    data.setdefault("schema", SCHEMA)
    return data


def load(pid: str) -> FinishingSpec:
    path = repo.project_dir(pid) / FILE
    if not path.exists():
        return FinishingSpec()
    return FinishingSpec.model_validate(migrate(json.loads(path.read_text())))


def load_revision(pid: str, revision: int) -> FinishingSpec:
    if revision == 0:
        return FinishingSpec()
    path = repo.project_dir(pid) / REV_DIR / f"rev-{revision}.json"
    if not path.exists():
        raise ApiError(404, "FINISHING_REVISION_NOT_FOUND", "후가공 저장 기록을 찾을 수 없습니다.")
    return FinishingSpec.model_validate(migrate(json.loads(path.read_text())))


def validate(
    assignments: list[Assignment], assets: list[dict], panel_ids: set[str]
) -> list[Assignment]:
    """Check each assignment against the catalogue and the project; clamp parameters."""
    by_id = {a["id"]: a for a in assets}
    seen: set[str] = set()
    out = []
    for a in assignments:
        if a.id in seen:
            raise ApiError(422, "FINISHING_DUPLICATE_ID", "같은 후가공 항목이 두 번 있습니다.")
        seen.add(a.id)
        try:
            f = catalog.finish(a.finish)
        except KeyError:
            raise ApiError(
                422, "FINISH_UNKNOWN", "알 수 없는 후가공입니다.", details={"finish": a.finish}
            ) from None
        if not f.available:
            raise ApiError(
                422, "FINISH_UNAVAILABLE", f"'{f.label_ko}'은(는) 아직 제공하지 않습니다."
            )
        if not a.targets:
            raise ApiError(422, "FINISHING_NO_TARGET", "후가공을 적용할 대상이 없습니다.")
        for t in a.targets:
            if t.range is not None:
                raise ApiError(
                    422, "FINISHING_RANGE_UNSUPPORTED", "글자 단위 선택은 아직 지원하지 않습니다."
                )
            if t.kind == "asset":
                if f.scope == "surface":
                    raise ApiError(
                        422,
                        "FINISHING_SCOPE",
                        f"'{f.label_ko}'은(는) 전체 시트나 패널에 적용하는 후가공입니다.",
                    )
                asset = by_id.get(t.id or "")
                if asset is None or not asset.get("selectable"):
                    raise ApiError(
                        422,
                        "FINISHING_TARGET_INVALID",
                        "선택할 수 없는 요소가 대상에 있습니다.",
                        details={"target": t.id},
                    )
            else:
                if f.scope == "selective":
                    raise ApiError(
                        422,
                        "FINISHING_SCOPE",
                        f"'{f.label_ko}'은(는) 선택한 요소에 적용하는 후가공입니다.",
                    )
                if t.kind == "panel" and t.id not in panel_ids:
                    raise ApiError(
                        422,
                        "FINISHING_TARGET_INVALID",
                        "없는 패널이 대상에 있습니다.",
                        details={"target": t.id},
                    )
        out.append(a.model_copy(update={"params": catalog.clamp_params(a.finish, a.params)}))
    return out


def save(pid: str, base_revision: int, assignments: list[Assignment]) -> FinishingSpec:
    current = load(pid)
    if base_revision != current.revision:
        raise ApiError(
            409,
            "FINISHING_CONFLICT",
            "다른 곳에서 후가공이 바뀌었습니다.",
            hint="최신 상태를 불러온 뒤 다시 적용해주세요.",
            details={"current_revision": current.revision},
        )
    now = _now()
    before = {a.id: a for a in current.assignments}
    stamped = []
    for a in assignments:
        old = before.get(a.id)
        created = old.created_at if old else (a.created_at or now)
        changed = old is None or old.model_dump(
            exclude={"created_at", "updated_at"}
        ) != a.model_dump(exclude={"created_at", "updated_at"})
        updated = now if changed else (old.updated_at if old else now)
        stamped.append(a.model_copy(update={"created_at": created, "updated_at": updated}))
    spec = FinishingSpec(revision=current.revision + 1, assignments=stamped, updated_at=now)
    data = spec.model_dump(by_alias=True)
    d = repo.project_dir(pid)
    (d / REV_DIR).mkdir(exist_ok=True)
    (d / REV_DIR / f"rev-{spec.revision}.json").write_text(json.dumps(data, ensure_ascii=False))
    (d / FILE).write_text(json.dumps(data, ensure_ascii=False))
    return spec
