"""What the image model is told about our packaging: the Figma data, as text.

The image model gets the print as an image (exact pixels); this brief repeats what Figma knows
about it in words: sizes, panels, every text string verbatim (per panel and per box face),
fonts, logos and colours. It reads the Figma content stored at import (fetched once for older
projects); projects made from a PDF fall back to the PDF's own text lines.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from app.pdf.measure import parse_label
from app.render import carton3d
from app.render.layers import package_bbox
from app.services import pipeline
from app.spec.models import Specification
from app.storage import repo

FACE_NAMES = {
    "front": "front panel",
    "back": "back panel",
    "left": "left side panel",
    "right": "right side panel",
    "top": "top lid",
    "bottom": "bottom",
}
NONE = "(none)"


@dataclass
class FigmaBrief:
    figma_url: str
    dims: str
    panels: str
    texts_by_panel: str
    texts_by_face: str
    fonts: str
    logos: str
    colours: str


def _centre_in(b, box) -> bool:
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def _quote(t: str) -> str:
    # Verbatim, with line breaks shown as " / " so one text stays on one line of the brief.
    return '"' + " / ".join(x.strip() for x in t.strip().splitlines() if x.strip()) + '"'


def _pdf_texts(pid: str, spec: Specification) -> list[dict]:
    """Text lines of a PDF-only project (no Figma content), in the same shape as Figma's."""
    try:
        doc = pymupdf.open(stream=repo.read_source(pid), filetype="pdf")
    except Exception:  # noqa: BLE001 - the brief is still useful without texts
        return []
    out = []
    for block in doc[spec.page.index].get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            out.append(
                {
                    "text": "".join(s["text"] for s in spans).strip(),
                    "bbox": [round(v, 2) for v in line["bbox"]],
                    "font": spans[0]["font"],
                    "weight": None,
                    "size": round(spans[0]["size"], 1),
                    "color": f"#{spans[0]['color']:06X}",
                    "technical": False,
                }
            )
    return out


def _texts(pid: str, spec: Specification, content: dict | None) -> list[dict]:
    """Printed texts on the sheet: technical layers and dimension labels left out."""
    texts = (content or {}).get("texts") if content else None
    if texts is None:
        texts = _pdf_texts(pid, spec)
    sheet = package_bbox(spec)
    return [
        t
        for t in texts
        if not t.get("technical")
        and (t.get("text") or "").strip()
        and t.get("bbox")
        and _centre_in(t["bbox"], sheet)
        and not parse_label(t["text"], tuple(t["bbox"]))
    ]


def _by_region(texts: list[dict], regions: list[tuple[str, tuple]], rest: str) -> str:
    lines, used = [], set()
    for name, box in regions:
        mine = [i for i, t in enumerate(texts) if i not in used and _centre_in(t["bbox"], box)]
        used.update(mine)
        if mine:
            lines.append(f"- {name}: " + "; ".join(_quote(texts[i]["text"]) for i in mine))
    left = [t for i, t in enumerate(texts) if i not in used]
    if left:
        lines.append(f"- {rest}: " + "; ".join(_quote(t["text"]) for t in left))
    return "\n".join(lines) or NONE


def _fonts(texts: list[dict], spec: Specification) -> str:
    fonts: dict[str, set] = {}
    for t in texts:
        if not t.get("font"):
            continue
        name = f"{t['font']} {t['weight']}" if t.get("weight") else t["font"]
        fonts.setdefault(name, set())
        if t.get("size"):
            k = spec.scale.mm_per_pt / (25.4 / 72)  # design units -> printed points
            fonts[name].add(round(t["size"] * k, 1))
    if not fonts:
        return ", ".join(spec.counts.fonts) or NONE
    return "; ".join(
        f"{n} ({', '.join(f'{s:g}' for s in sorted(sizes))} pt)" if sizes else n
        for n, sizes in sorted(fonts.items())
    )


def figma_brief(pid: str, spec: Specification) -> FigmaBrief:
    project = repo.project_or_404(pid)
    content = pipeline.figma_content(pid, backfill=True)
    k = spec.scale.mm_per_pt
    texts = _texts(pid, spec, content)

    x0, y0, x1, y1 = package_bbox(spec)
    dims = f"flat sheet {(x1 - x0) * k:.1f} x {(y1 - y0) * k:.1f} mm"
    if spec.box:
        b = spec.box
        dims = (
            f"folded box {b.width_mm:g} mm wide x {b.depth_mm:g} mm deep x "
            f"{b.height_mm:g} mm tall; " + dims
        )

    panels = spec.panels
    panel_list = "; ".join(f"{p.name} {p.width_mm:g} x {p.height_mm:g} mm" for p in panels) or NONE
    faces = carton3d.map_faces(panels, spec.box) if panels else {}

    graphics = [g for g in (content or {}).get("graphics", []) if g.get("bbox")]
    named = [g for g in graphics if not g.get("generic_name")]
    logos = [
        f"{g['name']} ({(g['bbox'][2] - g['bbox'][0]) * k:.0f} x "
        f"{(g['bbox'][3] - g['bbox'][1]) * k:.0f} mm)"
        for g in named
    ]
    if len(graphics) > len(named):
        logos.append(f"{len(graphics) - len(named)} unnamed vector graphics")
    if not content:
        n = sum(1 for o in spec.objects if o.kind in ("vector", "image"))
        logos = [f"{n} vector/image graphics (exactly as printed in the image)"] if n else []

    colours = sorted({i["color"] for i in texts + graphics if i.get("color")})
    if not content:
        colours = sorted({o.color for o in spec.objects if o.color} | set(colours))

    return FigmaBrief(
        figma_url=(project.get("figma_json") or {}).get("url") or "(not a Figma import)",
        dims=dims,
        panels=panel_list,
        texts_by_panel=_by_region(
            texts, [(p.name, p.bbox) for p in panels], "across panels / outside the panels"
        ),
        texts_by_face=_by_region(
            texts,
            [(FACE_NAMES[f], box) for f, box in faces.items()],
            "flaps, tabs and other panels",
        ),
        fonts=_fonts(texts, spec),
        logos="; ".join(logos) or NONE,
        colours=", ".join(colours) or NONE,
    )
