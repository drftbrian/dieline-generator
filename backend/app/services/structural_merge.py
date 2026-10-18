"""Step 3, structural mode: our folded carton in place of every package of a reference photo.

Order (deterministic first, AI second):
1. **Structure:** the confirmed dieline is folded (``structure.topology`` / ``carton`` /
   ``fold``). An unsupported structure stops here; nothing is invented.
2. **Instances:** one per package of the reference, each the image quad of its most visible face.
   Claude proposes them (``detect``), the user confirms or edits them (``save_scene``), and
   they are stored per reference.
3. **Precomposition:** ``scene.compose`` places a rigid copy of our carton on each quad, maps the
   approved flat render onto it and lights it with the photo's light. The reference packages
   are removed and the ground is re-shadowed. It is saved on its own.
4. **Optional AI** (Gemini):
   - **Removal:** a better fill where the old packages stood, used only inside their mask and
     dropped if it looks like a new object.
   - **Harmonization:** only a smooth, bounded, achromatic light map on our cartons, and the
     model's ground inside the removal mask. Never our print, silhouette, pose or framing.
5. **Verify:** ``verify_structural`` (exact print × light, no print in the light, ours or the
   reference's). A failed AI pass falls back to the deterministic precomposition; it never
   fails the version.
"""

from __future__ import annotations

import json
import logging

import numpy as np
from PIL import Image
from scipy import ndimage

from app.ai import claude, prompts, providers
from app.ai.models import IMAGE_MODEL
from app.ai.providers.base import GenerationRequest
from app.errors import ApiError
from app.jobs.runner import Cancelled, JobContext
from app.scene import compose as sc
from app.services import merge, pipeline, specs
from app.storage import repo
from app.structure import carton, fold, topology

log = logging.getLogger(__name__)

MAX_EDGE = 2048  # composition resolution (long edge)
MAX_INSTANCES = 8
HARMONIZE_RANGE = (0.75, 1.2)  # the model's light map on our cartons, bounded
REMOVAL_EDGE_RATIO = 2.5  # AI fill with this much more structure than its surroundings = new object


# ---- scene (instances) per reference --------------------------------------------------------


def scene_path(pid: str, rid: str):
    d = repo.project_dir(pid) / "refs"
    d.mkdir(exist_ok=True)
    return d / f"{rid}_scene.json"


def load_scene(pid: str, rid: str) -> dict:
    p = scene_path(pid, rid)
    if p.exists():
        return json.loads(p.read_text())
    return {"schema": 1, "source": None, "instances": [], "settings": {}}


def validate_scene(data: dict) -> dict:
    inst = data.get("instances") or []
    if len(inst) > MAX_INSTANCES:
        raise ApiError(
            422, "SCENE_TOO_MANY", f"패키지는 최대 {MAX_INSTANCES}개까지 배치할 수 있습니다."
        )
    for i in inst:
        q = i.get("quad") or []
        if len(q) != 4 or sum(c is None for c in q) > 1:
            raise ApiError(
                422,
                "SCENE_QUAD_INVALID",
                "패키지마다 윗면 꼭짓점 4개가 필요합니다(가려진 꼭짓점은 1개까지).",
                details={"id": i.get("id")},
            )
        for c in q:
            if c is not None and not (len(c) == 2 and all(-0.5 <= v <= 1.5 for v in c)):
                raise ApiError(
                    422, "SCENE_QUAD_INVALID", "꼭짓점 좌표가 이미지 범위를 벗어났습니다."
                )
    return data


def save_scene(pid: str, rid: str, data: dict) -> dict:
    data = validate_scene({**data, "schema": 1})
    scene_path(pid, rid).write_text(json.dumps(data, ensure_ascii=False))
    return data


def detect(pid: str, rid: str) -> dict:
    """Claude's proposal of the reference's packages (normalised quads), saved as the scene."""
    ref = repo.get("refs", rid)
    if ref is None or ref["project_id"] != pid:
        raise ApiError(404, "REFERENCE_NOT_FOUND", "레퍼런스를 찾을 수 없습니다.")
    img = Image.open(repo.project_dir(pid) / "refs" / f"{rid}.png").convert("RGB")
    found = claude.detect_instances(img)
    inst = []
    for n, a in enumerate(sorted(found.instances, key=lambda a: a.order)[:MAX_INSTANCES], start=1):
        if len(a.corners) != 4:
            continue
        quad = [[round(c.x, 4), round(c.y, 4)] if c.visible else None for c in a.corners]
        if sum(c is None for c in quad) > 1:
            quad = [[round(c.x, 4), round(c.y, 4)] for c in a.corners]
        inst.append(
            {
                "id": f"inst{n}",
                "quad": quad,
                "height": float(np.clip(a.height_ratio, 0.03, 1.5)),
                "enabled": True,
                "confidence": round(float(a.confidence), 2),
                "our_face": "front",
                "yaw_deg": 0.0,
                "offset": [0.0, 0.0],
            }
        )
    prev = load_scene(pid, rid)
    return save_scene(
        pid, rid, {"source": "claude", "instances": inst, "settings": prev.get("settings", {})}
    )


# ---- composition ----------------------------------------------------------------------------


def _structure(spec):
    top = topology.analyze(spec)
    info = carton.classify(top, spec.box)
    try:
        return fold.fold(top, info, "closed")
    except fold.FoldError as e:
        raise ApiError(
            409,
            "STRUCTURE_UNSUPPORTED",
            "이 전개도는 아직 접어서 합성할 수 없습니다.",
            hint="구조 검토에서 칼선·접는 선을 확인하거나 기존 합성 방식을 사용하세요.",
            details={"reasons": e.reasons, "code": e.code},
        ) from None


def _settings(scene: dict, reading: dict) -> sc.SceneSettings:
    s = scene.get("settings") or {}
    light = (reading or {}).get("light") or {}
    temp = light.get("temperature") or "neutral"
    return sc.SceneSettings(
        size=float(np.clip(s.get("size", 1.0), 0.3, 2.0)),
        key_azimuth=s.get("key_azimuth"),
        key_elevation=s.get("key_elevation"),
        reading_azimuth=float(light.get("key_azimuth", 45.0)),
        reading_elevation=float(light.get("key_elevation", 35.0)),
        ambient=s.get("ambient"),
        shadow_strength=float(np.clip(s.get("shadow_strength", 1.0), 0, 1)),
        light_tint=tuple(sc.LIGHT_TINTS.get(temp, sc.LIGHT_TINTS["neutral"])),
    )


def precompose(pid: str, rid: str, flat_vid: str, edge: int = MAX_EDGE, scene: dict | None = None):
    """The deterministic precomposition of a reference with the project's carton(s)."""
    spec = specs.load(repo.project_or_404(pid))
    flat = repo.get("versions", flat_vid)
    if (
        flat is None
        or flat["project_id"] != pid
        or flat["status"] != "done"
        or not flat.get("frame_json")
    ):
        raise ApiError(409, "FLAT_VERSION_MISSING", "합성할 플랫 렌더를 찾을 수 없습니다.")
    ref = repo.get("refs", rid)
    if ref is None or ref["project_id"] != pid:
        raise ApiError(404, "REFERENCE_NOT_FOUND", "레퍼런스를 찾을 수 없습니다.")
    scene = scene or load_scene(pid, rid)
    active = [i for i in scene.get("instances", []) if i.get("enabled", True)]
    if not active:
        raise ApiError(
            409,
            "SCENE_EMPTY",
            "레퍼런스에서 교체할 패키지가 없습니다.",
            hint="'패키지 찾기'를 누르거나 직접 지정해주세요.",
        )
    folded = _structure(spec)
    img = Image.open(repo.project_dir(pid) / "refs" / f"{rid}.png").convert("RGB")
    k = min(1.0, edge / max(img.size))
    w, h = max(16, round(img.width * k)), max(16, round(img.height * k))
    reference = np.asarray(img.resize((w, h), Image.LANCZOS)).astype(np.float32) / 255
    flat_img = np.asarray(merge.flat_image(pid, flat)).astype(np.float32) / 255
    instances = [
        sc.Instance(
            id=i["id"],
            quad=[None if c is None else [c[0] * w, c[1] * h] for c in i["quad"]],
            height=float(i.get("height", 0.17)),
            our_face=i.get("our_face", "front"),
            yaw_deg=float(i.get("yaw_deg", 0.0)),
            offset=tuple(i.get("offset", (0.0, 0.0))),
        )
        for i in active
    ]
    reading = merge.reference_reading(ref)
    comp = sc.compose(
        reference,
        folded,
        flat_img,
        flat["frame_json"],
        spec.scale.mm_per_pt,
        instances,
        _settings(scene, reading),
    )
    return comp, reference, scene


def _save_layers(vdir, vid: str, comp: sc.Composition) -> None:
    for name, a in comp.layers.items():
        if name == "instance_id":
            continue
        a = np.asarray(a, np.float32)
        if a.ndim == 2:
            a = np.repeat(a[..., None], 3, -1)
        Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)).save(
            vdir / f"{vid}_layer_{name}.png"
        )


def _edge_density(img: np.ndarray, m: np.ndarray) -> float:
    lum = img @ sc.LUMA
    g = np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1))
    return float(g[m].mean()) if m.any() else 0.0


def harmonize(
    comp: sc.Composition, reference: np.ndarray, raw: np.ndarray, strength: float
) -> tuple[np.ndarray, dict]:
    """Take from the model only what it may change; return (image, report)."""
    pkg = comp.layers["instance_id"] >= 0
    removed = comp.layers["removal_mask"] > 0.5
    pre = comp.image.astype(np.float32) / 255
    h, w = pre.shape[:2]
    # 1) Our cartons: a smooth achromatic light map, bounded, faded by ``strength``.
    sig = 0.012 * max(h, w)
    ratio = ndimage.gaussian_filter(raw @ sc.LUMA + 1e-3, sig) / ndimage.gaussian_filter(
        pre @ sc.LUMA + 1e-3, sig
    )
    light = np.clip(1 + (ratio - 1) * strength, *HARMONIZE_RANGE)
    light = np.where(pkg, light, 1.0)
    albedo = comp.layers["albedo"] * np.asarray(
        comp.report.get("light_tint", [1, 1, 1]), np.float32
    )
    illum = comp.layers["lighting"] * light
    package = np.clip(albedo * illum[..., None], 0, 1)
    # 2) The ground where the old packages stood: the model's, unless it drew something there.
    around = ndimage.binary_dilation(removed, iterations=int(0.03 * max(h, w))) & ~removed & ~pkg
    ground = removed & ~pkg
    fill_ok = _edge_density(raw, ground) <= REMOVAL_EDGE_RATIO * max(
        _edge_density(reference, around), 1e-4
    )
    out = pre.copy()
    if fill_ok:
        out[ground] = raw[ground]
    out[pkg] = package[pkg]
    check = sc.verify_structural(package, albedo, illum, pkg, reference)
    check.update(
        {
            "ai_light_min": round(float(light[pkg].min()), 3),
            "ai_light_max": round(float(light[pkg].max()), 3),
            "ai_ground_used": bool(fill_ok),
        }
    )
    return (out * 255 + 0.5).astype(np.uint8), check


def run_structural(ctx: JobContext, vid: str) -> dict:
    pid = ctx.project_id
    version = repo.get("versions", vid)
    params = version.get("scene_json") or {}
    rid, flat_vid = params.get("reference_id"), version.get("flat_version_id")
    vdir = repo.project_dir(pid) / "versions"
    vdir.mkdir(exist_ok=True)

    ctx.stage("structure", "running")
    comp, reference, scene = precompose(pid, rid, flat_vid, scene=params.get("scene"))
    ctx.stage("structure", "done", {"instances": comp.report["instances"]})
    ctx.check_cancel()

    ctx.stage("compose", "running")
    Image.fromarray(comp.image).save(vdir / f"{vid}_structure.png")
    _save_layers(vdir, vid, comp)
    ctx.stage(
        "compose",
        "done",
        {k: comp.report[k] for k in ("focal_px", "ambient", "light") if k in comp.report},
    )
    ctx.check_cancel()

    final, check = comp.image, {**comp.report, "ai_used": False}
    usage = None
    if params.get("harmonize"):
        ctx.stage("model", "running")
        try:
            ref_img = Image.fromarray((reference * 255 + 0.5).astype(np.uint8))
            req = GenerationRequest(
                prompt=prompts.text("scene_harmonize"),
                images=[
                    (
                        "Image A — the composition to refine (keep every package exactly as it is):",
                        Image.fromarray(comp.image),
                    ),
                    (
                        "Image B — the original reference photograph (light, atmosphere only):",
                        ref_img,
                    ),
                ],
                width=comp.image.shape[1],
                height=comp.image.shape[0],
            )
            result = providers.PROVIDER.generate(req, IMAGE_MODEL.model_id)
            usage = result.usage
            raw = (
                np.asarray(
                    pipeline.cover(result.image, comp.image.shape[1], comp.image.shape[0])
                ).astype(np.float32)
                / 255
            )
            Image.fromarray((raw * 255 + 0.5).astype(np.uint8)).save(vdir / f"{vid}_raw.png")
            ctx.stage("model", "done")
            ctx.check_cancel()
            ctx.stage("verify", "running")
            img, ai_check = harmonize(comp, reference, raw, float(params.get("strength", 0.7)))
            if ai_check["match"]:
                final, check = img, {**comp.report, **ai_check, "ai_used": True}
            else:
                check = {
                    **comp.report,
                    "ai_used": False,
                    "ai_reason": "verify_failed",
                    "ai_check": ai_check,
                }
                Image.fromarray(img).save(vdir / f"{vid}_ai_rejected.png")
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001 - any model failure keeps the deterministic result
            log.warning("harmonization failed for %s: %s", vid, e)
            ctx.stage("model", "failed", message=str(e)[:200])
            check = {**comp.report, "ai_used": False, "ai_reason": "model_failed"}
        ctx.stage("verify", "done", {"ai_used": check.get("ai_used")})
    else:
        ctx.stage("model", "skipped")
        ctx.stage("verify", "done", {"match": check["match"]})
    (vdir / f"{vid}_report.json").write_text(json.dumps(check, ensure_ascii=False, default=float))
    spec = specs.load(repo.project_or_404(pid))
    h, w = final.shape[:2]
    frame = merge._canvas_frame(spec, w, h)
    pipeline.deliver(pid, vid, final, check, frame_json=frame, usage_json=usage)
    return {"version_id": vid}
