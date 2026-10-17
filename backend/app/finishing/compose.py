"""A flat version with a finishing revision applied, at the version image's own resolution.

The finishes are rendered over the version's own pixels, only inside the finish regions (the
target masks from source geometry, plus a relief's shoulder); every other pixel is the
version image, bit for bit. Shared by the preview overlay and the finished-version job.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, replace

import numpy as np
from PIL import Image

from app.errors import ApiError
from app.finishing import assets as fa
from app.finishing import catalog, masks
from app.finishing import spec as fspec
from app.render.finishing import material
from app.render.layers import frame, structure_key
from app.services import pipeline
from app.spec.models import FLAT_LOOK, Specification
from app.storage import repo

CROP_PAD_MM = 2.5  # around the finish regions: room for relief shoulders and blurs


@dataclass
class Composed:
    image: np.ndarray  # HxWx3 uint8: the version image
    origin: tuple[float, float]  # page pt at pixel (0, 0)
    scale: float  # px per pt
    box: tuple[int, int, int, int] | None  # y0, x0, y1, x1 of the work area (None: no finish)
    finished: np.ndarray | None  # float RGB of the work area with the finishes
    changed: np.ndarray | None  # bool, the work area's pixels a finish changed
    stack: list[tuple[catalog.Finish, dict, np.ndarray]]  # finish, params, mask (work area)
    scene: material.Scene | None

    def full(self) -> np.ndarray:
        """The whole finished image (uint8)."""
        from app.render import shading

        out = self.image.copy()
        if self.box is not None:
            y0, x0, y1, x1 = self.box
            region = out[y0:y1, x0:x1]
            region[self.changed] = shading.to8(self.finished)[self.changed]
        return out

    def changed_full(self) -> np.ndarray:
        out = np.zeros(self.image.shape[:2], bool)
        if self.box is not None:
            y0, x0, y1, x1 = self.box
            out[y0:y1, x0:x1] = self.changed
        return out


def target_mask(
    pid, spec, t: fspec.Target, tree: dict, sil: np.ndarray, svgs: dict, long_edge: int, scale_of
) -> np.ndarray | None:
    """The target's mask on the version's frame (``sil`` = the board at that resolution)."""
    if t.kind == "sheet":
        return (sil > 0.001).astype(np.float32) * np.clip(sil, 0, 1)
    if t.kind == "panel":
        p = next((p for p in spec.panels if p.id == t.id), None)
        if p is None:
            return None
        (ox, oy), scale = scale_of
        x0, y0, x1, y1 = (
            int(round((v - o) * scale)) for v, o in zip(p.bbox, (ox, oy, ox, oy), strict=True)
        )
        m = np.zeros_like(sil)
        m[max(0, y0) : max(0, y1), max(0, x0) : max(0, x1)] = 1
        return m * np.clip(sil, 0, 1)
    asset = tree.get(t.id or "")
    if asset is None:
        return None
    svg = None
    if asset.get("exact"):
        svg = svgs.get(asset["id"])
        if svg is None:
            return None  # never guessed from the printed ink for Figma assets
    return masks.asset_mask(
        pid,
        spec,
        asset,
        long_edge,
        sil,
        svg,
        structure_key(spec),
        lambda: pipeline.get_layers(pid, spec, long_edge, FLAT_LOOK.lighting.margin),
    )


def compose(
    pid: str, spec: Specification, vid: str, fin: fspec.FinishingSpec, light: str = "top"
) -> Composed:
    path = repo.project_dir(pid) / "versions" / f"{vid}.png"
    if not path.exists():
        raise ApiError(
            404, "VERSION_NOT_FOUND", "후가공 미리보기에 쓸 플랫 렌더를 찾을 수 없습니다."
        )
    img = np.asarray(Image.open(path).convert("RGB"))
    h, w = img.shape[:2]
    long_edge = max(h, w)
    raster, _ = frame(spec, long_edge, FLAT_LOOK.lighting.margin)
    if (raster.h, raster.w) != (h, w):
        raise ApiError(
            409,
            "VERSION_STALE",
            "이 플랫 렌더는 지금 구조와 맞지 않습니다.",
            hint="플랫 렌더를 다시 생성한 뒤 후가공을 확인해주세요.",
        )
    sil = masks.board(spec, long_edge, structure_key(spec))
    _, tree_list = fa.project_assets(pid, spec)
    tree = {a["id"]: a for a in tree_list}
    asset_ids = [
        t.id for a in fin.assignments if a.enabled for t in a.targets if t.kind == "asset" and t.id
    ]
    svgs = fa.node_svgs(pid, [i for i in asset_ids if tree.get(i, {}).get("exact")])
    stack = []
    for a in sorted(fin.assignments, key=lambda a: a.order):
        if not a.enabled:
            continue
        ms = [
            target_mask(pid, spec, t, tree, sil, svgs, long_edge, (raster.origin, raster.scale))
            for t in a.targets
        ]
        ms = [m for m in ms if m is not None]
        if ms:
            stack.append((catalog.finish(a.finish), a.params, np.maximum.reduce(ms)))
    union = np.zeros((h, w), bool)
    for _, _, m in stack:
        union |= m > 0
    ys, xs = np.nonzero(union)
    if not ys.size:
        return Composed(img, raster.origin, raster.scale, None, None, None, [], None)
    # Work on the finishes' bounding box only (plus room for the relief shoulder).
    px_per_mm = raster.scale / spec.scale.mm_per_pt
    pad = int(CROP_PAD_MM * px_per_mm) + 8
    y0, x0 = max(0, int(ys.min()) - pad), max(0, int(xs.min()) - pad)
    y1, x1 = min(h, int(ys.max()) + 1 + pad), min(w, int(xs.max()) + 1 + pad)
    base = img[y0:y1, x0:x1].astype(np.float32) / 255
    scene = material.lighting(
        material.Scene(px_per_mm=px_per_mm, offset=(y0, x0), full=(h, w)), light
    )
    crop_stack = [(f, p, m[y0:y1, x0:x1]) for f, p, m in stack]
    out, changed = material.render(base, crop_stack, scene)
    return Composed(
        img, raster.origin, raster.scale, (y0, x0, y1, x1), out, changed, crop_stack, scene
    )


SWEEP_FRAMES = 12
SWEEP_EDGE = 900  # px, long edge of the sweep animation


def sweep(c: Composed, light: str = "top", frames: int = SWEEP_FRAMES) -> bytes:
    """Animated GIF of the finished area with the light swinging across it (±40° around the
    flat render's key, the reflections moving with it): how foil, coatings and relief catch
    light when a sample is tilted in the hand. Reduced to SWEEP_EDGE for speed."""
    assert c.box is not None and c.scene is not None
    y0, x0, y1, x1 = c.box
    k = min(1.0, SWEEP_EDGE / max(y1 - y0, x1 - x0))
    size = (max(1, round((x1 - x0) * k)), max(1, round((y1 - y0) * k)))
    base_img = Image.fromarray(c.image[y0:y1, x0:x1]).resize(size, Image.LANCZOS)
    base = np.asarray(base_img).astype(np.float32) / 255
    stack = []
    for f, p, m in c.stack:
        mm = Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8)).resize(size, Image.BILINEAR)
        stack.append((f, p, np.asarray(mm).astype(np.float32) / 255))
    fh, fw = c.image.shape[:2]
    scene = replace(
        c.scene,
        px_per_mm=c.scene.px_per_mm * k,
        offset=(round(y0 * k), round(x0 * k)),
        full=(round(fh * k), round(fw * k)),
    )
    out_frames = []
    for i in range(frames):
        t = math.sin(2 * math.pi * i / frames)
        angle = scene.light_angle + 40 * t
        lx, ly = math.sin(math.radians(angle)), -math.cos(math.radians(angle))
        sc = replace(
            material.lighting(replace(scene, light_angle=angle), light),
            softbox=(0.5 + 0.3 * lx, 0.5 + 0.3 * ly),
        )
        out, changed = material.render(base, stack, sc)
        frame = np.where(changed[..., None], out, base)
        out_frames.append(Image.fromarray((np.clip(frame, 0, 1) * 255).astype(np.uint8)))
    buf = io.BytesIO()
    pal = [f.quantize(colors=255, method=Image.Quantize.MEDIANCUT) for f in out_frames]
    pal[0].save(buf, "GIF", save_all=True, append_images=pal[1:], duration=110, loop=0)
    return buf.getvalue()
