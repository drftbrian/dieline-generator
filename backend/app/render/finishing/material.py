"""Deterministic finish materials (Milestone 4): metal foil, emboss/deboss, laminations and
clear coats, seen top-down under the flat render's studio light.

The scene: an overhead camera, a large softbox up and to the light side (``light_angle``,
0 = top, clockwise; the flat look uses 315 = top-left) and a darker room around it. A flat
mirror-like surface (foil, gloss coating) shows that softbox as a soft bright patch where its
reflection falls on the sheet, and the room elsewhere; the patch's edge softens with roughness.
Tilts of the surface (foil impression rim, paper micro-relief, relief shoulders) move the
reflection, which is what makes foil sparkle and edges catch light.

Tone levels come from measured reference photos (``calibration.json``, written by
``scripts/finish_calibrate.py``); nothing here is fitted to the artwork. Contract shared with the
placeholder: masks come only from source geometry and every pixel outside the returned region
is the source pixel.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from scipy import ndimage

from app.finishing import catalog
from app.render import shading
from app.render.finishing import placeholder
from app.render.folds import light_vector

CALIBRATION = Path(__file__).with_name("calibration.json")
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)

# Models this module renders; the rest still use the placeholder (M5).
MODELS = {"metal", "relief", "clearcoat"}


@cache
def calibration() -> dict:
    return json.loads(CALIBRATION.read_text())


@dataclass(frozen=True)
class Scene:
    """Where the crop sits in the full flat render, and the light."""

    px_per_mm: float
    offset: tuple[int, int] = (0, 0)  # (y, x) of the crop in the full image
    full: tuple[int, int] = (0, 0)  # (h, w) of the full image (0 = the crop is the image)
    light_angle: float = 315.0
    light_elevation_deg: float = 35.0  # soft key; a raking light is ~12°
    # The softbox's reflection on the sheet: centre (fractions of the image) and radius.
    softbox: tuple[float, float] = (0.30, 0.26)
    softbox_radius: float = 0.42
    camera_tilt_gain: float = 3.0  # how far a surface tilt moves the reflection (sheet widths)
    # Relief under a large soft key is far gentler than in the (raking) reference photos.
    relief_light: float = 0.3


def _grid(shape, scene: Scene) -> tuple[np.ndarray, np.ndarray]:
    """Image-normalised coordinates (u right, v down) of the crop's pixels in the full image."""
    h, w = shape
    fh, fw = scene.full if scene.full[0] else shape
    side = float(max(fh, fw))
    y0, x0 = scene.offset
    yy, xx = np.mgrid[y0 : y0 + h, x0 : x0 + w].astype(np.float32)
    return xx / side, yy / side


def _hash_noise(shape, scene: Scene, seed: float) -> np.ndarray:
    """Deterministic white noise tied to absolute pixel position (same in any crop)."""
    h, w = shape
    y0, x0 = scene.offset
    yy, xx = np.mgrid[y0 : y0 + h, x0 : x0 + w].astype(np.float64)
    v = np.sin(xx * 12.9898 + yy * 78.233 + seed * 37.719) * 43758.5453
    return (v - np.floor(v)).astype(np.float32)


def _slopes(height_mm: np.ndarray, px_per_mm: float) -> tuple[np.ndarray, np.ndarray]:
    gy, gx = np.gradient(height_mm)
    return gx * px_per_mm, gy * px_per_mm


def reflection(
    shape, scene: Scene, sx: np.ndarray | float, sy: np.ndarray | float, roughness: float
) -> np.ndarray:
    """0..1: how much of the softbox a mirror-like surface reflects at each pixel. ``sx, sy``
    are the surface slopes (a tilt moves the reflection by twice its angle)."""
    u, v = _grid(shape, scene)
    cu, cv = scene.softbox
    du = u - cu + scene.camera_tilt_gain * 2 * np.asarray(sx, np.float32) * scene.softbox_radius
    dv = v - cv + scene.camera_tilt_gain * 2 * np.asarray(sy, np.float32) * scene.softbox_radius
    r = np.sqrt(du * du + dv * dv) / scene.softbox_radius
    edge = 0.04 + 0.6 * roughness  # rough surfaces blur the softbox's edge
    return (1 / (1 + np.exp((r - 1) / edge))).astype(np.float32)


def strip(m: np.ndarray, scene: Scene, sx, sy, roughness: float) -> np.ndarray:
    """0..1: a strip light's reflection on one foil shape: a long soft band crossing it
    diagonally a little toward the light, as product photographers light foil (every
    reference photo shows such a sweep). Surface tilts bend it."""
    ys, xs = np.nonzero(m > 0.01)
    if not ys.size:
        return np.zeros_like(m)
    cy, cx = (ys.min() + ys.max()) / 2, (xs.min() + xs.max()) / 2
    diag = float(np.hypot(ys.max() - ys.min(), xs.max() - xs.min())) + 1
    lx, ly = shading.light_dir(scene.light_angle)  # toward the light, image coordinates
    cx, cy = cx + 0.18 * diag * lx, cy + 0.18 * diag * ly
    yy, xx = np.mgrid[0 : m.shape[0], 0 : m.shape[1]].astype(np.float32)
    shift = scene.camera_tilt_gain * 2 * 0.1 * diag
    du = xx - cx + shift * np.asarray(sx, np.float32)
    dv = yy - cy + shift * np.asarray(sy, np.float32)
    d = (du * lx + dv * ly) / diag  # across the band: along the light direction
    width = 0.10 + 0.5 * roughness
    return np.exp(-((d / width) ** 2)).astype(np.float32)


def _tint(f: catalog.Finish) -> tuple[np.ndarray, dict]:
    """Body colour (unit luminance) from the catalogue colour, tone levels measured from the
    reference photos (gold for gold, the neutral silver levels for the other metals)."""
    cal = calibration()
    levels = cal["gold"] if f.id == "foil.gold" else cal["silver"]
    h = (f.color or "#C0C0C0").lstrip("#")
    rgb = np.array([int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)
    return rgb / max(float(rgb @ LUMA), 1e-3), levels


def metal(img: np.ndarray, m: np.ndarray, f: catalog.Finish, p: dict, scene: Scene) -> np.ndarray:
    """Hot-foil stamped metal: an opaque mirror-like film that hides the ink under it."""
    ppm = scene.px_per_mm
    rough = float(p.get("roughness", 0.12))
    refl = float(p.get("reflectivity", 0.9))
    glint = float(p.get("glint", 0.5))
    reflector = float(p.get("reflector", 0.5))
    impression = float(p.get("impression_mm", 0.02))
    tint, lv = _tint(f)
    # Surface: the die presses the foil a hair into the board (a rounded rim), and the foil
    # follows the paper's micro-relief (fine, random tilts: the sparkle).
    rim = ndimage.gaussian_filter(m, max(0.6, 0.12 * ppm)) * -impression
    sx, sy = _slopes(rim, ppm)
    # Micro-relief: fine (sub-0.1 mm), low tilts; it breaks the reflection up a little.
    sg = max(0.6, 0.02 * ppm)
    grain = ndimage.gaussian_filter(_hash_noise(m.shape, scene, 1.0) - 0.5, sg)
    # Fixed scale (3 sigma of blurred uniform noise), not the crop's own max: same in any crop.
    grain /= 3 * 0.2887 / (2 * np.sqrt(np.pi) * sg)
    gx, gy = np.gradient(grain)
    tilt = 0.004 * glint * (1 - 0.5 * rough)
    sx, sy = sx + tilt * gx * 10, sy + tilt * gy * 10
    soft = reflection(m.shape, scene, sx, sy, rough)
    band = strip(m, scene, sx, sy, rough)
    # Tone: the room (dark) where no light is mirrored, lifted by a reflector card near the
    # camera; the softbox a broad lift, the strip light the bright sweep. Reflectivity scales
    # the contrast around the body tone.
    dark = lv["shadow"] + 0.5 * reflector * (lv["body"] - lv["shadow"])
    tone = dark + 0.45 * soft * (lv["body"] - dark) + band * (lv["highlight"] - dark)
    tone = lv["body"] + (tone - lv["body"]) * (0.6 + 0.4 * refl)
    # Sparkle: a few micro-facets catch the light even outside the bright areas.
    sparkle = np.clip((_hash_noise(m.shape, scene, 2.0) - 0.995) / 0.005, 0, 1)
    tone = np.clip(tone + glint * 0.12 * sparkle * (1 - rough), 0, 1)[..., None]
    # Colour: metal tints its reflection most in the mid and dark tones (rich gold, deep
    # bronze shadows); the brightest highlights go towards white.
    rich = 1 + (tint - 1) * (0.6 + 1.4 * np.clip(1 - tone / lv["highlight"], 0, 1))
    whiten = np.clip((tone - lv["body"]) / max(1e-3, 1 - lv["body"]), 0, 1) ** 1.5 * 0.7
    col = np.clip(rich * tone * (1 - whiten) + tone * whiten, 0, 1)
    a = m[..., None]
    return img * (1 - a) + col * a


def relief(img: np.ndarray, m: np.ndarray, f: catalog.Finish, p: dict, scene: Scene) -> np.ndarray:
    """Emboss / deboss: a height field from the mask, shaded by the key light (Lambert relative
    to the flat board), so the side facing the light brightens and the other darkens."""
    ppm = scene.px_per_mm
    depth = float(p.get("depth_mm", 0.3)) * (-1.0 if f.id.endswith("deboss") else 1.0)
    shoulder = float(p.get("shoulder_mm", 0.4))
    softness = float(p.get("softness", 0.4))
    balance = float(p.get("shadow_balance", 0.5))
    sigma = max(0.8, shoulder * ppm * (0.35 + 0.4 * softness))
    h = ndimage.gaussian_filter((m > 0.5).astype(np.float32), sigma) * depth
    sx, sy = _slopes(h, ppm)
    n = np.dstack([-sx, -sy, np.ones_like(sx)])
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    lv = light_vector(scene.light_angle, scene.light_elevation_deg)
    lit = (n @ lv.astype(np.float32)) / float(lv[2]) - 1
    cal = calibration()["relief"]
    k = scene.relief_light
    hi = np.clip(lit, 0, None) * (0.5 + balance) * k
    lo = np.clip(-lit, 0, None) * (1.5 - balance) * k
    # Inside a deboss the walls also shade the floor a little (occlusion).
    occl = 0.0
    if depth < 0:
        occl = np.clip(-h / max(abs(depth), 1e-6), 0, 1) * 0.03
    gain = 1 + np.clip(hi, 0, cal["highlight"] * k) - np.clip(lo + occl, 0, -cal["shadow"] * k)
    return np.clip(img * gain[..., None], 0, 1)


def relief_region(m: np.ndarray, p: dict, scene: Scene) -> np.ndarray:
    """Where a relief may change pixels: the shape plus its shoulder."""
    reach = max(2, int(np.ceil(float(p.get("shoulder_mm", 0.4)) * scene.px_per_mm * 1.6)))
    return ndimage.binary_dilation(m > 0, iterations=reach)


def _saturate(img: np.ndarray, k: float) -> np.ndarray:
    y = (img @ LUMA)[..., None]
    return y + (img - y) * k


def clearcoat(
    img: np.ndarray, m: np.ndarray, f: catalog.Finish, p: dict, scene: Scene
) -> np.ndarray:
    """Clear layers: gloss (lamination, UV, varnish) deepens colour and mirrors the softbox as a
    soft sheen; matte films scatter: lower contrast, a slight veil lifting the darks."""
    rough = float(p.get("roughness", 0.1))
    gloss = float(p.get("gloss", 0.8))
    sat = float(p.get("saturation", 0.0))
    veil = float(p.get("veil", 0.0))
    out = _saturate(img, 1 + sat)
    if rough < 0.2:  # glossy: darks go deeper (less surface scatter), a wet look
        out = out * (1 - 0.05 * gloss) - 0.02 * gloss * (1 - out)
    else:  # matte: scattered surface light lifts darks, softens colour
        out = _saturate(out, 1 - 0.25 * rough) * (1 - veil) + veil
    s = reflection(m.shape, scene, 0.0, 0.0, rough)
    peak = gloss * (1 - rough) ** 2
    if f.id in ("coating.spot_uv", "coating.varnish_gloss", "coating.flood_uv"):
        # A thick clear layer: its edge is a small bevel that catches the key light.
        cal = calibration()["spot_uv"]
        ppm = scene.px_per_mm
        h = ndimage.gaussian_filter((m > 0.5).astype(np.float32), max(0.7, 0.08 * ppm)) * 0.02
        sx, sy = _slopes(h, ppm)
        lv = light_vector(scene.light_angle, scene.light_elevation_deg)
        edge = np.clip((-sx * lv[0] - sy * lv[1]) * 40, -1, 1)
        sheen = s * peak * (cal["gloss_peak"] - cal["matte_base"]) * 0.35
        out = (
            out
            + (
                sheen + 0.22 * peak * np.clip(edge, 0, None) - 0.06 * peak * np.clip(-edge, 0, None)
            )[..., None]
        )
    else:
        # A film over the whole sheet: a broad, faint sheen (never a white band).
        out = out + (s * peak * 0.07)[..., None]
    a = m[..., None]
    return np.clip(img * (1 - a) + np.clip(out, 0, 1) * a, 0, 1)


RENDER = {"metal": metal, "relief": relief, "clearcoat": clearcoat}


def render(
    base: np.ndarray,
    layers: list[tuple[catalog.Finish, dict, np.ndarray]],
    scene: Scene,
) -> tuple[np.ndarray, np.ndarray]:
    """``base`` HxWx3 float with the enabled assignments in layer order (substrate coats, foils,
    relief, dome). Returns the image and the region any finish may have changed."""
    out = base.copy()
    changed = np.zeros(base.shape[:2], bool)
    for f, params, m in sorted(layers, key=lambda x: placeholder.LAYER.get(x[0].model, 9)):
        if not m.any():
            continue
        if f.model in RENDER:
            region = relief_region(m, params, scene) if f.model == "relief" else m > 0
            new = RENDER[f.model](out, m, f, params, scene).astype(np.float32)
        else:
            new, region = placeholder.render(out, [(f, params, m)])
            new = new.astype(np.float32)
        out = np.where(region[..., None], new, out)
        changed |= region
    return out, changed
