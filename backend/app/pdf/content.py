"""Content-stream walker: every painted path with its color-space name, layer and source op.

PyMuPDF's ``get_drawings`` reports paths in RGB only, so a stroke in a spot color named
"Die" is indistinguishable from red artwork. Dieline detection needs the spot-color and
optional-content (layer) names, so this walks the content streams with pikepdf and records,
for every painting operator:

- geometry in *page space* (points, origin top-left of the CropBox, y down)
- stroke/fill color-space names (``Separation:Die``, ``DeviceCMYK`` ...)
- optional-content group names in effect
- a ``source_ref`` (stream key + operator index) so the renderer can suppress exactly
  that operator later without touching the original file (see ``rewrite.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pikepdf
from pikepdf import Name

Point = tuple[float, float]
# ("L", p0, p1) or ("C", p0, c1, c2, p1)
Segment = tuple


@dataclass
class PaintedPath:
    index: int
    stream: str
    op_index: int
    subpaths: list[list[Segment]]
    closed: list[bool]
    stroke: bool
    fill: bool
    stroke_cs: str
    fill_cs: str
    stroke_rgb: tuple[float, float, float] | None
    fill_rgb: tuple[float, float, float] | None
    line_width: float
    dashed: bool
    ocgs: list[str]
    # Layer names from the design tool (e.g. Figma) that this path was matched to.
    design_layers: list[str] = field(default_factory=list)

    @property
    def points(self) -> list[Point]:
        pts: list[Point] = []
        for sp in self.subpaths:
            for seg in sp:
                pts.extend(seg[1:])
        return pts

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        pts = self.points
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    @property
    def stroke_only(self) -> bool:
        return self.stroke and not self.fill

    def length(self) -> float:
        total = 0.0
        for sp in self.subpaths:
            for seg in sp:
                total += math.dist(seg[1], seg[-1])
        return total


@dataclass
class WalkResult:
    paths: list[PaintedPath] = field(default_factory=list)
    spot_names: set[str] = field(default_factory=set)
    color_spaces: set[str] = field(default_factory=set)
    ocg_names: list[str] = field(default_factory=list)
    text_ops: int = 0
    image_ops: int = 0
    shading_ops: int = 0


Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1, 0, 0, 1, 0, 0)


def mat_mul(m: Matrix, n: Matrix) -> Matrix:
    """m then n (PDF convention: new_ctm = m x ctm)."""
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a * a2 + b * c2,
        a * b2 + b * d2,
        c * a2 + d * c2,
        c * b2 + d * d2,
        e * a2 + f * c2 + e2,
        e * b2 + f * d2 + f2,
    )


def apply(m: Matrix, x: float, y: float) -> Point:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def cmyk_to_rgb(c: float, m: float, y: float, k: float) -> tuple[float, float, float]:
    return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))


@dataclass
class ColorSpace:
    name: str  # display name, e.g. "Separation:Die"
    base: str  # "gray" | "rgb" | "cmyk" | "sep" | "pattern" | "other"
    sep_alt: tuple[float, ...] | None = None  # alternate CMYK/RGB at tint 1 (Type 2 fn)
    sep_alt_base: str | None = None


DEVICE = {
    "/DeviceGray": ColorSpace("DeviceGray", "gray"),
    "/DeviceRGB": ColorSpace("DeviceRGB", "rgb"),
    "/DeviceCMYK": ColorSpace("DeviceCMYK", "cmyk"),
    "/Pattern": ColorSpace("Pattern", "pattern"),
}


def _num(o) -> float:
    try:
        return float(o)
    except (TypeError, ValueError):
        return 0.0


def resolve_colorspace(name: str, resources) -> ColorSpace:
    if name in DEVICE:
        return DEVICE[name]
    try:
        obj = resources.ColorSpace[name]
    except (AttributeError, KeyError, TypeError):
        return ColorSpace(name.lstrip("/"), "other")
    return describe_colorspace(obj)


def describe_colorspace(obj) -> ColorSpace:
    if isinstance(obj, Name):
        return DEVICE.get(str(obj), ColorSpace(str(obj).lstrip("/"), "other"))
    if not isinstance(obj, pikepdf.Array) or len(obj) == 0:
        return ColorSpace("Unknown", "other")
    kind = str(obj[0])
    if kind == "/Separation":
        sep = str(obj[1]).lstrip("/")
        alt = describe_colorspace(obj[2])
        c1 = None
        try:
            fn = obj[3]
            if int(fn.get("/FunctionType", -1)) == 2 and "/C1" in fn:
                c1 = tuple(_num(v) for v in fn.C1)
        except Exception:  # noqa: BLE001 - malformed tint transforms are common
            c1 = None
        return ColorSpace(f"Separation:{sep}", "sep", c1, alt.base)
    if kind == "/DeviceN":
        names = ",".join(str(n).lstrip("/") for n in obj[1])
        return ColorSpace(f"DeviceN:{names}", "other")
    if kind == "/ICCBased":
        n = int(obj[1].get("/N", 3))
        base = {1: "gray", 3: "rgb", 4: "cmyk"}.get(n, "other")
        return ColorSpace(f"ICCBased({base})", base)
    if kind in ("/CalRGB", "/Lab"):
        return ColorSpace(kind.lstrip("/"), "rgb")
    if kind == "/CalGray":
        return ColorSpace("CalGray", "gray")
    if kind == "/Indexed":
        return ColorSpace("Indexed", "other")
    if kind == "/Pattern":
        return ColorSpace("Pattern", "pattern")
    return ColorSpace(kind.lstrip("/"), "other")


def to_rgb(cs: ColorSpace, comps: list[float]) -> tuple[float, float, float] | None:
    if cs.base == "gray" and comps:
        g = comps[0]
        return (g, g, g)
    if cs.base == "rgb" and len(comps) >= 3:
        return (comps[0], comps[1], comps[2])
    if cs.base == "cmyk" and len(comps) >= 4:
        return cmyk_to_rgb(*comps[:4])
    if cs.base == "sep" and comps:
        t = comps[0]
        if cs.sep_alt and cs.sep_alt_base == "cmyk" and len(cs.sep_alt) == 4:
            return cmyk_to_rgb(*(v * t for v in cs.sep_alt))
        if cs.sep_alt and cs.sep_alt_base == "rgb" and len(cs.sep_alt) == 3:
            return tuple(1 - (1 - v) * t for v in cs.sep_alt)  # type: ignore[return-value]
        return (1 - 0.7 * t,) * 3  # unknown tint transform: neutral approximation
    return None


@dataclass
class GState:
    ctm: Matrix
    stroke_cs: ColorSpace
    fill_cs: ColorSpace
    stroke: list[float]
    fill: list[float]
    lw: float
    dashed: bool

    def copy(self) -> GState:
        return GState(
            self.ctm,
            self.stroke_cs,
            self.fill_cs,
            list(self.stroke),
            list(self.fill),
            self.lw,
            self.dashed,
        )


PAINT_OPS = {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"}
TEXT_SHOW = {"Tj", "TJ", "'", '"'}


def ocg_name(obj) -> list[str]:
    """Names of the OCG(s) an /OC property refers to (OCG or OCMD)."""
    try:
        if obj.get("/Type") == Name.OCMD:
            ocgs = obj.get("/OCGs")
            items = ocgs if isinstance(ocgs, pikepdf.Array) else [ocgs]
            return [str(o.get("/Name", "?")) for o in items if o is not None]
        return [str(obj.get("/Name", "?"))]
    except Exception:  # noqa: BLE001
        return []


class Walker:
    def __init__(self, page: pikepdf.Page):
        self.page = page
        box = page.obj.get("/CropBox") or page.obj.get("/MediaBox")
        x0, y0, x1, y1 = (float(v) for v in box)
        self.origin_x = min(x0, x1)
        self.top_y = max(y0, y1)
        self.result = WalkResult()
        self._visited_forms: set[tuple[int, int]] = set()

    def to_page(self, p: Point) -> Point:
        return (p[0] - self.origin_x, self.top_y - p[1])

    def run(self) -> WalkResult:
        gs = GState(IDENTITY, DEVICE["/DeviceGray"], DEVICE["/DeviceGray"], [0], [0], 1.0, False)
        self._walk(self.page.obj, "page", self.page.obj.get("/Resources"), gs, [])
        return self.result

    def _walk(self, owner, stream_key: str, resources, gs: GState, ocg_stack: list):
        try:
            ops = pikepdf.parse_content_stream(owner)
        except pikepdf.PdfError:
            return
        stack: list[GState] = []
        subpaths: list[list[Segment]] = []
        closed: list[bool] = []
        cur: Point | None = None
        start: Point | None = None
        clip_pending = False

        def T(x, y) -> Point:
            return self.to_page(apply(gs.ctm, float(x), float(y)))

        for idx, item in enumerate(ops):
            if isinstance(item, pikepdf.ContentStreamInlineImage):
                self.result.image_ops += 1
                continue
            op = str(item.operator)
            args = item.operands

            if op == "q":
                stack.append(gs.copy())
            elif op == "Q":
                if stack:
                    gs = stack.pop()
            elif op == "cm" and len(args) == 6:
                gs.ctm = mat_mul(tuple(float(a) for a in args), gs.ctm)  # type: ignore[arg-type]
            elif op == "w" and args:
                gs.lw = float(args[0])
            elif op == "d" and args:
                arr = args[0]
                gs.dashed = isinstance(arr, pikepdf.Array) and any(_num(v) > 0 for v in arr)
            elif op == "gs" and args:
                try:
                    eg = resources.ExtGState[str(args[0])]
                    if "/LW" in eg:
                        gs.lw = float(eg.LW)
                    if "/D" in eg:
                        gs.dashed = any(_num(v) > 0 for v in eg.D[0])
                except Exception:  # noqa: BLE001
                    pass
            elif op in ("CS", "cs") and args:
                cs = resolve_colorspace(str(args[0]), resources)
                self.result.color_spaces.add(cs.name)
                if cs.base == "sep":
                    self.result.spot_names.add(cs.name.split(":", 1)[1])
                if op == "CS":
                    gs.stroke_cs, gs.stroke = cs, [1.0] if cs.base == "sep" else [0.0]
                else:
                    gs.fill_cs, gs.fill = cs, [1.0] if cs.base == "sep" else [0.0]
            elif op in ("SC", "SCN"):
                gs.stroke = [_num(a) for a in args if not isinstance(a, Name)]
            elif op in ("sc", "scn"):
                gs.fill = [_num(a) for a in args if not isinstance(a, Name)]
            elif op in ("G", "g", "RG", "rg", "K", "k"):
                cs = DEVICE[
                    {"G": "/DeviceGray", "RG": "/DeviceRGB", "K": "/DeviceCMYK"}[op.upper()]
                ]
                self.result.color_spaces.add(cs.name)
                if op.isupper():
                    gs.stroke_cs, gs.stroke = cs, [_num(a) for a in args]
                else:
                    gs.fill_cs, gs.fill = cs, [_num(a) for a in args]
            elif op == "m" and len(args) == 2:
                cur = start = T(*args)
                subpaths.append([])
                closed.append(False)
            elif op == "l" and len(args) == 2 and cur is not None:
                p = T(*args)
                subpaths[-1].append(("L", cur, p))
                cur = p
            elif op in ("c", "v", "y") and cur is not None:
                vals = [float(a) for a in args]
                if op == "c" and len(vals) == 6:
                    c1, c2, p = T(vals[0], vals[1]), T(vals[2], vals[3]), T(vals[4], vals[5])
                elif op == "v" and len(vals) == 4:
                    c1, c2, p = cur, T(vals[0], vals[1]), T(vals[2], vals[3])
                elif op == "y" and len(vals) == 4:
                    c1, c2, p = T(vals[0], vals[1]), T(vals[2], vals[3]), T(vals[2], vals[3])
                else:
                    continue
                subpaths[-1].append(("C", cur, c1, c2, p))
                cur = p
            elif op == "h" and subpaths:
                if cur is not None and start is not None and cur != start:
                    subpaths[-1].append(("L", cur, start))
                closed[-1] = True
                cur = start
            elif op == "re" and len(args) == 4:
                x, y, w, h = (float(a) for a in args)
                corners = [T(x, y), T(x + w, y), T(x + w, y + h), T(x, y + h)]
                subpaths.append([("L", corners[i], corners[(i + 1) % 4]) for i in range(4)])
                closed.append(True)
                cur = start = corners[0]
            elif op in ("W", "W*"):
                clip_pending = True
            elif op in PAINT_OPS:
                if op in ("s", "b", "b*") and subpaths:
                    if cur is not None and start is not None and cur != start:
                        subpaths[-1].append(("L", cur, start))
                    closed[-1] = True
                stroke = op in ("S", "s", "B", "B*", "b", "b*")
                fill = op in ("f", "F", "f*", "B", "B*", "b", "b*")
                live = [(sp, c) for sp, c in zip(subpaths, closed, strict=True) if sp]
                if (stroke or fill) and live:
                    scale = math.sqrt(abs(gs.ctm[0] * gs.ctm[3] - gs.ctm[1] * gs.ctm[2])) or 1
                    self.result.paths.append(
                        PaintedPath(
                            index=len(self.result.paths),
                            stream=stream_key,
                            op_index=idx,
                            subpaths=[sp for sp, _ in live],
                            closed=[c for _, c in live],
                            stroke=stroke,
                            fill=fill,
                            stroke_cs=gs.stroke_cs.name,
                            fill_cs=gs.fill_cs.name,
                            stroke_rgb=to_rgb(gs.stroke_cs, gs.stroke) if stroke else None,
                            fill_rgb=to_rgb(gs.fill_cs, gs.fill) if fill else None,
                            line_width=gs.lw * scale,
                            dashed=gs.dashed,
                            ocgs=[n for frame in ocg_stack for n in (frame or [])],
                        )
                    )
                subpaths, closed, cur, start, clip_pending = [], [], None, None, False
            elif op in ("BDC", "BMC"):
                names = None
                if op == "BDC" and len(args) == 2 and str(args[0]) == "/OC":
                    prop = args[1]
                    if isinstance(prop, Name):
                        try:
                            prop = resources.Properties[str(prop)]
                        except Exception:  # noqa: BLE001
                            prop = None
                    names = ocg_name(prop) if prop is not None else None
                ocg_stack.append(names)
            elif op == "EMC":
                if ocg_stack:
                    ocg_stack.pop()
            elif op in TEXT_SHOW:
                self.result.text_ops += 1
            elif op == "sh":
                self.result.shading_ops += 1
            elif op == "Do" and args:
                self._do(str(args[0]), resources, gs, ocg_stack)
        del clip_pending

    def _do(self, name: str, resources, gs: GState, ocg_stack: list):
        try:
            xobj = resources.XObject[name]
        except Exception:  # noqa: BLE001
            return
        subtype = xobj.get("/Subtype")
        if subtype == Name.Image:
            self.result.image_ops += 1
            return
        if subtype != Name.Form:
            return
        key = xobj.objgen
        if key in self._visited_forms and key != (0, 0):
            # Shared form drawn again: geometry repeats at a new CTM; walk it again but
            # stream key stays the same so suppression applies to every placement.
            pass
        self._visited_forms.add(key)
        inner = gs.copy()
        if "/Matrix" in xobj:
            inner.ctm = mat_mul(tuple(float(v) for v in xobj.Matrix), inner.ctm)  # type: ignore[arg-type]
        frame = ocg_name(xobj.OC) if "/OC" in xobj else None
        ocg_stack.append(frame)
        self._walk(
            xobj, f"xobj:{key[0]}:{key[1]}", xobj.get("/Resources", resources), inner, ocg_stack
        )
        ocg_stack.pop()


def walk_page(pdf: pikepdf.Pdf, page_index: int = 0) -> WalkResult:
    result = Walker(pdf.pages[page_index]).run()
    try:
        ocgs = pdf.Root.OCProperties.OCGs
        result.ocg_names = [str(o.get("/Name", "?")) for o in ocgs]
    except (AttributeError, KeyError):
        result.ocg_names = []
    return result
