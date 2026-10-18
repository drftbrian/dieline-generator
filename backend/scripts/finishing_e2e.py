"""End-to-end finishing regression on a real project, run against a COPY of the data folder
(never the real ``backend/data``): gold foil, emboss, combined finishes, save/reload/undo,
a changed and a removed source node, and plates vs preview. No model or Figma calls: the
keys are not loaded and every outline must already be cached in the copy.

    DATA_DIR=/path/to/copy uv run python scripts/finishing_e2e.py PID VERSION_ID OUT_DIR \\
        --logo 23:832 --emboss 27:1296 --uv 27:1292

Writes OUT_DIR/report.json and crops (before / after / plate) for the visual check.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import BACKEND_DIR, Settings, get_settings  # noqa: E402

for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "FIGMA_TOKEN"):
    os.environ.pop(k, None)
Settings.model_config["env_file"] = None  # no keys: nothing here may reach a model or Figma
get_settings.cache_clear()

from fastapi.testclient import TestClient  # noqa: E402

from app.finishing import assets as fa  # noqa: E402
from app.finishing import compose, plates  # noqa: E402
from app.finishing import spec as fspec  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import specs  # noqa: E402
from app.storage import repo  # noqa: E402


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pid")
    ap.add_argument("vid")
    ap.add_argument("out")
    ap.add_argument("--logo", required=True)
    ap.add_argument("--emboss", required=True)
    ap.add_argument("--uv", required=True)
    args = ap.parse_args()
    data = get_settings().data_dir.resolve()
    if data == (BACKEND_DIR / "data").resolve():
        sys.exit("refusing to run on the real data folder: set DATA_DIR to a copy")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pid, vid = args.pid, args.vid
    report: dict = {"project": pid, "version": vid, "scenarios": {}}
    ok = True

    def check(name: str, cond: bool, **info) -> None:
        nonlocal ok
        ok &= bool(cond)
        report["scenarios"].setdefault(current, []).append(
            {"check": name, "pass": bool(cond), **info}
        )
        print(f"  [{'PASS' if cond else 'FAIL'}] {name} {info if info else ''}")

    c = TestClient(create_app())
    pdir = repo.project_dir(pid)
    src_pdf, ver_png = pdir / "source.pdf", pdir / "versions" / f"{vid}.png"
    hashes = {"source.pdf": sha(src_pdf), "version.png": sha(ver_png)}
    svg_hashes = {p.name: sha(p) for p in (pdir / "asset_svg").glob("*.svg")}
    image = np.asarray(Image.open(ver_png).convert("RGB"))
    spec = specs.load(repo.project_or_404(pid))
    rev = c.get(f"/api/projects/{pid}/finishing").json()["revision"]

    def put(assignments):
        nonlocal rev
        r = c.put(
            f"/api/projects/{pid}/finishing",
            json={"base_revision": rev, "assignments": assignments},
        )
        assert r.status_code == 200, r.json()
        rev = r.json()["revision"]
        return r.json()

    def overlay():
        t = time.perf_counter()
        r = c.get(f"/api/projects/{pid}/finishing/preview", params={"version_id": vid})
        dt = time.perf_counter() - t
        x, y, w, h, _, _ = (int(v) for v in r.headers["x-overlay-rect"].split(","))
        ov = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA"))
        full = image.copy()
        if w and h:
            a = ov[..., 3] > 0
            full[y : y + h, x : x + w][a] = ov[..., :3][a]
        return full, (x, y, w, h), dt

    def changed(full):
        return np.abs(full.astype(int) - image.astype(int)).max(-1) > 0

    def mask_of(aid):
        tree = {a["id"]: a for a in fa.project_assets(pid, spec)[1]}
        fin = fspec.FinishingSpec(
            revision=0,
            assignments=[
                fspec.Assignment(finish="foil.gold", targets=[fspec.Target(kind="asset", id=aid)])
            ],
        )
        cc = compose.compose(pid, spec, vid, fin)
        m = np.zeros(image.shape[:2], np.float32)
        y0, x0, y1, x1 = cc.box
        m[y0:y1, x0:x1] = cc.stack[0][2]
        return m, tree[aid]

    def crop(name, full, box, pad=40):
        x, y, w, h = box
        ys, xs = slice(max(0, y - pad), y + h + pad), slice(max(0, x - pad), x + w + pad)
        Image.fromarray(np.hstack([image[ys, xs], full[ys, xs]])).save(out / f"{name}.png")

    # ---- A: gold foil on the vertical logo ------------------------------------------------
    current = "A_gold_foil"
    print(current)
    put([{"id": "fin_A", "finish": "foil.gold", "targets": [{"kind": "asset", "id": args.logo}]}])
    full, box, dt = overlay()
    m, logo = mask_of(args.logo)
    ch = changed(full)
    check(
        "changes only inside the logo's mask", not (ch & (m <= 0)).any(), changed_px=int(ch.sum())
    )
    check("covers the logo's shapes", (ch & (m > 0.5)).sum() >= 0.98 * (m > 0.5).sum())
    check("preview time", True, seconds=round(dt, 2))
    crop("A_gold", full, box)

    # ---- B: emboss on another element -----------------------------------------------------
    current = "B_emboss"
    print(current)
    put(
        [
            {
                "id": "fin_B",
                "finish": "relief.emboss",
                "targets": [{"kind": "asset", "id": args.emboss}],
            }
        ]
    )
    full, box, _ = overlay()
    mb, _ = mask_of(args.emboss)
    ch = changed(full)
    from scipy import ndimage

    ppm = compose.compose(pid, spec, vid, fspec.FinishingSpec()).scale / spec.scale.mm_per_pt
    near = ndimage.distance_transform_edt(mb <= 0) <= (compose.CROP_PAD_MM * ppm)
    check("relief stays on the shape + its shoulder", not (ch & ~near).any())
    lum = full.astype(float).mean(-1) - image.astype(float).mean(-1)
    inside = mb > 0.5
    check(
        "directional light: a lit and a shaded side",
        lum[inside].max() > 3 and lum[inside].min() < -3,
    )
    crop("B_emboss", full, box)

    # ---- C: gold + emboss on the logo, spot UV on a separate asset -----------------------
    current = "C_multiple"
    print(current)
    combo = [
        {
            "id": "fin_C1",
            "finish": "foil.gold",
            "targets": [{"kind": "asset", "id": args.logo}],
            "order": 0,
        },
        {
            "id": "fin_C2",
            "finish": "relief.emboss",
            "targets": [{"kind": "asset", "id": args.logo}],
            "order": 1,
        },
        {
            "id": "fin_C3",
            "finish": "coating.spot_uv",
            "targets": [{"kind": "asset", "id": args.uv}],
            "order": 2,
        },
    ]
    saved = put(combo)
    full, box, dt = overlay()
    mu, _ = mask_of(args.uv)
    ch = changed(full)
    ppm_near = ndimage.distance_transform_edt((m <= 0) & (mu <= 0)) <= compose.CROP_PAD_MM * ppm
    check("unselected artwork untouched", not (ch & ~ppm_near).any(), changed_px=int(ch.sum()))
    check("spot UV area changed", (ch & (mu > 0.5)).any())
    check("preview time (3 finishes)", True, seconds=round(dt, 2))
    crop("C_combined", full, box)
    warns = c.get(f"/api/projects/{pid}/finishing/warnings").json()["warnings"]
    report["warnings_C"] = [(w["code"], w["level"], w["message"]) for w in warns]

    # ---- D: save, reload, undo/redo, remove all ------------------------------------------
    current = "D_save_reload"
    print(current)
    again = c.get(f"/api/projects/{pid}/finishing").json()
    check(
        "reload returns every assignment",
        [a["id"] for a in again["assignments"]] == ["fin_C1", "fin_C2", "fin_C3"],
    )
    check("same revision after reload", again["revision"] == saved["revision"])
    # The client's undo = saving the previous list; redo = saving it again.
    put(combo[:2])
    check(
        "undo (drop spot UV) saved",
        len(c.get(f"/api/projects/{pid}/finishing").json()["assignments"]) == 2,
    )
    put(combo)
    full_redo, _, _ = overlay()
    check("redo restores the same pixels", np.array_equal(full_redo, full))
    put([])
    empty, box0, _ = overlay()
    check("no finishes: preview is empty", box0[2] == 0 and box0[3] == 0)
    check("no finishes: image is the source bit for bit", np.array_equal(empty, image))
    cc = compose.compose(pid, spec, vid, fspec.load(pid))
    check("compose with none == version image", np.array_equal(cc.full(), image))

    # ---- E: a modified and a removed source node -----------------------------------------
    current = "E_source_change"
    print(current)
    put([{"id": "fin_E", "finish": "foil.gold", "targets": [{"kind": "asset", "id": args.emboss}]}])
    _, box_before, _ = overlay()
    svg = fa.svg_path(pid, args.emboss)
    original = svg.read_text()
    # Controlled edit: the same node now draws only its left half (a clip, as Figma exports).
    w_attr = original.split('width="')[1].split('"')[0]
    h_attr = original.split('height="')[1].split('"')[0]
    half = float(w_attr) / 2
    edited = original.replace(
        ">",
        f'><defs><clipPath id="e2e"><rect width="{half}" height="{h_attr}"/></clipPath></defs>'
        '<g clip-path="url(#e2e)">',
        1,
    ).replace("</svg>", "</g></svg>")
    svg.write_text(edited)
    _, box_after, _ = overlay()
    check(
        "edited outline -> new preview (narrower)",
        box_after[2] < box_before[2],
        before=box_before,
        after=box_after,
    )
    svg.write_text(original)
    _, box_back, _ = overlay()
    check("restored outline -> original preview", box_back == box_before)
    tree_file = pdir / fa.TREE_FILE
    tree_text = tree_file.read_text()
    tree_file.write_text(json.dumps([a for a in json.loads(tree_text) if a["id"] != args.emboss]))
    warns = c.get(f"/api/projects/{pid}/finishing/warnings").json()["warnings"]
    check(
        "removed node reported",
        any(w["code"] == "TARGET_MISSING" and w["assignment_id"] == "fin_E" for w in warns),
    )
    _, box_gone, _ = overlay()
    check("removed node: nothing drawn, nothing reattached", box_gone[2] == 0)
    tree_file.write_text(tree_text)

    # ---- F: plates vs preview ---------------------------------------------------------------
    current = "F_export"
    print(current)
    put(
        combo
        + [
            {
                "id": "fin_F",
                "finish": "surface.matte_lamination",
                "targets": [{"kind": "panel", "id": spec.panels[0].id}],
                "order": 3,
            }
        ]
    )
    fin = fspec.load(pid)
    t = time.perf_counter()
    found = plates.compare(pid, spec, vid, fin)
    report["plates_compare_seconds"] = round(time.perf_counter() - t, 2)
    for r in found:
        check(
            f"plate {r['finish']} == preview", r["wrong_px"] == 0 and r["beyond_bleed_px"] == 0, **r
        )
    zr = c.get(f"/api/projects/{pid}/finishing/plates")
    z = zipfile.ZipFile(io.BytesIO(zr.content))
    import pymupdf

    structure = {}
    for name in z.namelist():
        if name.endswith(".pdf"):
            doc = pymupdf.open(stream=z.read(name), filetype="pdf")
            pg = doc[0]
            streams = b"".join(
                doc.xref_stream(x) or b""
                for x in range(1, doc.xref_length())
                if doc.xref_is_stream(x)
            )
            structure[name] = {
                "pages": len(doc),
                # As Illustrator / Acrobat read it: PDF points are 1/72 inch.
                "size_mm": [
                    round(pg.rect.width * 25.4 / 72, 2),
                    round(pg.rect.height * 25.4 / 72, 2),
                ],
                "layers": [o["name"] for o in doc.get_ocgs().values()],
                "drawings": len(pg.get_drawings()),
                "images": len(pg.get_images()),
                "k_fill": b"0 0 0 1 k" in streams,
                "rgb_ops": b" rg" in streams,
            }
    report["plate_pdfs"] = structure
    check(
        "plates carry no layers / guides",
        all(not v["layers"] for k, v in structure.items() if k != "dieline.pdf"),
    )
    check(
        "plates are K, not RGB",
        all(v["k_fill"] and not v["rgb_ops"] for k, v in structure.items() if k != "dieline.pdf"),
    )
    page_mm = [
        round(spec.page.width_pt * spec.scale.mm_per_pt, 2),
        round(spec.page.height_pt * spec.scale.mm_per_pt, 2),
    ]
    check(
        "every PDF is the carton's real size (mm, as a PDF reader measures it)",
        all(
            abs(v["size_mm"][0] - page_mm[0]) < 0.05 and abs(v["size_mm"][1] - page_mm[1]) < 0.05
            for v in structure.values()
        ),
        page_mm=page_mm,
        pdf_mm={k: v["size_mm"] for k, v in structure.items()},
    )
    # A visual: the preview's gold mask (red) over the plate raster (cyan), around the logo.
    gold_plate = plates.plate_coverage(z.read("foil_gold.pdf"), spec, max(image.shape[:2]))
    ys, xs = np.nonzero(m > 0.5)
    sl = (slice(ys.min() - 30, ys.max() + 30), slice(xs.min() - 30, xs.max() + 30))
    vis = np.zeros((*m[sl].shape, 3), np.uint8)
    vis[..., 0] = (m[sl] > 0.5) * 255
    vis[..., 1] = vis[..., 2] = (gold_plate[sl] > 0.5) * 255
    Image.fromarray(vis).save(
        out / "F_gold_plate_vs_preview.png"
    )  # white = both, red/cyan = one only

    # ---- untouched sources -----------------------------------------------------------------
    current = "sources"
    put([])
    check("source PDF unchanged", sha(src_pdf) == hashes["source.pdf"])
    check("version image unchanged", sha(ver_png) == hashes["version.png"])
    check(
        "outlines restored",
        {p.name: sha(p) for p in (pdir / "asset_svg").glob("*.svg")} == svg_hashes,
    )
    report["pass"] = ok
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    print("ALL PASS" if ok else "FAILURES", "->", out / "report.json")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
