"""Post-render AI material enhancement ("ai_material") of a finished deterministic flat render.

The deterministic v3 render is finished and saved first; this job makes a *new* version from it
and never touches the source. The image model only ever sees a blank board (exact silhouette,
openings, fold scores, no print) and a reference photograph for material and light, so it has
nothing to redraw. From its photograph we keep only bounded appearance maps measured on the blank
board, registered to our pixels:

- light: smooth, neutral, clamped illumination (phase 1);
- detail: restrained mid-frequency paper appearance from clean board, never near print edges
  or the model's own markings (phase 2).

The final image is rebuilt from the vector print: ``clip(print x v3 gain x light x (1 + detail))``
with the strength applied to the maps, and the deterministic ground, cut and shadow outside.
It must pass ``look.verify_flat`` plus the enhancement checks, or the version fails with
ENHANCE_REJECTED and the original stays the result.

Saved next to the version (``versions/<vid>_*``): source, blank, raw, registered, light/detail
maps (``.npy`` for re-applying a new strength without the model, ``.png`` to look at), the final
image and ``_enhance.json`` (model, reference, strength, settings, checks).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil

import numpy as np
from PIL import Image
from scipy import ndimage

from app.ai import prompts, providers
from app.ai.models import IMAGE_MODEL
from app.ai.providers.base import GenerationRequest
from app.errors import ApiError
from app.jobs.runner import JobContext
from app.render import look, shading
from app.render.layers import Layers
from app.services import brief, pipeline, specs
from app.spec.models import FLAT_LOOKS
from app.spec.models import flat_look as look_for
from app.storage import repo

PHASE = 2  # 1: broad light only; 2: + restrained paper appearance (detail map)
MIN_IOU = 0.95  # the model's board against ours, after registration
MAX_SHIFT = 0.01  # registration may correct at most 1% of the long edge
MAX_INVENTED = 0.005  # share of the board where the model drew lines we do not have
LIGHT_RANGE = (0.96, 1.03)  # light at full strength
LIGHT_MIN_MM = 15.0  # light is smooth over at least this much board (never mottling)
MAX_CHANGE = 0.06  # final / source inside the board, at full strength
DEFAULT_STRENGTH = 0.6
PROTECT_MM = 4.0  # how far around type and logos the AI light is held back (fade, mm)
DETAIL_FINE_MM = 0.4  # finer than this is v3's own fibre texture (kept as the base)
DETAIL_BROAD_MM = 3.0  # broader than this is light (the light map), not paper
DETAIL_MAX = 0.015  # the paper appearance never moves a pixel more than 1.5%
DETAIL_STD = 0.0025  # ... and stays this restrained overall (verify cloud limit: 0.004)
CLOUD_LIMIT = 0.0036  # mottling under the AI appearance (verify allows 0.004)
COLOUR_LIMIT = 5.5  # Figma colours under the AI light (verify allows 6): leave some margin


def blank_layers(L: Layers) -> Layers:
    """The same board with no print: silhouette, openings, folds; no text, graphics or logos."""
    return dataclasses.replace(L, artwork=np.zeros_like(L.artwork))


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _png(path, rgb_float: np.ndarray) -> None:
    Image.fromarray(shading.to8(rgb_float)).save(path)


def _heat(m: np.ndarray, lo: float, hi: float) -> np.ndarray:
    v = np.clip((m - lo) / max(hi - lo, 1e-6), 0, 1)
    return np.repeat(v[..., None], 3, axis=-1)


def board_mask(scene: np.ndarray) -> np.ndarray:
    """The model's board: bright paper against its near-black ground."""
    return ndimage.uniform_filter(scene @ look.LUMA, 3) > 0.25


def register(scene: np.ndarray, sil: np.ndarray) -> tuple[np.ndarray, dict]:
    """Snap the model's board onto ours by the translation that best matches the two board
    masks (phase correlation on a small copy); report the shift and the overlap after it."""
    h, w = sil.shape
    k = max(1, round(max(h, w) / 1024))
    a = board_mask(scene)[::k, ::k].astype(np.float32)
    b = (sil[::k, ::k] > 0.5).astype(np.float32)
    fa, fb = np.fft.fft2(a - a.mean()), np.fft.fft2(b - b.mean())
    cross = fb * np.conj(fa)
    corr = np.real(np.fft.ifft2(cross / np.maximum(np.abs(cross), 1e-9)))
    dy, dx = np.unravel_index(int(corr.argmax()), corr.shape)
    dy = dy - corr.shape[0] if dy > corr.shape[0] // 2 else dy
    dx = dx - corr.shape[1] if dx > corr.shape[1] // 2 else dx
    dy, dx = dy * k, dx * k
    moved = ndimage.shift(scene, (dy, dx, 0), order=1, mode="nearest") if (dx or dy) else scene
    mask, ours = board_mask(moved), sil > 0.5
    union = (mask | ours).sum()
    iou = float((mask & ours).sum() / union) if union else 0.0
    return moved, {"shift_px": [int(dx), int(dy)], "iou": round(iou, 4)}


def invented_lines(scene: np.ndarray, blank: np.ndarray, L: Layers) -> float:
    """Share of the board where the model drew strong lines (folds, cuts, marks) that our blank
    board does not have: shifted panels or new structure."""
    px = L.px_per_mm
    lum_s = ndimage.gaussian_filter(scene @ look.LUMA, 1.0)
    grad = np.hypot(ndimage.sobel(lum_s, 0), ndimage.sobel(lum_s, 1)) / 8
    inner = ndimage.binary_erosion(L.silhouette > 0.5, iterations=max(2, round(2 * px)))
    ours = ndimage.binary_dilation(L.crease > 0.05, iterations=max(2, round(1.5 * px)))
    strong = grad > 0.03
    region = inner & ~ours
    return float((strong & region).sum() / max(1, int(inner.sum())))


def clean_board(L: Layers) -> np.ndarray:
    """Blank board away from the cut edge and the folds: where the model's light is measured."""
    px = L.px_per_mm
    solid = ndimage.binary_erosion(L.silhouette >= 0.999, iterations=max(2, round(2 * px)))
    folds = ndimage.binary_dilation(L.crease > 0.05, iterations=max(2, round(2 * px)))
    return solid & ~folds


def model_marks(scene: np.ndarray, L: Layers) -> np.ndarray:
    """Strong edges the model drew on the board (stray lines, marks, letters), grown by 1 mm:
    nothing of the model's appearance is taken from there."""
    px = L.px_per_mm
    lum = ndimage.gaussian_filter(scene @ look.LUMA, 1.0)
    grad = np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1)) / 8
    return ndimage.binary_dilation(grad > 0.02, iterations=max(2, round(px)))


def _masked_blur(v: np.ndarray, m: np.ndarray, sigma: float) -> np.ndarray:
    num = ndimage.gaussian_filter(v * m, sigma)
    den = ndimage.gaussian_filter(m, sigma)
    return np.where(den > 1e-3, num / np.maximum(den, 1e-3), 1.0)


def paper_detail(scene: np.ndarray, blank: np.ndarray, L: Layers) -> np.ndarray:
    """Restrained mid-frequency paper appearance (HxW, zero-mean, additive): what the model's
    board shows between fibre scale (0.4 mm; v3's own micro-texture stays the base) and light
    scale (6 mm), measured as model / our blank board on clean board only. Clamped and scaled
    to a small std; zero where the measurement is not trustworthy."""
    px = L.px_per_mm
    valid = (clean_board(L) & ~model_marks(scene, L)).astype(np.float32)
    if valid.sum() < 0.2 * max(1.0, float((L.silhouette >= 0.999).sum())):
        return np.zeros(valid.shape, np.float32)
    ratio = (scene @ look.LUMA) / np.maximum(blank @ look.LUMA, 0.05)
    fine = _masked_blur(ratio, valid, max(1.0, DETAIL_FINE_MM * px))
    broad = _masked_blur(ratio, valid, max(2.0, DETAIL_BROAD_MM * px))
    detail = fine / np.maximum(broad, 1e-3) - 1
    # Fade out (over ~1 mm) wherever the measurement was not valid.
    trust = np.clip(ndimage.gaussian_filter(valid, max(1.0, px)) * 2 - 1, 0, 1) * valid
    detail = np.clip(detail, -DETAIL_MAX, DETAIL_MAX) * trust
    on = trust > 0.5
    if on.any():
        detail -= float(detail[on].mean()) * trust
        std = float(detail[on].std())
        if std > DETAIL_STD:
            detail *= DETAIL_STD / std
    return detail.astype(np.float32)


def extract(scene: np.ndarray, blank: np.ndarray, L: Layers) -> dict[str, np.ndarray]:
    """Appearance maps (HxW, multiplicative around 1 / additive around 0) from the blank board."""
    solid = L.silhouette >= 0.999
    light = pipeline.broad_light(
        scene, blank, clean_board(L), LIGHT_RANGE, min_sigma_px=LIGHT_MIN_MM * L.px_per_mm
    )
    light = 1 + (light - 1) * solid
    if PHASE >= 2:
        detail = paper_detail(scene, blank, L) * solid
    else:
        detail = np.zeros_like(light)
    return {"light": light.astype(np.float32), "detail": detail.astype(np.float32)}


def protected_zone(L: Layers) -> np.ndarray:
    """0..1 over and around type, logos and line work, fading out over a few millimetres: the
    AI's paper detail is kept off the print there (the light is not: see ``fit_strength``)."""
    m = FLAT_LOOKS["v3"].material
    edges = shading.print_edge_zone(L, m) > 0.5
    k = max(1, round(L.px_per_mm))  # work at about 1 px per mm
    small = edges[::k, ::k].astype(np.float32)
    zone = np.clip(ndimage.gaussian_filter(small, PROTECT_MM) * 4, 0, 1)
    up = ndimage.zoom(zone, k, order=1)[: L.height, : L.width]
    return np.pad(up, ((0, L.height - up.shape[0]), (0, L.width - up.shape[1])), mode="edge")


def apply(
    parts: shading.Parts, maps: dict[str, np.ndarray], strength: float, protect: np.ndarray
) -> np.ndarray:
    """The enhanced gain: v3 gain x light^s x (1 + s * detail). The light reaches the whole
    board evenly (holding it back over print would outline text blocks); the fine paper detail
    is kept off the print."""
    s = float(np.clip(strength, 0, 1))
    solid = parts.sil >= 0.999  # the cut's edge pixels, openings and ground stay the source's
    light = 1 + (maps["light"] - 1) * s * solid
    detail = maps["detail"] * s * (1 - protect) * solid
    return (parts.gain * light * (1 + detail)).astype(np.float32)


def colours_hold(parts: shading.Parts, gain: np.ndarray, regions: list) -> bool:
    """Every solid Figma colour stays within the verify limit (CIE76 <= 6) under ``gain``."""
    for target, mask in regions:
        if mask.sum() < 20:
            continue
        seen = np.median(np.clip(parts.print_rgb[mask] * gain[mask][:, None], 0, 1), axis=0)
        if float(look.delta_e(seen, np.asarray(target, np.float32))) > COLOUR_LIMIT:
            return False
    return True


def fit_strength(
    parts, maps, strength, protect, regions, px_per_mm: float
) -> tuple[float, np.ndarray]:
    """The asked strength, or less: scaled down evenly (never locally) until the brand colours
    hold and the board stays free of cloudy mottling. Returns (applied strength, gain)."""
    solid = parts.sil >= 0.999
    edges = look.print_edges_of(shading.to8(parts.print_rgb), solid)
    for k in (1.0, 0.75, 0.5, 0.25, 0.0):
        gain = apply(parts, maps, strength * k, protect)
        if not colours_hold(parts, gain, regions):
            continue
        _, cloud, _ = look.board_texture(gain, solid, edges, px_per_mm)
        if cloud <= CLOUD_LIMIT or k == 0.0:
            return strength * k, gain
    return 0.0, apply(parts, maps, 0.0, protect)


def enhancement_checks(
    final: np.ndarray, source: np.ndarray, parts: shading.Parts, L: Layers
) -> dict:
    """What the enhancement must not change, compared with the source render."""
    sil = parts.sil
    solid = sil >= 0.999
    off_board = sil < 0.999  # ground, shadow, openings and the cut's edge pixels
    same_size = final.shape == source.shape
    outside_same = bool(same_size and np.array_equal(final[off_board], source[off_board]))
    f = final.astype(np.float32) / 255
    s = source.astype(np.float32) / 255
    ratio = (f @ look.LUMA + 1 / 255) / (s @ look.LUMA + 1 / 255)
    change = float(np.abs(ratio[solid] - 1).max()) if solid.any() else 0.0

    # Text and logo edges keep their sharpness: gradient energy at the print's edges.
    lum_p = parts.print_rgb @ look.LUMA
    edges = ndimage.binary_dilation(
        np.hypot(ndimage.sobel(lum_p, 0), ndimage.sobel(lum_p, 1)) / 8 > 0.03, iterations=1
    ) & ndimage.binary_erosion(solid, iterations=3)

    def energy(img):
        lum = img @ look.LUMA
        return float(np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1))[edges].mean())

    sharp = energy(f) / max(energy(s), 1e-6) if edges.any() else 1.0
    checks = {
        "same_size": same_size,
        "outline_and_openings_unchanged": outside_same,
        "bounded_change": change <= MAX_CHANGE,
        "text_edges_sharp": sharp >= 0.97,
    }
    return {
        "checks": checks,
        "max_change": round(change, 4),
        "edge_sharpness": round(sharp, 4),
    }


def run_enhance(ctx: JobContext, vid: str) -> dict:
    pid = ctx.project_id
    v = repo.get("versions", vid)
    if v is None:
        raise ApiError(404, "VERSION_NOT_FOUND", "버전을 찾을 수 없습니다.")
    params = v["settings_json"]
    src = repo.get("versions", params["source_version_id"])
    spec = specs.load(repo.project_or_404(pid))
    src_settings = src["settings_json"] or {}
    flat_look = look_for(
        src_settings.get("flat_look") or "v3", src_settings.get("fold_preset") or "medium"
    )
    strength = float(params["strength"])
    vdir = repo.project_dir(pid) / "versions"
    src_path = vdir / f"{src['id']}.png"
    src_sha = sha(src_path)

    ctx.stage("prepare", "running")
    source = np.asarray(Image.open(src_path).convert("RGB"))
    h, w = source.shape[:2]
    L = pipeline.get_layers(pid, spec, max(w, h), flat_look.lighting.margin)
    parts = shading.render_parts(L, flat_look)
    if shading.to8(parts.rgb).shape != source.shape or not np.array_equal(
        shading.to8(parts.rgb), source
    ):
        raise ApiError(
            409,
            "SOURCE_OUTDATED",
            "원본 렌더가 지금의 구조·룩과 달라 보정할 수 없습니다.",
            hint="② 플랫 렌더를 새로 만든 뒤 보정해주세요.",
        )
    shutil.copyfile(src_path, vdir / f"{vid}_source.png")
    blank = shading.render_parts(blank_layers(L), flat_look)
    _png(vdir / f"{vid}_blank.png", blank.rgb)
    ctx.stage("prepare", "done", {"size": [w, h], "look": flat_look.style})
    ctx.check_cancel()

    usage: dict = {}
    reused = params.get("maps_from")
    reg_info: dict = {}
    if reused:
        maps = {k: np.load(vdir / f"{reused}_{k}.npy") for k in ("light", "detail")}
        for key in ("model", "register", "extract"):
            ctx.stage(key, "skipped")
    else:
        ctx.stage("model", "running")
        pad = pipeline.provider_preview(shading.to8(blank.rgb), spec)
        ref_img, ref_label = reference_image(pid, params.get("reference_id"))
        req = GenerationRequest(
            prompt=prompts.render("material_enhance", dims=brief.figma_brief(pid, spec).dims),
            images=[
                ("Image 1 — blank board, exact structure (final):", pad.image),
                ("Image 2 — photograph for paperboard and lighting only:", ref_img),
            ],
            width=pad.image.width,
            height=pad.image.height,
        )
        result = providers.PROVIDER.generate(req, IMAGE_MODEL.model_id)
        usage = result.usage
        result.image.save(vdir / f"{vid}_raw.png")
        ctx.stage("model", "done", {"reference": ref_label})
        ctx.check_cancel()

        ctx.stage("register", "running")
        scene, reg_info = register(pipeline.registered(result.image, pad, w, h), L.silhouette)
        _png(vdir / f"{vid}_registered.png", scene)
        reg_info["invented_lines"] = round(invented_lines(scene, blank.rgb, L), 5)
        reasons = []
        if reg_info["iou"] < MIN_IOU:
            reasons.append("board_mismatch")
        if max(abs(x) for x in reg_info["shift_px"]) > MAX_SHIFT * max(w, h):
            reasons.append("board_shifted")
        if reg_info["invented_lines"] > MAX_INVENTED:
            reasons.append("invented_structure")
        ctx.stage("register", "done", reg_info)
        if reasons:
            _reject(pid, vid, reasons, {"register": reg_info}, params, src_sha, usage)
        ctx.check_cancel()

        ctx.stage("extract", "running")
        maps = extract(scene, blank.rgb, L)
        for k, m in maps.items():
            np.save(vdir / f"{vid}_{k}.npy", m)
        _png(vdir / f"{vid}_light.png", _heat(maps["light"], *LIGHT_RANGE))
        _png(vdir / f"{vid}_detail.png", _heat(maps["detail"], -0.02, 0.02))
        ctx.stage("extract", "done")

    ctx.stage("composite", "running")
    print8 = shading.to8(parts.print_rgb)
    regions = pipeline.figma_colour_regions(pid, L, print8)
    applied, gain = fit_strength(parts, maps, strength, protected_zone(L), regions, L.px_per_mm)
    board = np.clip(parts.print_rgb * gain[..., None], 0, 1)
    s = parts.sil[..., None]
    final = shading.to8(parts.background * (1 - s) + board * s)
    if reused:  # the maps are this version's too, so it can be re-applied again later
        for k, m in maps.items():
            np.save(vdir / f"{vid}_{k}.npy", m)
    ctx.stage("composite", "done", {"strength": strength, "strength_applied": applied})

    ctx.stage("verify", "running")
    check = look.verify_flat(
        final,
        print8,
        parts.sil,
        gain,
        L.artwork[..., 3],
        background=shading.hex_rgb(flat_look.lighting.background_color),
        colour_regions=regions,
        px_per_mm=L.px_per_mm,
    )
    check["strength_applied"] = round(applied, 3)
    extra = enhancement_checks(final, source, parts, L)
    check["checks"].update(extra["checks"])
    check.update({k: v for k, v in extra.items() if k != "checks"})
    check["source_unchanged"] = sha(src_path) == src_sha
    check["checks"]["source_unchanged"] = check["source_unchanged"]
    check["match"] = all(check["checks"].values())
    check.update(mode="ai_material", look=flat_look.style, size=[w, h], ai_used=True)
    ctx.stage("verify", "done", check)
    manifest = _manifest(params, src_sha, usage, check, reg_info)
    (vdir / f"{vid}_enhance.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    if not check["match"]:
        failed = [k for k, ok in check["checks"].items() if not ok]
        Image.fromarray(final).save(vdir / f"{vid}_rejected.png")
        repo.update("versions", vid, verify_json=check)
        _reject(pid, vid, failed, {"verify": check}, params, src_sha, usage, write=False)
    pipeline.deliver(pid, vid, final, check, frame_json=src["frame_json"], usage_json=usage)
    return {"version_id": vid}


def reference_image(pid: str, rid: str | None) -> tuple[Image.Image, str]:
    """The user's reference photo (material and light only), or the bundled look photo."""
    if rid:
        path = repo.project_dir(pid) / "refs" / f"{rid}.png"
        if path.exists():
            return Image.open(path).convert("RGB"), rid
    return Image.open(pipeline.FLAT_LOOK_IMAGE).convert("RGB"), "flat_look.png"


def _manifest(params: dict, src_sha: str, usage: dict, check: dict, reg: dict) -> dict:
    return {
        "mode": "ai_material",
        "phase": params.get("phase", PHASE),
        "model_id": IMAGE_MODEL.model_id,
        "source_version_id": params["source_version_id"],
        "source_sha256": src_sha,
        "reference": params.get("reference_id") or "flat_look.png",
        "strength": params["strength"],
        "maps_from": params.get("maps_from"),
        "limits": {
            "light_range": LIGHT_RANGE,
            "min_iou": MIN_IOU,
            "max_shift": MAX_SHIFT,
            "max_invented": MAX_INVENTED,
            "max_change": MAX_CHANGE,
        },
        "register": reg,
        "usage": usage,
        "verify": check,
    }


def _reject(pid, vid, reasons, details, params, src_sha, usage, write=True) -> None:
    """Keep the original: the enhancement fails with the reasons, nothing is delivered."""
    vdir = repo.project_dir(pid) / "versions"
    if write:
        manifest = _manifest(params, src_sha, usage, {"match": False}, details.get("register", {}))
        manifest["rejected"] = reasons
        (vdir / f"{vid}_enhance.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1)
        )
    raise ApiError(
        422,
        "ENHANCE_REJECTED",
        "AI 보정 결과가 검사를 통과하지 못해 원본 v3 렌더를 그대로 유지합니다.",
        hint="다른 레퍼런스나 낮은 강도로 다시 시도하거나, 원본 v3를 그대로 쓰세요.",
        details={"reasons": reasons},
    )
