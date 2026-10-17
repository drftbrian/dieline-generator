"""Every AI model identifier lives here so upgrades are a one-line change.

Verified on 2026-10-16:
- Gemini: "Nano Banana 2.1" = ``gemini-nano-banana-2.1`` (ai.google.dev model list, GA)
- Claude: ``claude-opus-5-5``
"""

from dataclasses import dataclass

CLAUDE_MODEL = "claude-opus-5-5"


@dataclass(frozen=True)
class ImageModel:
    provider: str
    label: str
    model_id: str
    eta_s: int


IMAGE_MODEL = ImageModel("gemini", "Nano Banana 2.1", "gemini-nano-banana-2.1", 40)
