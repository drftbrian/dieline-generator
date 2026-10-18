"""Typography-correction proof of concept (PRD v2 §4A) on an existing generated photo.

No model is called: the input is an already generated photo-first image (e.g. the external
ZENTRA prototype). The project data is only read; everything is written to OUT_DIR.

    uv run python scripts/typography_poc.py PID PHOTO FACES_JSON OUT_DIR

FACES_JSON: {"faces": [{"panel": "panel8", "quad": [[x, y] x4]}, ...]} with rough photo-pixel
corners of each visible panel in panel order TL, TR, BR, BL (refined automatically).

Writes the PRD's files: figma_typography_manifest.json, visible_face_registration.json,
text_logo_verification.json, text_repair_masks.png, text_repair_preview.png,
photo_first_text_corrected.png, strict_artwork.png, text_correction_quality_report.json,
model_raw.<ext> (a byte copy), and crops.jpg (raw | corrected | strict at 400%).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import BACKEND_DIR  # noqa: E402
from app.finishing import assets as fa  # noqa: E402
from app.render.layers import make_artwork_pdf, structure_key  # noqa: E402
from app.services import specs  # noqa: E402
from app.storage import repo  # noqa: E402
from app.typography import manifest, restore  # noqa: E402
from app.typography import register as rg  # noqa: E402

STATUS_COLOURS = {
    "match": (40, 200, 80),
    "misplaced": (255, 170, 0),
    "approximate": (255, 230, 0),
    "mismatch": (230, 30, 30),
    "not_verifiable": (120, 120, 255),
    "unresolved": (200, 0, 200),
    "not_visible": (128, 128, 128),
}


def _png(a: np.ndarray, path: Path) -> None:
    Image.fromarray(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8)).save(path)


def _photo_box(H: np.ndarray, src: restore.FaceSource, win) -> tuple[int, int, int, int]:
    h, w = src.rgb.shape[:2]
    x0, y0, x1, y1 = win
    u = np.array([x0, x1, x1, x0]) / w
    v = np.array([y0, y0, y1, y1]) / h
    x, y = rg.apply_h(H, u, v)
    return int(x.min()), int(y.min()), int(np.ceil(x.max())), int(np.ceil(y.max()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pid")
    ap.add_argument("photo", type=Path)
    ap.add_argument("faces", type=Path)
    ap.add_argument("out", type=Path)
    a = ap.parse_args()
    out = a.out.resolve()
    if (BACKEND_DIR / "data").resolve() in out.parents:
        sys.exit("refusing to write into backend/data")
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    spec = specs.load(repo.project_or_404(a.pid))
    source_kind, assets = fa.project_assets(a.pid, spec)
    art = repo.project_dir(a.pid) / f"artwork-{structure_key(spec)}.pdf"
    pdf = art.read_bytes() if art.exists() else make_artwork_pdf(repo.read_source(a.pid), spec)
    vfile = repo.project_dir(a.pid) / "figma_assets.version"
    man = manifest.build(
        spec,
        assets,
        pdf,
        lambda i: fa.svg_path(a.pid, i).exists(),
        vfile.read_text().strip() if vfile.exists() else None,
    )
    man["source_kind"] = source_kind
    (out / "figma_typography_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1))

    raw_bytes = a.photo.read_bytes()
    raw_copy = out / f"model_raw{a.photo.suffix.lower()}"
    shutil.copyfile(a.photo, raw_copy)
    photo = np.asarray(Image.open(a.photo).convert("RGB"), np.float32) / 255
    p_lum = rg.luminance(photo)
    panels = {p.id: p for p in spec.panels}
    faces = json.loads(a.faces.read_text())["faces"]

    corrected, strict = photo.copy(), photo.copy()
    mask_c = np.zeros(photo.shape[:2], np.float32)
    mask_s = np.zeros(photo.shape[:2], np.float32)
    results, regs, sources = [], {}, {}
    for f in faces:
        p = panels[f["panel"]]
        items = [i for i in man["items"] if i["panel_id"] == p.id]
        tex = restore.render_panel(pdf, p.bbox, (640, max(8, round(640 * (p.bbox[3] - p.bbox[1]) / (p.bbox[2] - p.bbox[0])))))
        reg = rg.refine(p.id, p_lum, rg.luminance(tex), f["quad"])
        src = restore.face_source(pdf, p.id, p.name, p.bbox, reg.quad, items)
        res, layers = restore.correct_face(photo, reg, src, items)
        results.append(res)
        regs[p.id], sources[p.id] = reg, src
        if layers:
            corrected, mc = restore.composite(corrected, reg.H, *layers["text_corrected"])
            strict, ms = restore.composite(strict, reg.H, *layers["strict"])
            mask_c, mask_s = np.maximum(mask_c, mc), np.maximum(mask_s, ms)
    quads = [regs[k].quad for k in regs if regs[k].ok]
    bg_report = None
    mask_b = np.zeros(photo.shape[:2], np.float32)
    if quads:
        corrected, mask_b, bg_report = restore.clean_background(corrected, quads)
        strict = strict + mask_b[..., None] * (corrected - strict)

    _png(corrected, out / "photo_first_text_corrected.png")
    _png(strict, out / "strict_artwork.png")
    _png(np.stack([mask_c, mask_s, mask_b], -1), out / "text_repair_masks.png")

    preview = Image.fromarray((photo * 255).astype(np.uint8))
    d = ImageDraw.Draw(preview)
    for res in results:
        if res.face_id not in regs or not regs[res.face_id].ok:
            continue
        reg, src = regs[res.face_id], sources[res.face_id]
        d.polygon([tuple(q) for q in reg.quad], outline=(0, 160, 255), width=6)
        for v in res.items:
            if "window_px" in v:
                d.rectangle(_photo_box(reg.H, src, v["window_px"]), outline=STATUS_COLOURS[v["status"]], width=5)
        for u in res.unexpected:
            d.rectangle(_photo_box(reg.H, src, u["bbox_px"]), outline=(255, 0, 0) if not u["large"] else (255, 0, 255), width=8)
    preview.save(out / "text_repair_preview.png")

    (out / "visible_face_registration.json").write_text(
        json.dumps([r.registration for r in results], indent=1)
    )
    (out / "text_logo_verification.json").write_text(
        json.dumps(
            [{"face_id": r.face_id, "items": r.items, "unexpected": r.unexpected} for r in results],
            ensure_ascii=False,
            indent=1,
        )
    )
    review = [m for r in results for m in r.review]
    for r in results:
        for mode, v in r.after.items():
            if not v["shading"]["preserved"]:
                review.append(f"{r.face_id}/{mode}: shading changed outside removed content")
            if v["remaining_unexpected"]:
                review.append(f"{r.face_id}/{mode}: {v['remaining_unexpected']} unexpected marks remain")
    report = {
        "status": "review_required" if review else "ok",
        "review": review,
        "faces": [
            {"face_id": r.face_id, "light": r.light, "after": r.after,
             "items": {s: sum(1 for v in r.items if v["status"] == s) for s in STATUS_COLOURS}}
            for r in results
        ],
        "background": bg_report,
        "raw_sha1": hashlib.sha1(raw_bytes).hexdigest(),
        "raw_unchanged": hashlib.sha1(raw_copy.read_bytes()).hexdigest() == hashlib.sha1(raw_bytes).hexdigest(),
        "seconds": round(time.time() - t0, 1),
        "no_model_calls": True,
    }
    (out / "text_correction_quality_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))

    # 400% crops of every verified item and unexpected mark: raw | corrected | strict.
    rows = []
    imgs = [photo, corrected, strict]
    for res in results:
        if res.face_id not in regs or not regs[res.face_id].ok:
            continue
        reg, src = regs[res.face_id], sources[res.face_id]
        boxes = [(f"{v['id']} {v['status']}", v["window_px"]) for v in res.items if "window_px" in v]
        boxes += [(f"unexpected {i}", u["bbox_px"]) for i, u in enumerate(res.unexpected)]
        for label, win in boxes:
            x0, y0, x1, y1 = _photo_box(reg.H, src, win)
            x0, y0 = max(0, x0 - 12), max(0, y0 - 12)
            x1, y1 = min(photo.shape[1], x1 + 12), min(photo.shape[0], y1 + 12)
            if x1 - x0 > 260:  # long items: their start, at 400%
                x1 = x0 + 260
            if y1 - y0 > 260:
                y1 = y0 + 260
            tiles = [Image.fromarray((im[y0:y1, x0:x1] * 255).astype(np.uint8)).resize(((x1 - x0) * 4, (y1 - y0) * 4), Image.NEAREST) for im in imgs]
            row = Image.new("RGB", (sum(t.width for t in tiles) + 40, tiles[0].height + 36), (255, 255, 255))
            ImageDraw.Draw(row).text((6, 6), f"{res.face_id} {label}   raw | text-corrected | strict (400%)", fill=(0, 0, 0))
            x = 0
            for t in tiles:
                row.paste(t, (x, 30))
                x += t.width + 20
            rows.append(row)
    if rows:
        sheet = Image.new("RGB", (max(r.width for r in rows), sum(r.height for r in rows)), (255, 255, 255))
        y = 0
        for r in rows:
            sheet.paste(r, (0, y))
            y += r.height
        sheet.save(out / "crops.jpg", quality=90)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
