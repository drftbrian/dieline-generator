"""API request/response models. The frontend's TypeScript types are generated from these."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.errors import ErrorBody
from app.spec.models import PathClass

ProjectStatus = Literal[
    "uploading", "analyzing", "needs_page", "needs_review", "rendering", "ready", "failed"
]


class SourceOut(BaseModel):
    filename: str
    size_bytes: int
    sha256: str
    page_count: int
    width_mm: float
    height_mm: float
    uploaded_at: str


class FigmaLayer(BaseModel):
    name: str
    cls: str
    shapes: int


class FigmaInfo(BaseModel):
    """Where a project came from when it was imported by Figma link."""

    url: str
    file_key: str
    node_id: str
    file_name: str
    node_name: str
    version: str
    last_modified: str
    layers: list[FigmaLayer]
    synced_from: str | None = None  # older projects: the project this one was re-imported from
    # Texts/graphics read from Figma are stored (older imports get them on first use).
    content_ready: bool = False


class ProjectOut(BaseModel):
    id: str
    name: str
    status: ProjectStatus
    source: SourceOut | None
    spec_version: int
    thumbnail_url: str | None
    version_count: int
    latest_version: int | None
    active_job_id: str | None
    figma: FigmaInfo | None = None
    error: ErrorBody | None
    created_at: str
    updated_at: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ProjectPatch(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class FigmaImportIn(BaseModel):
    url: str = Field(min_length=10, max_length=1000)


class FigmaStatus(BaseModel):
    configured: bool


class JobRef(BaseModel):
    job_id: str


class UploadOut(BaseModel):
    project: ProjectOut
    job_id: str


class AnalyzeIn(BaseModel):
    page: int | None = Field(None, ge=0)


class JobStage(BaseModel):
    key: str
    status: Literal["pending", "running", "done", "failed", "skipped"]
    summary: dict[str, Any] | None = None
    message: str | None = None


class JobOut(BaseModel):
    id: str
    project_id: str
    type: Literal["analyze", "render", "generate", "merge"]
    status: Literal["pending", "running", "done", "failed", "cancelled"]
    progress: float
    stages: list[JobStage]
    result: dict[str, Any] | None
    error: ErrorBody | None


class PathUpdate(BaseModel):
    id: str
    cls: PathClass


class ManualPath(BaseModel):
    """A user-drawn closed outline (for PDFs without usable cut lines)."""

    points: list[tuple[float, float]] = Field(min_length=3)


class PanelName(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=40)


class BoxIn(BaseModel):
    width_mm: float = Field(gt=0, le=2000)
    depth_mm: float = Field(gt=0, le=2000)
    height_mm: float = Field(gt=0, le=2000)


class SpecPatch(BaseModel):
    box: BoxIn | None = None  # finished carton size; calibrates the scale when no marks exist
    mm_per_pt: float | None = Field(None, gt=0, le=10)  # explicit physical scale override
    paths: list[PathUpdate] | None = None
    manual_cut: ManualPath | None = None
    remove_paths: list[str] | None = None
    panel_names: list[PanelName] | None = None


class FrameOut(BaseModel):
    origin: tuple[float, float]
    size: tuple[float, float]


ReferenceStatus = Literal["pending", "done", "failed", "skipped", "stale"]


class ReferenceSection(BaseModel):
    key: str
    title_ko: str
    text_en: str


class ReferenceCamera(BaseModel):
    azimuth: float
    elevation: float
    lens_mm: float
    placement: list[float]  # x0, y0, x1, y1 fractions of the frame
    aspect_ratio: str


class ReferenceLight(BaseModel):
    key_azimuth: float
    key_elevation: float
    quality: str
    shadow: str
    temperature: str


class ReferenceAnalysis(BaseModel):
    """Claude's reading of the reference (guide: app/ai/prompts/reference_guide.md)."""

    category: Literal["person", "beverage", "product_packaging"]
    summary: str
    sections: list[ReferenceSection]  # the category's seven sections, in order
    packaging_form: Literal["flat", "folded", "none"]
    camera: ReferenceCamera
    light: ReferenceLight
    prompt_en: str


class ReferenceOut(BaseModel):
    id: str
    filename: str
    width: int
    height: int
    # "stale": read by an earlier version of the app; it is read again in the background.
    analysis_status: ReferenceStatus
    analysis: ReferenceAnalysis | None = None  # only a current reading
    image_url: str
    thumb_url: str
    created_at: str


class GenerateIn(BaseModel):
    """Step 2 takes no options: the look is fixed."""


MergeForm = Literal["auto", "flat", "folded"]


class MergeIn(BaseModel):
    reference_id: str
    flat_version_id: str | None = None  # default: the latest successful flat render
    form: MergeForm = "auto"  # auto = the form Claude read in the reference (none -> folded)


class GenerateOut(BaseModel):
    job_id: str
    version_id: str


class VerifyOut(BaseModel):
    protected_px: int
    changed_px: int
    changed_ratio: float
    match: bool  # print detail identical (light and surface may differ)
    light_applied: bool = False
    detail_match: float | None = None
    min_gain: float | None = None
    max_gain: float | None = None
    residual: float | None = None  # 8-bit levels between result and print x light
    light_roughness: float | None = None
    print_ghost: float | None = None  # model's own print leaking into the surface (<0.3)
    print_echo: float | None = None  # displaced copy of the print (stereo ghost, <0.15)
    colour_delta_e_median: float | None = None  # package vs its print (CIE76, <=3)
    colour_delta_e_max: float | None = None  # worst Figma colour (CIE76, <=6)


class VersionOut(BaseModel):
    id: str
    number: int
    kind: Literal["flat", "merge"]  # step 2 flat render or step 3 reference merge
    # Made by an earlier version of the app (other looks, providers or scene mockups): shown
    # and downloadable, never used as the flat render of a merge.
    legacy: bool
    status: Literal["running", "done", "failed"]
    provider_label: str
    model_id: str
    flat_version_id: str | None = None  # merge: the flat render it was made from
    reference_id: str | None = None  # merge: the reference photo
    form: Literal["flat", "folded"] | None = None  # merge: the form used
    verify: VerifyOut | None
    frame: FrameOut | None
    error: ErrorBody | None
    job_id: str | None
    image_url: str | None
    thumb_url: str | None
    download_url: str | None
    created_at: str


class HistoryOut(BaseModel):
    versions: list[VersionOut]
