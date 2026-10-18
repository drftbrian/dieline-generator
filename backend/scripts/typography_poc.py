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
from app.services import photo_first, specs  # noqa: E402
from app.storage import repo  # noqa: E402
from app.typography import correct  # noqa: E402
from app.typography import register as rg  # noqa: E402


def _png(a: np.ndarray, path: Path) -> None:
    Image.fromarray(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8)).save(path)


def _crops(photo, result: correct.Correction, path: Path) -> None:
    """400% crops of every verified item and unexpected mark: raw | corrected | strict."""
    rows = []
    imgs = [photo, result.corrected, result.strict]
    for face in result.faces:
        if not face.registration["ok"]:
            continue
        H = rg.homography(np.array(face.registration["quad_px"]))
        boxes = [(f"{v['id']} {v['status']}", v["window_px"]) for v in face.items if "window_px" in v]
        boxes += [(f"unexpected {i}", u["bbox_px"]) for i, u in enumerate(face.unexpected)]
        for label, win in boxes:
            x0, y0, x1, y1 = correct.photo_box(H, face.raster, win)
            x0, y0 = max(0, x0 - 12), max(0, y0 - 12)
            x1 = min(photo.shape[1], x1 + 12, x0 + 260)  # long items: their start, at 400%
            y1 = min(photo.shape[0], y1 + 12, y0 + 260)
            if x1 <= x0 or y1 <= y0:
                continue
            tiles = [
                Image.fromarray((np.clip(im[y0:y1, x0:x1], 0, 1) * 255).astype(np.uint8)).resize(
                    ((x1 - x0) * 4, (y1 - y0) * 4), Image.NEAREST
                )
                for im in imgs
            ]
            row = Image.new("RGB", (sum(t.width for t in tiles) + 40, tiles[0].height + 36), (255, 255, 255))
            ImageDraw.Draw(row).text((6, 6), f"{face.face_id} {label}   raw | text-corrected | strict (400%)", fill=(0, 0, 0))
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
        sheet.save(path, quality=90)


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
    man, pdf = photo_first.source(a.pid, spec)
    (out / "figma_typography_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1))

    raw_bytes = a.photo.read_bytes()
    raw_copy = out / f"model_raw{a.photo.suffix.lower()}"
    shutil.copyfile(a.photo, raw_copy)
    photo = np.asarray(Image.open(a.photo).convert("RGB"), np.float32) / 255
    faces = json.loads(a.faces.read_text())["faces"]
    result = correct.correct_photo(photo, pdf, spec.panels, man["items"], faces)

    _png(result.corrected, out / "photo_first_text_corrected.png")
    _png(result.strict, out / "strict_artwork.png")
    _png(result.masks, out / "text_repair_masks.png")
    result.preview.save(out / "text_repair_preview.png")
    (out / "visible_face_registration.json").write_text(
        json.dumps([f.registration for f in result.faces], indent=1)
    )
    (out / "text_logo_verification.json").write_text(
        json.dumps(result.verification(), ensure_ascii=False, indent=1)
    )
    report = {
        **result.report(),
        "raw_sha1": hashlib.sha1(raw_bytes).hexdigest(),
        "raw_unchanged": hashlib.sha1(raw_copy.read_bytes()).hexdigest() == hashlib.sha1(raw_bytes).hexdigest(),
        "seconds": round(time.time() - t0, 1),
        "no_model_calls": True,
    }
    (out / "text_correction_quality_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    _crops(photo, result, out / "crops.jpg")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
