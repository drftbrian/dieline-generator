"""Google Gemini image models (Nano Banana family)."""

from __future__ import annotations

import io

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from PIL import Image

from app.ai.providers.base import GenerationRequest, GenerationResult
from app.config import get_settings
from app.errors import ApiError


def _quota_error(e: genai_errors.ClientError) -> ApiError:
    """429 RESOURCE_EXHAUSTED: a free-tier key (limit 0 for image models) or a rate limit."""
    text = str(getattr(e, "message", "") or e)
    if "free_tier" in text and "limit: 0" in text:
        return ApiError(
            402,
            "PROVIDER_BILLING_REQUIRED",
            "이 Gemini API 키는 무료 등급이라 Nano Banana를 쓸 수 없습니다.",
            hint="Google AI Studio에서 이 키의 프로젝트에 결제(유료 등급)를 연결하면 바로 쓸 수 있어요.",
            details={"status": 429, "provider_message": text[:300]},
        )
    return ApiError(
        429,
        "PROVIDER_RATE_LIMIT",
        "Gemini 사용 한도에 도달했습니다.",
        hint="잠시 후 다시 시도해주세요.",
        details={"status": 429, "provider_message": text[:300]},
    )


RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]


def nearest_ratio(w: int, h: int) -> str:
    """Gemini's supported aspect ratio closest to the requested frame."""
    import math

    target = math.log(w / h)
    return min(
        RATIOS, key=lambda r: abs(math.log(int(r.split(":")[0]) / int(r.split(":")[1])) - target)
    )


class GeminiProvider:
    name = "gemini"

    def available(self) -> bool:
        return get_settings().gemini_api_key is not None

    def generate(self, req: GenerationRequest, model_id: str) -> GenerationResult:  # noqa: C901
        key = get_settings().gemini_api_key
        if key is None:
            raise ApiError(
                503,
                "PROVIDER_UNAVAILABLE",
                "Gemini API 키가 설정되지 않았습니다.",
                hint="backend/.env에 GEMINI_API_KEY를 추가하세요.",
            )
        client = genai.Client(api_key=key.get_secret_value())
        contents: list = [req.prompt]
        for label, img in req.images:
            contents += [label, img]
        try:
            resp = client.models.generate_content(
                model=model_id,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    # 2K: fine board ribs and fibres only exist at this resolution.
                    image_config=types.ImageConfig(
                        image_size="2K", aspect_ratio=nearest_ratio(req.width, req.height)
                    ),
                ),
            )
        except genai_errors.ClientError as e:
            if getattr(e, "code", None) == 429:
                raise _quota_error(e) from e
            if getattr(e, "code", None) == 402:
                raise ApiError(
                    402,
                    "PROVIDER_BILLING_REQUIRED",
                    "Gemini 계정의 결제(크레딧)가 필요합니다.",
                    hint="Google AI Studio → Billing에서 이 API 키 프로젝트의 결제 수단이나 "
                    "선불 크레딧 잔액을 확인하세요.",
                    details={"status": 402, "provider_message": str(e)[:300]},
                ) from e
            raise ApiError(
                502,
                "PROVIDER_REJECTED",
                "Gemini가 요청을 거절했습니다.",
                hint="다른 레퍼런스로 다시 시도해주세요.",
                details={"status": getattr(e, "code", None)},
            ) from e
        except genai_errors.ServerError as e:
            raise ApiError(
                502,
                "PROVIDER_ERROR",
                "Gemini 응답을 받지 못했습니다.",
                hint="잠시 후 다시 시도해주세요.",
            ) from e

        for cand in resp.candidates or []:
            for part in (cand.content.parts if cand.content else []) or []:
                if part.inline_data and part.inline_data.data:
                    img = Image.open(io.BytesIO(part.inline_data.data)).convert("RGB")
                    usage = {}
                    if resp.usage_metadata:
                        usage = {
                            "input_tokens": resp.usage_metadata.prompt_token_count,
                            "output_tokens": resp.usage_metadata.candidates_token_count,
                        }
                    return GenerationResult(img, usage)
        raise ApiError(
            502,
            "PROVIDER_NO_IMAGE",
            "Gemini가 이미지를 반환하지 않았습니다.",
            hint="다시 시도해주세요.",
        )
