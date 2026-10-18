"""Draw a project's structural topology for review: each panel filled and labelled with its
role, fold edges (hinges) in green, cut contacts between panels in red, issues listed below.

    uv run python scripts/topology_diagram.py SPEC_JSON OUT_PNG
    DATA_DIR=<copy> uv run python scripts/topology_diagram.py --project PID OUT_PNG

``SPEC_JSON`` is a Specification as stored in ``projects.spec_json``. Read-only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.spec.models import Specification  # noqa: E402
from app.structure import carton, topology  # noqa: E402

FONT_CANDIDATES = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
]
ROLE_COLOUR = {
    "W": (225, 236, 250),
    "D": (232, 245, 228),
    "glue": (240, 240, 240),
    "lid": (255, 243, 214),
    "tuck": (255, 230, 200),
    "dust": (245, 232, 250),
    "crash": (255, 220, 220),
}


def _font(size: int):
    for f in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw(spec: Specification, out: Path, long_edge: int = 1800) -> dict:
    top = topology.analyze(spec)
    info = carton.classify(top, spec.box)
    roles: dict[str, str] = dict((info.get("body") or {}).get("roles") or {})
    for e in (info.get("ends") or {}).values():
        if e.get("type") == "crash_lock":
            for f in e["flaps"].values():
                for p in f["panels"]:
                    roles[p] = "crash"
        if e.get("lid"):
            roles[e["lid"]] = "lid"
        if e.get("tuck_flap"):
            roles[e["tuck_flap"]] = "tuck"
        for d in e.get("dust_flaps") or []:
            roles[d] = "dust"
    xs = [x for p in top.panels for poly in p.polygon for x, _ in poly] or [0, 1]
    ys = [y for p in top.panels for poly in p.polygon for _, y in poly] or [0, 1]
    pad = 20
    k = (long_edge - 2 * pad) / max(max(xs) - min(xs), max(ys) - min(ys))
    W = int((max(xs) - min(xs)) * k) + 2 * pad
    H = int((max(ys) - min(ys)) * k) + 2 * pad + 40 + 22 * len(top.issues)

    def P(x, y):
        return (pad + (x - min(xs)) * k, pad + (y - min(ys)) * k)

    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f, small = _font(max(12, int(long_edge / 90))), _font(max(11, int(long_edge / 120)))
    for p in top.panels:
        col = ROLE_COLOUR.get(roles.get(p.id, ""), (250, 250, 250))
        for poly in p.polygon:
            d.polygon([P(x, y) for x, y in poly], fill=col, outline=(120, 120, 120))
    for e in top.folds:
        colour = (20, 150, 60) if e.orientation != "diagonal" else (220, 120, 0)
        d.line([P(*e.p0), P(*e.p1)], fill=colour, width=4)
        mx, my = P((e.p0[0] + e.p1[0]) / 2, (e.p0[1] + e.p1[1]) / 2)
        d.text((mx + 4, my + 2), e.id, fill=colour, font=small)
    for p in top.panels:
        x0, y0, x1, y1 = p.bbox
        cx, cy = P((x0 + x1) / 2, (y0 + y1) / 2)
        label = f"{p.id} {roles.get(p.id, '')}\n{p.name}\n{p.width_mm:.1f}×{p.height_mm:.1f}mm"
        d.multiline_text(
            (cx, cy), label, fill=(20, 20, 20), font=small, anchor="mm", align="center"
        )
    y = int((max(ys) - min(ys)) * k) + 2 * pad
    body = info.get("body") or {}
    head = (
        f"{info.get('family')} / {info.get('style')} / supported={info.get('supported')}  "
        f"W×D×H = {body.get('W_mm')}×{body.get('D_mm')}×{body.get('H_mm')} mm"
    )
    d.text((pad, y), head, fill=(0, 0, 0), font=f)
    for i, iss in enumerate(top.issues):
        d.text(
            (pad, y + 30 + 22 * i),
            f"[{iss.level}] {iss.code}: {iss.message}",
            fill=(160, 0, 0),
            font=small,
        )
    img.save(out)
    return {"topology": top.to_dict(), "carton": info}


def main() -> None:
    args = sys.argv[1:]
    if args[0] == "--project":
        from app.config import Settings, get_settings

        Settings.model_config["env_file"] = None
        get_settings.cache_clear()
        from app.services import specs
        from app.storage import repo

        spec = specs.load(repo.project_or_404(args[1]))
        out = Path(args[2])
    else:
        spec = Specification.model_validate(json.loads(Path(args[0]).read_text()))
        out = Path(args[1])
    result = draw(spec, out)
    out.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(out, result["carton"]["style"], "ok" if result["topology"]["ok"] else "errors")


if __name__ == "__main__":
    main()
