"""Finished flat versions (②): a flat render with a finishing revision baked in, as a new
version (the source render and the finishing specification are never changed).

Optional "AI 사실감": for each selective finish area (foil, relief, spot UV) the image model gets
our deterministic render of that area plus real photographs of the same finish (the local study
set) and re-photographs it. From its picture we keep only a bounded *luminance* map (light,
reflections, micro texture), measured against our render and applied inside that finish's own
mask. Shapes, positions, colours and everything outside the masks stay ours; an area whose
picture does not line up with ours, or would change too much, keeps the deterministic result.

Saved next to the version (``versions/<vid>_*``): the deterministic finished image, per area the
model's raw image and the luminance map, and ``_finishing.json`` (revision, assignments, checks).
"""

from __future__ import annotations

import json
import unicodedata

import numpy as np
from PIL import Image
from scipy import ndimage

from app.ai import prompts, providers
from app.ai.models import IMAGE_MODEL
from app.ai.providers.base import GenerationRequest
from app.ai.providers.gemini import nearest_ratio
from app.config import get_settings
from app.errors import ApiError
from app.finishing import catalog, compose
from app.finishing import spec as fspec
from app.jobs.runner import JobContext
from app.render import shading
from app.render.finishing import material
from app.services import pipeline, specs
from app.services.enhance import sha
from app.storage import repo

AI_MODELS = ("metal", "relief", "clearcoat")  # finishes the model may re-photograph
MAX_AREAS = 4  # model calls per version
MAX_AREA_SHARE = 0.3  # larger finishes (whole-sheet coats) are not sent: too much artwork
AREA_PAD_MM = 3.0
GEN_EDGE = (1024, 2048)  # the model's image of an area: long edge between these
GAIN_RANGE = (0.6, 1.5)  # luminance the model may give a finish pixel, relative to ours
DETAIL_SIGMA_MM = 0.05  # finer than this is the model's resampling noise, not material
MIN_EDGE_CORR = 0.55  # its picture's edges against ours, or the area is not used
MAX_EXTREME = 0.04  # share of the mask whose raw gain falls outside GAIN_RANGE
DEFAULT_STRENGTH = 0.7

# Study photos per finish (file names contain these words).
REFERENCE_WORDS = {
    "foil.gold": ("금박",),
    "foil.silver": ("은박",),
    "foil.black": ("먹박",),
    "foil.black_matte": ("먹박",),
    "foil.white": ("백박",),
    "foil.red": ("적박",),
    "foil.red_metallic": ("적박",),
    "foil.green": ("녹박",),
    "foil.green_metallic": ("녹박",),
    "foil.blue": ("청박",),
    "foil.blue_metallic": ("청박",),
    "foil.holographic": ("홀로그램",),
    "relief.emboss": ("엠보싱",),
    "relief.deboss": ("디보싱",),
    "coating.spot_uv": ("부분",),
    "coating.varnish_gloss": ("부분", "유광"),
}


def reference_photos(finish_id: str, limit: int = 2) -> list[tuple[str, Image.Image]]:
    """Up to ``limit`` local study photos of a finish (none when the folder is missing)."""
    folder = get_settings().finish_reference_dir
    words = REFERENCE_WORDS.get(finish_id, ())
    if not words or not folder.is_dir():
        return []
    out = []
    for f in sorted(folder.iterdir()):
        name = unicodedata.normalize("NFC", f.name)  # macOS stores Hangul file names decomposed
        if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and any(w in name for w in words):
            try:
                im = Image.open(f).convert("RGB")
            except OSError:
                continue
            im.thumbnail((1024, 1024))
            out.append((name, im))
        if len(out) >= limit:
            break
    return out


def _lum(rgb: np.ndarray) -> np.ndarray:
    return rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)


def _padded(crop: np.ndarray) -> pipeline.Padded:
    """The area on a canvas of a supported aspect, its long edge within GEN_EDGE."""
    h, w = crop.shape[:2]
    k = min(GEN_EDGE[1], max(GEN_EDGE[0], max(w, h))) / max(w, h)
    w2, h2 = max(16, round(w * k)), max(16, round(h * k))
    rw, rh = (int(v) for v in nearest_ratio(w2, h2).split(":"))
    cw, ch = (w2, round(w2 * rh / rw)) if w2 / h2 > rw / rh else (round(h2 * rw / rh), h2)
    canvas = Image.new("RGB", (cw, ch), (0, 0, 0))
    x0, y0 = (cw - w2) // 2, (ch - h2) // 2
    canvas.paste(Image.fromarray(crop).resize((w2, h2), Image.LANCZOS), (x0, y0))
    return pipeline.Padded(canvas, (x0, y0, x0 + w2, y0 + h2))


def _edges(lum: np.ndarray) -> np.ndarray:
    return np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1))


def edge_corr(ours: np.ndarray, theirs: np.ndarray, where: np.ndarray) -> float:
    """Pearson correlation of edge strength (does their picture keep our shapes in place?)."""
    a, b = _edges(_lum(ours))[where], _edges(_lum(theirs))[where]
    if a.size < 16 or a.std() < 1e-6 or b.std() < 1e-6:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def luminance_gain(ours: np.ndarray, theirs: np.ndarray, px_per_mm: float) -> np.ndarray:
    """Their luminance relative to ours, lightly smoothed (raw, not clamped)."""
    s = max(0.5, DETAIL_SIGMA_MM * px_per_mm)
    lo = ndimage.gaussian_filter(_lum(ours), s)
    li = ndimage.gaussian_filter(_lum(theirs), s)
    return li / np.maximum(lo, 0.03)


NOT_WORSE = 0.03  # luminance: how much further from the photos the AI may land


def photo_distance(f: catalog.Finish, rgb: np.ndarray, inside: np.ndarray) -> float | None:
    """How far a metal foil's tones (5th / 50th / 98th percentile luminance) are from those
    measured on real photos of that foil (None for finishes without measured tones)."""
    if f.model != "metal" or not inside.any():
        return None
    cal = material.calibration()["gold" if f.id == "foil.gold" else "silver"]
    if float(_lum(material._rgb(f.color))) < 0.35:
        return None  # dark / coloured metals: the photo levels are for bright metals
    lum = _lum(rgb)[inside]
    got = np.percentile(lum, [5, 50, 98])
    want = np.array([cal["shadow"], cal["body"], cal["highlight"]])
    return round(float(np.abs(got - want).mean()), 4)


def areas(c: compose.Composed) -> list[tuple[catalog.Finish, dict, np.ndarray]]:
    """Selective finishes the model may re-photograph, largest first, at most MAX_AREAS."""
    picked = [
        (f, p, m)
        for f, p, m in c.stack
        if f.model in AI_MODELS and f.scope != "surface" and 0 < (m > 0).sum()
    ]
    picked = [x for x in picked if (x[2] > 0).sum() <= MAX_AREA_SHARE * c.image[..., 0].size]
    picked.sort(key=lambda x: -int((x[2] > 0).sum()))
    return picked[:MAX_AREAS]


def run_finish(ctx: JobContext, vid: str) -> dict:
    pid = ctx.project_id
    v = repo.get("versions", vid)
    if v is None:
        raise ApiError(404, "VERSION_NOT_FOUND", "버전을 찾을 수 없습니다.")
    params = v["settings_json"]
    src = repo.get("versions", params["source_version_id"])
    spec = specs.load(repo.project_or_404(pid))
    fin = fspec.load_revision(pid, int(params["finishing_revision"]))
    use_ai = bool(params.get("ai"))
    strength = float(params.get("strength", DEFAULT_STRENGTH))
    vdir = repo.project_dir(pid) / "versions"
    src_path = vdir / f"{src['id']}.png"
    src_sha = sha(src_path)

    ctx.stage("compose", "running")
    c = compose.compose(pid, spec, src["id"], fin, params.get("light") or "top")
    if c.box is None:
        raise ApiError(409, "FINISHING_EMPTY", "적용된 후가공이 없습니다.")
    finished = c.full()
    Image.fromarray(finished).save(vdir / f"{vid}_deterministic.png")
    changed = c.changed_full()
    y0, x0, _, _ = c.box
    ctx.stage("compose", "done", {"finishes": len(c.stack), "changed_px": int(changed.sum())})
    ctx.check_cancel()

    usage: dict = {}
    report: list[dict] = []
    final = finished.copy()
    if use_ai:
        ctx.stage("model", "running")
        px_per_mm = c.scene.px_per_mm if c.scene else 1.0
        pad = int(AREA_PAD_MM * px_per_mm)
        for i, (f, _p, m) in enumerate(areas(c)):
            ys, xs = np.nonzero(m > 0)
            ay0, ax0 = max(0, ys.min() - pad), max(0, xs.min() - pad)
            ay1, ax1 = min(m.shape[0], ys.max() + 1 + pad), min(m.shape[1], xs.max() + 1 + pad)
            gy0, gx0 = y0 + ay0, x0 + ax0  # in the full image
            ours8 = final[gy0 : gy0 + (ay1 - ay0), gx0 : gx0 + (ax1 - ax0)]
            padded = _padded(ours8)
            refs = reference_photos(f.id)
            req = GenerationRequest(
                prompt=prompts.render(
                    "finish_realism",
                    finish=f"{f.label_en} ({f.label_ko})",
                    material=prompts.text(f"finish_realism_{f.model}"),
                ),
                images=[
                    ("Image 1 — our render of the area (exact shapes, final):", padded.image),
                    *[
                        (f"Image {k + 2} — real photograph of {f.label_en} (material only):", im)
                        for k, (_, im) in enumerate(refs)
                    ],
                ],
                width=padded.image.width,
                height=padded.image.height,
            )
            result = providers.PROVIDER.generate(req, IMAGE_MODEL.model_id)
            for key, n in (result.usage or {}).items():
                if isinstance(n, int | float):
                    usage[key] = usage.get(key, 0) + n
            result.image.save(vdir / f"{vid}_area{i}_raw.png")
            hh, ww = ours8.shape[:2]
            theirs = pipeline.registered(result.image, padded, ww, hh)
            ours = ours8.astype(np.float32) / 255
            mm = m[ay0:ay1, ax0:ax1]
            near = ndimage.binary_dilation(mm > 0, iterations=max(2, int(0.3 * px_per_mm)))
            corr = edge_corr(ours, theirs, near)
            gain = luminance_gain(ours, theirs, px_per_mm)
            inside = mm > 0.5
            extreme = float(
                ((gain < GAIN_RANGE[0]) | (gain > GAIN_RANGE[1]))[inside].mean()
                if inside.any()
                else 1.0
            )
            entry = {
                "finish": f.id,
                "box": [int(gx0), int(gy0), int(ww), int(hh)],
                "edge_corr": round(corr, 3),
                "extreme": round(extreme, 4),
                "references": [n for n, _ in refs],
            }
            if corr < MIN_EDGE_CORR:
                entry["used"], entry["reason"] = False, "misaligned"
            elif extreme > MAX_EXTREME:
                entry["used"], entry["reason"] = False, "too_different"
            else:
                g = 1 + (np.clip(gain, *GAIN_RANGE) - 1) * strength
                k = mm[..., None]
                new = np.clip(ours * (1 + k * (g[..., None] - 1)), 0, 1)
                # Adopted only if it is not measurably further from real photos of this
                # finish than our own render (metals: tone percentiles from calibration).
                before, after = photo_distance(f, ours, inside), photo_distance(f, new, inside)
                entry["photo_distance"] = [before, after]
                if before is not None and after is not None and after > before + NOT_WORSE:
                    entry["used"], entry["reason"] = False, "not_better"
                else:
                    region = final[gy0 : gy0 + hh, gx0 : gx0 + ww]
                    region[mm > 0] = shading.to8(new)[mm > 0]
                    np.save(vdir / f"{vid}_area{i}_gain.npy", g.astype(np.float32))
                    entry["used"] = True
            report.append(entry)
            ctx.check_cancel()
        ctx.stage("model", "done", {"areas": report})
    else:
        ctx.stage("model", "skipped")

    ctx.stage("verify", "running")
    source = np.asarray(Image.open(src_path).convert("RGB"))
    outside_same = bool(np.array_equal(final[~changed], source[~changed]))
    used = [a for a in report if a.get("used")]
    checks = {
        "outside_unchanged": outside_same,  # nothing outside the finish regions moved
        "source_unchanged": sha(src_path) == src_sha,
    }
    n = int(changed.sum())
    check = {
        "protected_px": int((~changed).sum()),
        "changed_px": n,
        "changed_ratio": round(n / changed.size, 5),
        "match": all(checks.values()),
        "checks": checks,
        "mode": "finished",
        "size": [int(finished.shape[1]), int(finished.shape[0])],
        "ai_used": bool(used),
        "ai_reason": None
        if used or not use_ai
        else ("no_areas" if not report else "areas_rejected"),
        "strength_applied": strength if used else None,
        "source_unchanged": checks["source_unchanged"],
    }
    ctx.stage("verify", "done", check)
    manifest = {
        "mode": "finished",
        "source_version_id": src["id"],
        "source_sha256": src_sha,
        "finishing_revision": fin.revision,
        "assignments": [a.model_dump() for a in fin.assignments],
        "ai": use_ai,
        "model_id": IMAGE_MODEL.model_id if use_ai else None,
        "strength": strength,
        "areas": report,
        "check": check,
    }
    (vdir / f"{vid}_finishing.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    pipeline.deliver(pid, vid, final, check, frame_json=src["frame_json"], usage_json=usage)
    return {"version_id": vid}
