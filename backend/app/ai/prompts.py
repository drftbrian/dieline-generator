"""Prompt templates. Every prompt the app sends lives in ``prompts/<name>.md``.

Templates use ``string.Template`` placeholders (``$name``). ``render`` fails loudly when a
placeholder is left unfilled, so a prompt never reaches a model with a hole in it.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from string import Template

DIR = Path(__file__).parent / "prompts"


@cache
def _template(name: str) -> Template:
    return Template((DIR / f"{name}.md").read_text(encoding="utf-8"))


def text(name: str) -> str:
    """A prompt file used as-is (no placeholders), e.g. a system guide."""
    return (DIR / f"{name}.md").read_text(encoding="utf-8")


def render(name: str, **values: str) -> str:
    """``<name>.md`` with every placeholder filled; KeyError names a missing one."""
    return _template(name).substitute(values)
