"""Step 3: our packaging in place of the packaging in a reference photo.

Claude reads the reference (category, seven sections, packaging form, camera, light). The form
follows the reference, unless the user overrides it:

- **folded**: our carton is folded by us (``render.carton3d``) into the reference's pose, its
  faces cut from the approved flat render, so its print is exact before the model sees it.
- **flat**: the approved flat render goes in as it is, flat and top-down.

The image model gets Image A (our packaging), Image B (the reference) and, for folded, Image C
(the flat render, for print detail only), with prompts/merge.md. Then, as in step 2, only the
scene's light and the board's surface reach our packaging: the print is composited back and the
result is verified before it is ever shown.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy import ndimage

from app.ai import prompts, providers
from app.ai.models import IMAGE_MODEL
from app.ai.providers.base import GenerationRequest
from app.errors import ApiError
from app.jobs.runner import JobContext
from app.render import carton3d, look, surface
from app.render.layers import package_bbox
from app.services import brief, pipeline, specs
from app.spec.models import Specification
from app.storage import repo

MERGE_LONG_EDGE = 2048
REFERENCE_SCHEMA = 2  # analysis_json["schema"] of a reading made with prompts/reference_guide.md

FORM_RULES = {
    "flat": (
        "Image A is our approved flat, unfolded render of the packaging. It must stay flat and "
        "unfolded, seen from directly above (top-down), exactly where it is in the frame. Do not "
        "fold it, stand it up, tilt it or change its outline."
    ),
    "folded": (
        "Image A is our carton, folded by our renderer into the reference's pose. Its pose, "
        "position, size, perspective, outline and print are final: keep them exactly. Image C "
        "is our approved flat render, sent for print detail only (text, logos, colours); never "
        "place the flat sheet itself in the scene."
    ),
}


# ---- the carton ----------------------------------------------------------------------


@dataclass
class Carton:
    textures: dict[str, np.ndarray]  # face -> upright print, float RGB
    faces: dict[str, tuple[float, float, float, float]]  # face -> panel bbox (page points)
    dims: tuple[float, float, float]  # W, D, H mm


def faces_or_409(spec: Specification) -> dict[str, tuple[float, float, float, float]]:
    faces = carton3d.map_faces(spec.panels, spec.box)
    if "front" not in faces:
        raise ApiError(
            409,
            "FACES_UNKNOWN",
            "전개도에서 앞면을 찾지 못했습니다.",
            hint="구조 검토에서 패널 이름(앞면·옆면·윗면)을 확인하거나 평면 합성을 선택해주세요.",
        )
    return faces


def flat_image(pid: str, flat: dict) -> Image.Image:
    return Image.open(repo.project_dir(pid) / "versions" / f"{flat['id']}.png").convert("RGB")


def carton(pid: str, spec: Specification, flat: dict) -> Carton:
    """The faces of the folded box, cut from the approved flat render through its frame."""
    faces = faces_or_409(spec)
    img = np.asarray(flat_image(pid, flat)).astype(np.float32) / 255
    fr = flat["frame_json"]
    (ox, oy), (sw, sh) = fr["origin"], fr["size"]
    kx, ky = img.shape[1] / sw, img.shape[0] / sh  # px per page point
    tex = {}
    for f, (a, b, c, d) in faces.items():
        tex[f] = img[
            max(0, int((b - oy) * ky)) : int((d - oy) * ky),
            max(0, int((a - ox) * kx)) : int((c - ox) * kx),
        ]
    mm_per_pt = spec.scale.mm_per_pt if spec.scale else 25.4 / 72
    return Carton(tex, faces, carton3d.dims_from(faces, mm_per_pt, spec.box))


def camera_of(reading: dict | None) -> carton3d.Camera:
    cam = (reading or {}).get("camera") or {}
    placement = cam.get("placement") or [0.25, 0.15, 0.75, 0.85]
    if len(placement) != 4 or placement[2] <= placement[0] or placement[3] <= placement[1]:
        placement = [0.25, 0.15, 0.75, 0.85]
    return carton3d.Camera(
        azimuth=float(np.clip(cam.get("azimuth", 30), -60, 60)),
        # A straight-down view of a closed box has no up direction; 80 degrees reads as top.
        elevation=float(np.clip(cam.get("elevation", 15), 0, 80)),
        lens_mm=float(np.clip(cam.get("lens_mm", 50), 24, 135)),
        placement=tuple(float(np.clip(v, 0, 1)) for v in placement),
    )


def size_of(ref: dict) -> tuple[int, int]:
    """The reference's aspect at a 2048 px long edge (multiples of 16)."""
    w, h = max(1, ref["width"]), max(1, ref["height"])
    k = MERGE_LONG_EDGE / max(w, h)
    return max(16, round(w * k / 16) * 16), max(16, round(h * k / 16) * 16)


def stage(
    c: Carton, cam: carton3d.Camera, size: tuple[int, int]
) -> tuple[np.ndarray, carton3d.Render]:
    """The carton on a neutral grey ground with a soft placeholder contact shadow."""
    r = carton3d.render(c.textures, c.dims, cam, size)
    w, h = size
    a = r.rgba[..., 3]
    ground = np.full((h, w, 3), 0.82, np.float32)
    shadow = ndimage.gaussian_filter(np.roll(a, max(2, h // 120), axis=0), max(3, h / 90))
    ground *= 1 - 0.35 * np.clip(shadow, 0, 1)[..., None]
    img = ground * (1 - a[..., None]) + r.rgba[..., :3] * a[..., None]
    return np.clip(img, 0, 1), r


# ---- what the model is told ------------------------------------------------------------


def _camera_text(reading: dict) -> str:
    c = reading.get("camera") or {}
    p = c.get("placement") or []
    where = (
        f"; the packaging occupies x {p[0]:.2f}-{p[2]:.2f}, y {p[1]:.2f}-{p[3]:.2f} of the frame"
        if len(p) == 4
        else ""
    )
    return (
        f"azimuth {c.get('azimuth', 0):g} deg, elevation {c.get('elevation', 0):g} deg, "
        f"~{c.get('lens_mm', 50):g} mm lens, aspect {c.get('aspect_ratio', '1:1')}{where}"
    )


def _light_text(reading: dict) -> str:
    li = reading.get("light") or {}
    return (
        f"key light from {li.get('key_azimuth', 0):g} deg (0 = top of frame, clockwise), "
        f"{li.get('key_elevation', 45):g} deg high, {li.get('quality', 'soft')}, "
        f"{li.get('temperature', 'neutral')}. Shadow: {li.get('shadow', '')}"
    )


def merge_prompt(pid: str, spec: Specification, reading: dict, form: str) -> str:
    b = brief.figma_brief(pid, spec)
    sections = "\n".join(
        f"- {s['title_ko']} ({s['key']}): {s['text_en']}" for s in reading.get("sections", [])
    )
    return prompts.render(
        "merge",
        figma_url=b.figma_url,
        form_rule=FORM_RULES[form],
        category=reading.get("category", "product_packaging"),
        dims=b.dims,
        colours=b.colours,
        texts_by_face=b.texts_by_face,
        reference_sections=sections or "(none)",
        camera=_camera_text(reading),
        light=_light_text(reading),
    )


def is_stale(ref: dict) -> bool:
    """Read by an earlier version of the app (other sections, no form or camera)."""
    analysis = ref.get("analysis_json") or {}
    return (
        ref["analysis_status"] == "done"
        and analysis.get("schema") != REFERENCE_SCHEMA
        and bool(analysis or ref.get("scene_json"))
    )


def reference_reading(ref: dict | None) -> dict:
    """The reference's current reading, or 409 until there is one."""
    if ref is None:
        raise ApiError(404, "REFERENCE_NOT_FOUND", "레퍼런스를 찾을 수 없습니다.")
    analysis = ref.get("analysis_json") or {}
    if ref["analysis_status"] == "done" and analysis.get("schema") == REFERENCE_SCHEMA:
        return analysis
    if ref["analysis_status"] == "pending":
        raise ApiError(
            409,
            "REFERENCE_PENDING",
            "Claude가 레퍼런스를 읽는 중입니다.",
            hint="읽기가 끝난 뒤 다시 시도해주세요.",
        )
    if is_stale(ref):
        raise ApiError(
            409,
            "REFERENCE_STALE",
            "이전 방식으로 읽은 레퍼런스입니다.",
            hint="새 방식으로 다시 읽는 중입니다. 잠시 후 다시 시도해주세요.",
        )
    raise ApiError(
        409,
        "REFERENCE_NOT_ANALYZED",
        "레퍼런스가 아직 분석되지 않았습니다.",
        hint="레퍼런스를 다시 분석한 뒤 시도해주세요.",
    )


def _face_masks(r: carton3d.Render) -> dict[str, np.ndarray]:
    return {f: r.face == i for i, f in enumerate(carton3d.FACES) if (r.face == i).any()}


def composite(
    c: Carton, r: carton3d.Render, raw: Image.Image, size: tuple[int, int], pid: str
) -> pipeline.Composited:
    """Scene from the model; each visible face = exact print x the scene's light and surface.

    The largest visible face is the hero: its colours stay exact (exposure-neutral). Other faces
    turn away from the light, so they take the scene's level for that face (darker or lighter),
    with no tint; their print and hue are unchanged.
    """
    w, h = size
    scene = np.asarray(pipeline.cover(raw, w, h)).astype(np.float32) / 255
    alpha = r.rgba[..., 3]
    print_rgb = r.rgba[..., :3]
    masks = _face_masks(r)
    hero = max(masks, key=lambda f: masks[f].sum())
    px_per_mm = max(w, h) / (max(c.dims) * 2.2)
    gain = np.ones((h, w, 3), np.float32)
    level = np.ones((h, w), np.float32)
    edges = np.zeros((h, w), bool)
    for f, m in masks.items():
        sil = alpha * m
        g, e, _ = surface.transfer(print_rgb, scene, sil, px_per_mm)
        gain = np.where(m[..., None], g, gain)
        edges |= e
        if f != hero:
            solid = ndimage.binary_erosion(m, iterations=3)
            ratio = (scene @ look.LUMA)[solid] / np.maximum((print_rgb @ look.LUMA)[solid], 0.03)
            lv = float(np.clip(np.median(ratio) if ratio.size else 1.0, 0.55, 1.05))
            level[m] = lv / max(_hero_level(scene, print_rgb, masks[hero]), 1e-3)
    level = np.clip(level, 0.5, 1.1)
    shaded = np.clip(print_rgb * level[..., None], 0, 1)  # faces turned from the light
    print8 = (shaded * 255 + 0.5).astype(np.uint8)
    pkg = np.clip(print8.astype(np.float32) / 255 * gain, 0, 1)
    a = alpha[..., None]
    out = scene * (1 - a) + pkg * a
    regions = _hero_colour_regions(pid, c, r, hero, print8)
    return pipeline.Composited(
        (out * 255 + 0.5).astype(np.uint8), print8, gain, edges, scene, regions
    )


def _hero_level(scene, print_rgb, m) -> float:
    solid = ndimage.binary_erosion(m, iterations=3)
    ratio = (scene @ look.LUMA)[solid] / np.maximum((print_rgb @ look.LUMA)[solid], 0.03)
    return float(np.clip(np.median(ratio) if ratio.size else 1.0, 0.55, 1.25))


def _hero_colour_regions(pid, c: Carton, r: carton3d.Render, hero: str, print8) -> list:
    """Figma colours on the hero face (its texts/graphics), located through the face's UVs."""
    content = pipeline.figma_content(pid) or {}
    a, b, cx, d = c.faces[hero]
    m = r.face == carton3d.FACES.index(hero)
    u, v = r.uv[..., 0], r.uv[..., 1]
    rgb = print8.astype(np.float32) / 255
    out = []
    for item in content.get("texts", []) + content.get("graphics", []):
        if item.get("technical") or not item.get("color") or not item.get("bbox"):
            continue
        x0, y0, x1, y1 = item["bbox"]
        if not (a <= x0 and x1 <= cx and b <= y0 and y1 <= d):
            continue
        u0, u1 = (x0 - a) / (cx - a), (x1 - a) / (cx - a)
        v0, v1 = (y0 - b) / (d - b), (y1 - b) / (d - b)
        hexv = item["color"].lstrip("#")[:6]
        target = np.array([int(hexv[i : i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)
        box = m & (u >= u0) & (u <= u1) & (v >= v0) & (v <= v1)
        close = ndimage.binary_erosion(box & (look.delta_e(rgb, target) < 8), iterations=1)
        if close.sum() >= 20:
            out.append((target, close))
    return out


def run_merge(ctx: JobContext, vid: str) -> dict:
    pid = ctx.project_id
    version = repo.get("versions", vid)
    if version is None:
        raise ApiError(404, "VERSION_NOT_FOUND", "버전을 찾을 수 없습니다.")
    params = version.get("scene_json") or {}
    ref = repo.get("refs", params.get("reference_id") or "")
    reading = reference_reading(ref)
    flat = repo.get("versions", version.get("flat_version_id") or "")
    if flat is None or flat["status"] != "done" or not flat.get("frame_json"):
        raise ApiError(409, "FLAT_VERSION_MISSING", "합성할 플랫 렌더를 찾을 수 없습니다.")
    form = params["form"]
    spec = specs.load(repo.project_or_404(pid))
    ref_img = Image.open(repo.project_dir(pid) / "refs" / f"{ref['id']}.png").convert("RGB")
    vdir = repo.project_dir(pid) / "versions"
    vdir.mkdir(exist_ok=True)

    ctx.stage("prepare", "running")
    if form == "folded":
        c = carton(pid, spec, flat)
        size = size_of(ref)
        staged, r = stage(c, camera_of(reading), size)
        structure = Image.fromarray((staged * 255 + 0.5).astype(np.uint8))
        images = [
            ("Image A — our packaging, folded and posed (structure, print and pose):", structure),
            ("Image B — the reference photograph (visual style):", ref_img),
            ("Image C — our approved flat render (print detail only):", flat_image(pid, flat)),
        ]
    else:
        w, h = pipeline.gen_size(spec)
        size = (w, h)
        long_edge = max(w, h)
        base_img, sil, _ = pipeline.render_image(pid, spec, long_edge)
        structure = flat_image(pid, flat).resize(size, Image.LANCZOS)
        images = [
            ("Image A — our approved flat render (structure and print):", structure),
            ("Image B — the reference photograph (visual style):", ref_img),
        ]
    structure.save(vdir / f"{vid}_structure.png")
    prompt = merge_prompt(pid, spec, reading, form)
    ctx.stage("prepare", "done", {"form": form})
    ctx.check_cancel()

    ctx.stage("model", "running")
    req = GenerationRequest(prompt=prompt, images=images, width=size[0], height=size[1])
    result = providers.PROVIDER.generate(req, IMAGE_MODEL.model_id)
    ctx.stage("model", "done")
    ctx.check_cancel()

    ctx.stage("composite", "running")
    result.image.save(vdir / f"{vid}_raw.png")
    if form == "folded":
        comp = composite(c, r, result.image, size, pid)
        sil = r.rgba[..., 3]
        frame_json = _canvas_frame(spec, *size)
    else:
        comp = pipeline.composite(base_img, sil, result.image, pid, spec, long_edge)
        frame_json = flat["frame_json"]
    ctx.stage("composite", "done")

    ctx.stage("verify", "running")
    check = pipeline.verify(comp, sil)
    ctx.stage("verify", "done", check)
    pipeline.deliver(pid, vid, comp.image, check, frame_json=frame_json, usage_json=result.usage)
    return {"version_id": vid}


def _canvas_frame(spec: Specification, w: int, h: int) -> dict:
    """Where the studio canvas shows the photo: centred on the dieline, same long edge."""
    x0, y0, x1, y1 = package_bbox(spec)
    long_pt = max(x1 - x0, y1 - y0)
    k = long_pt / max(w, h)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return {"origin": [cx - w * k / 2, cy - h * k / 2], "size": [w * k, h * k]}
