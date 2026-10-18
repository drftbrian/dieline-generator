"""Step 3, photo-first mode: an AI-generated product photo corrected with Figma's own lettering.

1. **Candidate:** the user brings a generated photo (Flora, Gemini...). It is stored byte for
   byte (``candidates/<cid><ext>``) and never changed; nothing about it is read by a model.
2. **Faces:** which of our panels are visible, each with the rough corners of its face in the
   photo (fractions of the image), confirmed or dragged by the user.
3. **Correction job** (``run_typography``): registration, verification against the Figma
   typography manifest, the text-corrected and strict composites (``app.typography``).
   The text-corrected image is the version; the raw copy, the strict output, the repair
   preview and the masks are saved beside it, with the full report.

No model is called anywhere in this mode.
"""

from __future__ import annotations

import io
import json
import time

import numpy as np
from PIL import Image, UnidentifiedImageError

from app.config import get_settings
from app.errors import ApiError
from app.finishing import assets as fa
from app.jobs.runner import JobContext
from app.render.layers import make_artwork_pdf, structure_key
from app.services import merge, pipeline, specs
from app.spec.models import Panel, Specification
from app.storage import repo
from app.typography import correct, manifest

ALLOWED = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}
MAX_CANDIDATES = 12
MAX_FACES = 3
MAIN_PANEL = 0.25  # a panel at least this share of the largest one can be a visible face
MAX_PIXELS = 40_000_000  # larger photos are refused (memory and time)


# ---- the Figma source -----------------------------------------------------------------------


def source(pid: str, spec: Specification) -> tuple[dict, bytes]:
    """The typography manifest and the artwork PDF whose embedded outlines are drawn."""
    _kind, assets = fa.project_assets(pid, spec)
    art = repo.project_dir(pid) / f"artwork-{structure_key(spec)}.pdf"
    pdf = art.read_bytes() if art.exists() else make_artwork_pdf(repo.read_source(pid), spec)
    vfile = repo.project_dir(pid) / "figma_assets.version"
    man = manifest.build(
        spec,
        assets,
        pdf,
        lambda i: fa.svg_path(pid, i).exists(),
        vfile.read_text().strip() if vfile.exists() else None,
    )
    man["source_kind"] = _kind
    return man, pdf


def main_panels(spec: Specification) -> list[Panel]:
    """The panels that can be a visible face of the closed carton (not flaps)."""
    if not spec.panels:
        return []
    biggest = max(p.area_pt2 or p.area_mm2 for p in spec.panels)
    return [p for p in spec.panels if (p.area_pt2 or p.area_mm2) >= MAIN_PANEL * biggest]


def default_faces(spec: Specification) -> list[dict]:
    """A starting guess for a three-quarter product shot: the front, and the side panel to its
    left. Corners are only a start; the user drags them, the job refines them."""
    panels = main_panels(spec)
    if not panels:
        return []
    front = next((p for p in panels if p.name == "앞면"), None) or max(
        panels, key=lambda p: p.area_pt2 or p.area_mm2
    )
    faces = [{"panel": front.id, "quad": [[0.45, 0.22], [0.78, 0.24], [0.78, 0.82], [0.45, 0.86]]}]
    left = [
        p
        for p in panels
        if p.id != front.id and abs(p.bbox[2] - front.bbox[0]) < 8 and p.bbox[3] > front.bbox[1]
    ]
    if left:
        faces.insert(0, {"panel": left[0].id, "quad": [[0.24, 0.22], [0.45, 0.22], [0.45, 0.86], [0.24, 0.82]]})
    return faces


# ---- candidates -----------------------------------------------------------------------------


def _dir(pid: str):
    d = repo.project_dir(pid) / "candidates"
    d.mkdir(exist_ok=True)
    return d


def _meta_path(pid: str, cid: str):
    return _dir(pid) / f"{cid}.json"


def get_candidate(pid: str, cid: str) -> dict:
    p = _meta_path(pid, cid) if cid.startswith("cand_") else None
    if p is None or not p.exists():
        raise ApiError(404, "CANDIDATE_NOT_FOUND", "AI 사진을 찾을 수 없습니다.")
    return json.loads(p.read_text())


def list_candidates(pid: str) -> list[dict]:
    out = [json.loads(p.read_text()) for p in _dir(pid).glob("cand_*.json")]
    return sorted(out, key=lambda c: c["created_at"])


def image_path(pid: str, cand: dict):
    return _dir(pid) / f"{cand['id']}{cand['ext']}"


def add_candidate(pid: str, spec: Specification, filename: str, data: bytes) -> dict:
    if len(list_candidates(pid)) >= MAX_CANDIDATES:
        raise ApiError(
            409,
            "CANDIDATE_LIMIT",
            f"AI 사진은 최대 {MAX_CANDIDATES}개까지 올릴 수 있습니다.",
            hint="기존 사진을 삭제한 뒤 추가해주세요.",
        )
    limit = get_settings().max_reference_mb
    if len(data) > limit * 1024 * 1024:
        raise ApiError(413, "CANDIDATE_TOO_LARGE", f"이미지가 {limit}MB를 넘습니다.", hint="더 작은 이미지를 사용해주세요.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ApiError(400, "CANDIDATE_INVALID", "이미지를 읽을 수 없습니다.", hint="PNG, JPEG, WebP 파일만 지원합니다.") from e
    if img.format not in ALLOWED:
        raise ApiError(400, "CANDIDATE_FORMAT", "지원하지 않는 이미지 형식입니다.", hint="PNG, JPEG, WebP 파일만 지원합니다.")
    if img.width * img.height > MAX_PIXELS:
        raise ApiError(413, "CANDIDATE_TOO_LARGE", "이미지 해상도가 너무 큽니다.", hint="4000만 화소 이하로 줄여주세요.")
    cid = repo.new_id("cand")
    cand = {
        "id": cid,
        "filename": filename or "photo",
        "ext": ALLOWED[img.format],
        "width": img.width,
        "height": img.height,
        "faces": default_faces(spec),
        "created_at": repo.now(),
    }
    (_dir(pid) / f"{cid}{cand['ext']}").write_bytes(data)  # the raw photo, byte for byte
    thumb = img.convert("RGB")
    thumb.thumbnail((320, 320))
    thumb.save(_dir(pid) / f"{cid}_thumb.jpg", "JPEG", quality=85)
    _meta_path(pid, cid).write_text(json.dumps(cand, ensure_ascii=False))
    return cand


def validate_faces(spec: Specification, faces: list[dict]) -> list[dict]:
    ids = {p.id for p in main_panels(spec)}
    if not faces:
        raise ApiError(422, "FACES_EMPTY", "보이는 면을 하나 이상 지정해주세요.")
    if len(faces) > MAX_FACES:
        raise ApiError(422, "FACES_TOO_MANY", f"보이는 면은 최대 {MAX_FACES}개까지 지정할 수 있습니다.")
    seen = set()
    out = []
    for f in faces:
        pid_ = f.get("panel")
        q = f.get("quad") or []
        if pid_ not in ids:
            raise ApiError(422, "FACE_PANEL_INVALID", "전개도의 면이 아닙니다.", details={"panel": pid_})
        if pid_ in seen:
            raise ApiError(422, "FACE_PANEL_DUPLICATE", "같은 면을 두 번 지정했습니다.", details={"panel": pid_})
        if len(q) != 4 or any(
            not isinstance(c, list | tuple) or len(c) != 2 or not all(-0.5 <= float(v) <= 1.5 for v in c) for c in q
        ):
            raise ApiError(422, "FACE_QUAD_INVALID", "면마다 꼭짓점 4개가 필요합니다.", details={"panel": pid_})
        seen.add(pid_)
        out.append({"panel": pid_, "quad": [[round(float(x), 5), round(float(y), 5)] for x, y in q]})
    return out


def save_faces(pid: str, cid: str, spec: Specification, faces: list[dict]) -> dict:
    cand = get_candidate(pid, cid)
    cand["faces"] = validate_faces(spec, faces)
    _meta_path(pid, cid).write_text(json.dumps(cand, ensure_ascii=False))
    return cand


def delete_candidate(pid: str, cid: str) -> None:
    cand = get_candidate(pid, cid)
    for p in (image_path(pid, cand), _dir(pid) / f"{cid}_thumb.jpg", _meta_path(pid, cid)):
        p.unlink(missing_ok=True)


# ---- the correction job ---------------------------------------------------------------------


def _png(a: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8))


def run_typography(ctx: JobContext, vid: str) -> dict:
    pid = ctx.project_id
    version = repo.get("versions", vid)
    params = version.get("scene_json") or {}
    cand = get_candidate(pid, params["candidate_id"])
    spec = specs.load(repo.project_or_404(pid))
    vdir = repo.project_dir(pid) / "versions"
    vdir.mkdir(exist_ok=True)
    t0 = time.time()

    ctx.stage("register", "running")
    man, pdf = source(pid, spec)
    photo = np.asarray(Image.open(image_path(pid, cand)).convert("RGB"), np.float32) / 255
    h, w = photo.shape[:2]
    faces = [
        {"panel": f["panel"], "quad": [[x * w, y * h] for x, y in f["quad"]]} for f in params["faces"]
    ]
    ctx.stage("register", "done", {"faces": len(faces), "items": len(man["items"])})
    ctx.check_cancel()

    ctx.stage("verify", "running")
    result = correct.correct_photo(photo, pdf, spec.panels, man["items"], faces)
    ctx.stage("verify", "done", {"registered": result.registered, "status": result.status})
    ctx.check_cancel()

    ctx.stage("correct", "running")
    raw = Image.open(image_path(pid, cand)).convert("RGB")
    raw.save(vdir / f"{vid}_raw.png")
    _png(result.strict).save(vdir / f"{vid}_layer_strict.png")
    _png(result.masks).save(vdir / f"{vid}_layer_repair_masks.png")
    result.preview.save(vdir / f"{vid}_layer_repair_preview.png")
    report = {
        **result.report(),
        "candidate_id": cand["id"],
        "verification": result.verification(),
        "manifest": {"items": len(man["items"]), "unresolved": man["unresolved"], "source_kind": man["source_kind"]},
        "seconds": round(time.time() - t0, 1),
        "no_model_calls": True,
    }
    (vdir / f"{vid}_report.json").write_text(json.dumps(report, ensure_ascii=False, default=float))
    ctx.stage("correct", "done", {"seconds": report["seconds"]})

    ctx.stage("save", "running")
    if not result.registered:
        raise ApiError(
            422,
            "TYPOGRAPHY_NOT_REGISTERED",
            "사진에서 전개도의 면을 찾지 못했습니다. 원본 사진은 그대로 두었어요.",
            hint="면 선택과 꼭짓점 위치를 확인한 뒤 다시 시도해주세요.",
            details={"review": result.review},
        )
    image = (np.clip(result.corrected, 0, 1) * 255 + 0.5).astype(np.uint8)
    changed = result.masks.max(-1) > 0.5
    check = {
        "match": True,  # registered; anything left to review is listed, never hidden
        "protected_px": int((~changed).sum()),
        "changed_px": int(changed.sum()),
        "changed_ratio": round(float(changed.mean()), 4),
        "typography": {
            "status": result.status,
            "review": result.review,
            "faces": report["faces"],
            "background": result.background,
        },
    }
    pipeline.deliver(pid, vid, image, check, frame_json=merge._canvas_frame(spec, w, h))
    ctx.stage("save", "done")
    return {"version_id": vid}
