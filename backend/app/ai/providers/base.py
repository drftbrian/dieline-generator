"""Image-provider interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image


@dataclass
class GenerationRequest:
    prompt: str
    images: list[tuple[str, Image.Image]]  # (label, image), sent in this order after the prompt
    width: int
    height: int


@dataclass
class GenerationResult:
    image: Image.Image
    usage: dict = field(default_factory=dict)


class ImageProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def generate(self, req: GenerationRequest, model_id: str) -> GenerationResult: ...
