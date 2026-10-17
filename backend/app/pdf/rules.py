"""Layer / spot-color naming rules for separation detection.

One table shared by detection and the upload guide copy. Names are compared after
lower-casing and stripping spaces, dashes and underscores.
"""

import re

from app.spec.models import PathClass

RULES: dict[PathClass, list[str]] = {
    "cut": [
        "die",
        "dieline",
        "redline",
        "레드라인",
        "다이라인",
        "diecut",
        "cut",
        "cutline",
        "cutcontour",
        "cutter",
        "thrucut",
        "칼선",
        "재단",
        "재단선",
        "도무송",
    ],
    "crease": [
        "crease",
        "creaseline",
        "fold",
        "foldline",
        "score",
        "scoring",
        "perf",
        "perforation",
        "접는선",
        "오시",
        "접지",
        "접지선",
    ],
    "finish": [
        "spotuv",
        "uv",
        "varnish",
        "gloss",
        "white",
        "whiteink",
        "foil",
        "hotfoil",
        "emboss",
        "deboss",
        "화이트",
        "백색",
        "박",
        "형압",
        "에폭시",
        "부분코팅",
    ],
    "annotation": [
        "info",
        "dimension",
        "dimensions",
        "dim",
        "guide",
        "guides",
        "technical",
        "notes",
        "slug",
        "registration",
        "치수",
        "치수선",
        "measure",
        "measurement",
        "size",
        "사이즈",
        "가이드",
        "주석",
        "정보",
    ],
    "bleed": ["bleed", "블리드", "도련"],
}

# Recommended names shown in the upload guide.
RECOMMENDED = {"cut": "Die", "crease": "Crease", "finish": "SpotUV / White"}


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_./]+", "", s.lower())


def match(name: str) -> PathClass | None:
    n = _norm(name)
    if not n:
        return None
    for cls, words in RULES.items():
        if n in words:
            return cls
    # Prefix matches like "Die_Line_01", "Cut Contour 2", "SpotUV-front"
    for cls, words in RULES.items():
        if any(len(w) >= 3 and n.startswith(w) for w in words):
            return cls
    return None
