"""Verification and correction of a generated photo's printed text and logos (PRD v2 §4A).

For each registered visible face:

- **Source:** the panel's print rendered by MuPDF from the artwork PDF (the Figma glyph and
  vector outlines, never re-typeset), at about the photo's pixel density.
- **Light:** the photo's own light on that face, ``L = smooth(photo / source)``, estimated only
  where neither image has an edge (glyph strokes, the model's lettering and overlays are
  excluded and outliers rejected), so ``L`` keeps the studio gradient, shadows and colour cast
  but never a letter. Luminance and a narrow, heavily smoothed chroma are kept apart: a white
  glyph takes the paper's light, not the model's hue errors.
- **Prediction:** ``source × L``, what the face should look like in this photo.
- **Verification:** every manifest item on the face is compared with the prediction (gradient
  correlation, best local shift, residual lettering). Differences outside every item are
  *unexpected* content: hallucinated text, pseudo logos, reference-brand print, watermarks.
  A large difference (an occluder or a wrong face) is never painted over.
- **Correction:** ``out = photo + m × (source × L − photo)`` with a feathered repair mask
  ``m``: item footprints and unexpected content (``text_corrected``) or the whole face
  (``strict``). Outside ``m`` the photo is untouched, so its shading, shadows and edges stay
  the model's; inside, the shading is the model's smooth light and the letterforms are Figma's.

Nothing here changes the raw image, the manifest or the source.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pymupdf
from scipy import ndimage

from app.typography import register as rg

PAPER = np.array([0.94, 0.93, 0.90], np.float32)  # unprinted board under transparent artwork
LIGHT_SIGMA = 0.02  # light smoothing, fraction of the face's long edge
LIGHT_EDGE = 400  # px, long edge the paper colour is modelled at
SHADOW_EDGE = 1000  # px, long edge the light (with its hard shadow edges) is estimated at
LIGHT_OUTLIER = 0.08  # relative deviation from the light that is not plain paper
BRIGHT_STROKES = 3  # bright marks up to this many strokes wide are overlays, not light
STROKE = 0.03  # widest lettering stroke, fraction of the face's long edge: thinner is not light
CHROMA_LIMIT = 0.08  # the light's colour may differ from grey by at most this per channel
DIFF_REL = 0.05  # a pixel differs from the prediction by more than this (relative) ...
DIFF_ABS = 0.025  # ... and this (absolute luminance)
LEGIBLE_PX = 8.0  # glyph x-height in photo px below which text is not verified
MATCH_NCC = 0.8  # item gradient correlation for a match
APPROX_NCC = 0.5  # below this the item is not the source item (wrong / missing / hallucinated)
RESIDUAL_GLYPH = 0.06  # residual lettering, in glyph cells, above which an item is not a match
WRONG_GLYPHS = 1.5  # this many glyph cells of residual lettering: wrong or missing characters
LARGE_DIFF = 0.05  # a difference covering more than this of the face ...
OCCLUSION_TILE = 0.04  # tile size of the occlusion test, fraction of the long edge
OCCLUSION_DARK = 0.8  # an occluder extends over the connected area this much darker than the face
OCCLUSION_LEFT = 0.25  # photo detail below this share of the lit source detail: occluded
SOLID = 0.5  # ... and more than this of its own box: an occluder or a wrong face
EDGE_INSET = 0.025  # face fraction at the borders left to the photo (fold edges, highlights)
HAIRLINE = 0.006  # an overlay reaching the border is removed up to this close to the edge
SHADING_TOL = 0.03  # low-pass luminance change allowed outside removed content
FAINT_SIGMA = 2.0  # px, gradient scale for faint overlays
FAINT_EDGE = 0.0015  # gradient a faint overlay edge must exceed the prediction's by
GROUP = 0.015  # differences closer than this (face fraction) are one mark
FAINT_SPAN = 0.04  # a faint mark is a connected stroke at least this long (face fraction)
INK_DIFF = 0.04  # a source pixel this far from its item's surrounding paper is ink
SOLID_GRAPHIC = 0.6  # a graphic inking more of its box is a solid shape, coloured like paper
INK_GAIN = (0.5, 1.5)  # bounds of the photo's print contrast relative to the source
PAPER_HUE = 0.4  # bound of the residual colour field over the per-face colour map
PACKAGE_ZONE = 0.05  # image fraction above and below the faces that belongs to the package
OVERLAY_BRIGHT = 0.05  # a backdrop mark this much brighter than the local backdrop ...
OVERLAY_MIN_AREA = 150  # ... and this large (px at 1200 px long edge) is an overlay, not texture
OVERLAY_OPEN = 41  # px at 1200 px long edge: backdrop marks narrower than this are overlays


@dataclass
class FaceSource:
    face_id: str
    name: str
    bbox_pt: tuple[float, float, float, float]
    rgb: np.ndarray  # HxWx3, the print over board, at the analysis raster
    unresolved: np.ndarray  # HxW bool, items whose glyph geometry is not available
    px_per_pt: tuple[float, float]
    lettering: np.ndarray | None = None  # HxW bool, glyph pixels of text and letter-like logos


@dataclass
class FaceResult:
    face_id: str
    registration: dict
    items: list[dict] = field(default_factory=list)
    unexpected: list[dict] = field(default_factory=list)
    light: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    review: list[str] = field(default_factory=list)


def render_panel(pdf: bytes, bbox_pt, size: tuple[int, int]) -> np.ndarray:
    """The panel's print at ``size`` (w, h) px, composited over the board colour."""
    w, h = size
    x0, y0, x1, y1 = bbox_pt
    page = pymupdf.open(stream=pdf, filetype="pdf")[0]
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(w / (x1 - x0), h / (y1 - y0)),
        clip=pymupdf.Rect(x0, y0, x1, y1),
        alpha=True,
        annots=False,
    )
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 4).astype(np.float32) / 255
    rgb = a[..., :3] + PAPER * (1 - a[..., 3:])  # premultiplied over the board
    out = np.ones((h, w, 3), np.float32) * PAPER
    out[: min(h, rgb.shape[0]), : min(w, rgb.shape[1])] = rgb[:h, :w]
    return np.clip(out, 0, 1)


def face_source(pdf: bytes, face_id: str, name: str, bbox_pt, quad, items: list[dict]) -> FaceSource:
    """The source panel at about the photo's density on this face (never coarser)."""
    q = np.asarray(quad, float)
    w_pt, h_pt = bbox_pt[2] - bbox_pt[0], bbox_pt[3] - bbox_pt[1]
    w_px = max(np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[2] - q[3]))
    h_px = max(np.linalg.norm(q[3] - q[0]), np.linalg.norm(q[2] - q[1]))
    d = max(w_px / w_pt, h_px / h_pt)
    size = (max(8, round(w_pt * d)), max(8, round(h_pt * d)))
    rgb = render_panel(pdf, bbox_pt, size)
    unresolved = np.zeros(rgb.shape[:2], bool)
    for it in items:
        if it["geometry"] == "unresolved":
            x0, y0, x1, y1 = _window(it, bbox_pt, (d, d), rgb.shape[:2], pad=2)
            unresolved[y0:y1, x0:x1] = True
    src = FaceSource(face_id, name, tuple(bbox_pt), rgb, unresolved, (d, d))
    src.lettering = lettering_mask(src, items)
    return src


def lettering_mask(src: FaceSource, items: list[dict]) -> np.ndarray:
    """Glyph pixels: inside each text item's box (or a letter-like logo's: strokes with paper
    between them, not a solid shape), the pixels that differ from the paper around the box. A
    big letter's interior is ink however far it is from an edge; only the manifest says so."""
    h, w = src.rgb.shape[:2]
    out = np.zeros((h, w), bool)
    for it in items:
        x0, y0, x1, y1 = _window(it, src.bbox_pt, src.px_per_pt, (h, w), pad=2)
        if x1 - x0 < 3 or y1 - y0 < 3:
            continue
        win = src.rgb[y0:y1, x0:x1]
        ring = np.concatenate([win[0], win[-1], win[:, 0], win[:, -1]])
        ink = np.abs(win - np.median(ring, 0)).max(-1) > INK_DIFF
        if it["kind"] == "text" or ink.mean() < SOLID_GRAPHIC:
            out[y0:y1, x0:x1] |= ink
    return ndimage.binary_dilation(out, iterations=2)


def _window(item: dict, bbox_pt, px_per_pt, shape, pad: int = 0) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = item["bbox_pt"]
    sx, sy = px_per_pt
    h, w = shape
    return (
        max(0, int((x0 - bbox_pt[0]) * sx) - pad),
        max(0, int((y0 - bbox_pt[1]) * sy) - pad),
        min(w, int(np.ceil((x1 - bbox_pt[0]) * sx)) + pad),
        min(h, int(np.ceil((y1 - bbox_pt[1]) * sy)) + pad),
    )


def _nconv(v: np.ndarray, w: np.ndarray, sigma: float) -> np.ndarray:
    """Normalised convolution: the weighted local mean, widening where there is no data."""
    out = np.full(v.shape, np.nan, np.float32)
    for s in (sigma, sigma * 4, sigma * 16):
        num = ndimage.gaussian_filter(v * w, s)
        den = ndimage.gaussian_filter(w.astype(np.float32), s)
        fill = np.isnan(out) & (den > 0.05)
        out[fill] = (num[fill] / den[fill]).astype(np.float32)
    if np.isnan(out).any():
        out[np.isnan(out)] = float(np.median(v[w > 0])) if (w > 0).any() else 1.0
    return out


def _down(a: np.ndarray, edge: int) -> np.ndarray:
    f = max(a.shape[:2]) / edge
    if f <= 1:
        return a
    sig = [f / 2, f / 2] + ([0] if a.ndim == 3 else [])
    zoom = [1 / f, 1 / f] + ([1] if a.ndim == 3 else [])
    return ndimage.zoom(ndimage.gaussian_filter(a, sig), zoom, order=1).astype(np.float32)


def _up(a: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    zoom = [shape[0] / a.shape[0], shape[1] / a.shape[1]] + ([1] if a.ndim == 3 else [])
    out = ndimage.zoom(a, zoom, order=1)
    pad = [(0, max(0, shape[0] - out.shape[0])), (0, max(0, shape[1] - out.shape[1]))]
    if a.ndim == 3:
        pad.append((0, 0))
    return np.pad(out, pad, mode="edge")[: shape[0], : shape[1]].astype(np.float32)


def estimate_light(
    photo: np.ndarray, src: np.ndarray, valid: np.ndarray
) -> tuple[np.ndarray, np.ndarray, dict]:
    """The photo's light on the face (HxWx3, no letter in it) and the low-resolution weights of
    the pixels where both images agree.

    Light varies over areas wider than a stroke; lettering, watermarks and pseudo logos are
    strokes. So the light is the photo/source ratio with everything thinner than ``STROKE``
    removed by a grey closing (dark marks) and opening (bright marks, up to ``BRIGHT_STROKES``
    strokes wide): a hard leaf shadow or a shadow band survives at full depth, a letter or a
    watermark never does. No outlier test can mistake a
    deep shadow for an error this way."""
    P, S = _down(photo, SHADOW_EDGE), _down(src, SHADOW_EDGE)
    ok = _down(valid.astype(np.float32), SHADOW_EDGE) > 0.99
    lp, ls = rg.luminance(P), rg.luminance(S)
    r = lp / np.maximum(ls, 0.03)
    edges = (ndimage.gaussian_gradient_magnitude(ls, 1.0) > 0.01) | (
        ndimage.gaussian_gradient_magnitude(lp, 1.0) > 0.012
    )
    w0 = ok & ~ndimage.binary_dilation(edges, iterations=2)
    sigma = LIGHT_SIGMA * max(P.shape[:2])
    stroke = max(3, round(STROKE * max(P.shape[:2])))
    filled = _nconv(r, w0.astype(np.float32), 1.0)
    # Dark marks narrower than a stroke are print; a hard shadow is wider. Bright marks are held
    # to a wider test: light brightens broadly, a watermark or pseudo logo is a crisp patch.
    L = ndimage.grey_opening(ndimage.grey_closing(filled, size=stroke), size=stroke * BRIGHT_STROKES)
    L = ndimage.gaussian_filter(L, 1.0).astype(np.float32)  # morphology keeps shadow edges sharp
    w = w0 & (np.abs(r / np.maximum(L, 1e-3) - 1) < LIGHT_OUTLIER)
    c = np.stack(
        [_nconv(P[..., k] / np.maximum(S[..., k] * L, 1e-3), w.astype(np.float32), sigma * 3) for k in range(3)],
        -1,
    )
    c = np.clip(c, 1 - CHROMA_LIMIT, 1 + CHROMA_LIMIT)
    c /= np.maximum(c @ rg.LUMA, 1e-3)[..., None]
    light = _up(L[..., None] * c, src.shape[:2])
    stats = {
        "used_fraction": round(float(w.mean()), 3),
        "luminance_p1_p50_p99": [round(float(v), 3) for v in np.percentile(L[ok], [1, 50, 99])] if ok.any() else None,
        "chroma_max_dev": round(float(np.abs(c - 1).max()), 3),
    }
    # The paper is modelled at LIGHT_EDGE: its weights at that raster.
    w_full = _up(w.astype(np.float32), src.shape[:2])  # same raster as every other LIGHT_EDGE array
    return light, (_down(w_full, LIGHT_EDGE) > 0.99).astype(np.float32), stats


def paper(img: np.ndarray, w: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """``img`` without its lettering: its unlettered pixels (``w``) spread smoothly."""
    lo = _down(img, LIGHT_EDGE)
    sigma = 0.5 * LIGHT_SIGMA * max(lo.shape[:2])
    return _up(np.stack([_nconv(lo[..., k], w, sigma) for k in range(3)], -1), shape)


def ink_contrast(p_detail: np.ndarray, s_detail: np.ndarray, mask: np.ndarray) -> float:
    """How strongly the photo renders lettering against its paper, relative to the source.

    Matched by distribution (the 98th percentile of |ink − paper| over the lettering), so it
    needs no glyph alignment and never borrows a glyph shape."""
    if mask.sum() < 50:
        return 1.0
    pa = np.percentile(np.abs(rg.luminance(p_detail))[mask], 98)
    pb = np.percentile(np.abs(rg.luminance(s_detail))[mask], 98)
    return float(np.clip(pa / max(pb, 1e-3), *INK_GAIN))


def ink_chroma(p_detail: np.ndarray, detail: np.ndarray, p_paper: np.ndarray, letters: np.ndarray) -> float:
    """How much of the source lettering's colour difference to keep (0..1.2).

    White type on our paler paper differs from it in blue; on the model's more saturated paper
    the same white differs more. Chosen so the strongest lettering pixels get the photo's
    lettering hue (matched by distribution, never by position)."""
    if letters.sum() < 50:
        return 1.0

    def hue(rgb):
        c = rgb - rg.luminance(rgb)[..., None]
        return c.mean(0)

    pm = np.abs(rg.luminance(p_detail))[letters]
    target = hue((p_paper + p_detail)[letters][pm >= np.percentile(pm, 95)])
    dm = np.abs(rg.luminance(detail))[letters]
    top = dm >= np.percentile(dm, 95)
    lum = rg.luminance(detail)[letters][top][..., None]
    chroma = detail[letters][top] - lum
    base = p_paper[letters][top]
    ks = np.linspace(0, 1.2, 13)
    errs = [np.abs(hue(base + lum + k * chroma) - target).sum() for k in ks]
    return float(ks[int(np.argmin(errs))])


def photo_paper(photo: np.ndarray, s_paper: np.ndarray, w: np.ndarray, light: np.ndarray) -> np.ndarray:
    """The photo's paper, modelled from the source paper so a hole never gets a made-up colour.

    1. The face's light (``estimate_light``: shadows included, measured everywhere, holes too).
    2. One affine colour map per face, ``photo ≈ M · [source × light, 1]``, fitted on plain
       paper: the model's paper is usually a re-coloured version of ours (more saturated,
       warmer). It acts on colours, never on positions.
    3. A bounded, smooth residual field for what the map misses, spread into holes (a removed
       overlay) from ever wider surroundings, so a repair's edges match the photo and its
       interior follows the source's own gradient."""
    P, S = _down(photo, LIGHT_EDGE), _down(s_paper, LIGHT_EDGE)
    sigma = LIGHT_SIGMA * max(P.shape[:2])
    lum = rg.luminance(_down(light, LIGHT_EDGE))
    X = (S * lum[..., None]).reshape(-1, 3)
    sel = w.ravel() > 0
    if sel.sum() >= 50:
        A = np.concatenate([X[sel], np.ones((int(sel.sum()), 1), np.float32)], 1)
        M, *_ = np.linalg.lstsq(A, P.reshape(-1, 3)[sel], rcond=None)
        mapped = np.concatenate([X, np.ones((X.shape[0], 1), np.float32)], 1) @ M
    else:
        mapped = X
    mapped = np.clip(mapped.reshape(P.shape), 0.01, 1.5)
    resid = np.stack([_nconv(P[..., k] / mapped[..., k], w, sigma) for k in range(3)], -1)
    q = mapped * np.clip(resid, 1 - PAPER_HUE, 1 + PAPER_HUE) / np.maximum(S, 0.02)
    return np.clip(s_paper * _up(q, s_paper.shape[:2]), 0, 1)


def _diff(p_lum: np.ndarray, pred_lum: np.ndarray) -> np.ndarray:
    """Pixels that differ from the prediction beyond a 1 px misregistration tolerance."""
    lo = ndimage.grey_erosion(pred_lum, size=3)
    hi = ndimage.grey_dilation(pred_lum, size=3)
    d = np.maximum(p_lum - hi, lo - p_lum)
    m = (d > DIFF_ABS) & (d > DIFF_REL * np.maximum(pred_lum, 0.05))
    return ndimage.binary_opening(m, np.ones((2, 2), bool))


def _inner(shape: tuple[int, int]) -> np.ndarray:
    h, w = shape
    m = np.zeros(shape, bool)
    iy, ix = max(2, round(h * EDGE_INSET)), max(2, round(w * EDGE_INSET))
    m[iy : h - iy, ix : w - ix] = True
    return m


def _gncc(a: np.ndarray, b: np.ndarray) -> float:
    ga = ndimage.gaussian_gradient_magnitude(a, 1.0).ravel()
    gb = ndimage.gaussian_gradient_magnitude(b, 1.0).ravel()
    ga, gb = ga - ga.mean(), gb - gb.mean()
    d = float(np.sqrt((ga * ga).sum() * (gb * gb).sum()))
    return float((ga * gb).sum() / d) if d > 0 else 0.0


def _photo_density(quad, bbox_pt) -> tuple[float, float]:
    q = np.asarray(quad, float)
    w_pt, h_pt = bbox_pt[2] - bbox_pt[0], bbox_pt[3] - bbox_pt[1]
    du = min(np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[2] - q[3])) / w_pt
    dv = min(np.linalg.norm(q[3] - q[0]), np.linalg.norm(q[2] - q[1])) / h_pt
    return du, dv


def verify_items(
    src: FaceSource, items: list[dict], p_lum: np.ndarray, pred_lum: np.ndarray, diff: np.ndarray, quad
) -> list[dict]:
    du, dv = _photo_density(quad, src.bbox_pt)
    out = []
    for it in items:
        if it["kind"] == "text":
            glyph = (it["size_pt"] or 0) * min(du, dv) * 0.55  # about the x-height
        else:
            b = it["bbox_pt"]
            glyph = min(b[2] - b[0], b[3] - b[1]) * min(du, dv)
        rec = {
            "id": it["id"],
            "kind": it["kind"],
            "text": it["text"],
            "role": it["role"],
            "glyph_px": round(float(glyph), 1),
        }
        if it["geometry"] == "unresolved":
            out.append({**rec, "status": "unresolved", "note": "font not embedded and no outline"})
            continue
        x0, y0, x1, y1 = _window(it, src.bbox_pt, src.px_per_pt, p_lum.shape, pad=3)
        if x1 - x0 < 6 or y1 - y0 < 6:
            out.append({**rec, "status": "not_visible"})
            continue
        if glyph < LEGIBLE_PX:
            out.append({**rec, "status": "not_verifiable", "note": "too small at this resolution"})
            continue
        ref = pred_lum[y0:y1, x0:x1]
        ncc0 = _gncc(p_lum[y0:y1, x0:x1], ref)
        smax = int(max(3, min(40, glyph * 0.8)))
        best, shift = ncc0, (0, 0)
        for dy in range(-smax, smax + 1, max(1, smax // 6)):
            for dx in range(-smax, smax + 1, max(1, smax // 6)):
                ys, xs = y0 + dy, x0 + dx
                if ys < 0 or xs < 0 or ys + ref.shape[0] > p_lum.shape[0] or xs + ref.shape[1] > p_lum.shape[1]:
                    continue
                v = _gncc(p_lum[ys : ys + ref.shape[0], xs : xs + ref.shape[1]], ref)
                if v > best:
                    best, shift = v, (dx, dy)
        resid = float(diff[y0:y1, x0:x1].sum()) / max(glyph * glyph * 4, 1.0)
        if ncc0 >= MATCH_NCC and resid <= RESIDUAL_GLYPH:
            status = "match"
        elif best >= MATCH_NCC and max(abs(shift[0]), abs(shift[1])) >= 2:
            status = "misplaced"
        elif best >= APPROX_NCC and resid < WRONG_GLYPHS:
            status = "approximate"  # same words and place, letterforms not Figma's
        else:
            status = "mismatch"
        out.append(
            {
                **rec,
                "status": status,
                "ncc": round(ncc0, 3),
                "best_ncc": round(best, 3),
                "shift_px": list(shift),
                "residual_glyphs": round(resid, 3),
                "window_px": [x0, y0, x1, y1],
            }
        )
    return out


def faint_marks(p_lum: np.ndarray, pred_lum: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Faint overlays (a watermark a few percent brighter than white paper): edges in the photo
    that the prediction does not have, kept only where they form long connected strokes, so
    paper grain and JPEG noise never qualify."""
    gp = ndimage.gaussian_gradient_magnitude(p_lum, FAINT_SIGMA)
    gs = ndimage.grey_dilation(ndimage.gaussian_gradient_magnitude(pred_lum, FAINT_SIGMA), size=7)
    noise = float(np.percentile(gp[valid], 50)) if valid.any() else 0.0
    e = (gp - gs > max(FAINT_EDGE, 2.0 * noise)) & valid
    e = ndimage.binary_closing(e, np.ones((5, 5), bool))
    lab, n = ndimage.label(e)
    out = np.zeros_like(e)
    span = FAINT_SPAN * max(p_lum.shape)
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        if np.hypot(sl[0].stop - sl[0].start, sl[1].stop - sl[1].start) >= span:
            out[sl] |= lab[sl] == i
    return out


def occluded(p_lum: np.ndarray, s_lum: np.ndarray, light_lum: np.ndarray, valid: np.ndarray) -> list[dict]:
    """Regions where the source has print but the photo shows none of it.

    A shadow darkens the print and keeps it (the light model absorbs it); an object in front
    hides it. Tile by tile, the photo's fine detail is compared with the source's detail times
    the light: almost none of it left means occluded, never repaired."""
    h, w = p_lum.shape
    t = max(16, round(OCCLUSION_TILE * max(h, w)))
    hp_p = p_lum - ndimage.gaussian_filter(p_lum, 2)
    hp_s = s_lum - ndimage.gaussian_filter(s_lum, 2)
    ny, nx = h // t, w // t
    occ = np.zeros((ny, nx), bool)
    for j in range(ny):
        for i in range(nx):
            sl = (slice(j * t, (j + 1) * t), slice(i * t, (i + 1) * t))
            if not valid[sl].all():
                continue
            s_std = float(hp_s[sl].std())
            if s_std > 0.02 and float(hp_p[sl].std()) < OCCLUSION_LEFT * s_std * float(light_lum[sl].mean()):
                occ[j, i] = True
    seed = np.zeros((h, w), bool)
    seed[: ny * t, : nx * t] = np.kron(occ, np.ones((t, t), bool))
    # The object goes on where the "light" stays as dark as under the hidden print.
    dark = valid & (light_lum < OCCLUSION_DARK * float(np.median(light_lum[valid])))
    region = ndimage.binary_propagation(seed & dark, mask=dark) | seed
    lab, _ = ndimage.label(region)
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        area = int((lab[sl] == i).sum())
        if area >= 2 * t * t:
            box = [sl[1].start, sl[0].start, sl[1].stop, sl[0].stop]
            out.append({"bbox_px": box, "area_px": area, "large": True, "occluded": True})
    return out


def find_unexpected(diff: np.ndarray, windows: list[tuple[int, int, int, int]]) -> list[dict]:
    """Connected differences that no source item explains."""
    h, w = diff.shape
    inset = (max(2, round(h * EDGE_INSET)), max(2, round(w * EDGE_INSET)))
    d = diff.copy()
    d[: inset[0]] = d[-inset[0] :] = False
    d[:, : inset[1]] = d[:, -inset[1] :] = False
    covered = np.zeros_like(d)
    for x0, y0, x1, y1 in windows:
        covered[y0:y1, x0:x1] = True
    out = []
    # An occluder (or a face we do not understand) is one big *solid* difference; lettering is
    # sparse. Judged before grouping, so nearby marks never dilute it, and over item windows too.
    lab0, _ = ndimage.label(d)
    for i, sl in enumerate(ndimage.find_objects(lab0), 1):
        comp = lab0[sl] == i
        area = int(comp.sum())
        box_area = (sl[0].stop - sl[0].start) * (sl[1].stop - sl[1].start)
        if area > LARGE_DIFF * h * w and area > SOLID * box_area:
            out.append({"bbox_px": [sl[1].start, sl[0].start, sl[1].stop, sl[0].stop], "area_px": area, "large": True})
            d[sl] &= ~comp
    # Join the strokes of one word or mark (and the pieces of one overlay) into one component.
    lab, n = ndimage.label(ndimage.binary_dilation(d, iterations=max(3, round(GROUP * max(h, w)))))
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        comp = (lab[sl] == i) & d[sl]
        area = int(comp.sum())
        if area < 30:
            continue
        if float((comp & covered[sl]).sum()) / area >= 0.7:
            continue  # part of an item's own verification
        out.append({"bbox_px": [sl[1].start, sl[0].start, sl[1].stop, sl[0].stop], "area_px": area, "large": False})
    return out


def repair_mask(
    src: FaceSource,
    items: list[dict],
    verified: list[dict],
    unexpected: list[dict],
    mode: str,
) -> np.ndarray:
    """Feathered 0..1 mask on the panel raster of the pixels taken from ``source × light``."""
    h, w = src.rgb.shape[:2]
    m = np.zeros((h, w), bool)
    if mode == "strict":
        iy, ix = max(2, round(h * EDGE_INSET)), max(2, round(w * EDGE_INSET))
        m[iy : h - iy, ix : w - ix] = True
    else:
        by_id = {v["id"]: v for v in verified}
        for it in items:
            v = by_id.get(it["id"], {})
            if v.get("status") in ("unresolved", "not_visible"):
                continue
            s = v.get("shift_px", [0, 0])
            pad = 3 + max(abs(s[0]), abs(s[1]))
            x0, y0, x1, y1 = _window(it, src.bbox_pt, src.px_per_pt, (h, w), pad=pad)
            m[y0:y1, x0:x1] = True
    # Unexpected marks are removed in both modes; one reaching the border goes to the edge.
    near = (round(h * EDGE_INSET * 1.5), round(w * EDGE_INSET * 1.5))
    hair = (max(1, round(h * HAIRLINE)), max(1, round(w * HAIRLINE)))
    for u in unexpected:
        if not u["large"]:
            x0, y0, x1, y1 = u["bbox_px"]
            x0 = hair[1] if x0 <= near[1] else max(0, x0 - 4)
            y0 = hair[0] if y0 <= near[0] else max(0, y0 - 4)
            x1 = w - hair[1] if x1 >= w - near[1] else x1 + 4
            y1 = h - hair[0] if y1 >= h - near[0] else y1 + 4
            m[y0:y1, x0:x1] = True
    for u in unexpected:
        if u["large"]:  # never paint over an occluder or a face we do not understand
            x0, y0, x1, y1 = u["bbox_px"]
            m[y0:y1, x0:x1] = False
    m &= ~src.unresolved
    soft = np.clip(ndimage.gaussian_filter(m.astype(np.float32), 3.0) * 2, 0, 1)
    soft[ndimage.binary_erosion(m, iterations=6)] = 1.0
    for u in unexpected:  # hard zero: not even the feather reaches an occluder
        if u["large"]:
            x0, y0, x1, y1 = u["bbox_px"]
            soft[y0:y1, x0:x1] = 0.0
    return soft


def composite(photo: np.ndarray, H: np.ndarray, target: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Blend the panel-space ``target`` into ``photo`` through ``H`` where ``mask`` > 0."""
    out = photo.copy()
    mp = np.zeros(photo.shape[:2], np.float32)
    corners = np.array([rg.apply_h(H, np.array([u]), np.array([v])) for u, v in rg.UNIT])[..., 0]
    x0, y0 = np.floor(corners.min(0)).astype(int)
    x1, y1 = np.ceil(corners.max(0)).astype(int)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(photo.shape[1], x1), min(photo.shape[0], y1)
    if x1 <= x0 or y1 <= y0:
        return out, mp
    Hi = np.linalg.inv(H)
    xs, ys = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
    u, v = rg.apply_h(Hi, xs, ys)
    h, w = mask.shape
    m = rg.sample(mask, u * w, v * h) * ((u >= 0) & (u <= 1) & (v >= 0) & (v <= 1))
    t = rg.sample(target, u * w, v * h)
    region = out[y0:y1, x0:x1]
    out[y0:y1, x0:x1] = region + m[..., None] * (t - region)
    mp[y0:y1, x0:x1] = m
    return out, mp


def shading_change(raw_panel: np.ndarray, out_panel: np.ndarray, keep: np.ndarray) -> dict:
    """Low-pass luminance of the result over the raw photo, where nothing was removed."""
    sigma = 0.01 * max(raw_panel.shape[:2])
    a = ndimage.gaussian_filter(rg.luminance(raw_panel), sigma)
    b = ndimage.gaussian_filter(rg.luminance(out_panel), sigma)
    r = (b / np.maximum(a, 1e-3))[keep]
    if r.size == 0:
        return {"ratio_p1_p99": None, "preserved": False}
    p1, p99 = np.percentile(r, [1, 99])
    return {
        "ratio_p1_p99": [round(float(p1), 4), round(float(p99), 4)],
        "preserved": bool(p1 >= 1 - SHADING_TOL and p99 <= 1 + SHADING_TOL),
    }


def correct_face(
    photo: np.ndarray, reg: rg.Registration, src: FaceSource, items: list[dict]
) -> tuple[FaceResult, dict[str, tuple[np.ndarray, np.ndarray]] | None]:
    """Verify one registered face; return its corrected and strict layers (target, mask)."""
    res = FaceResult(src.face_id, reg.report())
    if not reg.ok:
        res.review.append(f"{src.face_id}: registration rejected ({reg.reason})")
        return res, None
    shape = src.rgb.shape[:2]
    P = rg.to_panel(photo, reg.H, shape)
    valid = rg.inside(reg.H, shape, photo.shape[:2])
    light, w, res.light = estimate_light(P, src.rgb, valid)
    # Strict: Figma's colours under the photo's light. Text-corrected: the photo's own paper
    # (``photo_paper``: its colour, gradient and shadows) plus Figma's print as detail over
    # Figma's paper, at the photo's print contrast. Letterforms only ever come from the source;
    # the photo lends colour and light. Light is measured wherever both images agree, ink
    # included; the paper only away from lettering (a big letter's interior is not paper).
    strict = np.clip(src.rgb * light, 0, 1)
    letters = src.lettering if src.lettering is not None else np.zeros(shape, bool)
    w = w * (_down(letters.astype(np.float32), LIGHT_EDGE) < 0.01)

    def corrected_from(w):
        s_paper = paper(src.rgb, w, shape)
        detail = src.rgb - s_paper
        p_paper = photo_paper(P, s_paper, w, light)
        p_detail = P - paper(P, w, shape)
        gain = ink_contrast(p_detail, detail, letters)
        lum = rg.luminance(detail)[..., None]
        k = ink_chroma(p_detail, detail * gain, p_paper, letters)
        res.light["ink_contrast"], res.light["ink_chroma"] = round(gain, 3), round(k, 2)
        return np.clip(p_paper + (lum + k * (detail - lum)) * gain, 0, 1)

    corrected = corrected_from(w)
    p_lum = rg.luminance(P)
    inner = valid & _inner(shape)
    diff = (_diff(p_lum, rg.luminance(corrected)) | faint_marks(p_lum, rg.luminance(corrected), inner)) & valid
    res.items = verify_items(src, items, p_lum, rg.luminance(corrected), diff, reg.quad)
    windows = [tuple(v["window_px"]) for v in res.items if "window_px" in v]
    windows += [_window(it, src.bbox_pt, src.px_per_pt, shape, pad=3) for it in items]
    res.unexpected = find_unexpected(diff, windows)
    res.unexpected += occluded(p_lum, rg.luminance(src.rgb), rg.luminance(light), valid)
    removed = np.zeros(shape, bool)
    for u in res.unexpected:
        x0, y0, x1, y1 = u["bbox_px"]
        removed[y0:y1, x0:x1] = True
    if removed.any():  # again without what is removed (no faint glow left behind)
        w = w * (_down(removed.astype(np.float32), LIGHT_EDGE) < 0.01)
        corrected = corrected_from(w)
    if any(u["large"] for u in res.unexpected):
        res.review.append(f"{src.face_id}: a large difference was left untouched (occluder or wrong face?)")
    if any(v["status"] == "unresolved" for v in res.items):
        res.review.append(f"{src.face_id}: text with unavailable glyph outlines was left as generated")
    layers = {}
    for mode in ("text_corrected", "strict"):
        m = repair_mask(src, items, res.items, res.unexpected, mode)
        t = corrected if mode == "text_corrected" else strict
        layers[mode] = (t, m)
        out_panel = P + m[..., None] * (t - P)
        sig = max(2, round(0.03 * max(shape)))
        keep = valid & ~ndimage.binary_dilation(removed, iterations=sig)
        left = _diff(rg.luminance(out_panel), rg.luminance(t)) & valid
        remaining = find_unexpected(left, windows)
        fidelity = [
            round(_gncc(rg.luminance(out_panel)[v["window_px"][1] : v["window_px"][3], v["window_px"][0] : v["window_px"][2]],
                        rg.luminance(t)[v["window_px"][1] : v["window_px"][3], v["window_px"][0] : v["window_px"][2]]), 3)
            for v in res.items
            if "window_px" in v
        ]
        res.after[mode] = {
            "repaired_fraction": round(float((m > 0.5).mean()), 4),
            "remaining_unexpected": len([u for u in remaining if not u["large"]]),
            "item_ncc_min": min(fidelity) if fidelity else None,
            "shading": shading_change(P, out_panel, keep),
        }
    return res, layers


def clean_background(photo: np.ndarray, quads: list[np.ndarray], band: float = 0.003) -> tuple[np.ndarray, np.ndarray, dict]:
    """Remove thin bright overlays (watermarks, pseudo logos) from the backdrop.

    Only marks narrower than a stroke opening, clearly brighter than the local backdrop and
    large enough not to be texture. The package (its faces, the lid above and the floor contact
    below) is never touched; a mark found beside it is followed up to its outline."""
    h, w = photo.shape[:2]
    f = max(1, round(max(h, w) / 1200))
    lum = rg.luminance(_down(photo, max(h, w) // f))
    bg = ndimage.gaussian_filter(ndimage.grey_opening(lum, size=OVERLAY_OPEN), 2)
    bright = (lum - bg) > OVERLAY_BRIGHT
    from PIL import Image, ImageDraw

    keep_out = Image.new("L", (lum.shape[1], lum.shape[0]), 0)
    d = ImageDraw.Draw(keep_out)
    pts = np.concatenate(quads) / f
    hull = pts[np.argsort(np.arctan2(pts[:, 1] - pts[:, 1].mean(), pts[:, 0] - pts[:, 0].mean()))]
    d.polygon([tuple(p) for p in hull], fill=255)
    # The lid above and the floor contact below (flap edges, contact shadow) belong to the
    # package's form: never cleaned.
    dy = PACKAGE_ZONE * lum.shape[0]
    for q in quads:
        q = np.asarray(q, float) / f
        tl, tr, br, bl = q
        d.polygon([tuple(tl), tuple(tr), (tr[0], tr[1] - dy), (tl[0], tl[1] - dy)], fill=255)
        d.polygon([tuple(bl), tuple(br), (br[0], br[1] + dy), (bl[0], bl[1] + dy)], fill=255)
    package = np.asarray(keep_out) > 0
    near = ndimage.binary_dilation(package, iterations=max(1, round(band * max(lum.shape))))
    m = ndimage.binary_opening(bright & ~near, np.ones((2, 2), bool))
    lab, _ = ndimage.label(ndimage.binary_dilation(m, iterations=3))
    sizes = ndimage.sum(m, lab, range(1, lab.max() + 1))
    m = np.isin(lab, np.nonzero(sizes >= OVERLAY_MIN_AREA)[0] + 1) & ~near
    # A confident mark is followed into the band, up to the package outline: an overlay that
    # crosses the package does not stop short of it.
    m = ndimage.binary_propagation(m, mask=ndimage.binary_dilation(bright, iterations=1) & ~package)
    m = ndimage.binary_dilation(m, iterations=2) & ~package
    soft = _up(np.clip(ndimage.gaussian_filter(m.astype(np.float32), 1.0) * 2, 0, 1), (h, w))
    # The backdrop under a mark: its surroundings spread in (not an opening, which reads darker).
    lo = _down(photo, max(h, w) // f)
    keep = (~ndimage.binary_dilation(m, iterations=2) & ~package).astype(np.float32)
    fill = _up(np.stack([_nconv(lo[..., k], keep, 4.0) for k in range(3)], -1), (h, w))
    out = photo + soft[..., None] * (fill - photo)
    return out, soft, {"removed_fraction": round(float((soft > 0.5).mean()), 5), "components": int(lab.max())}
