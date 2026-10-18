"""One generated photo, corrected: every visible face registered, verified and restored.

Shared by the step ③ job (``services.photo_first``) and ``scripts/typography_poc.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw

from app.spec.models import Panel
from app.typography import register as rg
from app.typography import restore

STATUSES = ("match", "misplaced", "approximate", "mismatch", "not_verifiable", "unresolved", "not_visible")
STATUS_COLOURS = {
    "match": (40, 200, 80),
    "misplaced": (255, 170, 0),
    "approximate": (255, 230, 0),
    "mismatch": (230, 30, 30),
    "not_verifiable": (120, 120, 255),
    "unresolved": (200, 0, 200),
    "not_visible": (128, 128, 128),
}
REGISTER_EDGE = 640  # px, long edge of the source panel used for registration


@dataclass
class Correction:
    corrected: np.ndarray  # HxWx3 float, text-corrected
    strict: np.ndarray  # HxWx3 float, strict artwork
    masks: np.ndarray  # HxWx3 float: text-corrected / strict / backdrop repair masks
    preview: Image.Image  # the raw photo with faces, item verdicts and unexpected marks drawn
    faces: list[restore.FaceResult] = field(default_factory=list)
    background: dict | None = None
    review: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "review_required" if self.review else "ok"

    @property
    def registered(self) -> int:
        return sum(1 for f in self.faces if f.registration.get("ok"))

    def report(self) -> dict:
        return {
            "status": self.status,
            "review": self.review,
            "faces": [
                {
                    "face_id": f.face_id,
                    "registration": f.registration,
                    "light": f.light,
                    "after": f.after,
                    "items": {s: sum(1 for v in f.items if v["status"] == s) for s in STATUSES},
                    "unexpected": len(f.unexpected),
                }
                for f in self.faces
            ],
            "background": self.background,
        }

    def verification(self) -> list[dict]:
        return [{"face_id": f.face_id, "items": f.items, "unexpected": f.unexpected} for f in self.faces]


def photo_box(H: np.ndarray, shape: tuple[int, int], win) -> tuple[int, int, int, int]:
    """A panel-raster box (``win``) as a photo-pixel box through the face homography."""
    h, w = shape
    x0, y0, x1, y1 = win
    x, y = rg.apply_h(H, np.array([x0, x1, x1, x0]) / w, np.array([y0, y0, y1, y1]) / h)
    return int(x.min()), int(y.min()), int(np.ceil(x.max())), int(np.ceil(y.max()))


EDGE_TOL_PT = 8.0  # panels whose edges are this close in the net share a fold


def shared_edge_start(panel: Panel, guess: np.ndarray, regs: dict, by_id: dict) -> np.ndarray | None:
    """A starting quad for ``panel`` from a registered neighbour sharing a vertical fold edge:
    the shared corners are the neighbour's, the other two the user's guess moved alike."""
    for nid, reg in regs.items():
        if not reg.ok or nid == panel.id:
            continue
        n = by_id[nid]
        if abs(panel.bbox[3] - n.bbox[3]) > EDGE_TOL_PT * 4:
            continue  # not side by side
        q = guess.copy()
        if abs(panel.bbox[2] - n.bbox[0]) < EDGE_TOL_PT:  # neighbour on the right
            shared, ours = (0, 3), (1, 2)
        elif abs(panel.bbox[0] - n.bbox[2]) < EDGE_TOL_PT:  # neighbour on the left
            shared, ours = (1, 2), (0, 3)
        else:
            continue
        delta = (reg.quad[list(shared)] - guess[list(ours)]).mean(0)
        q[list(ours)] = reg.quad[list(shared)]
        other = [i for i in range(4) if i not in ours]
        q[other] = guess[other] + delta
        return q
    return None


def correct_photo(
    photo: np.ndarray, pdf: bytes, panels: list[Panel], items: list[dict], faces: list[dict]
) -> Correction:
    """``faces``: ``[{"panel": id, "quad": [[x, y] x4] photo px, panel TL TR BR BL}]``."""
    by_id = {p.id: p for p in panels}
    p_lum = rg.luminance(photo)
    corrected, strict = photo.copy(), photo.copy()
    mask_c = np.zeros(photo.shape[:2], np.float32)
    mask_s = np.zeros(photo.shape[:2], np.float32)
    texs = {}
    for f in faces:
        p = by_id[f["panel"]]
        w_pt, h_pt = p.bbox[2] - p.bbox[0], p.bbox[3] - p.bbox[1]
        k = REGISTER_EDGE / max(w_pt, h_pt)
        texs[p.id] = rg.luminance(
            restore.render_panel(pdf, p.bbox, (max(8, round(w_pt * k)), max(8, round(h_pt * k))))
        )
    regs = {f["panel"]: rg.refine(f["panel"], p_lum, texs[f["panel"]], f["quad"]) for f in faces}
    # A face that was not found starts again from its registered neighbour: adjacent panels
    # share their fold edge, so two of its corners are known.
    for f in faces:
        if regs[f["panel"]].ok:
            continue
        start = shared_edge_start(by_id[f["panel"]], np.asarray(f["quad"], float), regs, by_id)
        if start is not None:
            retry = rg.refine(f["panel"], p_lum, texs[f["panel"]], start)
            if retry.ok:
                regs[f["panel"]] = retry

    results = []
    for f in faces:
        p = by_id[f["panel"]]
        face_items = [i for i in items if i["panel_id"] == p.id]
        reg = regs[p.id]
        src = restore.face_source(pdf, p.id, p.name, p.bbox, reg.quad, face_items)
        res, layers = restore.correct_face(photo, reg, src, face_items)
        results.append(res)
        if layers:
            corrected, mc = restore.composite(corrected, reg.H, *layers["text_corrected"])
            strict, ms = restore.composite(strict, reg.H, *layers["strict"])
            mask_c, mask_s = np.maximum(mask_c, mc), np.maximum(mask_s, ms)

    mask_b = np.zeros(photo.shape[:2], np.float32)
    background = None
    quads = [r.quad for r in regs.values() if r.ok]
    if quads:
        corrected, mask_b, background = restore.clean_background(corrected, quads)
        strict = strict + mask_b[..., None] * (corrected - strict)

    preview = Image.fromarray((np.clip(photo, 0, 1) * 255).astype(np.uint8))
    d = ImageDraw.Draw(preview)
    width = max(2, round(max(photo.shape[:2]) / 700))
    for res in results:
        reg = regs[res.face_id]
        if not reg.ok:
            continue
        d.polygon([tuple(q) for q in reg.quad], outline=(0, 160, 255), width=width)
        for v in res.items:
            if "window_px" in v:
                box = photo_box(reg.H, res.raster, v["window_px"])
                d.rectangle(box, outline=STATUS_COLOURS[v["status"]], width=width)
        for u in res.unexpected:
            box = photo_box(reg.H, res.raster, u["bbox_px"])
            d.rectangle(box, outline=(255, 0, 255) if u["large"] else (255, 0, 0), width=width + 2)

    review = [m for r in results for m in r.review]
    for r in results:
        for mode, v in r.after.items():
            if not v["shading"]["preserved"]:
                review.append(f"{r.face_id}/{mode}: shading changed outside removed content")
            if v["remaining_unexpected"]:
                review.append(f"{r.face_id}/{mode}: {v['remaining_unexpected']} unexpected marks remain")
    return Correction(corrected, strict, np.stack([mask_c, mask_s, mask_b], -1), preview, results, background, review)
