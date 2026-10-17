"""Scene light on the package, and its verification.

The package's print always comes from the PDF render. What may change on it is only what a
lit scene would change: broad light and shadow (far larger than any glyph) and the board's
surface detail.
``verify`` proves the print detail survived exactly that and nothing else.
"""

from __future__ import annotations

import numpy as np
from PIL import Image
from scipy import ndimage

LUMA = np.array([0.299, 0.587, 0.114], np.float32)
GAIN_RANGE = (0.55, 1.25)
TILT = 0.0  # the scene's light never tints the print: its colours are the Figma colours
LIGHT_RANGE = (0.92, 1.06)  # exposure-neutral light and shadow across the package
DETAIL_RANGE = (0.9, 1.1)  # zero-mean surface detail (ribs, fibres, folds) around the light
EDGE_RANGE = (0.5, 1.4)  # the cut edge as photographed (board thickness, light on the cut face)


def to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (float 0..1, ...x3) to CIE Lab (D65)."""
    c = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m = np.array(
        [[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]],
        np.float32,
    )
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883], np.float32)
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack(
        [116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1
    )


def delta_e(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """CIE76 colour difference between sRGB colours (float 0..1)."""
    return np.linalg.norm(to_lab(a) - to_lab(b), axis=-1)


def _small(img: np.ndarray, long_edge: int = 512) -> tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    k = min(1.0, long_edge / max(h, w))
    if k == 1.0:
        return img, 1.0
    return ndimage.zoom(img, (k, k) + (1,) * (img.ndim - 2), order=1), k


def _masked_blur(v: np.ndarray, m: np.ndarray, sigma: float) -> np.ndarray:
    num = ndimage.gaussian_filter(v * m, sigma)
    den = ndimage.gaussian_filter(m, sigma)
    return num / np.maximum(den, 1e-4)


def _up(v: np.ndarray, h: int, w: int) -> np.ndarray:
    return np.asarray(Image.fromarray(v.astype(np.float32)).resize((w, h), Image.BILINEAR))


def light_gain(scene: np.ndarray, base: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Per-channel multiplier (HxWx3) carrying the scene's broad light onto the package.

    Both images are blurred far beyond glyph size (2.5% of the long edge) inside the package
    mask, so the model's redrawn or garbled print averages out and only light remains.
    """
    h, w = base.shape[:2]
    s_small, _ = _small(scene)
    b_small, _ = _small(base)
    m_small, _ = _small(mask.astype(np.float32))
    sigma = 0.025 * max(s_small.shape[:2])
    ls = _masked_blur(s_small @ LUMA, m_small, sigma)
    lb = _masked_blur(b_small @ LUMA, m_small, sigma)
    gain = np.clip(ls / np.maximum(lb, 0.02), *GAIN_RANGE)
    out = np.empty((h, w, 3), np.float32)
    g_full = _up(gain, h, w)
    for c in range(3):
        sc = _masked_blur(s_small[..., c], m_small, sigma)
        bc = _masked_blur(b_small[..., c], m_small, sigma)
        tilt = (sc / np.maximum(bc, 0.02)) / np.maximum(gain, 1e-3)
        tilt = np.clip(tilt / max(float(np.median(tilt)), 1e-3), 1 - TILT, 1 + TILT)
        out[..., c] = g_full * _up(tilt, h, w)
    return out


def print_echo(
    gain: np.ndarray, print_rgb: np.ndarray, mask: np.ndarray, max_shift: int = 16
) -> float:
    """How strongly the light/surface map contains a *displaced* copy of our print.

    A model that redrew the text a few pixels off leaves that text in ``photo / print``; once
    multiplied onto our print it reads as a stereo-glasses ghost. Normalised cross-correlation
    of the two high-passes, over offsets up to ``max_shift`` px (the true position excluded).
    """
    g = gain @ LUMA if gain.ndim == 3 else gain
    p = print_rgb @ LUMA if print_rgb.ndim == 3 else print_rgb
    m = ndimage.binary_erosion(mask, iterations=4)
    # Only near our print can a displaced copy of it sit.
    lum = ndimage.gaussian_filter(p, 0.7)
    grad = np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1)) / 8
    m &= ndimage.binary_dilation(grad > 0.012, iterations=max_shift + 2)
    if m.sum() < 1000:
        return 0.0
    a = (g - ndimage.gaussian_filter(g, 2)) * m
    b = (p - ndimage.gaussian_filter(p, 2)) * m
    na, nb = float(np.sqrt((a * a).sum())), float(np.sqrt((b * b).sum()))
    if na < 1e-6 or nb < 1e-6:
        return 0.0
    cc = np.real(np.fft.ifft2(np.fft.fft2(a) * np.conj(np.fft.fft2(b)))) / (na * nb)
    k = max_shift
    win = np.concatenate([cc[-k:], cc[: k + 1]], 0)
    win = np.concatenate([win[:, -k:], win[:, : k + 1]], 1)  # offsets -k..k, centre at [k, k]
    win[k - 1 : k + 2, k - 1 : k + 2] = 0  # the true position (and its rounding) is not an echo
    return float(np.abs(win).max())


def verify(
    final: np.ndarray,
    base: np.ndarray,
    sil: np.ndarray,
    gain: np.ndarray | None = None,
    print_mask: np.ndarray | None = None,
    scene: np.ndarray | None = None,
    colour_regions: list[tuple[np.ndarray, np.ndarray]] | None = None,
) -> dict:
    """Print detail identical; only broad light may differ.

    ``final`` must equal ``base x gain`` up to 8-bit rounding, and ``gain`` must be smooth at
    glyph scale and within the light range, so nothing but light can have changed the print.
    The detail correlation is reported as an independent cross-check (a shifted or redrawn
    print drops it far below 0.98).
    """
    solid = sil >= 0.999
    total = int(solid.sum())
    f = final[..., :3].astype(np.float32) / 255
    b = base[..., :3].astype(np.float32) / 255
    if total == 0:
        return {
            "protected_px": 0,
            "changed_px": 0,
            "changed_ratio": 0.0,
            "match": True,
            "light_applied": False,
            "detail_match": 1.0,
            "min_gain": 1.0,
            "max_gain": 1.0,
        }
    g = gain if gain is not None else np.ones_like(b)
    expected = np.clip(b * g, 0, 1)
    residual = float(np.abs(f - expected).max(axis=-1)[solid].max())
    exact = residual <= 1.5 / 255
    # Light only: no structure at glyph/stroke scale (~0.4% of the image) in the light map.
    lum_g = g @ LUMA
    # Where the print has edges (``print_mask``, default: everywhere), the light/surface map
    # must carry no glyph-scale structure: there it can only be light, never redrawn print.
    where = solid & print_mask if print_mask is not None else solid
    fine = np.abs(lum_g - ndimage.gaussian_filter(lum_g, max(2.0, 0.004 * max(lum_g.shape))))[
        where if where.any() else solid
    ]
    roughness = float(np.percentile(fine, 99.9))
    smooth = roughness < 0.02
    ghost = 0.0
    if scene is not None and print_mask is not None and where.any():
        # Surface mode: the board's texture may cross the print, but the model's own (garbled)
        # print must not leak into the surface map there.
        hp_g = lum_g - ndimage.gaussian_filter(lum_g, 2)
        sl = scene @ LUMA
        hp_s = sl - ndimage.gaussian_filter(sl, 2)
        a, c = hp_g[where], hp_s[where]
        ghost = float(np.corrcoef(a, c)[0, 1]) if a.std() > 1e-6 and c.std() > 1e-6 else 0.0
        smooth = ghost < 0.3
    lo = min(GAIN_RANGE[0], LIGHT_RANGE[0]) * min(DETAIL_RANGE[0], EDGE_RANGE[0]) - 1e-3
    hi = max(GAIN_RANGE[1], LIGHT_RANGE[1]) * max(DETAIL_RANGE[1], EDGE_RANGE[1]) + 1e-3
    in_range = lo <= float(lum_g[solid].min()) and float(lum_g[solid].max()) <= hi
    hp = lambda v: v - ndimage.gaussian_filter(v, 2)  # noqa: E731
    # Compare detail away from the outline, where the filter would also see the background.
    inner = ndimage.binary_erosion(solid, iterations=6)
    inner = inner if inner.sum() > 100 else solid
    hf, he = hp(f @ LUMA)[inner], hp(expected @ LUMA)[inner]
    corr = float(np.corrcoef(hf, he)[0, 1]) if hf.std() > 1e-6 and he.std() > 1e-6 else 1.0
    changed = int(
        (np.abs(final[..., :3].astype(int) - base[..., :3].astype(int)).max(-1)[solid] > 0).sum()
    )
    gl = lum_g[solid]
    # Colour fidelity. Overall: the package against its own print. Per Figma colour: each
    # solid text/graphic colour (its pixels) against the exact Figma value.
    # Compared as areas (~1% of the image): paper grain is texture, not a colour change.
    sig = max(4.0, 0.01 * max(f.shape[:2]))
    area = lambda v: ndimage.gaussian_filter(v, (sig, sig, 0))  # noqa: E731
    inner_c = ndimage.binary_erosion(solid, iterations=8)
    inner_c = inner_c if inner_c.any() else solid
    pick = np.random.default_rng(0).permutation(np.flatnonzero(inner_c))[:200_000]
    flat_f, flat_b = area(f).reshape(-1, 3)[pick], area(b).reshape(-1, 3)[pick]
    overall = float(np.median(delta_e(flat_f, flat_b))) if pick.size else 0.0
    worst = 0.0
    for target, mask in colour_regions or []:
        region = mask & solid
        if region.sum() < 20:
            continue
        seen = np.median(f[region], axis=0)
        worst = max(worst, float(delta_e(seen, np.asarray(target, np.float32))))
    colour_ok = overall <= 3 and worst <= 6
    echo = print_echo(g, b, solid) if gain is not None else 0.0
    return {
        "protected_px": total,
        "changed_px": changed,
        "changed_ratio": round(changed / total, 6),
        # print_echo is reported, not gated: the AI's misplaced text is kept out by the print
        # zone in surface.transfer (garbled text is not a clean shifted copy to correlate with).
        "match": bool(exact and smooth and in_range and corr >= 0.98 and colour_ok),
        "light_applied": bool(np.abs(gl - 1).max() > 0.01),
        "detail_match": round(corr, 4),
        "min_gain": round(float(gl.min()), 3),
        "max_gain": round(float(gl.max()), 3),
        "residual": round(residual * 255, 2),  # in 8-bit levels
        "light_roughness": round(roughness, 4),
        "print_ghost": round(ghost, 3),
        "print_echo": round(echo, 3),
        "colour_delta_e_median": round(overall, 2),
        "colour_delta_e_max": round(worst, 2),
    }
