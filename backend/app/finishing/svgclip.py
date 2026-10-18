"""Clipping inside an outlined Figma SVG, which MuPDF's SVG reader ignores.

Figma exports a frame that clips its content, and a mask layer, as ``clip-path`` / ``mask`` on a
group. MuPDF draws such a group unclipped, so a finish on a masked shape would cover the hidden
part too. ``pieces`` splits the SVG into the unclipped rest and one SVG per clipped group, each
with the box of its clip in the SVG's own coordinates; the caller draws each piece clipped to
that box (``masks.place_svg``). A clip made of one unrotated, square-cornered rectangle (Figma's
usual frame clip) is exact; any other clip shape is approximated by its box and reported.
"""

from __future__ import annotations

import copy
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from app.figma.layers import parse_svg_path

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG)
ET.register_namespace("xlink", XLINK)

# Containers whose children are never drawn directly.
_DEFS = {"defs", "clipPath", "mask", "pattern", "symbol", "linearGradient", "radialGradient"}
_URL = re.compile(r"url\(\s*#([^)\s]+)\s*\)")
_NUM = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")

Box = tuple[float, float, float, float]
Affine = tuple[float, float, float, float, float, float]  # a b c d e f (SVG matrix order)
IDENTITY: Affine = (1, 0, 0, 1, 0, 0)


@dataclass
class Piece:
    svg: str
    clip: Box | None  # in the SVG page's coordinates (pt, origin top-left); None = unclipped
    exact: bool  # False: a clip shape approximated by its box


def _tag(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _mul(m: Affine, n: Affine) -> Affine:
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a * a2 + c * b2,
        b * a2 + d * b2,
        a * c2 + c * d2,
        b * c2 + d * d2,
        a * e2 + c * f2 + e,
        b * e2 + d * f2 + f,
    )


def affine(text: str | None) -> Affine:
    """An SVG ``transform`` attribute as one matrix."""
    m = IDENTITY
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", text or ""):
        v = [float(x) for x in _NUM.findall(args)]
        if name == "matrix" and len(v) == 6:
            t = tuple(v)
        elif name == "translate":
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale":
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate":
            r = math.radians(v[0])
            cos, sin = math.cos(r), math.sin(r)
            t = (cos, sin, -sin, cos, 0, 0)
            if len(v) == 3:
                cx, cy = v[1], v[2]
                t = _mul(_mul((1, 0, 0, 1, cx, cy), t), (1, 0, 0, 1, -cx, -cy))
        elif name == "skewX":
            t = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == "skewY":
            t = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        m = _mul(m, t)  # type: ignore[arg-type]
    return m


def _f(el: ET.Element, k: str, default: float = 0.0) -> float:
    v = _NUM.findall(el.get(k) or "")
    return float(v[0]) if v else default


def _ref(el: ET.Element) -> tuple[str, str] | None:
    """("clip-path" | "mask", id) of a group's clip, from attributes or inline style."""
    style = el.get("style") or ""
    for key in ("clip-path", "mask"):
        val = el.get(key)
        if val is None:
            m = re.search(rf"(?:^|;)\s*{key}\s*:\s*([^;]+)", style)
            val = m.group(1) if m else None
        if val and (m := _URL.search(val)):
            return key, m.group(1)
    return None


def _shape_box(el: ET.Element) -> tuple[list[tuple[float, float]], bool]:
    """Corner points of one clip child (its own coordinates) and whether a box is exact."""
    t = _tag(el)
    if t == "rect":
        x, y, w, h = _f(el, "x"), _f(el, "y"), _f(el, "width"), _f(el, "height")
        exact = _f(el, "rx") == 0 and _f(el, "ry") == 0
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], exact
    if t in ("circle", "ellipse"):
        cx, cy = _f(el, "cx"), _f(el, "cy")
        rx = _f(el, "r") if t == "circle" else _f(el, "rx")
        ry = _f(el, "r") if t == "circle" else _f(el, "ry")
        return [(cx - rx, cy - ry), (cx + rx, cy + ry)], False
    if t == "path":
        pts = [p for pl in parse_svg_path(el.get("d") or "") for p in pl]
        return pts, False
    if t in ("polygon", "polyline"):
        v = [float(x) for x in _NUM.findall(el.get("points") or "")]
        return list(zip(v[::2], v[1::2], strict=False)), False
    return [], False


def _clip_box(defn: ET.Element, m: Affine) -> tuple[Box | None, bool]:
    """Box (under ``m``) of a clipPath / mask definition, and whether it is exactly a box."""
    pts: list[tuple[float, float]] = []
    shapes = 0
    exact = True
    for el in defn.iter():
        if el is defn or _tag(el) in ("g", "defs"):
            continue
        local, ok = _shape_box(el)
        if not local:
            continue
        shapes += 1
        mm = _mul(m, affine(el.get("transform")))
        exact &= ok and abs(mm[1]) < 1e-9 and abs(mm[2]) < 1e-9
        a, b, c, d, e, f = mm
        pts += [(a * x + c * y + e, b * x + d * y + f) for x, y in local]
    if _tag(defn) == "mask" and defn.get("width") and defn.get("height"):
        # The mask's own region bounds what it can show.
        x, y = _f(defn, "x"), _f(defn, "y")
        region = [(x, y), (x + _f(defn, "width"), y + _f(defn, "height"))]
        a, b, c, d, e, f = m
        rpts = [(a * px + c * py + e, b * px + d * py + f) for px, py in region]
        rbox = (min(p[0] for p in rpts), min(p[1] for p in rpts))
        rbox2 = (max(p[0] for p in rpts), max(p[1] for p in rpts))
    else:
        rbox = rbox2 = None
    if not pts:
        return (0.0, 0.0, 0.0, 0.0), True  # an empty clip shows nothing
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    box = (min(xs), min(ys), max(xs), max(ys))
    if rbox is not None and rbox2 is not None:
        box = (
            max(box[0], rbox[0]),
            max(box[1], rbox[1]),
            min(box[2], rbox2[0]),
            min(box[3], rbox2[1]),
        )
    return box, exact and shapes == 1


def _intersect(a: Box | None, b: Box | None) -> Box | None:
    if a is None:
        return b
    if b is None:
        return a
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def _clipped(root: ET.Element) -> list[list[int]]:
    """Index paths of the outermost elements that carry a clip-path or mask."""
    found: list[list[int]] = []

    def walk(el: ET.Element, path: list[int]) -> None:
        for i, child in enumerate(list(el)):
            if _tag(child) in _DEFS:
                continue
            if _ref(child):
                found.append(path + [i])
            else:
                walk(child, path + [i])

    walk(root, [])
    return found


def _strip_ref(el: ET.Element) -> None:
    el.attrib.pop("clip-path", None)
    el.attrib.pop("mask", None)
    if style := el.get("style"):
        el.set("style", re.sub(r"(?:^|;)\s*(clip-path|mask)\s*:[^;]*", "", style))


def _view(root: ET.Element) -> Affine:
    """SVG user units (viewBox) -> the converted page's pt."""
    w, h = _f(root, "width", 0), _f(root, "height", 0)
    vb = [float(x) for x in _NUM.findall(root.get("viewBox") or "")]
    if len(vb) != 4 or not w or not h or not vb[2] or not vb[3]:
        return IDENTITY
    sx, sy = w / vb[2], h / vb[3]
    return (sx, 0, 0, sy, -vb[0] * sx, -vb[1] * sy)


def pieces(svg: str) -> list[Piece]:
    """The SVG as pieces to draw, each clipped to its box (see the module docstring)."""
    if "clip-path" not in svg and "mask" not in svg:
        return [Piece(svg, None, True)]
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return [Piece(svg, None, True)]
    defs = {el.get("id"): el for el in root.iter() if el.get("id")}
    out: list[Piece] = []

    def split(doc: ET.Element, base: Box | None, exact: bool) -> None:
        paths = _clipped(doc)
        if not paths:
            out.append(Piece(ET.tostring(doc, encoding="unicode"), base, exact))
            return
        rest = copy.deepcopy(doc)
        for p in sorted(paths, reverse=True):  # later siblings first: indices stay valid
            parent = rest
            for i in p[:-1]:
                parent = list(parent)[i]
            parent.remove(list(parent)[p[-1]])
        out.append(Piece(ET.tostring(rest, encoding="unicode"), base, exact))
        for p in paths:
            piece = copy.deepcopy(doc)
            el, m = piece, _view(piece)
            for i in p:
                keep = list(el)[i]
                for child in list(el):
                    if child is not keep and _tag(child) not in _DEFS:
                        el.remove(child)
                el = keep
                m = _mul(m, affine(el.get("transform")))
            ref = _ref(el)
            _strip_ref(el)
            defn = defs.get(ref[1]) if ref else None
            if defn is None:
                box, ok = None, False  # a dangling reference: drawn unclipped, reported
            else:
                box, ok = _clip_box(defn, m)
            split(piece, _intersect(base, box), exact and ok)

    split(root, None, True)
    return out
