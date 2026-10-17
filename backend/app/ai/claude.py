"""Claude: structure suggestions, panel names, and reading reference photos.

Claude *suggests*; it never edits artwork. Structure and panel results are stored with
provenance ``claude_inferred`` and are applied only after the user approves them.
"""

from __future__ import annotations

import base64
import io
import json
from typing import Any, Literal, TypeVar

import anthropic
from PIL import Image
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.ai import prompts
from app.ai.models import CLAUDE_MODEL
from app.config import get_settings
from app.errors import ApiError

T = TypeVar("T", bound=BaseModel)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- output schemas ------------------------------------------------------------------


class AiPathSuggestion(Strict):
    id: str
    cls: Literal["cut", "crease", "artwork", "annotation"]
    reason: str


class AiStructure(Strict):
    paths: list[AiPathSuggestion]


class AiPanelName(Strict):
    id: str
    name: str


class AiPanels(Strict):
    panels: list[AiPanelName]


Category = Literal["person", "beverage", "product_packaging"]

# The seven sections of each category, in order (prompts/reference_guide.md).
CATEGORY_SECTIONS: dict[str, tuple[str, ...]] = {
    "person": ("pose", "face", "outfit", "accessories", "background", "mood", "extras"),
    "beverage": (
        "container",
        "label_typography",
        "color",
        "material",
        "background_styling",
        "brand_mood",
        "extras",
    ),
    "product_packaging": (
        "structure",
        "typography",
        "color",
        "material",
        "background_styling",
        "brand_mood",
        "extras",
    ),
}
SectionKey = Literal[
    "pose",
    "face",
    "outfit",
    "accessories",
    "background",
    "mood",
    "container",
    "label_typography",
    "structure",
    "typography",
    "color",
    "material",
    "background_styling",
    "brand_mood",
    "extras",
]


class AiReferenceSection(Strict):
    key: SectionKey
    title_ko: str
    text_en: str


class AiCamera(Strict):
    azimuth: float  # degrees, -60..60; positive shows the package's right side
    elevation: float  # degrees above the package's centre, 0..90 (90 = straight down)
    lens_mm: float  # 35 mm-equivalent
    placement: list[float]  # x0, y0, x1, y1 fractions of the frame
    aspect_ratio: Literal["1:1", "4:5", "3:2", "16:9"]


class AiLight(Strict):
    key_azimuth: float  # where light comes from; 0 = top of frame, clockwise
    key_elevation: float
    quality: Literal["soft", "hard"]
    shadow: str
    temperature: Literal["warm", "neutral", "cool"]


class AiReference(Strict):
    """Reading of a reference photo for the merge (prompts/reference_guide.md)."""

    category: Category
    summary: str
    sections: list[AiReferenceSection]
    packaging_form: Literal["flat", "folded", "none"]
    camera: AiCamera
    light: AiLight
    prompt_en: str

    @model_validator(mode="after")
    def _sections_match_category(self) -> AiReference:
        keys = [s.key for s in self.sections]
        if sorted(keys) != sorted(CATEGORY_SECTIONS[self.category]):
            raise ValueError(f"sections {keys} do not match category {self.category}")
        return self


# ---- client --------------------------------------------------------------------------


def available() -> bool:
    return get_settings().anthropic_api_key is not None


def _client() -> anthropic.Anthropic:
    key = get_settings().anthropic_api_key
    if key is None:
        raise ApiError(
            503,
            "CLAUDE_UNAVAILABLE",
            "Claude API 키가 설정되지 않았습니다.",
            hint="backend/.env에 ANTHROPIC_API_KEY를 추가한 뒤 서버를 다시 시작하세요.",
        )
    return anthropic.Anthropic(api_key=key.get_secret_value())


def strict_schema(model: type[BaseModel]) -> dict:
    """JSON schema for structured outputs: every object closed, every property required."""
    schema = model.model_json_schema()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("title", None)
            node.pop("default", None)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return schema


def _call[T: BaseModel](
    system: str, content: list[dict], out: type[T], *, effort: str = "low"
) -> T:
    client = _client()
    try:
        resp = client.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": strict_schema(out)},
            },
            system=system,
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError as e:
        raise ApiError(
            503,
            "CLAUDE_AUTH",
            "Claude API 키가 유효하지 않습니다.",
            hint="backend/.env의 ANTHROPIC_API_KEY를 확인하세요.",
        ) from e
    except anthropic.RateLimitError as e:
        raise ApiError(
            429,
            "CLAUDE_RATE_LIMIT",
            "Claude 요청 한도에 도달했습니다.",
            hint="잠시 후 다시 시도해주세요.",
        ) from e
    except anthropic.APIStatusError as e:
        raise ApiError(
            502,
            "CLAUDE_ERROR",
            "Claude 응답을 받지 못했습니다.",
            hint="잠시 후 다시 시도해주세요.",
            details={"status": e.status_code},
        ) from e
    except anthropic.APIConnectionError as e:
        raise ApiError(
            502,
            "CLAUDE_UNREACHABLE",
            "Claude에 연결할 수 없습니다.",
            hint="네트워크 연결을 확인하세요.",
        ) from e

    if resp.stop_reason == "refusal":
        raise ApiError(
            422,
            "CLAUDE_REFUSED",
            "Claude가 이 요청을 처리하지 않았습니다.",
            hint="다른 이미지로 다시 시도해주세요.",
        )
    if resp.stop_reason == "max_tokens":
        raise ApiError(
            502,
            "CLAUDE_TRUNCATED",
            "Claude의 결과가 너무 길어 잘렸습니다.",
            hint="다시 시도해주세요.",
        )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return out.model_validate_json(text)
    except ValidationError as e:
        raise ApiError(
            502,
            "CLAUDE_BAD_OUTPUT",
            "Claude의 결과 형식이 올바르지 않습니다.",
            hint="다시 시도해주세요.",
        ) from e


def _image_block(img: Image.Image, max_edge: int = 1400) -> dict:
    im = img.convert("RGB")
    im.thumbnail((max_edge, max_edge))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(buf.getvalue()).decode(),
        },
    }


# ---- tasks ---------------------------------------------------------------------------

STRUCTURE_SYSTEM = """You review a packaging dieline PDF. The image shows the page; paths that \
need a decision are outlined in orange with numeric labels. For each listed path, suggest \
whether it is a cut line (die-cut outline or slit), crease (fold), printed artwork, or a \
technical annotation (dimensions, notes, marks outside the carton). Printed red or magenta \
artwork exists: only call something a cut if it plausibly separates material. Reasons: one \
short Korean sentence each."""


def suggest_structure(page_image: Image.Image, paths: list[dict]) -> AiStructure:
    content = [
        _image_block(page_image),
        {"type": "text", "text": json.dumps({"paths": paths}, ensure_ascii=False)},
    ]
    return _call(STRUCTURE_SYSTEM, content, AiStructure, effort="medium")


PANELS_SYSTEM = """Name each panel of this unfolded folding carton (Korean, short), e.g. 앞면, \
뒷면, 옆면 좌, 옆면 우, 접착 날개, 윗면 뚜껑, 윗면 꽂이, 아랫면 뚜껑, 먼지 날개. Panels are \
listed with ids and bounding boxes in page points (origin top-left)."""


def name_panels(page_image: Image.Image, panels: list[dict]) -> AiPanels:
    content = [
        _image_block(page_image),
        {"type": "text", "text": json.dumps({"panels": panels}, ensure_ascii=False)},
    ]
    return _call(PANELS_SYSTEM, content, AiPanels)


REFERENCE_SYSTEM = (
    "A packaging designer will put THEIR OWN packaging in place of the packaging in this "
    "reference photo. Read the photo following the guide below exactly: pick the category, "
    "fill all seven of its sections (its keys, in order), read the packaging form, the camera "
    "and the light, and write `prompt_en`.\n\n"
)


def analyze_reference(img: Image.Image) -> AiReference:
    content = [
        _image_block(img, 1568),
        {"type": "text", "text": "Read this reference photo."},
    ]
    return _call(
        REFERENCE_SYSTEM + prompts.text("reference_guide"), content, AiReference, effort="medium"
    )
