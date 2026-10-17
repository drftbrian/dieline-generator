"""Post-press finishing catalogue: stable ids, Korean/English labels, the material model each finish
uses, and its user parameters with bounded, research-based defaults.

Sources: docs/research/postpress/material-behavior-matrix.md (optics), finishing-research.md
(numbers), manufacturing-constraints.md (limits). Ids are stable API/data keys; never rename one,
add a new id instead. Values marked "inferred" in the research are kept conservative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Category = Literal["foil", "relief", "surface", "coating", "dome"]
# How a finish is rendered (render/finishing): its optical model.
Model = Literal["metal", "pigment", "holographic", "relief", "clearcoat", "uncoated", "dome"]
# Where a finish may be applied.
Scope = Literal["selective", "surface", "both"]


@dataclass(frozen=True)
class Param:
    id: str
    label_ko: str
    label_en: str
    min: float
    max: float
    default: float
    unit: str = ""  # "mm", "" for 0..1 amounts
    note: str = ""  # where the default comes from


@dataclass(frozen=True)
class Finish:
    id: str  # stable, e.g. "foil.gold"
    category: Category
    label_ko: str
    label_en: str
    model: Model
    scope: Scope
    color: str | None = None  # foil tint / pigment colour (sRGB hex); None = clear or substrate
    params: tuple[Param, ...] = field(default_factory=tuple)
    available: bool = True  # False: reserved in the data model, not offered yet
    note: str = ""


CATEGORIES: dict[str, tuple[str, str]] = {
    "foil": ("박", "Foil stamping"),
    "relief": ("형압", "Embossing / debossing"),
    "surface": ("코팅", "Lamination / surface"),
    "coating": ("액상 코팅", "Liquid coating"),
    "dome": ("에폭시", "Resin doming"),
}

# ---- parameters ----------------------------------------------------------------------------

# Foil: metal BRDF with an environment / reflector term (matrix §C: flat foil seen top-down
# mirrors the camera's surroundings and reads dark unless a reflector is near the camera).
REFLECTIVITY = Param("reflectivity", "반사도", "Reflectivity", 0.5, 1.0, 0.9, note="metal F0")
ROUGHNESS_FOIL = Param(
    "roughness", "거칠기", "Roughness", 0.02, 0.6, 0.12, note="gloss foil very low; matt ~0.4"
)
REFLECTOR = Param(
    "reflector",
    "반사판",
    "Reflector card",
    0.0,
    1.0,
    0.5,
    note="white card near the camera (tog.ink overhead foil shoot)",
)
GLINT = Param(
    "glint",
    "반짝임",
    "Glint",
    0.0,
    1.0,
    0.5,
    note="foil follows the paper's micro-relief: fine sparkle (inspected swatches, 박종류별/녹박/청박)",
)
IMPRESSION = Param(
    "impression_mm",
    "눌림 깊이",
    "Impression depth",
    0.0,
    0.1,
    0.02,
    "mm",
    note="hot-foil die impression; a hairline rim (matrix §B)",
)
ROUGHNESS_PIGMENT = Param("roughness", "거칠기", "Roughness", 0.3, 0.9, 0.7, note="near-diffuse")
SHEEN = Param("sheen", "광택", "Sheen", 0.0, 0.4, 0.1, note="faint matte sheen of pigment foil")
OPACITY = Param(
    "opacity",
    "은폐력",
    "Opacity",
    0.7,
    1.0,
    1.0,
    note="white foil may need a double hit (Briar Press)",
)
RAINBOW = Param(
    "diffraction",
    "회절 세기",
    "Diffraction",
    0.0,
    1.0,
    0.6,
    note="rainbow only under directional light; pale pastel when soft (4OVER4, inspected samples)",
)
GRATING = Param(
    "grating_lines_mm", "격자 밀도", "Grating density", 300, 1500, 1000, "lines/mm", "typical holo"
)

# Emboss / deboss: height field from the mask (Iggesund: 0.15-2.5 mm; foil-emboss 0.25-0.60 mm).
DEPTH = Param("depth_mm", "깊이", "Relief depth", 0.15, 1.0, 0.3, "mm", "Iggesund; blind 0.3")
SHOULDER = Param(
    "shoulder_mm", "어깨 폭", "Shoulder width", 0.1, 1.5, 0.4, "mm", "no published angles: inferred"
)
SOFTNESS = Param("softness", "가장자리 부드러움", "Edge softness", 0.0, 1.0, 0.4)
PROFILE = Param(
    "profile", "다이 형태", "Die profile", 0, 3, 0, note="0 flat, 1 bevel, 2 rounded, 3 sculpted"
)
LIGHT_BALANCE = Param("shadow_balance", "그림자/빛 균형", "Shadow/highlight balance", 0.0, 1.0, 0.5)


# Clearcoats: gloss lam ≈ gloss UV < aqueous < satin < matte lam < soft-touch (matrix §C).
def _clear_roughness(default: float, note: str) -> Param:
    return Param("roughness", "거칠기", "Roughness", 0.01, 0.8, default, note=note)


GLOSS = Param("gloss", "광택 세기", "Gloss strength", 0.0, 1.0, 0.8)
SATURATION = Param(
    "saturation",
    "색 깊이",
    "Colour depth",
    0.0,
    0.15,
    0.06,
    note="clear layers saturate (Iggesund)",
)
VEIL = Param(
    "veil", "베일", "Veiling lift", 0.0, 0.08, 0.03, note="matte films lift darks slightly"
)
FIBRE = Param("fibre", "섬유결", "Fibre texture", 0.0, 1.0, 0.6)
DOT_GAIN = Param(
    "dot_gain",
    "잉크 번짐",
    "Ink absorption",
    0.0,
    0.3,
    0.12,
    note="uncoated: lower density, more dot gain",
)
MISREGISTER = Param(
    "misregistration_mm",
    "어긋남",
    "Misregistration",
    0.0,
    1.0,
    0.0,
    "mm",
    "±0.5-2 mm in production",
)

RAISED = Param(
    "height_um", "두께", "Coat height", 20, 100, 50, "µm", note="digital raised UV 20-100 µm"
)

# Dome: capillary meniscus, ~1.5 mm ±0.5 (Screen Printing mag, Publog).
DOME_HEIGHT = Param("height_mm", "돔 높이", "Dome height", 0.5, 2.5, 1.5, "mm")
CLARITY = Param("clarity", "투명도", "Optical clarity", 0.7, 1.0, 0.95)
HIGHLIGHT = Param("highlight", "하이라이트", "Highlight intensity", 0.0, 1.0, 0.7)
REFRACTION = Param("ior", "굴절률", "Refractive index", 1.45, 1.6, 1.5, note="epoxy/PU ≈ 1.5")


def _foil(key: str, ko: str, en: str, color: str, note: str = "") -> Finish:
    return Finish(
        f"foil.{key}",
        "foil",
        ko,
        en,
        "metal",
        "selective",
        color,
        (REFLECTIVITY, ROUGHNESS_FOIL, REFLECTOR, GLINT, IMPRESSION, MISREGISTER),
        note=note,
    )


def _pigment(key: str, ko: str, en: str, color: str, extra: tuple[Param, ...] = ()) -> Finish:
    return Finish(
        f"foil.{key}",
        "foil",
        ko,
        en,
        "pigment",
        "selective",
        color,
        (ROUGHNESS_PIGMENT, SHEEN, IMPRESSION, MISREGISTER, *extra),
    )


FINISHES: tuple[Finish, ...] = (
    # A. Foil — metallic colour foils and pigment colour foils are separate choices: under an
    # overhead light they look completely different (dark with streaks vs flat colour).
    _foil("gold", "금박", "Gold foil", "#D4AF37"),
    _foil("silver", "은박", "Silver foil", "#D8DADC"),
    # 먹박 in the inspected samples is gloss black on matte stock (visible as sheen contrast);
    # a matte pigment black is a separate choice.
    _foil("black", "먹박", "Black foil (gloss)", "#141414"),
    _pigment("black_matte", "먹박 (무광)", "Black foil (matte)", "#111111"),
    _pigment("white", "백박", "White foil", "#F7F7F5", (OPACITY,)),
    _foil("red_metallic", "적박 (메탈)", "Red foil (metallic)", "#B3262E"),
    _pigment("red", "적박 (안료)", "Red foil (pigment)", "#C1272D"),
    _foil("green_metallic", "녹박 (메탈)", "Green foil (metallic)", "#2E7D4F"),
    _pigment("green", "녹박 (안료)", "Green foil (pigment)", "#1F7A48"),
    _foil("blue_metallic", "청박 (메탈)", "Blue foil (metallic)", "#24569E"),
    _pigment("blue", "청박 (안료)", "Blue foil (pigment)", "#1F4E9C"),
    Finish(
        "foil.holographic",
        "foil",
        "홀로그램박",
        "Holographic foil",
        "holographic",
        "selective",
        "#C9CCD1",
        (REFLECTIVITY, ROUGHNESS_FOIL, REFLECTOR, GLINT, RAINBOW, GRATING, MISREGISTER),
    ),
    # B. Relief — blind or registered (over print), emboss or deboss.
    Finish(
        "relief.emboss",
        "relief",
        "엠보싱 (볼록형압)",
        "Embossing",
        "relief",
        "selective",
        params=(DEPTH, SHOULDER, SOFTNESS, PROFILE, LIGHT_BALANCE),
    ),
    Finish(
        "relief.deboss",
        "relief",
        "디보싱 (오목형압)",
        "Debossing",
        "relief",
        "selective",
        params=(DEPTH, SHOULDER, SOFTNESS, PROFILE, LIGHT_BALANCE),
    ),
    # C. Surface — films bonded to the board, or no film at all. Whole panel / sheet.
    Finish(
        "surface.gloss_lamination",
        "surface",
        "유광 라미네이팅",
        "Gloss lamination",
        "clearcoat",
        "surface",
        params=(_clear_roughness(0.03, "smooth PP film"), GLOSS, SATURATION),
    ),
    Finish(
        "surface.matte_lamination",
        "surface",
        "무광 라미네이팅",
        "Matte lamination",
        "clearcoat",
        "surface",
        params=(_clear_roughness(0.45, "45° gloss <10 GU"), GLOSS, VEIL),
    ),
    Finish(
        "surface.soft_touch",
        "surface",
        "벨벳(소프트터치) 라미네이팅",
        "Soft-touch lamination",
        "clearcoat",
        "surface",
        params=(_clear_roughness(0.6, "≤20 GU at 60°"), GLOSS, VEIL),
    ),
    Finish(
        "surface.uncoated",
        "surface",
        "비코팅",
        "Uncoated",
        "uncoated",
        "surface",
        params=(FIBRE, DOT_GAIN),
        note="no film: diffuse paper, lower solid density",
    ),
    # D. Liquid coatings — clear, thin (µm): visible as gloss contrast, not relief.
    Finish(
        "coating.spot_uv",
        "coating",
        "부분 UV",
        "Spot UV",
        "clearcoat",
        "selective",
        params=(_clear_roughness(0.03, "2-20 µm, highest gloss"), GLOSS, SATURATION, MISREGISTER),
        note="best over matte/soft-touch; flag on gloss lamination or uncoated",
    ),
    Finish(
        "coating.flood_uv",
        "coating",
        "전체 UV",
        "Flood UV",
        "clearcoat",
        "surface",
        params=(_clear_roughness(0.04, "5-25 µm"), GLOSS, SATURATION),
    ),
    Finish(
        "coating.varnish_gloss",
        "coating",
        "유광 바니시",
        "Gloss varnish",
        "clearcoat",
        "both",
        params=(_clear_roughness(0.1, "below UV gloss"), GLOSS, SATURATION),
    ),
    Finish(
        "coating.varnish_satin",
        "coating",
        "반광(새틴) 바니시",
        "Satin varnish",
        "clearcoat",
        "both",
        params=(_clear_roughness(0.25, "between gloss and matt"), GLOSS),
    ),
    Finish(
        "coating.varnish_matte",
        "coating",
        "무광 바니시",
        "Matte varnish",
        "clearcoat",
        "both",
        params=(_clear_roughness(0.45, "diffuse"), GLOSS, VEIL),
    ),
    Finish(
        "coating.raised_uv",
        "coating",
        "입체 UV (디지털 에폭시)",
        "Raised UV",
        "clearcoat",
        "selective",
        params=(_clear_roughness(0.03, "glossy raised clear"), GLOSS, SATURATION, RAISED),
        note="20-100 µm digital raised UV (Scodix type); Korean '에폭시' on cards often means this",
    ),
    # E. Resin domes — poured resin with a pinned meniscus; applied labels, not a board coating.
    Finish(
        "dome.epoxy",
        "dome",
        "에폭시 도밍",
        "Epoxy dome",
        "dome",
        "selective",
        params=(DOME_HEIGHT, CLARITY, HIGHLIGHT, REFRACTION),
    ),
    Finish(
        "dome.polyurethane",
        "dome",
        "우레탄 도밍",
        "Polyurethane dome",
        "dome",
        "selective",
        params=(DOME_HEIGHT, CLARITY, HIGHLIGHT, REFRACTION),
        note="PU: softer, non-yellowing; optics like epoxy",
    ),
)

BY_ID: dict[str, Finish] = {f.id: f for f in FINISHES}


def finish(fid: str) -> Finish:
    if fid not in BY_ID:
        raise KeyError(f"unknown finish {fid!r}")
    return BY_ID[fid]


def defaults(fid: str) -> dict[str, float]:
    return {p.id: p.default for p in finish(fid).params}


def clamp_params(fid: str, values: dict[str, float]) -> dict[str, float]:
    """The finish's parameters: given values clamped to their bounds, defaults for the rest;
    unknown keys dropped."""
    out = {}
    for p in finish(fid).params:
        v = values.get(p.id, p.default)
        out[p.id] = float(min(p.max, max(p.min, v)))
    return out
