"""Where each package of a reference photo sits in 3D, and the matching pose of our carton.

An instance is described by the image quad of its most visible face (usually the lid of a box
seen from above). With one pinhole camera for the whole photo, that quad is a homography of a
rectangle:
- **Focal length:** each rectangle's homography gives one focal-length estimate (its sides are
  orthogonal); the median over all instances is the camera's.
- **Pose:** decomposing the homography gives the face's plane, centre and axes.

The reference boxes' real size is unknown, so the scene is in "reference units": every reference
face's long side is 1. Our carton keeps its own proportions and goes into that face's plane and
orientation, scaled by one factor shared by all instances (``size``), so the instances keep their
relative scale. Nothing is warped: the carton is the folded model, posed rigidly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.render.carton3d import _homography
from app.structure.fold import Folded

FACE_AXES = {  # which of our faces lies in the reference face: (axis, sign) in the box frame
    "front": (2, 1),
    "back": (2, -1),
    "top": (1, 1),
    "bottom": (1, -1),
    "right": (0, 1),
    "left": (0, -1),
}


@dataclass
class RefFace:
    origin: np.ndarray  # centre of the face (camera space, reference units)
    e_long: np.ndarray  # unit axis along the face's long side
    e_short: np.ndarray
    normal: np.ndarray  # unit, toward the camera
    long: float  # side lengths (reference units; long = 1)
    short: float
    corners: np.ndarray  # 4x3 camera space


def intrinsics(f: float, size: tuple[int, int]) -> np.ndarray:
    w, h = size
    return np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], float)


def _ordered(quad: np.ndarray) -> np.ndarray:
    """Corners in a consistent winding (clockwise on screen), starting top-left-most."""
    c = quad.mean(0)
    ang = np.arctan2(quad[:, 1] - c[1], quad[:, 0] - c[0])
    q = quad[np.argsort(ang)]
    start = int(np.argmin(q[:, 0] + q[:, 1]))
    return np.roll(q, -start, axis=0)


def _H(quad_px: np.ndarray, centre: tuple[float, float]) -> np.ndarray:
    unit = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)
    return _homography(unit, quad_px - np.array(centre))


def focal_from_quads(quads_px: list[np.ndarray], size: tuple[int, int]) -> float | None:
    """Median focal length (pixels) from rectangles seen in perspective; None if none tells."""
    w, h = size
    out = []
    for q in quads_px:
        H = _H(_ordered(q), (w / 2, h / 2))
        h1, h2 = H[:, 0], H[:, 1]
        den = h1[2] * h2[2]
        if abs(den) < 1e-12:
            continue
        f2 = -(h1[0] * h2[0] + h1[1] * h2[1]) / den
        if f2 > 0:
            f = math.sqrt(f2)
            if 0.4 * max(w, h) <= f <= 6 * max(w, h):
                out.append(f)
    return float(np.median(out)) if out else None


def ref_face(quad_px: np.ndarray, K: np.ndarray) -> RefFace:
    q = _ordered(np.asarray(quad_px, float))
    H = _H(q, (K[0, 2], K[1, 2]))
    Kc = K.copy()
    Kc[0, 2] = Kc[1, 2] = 0  # H was fitted in centred pixels
    A = np.linalg.inv(Kc) @ H
    if A[2, 2] < 0:  # DLT sign: the face must be in front of the camera
        A = -A
    a1, a2, a3 = A[:, 0], A[:, 1], A[:, 2]
    s = max(np.linalg.norm(a1), np.linalg.norm(a2))
    Lu, Lv = np.linalg.norm(a1) / s, np.linalg.norm(a2) / s
    p0 = a3 / s
    e1 = a1 / np.linalg.norm(a1)
    e2 = a2 / np.linalg.norm(a2)
    # Nearest orthonormal frame (the quad is never a perfect rectangle in a photo).
    U, _, Vt = np.linalg.svd(np.c_[e1, e2, np.cross(e1, e2)])
    R = U @ Vt
    e1, e2, n = R[:, 0], R[:, 1], R[:, 2]
    centre = p0 + 0.5 * Lu * e1 + 0.5 * Lv * e2
    if n @ centre > 0:  # the normal faces the camera; the in-plane axes stay as the quad's
        n = -n
    corners = np.array([p0, p0 + Lu * e1, p0 + Lu * e1 + Lv * e2, p0 + Lv * e2])
    if Lu >= Lv:
        return RefFace(centre, e1, e2, n, Lu, Lv, corners)
    return RefFace(centre, e2, e1, n, Lv, Lu, corners)


def project(K: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return np.c_[
        pts[:, 0] / pts[:, 2] * K[0, 0] + K[0, 2], pts[:, 1] / pts[:, 2] * K[1, 1] + K[1, 2]
    ]


def ref_silhouette(face: RefFace, height: float, K: np.ndarray, margin: float = 0.03) -> np.ndarray:
    """Image outline (convex hull) of the reference box: its face, grown in its own plane by
    ``margin`` (of the long side; hand-placed or proposed corners are never exact), and that
    face moved down by ``height`` (reference units) along the face normal."""
    c = face.corners
    centre = c.mean(0)
    grown = (
        c + (c - centre) / np.linalg.norm(c - centre, axis=1, keepdims=True) * margin * face.long
    )
    pts = np.vstack([grown, grown - face.normal * height])
    p = project(K, pts)
    return _hull(p)


def _hull(p: np.ndarray) -> np.ndarray:
    pts = sorted(map(tuple, p))
    if len(pts) <= 2:
        return np.array(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for q in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return np.array(lower[:-1] + upper[:-1])


def carton_box(folded: Folded) -> tuple[np.ndarray, np.ndarray]:
    """(min, max) corners of the folded carton (mm, box frame)."""
    pts = np.vstack([w for p in folded.panels for w in p.world()])
    return pts.min(0), pts.max(0)


def instance_matrix(
    folded: Folded,
    face: RefFace,
    our_face: str = "front",
    size: float = 1.0,
    yaw_deg: float = 0.0,
    offset: tuple[float, float] = (0.0, 0.0),
) -> np.ndarray:
    """4x4: our carton's box frame (mm) -> camera space, with ``our_face`` lying in the
    reference face's plane, its long side along the reference face's long side, our long side
    = ``size`` reference units (shared by all instances: relative scale is kept)."""
    lo, hi = carton_box(folded)
    ext = hi - lo
    axis, sign = FACE_AXES[our_face]
    others = [a for a in range(3) if a != axis]
    long_ax, short_ax = sorted(others, key=lambda a: -ext[a])
    s = size / ext[long_ax]
    # Our axes -> reference axes (rotation about the normal by yaw).
    y = math.radians(yaw_deg)
    el = math.cos(y) * face.e_long + math.sin(y) * face.e_short
    es = -math.sin(y) * face.e_long + math.cos(y) * face.e_short
    R = np.zeros((3, 3))
    R[:, axis] = face.normal * sign
    R[:, long_ax] = el
    R[:, short_ax] = es
    if np.linalg.det(R) < 0:  # keep it a rotation (never a mirror: text must not flip)
        R[:, short_ax] = -es
    face_c = (lo + hi) / 2
    face_c[axis] = hi[axis] if sign > 0 else lo[axis]
    origin = face.origin + offset[0] * face.e_long + offset[1] * face.e_short
    M = np.eye(4)
    M[:3, :3] = R * s
    M[:3, 3] = origin - (R * s) @ face_c
    return M


def complete_quad(
    corners: list[list[float] | None], normal: np.ndarray, K: np.ndarray
) -> np.ndarray:
    """A face with one hidden corner (None): its plane has ``normal`` (e.g. the ground's, for
    stacked lids), so the hidden corner is the 3D parallelogram's fourth point. The result does
    not depend on the plane's distance (only on its orientation)."""
    hidden = [i for i, c in enumerate(corners) if c is None]
    if not hidden:
        return np.asarray(corners, float)
    if len(hidden) > 1:
        raise ValueError("at most one hidden corner")
    k = hidden[0]
    Kinv = np.linalg.inv(K)
    pts3 = {}
    for i, c in enumerate(corners):
        if c is None:
            continue
        ray = Kinv @ np.array([c[0], c[1], 1.0])
        pts3[i] = ray / (normal @ ray) * -1.0  # on the plane n.x = -1 (in front of the camera)
    a, b, c = (k + 1) % 4, (k + 2) % 4, (k + 3) % 4  # neighbours a, c; opposite b
    p = pts3[a] + pts3[c] - pts3[b]
    q = K @ p
    out = np.asarray([c_ if c_ is not None else [0, 0] for c_ in corners], float)
    out[k] = q[:2] / q[2]
    return out


def ground_normal(faces: list[RefFace]) -> np.ndarray:
    """The shared up direction of lids lying on the ground or on each other."""
    n = np.mean([f.normal for f in faces], axis=0)
    return n / np.linalg.norm(n)
