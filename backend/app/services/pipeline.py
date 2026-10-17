"""Processing pipelines run by background jobs: analysis, the structure render and step 2,
the flat photoreal render."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from app.ai import claude, prompts, providers
from app.ai.models import IMAGE_MODEL
from app.ai.providers.base import GenerationRequest
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
from app.spec.models import FLAT_LOOK, AiSuggestion, Specification
from app.storage import repo

log = logging.getLogger(__name__)

# The look reference for step 2 (Image 2): black background, top-down, matte white board.
FLAT_LOOK_IMAGE = prompts.DIR / "flat_look.png"
# Marks a version made by this pipeline; older rows are shown as legacy.
PIPELINE = 2

# ---- layer cache ---------------------------------------------------------------------

_cache: OrderedDict[str, Layers] = OrderedDict()
_cache_lock = threading.Lock()
CACHE_SIZE = 8


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

GEN_LONG_EDGE = 2048  # model output at 2K: fine ribs and fibres need it


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


def run_generate(ctx: JobContext, vid: str) -> dict:
    """Step 2: one flat, unfolded photoreal render in the fixed look (prompts/flat_render.md).

    Image 1 is our exact print, Image 2 the look reference. The model's image only lends the
    board's surface and light: the print is composited back from the PDF and verified.
    """
    pid = ctx.project_id
    if repo.get("versions", vid) is None:
        raise ApiError(404, "VERSION_NOT_FOUND", "버전을 찾을 수 없습니다.")
    spec = specs.load(repo.project_or_404(pid))

    ctx.stage("render", "running")
    w, h = gen_size(spec)
    long_edge = max(w, h)
    base_img, sil, _ = render_image(pid, spec, long_edge)
    base = Image.fromarray(base_img).convert("RGB").resize((w, h), Image.LANCZOS)
    prompt = flat_prompt(pid, spec)
    ctx.stage("render", "done")
    ctx.check_cancel()

    ctx.stage("model", "running")
    req = GenerationRequest(
        prompt=prompt,
        images=[
            ("Image 1 — exact Figma print, final structure:", base),
            ("Image 2 — visual reference (look only):", Image.open(FLAT_LOOK_IMAGE).convert("RGB")),
        ],
        width=w,
        height=h,
    )
    result = providers.PROVIDER.generate(req, IMAGE_MODEL.model_id)
    ctx.stage("model", "done")
    ctx.check_cancel()

    ctx.stage("composite", "running")
    vdir = repo.project_dir(pid) / "versions"
    vdir.mkdir(exist_ok=True)
    result.image.save(vdir / f"{vid}_raw.png")
    comp = composite(base_img, sil, result.image, pid, spec, long_edge)
    ctx.stage("composite", "done")

    ctx.stage("verify", "running")
    check = verify(comp, sil)
    ctx.stage("verify", "done", check)
    _, crop = frame(spec, long_edge, FLAT_LOOK.lighting.margin)
    deliver(
        pid,
        vid,
        comp.image,
        check,
        frame_json={"origin": [crop[0], crop[1]], "size": [crop[2] - crop[0], crop[3] - crop[1]]},
        usage_json=result.usage,
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
    """Scene and the board's surface photographed by the model; print from the PDF.

    The package is our print x the model's photographed board surface (fibres, sheen, folds,
    light). The model's own print is discarded; around print edges the surface is filled in
    from the surrounding board. See app/render/surface.py.
    """
    h, w = base_img.shape[:2]
    scene = np.asarray(cover(raw, w, h)).astype(np.float32) / 255
    layers = get_layers(pid, spec, long_edge, FLAT_LOOK.lighting.margin)
    m = FLAT_LOOK.material
    print_rgb = shading.print_surface(layers, m)
    gain, edges, valley = surface.transfer(
        print_rgb,
        scene,
        sil,
        layers.px_per_mm,
        ink=layers.artwork[..., 3],
        folds=layers.crease,
    )
    # Ink sits in the paper: slightly starved in the board's valleys.
    alpha = layers.artwork[..., 3] * (1 - surface.INK_STARVE * valley)
    print8 = (np.clip(shading.print_surface(layers, m, alpha), 0, 1) * 255 + 0.5).astype(np.uint8)
    pkg = np.clip(print8.astype(np.float32) / 255 * gain, 0, 1)
    t_img, _, _ = render_image(pid, spec, long_edge, transparent=True)
    shadow = np.clip(t_img[..., 3].astype(np.float32) / 255 - sil, 0, 1)
    s = sil[..., None]
    out = scene * (1 - shadow[..., None]) * (1 - s) + pkg * s
    regions = figma_colour_regions(pid, layers, print8)
    return Composited((out * 255 + 0.5).astype(np.uint8), print8, gain, edges, scene, regions)


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
        box = np.zeros((h, w), bool)
        box[r0:r1, c0:c1] = True
        # The item's own pixels: inside its box and drawn in its colour (glyph interiors).
        close = box & (look.delta_e(rgb, target) < 8)
        close = ndimage.binary_erosion(close, iterations=1)
        if close.sum() >= 20:
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
