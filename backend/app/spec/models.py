"""Packaging Specification Manifest.

Every structural or artwork element carries ``provenance`` so AI-inferred values stay
distinguishable from extracted document facts (trust hierarchy below).
"""

from typing import Literal

from pydantic import BaseModel, Field

# Trust order, highest first.
Provenance = Literal[
    "pdf",  # read directly from the PDF
    "extracted",  # deterministic analysis of PDF data
    "user_confirmed",
    "user_setting",
    "claude_inferred",
    "generated",
    "default",
    "estimate",
]

PathClass = Literal["cut", "crease", "artwork", "annotation", "finish", "bleed"]
PathStatus = Literal["auto", "unresolved", "confirmed"]
SeparationState = Literal["detected", "estimated", "missing", "absent_optional"]


class PageInfo(BaseModel):
    index: int
    count: int
    width_pt: float
    height_pt: float
    width_mm: float
    height_mm: float
    rotation: int


class SeparationItem(BaseModel):
    state: SeparationState
    required: bool
    path_count: int = 0
    evidence: list[str] = []


class Separations(BaseModel):
    cut: SeparationItem
    crease: SeparationItem
    artwork: SeparationItem
    finish: SeparationItem


class AiSuggestion(BaseModel):
    cls: PathClass
    reason: str


class StructuralPath(BaseModel):
    id: str
    cls: PathClass
    status: PathStatus
    suggested_cls: PathClass | None = None
    confidence: float
    provenance: Provenance
    reason: str
    ai: AiSuggestion | None = None
    polylines: list[list[tuple[float, float]]]  # flattened geometry, page points (y down)
    closed: list[bool]
    bbox: tuple[float, float, float, float]
    color: str  # hex
    dashed: bool
    width_pt: float
    color_space: str
    layers: list[str]
    source_ref: str  # "<stream>#<op index>", or "manual:<n>" for user-drawn outlines
    subpath: int | None = None  # piece index when one PDF path holds several lines


class Panel(BaseModel):
    id: str
    name: str
    name_provenance: Provenance
    bbox: tuple[float, float, float, float]
    area_mm2: float
    area_pt2: float = 0.0  # in PDF units; mm values derive from it via the physical scale
    width_mm: float = 0.0
    height_mm: float = 0.0


PDF_MM_PER_PT = 25.4 / 72


class PhysicalScale(BaseModel):
    """Millimetres per PDF unit. PDF units are physical only for print-ready files;
    design-tool exports (Figma: 1 px -> 1 unit) need a ruler, e.g. dimension marks."""

    mm_per_pt: float = PDF_MM_PER_PT
    source: Literal["dimension_marks", "pdf_units", "user"] = "pdf_units"
    confidence: float = 0.5
    evidence: list[str] = []


class BoxDims(BaseModel):
    """Finished carton size as written by the designer (e.g. "100*52*141")."""

    width_mm: float
    depth_mm: float
    height_mm: float
    source: Literal["title_text", "user"] = "title_text"


class ArtObject(BaseModel):
    id: str
    kind: Literal["text", "vector", "image"]
    label: str
    bbox: tuple[float, float, float, float]
    color: str | None = None
    path_ids: list[str] = []  # source_refs of member paths (vector groups)
    detail: dict = {}


class LayerInfo(BaseModel):
    name: str
    path_count: int
    role: PathClass | None


class ReviewState(BaseModel):
    required: bool
    reasons: list[Literal["uncertain_paths", "cut_missing", "cut_open"]]
    pending: int


class Counts(BaseModel):
    vectors: int
    images: int
    text_spans: int
    fonts: list[str]
    color_spaces: list[str]
    spot_colors: list[str]


class Material(BaseModel):
    """The board of the flat render: plain white paperboard (the design's unprinted paper)."""

    base_color: str = "#FFFFFF"
    caliper_mm: float = Field(0.46, ge=0.2, le=1.2)
    reflectivity: int = Field(8, ge=0, le=100)
    roughness: int = Field(70, ge=0, le=100)
    texture: int = Field(20, ge=0, le=100)  # paper fibres: 20 = about +-1.4% (spec cap 1.5%)
    crease_depth: int = Field(30, ge=0, le=100)  # how pressed-in the folds look


class Lighting(BaseModel):
    light_angle: int = Field(315, ge=0, lt=360)  # where light comes from, 0 = top, clockwise
    light_intensity: int = Field(60, ge=0, le=100)
    shadow_strength: int = Field(25, ge=0, le=100)
    background_color: str = "#000000"
    margin: int = Field(12, ge=0, le=40)  # % of package size


LookStyle = Literal["v1", "v2", "v3", "v4"]
FoldPreset = Literal["low", "medium", "high"]


class Look(BaseModel):
    """The fixed look of the flat render (step 2). Not user-editable.

    ``style`` picks the board model: "v4" (v3 with physical fold scores, opt-in), "v3" (v2 +
    finishing: edge tone, contact shadow on a
    near-black ground, deeper scores, panel planes), "v2" (physical: paper fibres, cut-edge
    thickness, soft fold scores, overhead light) or "v1" (the first deterministic look).
    v1 and v2 are kept unchanged for comparison.
    """

    material: Material = Material()
    lighting: Lighting = Lighting()
    style: LookStyle = "v2"
    fold_preset: FoldPreset = "medium"  # v4: physical fold score detail (render/folds.py)


# Matte white board on solid black, top-down, soft even light (see prompts/flat_look.png).
FLAT_LOOK_V1 = Look(style="v1")
FLAT_LOOK_V2 = Look(style="v2")
# v3: the ground is near-black (#040404, reads as black) so the contact shadow, down to true
# black at the cut, can actually be seen.
FLAT_LOOK = Look(style="v3", lighting=Lighting(background_color="#040404", shadow_strength=60))
# v4: v3 with physical fold scores (height field, normals, soft key light). Not the default
# until it passes review.
FLAT_LOOK_V4 = FLAT_LOOK.model_copy(update={"style": "v4"})
FLAT_LOOKS: dict[str, Look] = {
    "v1": FLAT_LOOK_V1,
    "v2": FLAT_LOOK_V2,
    "v3": FLAT_LOOK,
    "v4": FLAT_LOOK_V4,
}


def flat_look(style: str, fold_preset: str = "medium") -> Look:
    """The look ``style``; for v4 with the given fold detail preset."""
    look = FLAT_LOOKS[style]
    return look.model_copy(update={"fold_preset": fold_preset}) if style == "v4" else look


class Specification(BaseModel):
    """Keys written by older versions of the app (settings, checks, ...) are ignored on load."""

    version: int = 1
    page: PageInfo
    flattened: bool
    separations: Separations
    paths: list[StructuralPath]
    panels: list[Panel]
    objects: list[ArtObject]
    layers: list[LayerInfo]
    review: ReviewState
    structure_confirmed: bool
    counts: Counts
    scale: PhysicalScale = PhysicalScale()
    box: BoxDims | None = None
