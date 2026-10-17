"""Provider requests: prompt and labelled images in order, at 2K (no network)."""

import io
from types import SimpleNamespace

from PIL import Image
from pydantic import SecretStr

from app.ai.providers import gemini
from app.ai.providers.base import GenerationRequest


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "PNG")
    return buf.getvalue()


def _fake_gemini(monkeypatch) -> dict:
    seen = {}

    class Models:
        def generate_content(self, model, contents, config):
            seen["contents"], seen["config"] = contents, config
            part = SimpleNamespace(inline_data=SimpleNamespace(data=_png_bytes()))
            cand = SimpleNamespace(content=SimpleNamespace(parts=[part]))
            return SimpleNamespace(candidates=[cand], usage_metadata=None)

    monkeypatch.setattr(gemini.genai, "Client", lambda api_key: SimpleNamespace(models=Models()))
    monkeypatch.setattr(
        gemini, "get_settings", lambda: SimpleNamespace(gemini_api_key=SecretStr("k"))
    )
    return seen


def test_gemini_asks_for_2k_at_the_frame_aspect(monkeypatch):
    seen = _fake_gemini(monkeypatch)
    gemini.GeminiProvider().generate(GenerationRequest("p", [], 2048, 1536), "m")
    cfg = seen["config"].image_config
    assert cfg.image_size == "2K" and cfg.aspect_ratio == "4:3"
    assert gemini.nearest_ratio(1900, 1000) == "16:9" and gemini.nearest_ratio(1000, 1000) == "1:1"


def test_gemini_contents_are_prompt_then_label_image_pairs(monkeypatch):
    seen = _fake_gemini(monkeypatch)
    a = Image.new("RGB", (64, 48), (200, 0, 0))
    b = Image.new("RGB", (32, 32), (0, 200, 0))
    req = GenerationRequest("the prompt", [("Image A:", a), ("Image B:", b)], 1024, 768)
    gemini.GeminiProvider().generate(req, "m")
    assert seen["contents"][0] == "the prompt"
    assert seen["contents"][1:] == ["Image A:", a, "Image B:", b]
