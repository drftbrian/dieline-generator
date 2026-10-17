"""Fold the dieline into a closed box and photograph it with a pinhole camera.

The faces are the exact print (cropped from the approved flat render), so the carton in a
reference merge can never carry invented text or shifted colours. Each face is a planar quad,
so mapping the print onto it is an exact homography; rendering is supersampled for clean edges.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np
from PIL import Image

FACES = ("front", "back", "left", "right", "top", "bottom")

# Panel names (Claude naming, Korean or English) -> face.
NAME_RULES = [
    ("front", re.compile(r"앞면|정면|front", re.I)),
    ("back", re.compile(r"뒷면|후면|back", re.I)),
    ("left", re.compile(r"(옆면|측면|side).*(좌|left)|left.*side", re.I)),
    ("right", re.compile(r"(옆면|측면|side).*(우|right)|right.*side", re.I)),
    ("top", re.compile(r"윗면\s*뚜껑|상단\s*뚜껑|top\s*(lid|panel)?$|^top", re.I)),
    ("bottom", re.compile(r"아랫면\s*뚜껑\s*1?$|하단\s*뚜껑|bottom\s*(lid|panel)?$", re.I)),
]


@dataclass
class Camera:
    azimuth: float = 30.0  # degrees; positive turns the box so its right side shows
    elevation: float = 15.0  # degrees above the box's mid-height
    lens_mm: float = 50.0  # 35 mm-equivalent focal length
    placement: tuple[float, float, float, float] = (0.25, 0.15, 0.75, 0.85)  # x0 y0 x1 y1


@dataclass
class Render:
    rgba: np.ndarray  # HxWx4 float, straight alpha
    face: np.ndarray  # HxW int8, index into FACES, -1 = background
    uv: np.ndarray  # HxWx2 float, texture coordinates (0..1) on that face
    corners: dict[str, np.ndarray]  # face -> 4x2 image points (tl, tr, br, bl)


def map_faces(panels, box=None) -> dict[str, tuple[float, float, float, float]]:
    """Face -> panel bbox (page points): by panel name, else by the dieline's geometry."""
    out: dict[str, tuple] = {}
    for face, rule in NAME_RULES:
        for p in panels:
            if face not in out and rule.search(p.name or ""):
                out[face] = p.bbox
    if "front" in out:
        return out

    # Geometry: the body panels are the tallest row; front = right-most wide one, sides are its
    # neighbours, the lid sits directly above it and the bottom directly below.
    def h(b):
        return b[3] - b[1]

    def w(b):
        return b[2] - b[0]

    tall = max((h(p.bbox) for p in panels), default=0)
    body = sorted((p.bbox for p in panels if h(p.bbox) > 0.9 * tall), key=lambda b: b[0])
    if not body:
        return out
    wide = max(w(b) for b in body)
    fronts = [b for b in body if w(b) > 0.85 * wide]
    front = fronts[-1]
    out["front"] = front
    if len(fronts) > 1:
        out["back"] = fronts[-2]
    i = body.index(front)
    if i > 0 and w(body[i - 1]) < 0.85 * wide:
        out["left"] = body[i - 1]
    if i + 1 < len(body) and w(body[i + 1]) < 0.85 * wide:
        out["right"] = body[i + 1]

    def overlaps(b):
        return min(b[2], front[2]) - max(b[0], front[0]) > 0.6 * w(front)

    gap = 0.05 * h(front)
    above = [p.bbox for p in panels if overlaps(p.bbox) and abs(p.bbox[3] - front[1]) < gap]
    below = [p.bbox for p in panels if overlaps(p.bbox) and abs(p.bbox[1] - front[3]) < gap]
    if above:
        out["top"] = max(above, key=h)
    if below:
        out["bottom"] = max(below, key=h)
    return out


def dims_from(faces: dict, mm_per_pt: float, box=None) -> tuple[float, float, float]:
    """W, D, H in mm: the stated box size, else measured from the front and a side panel."""
    if box is not None:
        return box.width_mm, box.depth_mm, box.height_mm
    f = faces["front"]
    side = faces.get("right") or faces.get("left") or faces.get("top")
    W, H = (f[2] - f[0]) * mm_per_pt, (f[3] - f[1]) * mm_per_pt
    if side is None:
        D = 0.4 * W
    elif side is faces.get("top"):
        D = (side[3] - side[1]) * mm_per_pt
    else:
        D = (side[2] - side[0]) * mm_per_pt
    return W, D, H


def _corners(face: str, W: float, D: float, H: float) -> np.ndarray:
    """3D corners (tl, tr, br, bl as seen from outside, print upright) of a box face (mm).
    Box: x across the front (left -> right), y up, z toward the viewer (front at +D/2)."""
    x0, x1, z0, z1 = -W / 2, W / 2, -D / 2, D / 2
    return {
        "front": [(x0, H, z1), (x1, H, z1), (x1, 0, z1), (x0, 0, z1)],
        "back": [(x1, H, z0), (x0, H, z0), (x0, 0, z0), (x1, 0, z0)],
        "left": [(x0, H, z0), (x0, H, z1), (x0, 0, z1), (x0, 0, z0)],
        "right": [(x1, H, z1), (x1, H, z0), (x1, 0, z0), (x1, 0, z1)],
        # Top lid hinges on the back edge; on the dieline its bottom edge meets the front panel.
        "top": [(x0, H, z0), (x1, H, z0), (x1, H, z1), (x0, H, z1)],
        "bottom": [(x0, 0, z1), (x1, 0, z1), (x1, 0, z0), (x0, 0, z0)],
    }[face]


NORMALS = {
    "front": (0, 0, 1),
    "back": (0, 0, -1),
    "left": (-1, 0, 0),
    "right": (1, 0, 0),
    "top": (0, 1, 0),
    "bottom": (0, -1, 0),
}


def _project(
    pts: np.ndarray, cam: Camera, W: float, D: float, H: float
) -> tuple[np.ndarray, np.ndarray]:
    """World mm -> normalised image plane (x right, y down) and camera-space depth."""
    centre = np.array([0, H / 2, 0])
    az, el = math.radians(cam.azimuth), math.radians(cam.elevation)
    # Distance from the lens: a 36 mm-wide sensor frames ~1.6x the box's largest side.
    size = max(W, D, H)
    dist = size * 1.6 * cam.lens_mm / 36
    eye = centre + dist * np.array(
        [math.sin(az) * math.cos(el), math.sin(el), math.cos(az) * math.cos(el)]
    )
    fwd = (centre - eye) / np.linalg.norm(centre - eye)
    right = np.cross(fwd, [0, 1, 0])
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    rel = pts - eye
    z = rel @ fwd
    x = (rel @ right) / z
    y = -(rel @ up) / z
    return np.stack([x, y], -1), z


def _homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """3x3 H with dst ~ H @ src (4 point pairs)."""
    a = []
    for (x, y), (u, v) in zip(src, dst, strict=True):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, vt = np.linalg.svd(np.asarray(a, float))
    return vt[-1].reshape(3, 3)


def _sample(tex: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    h, w = tex.shape[:2]
    x = np.clip(u * (w - 1), 0, w - 1)
    y = np.clip(v * (h - 1), 0, h - 1)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]
    return (
        tex[y0, x0] * (1 - fx) * (1 - fy)
        + tex[y0, x1] * fx * (1 - fy)
        + tex[y1, x0] * (1 - fx) * fy
        + tex[y1, x1] * fx * fy
    )


def render(
    textures: dict[str, np.ndarray],
    dims_mm: tuple[float, float, float],
    cam: Camera,
    size: tuple[int, int],
    supersample: int = 2,
) -> Render:
    """Photograph the folded box. ``textures``: face -> HxWx3 float print (upright)."""
    W, D, H = dims_mm
    out_w, out_h = size
    sw, sh = out_w * supersample, out_h * supersample
    eye_dir = None
    proj: dict[str, tuple[np.ndarray, float]] = {}
    all_pts = []
    for face in FACES:
        pts3 = np.asarray(_corners(face, W, D, H), float)
        xy, z = _project(pts3, cam, W, D, H)
        proj[face] = (xy, float(z.mean()))
        all_pts.append(xy)
    # Visible faces: normal points toward the camera (projected winding is clockwise).
    visible = []
    for face, (xy, _) in proj.items():
        e = xy[1] - xy[0]
        f = xy[3] - xy[0]
        if e[0] * f[1] - e[1] * f[0] > 1e-9 and face in textures:
            visible.append(face)
    pts = np.concatenate([proj[f][0] for f in visible] or all_pts)
    # Fit the visible box into the placement rectangle, keeping its aspect.
    px0, py0, px1, py1 = cam.placement
    bx0, by0 = pts.min(0)
    bx1, by1 = pts.max(0)
    scale = min((px1 - px0) * sw / (bx1 - bx0), (py1 - py0) * sh / (by1 - by0))
    ox = (px0 + px1) / 2 * sw - (bx0 + bx1) / 2 * scale
    oy = (py0 + py1) / 2 * sh - (by0 + by1) / 2 * scale
    rgba = np.zeros((sh, sw, 4), np.float32)
    face_id = np.full((sh, sw), -1, np.int8)
    uvmap = np.zeros((sh, sw, 2), np.float32)
    corners = {}
    for face in sorted(visible, key=lambda f: -proj[f][1]):  # far to near
        img_pts = proj[face][0] * scale + [ox, oy]
        corners[face] = img_pts / supersample
        Hm = _homography(np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float), img_pts)
        inv = np.linalg.inv(Hm)
        x0, y0 = np.floor(img_pts.min(0)).astype(int)
        x1, y1 = np.ceil(img_pts.max(0)).astype(int)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(sw, x1 + 1), min(sh, y1 + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(float) + 0.5
        q = np.stack([xx, yy, np.ones_like(xx)], -1) @ inv.T
        u, v = q[..., 0] / q[..., 2], q[..., 1] / q[..., 2]
        inside = (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
        col = _sample(textures[face], u, v)
        region = rgba[y0:y1, x0:x1]
        region[inside, :3] = col[inside]
        region[inside, 3] = 1.0
        face_id[y0:y1, x0:x1][inside] = FACES.index(face)
        uvmap[y0:y1, x0:x1][inside] = np.stack([u, v], -1)[inside]
    del eye_dir
    if supersample > 1:
        img = Image.fromarray((rgba * 255 + 0.5).astype(np.uint8), "RGBA")
        # Premultiply for a clean downsample of the edges.
        pre = rgba.copy()
        pre[..., :3] *= pre[..., 3:]
        k = supersample
        pre = pre.reshape(out_h, k, out_w, k, 4).mean(axis=(1, 3))
        a = pre[..., 3:]
        rgb = np.where(a > 1e-6, pre[..., :3] / np.maximum(a, 1e-6), 0)
        rgba_out = np.concatenate([rgb, a], -1).astype(np.float32)
        face_out = face_id[::k, ::k]
        uv_out = uvmap[::k, ::k]
        del img
    else:
        rgba_out, face_out, uv_out = rgba, face_id, uvmap
    return Render(rgba_out, face_out, uv_out, corners)
