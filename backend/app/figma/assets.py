"""Selectable design assets of a Figma frame: the visible node tree with stable ids, and exact
per-node vector geometry (outlined SVG export) for finishing masks.

The tree is read from the same file version the project's PDF came from, so coordinates match
the render: frame-relative points (1 Figma px = 1 pt, origin at the frame's top-left).
Technical layers (cut/fold/dimension/guides, see ``pdf.rules``) are kept for completeness but
are never selectable.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.figma import client as figma
from app.pdf import rules

# Node types that can carry printed artwork.
ARTWORK_TYPES = {
    "TEXT",
    "VECTOR",
    "BOOLEAN_OPERATION",
    "GROUP",
    "INSTANCE",
    "COMPONENT",
    "ELLIPSE",
    "STAR",
    "POLYGON",
    "RECTANGLE",
    "REGULAR_POLYGON",
    "FRAME",
}
KIND = {
    "TEXT": "text",
    "GROUP": "group",
    "FRAME": "group",
    "INSTANCE": "group",
    "COMPONENT": "group",
    "BOOLEAN_OPERATION": "vector",
}
MIN_SIZE_PT = 0.5  # thinner than this: a rule or mark, not a selectable shape


def _hex(c: dict | None) -> str | None:
    if not c:
        return None
    return "#{:02X}{:02X}{:02X}".format(*(round(c[k] * 255) for k in ("r", "g", "b")))


def _bbox(node: dict, fx: float, fy: float, key: str = "absoluteBoundingBox") -> list[float] | None:
    b = node.get(key)
    if not b:
        return None
    return [
        round(b["x"] - fx, 3),
        round(b["y"] - fy, 3),
        round(b["x"] - fx + b["width"], 3),
        round(b["y"] - fy + b["height"], 3),
    ]


def _intersect(a: list[float] | None, b: list[float] | None) -> list[float] | None:
    if a is None:
        return b
    if b is None:
        return a
    r = [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]
    return r if r[2] > r[0] and r[3] > r[1] else [r[0], r[1], r[0], r[1]]


def asset_tree(frame: dict) -> list[dict]:
    """Every visible node under the frame, parents before children.

    Each asset: id, parent, children, name, type, kind, depth, bbox (frame-relative pt),
    clip (intersection of clipping ancestors, or None), opacity (product down the tree),
    technical, selectable, and for text: text, font, size, weight, color.
    """
    box = frame.get("absoluteBoundingBox") or {"x": 0, "y": 0, "width": 1, "height": 1}
    fx, fy = box["x"], box["y"]
    out: list[dict] = []
    by_id: dict[str, dict] = {}

    def walk(node, parent, depth, technical, clip, opacity, path="0"):
        if node.get("visible") is False:
            return
        nid = node.get("id") or f"path:{path}"  # Figma always sends ids; fixtures may not
        kind_type = node.get("type", "")
        technical = technical or bool(rules.match(node.get("name", "")))
        bb = _bbox(node, fx, fy)
        alpha = opacity * float(node.get("opacity", 1.0))
        item = None
        if depth >= 1 and bb and kind_type in ARTWORK_TYPES:
            w, h = bb[2] - bb[0], bb[3] - bb[1]
            visible_box = _intersect(clip, bb)
            clipped_away = visible_box is not None and (
                visible_box[2] - visible_box[0] <= 0 or visible_box[3] - visible_box[1] <= 0
            )
            fills = [p for p in node.get("fills") or [] if p.get("visible", True)]
            item = {
                "id": nid,
                "parent": parent,
                "children": [],
                "name": node.get("name", ""),
                "type": kind_type,
                "kind": KIND.get(kind_type, "vector"),
                "depth": depth,
                "bbox": bb,
                "clip": clip,
                "opacity": round(alpha, 3),
                "technical": technical,
                "selectable": bool(
                    not technical
                    and not clipped_away
                    and alpha > 0.01
                    and min(w, h) >= MIN_SIZE_PT
                    # A full-frame background is not a finishing target.
                    and w * h < 0.9 * box["width"] * box["height"]
                ),
            }
            if kind_type == "TEXT":
                style = node.get("style") or {}
                item.update(
                    text=node.get("characters", ""),
                    font=style.get("fontFamily"),
                    size=style.get("fontSize"),
                    weight=style.get("fontWeight"),
                    color=_hex(fills[0].get("color")) if fills else None,
                )
            elif fills and fills[0].get("color"):
                item["color"] = _hex(fills[0]["color"])
            out.append(item)
            by_id[item["id"]] = item
            if parent in by_id:
                by_id[parent]["children"].append(nid)
        if node.get("clipsContent") and bb:
            clip = _intersect(clip, bb)
        if kind_type == "TEXT":
            return  # glyph runs are not separate nodes
        for i, child in enumerate(node.get("children") or []):
            walk(child, nid if item else parent, depth + 1, technical, clip, alpha, f"{path}.{i}")

    for i, child in enumerate(frame.get("children") or []):
        walk(child, None, 1, False, None, 1.0, str(i))
    return out


def _download(url: str) -> str | None:
    """One pre-signed export URL, with a few retries (the CDN resets busy connections).
    None when it still fails: that node is fetched again on the next request."""
    for attempt in range(3):
        try:
            r = httpx.get(url, timeout=figma.TIMEOUT)
            r.raise_for_status()
            return r.text
        except httpx.HTTPError:
            time.sleep(0.5 * (attempt + 1))
    return None


def export_svgs(link: figma.FigmaLink, ids: list[str], version: str | None) -> dict[str, str]:
    """Outlined SVG of each node (text converted to glyph outlines), at its absolute bounds."""
    out: dict[str, str] = {}
    with figma._client() as c:
        for i in range(0, len(ids), 40):
            batch = ids[i : i + 40]
            params = {
                "ids": ",".join(batch),
                "format": "svg",
                "svg_outline_text": "true",
                "svg_include_id": "false",
                "svg_simplify_stroke": "true",
                "use_absolute_bounds": "true",
            }
            if version:
                params["version"] = version
            data = figma._get(c, f"/images/{link.file_key}", params)
            urls = {nid: url for nid, url in (data.get("images") or {}).items() if url}
            with ThreadPoolExecutor(max_workers=4) as pool:  # pre-signed URLs, fetched together
                for nid, svg in zip(urls, pool.map(_download, urls.values()), strict=True):
                    if svg is not None:
                        out[nid] = svg
    return out
