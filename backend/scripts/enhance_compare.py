"""Before/after of a post-render AI material enhancement: the v3 source against the enhanced
version, overview plus 100% and 400% crops (small Korean text, wordmark, cut corner, fold line,
gradient transition, plain board), and the extracted light map.

    cd backend && uv run python scripts/enhance_compare.py <project_id> <enhanced_version_id>
        [--out enhance.png] [--data <data dir>]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flat_qa import _crop4, _fit, _label, _sheet  # noqa: E402
from look_compare import _crop1, spots  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pid")
    ap.add_argument("vid")
    ap.add_argument("--out", default="enhance.png")
    ap.add_argument("--data")
    args = ap.parse_args()
    if args.data:
        os.environ["DATA_DIR"] = args.data

    from app.render import shading
    from app.services import pipeline, specs
    from app.spec.models import FLAT_LOOKS
    from app.storage import repo

    pid, vid = args.pid, args.vid
    v = repo.get("versions", vid)
    settings = v["settings_json"]
    src_vid = settings["source_version_id"]
    vdir = repo.project_dir(pid) / "versions"
    after = Image.open(vdir / f"{vid}.png").convert("RGB")
    before = Image.open(vdir / f"{src_vid}.png").convert("RGB")
    maps_vid = settings.get("maps_from") or vid
    spec = specs.load(repo.project_or_404(pid))
    look = FLAT_LOOKS[settings.get("flat_look", "v3")]
    L = pipeline.get_layers(pid, spec, max(after.size), look.lighting.margin)
    parts = shading.render_parts(L, look)

    a = np.asarray(before).astype(np.float32)
    b = np.asarray(after).astype(np.float32)
    lum = lambda x: x @ np.array([0.299, 0.587, 0.114], np.float32)  # noqa: E731
    ratio = (lum(b) + 1) / (lum(a) + 1)
    board = parts.sil >= 0.999
    print(f"size {after.size}  strength {settings['strength']}  maps from {maps_vid}")
    print(f"brightness change on board: min {ratio[board].min():.3f} max {ratio[board].max():.3f}")
    print(f"pixels changed off board: {int((a != b).any(-1)[~board].sum())}")
    print("verify", json.dumps(v["verify_json"], ensure_ascii=False)[:400])

    heat = np.clip((ratio - 0.95) / 0.1, 0, 1) * board
    rows = [
        [
            _label(_fit(before, 900), f"v3 source {src_vid}"),
            _label(_fit(after, 900), f"AI enhanced {vid} (strength {settings['strength']})"),
            _label(
                _fit(Image.fromarray((np.dstack([heat] * 3) * 255).astype(np.uint8)), 900),
                "after / before brightness 0.95..1.05",
            ),
        ]
    ]
    raw = vdir / f"{maps_vid}_raw.png"
    if raw.exists():
        rows[0].append(_label(_fit(Image.open(raw), 600), "raw AI (blank board)"))
    for n, x, y in spots(pid, L, parts):
        rows.append(
            [
                _label(_crop1(before, x, y), f"{n} · v3 100% (shown 2x)"),
                _label(_crop1(after, x, y), f"{n} · AI 100% (shown 2x)"),
                _label(_crop4(before, x, y), f"{n} · v3 400%"),
                _label(_crop4(after, x, y), f"{n} · AI 400%"),
            ]
        )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    _sheet(rows).save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
