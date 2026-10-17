"""Synthetic folding-carton PDFs with known geometry.

Each variant writes ``<name>.pdf`` plus ``<name>.truth.json``. The truth file lists the expected
class of every painted path in content-stream order, so the analyzer's output can be checked
path by path. These files are test data only and are never shipped with the product.

Run: uv run python tests/fixtures/synthetic/generate.py
"""

import json
import zlib
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name

OUT = Path(__file__).resolve().parent
MM = 72 / 25.4

# Reverse tuck-end carton, mm, origin top-left of the dieline, y down.
T, D = 42.0, 100.0
B = T + D
OUTLINE = [
    (0, T + 4),
    (12, T),
    (72, T),
    (76, T - 18),
    (97, T - 22),
    (102, T),
    (102, T - 30),
    (105, T - 42),
    (159, T - 42),
    (162, T - 30),
    (162, T),
    (167, T - 22),
    (188, T - 18),
    (192, T),
    (192, B),
    (188, B + 18),
    (167, B + 22),
    (162, B),
    (162, B),
    (102, B),
    (102, B),
    (97, B + 22),
    (76, B + 18),
    (72, B),
    (72, B + 30),
    (69, B + 42),
    (15, B + 42),
    (12, B + 30),
    (12, B),
    (0, B - 4),
]
OUTLINE = [p for i, p in enumerate(OUTLINE) if p != OUTLINE[i - 1]]  # drop repeated corners
CREASES = [
    ((12, T), (12, B)),
    ((72, T), (72, B)),
    ((102, T), (102, B)),
    ((162, T), (162, B)),
    ((72, T), (102, T)),
    ((102, T), (162, T)),
    ((162, T), (192, T)),
    ((102, T - 30), (162, T - 30)),
    ((12, B), (72, B)),
    ((72, B), (102, B)),
    ((162, B), (192, B)),
    ((12, B + 30), (72, B + 30)),
]
MARGIN = 24.0
PAGE_W_MM = 192 + 2 * MARGIN
PAGE_H_MM = 184 + 2 * MARGIN


def P(x: float, y: float) -> str:
    """Dieline mm (y down) -> PDF points (y up)."""
    return f"{(x + MARGIN) * MM:.3f} {(PAGE_H_MM - (y + MARGIN)) * MM:.3f}"


def polyline(points, close=False) -> str:
    ops = [f"{P(*points[0])} m"] + [f"{P(*p)} l" for p in points[1:]]
    if close:
        ops.append("h")
    return " ".join(ops)


def rect(x, y, w, h) -> str:
    return polyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], close=True)


class Builder:
    """Collects content operators and the expected class of each painted path.

    A truth entry is one class for the whole path, or a list with one class per subpath
    when a single path holds several lines (e.g. a whole dieline in one shape).
    """

    def __init__(self):
        self.ops: list[str] = []
        self.truth: list[str | list[str]] = []

    def paint(self, path: str, op: str, cls: str | list[str]):
        self.ops.append(f"{path} {op}")
        self.truth.append(cls)

    def raw(self, s: str):
        self.ops.append(s)


def artwork(b: Builder, *, red_trap: bool = True):
    """Printed design. Fills bleed 3mm past the cut so clipping is exercised."""
    b.raw("0.02 0.04 0.08 0 k")  # light lid/flaps
    b.paint(rect(99, T - 45, 66, 45), "f", "artwork")
    b.paint(rect(9, B, 66, 45), "f", "artwork")
    b.paint(rect(69, T - 25, 36, 25), "f", "artwork")
    b.paint(rect(159, T - 25, 36, 25), "f", "artwork")
    b.paint(rect(69, B, 36, 25), "f", "artwork")
    b.paint(rect(159, B, 36, 25), "f", "artwork")
    b.raw("0.86 0.36 0.10 0.02 k")  # deep teal body, drawn over the flap fills
    b.paint(rect(-3, T, 198, D), "f", "artwork")
    # White outlined "logo": three letter-like bars on the front panel.
    b.raw("0 0 0 0 k")
    b.paint(rect(24, T + 30, 8, 26), "f", "artwork")
    b.paint(rect(36, T + 30, 8, 26), "f", "artwork")
    b.paint(rect(48, T + 30, 12, 8), "f", "artwork")
    if red_trap:
        # Red artwork that looks like a dieline: a thin stroke-only line and a filled dot.
        b.raw("0 1 1 0 K 0.6 w")
        b.paint(polyline([(20, T + 70), (64, T + 70)]), "S", "artwork")
        b.raw("0 1 1 0 k")
        b.paint(rect(40, T + 78, 4, 4), "f", "artwork")
    # Text with a real font on the back panel.
    b.raw(f"BT /F1 14 Tf 1 1 1 rg 1 0 0 1 {P(112, T + 50)} Tm (SAMPLE CARTON) Tj ET")
    # Embedded raster image on a side panel.
    b.raw(f"q {22 * MM:.3f} 0 0 {30 * MM:.3f} {P(76, T + 60)} cm /Im1 Do Q")


def annotations(b: Builder):
    """Technical marks outside the carton: dimension line + label."""
    b.raw("0 0 0 1 K 0.3 w")
    b.paint(polyline([(12, B + 50), (72, B + 50)]), "S", "annotation")
    b.raw(f"BT /F1 7 Tf 0 0 0 rg 1 0 0 1 {P(36, B + 49)} Tm (60 mm) Tj ET")


def structure_named(b: Builder):
    b.raw("q /CSDie CS 1 SCN 0.5 w")
    b.paint(polyline(OUTLINE, close=True), "S", "cut")
    b.raw("Q q /CSCrease CS 1 SCN 0.5 w [3 2] 0 d")
    for a, c in CREASES:
        b.paint(polyline([a, c]), "S", "crease")
    b.raw("Q")


def structure_unnamed(b: Builder):
    """Same geometry, plain RGB strokes on the artwork layer: needs geometric inference."""
    b.raw("q 1 0 0 RG 0.5 w")
    for i in range(len(OUTLINE)):  # cut drawn as separate segments, as many exports do
        b.paint(polyline([OUTLINE[i], OUTLINE[(i + 1) % len(OUTLINE)]]), "S", "cut")
    b.raw("Q q 0 0.6 0 RG 0.5 w [3 2] 0 d")
    for a, c in CREASES:
        b.paint(polyline([a, c]), "S", "crease")
    b.raw("Q")


def structure_single_separation(b: Builder):
    """Outline and solid folds all in one spot color "Die" (no crease separation)."""
    b.raw("q /CSDie CS 1 SCN 0.5 w")
    b.paint(polyline(OUTLINE, close=True), "S", "cut")
    for a, c in CREASES:
        b.paint(polyline([a, c]), "S", "crease")
    b.raw("Q")


def structure_unnamed_solid(b: Builder):
    """Outline and folds in the same plain red, all solid: only topology can tell them apart."""
    b.raw("q 1 0 0 RG 0.5 w")
    for i in range(len(OUTLINE)):
        b.paint(polyline([OUTLINE[i], OUTLINE[(i + 1) % len(OUTLINE)]]), "S", "cut")
    for a, c in CREASES:
        b.paint(polyline([a, c]), "S", "crease")
    b.raw("Q")


LINE_MM = 0.32  # ~0.9pt, a typical dieline stroke


def bar(p0, p1, w=LINE_MM) -> str:
    """A line segment as a thin filled rectangle (how Figma exports strokes)."""
    (x0, y0), (x1, y1) = p0, p1
    length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 or 1
    nx, ny = -(y1 - y0) / length * w / 2, (x1 - x0) / length * w / 2
    return polyline(
        [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)], close=True
    )


def structure_outlined(b: Builder):
    """Figma-style export: the whole dieline is ONE filled shape of outlined strokes."""
    segs = [(OUTLINE[i], OUTLINE[(i + 1) % len(OUTLINE)]) for i in range(len(OUTLINE))]
    b.raw("q 0.9 0 0.07 rg")
    b.paint(
        " ".join(bar(a, c) for a, c in segs + CREASES),
        "f",
        ["cut"] * len(segs) + ["crease"] * len(CREASES),
    )
    b.raw("Q")


def annotations_outlined(b: Builder):
    """Figma-style dimension marker outside the carton: dashed bar line, end ticks, red tag."""
    y = -14
    dashes = [((x, y), (x + 2, y)) for x in range(12, 70, 3)]
    b.raw("q 0.88 0.03 0.09 rg")
    b.paint(" ".join(bar(a, c, 0.25) for a, c in dashes), "f", ["annotation"] * len(dashes))
    b.paint(
        bar((12, y - 2), (12, y + 2), 0.25) + " " + bar((72, y - 2), (72, y + 2), 0.25),
        "f",
        ["annotation", "annotation"],
    )
    b.paint(rect(36, y - 2.5, 12, 5), "f", "artwork")  # label tag, thick fill
    b.raw("Q")
    b.raw(f"BT /F1 7 Tf 1 1 1 rg 1 0 0 1 {P(37, y + 1)} Tm (60mm) Tj ET")


def spot_uv(b: Builder):
    b.raw("q /CSSpotUV cs 1 scn")
    b.paint(rect(24, T + 30, 8, 26), "f", "finish")
    b.paint(rect(36, T + 30, 8, 26), "f", "finish")
    b.paint(rect(48, T + 30, 12, 8), "f", "finish")
    b.raw("Q")


def separation(pdf: pikepdf.Pdf, name: str, cmyk: tuple[float, float, float, float]):
    fn = Dictionary(
        FunctionType=2, Domain=Array([0, 1]), C0=Array([0, 0, 0, 0]), C1=Array(list(cmyk)), N=1
    )
    return Array([Name.Separation, Name("/" + name), Name.DeviceCMYK, pdf.make_indirect(fn)])


def gradient_image(pdf: pikepdf.Pdf):
    w = h = 48
    raw = bytearray()
    for y in range(h):
        for x in range(w):
            raw += bytes((40 + x * 4, 120 + y * 2, 200 - x * 2))
    return pdf.make_stream(
        zlib.compress(bytes(raw)),
        Type=Name.XObject,
        Subtype=Name.Image,
        Width=w,
        Height=h,
        ColorSpace=Name.DeviceRGB,
        BitsPerComponent=8,
        Filter=Name.FlateDecode,
    )


def build(name: str, *, structure: str, layers: bool, finish: bool, annotate: bool = True):
    pdf = pikepdf.new()
    b = Builder()
    ocgs: dict[str, pikepdf.Object] = {}

    def layer(label: str, fn):
        if not layers:
            fn()
            return
        if label not in ocgs:
            ocgs[label] = pdf.make_indirect(Dictionary(Type=Name.OCG, Name=label))
        b.raw(f"/OC /L{list(ocgs).index(label)} BDC")
        fn()
        b.raw("EMC")

    if structure == "outlined":
        # Full-artboard background like a Figma frame: extends far beyond the carton.
        b.raw("0.86 0.85 0.72 rg")
        b.paint(rect(-MARGIN, -MARGIN, PAGE_W_MM, PAGE_H_MM), "f", "artwork")
    layer("Artwork", lambda: artwork(b, red_trap=structure != "outlined"))
    if finish:
        layer("SpotUV", lambda: spot_uv(b))
    if annotate:
        layer(
            "Info", lambda: annotations_outlined(b) if structure == "outlined" else annotations(b)
        )
    if structure == "named":
        if layers:
            # Layered variant: plain CMYK strokes, the layer name carries the meaning.
            b.raw("q 0 1 0 0 K 0.5 w")
            layer("Cut", lambda: b.paint(polyline(OUTLINE, close=True), "S", "cut"))
            b.raw("Q q 0 0 1 0 K 0.5 w [3 2] 0 d")
            layer("Crease", lambda: [b.paint(polyline([a, c]), "S", "crease") for a, c in CREASES])
            b.raw("Q")
        else:
            structure_named(b)
    elif structure == "unnamed":
        structure_unnamed(b)
    elif structure == "single_sep":
        structure_single_separation(b)
    elif structure == "unnamed_solid":
        structure_unnamed_solid(b)
    elif structure == "outlined":
        structure_outlined(b)

    font = pdf.make_indirect(
        Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica)
    )
    resources = Dictionary(
        Font=Dictionary(F1=font),
        XObject=Dictionary(Im1=gradient_image(pdf)),
        ColorSpace=Dictionary(
            CSDie=separation(pdf, "Die", (0, 1, 0, 0)),
            CSCrease=separation(pdf, "Crease", (1, 0, 0, 0)),
            CSSpotUV=separation(pdf, "SpotUV", (0, 0, 1, 0)),
        ),
    )
    if ocgs:
        resources.Properties = Dictionary({f"/L{i}": o for i, o in enumerate(ocgs.values())})
        pdf.Root.OCProperties = Dictionary(
            OCGs=Array(list(ocgs.values())), D=Dictionary(Order=Array(list(ocgs.values())))
        )

    page = pdf.add_blank_page(page_size=(PAGE_W_MM * MM, PAGE_H_MM * MM))
    page.Resources = resources
    page.Contents = pdf.make_stream("\n".join(b.ops).encode())
    pdf.save(OUT / f"{name}.pdf")

    truth = {
        "name": name,
        "page_mm": [PAGE_W_MM, PAGE_H_MM],
        "outline_mm": [[x + MARGIN, y + MARGIN] for x, y in OUTLINE],
        "paths": b.truth,
        "expect": {
            "cut": structure != "none",
            "cut_named": structure == "named",
            "finish_named": finish,
            "panels_min": 4 if structure != "none" else 0,
        },
    }
    (OUT / f"{name}.truth.json").write_text(json.dumps(truth, indent=2))


def build_flattened():
    import pymupdf

    src = pymupdf.open(OUT / "named_spot.pdf")
    pix = src[0].get_pixmap(dpi=150)
    doc = pymupdf.open()
    page = doc.new_page(width=src[0].rect.width, height=src[0].rect.height)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    doc.save(OUT / "flattened.pdf")


def build_encrypted():
    with pikepdf.open(OUT / "named_spot.pdf") as pdf:
        pdf.save(OUT / "encrypted.pdf", encryption=pikepdf.Encryption(user="secret", owner="x"))


def build_multipage():
    with pikepdf.open(OUT / "named_spot.pdf") as pdf:
        pdf.pages.append(pdf.pages[0])
        pdf.save(OUT / "multipage.pdf")


def main():
    build("named_spot", structure="named", layers=False, finish=True)
    build("ocg_layers", structure="named", layers=True, finish=False)
    build("unnamed_mixed", structure="unnamed", layers=False, finish=False)
    build("artwork_only", structure="none", layers=False, finish=False, annotate=False)
    build("named_single_sep", structure="single_sep", layers=False, finish=False)
    build("unnamed_solid", structure="unnamed_solid", layers=False, finish=False)
    build("figma_outlined", structure="outlined", layers=False, finish=False)
    build_flattened()
    build_encrypted()
    build_multipage()
    (OUT / "corrupt.pdf").write_bytes(b"%PDF-1.7\nthis is not really a pdf\n")
    print("written to", OUT)


if __name__ == "__main__":
    main()
