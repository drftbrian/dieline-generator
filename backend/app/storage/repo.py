"""Data access. Rows go in and out as plain dicts; JSON columns are decoded on read."""

from __future__ import annotations

import json
import secrets
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.errors import ApiError
from app.storage.db import connect

JSON_COLS = {
    "source_json",
    "spec_json",
    "error_json",
    "figma_json",
    "analysis_json",
    "stages",
    "result",
    "error",
    "settings_json",
    "reference_ids",
    "usage_json",
    "verify_json",
    "frame_json",
    "scene_json",
    "body",
}


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in JSON_COLS & d.keys():
        if d[k] is not None:
            d[k] = json.loads(d[k])
    return d


def _enc(v: Any) -> Any:
    return json.dumps(v, ensure_ascii=False) if isinstance(v, dict | list) else v


def db():
    return connect(get_settings().db_path)


def insert(table: str, row: dict) -> dict:
    cols = ", ".join(row)
    qs = ", ".join("?" for _ in row)
    with db() as c:
        c.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", [_enc(v) for v in row.values()])
    return row


def update(table: str, id_: str, **fields) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with db() as c:
        c.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*map(_enc, fields.values()), id_])


def get(table: str, id_: str) -> dict | None:
    with db() as c:
        return _row(c.execute(f"SELECT * FROM {table} WHERE id = ?", [id_]).fetchone())


def query(sql: str, args: list | tuple = ()) -> list[dict]:
    with db() as c:
        return [_row(r) for r in c.execute(sql, args).fetchall()]  # type: ignore[misc]


def execute(sql: str, args: list | tuple = ()) -> None:
    with db() as c:
        c.execute(sql, args)


def project_or_404(pid: str) -> dict:
    p = get("projects", pid)
    if p is None:
        raise ApiError(
            404,
            "PROJECT_NOT_FOUND",
            "프로젝트를 찾을 수 없습니다.",
            hint="프로젝트 목록에서 다시 선택해주세요.",
        )
    return p


# ---- files ---------------------------------------------------------------------------


def project_dir(pid: str) -> Path:
    d = get_settings().projects_dir / pid
    d.mkdir(parents=True, exist_ok=True)
    return d


def source_path(pid: str) -> Path:
    return project_dir(pid) / "source.pdf"


def read_source(pid: str) -> bytes:
    p = source_path(pid)
    if not p.exists():
        raise ApiError(
            409,
            "SOURCE_MISSING",
            "원본 PDF가 아직 업로드되지 않았습니다.",
            hint="PDF를 먼저 업로드해주세요.",
        )
    return p.read_bytes()


def write_source_once(pid: str, data: bytes) -> None:
    """The original is immutable: written once, then made read-only."""
    p = source_path(pid)
    if p.exists():
        raise ApiError(
            409,
            "SOURCE_EXISTS",
            "이 프로젝트에는 이미 원본 PDF가 있습니다.",
            hint="다른 PDF는 새 프로젝트로 업로드해주세요.",
        )
    p.write_bytes(data)
    p.chmod(0o444)


def remove_project_files(pid: str) -> None:
    d = get_settings().projects_dir / pid
    if d.exists():
        for f in d.rglob("*"):
            f.chmod(0o644) if f.is_file() else None
        shutil.rmtree(d)


def copy_project_files(src: str, dst: str, include: list[str]) -> None:
    s, d = project_dir(src), project_dir(dst)
    for name in include:
        sp = s / name
        if sp.is_dir():
            shutil.copytree(sp, d / name, dirs_exist_ok=True)
        elif sp.exists():
            shutil.copy2(sp, d / name)
            (d / name).chmod(0o444 if name == "source.pdf" else 0o644)
