"""Render a folded carton (``structure.fold``) with a pinhole camera: deterministic, no GPU.

Every panel is planar, so each pixel's depth and its point on the panel come from an exact
ray-plane intersection (a z-buffer over planar polygons). Besides the image, the render returns
per pixel:
- which panel it shows;
- whether the outside (printed) face or the inside is visible;
- the point hit, in the panel's flat-net coordinates (mm).

M4 samples the approved print through those coordinates, which makes the mapping exact by
construction.

Poses are the camera and the carton's placement, kept apart from the fold state (``fold``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

from app.structure.fold import Folded

ROLE_COLOUR = {  # structural preview: outside faces by role
    "W": (0.80, 0.86, 0.95),
    "D": (0.82, 0.92, 0.80),
    "lid": (0.98, 0.92, 0.75),
    "tuck": (0.98, 0.85, 0.70),
    "dust": (0.90, 0.84, 0.95),
    "glue": (0.85, 0.85, 0.85),
    "bottom_W": (0.95, 0.80, 0.80),
    "bottom_D": (0.95, 0.85, 0.80),
    "lock_triangle": (0.92, 0.75, 0.70),
}
INSIDE = (0.78, 0.74, 0.66)  # unprinted board
BACKGROUND = (0.93, 0.93, 0.93)


@dataclass(frozen=True)
class Pose:
    id: str
    label_ko: str
    azimuth: float  # degrees, 0 = facing the front panel, positive turns to show the right side
    elevation: float  # degrees above the horizon
    lying: bool = False  # the carton on its back, front panel up
    default_state: str = "closed"


POSES = {
    p.id: p
    for p in (
        Pose("standing_front", "정면", 0, 8),
        Pose("standing_three_quarter", "3/4 각도", 35, 18),
        Pose("standing_side", "측면", 90, 8),
        # On its back, front up; seen from the lid's end so the top and front show.
        Pose("lying_down", "눕힘", 155, 40, lying=True),
        Pose("open_top", "윗면 열림", 30, 32, default_state="open_top"),
    )
}


@dataclass
class Render:
    rgba: np.ndarray  # HxWx4 float
    panel: np.ndarray  # HxW int16, index into folded.panels, -1 = background
    outside: np.ndarray  # HxW bool, the printed face is visible
    flat_xy: np.ndarray  # HxWx2 float32, hit point in the panel's flat frame (mm)
    depth: np.ndarray  # HxW float32, camera depth (mm), inf = background


def _area(q: np.ndarray) -> float:
    """Shoelace area of a 2-D polygon."""
    if len(q) < 3:
        return 0.0
    x, y = q[:, 0], q[:, 1]
    return abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) / 2


def _pose_matrix(pose: Pose) -> np.ndarray:
    R = np.eye(4)
    if pose.lying:  # -90 deg about X: the front (+Z) turns up (+Y)
        R[:3, :3] = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float)
    return R


def _camera(pts: np.ndarray, az: float, el: float, lens_mm: float, aspect: float):
    """Look-at camera around the carton's centre, far enough to frame it with a margin."""
    centre = (pts.min(0) + pts.max(0)) / 2
    radius = float(np.linalg.norm(pts - centre, axis=1).max())
    fov = 2 * math.atan(36 / 2 / lens_mm)  # horizontal, 35 mm equivalent
    fov_min = min(fov, 2 * math.atan(math.tan(fov / 2) / aspect))
    dist = radius / math.sin(fov_min / 2) * 1.08
    a, e = math.radians(az), math.radians(el)
    eye = centre + dist * np.array(
        [math.sin(a) * math.cos(e), math.sin(e), math.cos(a) * math.cos(e)]
    )
    fwd = (centre - eye) / np.linalg.norm(centre - eye)
    right = np.cross(fwd, [0.0, 1.0, 0.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    return eye, np.stack([right, -up, fwd]), fov  # rows: camera x (right), y (down), z (forward)


def render(
    folded: Folded,
    pose: Pose,
    size: tuple[int, int] = (1200, 900),
    lens_mm: float = 50.0,
    supersample: int = 2,
    azimuth: float | None = None,
    elevation: float | None = None,
) -> Render:
    w, h = size[0] * supersample, size[1] * supersample
    P = _pose_matrix(pose)
    mats = [P @ p.matrix for p in folded.panels]
    loops = []
    for p, M in zip(folded.panels, mats, strict=True):
        ls = []
        for loop in p.flat:
            pts = np.c_[loop, np.zeros(len(loop)), np.ones(len(loop))] @ M.T
            ls.append(pts[:, :3])
        loops.append(ls)
    allpts = np.vstack([q for ls in loops for q in ls])
    eye, rot, fov = _camera(
        allpts,
        pose.azimuth if azimuth is None else azimuth,
        pose.elevation if elevation is None else elevation,
        lens_mm,
        w / h,
    )
    f = (w / 2) / math.tan(fov / 2)
    cx, cy = w / 2, h / 2

    depth = np.full((h, w), np.inf, np.float32)
    pid = np.full((h, w), -1, np.int16)
    outside = np.zeros((h, w), bool)
    flat_xy = np.zeros((h, w, 2), np.float32)
    light = np.array([-0.45, 0.75, 0.5])
    light /= np.linalg.norm(light)
    shade = np.zeros((h, w), np.float32)
    for i, (M, ls) in enumerate(zip(mats, loops, strict=True)):
        cam = [(q - eye) @ rot.T for q in ls]
        if any((c[:, 2] <= 1e-3).any() for c in cam):
            continue
        proj = [np.c_[c[:, 0] / c[:, 2] * f + cx, c[:, 1] / c[:, 2] * f + cy] for c in cam]
        # Outer loop = the largest; the others are holes.
        areas = [_area(q) for q in proj]
        outer = int(np.argmax(areas))
        img = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(img)
        d.polygon([tuple(v) for v in proj[outer]], fill=255)
        for j, q in enumerate(proj):
            if j != outer:
                d.polygon([tuple(v) for v in q], fill=0)
        mask = np.asarray(img) > 127
        if not mask.any():
            continue
        ys, xs = np.nonzero(mask)
        # Plane of the panel in camera space.
        n_world = M[:3, :3] @ np.array([0.0, 0.0, 1.0])
        n = rot @ n_world
        p0 = cam[outer][0]
        dx = (xs + 0.5 - cx) / f
        dy = (ys + 0.5 - cy) / f
        denom = n[0] * dx + n[1] * dy + n[2]
        ok = np.abs(denom) > 1e-9
        t = np.where(ok, (n @ p0) / np.where(ok, denom, 1), np.inf)  # = camera z
        closer = ok & (t > 0) & (t < depth[ys, xs])
        ys, xs, t, dx, dy = ys[closer], xs[closer], t[closer], dx[closer], dy[closer]
        depth[ys, xs] = t
        pid[ys, xs] = i
        facing = (n @ -p0) > 0  # the printed face looks at the camera
        outside[ys, xs] = facing
        hit_cam = np.stack([dx * t, dy * t, t], -1)
        hit_world = hit_cam @ rot + eye
        Minv = np.linalg.inv(M)
        local = np.c_[hit_world, np.ones(len(hit_world))] @ Minv.T
        flat_xy[ys, xs] = local[:, :2]
        lit = n_world if facing else -n_world
        shade[ys, xs] = 0.6 + 0.4 * max(0.0, float(lit @ light))

    rgb = np.empty((h, w, 3), np.float32)
    rgb[:] = BACKGROUND
    for i, p in enumerate(folded.panels):
        m = pid == i
        if not m.any():
            continue
        base = np.where(outside[m][:, None], ROLE_COLOUR.get(p.role, (0.9, 0.9, 0.9)), INSIDE)
        rgb[m] = base * shade[m][:, None]
    # Panel edges: where the visible panel changes.
    edge = np.zeros((h, w), bool)
    edge[:, 1:] |= pid[:, 1:] != pid[:, :-1]
    edge[1:, :] |= pid[1:, :] != pid[:-1, :]
    rgb[edge & (pid >= 0)] *= 0.55
    alpha = (pid >= 0).astype(np.float32)
    rgba = np.dstack([rgb, alpha])
    if supersample > 1:
        k = supersample
        H, W = size[1], size[0]
        rgba = rgba.reshape(H, k, W, k, 4).mean(axis=(1, 3))
        pid, outside, depth = pid[::k, ::k], outside[::k, ::k], depth[::k, ::k]
        flat_xy = flat_xy[::k, ::k]
    return Render(rgba.astype(np.float32), pid, outside, flat_xy, depth)


def to_png(r: Render) -> bytes:
    import io

    buf = io.BytesIO()
    Image.fromarray((np.clip(r.rgba[..., :3], 0, 1) * 255 + 0.5).astype(np.uint8)).save(buf, "PNG")
    return buf.getvalue()


# ---- scenes: several cartons, one camera (structural reference composition) ---------------


@dataclass
class Buffers:
    """A scene raster at the output resolution (camera space: x right, y down, z forward)."""

    obj: np.ndarray  # HxW int16: object index, -1 = background
    panel: np.ndarray  # HxW int16: panel index within the object
    outside: np.ndarray  # HxW bool: the printed face is seen
    flat_xy: np.ndarray  # HxWx2 float32: hit point on the flat net (mm)
    depth: np.ndarray  # HxW float32: camera z, inf = background
    point: np.ndarray  # HxWx3 float32: hit point (camera space)
    normal: np.ndarray  # HxWx3 float32: normal of the visible side (camera space)
    coverage: np.ndarray  # HxW float32: anti-aliased silhouette of all objects


def rasterize(
    objects: list[tuple[Folded, np.ndarray]],
    K: np.ndarray,
    size: tuple[int, int],
    cover_ss: int = 3,
) -> Buffers:
    """Z-buffer several folded cartons. ``objects``: (folded, 4x4 model matrix to camera
    space), camera at the origin looking down +z; ``K``: 3x3 intrinsics in output pixels."""
    w, h = size
    f, cx, cy = K[0, 0], K[0, 2], K[1, 2]
    obj = np.full((h, w), -1, np.int16)
    panel = np.full((h, w), -1, np.int16)
    outside = np.zeros((h, w), bool)
    flat_xy = np.zeros((h, w, 2), np.float32)
    depth = np.full((h, w), np.inf, np.float32)
    point = np.zeros((h, w, 3), np.float32)
    normal = np.zeros((h, w, 3), np.float32)
    cover = Image.new("L", (w * cover_ss, h * cover_ss), 0)
    cd = ImageDraw.Draw(cover)
    for oi, (folded, Mo) in enumerate(objects):
        for pi, p in enumerate(folded.panels):
            M = Mo @ p.matrix
            cam = [(np.c_[q, np.zeros(len(q)), np.ones(len(q))] @ M.T)[:, :3] for q in p.flat]
            if any((c[:, 2] <= 1e-6).any() for c in cam):
                continue  # behind the camera: never happens in a fitted scene
            proj = [np.c_[c[:, 0] / c[:, 2] * f + cx, c[:, 1] / c[:, 2] * f + cy] for c in cam]
            outer = int(np.argmax([_area(q) for q in proj]))
            x0, y0 = np.floor(proj[outer].min(0)).astype(int) - 1
            x1, y1 = np.ceil(proj[outer].max(0)).astype(int) + 2
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
            if x1 <= x0 or y1 <= y0:
                continue
            img = Image.new("L", (x1 - x0, y1 - y0), 0)
            d = ImageDraw.Draw(img)
            d.polygon([(u - x0, v - y0) for u, v in proj[outer]], fill=255)
            for j, q in enumerate(proj):
                if j != outer:
                    d.polygon([(u - x0, v - y0) for u, v in q], fill=0)
            cd.polygon([(u * cover_ss, v * cover_ss) for u, v in proj[outer]], fill=255)
            ys, xs = np.nonzero(np.asarray(img) > 127)
            if not ys.size:
                continue
            ys, xs = ys + y0, xs + x0
            n = M[:3, :3] @ np.array([0.0, 0.0, 1.0])
            n /= np.linalg.norm(n)
            p0 = cam[outer][0]
            dx, dy = (xs + 0.5 - cx) / f, (ys + 0.5 - cy) / f
            denom = n[0] * dx + n[1] * dy + n[2]
            ok = np.abs(denom) > 1e-9
            t = np.where(ok, (n @ p0) / np.where(ok, denom, 1), np.inf)
            closer = ok & (t > 0) & (t < depth[ys, xs])
            ys, xs, t, dx, dy = ys[closer], xs[closer], t[closer], dx[closer], dy[closer]
            if not ys.size:
                continue
            hit = np.stack([dx * t, dy * t, t], -1)
            depth[ys, xs] = t
            obj[ys, xs] = oi
            panel[ys, xs] = pi
            facing = float(n @ -p0) > 0
            outside[ys, xs] = facing
            normal[ys, xs] = n if facing else -n
            point[ys, xs] = hit
            local = np.c_[hit, np.ones(len(hit))] @ np.linalg.inv(M).T
            flat_xy[ys, xs] = local[:, :2]
    # Silhouette coverage (supersampled): soft only along the outline. Colour for the partly
    # covered pixels just outside the z-buffer comes from their nearest covered neighbour.
    coverage = np.asarray(cover.resize((w, h), Image.BOX)).astype(np.float32) / 255
    return Buffers(obj, panel, outside, flat_xy, depth, point, normal, coverage)
