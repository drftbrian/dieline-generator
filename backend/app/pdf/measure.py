"""Real-world scale from dimension markings ("100mm" next to a 375-unit line).

PDF units are only physical when the file was made for print. Design-tool exports (Figma:
1 px -> 1 pt) are not, so a 100 mm panel can come out as 132 mm. Dimension markings the
designer already drew are the most reliable ruler: each label + line pair gives units/mm,
and several agreeing pairs give a confident scale.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

PT_TO_MM = 25.4 / 72
DIM_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(mm|㎜|cm)\s*$", re.IGNORECASE)
BOX_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[*x×X]\s*(\d+(?:\.\d+)?)\s*[*x×X]\s*(\d+(?:\.\d+)?)")


@dataclass
class Label:
    mm: float
    text: str
    bbox: tuple[float, float, float, float]

    @property
    def center(self) -> tuple[float, float]:
        return ((self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2)


@dataclass
class Segment:
    a: tuple[float, float]
    b: tuple[float, float]

    @property
    def length(self) -> float:
        return math.dist(self.a, self.b)


@dataclass
class Scale:
    mm_per_unit: float
    confidence: float
    evidence: list[str]


def parse_label(text: str, bbox) -> Label | None:
    m = DIM_RE.match(text.replace("\n", " "))
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    return Label(value * (10 if m.group(2).lower() == "cm" else 1), text.strip(), tuple(bbox))


def parse_box(texts: list[str]) -> tuple[float, float, float] | None:
    """'100*52*141' -> (100, 52, 141), as written on the artboard (W x D x H, mm)."""
    for t in texts:
        m = BOX_RE.search(t)
        if m:
            return tuple(float(v) for v in m.groups())  # type: ignore[return-value]
    return None


def _distance(p, s: Segment) -> tuple[float, float]:
    """(distance from p to the segment's line, projection parameter t along the segment)."""
    (x0, y0), (x1, y1) = s.a, s.b
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy or 1e-9
    t = ((p[0] - x0) * dx + (p[1] - y0) * dy) / L2
    px, py = x0 + t * dx, y0 + t * dy
    return math.dist(p, (px, py)), t


def scale_from_marks(labels: list[Label], segments: list[Segment]) -> Scale | None:
    """Pair each dimension label with the nearest long line it sits beside."""
    ratios: list[float] = []
    evidence: list[str] = []
    long = [s for s in segments if s.length >= 20]
    for lab in labels:
        best = None
        for s in long:
            d, t = _distance(lab.center, s)
            if -0.05 <= t <= 1.05 and d <= max(30.0, 0.15 * s.length):
                if best is None or d < best[0]:
                    best = (d, s)
        if best and lab.mm > 0:
            ratios.append(best[1].length / lab.mm)
            evidence.append(f"'{lab.text}' ↔ 선 {best[1].length:.0f}")
    if not ratios:
        return None
    ratios.sort()
    median = ratios[len(ratios) // 2]
    spread = max(abs(r / median - 1) for r in ratios)
    if len(ratios) >= 2 and spread < 0.03:
        confidence = 0.95
    elif len(ratios) == 1:
        confidence = 0.75
    else:
        confidence = 0.6
    return Scale(1 / median, confidence, evidence)
