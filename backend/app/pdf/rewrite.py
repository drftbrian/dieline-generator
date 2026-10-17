"""Produce an artwork-only *copy* of the PDF for rendering.

The original file is never modified. In the copy, painting operators of non-printing paths
(cut, crease, annotation, finish separations) are replaced by ``n`` (end path, paint nothing),
and everything inside non-printing layers is dropped. All other operators are kept
byte-for-byte, so the printed artwork renders exactly as authored.
"""

from __future__ import annotations

import io

import pikepdf
from pikepdf import Name, Operator

from app.pdf.content import PAINT_OPS, TEXT_SHOW, ocg_name


def artwork_only_pdf(
    source: bytes, page_index: int, hidden_refs: set[str], hidden_layers: set[str]
) -> bytes:
    pdf = pikepdf.open(io.BytesIO(source))
    page = pdf.pages[page_index]
    _rewrite(pdf, page.obj, "page", page.obj.get("/Resources"), hidden_refs, hidden_layers, set())
    # Keep only the requested page so downstream renderers can use index 0.
    for i in reversed(range(len(pdf.pages))):
        if i != page_index:
            del pdf.pages[i]
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def _rewrite(pdf, owner, key, resources, hidden_refs, hidden_layers, seen) -> None:
    if key in seen:
        return
    seen.add(key)
    try:
        ops = pikepdf.parse_content_stream(owner)
    except pikepdf.PdfError:
        return

    out = []
    stack: list[bool] = []  # per marked-content frame: is it a hidden layer?
    changed = False
    for idx, item in enumerate(ops):
        hidden_scope = any(stack)
        if isinstance(item, pikepdf.ContentStreamInlineImage):
            if hidden_scope:
                changed = True
                continue
            out.append(item)
            continue
        op = str(item.operator)
        args = item.operands
        if op in ("BDC", "BMC"):
            hide = False
            if op == "BDC" and len(args) == 2 and str(args[0]) == "/OC":
                prop = args[1]
                if isinstance(prop, Name):
                    try:
                        prop = resources.Properties[str(prop)]
                    except Exception:  # noqa: BLE001
                        prop = None
                hide = prop is not None and any(n in hidden_layers for n in ocg_name(prop))
            stack.append(hide)
        elif op == "EMC" and stack:
            stack.pop()

        if op in PAINT_OPS and (hidden_scope or f"{key}#{idx}" in hidden_refs):
            out.append(pikepdf.ContentStreamInstruction([], Operator("n")))
            changed = True
            continue
        if hidden_scope and (op in TEXT_SHOW or op in ("Do", "sh")):
            changed = True
            if op == "'":
                out.append(pikepdf.ContentStreamInstruction([], Operator("T*")))
            elif op == '"' and len(args) == 3:
                out.append(pikepdf.ContentStreamInstruction([args[0]], Operator("Tw")))
                out.append(pikepdf.ContentStreamInstruction([args[1]], Operator("Tc")))
                out.append(pikepdf.ContentStreamInstruction([], Operator("T*")))
            continue
        if op == "Do" and args:
            try:
                xobj = resources.XObject[str(args[0])]
            except Exception:  # noqa: BLE001
                xobj = None
            if xobj is not None and xobj.get("/Subtype") == Name.Form:
                if "/OC" in xobj and any(n in hidden_layers for n in ocg_name(xobj.OC)):
                    changed = True
                    continue
                g = xobj.objgen
                _rewrite(
                    pdf,
                    xobj,
                    f"xobj:{g[0]}:{g[1]}",
                    xobj.get("/Resources", resources),
                    hidden_refs,
                    hidden_layers,
                    seen,
                )
        out.append(item)

    if not changed:
        return
    data = pikepdf.unparse_content_stream(out)
    if key == "page":
        owner.Contents = pdf.make_stream(data)
    else:
        owner.write(data)
