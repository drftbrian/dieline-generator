"""Deterministic composition: our folded cartons in place of a reference photo's packages.

Kept as separate layers, multiplied only at the end:

- **albedo:** the approved flat render, sampled through each pixel's point on the flat net (no
  warping); inside faces are plain board.
- **illumination:** achromatic, from the scene's light (``light_dir``, ambient level).
  - **direct:** Lambert on each face's normal.
  - **visibility:** the reference's own shadow field (leaf shadows, cast light measured on the
    photo's surfaces, in screen space) combined (min) with shadows our cartons cast on each
    other (a light-space depth map of our geometry).
- **background:** the reference with its packages filled in from their surroundings
  (deterministic; an AI inpaint may replace it), darkened where our cartons cast shadows on the
  ground and where they touch it.

``package = albedo × illumination``. There is no exposure normalisation: a dark leaf shadow on a
light box stays dark, because it is light, not print. The print itself never changes:
``verify_structural`` checks that the package equals albedo × an achromatic light that carries
no print detail.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from app.render.structure3d import Buffers, rasterize
from app.scene import geometry as g
from app.structure.fold import Folded

BOARD_INSIDE = np.array([0.80, 0.76, 0.68], np.float32)  # unprinted board (inside faces)
LUMA = np.array([0.299, 0.587, 0.114], np.float32)


@dataclass
class Instance:
    id: str
    quad: list  # 4 image points (pixels), at most one None (hidden corner)
    height: float = 0.17  # reference box height / its long side (for its removal mask)
    enabled: bool = True
    our_face: str = "front"  # our face lying in the reference face
    yaw_deg: float = 0.0
    offset: tuple[float, float] = (0.0, 0.0)  # along the reference face's long / short axis


@dataclass
class SceneSettings:
    size: float = 1.0  # our long side, in reference long sides (shared by all instances)
    # The key light: None = estimated from the reference packages' own shading (fallback:
    # the reading's values, ``reading_azimuth`` / ``reading_elevation``).
    key_azimuth: float | None = None  # degrees, 0 = image up (far side), 90 = image right
    key_elevation: float | None = None  # above the ground
    reading_azimuth: float = 45.0
    reading_elevation: float = 35.0
    ambient: float | None = None  # shadow level; None = measured from the photo
    shadow_strength: float = 1.0  # 0 = no new shadows, 1 = as measured
    focal_px: float | None = None  # None = from the instance quads
    # The scene light's colour: one constant for the whole light (never varying across the
    # package, so it can only read as light, not as a change of print).
    light_tint: tuple[float, float, float] = (1.0, 1.0, 1.0)


LIGHT_TINTS = {  # from the reference reading's colour temperature
    "warm": (1.0, 0.955, 0.875),
    "neutral": (1.0, 1.0, 1.0),
    "cool": (0.93, 0.97, 1.0),
}


@dataclass
class Composition:
    image: np.ndarray  # HxWx3 uint8: the deterministic precomposition
    layers: dict[str, np.ndarray] = field(default_factory=dict)
    report: dict = field(default_factory=dict)


# ---- helpers ------------------------------------------------------------------------------


def _poly_mask(poly: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    img = Image.new("L", size, 0)
    ImageDraw.Draw(img).polygon([tuple(p) for p in poly], fill=255)
    return np.asarray(img) > 127


def push_pull_fill(img: np.ndarray, known: np.ndarray) -> np.ndarray:
    """Fill unknown pixels from the known ones by a coarse-to-fine pyramid (smooth, no AI)."""
    levels = []
    cur, w = img * known[..., None], known.astype(np.float32)
    while min(cur.shape[:2]) > 8:
        levels.append((cur, w))
        h2, w2 = cur.shape[0] // 2, cur.shape[1] // 2
        c = cur[: h2 * 2, : w2 * 2].reshape(h2, 2, w2, 2, -1).sum((1, 3))
        ww = w[: h2 * 2, : w2 * 2].reshape(h2, 2, w2, 2).sum((1, 3))
        cur = np.where(ww[..., None] > 0, c / np.maximum(ww, 1e-6)[..., None], 0)
        w = (ww > 0).astype(np.float32)
    # The coarsest level may still have empty cells (a large unknown area): their mean.
    filled = np.where(w[..., None] > 0, cur, cur[w > 0].mean(0) if (w > 0).any() else 0)
    for c, ww in reversed(levels):
        up = (
            np.asarray(
                Image.fromarray(np.clip(filled * 255, 0, 255).astype(np.uint8)).resize(
                    (c.shape[1], c.shape[0]), Image.BILINEAR
                )
            ).astype(np.float32)
            / 255
        )
        filled = np.where(ww[..., None] > 0, c, up)
    return np.where(known[..., None], img, filled)


FIELD_EDGE = 768  # px, long edge the photo's lighting is measured at


def _resize(a: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(Image.fromarray(a.astype(np.float32)).resize(size, Image.BILINEAR))


def _envelope(lum: np.ndarray, region: np.ndarray, win: int) -> np.ndarray:
    """The lit level of a surface around each pixel: a high local percentile of its luminance
    inside the region, filled outside it (so its edges do not read as shadow)."""
    vals = np.where(region, lum, np.nan)
    k = max(1, win // 6)
    hs, ws = lum.shape[0] // k, lum.shape[1] // k
    sub = vals[: hs * k, : ws * k].reshape(hs, k, ws, k)
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")  # empty windows outside the region are expected
        coarse = np.nanpercentile(sub, 90, axis=(1, 3))
    known = ~np.isnan(coarse)
    coarse = ndimage.maximum_filter(np.where(known, coarse, 0), size=5)
    filled = push_pull_fill(coarse[..., None].repeat(3, -1), coarse > 0)[..., 0]
    env = _resize(filled, (lum.shape[1], lum.shape[0]))
    return ndimage.gaussian_filter(env, win / 4)


def print_free(lum: np.ndarray, stroke_px: int) -> np.ndarray:
    """The photo's luminance with thin bright marks (its packages' printed text and logos)
    removed: a grey opening wider than their strokes. Shadows are dark, so they stay."""
    return ndimage.grey_opening(lum, size=(stroke_px, stroke_px))


def shadow_field(ref: np.ndarray, regions: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """(visibility 0..1, lit background level) at full size. Visibility: the photo's luminance
    (print removed) over the lit level of the surface it is on - each package region and the
    rest - so leaf shadows and cast shadows remain and the reference's artwork does not."""
    h, w = ref.shape[:2]
    k = FIELD_EDGE / max(h, w)
    sw, shh = max(8, round(w * k)), max(8, round(h * k))
    lum = _resize(ref @ LUMA, (sw, shh))
    small = [(_resize(r.astype(np.float32), (sw, shh)) > 0.5) for r in regions]
    clean = print_free(lum, max(3, int(0.012 * FIELD_EDGE)))
    # The lit level of a surface is measured over a quarter of the image: a shadow wider than
    # the window would otherwise be taken for the surface's own (lit) level and vanish.
    win = max(15, int(0.25 * FIELD_EDGE))
    out = np.ones_like(lum)
    rest = np.ones(lum.shape, bool)
    for r in small:
        rest &= ~r
    bg_level = np.ones_like(lum) * float(np.percentile(clean[rest], 90)) if rest.any() else out
    for r in [*small, rest]:
        if r.sum() < 50:
            continue
        env = _envelope(clean, r, win)
        out[r] = np.clip(clean[r] / np.maximum(env[r], 1e-3), 0.0, 1.0)
        if r is rest:
            bg_level = env
    vis = ndimage.gaussian_filter(out, 1.0)
    return np.clip(_resize(vis, (w, h)), 0, 1), _resize(bg_level, (w, h))


def reference_faces(face: g.RefFace, height: float) -> list[tuple[np.ndarray, np.ndarray]]:
    """The reference box's lid and side walls as (normal, 4x3 corners), camera space."""
    c = face.corners
    out = [(face.normal, c)]
    centre = c.mean(0)
    for j in range(4):
        a, b = c[j], c[(j + 1) % 4]
        quad = np.array([a, b, b - face.normal * height, a - face.normal * height])
        n = (a + b) / 2 - centre
        n = n - face.normal * (n @ face.normal)
        out.append((n / np.linalg.norm(n), quad))
    return out


def _ground_basis(up: np.ndarray):
    up = up / np.linalg.norm(up)
    img_up = np.array([0.0, -1.0, 0.0]) - up * (up @ np.array([0.0, -1.0, 0.0]))
    img_up /= np.linalg.norm(img_up)
    img_right = np.array([1.0, 0.0, 0.0]) - up * up[0]
    img_right -= img_up * (img_right @ img_up)
    return up, img_up, img_right / np.linalg.norm(img_right)


def floor_shadow_azimuth(
    vis: np.ndarray,
    removed: np.ndarray,
    faces: list[g.RefFace],
    heights: list[float],
    up: np.ndarray,
    K: np.ndarray,
) -> dict | None:
    """The light's horizontal direction from the shadow the packages cast on the ground: the
    light comes from the opposite side of where that shadow lies (on the ground plane, 3D)."""
    up, img_up, img_right = _ground_basis(up)
    floor_c = min(float(up @ f.origin) - hgt for f, hgt in zip(faces, heights, strict=True))
    bottoms = np.vstack([f.corners - up * hgt for f, hgt in zip(faces, heights, strict=True)])
    near = ndimage.distance_transform_edt(~removed) < 0.25 * max(vis.shape)
    dark = (vis < 0.55) & ~removed & near
    if dark.sum() < 0.002 * vis.size:
        return None
    ys, xs = np.nonzero(dark)
    rays = np.stack(
        [(xs + 0.5 - K[0, 2]) / K[0, 0], (ys + 0.5 - K[1, 2]) / K[1, 1], np.ones(len(xs))], -1
    )
    den = rays @ up
    ok = np.abs(den) > 1e-6
    t = floor_c / np.where(ok, den, 1)
    ok &= t > 0
    if ok.sum() < 50:
        return None
    pts = rays[ok] * t[ok, None]
    wgt = 1 - vis[ys[ok], xs[ok]]
    centre = (pts * wgt[:, None]).sum(0) / wgt.sum()
    d = centre - bottoms.mean(0)
    d -= up * (up @ d)
    if np.linalg.norm(d) < 1e-6:
        return None
    light_h = -d / np.linalg.norm(d)
    az = math.degrees(math.atan2(float(light_h @ img_right), float(light_h @ img_up))) % 360
    return {"azimuth": round(az, 1), "shadow_px": int(dark.sum())}


def estimate_light(
    reference: np.ndarray,
    faces: list[g.RefFace],
    heights: list[float],
    up: np.ndarray,
    K: np.ndarray,
    azimuth: float | None = None,
) -> dict | None:
    """Key light direction and ambient level that best explain the reference packages' own
    shading: each visible wall's brightness relative to its lid (print removed, the lit part).
    Returns {azimuth, elevation, ambient, error, faces} or None when too little is visible."""
    h, w = reference.shape[:2]
    k = FIELD_EDGE / max(h, w)
    sw, sh = max(8, round(w * k)), max(8, round(h * k))
    lum = print_free(_resize(reference @ LUMA, (sw, sh)), max(3, int(0.012 * FIELD_EDGE)))
    Ks = K.copy()
    Ks[:2] *= k
    order = sorted(range(len(faces)), key=lambda i: float(-faces[i].normal @ faces[i].origin))
    taken = np.zeros((sh, sw), bool)
    samples = []  # (lid normal, wall normal, observed wall / lid)
    shadow_ratios = []  # per lid: its shadowed level over its lit level
    for i in order:  # nearest (top of the stack) first: it hides what is under it
        parts = reference_faces(faces[i], heights[i])
        levels = []
        for n, quad in parts:
            if float(n @ -quad.mean(0)) <= 0:
                levels.append(None)  # faces away from the camera
                continue
            m = _poly_mask(g.project(Ks, quad), (sw, sh)) & ~taken
            m = ndimage.binary_erosion(m, iterations=2)
            levels.append(float(np.percentile(lum[m], 75)) if m.sum() > 30 else None)
            if len(levels) == 1 and m.sum() > 30:
                lo, hi = np.percentile(lum[m], [5, 90])
                if hi > 1e-3 and lo / hi < 0.8:  # this lid shows cast shadows
                    shadow_ratios.append(float(lo / hi))
        for _, quad in parts:
            taken |= _poly_mask(g.project(Ks, quad), (sw, sh))
        lid = levels[0]
        if lid is None or lid < 1e-3:
            continue
        for (n, _), lv in zip(parts[1:], levels[1:], strict=True):
            if lv is not None:
                samples.append((parts[0][0], n, lv / lid))
    if len(samples) < 2:
        return None
    # Shadows on the lids mean the lids are in direct light, and their depth fixes the ambient
    # level: shadow / lit = ambient / (ambient + (1 - ambient) cos(lid)).
    shadow = float(np.median(shadow_ratios)) if shadow_ratios else None
    lids = list({tuple(np.round(s_[0], 6)) for s_ in samples})
    best = None
    azimuths = [azimuth] if azimuth is not None else range(0, 360, 5)
    for el in range(10, 81, 5):
        for az in azimuths:
            L = light_vector(up, az, el)
            for amb in np.arange(0.2, 0.81, 0.05):
                err = 0.0
                if shadow is not None:
                    cos_l = min(max(0.0, float(np.asarray(nl) @ L)) for nl in lids)
                    if cos_l < 0.25:
                        continue  # a shadowed lid must be directly lit
                    pred = amb / (amb + (1 - amb) * cos_l)
                    err += 2 * (math.log(pred) - math.log(shadow)) ** 2
                for n_lid, n_w, ratio in samples:
                    lid_l = amb + (1 - amb) * max(0.0, float(n_lid @ L))
                    wall_l = amb + (1 - amb) * max(0.0, float(n_w @ L))
                    err += (math.log(max(wall_l, 1e-3) / max(lid_l, 1e-3)) - math.log(ratio)) ** 2
                if best is None or err < best[0]:
                    best = (err, az, el, float(amb))
    if best is None:
        return None
    err, az, el, amb = best
    return {
        "azimuth": float(az),
        "elevation": float(el),
        "ambient": round(amb, 3),
        "error": round(err / len(samples), 4),
        "faces": len(samples),
        "lid_shadow_ratio": round(shadow, 3) if shadow is not None else None,
    }


def light_vector(ground_up: np.ndarray, az: float, el: float) -> np.ndarray:
    """Toward the key light, camera space. ``az`` 0 = the image's up direction on the ground."""
    up = ground_up / np.linalg.norm(ground_up)
    img_up = np.array([0.0, -1.0, 0.0]) - up * (up @ np.array([0.0, -1.0, 0.0]))
    img_right = np.array([1.0, 0.0, 0.0]) - up * up[0]
    img_up /= np.linalg.norm(img_up)
    img_right -= img_up * (img_right @ img_up)
    img_right /= np.linalg.norm(img_right)
    a, e = math.radians(az), math.radians(el)
    horiz = math.cos(a) * img_up + math.sin(a) * img_right
    L = math.cos(e) * horiz + math.sin(e) * up
    return L / np.linalg.norm(L)


def _light_basis(L: np.ndarray):
    a = np.cross(L, [0.0, 1.0, 0.0])
    if np.linalg.norm(a) < 1e-6:
        a = np.cross(L, [1.0, 0.0, 0.0])
    a /= np.linalg.norm(a)
    b = np.cross(L, a)
    return a, b


def shadow_map(objects: list[tuple[Folded, np.ndarray]], L: np.ndarray, res: int = 1024):
    """Orthographic depth map of our cartons seen from the light: (lookup function)."""
    a, b = _light_basis(L)
    polys = []
    for folded, Mo in objects:
        for p in folded.panels:
            M = Mo @ p.matrix
            ring = max(p.flat, key=len)
            pts = (np.c_[ring, np.zeros(len(ring)), np.ones(len(ring))] @ M.T)[:, :3]
            polys.append(pts)
    allp = np.vstack(polys)
    u, v = allp @ a, allp @ b
    u0, u1, v0, v1 = u.min(), u.max(), v.min(), v.max()
    span = max(u1 - u0, v1 - v0) * 1.02
    k = (res - 1) / span
    depth = np.full((res, res), np.inf, np.float32)
    for pts in polys:
        pu, pv, pd = (pts @ a - u0) * k, (pts @ b - v0) * k, -(pts @ L)  # larger = farther
        img = Image.new("L", (res, res), 0)
        ImageDraw.Draw(img).polygon(list(zip(pu, pv, strict=True)), fill=255)
        ys, xs = np.nonzero(np.asarray(img) > 127)
        if not ys.size or len(pts) < 3:
            continue
        # Depth over the panel (planar): fit d = c0 + c1 u + c2 v.
        A = np.c_[np.ones(len(pu)), pu, pv]
        coef, *_ = np.linalg.lstsq(A, pd, rcond=None)
        d = coef[0] + coef[1] * xs + coef[2] * ys
        depth[ys, xs] = np.minimum(depth[ys, xs], d)
    depth = ndimage.grey_erosion(depth, size=3)  # conservative edges (no light leaks)

    def lookup(points: np.ndarray, bias: float) -> np.ndarray:
        pu = np.clip(((points @ a) - u0) * k, 0, res - 1).astype(int)
        pv = np.clip(((points @ b) - v0) * k, 0, res - 1).astype(int)
        return depth[pv, pu] < (-(points @ L) - bias)

    return lookup


def sample_print(
    flat: np.ndarray, frame: dict, mm_per_pt: float, flat_xy: np.ndarray
) -> np.ndarray:
    """The approved flat render at points of the flat net (mm, Y up) - bilinear."""
    (ox, oy), (sw, sh) = frame["origin"], frame["size"]
    H, W = flat.shape[:2]
    x = (flat_xy[..., 0] / mm_per_pt - ox) / sw * W - 0.5
    y = (-flat_xy[..., 1] / mm_per_pt - oy) / sh * H - 0.5
    x = np.clip(x, 0, W - 1)
    y = np.clip(y, 0, H - 1)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    x1, y1 = np.minimum(x0 + 1, W - 1), np.minimum(y0 + 1, H - 1)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]
    return (
        flat[y0, x0] * (1 - fx) * (1 - fy)
        + flat[y0, x1] * fx * (1 - fy)
        + flat[y1, x0] * (1 - fx) * fy
        + flat[y1, x1] * fx * fy
    )


# ---- the composition ------------------------------------------------------------------------


def compose(
    reference: np.ndarray,
    folded: Folded,
    flat: np.ndarray,
    frame: dict,
    mm_per_pt: float,
    instances: list[Instance],
    settings: SceneSettings,
    background: np.ndarray | None = None,
) -> Composition:
    h, w = reference.shape[:2]
    size = (w, h)
    active = [i for i in instances if i.enabled]
    if not active:
        raise ValueError("no instance to place")
    full = [np.asarray(i.quad, float) for i in active if all(c is not None for c in i.quad)]
    f = settings.focal_px or g.focal_from_quads(full, size) or 1.4 * max(w, h)
    K = g.intrinsics(f, size)
    up = g.ground_normal([g.ref_face(q, K) for q in full]) if full else np.array([0.0, -0.5, -0.87])
    faces = [g.ref_face(g.complete_quad(i.quad, up, K), K) for i in active]
    # Removal masks: each reference package's outline, slightly grown.
    grow = max(2, int(0.01 * max(w, h)))  # generous: no sliver of the old package may remain
    ref_masks = [
        ndimage.binary_dilation(
            _poly_mask(g.ref_silhouette(fc, i.height, K), size), iterations=grow
        )
        for fc, i in zip(faces, active, strict=True)
    ]
    removed = np.zeros((h, w), bool)
    for m in ref_masks:
        removed |= m
    # Lighting from the photo (before anything is removed).
    vis_photo, bg_level = shadow_field(reference, ref_masks)
    lum_vis = vis_photo[removed] if removed.any() else vis_photo.ravel()
    ambient = (
        settings.ambient
        if settings.ambient is not None
        else float(np.clip(np.percentile(lum_vis, 3), 0.25, 0.7))
    )
    est, floor = None, None
    if settings.key_azimuth is None or settings.key_elevation is None:
        heights = [i.height for i in active]
        # The light's direction from the ground shadow when there is one (most reliable), else
        # the reading's; elevation and ambient from the packages' own shading.
        floor = floor_shadow_azimuth(vis_photo, removed, faces, heights, up, K)
        fixed = settings.key_azimuth
        if fixed is None:
            fixed = floor["azimuth"] if floor else settings.reading_azimuth
        est = estimate_light(reference, faces, heights, up, K, azimuth=fixed)
        if est is not None:
            est["azimuth_source"] = (
                "ground_shadow" if floor and settings.key_azimuth is None else "reading"
            )
            est["ground_shadow"] = floor
    az = (
        settings.key_azimuth
        if settings.key_azimuth is not None
        else (est["azimuth"] if est else settings.reading_azimuth)
    )
    el = (
        settings.key_elevation
        if settings.key_elevation is not None
        else (est["elevation"] if est else settings.reading_elevation)
    )
    if settings.ambient is None and est:
        ambient = est["ambient"]
    L = light_vector(up, az, el)
    # Our cartons, posed.
    objects = [
        (folded, g.instance_matrix(folded, fc, i.our_face, settings.size, i.yaw_deg, i.offset))
        for fc, i in zip(faces, active, strict=True)
    ]
    buf: Buffers = rasterize(objects, K, size)
    pkg = buf.obj >= 0
    # Albedo: our print outside, plain board inside.
    albedo = np.zeros((h, w, 3), np.float32)
    printed = pkg & buf.outside
    albedo[printed] = sample_print(flat, frame, mm_per_pt, buf.flat_xy[printed])
    albedo[pkg & ~buf.outside] = BOARD_INSIDE
    # Direct light (Lambert), normalised so a face looking straight up the ground normal is 1.
    lit_up = max(float(up @ L), 0.05)
    cosine = np.clip(buf.normal @ L, 0, None) / lit_up
    # Visibility: the photo's shadows (screen space) and our own cast shadows (3D).
    vis_ref = np.clip((vis_photo - ambient) / max(1 - ambient, 1e-3), 0, 1)
    lookup = shadow_map(objects, L)
    scene_scale = float(np.median(np.abs(buf.depth[pkg]))) if pkg.any() else 1.0
    cast = np.zeros((h, w), bool)
    cast[pkg] = lookup(buf.point[pkg], bias=0.004 * scene_scale)
    vis = np.where(cast, 0.0, vis_ref)
    strength = float(np.clip(settings.shadow_strength, 0, 1))
    vis = 1 - strength * (1 - vis)
    illum = np.where(pkg, ambient + (1 - ambient) * np.minimum(cosine, 1.25) * vis, 1.0)
    illum = ndimage.gaussian_filter(illum, 0.6) * pkg + (~pkg)  # no aliasing at panel seams
    tint = np.asarray(settings.light_tint, np.float32)
    tint = tint / max(float(tint.max()), 1e-6)
    package = np.clip(albedo * illum[..., None] * tint, 0, 1)

    # Background: packages removed (filled from the surroundings) unless one was given.
    ref = reference.astype(np.float32)
    if background is None:
        # Where a package was: the ground's lit colour (from its brightest surroundings) times
        # the shading of the ground around it carried in smoothly (a shadow that reached the
        # package continues under where it stood). No new detail is invented; our own
        # cartons' shadows are added below. The edge is feathered.
        lum = ref @ LUMA
        around = ~removed
        bright = around & (lum >= np.percentile(lum[around], 70)) if around.any() else around
        lit = push_pull_fill(ref, bright)
        lit = ndimage.gaussian_filter(lit, (0.01 * max(h, w), 0.01 * max(h, w), 0))
        shade = push_pull_fill(vis_photo[..., None].repeat(3, -1), around)[..., 0]
        shade = ndimage.gaussian_filter(shade, 0.02 * max(h, w))
        fill = np.clip(lit * shade[..., None], 0, 1)
        feather = ndimage.gaussian_filter(removed.astype(np.float32), 0.004 * max(h, w))
        feather = np.maximum(feather, removed)[..., None]
        background = ref * (1 - feather) + fill * feather
        vis_photo = np.where(removed, shade, vis_photo)
    bg = background.astype(np.float32)
    # Ground: the plane under the lowest carton; our cartons' shadow and contact darkening on it.
    lowest = max(range(len(faces)), key=lambda k: float(-faces[k].normal @ faces[k].origin))
    lo_pts = np.vstack([w_ for p in folded.panels for w_ in p.world()])
    Mlow = objects[lowest][1]
    bottom = (np.c_[lo_pts, np.ones(len(lo_pts))] @ Mlow.T)[:, :3]
    floor_d = float(np.max(-(bottom @ up)))  # plane up.x = -floor_d
    yy, xx = np.mgrid[0:h, 0:w]
    rays = np.stack([(xx + 0.5 - K[0, 2]) / f, (yy + 0.5 - K[1, 2]) / f, np.ones((h, w))], -1)
    denom = rays @ up
    t = np.where(np.abs(denom) > 1e-9, -floor_d / np.where(np.abs(denom) > 1e-9, denom, 1), np.inf)
    floor_pts = rays * t[..., None]
    ground_shadow = np.zeros((h, w), bool)
    ok = (t > 0) & ~pkg
    ground_shadow[ok] = lookup(floor_pts[ok], bias=0.004 * scene_scale)
    ground_shadow = ndimage.gaussian_filter(ground_shadow.astype(np.float32), max(1.5, 0.003 * w))
    # The photo's own shadow level on the background (where it was already shadowed, stay).
    bg_vis = vis_photo
    target = ambient + (1 - ambient) * (1 - strength * ground_shadow)
    darken = np.clip(target / np.maximum(bg_vis, 1e-3), 0, 1)
    darken = np.where(bg_vis <= target, 1.0, darken)
    # Contact: soft darkening right around our cartons' footprint on the ground.
    contact = ndimage.gaussian_filter(pkg.astype(np.float32), max(2.0, 0.006 * w))
    contact = 1 - 0.25 * strength * np.clip(contact * 2, 0, 1) * (~pkg)
    bg_lit = np.clip(bg * (darken * contact)[..., None], 0, 1)

    # Composite, anti-aliased at the outline (colour of the nearest package pixel there).
    idx = ndimage.distance_transform_edt(~pkg, return_distances=False, return_indices=True)
    pkg_col = package[idx[0], idx[1]]
    a = np.clip(buf.coverage, 0, 1)[..., None]
    out = np.clip(bg_lit * (1 - a) + pkg_col * a, 0, 1)
    image = (out * 255 + 0.5).astype(np.uint8)
    report = verify_structural(package, albedo * tint, illum, pkg, reference)
    report["light_tint"] = np.round(tint, 3).tolist()
    report.update(
        {
            "instances": len(active),
            "focal_px": round(f, 1),
            "lens_mm_35eq": round(f / w * 36, 1),
            "ambient": round(ambient, 3),
            "light_vector": np.round(L, 3).tolist(),
            "light": {"azimuth": az, "elevation": el, "estimated": est},
            "removed_px": int(removed.sum()),
            "package_px": int(pkg.sum()),
        }
    )
    layers = {
        "removal_mask": removed.astype(np.float32),
        "background": bg,
        "albedo": np.where(pkg[..., None], albedo, 0),
        "lighting": illum,
        "shadow_only": np.where(pkg, vis, 1.0) * np.where(pkg, 1.0, darken),
        "photo_shadow_field": vis_photo,
        "cast_shadow": cast.astype(np.float32),
        "ground_shadow": ground_shadow,
        "placement": np.where(
            pkg[..., None], np.where(buf.outside[..., None], 0.85, 0.55), ref * 0.5
        ),
        "instance_id": buf.obj.astype(np.float32),
    }
    return Composition(image, layers, report)


def verify_structural(
    package: np.ndarray,
    albedo: np.ndarray,
    illum: np.ndarray,
    pkg: np.ndarray,
    reference: np.ndarray | None = None,
) -> dict:
    """The package is the approved print times achromatic light, and the light carries no print
    detail: neither ours (ghosted artwork) nor the reference packages' (their text or logo
    carried over by the shadow field). Shadows may be deep: they are light, not print."""
    if not pkg.any():
        return {"match": False, "reason": "no_package"}
    expected = np.clip(albedo * illum[..., None], 0, 1)
    residual = float(np.abs(package - expected).max(-1)[pkg].max())
    lum_a = albedo @ LUMA
    hp = lambda v: v - ndimage.gaussian_filter(v, 2)  # noqa: E731
    inner = ndimage.binary_erosion(pkg, iterations=4)
    inner = inner if inner.sum() > 100 else pkg
    a, b = hp(illum)[inner], hp(lum_a)[inner]
    ghost = float(np.corrcoef(a, b)[0, 1]) if a.std() > 1e-6 and b.std() > 1e-6 else 0.0
    leak = 0.0
    if reference is not None:
        lum_r = reference @ LUMA
        stroke = max(3, int(0.012 * max(lum_r.shape)))
        marks = lum_r - ndimage.grey_opening(lum_r, size=(stroke, stroke))  # bright thin print
        m, c = hp(illum)[inner], marks[inner]
        if m.std() > 1e-6 and c.std() > 1e-6:
            leak = float(np.corrcoef(m, c)[0, 1])
    lo, hi = float(illum[pkg].min()), float(illum[pkg].max())
    ok = residual <= 1.5 / 255 and ghost < 0.3 and leak < 0.15 and lo >= 0.05 and hi <= 1.3
    return {
        "match": bool(ok),
        "protected_px": int(pkg.sum()),
        "changed_px": int(pkg.sum()),
        "changed_ratio": 1.0,
        "residual": round(residual * 255, 2),
        "light_print_correlation": round(ghost, 3),
        "reference_print_leak": round(leak, 3),
        "light_min": round(lo, 3),
        "light_max": round(hi, 3),
        "shadow_share": round(float((illum[pkg] < 0.7).mean()), 3),
    }
