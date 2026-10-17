"""Processing pipelines run by background jobs: analysis, the structure render and step 2,
the flat render (deterministic, optionally lit by the image model)."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from app.ai import claude, prompts, providers
from app.ai.models import IMAGE_MODEL
from app.ai.providers.base import GenerationRequest
from app.ai.providers.gemini import nearest_ratio
from app.config import get_settings
from app.errors import ApiError
from app.figma import client as figma
from app.figma.layers import extract_content
from app.jobs.runner import JobContext, SkipRest
from app.pdf import analyze, physical
from app.pdf.validate import validate_pdf
from app.render import look, shading, surface
from app.render.layers import Layers, build_layers, frame, make_artwork_pdf, structure_key
from app.services import brief, specs
from app.spec.models import FLAT_LOOK, FLAT_LOOKS, AiSuggestion, Specification
from app.storage import repo

log = logging.getLogger(__name__)

# The look reference for step 2 (Image 2): black background, top-down, matte white board.
FLAT_LOOK_IMAGE = prompts.DIR / "flat_look.png"
# Marks a version made by this pipeline; older rows are shown as legacy. 3: deterministic
# flat render (renders of 2 took the model's surface and edges and are not merged any more).
PIPELINE = 3

# ---- layer cache ---------------------------------------------------------------------

_cache: OrderedDict[str, Layers] = OrderedDict()
_cache_lock = threading.Lock()
CACHE_SIZE = 8
CACHE_MAX_EDGE = 2048  # full-size flat layers (~4K) are hundreds of MB: built per job, not kept


def get_layers(pid: str, spec: Specification, long_edge: int, margin: int) -> Layers:
    skey = structure_key(spec)
    key = hashlib.sha1(f"{pid}|{skey}|{long_edge}|{margin}".encode()).hexdigest()
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    source = repo.read_source(pid)
    art_path = repo.project_dir(pid) / f"artwork-{skey}.pdf"
    if art_path.exists():
        art_pdf = art_path.read_bytes()
    else:
        art_pdf = make_artwork_pdf(source, spec)
        art_path.write_bytes(art_pdf)
    layers = build_layers(source, spec, long_edge, margin, artwork_pdf=art_pdf)
    if long_edge > CACHE_MAX_EDGE:
        return layers
    with _cache_lock:
        _cache[key] = layers
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return layers


def drop_cache(pid: str) -> None:
    """Forget cached layers for a project (structure changed or project deleted)."""
    with _cache_lock:
        _cache.clear()
    d = get_settings().projects_dir / pid
    for f in d.glob("artwork-*.pdf") if d.exists() else []:
        f.unlink(missing_ok=True)


def render_image(
    pid: str, spec: Specification, long_edge: int, transparent: bool = False
) -> tuple[np.ndarray, np.ndarray, Layers]:
    """The deterministic flat render in the fixed look: exact print, white board, black."""
    layers = get_layers(pid, spec, long_edge, FLAT_LOOK.lighting.margin)
    img, sil = shading.render(layers, FLAT_LOOK, transparent=transparent)
    return img, sil, layers


def save_thumb(img: np.ndarray | Image.Image, path, edge: int = 480) -> None:
    im = img if isinstance(img, Image.Image) else Image.fromarray(img)
    im = im.convert("RGB")
    im.thumbnail((edge, edge))
    im.save(path, "JPEG", quality=85)


# ---- analyze -------------------------------------------------------------------------


def run_analyze(ctx: JobContext, page: int | None) -> dict:
    pid = ctx.project_id
    repo.update("projects", pid, status="analyzing", error_json=None, updated_at=repo.now())
    try:
        return _analyze(ctx, pid, page)
    except SkipRest:
        raise
    except ApiError as e:
        repo.update("projects", pid, status="failed", error_json=e.body.model_dump())
        raise
    except Exception:
        repo.update(
            "projects",
            pid,
            status="failed",
            error_json={
                "code": "ANALYZE_FAILED",
                "message": "분석 중 오류가 발생했습니다.",
                "hint": "다시 시도하거나 다른 파일을 업로드해주세요.",
                "details": {},
            },
        )
        raise


def _analyze(ctx: JobContext, pid: str, page: int | None) -> dict:
    source = repo.read_source(pid)
    project = repo.project_or_404(pid)

    ctx.stage("validate", "running")
    info = validate_pdf(source, get_settings().max_upload_mb)
    if info.page_count > 1 and page is None:
        ctx.stage("validate", "done", {"page_count": info.page_count})
        _page_preview(pid, source, 0)  # dashboard thumbnail while the user picks a page
        repo.update("projects", pid, status="needs_page", updated_at=repo.now())
        raise SkipRest({"needs_page": True, "page_count": info.page_count})
    page_index = min(page or 0, info.page_count - 1)
    ctx.stage("validate", "done", {"page_count": info.page_count, "page": page_index})

    ctx.stage("preview", "running")
    page_png = _page_preview(pid, source, page_index)
    ctx.stage("preview", "done")
    ctx.check_cancel()

    ctx.stage("extract", "running")
    ex = analyze.extract(
        source,
        page_index,
        design_shapes=_figma_shapes(pid),
        design_content=figma_content(pid, backfill=True),
    )
    ctx.stage(
        "extract",
        "done",
        {
            "vectors": len(ex.walk.paths),
            "images": len(ex.images),
            "text": len(ex.text_lines),
            "layers": len(ex.walk.ocg_names),
            "flattened": ex.flattened,
        },
    )

    ctx.stage("separations", "running")
    cl = analyze.detect(ex)
    seps = analyze.separations(ex, cl)
    ctx.stage("separations", "done", {k: v["state"] for k, v in seps.model_dump().items()})

    ctx.stage("structure", "running")
    spec = analyze.build_spec(ex, cl)
    if project.get("spec_json"):  # re-analysis keeps the user's decisions
        _keep_user_decisions(spec, Specification.model_validate(project["spec_json"]))
    ai_note = _ai_structure(spec, page_png)
    specs.save(pid, spec)
    ctx.stage(
        "structure",
        "done",
        {
            "paths": len(spec.paths),
            "pending": spec.review.pending,
            "reasons": spec.review.reasons,
            "ai": ai_note,
        },
    )

    if spec.review.required:
        repo.update("projects", pid, status="needs_review", updated_at=repo.now())
        raise SkipRest({"review": True, "reasons": spec.review.reasons})
    _render_ready(ctx, pid)
    return {"review": False}


def figma_content(pid: str, backfill: bool = False) -> dict | None:
    """Texts, graphics and lines read from Figma at import time (see app/figma).

    Projects imported before this existed have none; ``backfill`` fetches it for the exact
    file version that was imported, so it matches the stored PDF.
    """
    path = repo.project_dir(pid) / "figma_content.json"
    if path.exists():
        return json.loads(path.read_text())
    if not backfill or not figma.configured():
        return None
    try:
        return backfill_figma_content(pid)
    except ApiError as e:
        log.warning("figma content backfill failed for %s: %s", pid, e.body.code)
        return None


def backfill_figma_content(pid: str) -> dict | None:
    """Fetch and store the Figma content of a project imported by link (raises ApiError)."""
    meta = (repo.get("projects", pid) or {}).get("figma_json")
    if not meta:
        return None
    link = figma.FigmaLink(meta["file_key"], meta["node_id"], meta["url"])
    content = extract_content(figma.fetch_frame(link, version=meta.get("version")).document)
    path = repo.project_dir(pid) / "figma_content.json"
    path.write_text(json.dumps(content, ensure_ascii=False))
    return content


def _figma_shapes(pid: str) -> list[dict] | None:
    """Named Figma layers saved at import time (see app/figma), if this project came from Figma."""
    path = repo.project_dir(pid) / "figma_shapes.json"
    return json.loads(path.read_text()) if path.exists() else None


def _keep_user_decisions(spec: Specification, previous: Specification) -> None:
    """User-confirmed classes outrank fresh analysis (trust order in spec.models)."""
    confirmed = {
        (p.source_ref, p.subpath): p.cls
        for p in previous.paths
        if p.provenance == "user_confirmed" and not p.source_ref.startswith("manual:")
    }
    for p in spec.paths:
        cls = confirmed.get((p.source_ref, p.subpath))
        if cls:
            p.cls, p.status, p.provenance = cls, "confirmed", "user_confirmed"
    # A hand-drawn outline only stays when the PDF still yields no cut line of its own.
    if not any(p.cls == "cut" for p in spec.paths):
        spec.paths += [p for p in previous.paths if p.source_ref.startswith("manual:")]
    spec.review, _ = analyze.review_state(spec.paths, spec.page)
    spec.structure_confirmed = not spec.review.required
    spec.panels = analyze.find_panels(spec.paths, spec.page) if not spec.review.required else []


def _page_preview(pid: str, source: bytes, page_index: int) -> bytes:
    import pymupdf

    doc = pymupdf.open(stream=source, filetype="pdf")
    pg = doc[page_index]
    zoom = 1400 / max(pg.rect.width, pg.rect.height)
    page_png = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")
    (repo.project_dir(pid) / "page.png").write_bytes(page_png)
    save_thumb(Image.open(io.BytesIO(page_png)), repo.project_dir(pid) / "thumb.jpg")
    return page_png


def _ai_structure(spec: Specification, page_png: bytes) -> str:
    """Optional Claude suggestions for unresolved paths. Failure never blocks analysis."""
    pending = [p for p in spec.paths if p.status == "unresolved"]
    if not pending:
        return "not_needed"
    if not claude.available():
        return "unavailable"
    try:
        img = Image.open(io.BytesIO(page_png)).convert("RGB")
        scale = img.width / spec.page.width_pt
        draw = ImageDraw.Draw(img)
        listed = []
        for n, p in enumerate(pending[:40], start=1):
            for pl in p.polylines:
                draw.line([(x * scale, y * scale) for x, y in pl], fill=(255, 140, 0), width=4)
            x0, y0 = p.bbox[0] * scale, p.bbox[1] * scale
            draw.text((x0 + 4, y0 - 14), str(n), fill=(255, 100, 0))
            listed.append(
                {
                    "id": p.id,
                    "label": n,
                    "bbox_pt": p.bbox,
                    "color": p.color,
                    "dashed": p.dashed,
                    "width_pt": p.width_pt,
                    "geometry_suggestion": p.suggested_cls,
                    "geometry_reason": p.reason,
                }
            )
        result = claude.suggest_structure(img, listed)
        by_id = {p.id: p for p in spec.paths}
        for s in result.paths:
            if s.id in by_id:
                by_id[s.id].ai = AiSuggestion(cls=s.cls, reason=s.reason)
        return "done"
    except ApiError as e:
        log.warning("claude structure suggestion skipped: %s", e.body.code)
        return "failed"


def run_render(ctx: JobContext) -> dict:
    _render_ready(ctx, ctx.project_id, stage_prefix=True)
    return {}


def _render_ready(ctx: JobContext, pid: str, stage_prefix: bool = False) -> None:
    """Build layers + the deterministic flat render (flat.jpg), then mark the project ready."""
    project = repo.project_or_404(pid)
    spec = specs.load(project)
    if stage_prefix:
        ctx.stage("layers", "running")
    else:
        ctx.stage("render", "running")
    if not spec.panels:
        spec.panels = analyze.find_panels(spec.paths, spec.page)
    _ai_panel_names(pid, spec)
    spec.objects = analyze.inside_cut(spec.objects, spec.paths, spec.page)
    physical.refresh(spec, figma_content(pid))  # panel sizes, margins: structure is final now
    drop_cache(pid)
    art_path = repo.project_dir(pid) / f"artwork-{structure_key(spec)}.pdf"
    art_path.write_bytes(make_artwork_pdf(repo.read_source(pid), spec))
    spec = specs.save(pid, spec)
    img, _, _ = render_image(pid, spec, get_settings().preview_long_edge)
    if stage_prefix:
        ctx.stage("layers", "done")
        ctx.stage("render", "running")
    save_thumb(img, repo.project_dir(pid) / "flat.jpg", 640)
    ctx.stage("render", "done")
    repo.update("projects", pid, status="ready", updated_at=repo.now())


def _ai_panel_names(pid: str, spec: Specification) -> None:
    if (
        not spec.panels
        or not claude.available()
        or any(p.name_provenance != "extracted" for p in spec.panels)
    ):
        return
    try:
        img = Image.open(repo.project_dir(pid) / "page.png")
        result = claude.name_panels(img, [{"id": p.id, "bbox_pt": p.bbox} for p in spec.panels])
        names = {p.id: p.name for p in result.panels}
        for p in spec.panels:
            if p.id in names:
                p.name, p.name_provenance = names[p.id], "claude_inferred"
    except (ApiError, OSError) as e:
        log.warning("claude panel naming skipped: %s", e)


# ---- step 2: flat render -------------------------------------------------------------
#
# The flat render is deterministic: the PDF/Figma vectors are rasterized once at the final
# size, on a board whose fibres, folds, light and cut edge are an achromatic gain, with the
# exact silhouette, openings and a black background. Nothing in it comes from an image model.
#
# "ai_appearance" mode may additionally ask the image model for a photographed look. Only a
# smooth, clamped, neutral light map measured on clean unprinted paper is taken from its
# image, and only when its board lines up with ours; its print, edges, texture and background
# are never used. See flat_render_replacement in prompts/flat_render.md.

FlatMode = Literal["deterministic", "ai_appearance"]
GEN_LONG_EDGE = 2048  # provider preview size (the model's image is never the print master)
AI_LIGHT_RANGE = (0.96, 1.03)  # the model may only shade the board this gently
AI_LIGHT_SIGMA = 0.03  # light map scale: 3% of the long edge, far larger than any glyph
AI_MIN_IOU = 0.9  # the model's board must cover ours this well, or its light is not used
AI_MIN_CLEAN = 0.05  # share of the board that must be clean paper to measure light on


def gen_size(spec: Specification) -> tuple[int, int]:
    raster, _ = frame(spec, GEN_LONG_EDGE, FLAT_LOOK.lighting.margin)
    w, h = raster.w, raster.h
    w, h = max(16, round(w / 16) * 16), max(16, round(h / 16) * 16)
    # Provider limits: aspect between 1:3 and 3:1, at least ~655k pixels.
    while w * h < 655_360:
        w, h = w + 16, h + round(16 * h / w)
    return w, h


def flat_prompt(pid: str, spec: Specification) -> str:
    b = brief.figma_brief(pid, spec)
    return prompts.render(
        "flat_render",
        figma_url=b.figma_url,
        dims=b.dims,
        panels=b.panels,
        fonts=b.fonts,
        logos=b.logos,
        colours=b.colours,
        texts_by_panel=b.texts_by_panel,
    )


def mismatch(check: dict) -> ApiError:
    return ApiError(
        422,
        "ARTWORK_MISMATCH",
        "결과의 글자·색이 원본과 달라 결과를 버렸습니다.",
        hint="다시 생성해주세요. 원본과 다른 이미지는 보여주지 않습니다.",
        details={k: v for k, v in check.items() if k not in ("protected_px", "changed_px")},
    )


def deliver(pid: str, vid: str, image: np.ndarray, check: dict, **fields) -> None:
    """Save a verified result. A result that failed verification is kept for diagnosis only
    (``<vid>_rejected.png``) and the version fails with ARTWORK_MISMATCH."""
    vdir = repo.project_dir(pid) / "versions"
    if not check["match"]:
        Image.fromarray(image).save(vdir / f"{vid}_rejected.png")
        repo.update("versions", vid, verify_json=check)
        raise mismatch(check)
    Image.fromarray(image).save(vdir / f"{vid}.png")
    save_thumb(image, vdir / f"{vid}_thumb.jpg", 360)
    repo.update("versions", vid, status="done", verify_json=check, **fields)
    repo.update("projects", pid, updated_at=repo.now())  # refresh the thumbnail cache key


@dataclass
class Padded:
    """The provider preview: our frame centred on a canvas of the provider's aspect ratio,
    so the returned image maps back onto our pixels by a known scale and offset."""

    image: Image.Image
    box: tuple[int, int, int, int]  # where our frame sits on the canvas (x0, y0, x1, y1)


def provider_preview(final: np.ndarray, spec: Specification) -> Padded:
    w, h = gen_size(spec)
    rw, rh = (int(v) for v in nearest_ratio(w, h).split(":"))
    if w / h > rw / rh:
        cw, ch = w, round(w * rh / rw)
    else:
        cw, ch = round(h * rw / rh), h
    canvas = Image.new("RGB", (cw, ch), (0, 0, 0))
    x0, y0 = (cw - w) // 2, (ch - h) // 2
    canvas.paste(Image.fromarray(final).convert("RGB").resize((w, h), Image.LANCZOS), (x0, y0))
    return Padded(canvas, (x0, y0, x0 + w, y0 + h))


def registered(raw: Image.Image, pad: Padded, w: int, h: int) -> np.ndarray:
    """The model's image mapped onto our frame (float RGB, h x w), through the padding
    transform; a returned image of the canvas's aspect lands pixel-aligned."""
    cw, ch = pad.image.size
    sx, sy = raw.width / cw, raw.height / ch
    x0, y0, x1, y1 = pad.box
    crop = raw.convert("RGB").crop((x0 * sx, y0 * sy, x1 * sx, y1 * sy))
    return np.asarray(crop.resize((w, h), Image.LANCZOS)).astype(np.float32) / 255


def model_board_iou(scene: np.ndarray, sil: np.ndarray) -> float:
    """How well the model's board (bright against the black ground) covers our exact board."""
    k = 4
    s = ndimage.uniform_filter(scene @ look.LUMA, k)[::k, ::k] > 0.12
    ours = sil[::k, ::k] > 0.5
    union = (s | ours).sum()
    return float((s & ours).sum() / union) if union else 0.0


def clean_paper(L: Layers, sil: np.ndarray) -> np.ndarray:
    """Board away from print edges (text, logos, barcode, line work), folds and the cut edge:
    where light can be measured. Flat tints and gradients count: the model's light on them is
    still a ratio to our own render there."""
    solid = ndimage.binary_erosion(sil >= 0.999, iterations=max(2, round(1.5 * L.px_per_mm)))
    near = max(2, round(2.0 * L.px_per_mm))
    print_rgb = shading.print_surface(L, FLAT_LOOK.material)
    edges = ndimage.binary_dilation(
        surface.print_edges(print_rgb, sil, L.px_per_mm), iterations=near
    )
    folds = ndimage.binary_dilation(L.crease > 0.05, iterations=near)
    return solid & ~edges & ~folds


def broad_light(
    scene: np.ndarray, det: np.ndarray, clean: np.ndarray, bounds: tuple[float, float]
) -> np.ndarray:
    """Scene / our render on ``clean`` paper, blurred far beyond glyph size, exposure-neutral
    and clamped to ``bounds``: only broad light survives (HxW)."""
    h, w = clean.shape
    ratio = (scene @ look.LUMA) / np.maximum(det @ look.LUMA, 0.05)
    k = max(1, round(max(h, w) / 512))  # measured on a small copy
    sigma = AI_LIGHT_SIGMA * max(h, w) / k
    m = clean[::k, ::k].astype(np.float32)
    num = ndimage.gaussian_filter(ratio[::k, ::k] * m, sigma)
    den = ndimage.gaussian_filter(m, sigma)
    small = np.where(den > 1e-3, num / np.maximum(den, 1e-3), 1.0)
    if (m > 0).any():
        small = small / max(float(np.median(small[m > 0])), 1e-3)
    small = np.clip(small, *bounds).astype(np.float32)
    return np.asarray(Image.fromarray(small).resize((w, h), Image.BILINEAR), np.float32)


def ai_light(
    scene: np.ndarray, det: np.ndarray, L: Layers, sil: np.ndarray
) -> tuple[np.ndarray, dict]:
    """A smooth, neutral, clamped light map (HxW) from the model's image, or ones.

    Measured only on clean paper and blurred far beyond glyph size, so the model's print,
    texture and edges cannot reach the package; exposure-neutral, so the Figma colours hold.
    """
    h, w = sil.shape
    ones = np.ones((h, w), np.float32)
    iou = model_board_iou(scene, sil)
    info = {"ai_iou": round(iou, 3)}
    if iou < AI_MIN_IOU:
        return ones, {**info, "ai_used": False, "ai_reason": "board_mismatch"}
    clean = clean_paper(L, sil)
    if clean.sum() < AI_MIN_CLEAN * max(1, int((sil >= 0.999).sum())):
        return ones, {**info, "ai_used": False, "ai_reason": "too_little_clean_paper"}
    light = broad_light(scene, det, clean, AI_LIGHT_RANGE)
    light = 1 + (light - 1) * (sil >= 0.999)  # only inside the board, never on its outline
    return light, {**info, "ai_used": True}


def run_generate(
    ctx: JobContext, vid: str, mode: FlatMode | None = None, look_style: str | None = None
) -> dict:
    """Step 2: one flat, unfolded render at the final size, on black.

    The print, board, cuts, folds and background are deterministic (see ``shading``). In
    ``ai_appearance`` mode the image model may only add a gentle light map (``ai_light``).
    """
    pid = ctx.project_id
    if repo.get("versions", vid) is None:
        raise ApiError(404, "VERSION_NOT_FOUND", "버전을 찾을 수 없습니다.")
    spec = specs.load(repo.project_or_404(pid))
    mode = mode or get_settings().flat_render_mode
    flat_look = FLAT_LOOKS[look_style or get_settings().flat_look]
    long_edge = get_settings().flat_long_edge
    vdir = repo.project_dir(pid) / "versions"
    vdir.mkdir(exist_ok=True)

    ctx.stage("render", "running")
    layers = get_layers(pid, spec, long_edge, FLAT_LOOK.lighting.margin)
    parts = shading.render_parts(layers, flat_look)
    det = shading.to8(parts.rgb)
    Image.fromarray(det).save(vdir / f"{vid}_deterministic.png")
    h, w = det.shape[:2]
    ctx.stage("render", "done", {"size": [w, h], "mode": mode, "look": flat_look.style})
    ctx.check_cancel()

    light = np.ones((h, w), np.float32)
    info: dict = {"ai_used": False}
    usage: dict = {}
    if mode == "ai_appearance":
        ctx.stage("model", "running")
        pad = provider_preview(det, spec)
        req = GenerationRequest(
            prompt=flat_prompt(pid, spec),
            images=[
                ("Image 1 — exact Figma print and die-cut structure (final):", pad.image),
                (
                    "Image 2 — photograph for paperboard and lighting only:",
                    Image.open(FLAT_LOOK_IMAGE).convert("RGB"),
                ),
            ],
            width=pad.image.width,
            height=pad.image.height,
        )
        result = providers.PROVIDER.generate(req, IMAGE_MODEL.model_id)
        usage = result.usage
        result.image.save(vdir / f"{vid}_raw.png")
        ctx.stage("model", "done")
        ctx.check_cancel()
        scene = registered(result.image, pad, w, h)
        light, info = ai_light(scene, parts.rgb, layers, parts.sil)
    else:
        ctx.stage("model", "skipped")

    ctx.stage("composite", "running")
    gain = parts.gain * light
    board = np.clip(parts.print_rgb * gain[..., None], 0, 1)
    # Outside the board: our black ground and contact shadow, never the model's pixels.
    s = parts.sil[..., None]
    final = shading.to8(parts.background * (1 - s) + board * s)
    print8 = shading.to8(parts.print_rgb)
    ctx.stage("composite", "done", info)

    ctx.stage("verify", "running")
    check = look.verify_flat(
        final,
        print8,
        parts.sil,
        gain,
        layers.artwork[..., 3],
        background=shading.hex_rgb(FLAT_LOOK.lighting.background_color),
        colour_regions=figma_colour_regions(pid, layers, print8),
        px_per_mm=layers.px_per_mm,
    )
    check.update(info, mode=mode, look=flat_look.style, size=[w, h])
    ctx.stage("verify", "done", check)
    _, crop = frame(spec, long_edge, FLAT_LOOK.lighting.margin)
    deliver(
        pid,
        vid,
        final,
        check,
        frame_json={"origin": [crop[0], crop[1]], "size": [crop[2] - crop[0], crop[3] - crop[1]]},
        usage_json=usage,
    )
    return {"version_id": vid}


@dataclass
class Composited:
    image: np.ndarray  # final RGB uint8
    print_img: np.ndarray | None = None  # the PDF print the package was built from (uint8)
    gain: np.ndarray | None = None  # package = print x gain
    print_mask: np.ndarray | None = None  # print edges, where the surface was filled in
    scene: np.ndarray | None = None  # the model's image, float RGB
    colour_regions: list | None = None  # (Figma colour, pixel mask) for the colour check


def composite(
    base_img: np.ndarray,
    sil: np.ndarray,
    raw: Image.Image,
    pid: str,
    spec: Specification,
    long_edge: int,
) -> Composited:
    """Step 3, flat form: the reference scene from the model around our deterministic board.

    The package is our print x the deterministic paper gain x a smooth, neutral light map from
    the scene (``ai_light``-style, no glyph-scale transfer), so the model's own print, texture
    and edges never reach it. Outside the exact silhouette the scene is kept: it is the
    reference's world.
    """
    h, w = base_img.shape[:2]
    scene = np.asarray(cover(raw, w, h)).astype(np.float32) / 255
    layers = get_layers(pid, spec, long_edge, FLAT_LOOK.lighting.margin)
    parts = shading.render_parts(layers, FLAT_LOOK)
    light = scene_light(scene, parts.rgb, layers, sil)
    gain = parts.gain * light
    print8 = shading.to8(parts.print_rgb)
    pkg = np.clip(print8.astype(np.float32) / 255 * gain[..., None], 0, 1)
    t_img, _, _ = render_image(pid, spec, long_edge, transparent=True)
    shadow = np.clip(t_img[..., 3].astype(np.float32) / 255 - sil, 0, 1)
    s = sil[..., None]
    out = scene * (1 - shadow[..., None]) * (1 - s) + pkg * s
    regions = figma_colour_regions(pid, layers, print8)
    edges = surface.print_edges(parts.print_rgb, sil, layers.px_per_mm)
    gain3 = np.repeat(gain[..., None], 3, axis=-1)
    return Composited(shading.to8(out), print8, gain3, edges, scene, regions)


def scene_light(scene: np.ndarray, det: np.ndarray, L: Layers, sil: np.ndarray) -> np.ndarray:
    """Broad scene light on the board for a merge: like ``ai_light`` but without the black
    ground check (the reference's world is not black), wider range for a real scene."""
    clean = clean_paper(L, sil)
    if clean.sum() < AI_MIN_CLEAN * max(1, int((sil >= 0.999).sum())):
        clean = sil >= 0.999
    return broad_light(scene, det, clean, look.LIGHT_RANGE)


def figma_colour_regions(pid: str, layers: Layers, print8: np.ndarray) -> list:
    """Pixels of each solid Figma text/graphic colour, to check the result against Figma."""
    content = figma_content(pid) or {}
    rgb = print8.astype(np.float32) / 255
    h, w = rgb.shape[:2]
    out = []
    for item in content.get("texts", []) + content.get("graphics", []):
        if item.get("technical") or not item.get("color") or not item.get("bbox"):
            continue
        hexv = item["color"].lstrip("#")[:6]
        target = np.array([int(hexv[i : i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)
        x0, y0, x1, y1 = item["bbox"]
        ox, oy = layers.origin
        c0 = max(0, int((x0 - ox) * layers.scale))
        r0 = max(0, int((y0 - oy) * layers.scale))
        c1 = min(w, int(np.ceil((x1 - ox) * layers.scale)))
        r1 = min(h, int(np.ceil((y1 - oy) * layers.scale)))
        if c1 - c0 < 3 or r1 - r0 < 3:
            continue
        # The item's own pixels: inside its box and drawn in its colour (glyph interiors).
        near = ndimage.binary_erosion(look.delta_e(rgb[r0:r1, c0:c1], target) < 8, iterations=1)
        if near.sum() >= 20:
            close = np.zeros((h, w), bool)
            close[r0:r1, c0:c1] = near
            out.append((target, close))
    return out


def verify(result: Composited, sil: np.ndarray) -> dict:
    """The package is the PDF print x a surface map that carries none of the model's print."""
    return look.verify(
        result.image,
        result.print_img,
        sil,
        result.gain,
        result.print_mask,
        result.scene,
        result.colour_regions,
    )


def cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale to cover w x h and center-crop (providers may return a different aspect)."""
    s = max(w / img.width, h / img.height)
    r = img.resize((max(w, round(img.width * s)), max(h, round(img.height * s))), Image.LANCZOS)
    x, y = (r.width - w) // 2, (r.height - h) // 2
    return r.crop((x, y, x + w, y + h)).convert("RGB")
