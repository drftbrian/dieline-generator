"""Background jobs with per-stage status.

Jobs run in a thread pool inside the API process. The DB row is the source of truth, so the
API contract (``GET /api/jobs/:id``) stays the same if this moves to a separate worker.
"""

from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait

from app.errors import ApiError
from app.storage import repo

log = logging.getLogger(__name__)
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="job")
_running: set[Future] = set()
_lock = threading.Lock()

STAGES = {
    "analyze": ["validate", "preview", "extract", "separations", "structure", "render"],
    "render": ["layers", "render"],
    "generate": ["render", "model", "composite", "verify"],
    "merge": ["prepare", "model", "composite", "verify"],
    "enhance": ["prepare", "model", "register", "extract", "composite", "verify"],
    "finish": ["compose", "model", "verify"],
}


class Cancelled(Exception):
    pass


class SkipRest(Exception):
    """Stop the job successfully, marking remaining stages skipped (e.g. review needed)."""


class JobContext:
    def __init__(self, job: dict):
        self.id = job["id"]
        self.project_id = job["project_id"]
        self.type = job["type"]
        self.stages = job["stages"]

    def _save(self, **extra) -> None:
        done = sum(1 for s in self.stages if s["status"] in ("done", "skipped", "failed"))
        repo.update(
            "jobs",
            self.id,
            stages=self.stages,
            progress=round(done / len(self.stages), 3),
            updated_at=repo.now(),
            **extra,
        )

    def stage(self, key: str, status: str, summary: dict | None = None, message: str | None = None):
        for s in self.stages:
            if s["key"] == key:
                s["status"] = status
                if summary is not None:
                    s["summary"] = summary
                if message is not None:
                    s["message"] = message
        self._save()

    def check_cancel(self) -> None:
        row = repo.get("jobs", self.id)
        if row and row["cancel_requested"]:
            raise Cancelled()


def create(project_id: str, type_: str) -> dict:
    job = {
        "id": repo.new_id("job"),
        "project_id": project_id,
        "type": type_,
        "status": "pending",
        "progress": 0.0,
        "stages": [{"key": k, "status": "pending"} for k in STAGES[type_]],
        "result": None,
        "error": None,
        "cancel_requested": 0,
        "created_at": repo.now(),
        "updated_at": repo.now(),
    }
    repo.insert("jobs", job)
    return job


def submit(job: dict, fn: Callable[[JobContext], dict | None]) -> None:
    ctx = JobContext(job)

    def run():
        repo.update("jobs", ctx.id, status="running", updated_at=repo.now())
        try:
            result = fn(ctx)
            for s in ctx.stages:
                if s["status"] in ("pending", "running"):
                    s["status"] = "skipped"
            ctx._save(status="done", result=result or {})
        except SkipRest as e:
            for s in ctx.stages:
                if s["status"] in ("pending", "running"):
                    s["status"] = "skipped"
            ctx._save(status="done", result=e.args[0] if e.args else {})
        except Cancelled:
            ctx._save(status="cancelled")
        except ApiError as e:
            _fail(ctx, e.body.model_dump())
        except Exception as e:  # noqa: BLE001 - surface as a job error, keep the process alive
            log.error("job %s failed: %s", ctx.id, traceback.format_exc())
            _fail(
                ctx,
                {
                    "code": "JOB_FAILED",
                    "message": "처리 중 오류가 발생했습니다.",
                    "hint": "다시 시도해주세요.",
                    "details": {"error": str(e)[:300]},
                },
            )

    fut = _pool.submit(run)
    with _lock:
        _running.add(fut)
    fut.add_done_callback(_forget)


def _forget(fut: Future) -> None:
    with _lock:
        _running.discard(fut)


def drain(timeout: float = 120) -> None:
    """Wait for submitted jobs to finish (tests: no job may outlive its data directory)."""
    with _lock:
        pending = list(_running)
        _running.clear()
    wait(pending, timeout=timeout)


def _fail(ctx: JobContext, error: dict) -> None:
    for s in ctx.stages:
        if s["status"] == "running":
            s["status"] = "failed"
            s["message"] = error.get("message")
    ctx._save(status="failed", error=error)


def active_count(*types: str) -> int:
    marks = ", ".join("?" for _ in types)
    rows = repo.query(
        f"SELECT COUNT(*) AS n FROM jobs WHERE type IN ({marks}) "
        "AND status IN ('pending', 'running')",
        list(types),
    )
    return rows[0]["n"]


INTERRUPTED = (
    '{"code": "JOB_INTERRUPTED", "message": "서버가 재시작되어 작업이 중단되었습니다.", '
    '"hint": "다시 시도해주세요.", "details": {}}'
)


def reap_orphans() -> None:
    """Jobs left running by a previous process can never finish; mark them failed, and the
    versions and reference readings they were producing too (otherwise they show as
    "generating" forever)."""
    repo.execute(
        "UPDATE jobs SET status = 'failed', error = ? WHERE status IN ('pending', 'running')",
        [INTERRUPTED],
    )
    repo.execute(
        "UPDATE versions SET status = 'failed', error_json = ? WHERE status = 'running'",
        [INTERRUPTED],
    )
    repo.execute("UPDATE refs SET analysis_status = 'failed' WHERE analysis_status = 'pending'")
