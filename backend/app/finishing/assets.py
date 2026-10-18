"""A project's selectable assets: from the Figma node tree (exact), or from the PDF's own
objects for PDF-only projects (approximate masks where objects overlap).

Stored next to the project: ``figma_assets.json`` (the tree, written at import or backfilled
for the imported file version), ``asset_svg/<node>.svg`` (outlined vector per node, fetched
on demand and cached; immutable for a file version) and ``figma_assets.version`` (the file
version both were made from: a mismatch drops them, see ``_check_version``).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.figma import assets as figma_assets
from app.figma import client as figma
from app.pdf.measure import parse_label
from app.render.layers import package_bbox
from app.spec.models import Specification
from app.storage import repo

TREE_FILE = "figma_assets.json"
VERSION_FILE = "figma_assets.version"  # the Figma file version the tree and outlines are from


def _project(pid: str) -> dict:
    return repo.project_or_404(pid)


def figma_link(project: dict) -> tuple[figma.FigmaLink, str | None] | None:
    meta = project.get("figma_json")
    if not meta:
        return None
    return figma.FigmaLink(meta["file_key"], meta["node_id"], meta["url"]), meta.get("version")


def _source_version(pid: str) -> str:
    """The Figma file version this project's print and geometry come from ("" if unknown)."""
    link = figma_link(_project(pid))
    return (link[1] or "") if link else ""


def _check_version(pid: str) -> None:
    """Drop the stored tree and outlines when they were made from another file version than
    the project's (``VERSION_FILE``). A project's source is immutable, so this only fires if
    its files were replaced; old projects without the stamp adopt the current version."""
    d = repo.project_dir(pid)
    stamp = d / VERSION_FILE
    current = _source_version(pid)
    if stamp.exists() and stamp.read_text() != current:
        (d / TREE_FILE).unlink(missing_ok=True)
        for f in (d / "asset_svg").glob("*.svg") if (d / "asset_svg").exists() else []:
            f.unlink()
    if not stamp.exists() or stamp.read_text() != current:
        stamp.write_text(current)


def save_tree(pid: str, frame_doc: dict) -> list[dict]:
    tree = figma_assets.asset_tree(frame_doc)
    d = repo.project_dir(pid)
    (d / TREE_FILE).write_text(json.dumps(tree, ensure_ascii=False))
    (d / VERSION_FILE).write_text(_source_version(pid))
    return tree


def figma_tree(pid: str) -> list[dict] | None:
    """The Figma asset tree, backfilled from the imported file version if missing."""
    path = repo.project_dir(pid) / TREE_FILE
    link = figma_link(_project(pid))
    if link is not None:
        _check_version(pid)
    if path.exists():
        return json.loads(path.read_text())
    if link is None:
        return None
    frame = figma.fetch_frame(link[0], version=link[1])
    return save_tree(pid, frame.document)


def geometry_stamp(pid: str) -> tuple:
    """Changes whenever the stored asset geometry (tree or any outline) changes: part of the
    finishing caches' keys."""
    d = repo.project_dir(pid)
    files = [d / TREE_FILE, d / VERSION_FILE]
    svg_dir = d / "asset_svg"
    if svg_dir.exists():
        files += sorted(svg_dir.glob("*.svg"))
    out = []
    for f in files:
        try:
            st = f.stat()
        except FileNotFoundError:
            continue
        out.append((f.name, st.st_mtime_ns, st.st_size))
    return tuple(out)


def _panel_of(spec: Specification, bbox: list[float]) -> str | None:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    for p in spec.panels:
        x0, y0, x1, y1 = p.bbox
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            return p.name or p.id
    return None


def pdf_tree(spec: Specification) -> list[dict]:
    """PDF-only projects: the extracted art objects (text runs and vector groups)."""
    out = []
    for o in spec.objects:
        out.append(
            {
                "id": f"pdf:{o.id}",
                "parent": None,
                "children": [],
                "name": o.label,
                "type": "TEXT" if o.kind == "text" else "VECTOR",
                "kind": "text"
                if o.kind == "text"
                else ("image" if o.kind == "image" else "vector"),
                "depth": 1,
                "bbox": list(o.bbox),
                "clip": None,
                "opacity": 1.0,
                "technical": False,
                "selectable": True,
                "color": o.color,
                "text": o.label if o.kind == "text" else None,
            }
        )
    return out


def project_assets(pid: str, spec: Specification) -> tuple[str, list[dict]]:
    """("figma" | "pdf", assets with ``panel`` and ``exact``).

    Beyond the tree's own rules, an asset is not selectable when it is a dimension label
    (e.g. "100mm") or lies entirely off the board."""
    tree = figma_tree(pid)
    source = "figma" if tree is not None else "pdf"
    assets = tree if tree is not None else pdf_tree(spec)
    bx0, by0, bx1, by1 = package_bbox(spec)
    for a in assets:
        a["panel"] = _panel_of(spec, a["bbox"])
        a["exact"] = source == "figma"
        x0, y0, x1, y1 = a["bbox"]
        off_board = x1 <= bx0 or x0 >= bx1 or y1 <= by0 or y0 >= by1
        dimension = a["kind"] == "text" and bool(parse_label(a.get("text") or "", a["bbox"]))
        if off_board or dimension:
            a["selectable"] = False
            a["technical"] = a["technical"] or dimension
    return source, assets


def svg_path(pid: str, node_id: str) -> Path:
    d = repo.project_dir(pid) / "asset_svg"
    d.mkdir(exist_ok=True)
    return d / f"{node_id.replace(':', '_').replace(';', '_')}.svg"


def node_svgs(pid: str, ids: list[str]) -> dict[str, str]:
    """Outlined SVG per Figma node, cached on disk (fetched in one batch when missing)."""
    if figma_link(_project(pid)) is not None:
        _check_version(pid)
    out, missing = {}, []
    for nid in ids:
        p = svg_path(pid, nid)
        if p.exists():
            out[nid] = p.read_text()
        else:
            missing.append(nid)
    if missing:
        link = figma_link(_project(pid))
        if link is None:
            return out
        fetched = figma_assets.export_svgs(link[0], missing, link[1])
        for nid, svg in fetched.items():
            svg_path(pid, nid).write_text(svg)
            out[nid] = svg
    return out
