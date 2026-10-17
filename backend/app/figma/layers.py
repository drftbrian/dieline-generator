"""Figma layer names -> classification evidence for PDF paths.

Figma's PDF export drops layer names, but the REST node tree keeps them together with each
layer's vector outline (``geometry=paths``). Layers whose own name or an ancestor's name
matches ``rules.RULES`` ("redline", "칼선", "fold", "치수"...) are converted to outlines in
page coordinates; a PDF path that lies on such an outline inherits the layer name, exactly
like a named layer inside an Illustrator PDF.
"""

from __future__ import annotations

import re

import numpy as np
from scipy import ndimage

from app.pdf import rules
from app.pdf.content import PaintedPath
from app.pdf.geometry import Polyline, Raster, flatten, sample_along

GEOMETRIC = {
    "VECTOR",
    "LINE",
    "RECTANGLE",
    "ELLIPSE",
    "POLYGON",
    "STAR",
    "BOOLEAN_OPERATION",
    "REGULAR_POLYGON",
}

_TOKEN = re.compile(r"[MLHVCQZmlhvcqz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")


def parse_svg_path(d: str, steps: int = 8) -> list[Polyline]:
    """Figma geometry paths (M/L/H/V/C/Q/Z, absolute or relative) -> polylines."""
    toks = _TOKEN.findall(d)
    out: list[Polyline] = []
    cur: Polyline = []
    x = y = 0.0
    sx = sy = 0.0
    cmd = ""
    i = 0

    def num() -> float:
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
            if cmd in "Zz":
                if cur:
                    cur.append((sx, sy))
                    out.append(cur)
                cur = []
                x, y = sx, sy
                continue
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if c == "M":
            if cur:
                out.append(cur)
            x, y = num() + ox, num() + oy
            sx, sy = x, y
            cur = [(x, y)]
            cmd = "l" if rel else "L"  # implicit lineto after moveto
        elif c == "L":
            x, y = num() + ox, num() + oy
            cur.append((x, y))
        elif c == "H":
            x = num() + (x if rel else 0.0)
            cur.append((x, y))
        elif c == "V":
            y = num() + (y if rel else 0.0)
            cur.append((x, y))
        elif c in "CQ":
            n = 3 if c == "C" else 2
            pts = [(num() + ox, num() + oy) for _ in range(n)]
            p0 = (x, y)
            for s in range(1, steps + 1):
                t = s / steps
                if n == 3:
                    (x1, y1), (x2, y2), (x3, y3) = pts
                    u = 1 - t
                    cur.append(
                        (
                            u**3 * p0[0] + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
                            u**3 * p0[1] + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3,
                        )
                    )
                else:
                    (x1, y1), (x2, y2) = pts
                    u = 1 - t
                    cur.append(
                        (
                            u * u * p0[0] + 2 * u * t * x1 + t * t * x2,
                            u * u * p0[1] + 2 * u * t * y1 + t * t * y2,
                        )
                    )
            x, y = pts[-1]
        else:
            i += 1  # unsupported command argument; skip
    if cur:
        out.append(cur)
    return [pl for pl in out if len(pl) >= 2]


def place(node: dict, geometry: list[dict] | None, fx: float, fy: float) -> list[Polyline]:
    """Node-local geometry -> page points.

    Applies the node's rotation/scale (``relativeTransform``'s 2x2 part), then anchors the
    result to the node's absolute bounding box. Exact for any rotation, and needs no
    bookkeeping of parent transforms.
    """
    nb = node.get("absoluteBoundingBox")
    if not nb or not geometry:
        return []
    (a, c, _), (b, d, _) = node.get("relativeTransform") or [[1, 0, 0], [0, 1, 0]]
    polys = [
        [(a * x + c * y, b * x + d * y) for x, y in pl]
        for g in geometry
        for pl in parse_svg_path(g.get("path", ""))
    ]
    pts = [q for pl in polys for q in pl]
    if not pts:
        return []
    # Anchor the node's own box (not its geometry: glyphs rarely fill the box) to its
    # absolute bounding box, after the same rotation.
    size = node.get("size")
    if size:
        corners = [(0, 0), (size["x"], 0), (0, size["y"]), (size["x"], size["y"])]
        ref = [(a * x + c * y, b * x + d * y) for x, y in corners]
    else:
        ref = pts
    ox = nb["x"] - fx - min(q[0] for q in ref)
    oy = nb["y"] - fy - min(q[1] for q in ref)
    return [[(round(x + ox, 2), round(y + oy, 2)) for x, y in pl] for pl in polys]


def _colors(node: dict) -> list[list[float]]:
    out = []
    for paint in (node.get("strokes") or []) + (node.get("fills") or []):
        if paint.get("visible", True) and paint.get("type") == "SOLID" and "color" in paint:
            c = paint["color"]
            out.append([round(c["r"], 4), round(c["g"], 4), round(c["b"], 4)])
    return out


def extract_shapes(frame: dict) -> list[dict]:
    """Named technical layers inside the frame, as outlines in PDF page points."""
    box = frame.get("absoluteBoundingBox") or {"x": 0, "y": 0}
    fx, fy = box["x"], box["y"]
    shapes: list[dict] = []

    def walk(node: dict, inherited: tuple[str, str] | None) -> None:
        if node.get("visible") is False:
            return
        name = node.get("name", "")
        cls = rules.match(name)
        here = (name, cls) if cls else inherited
        if node.get("type") in GEOMETRIC and here:
            nb = node.get("absoluteBoundingBox")
            if nb:
                ox, oy = nb["x"] - fx, nb["y"] - fy
                has_stroke = (
                    any(p.get("visible", True) for p in node.get("strokes") or [])
                    and (node.get("strokeWeight") or 0) > 0
                )
                geo = node.get("strokeGeometry") if has_stroke else node.get("fillGeometry")
                polys = place(node, geo, fx, fy)
                shapes.append(
                    {
                        "layer": here[0],
                        "cls": here[1],
                        "type": node["type"],
                        "polygons": polys,
                        "bbox": [ox, oy, ox + nb["width"], oy + nb["height"]],
                        "colors": _colors(node),
                        "approx": not polys,
                    }
                )
        for child in node.get("children") or []:
            walk(child, here)

    for child in frame.get("children") or []:
        walk(
            child,
            (frame.get("name", ""), rules.match(frame.get("name", "")))
            if rules.match(frame.get("name", ""))
            else None,
        )
    return shapes


def apply_design_layers(
    paths: list[PaintedPath], shapes: list[dict], page_w: float, page_h: float
) -> int:
    """Tag PDF paths that lie on a named Figma layer. Returns how many were tagged."""
    if not shapes:
        return 0
    scale = min(2.0, 2400 / max(page_w, page_h))
    r = Raster(page_w, page_h, scale)
    masks: dict[str, np.ndarray] = {}
    for s in shapes:
        if s["approx"]:
            continue
        m = r.fill(s["polygons"]) | r.lines(s["polygons"], width_px=2)
        masks[s["layer"]] = masks.get(s["layer"], np.zeros_like(m)) | m
    grow = max(1, round(2.0 * scale))  # 2pt tolerance for export rounding
    masks = {k: ndimage.binary_dilation(m, iterations=grow) for k, m in masks.items()}

    tagged = 0
    for p in paths:
        pts = [r.px(q) for sp in p.subpaths for q in sample_along(flatten(sp), 2.0)]
        if not pts:
            continue
        best, best_frac = None, 0.0
        for layer, m in masks.items():
            hit = sum(
                1 for x, y in pts if 0 <= int(y) < r.h and 0 <= int(x) < r.w and m[int(y), int(x)]
            )
            frac = hit / len(pts)
            if frac > best_frac:
                best, best_frac = layer, frac
        if best is None or best_frac < 0.8:
            best = _approx_match(p, shapes)
        if best:
            p.design_layers = [best]
            tagged += 1
    return tagged


def _approx_match(p: PaintedPath, shapes: list[dict]) -> str | None:
    """Rotated layers (no outline): same color and inside the layer's box."""
    rgb = p.stroke_rgb if p.stroke else p.fill_rgb
    if rgb is None:
        return None
    x0, y0, x1, y1 = p.bbox
    for s in shapes:
        if not s["approx"]:
            continue
        bx0, by0, bx1, by1 = s["bbox"]
        inside = x0 >= bx0 - 2 and y0 >= by0 - 2 and x1 <= bx1 + 2 and y1 <= by1 + 2
        if inside and any(
            max(abs(a - b) for a, b in zip(rgb, c, strict=False)) < 0.06 for c in s["colors"]
        ):
            return s["layer"]
    return None


def summarize(shapes: list[dict]) -> list[dict]:
    """Layer name -> class and count, for display."""
    out: dict[str, dict] = {}
    for s in shapes:
        e = out.setdefault(s["layer"], {"name": s["layer"], "cls": s["cls"], "shapes": 0})
        e["shapes"] += 1
    return list(out.values())


# ---- content: texts, graphics and straight lines -----------------------------------------


def _hex(c: dict | None) -> str | None:
    if not c:
        return None
    return "#" + "".join(f"{max(0, min(255, round(c[k] * 255))):02X}" for k in ("r", "g", "b"))


def _outline(node: dict, fx: float, fy: float) -> list[Polyline]:
    """Node outline in page points, including descendants."""
    out: list[Polyline] = []
    if node.get("type") != "TEXT":
        out += place(node, node.get("fillGeometry"), fx, fy)
    for child in node.get("children") or []:
        if child.get("visible") is not False:
            out += _outline(child, fx, fy)
    return out


GENERIC_NAME = re.compile(
    r"^(Vector|Union|Group|Frame|Subtract|Rectangle|Ellipse|Line|Path)( \d+)?$", re.I
)


def extract_content(frame: dict) -> dict:
    """Texts (exact strings + styles), top-level graphics, and straight lines of the frame."""
    box = frame.get("absoluteBoundingBox") or {"x": 0, "y": 0, "width": 1, "height": 1}
    fx, fy = box["x"], box["y"]
    frame_area = box["width"] * box["height"]
    texts: list[dict] = []
    graphics: list[dict] = []
    segments: list[dict] = []

    def bbox_of(n: dict) -> list[float] | None:
        b = n.get("absoluteBoundingBox")
        if not b:
            return None
        return [
            round(b["x"] - fx, 2),
            round(b["y"] - fy, 2),
            round(b["x"] - fx + b["width"], 2),
            round(b["y"] - fy + b["height"], 2),
        ]

    def walk(node: dict, depth: int, technical: bool) -> None:
        if node.get("visible") is False:
            return
        technical = technical or bool(rules.match(node.get("name", "")))
        kind = node.get("type")
        bb = bbox_of(node)
        if kind == "TEXT" and bb:
            style = node.get("style") or {}
            fills = [
                p for p in node.get("fills") or [] if p.get("visible", True) and p.get("color")
            ]
            texts.append(
                {
                    "id": node["id"],
                    "text": node.get("characters", ""),
                    "font": style.get("fontFamily"),
                    "weight": style.get("fontWeight"),
                    "size": style.get("fontSize"),
                    "color": _hex(fills[0]["color"]) if fills else None,
                    "bbox": bb,
                    "technical": technical,
                }
            )
            return
        if kind in ("VECTOR", "LINE") and bb and (bb[2] - bb[0] < 0.5 or bb[3] - bb[1] < 0.5):
            segments.append(
                {
                    "a": [bb[0], bb[1]],
                    "b": [bb[2], bb[3]],
                    "dashed": bool(node.get("strokeDashes")),
                    "technical": technical,
                }
            )
        if (
            depth == 1
            and not technical
            and kind
            in (
                "VECTOR",
                "BOOLEAN_OPERATION",
                "GROUP",
                "INSTANCE",
                "COMPONENT",
                "ELLIPSE",
                "STAR",
                "POLYGON",
            )
            and bb
            # Straight lines are rules/dimension marks, not selectable graphics.
            and min(bb[2] - bb[0], bb[3] - bb[1]) >= 0.5
            and (bb[2] - bb[0]) * (bb[3] - bb[1]) < 0.25 * frame_area
        ):
            fills = [
                p for p in node.get("fills") or [] if p.get("visible", True) and p.get("color")
            ]
            graphics.append(
                {
                    "id": node["id"],
                    "name": node.get("name", ""),
                    "generic_name": bool(GENERIC_NAME.match(node.get("name", ""))),
                    "bbox": bb,
                    "color": _hex(fills[0]["color"]) if fills else None,
                    "polygons": _outline(node, fx, fy),
                }
            )
        for child in node.get("children") or []:
            walk(child, depth + 1, technical)

    for child in frame.get("children") or []:
        walk(child, 1, False)
    return {"texts": texts, "graphics": graphics, "segments": segments}
