"""Figma-driven typography correction (PRD v2 §4A) on synthetic generated photos.

A source panel (a real PDF with embedded Korean/Latin outlines, rotated type, tiny type and a
non-embedded font) is warped into a "photo" with perspective, smooth studio light and a dark
shadow band; the "model" then misspells a word, adds reference-brand lettering and a faint
watermark. No model is called anywhere.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pymupdf
import pytest
from PIL import Image, ImageDraw

from app.typography import manifest, restore
from app.typography import register as rg

PANEL = (0.0, 0.0, 300.0, 420.0)  # page points
QUAD = np.array([[210.0, 120.0], [610.0, 150.0], [600.0, 760.0], [220.0, 800.0]])
SIZE = (820, 900)  # photo w, h
SHADOW = (430, 520)  # photo rows of a dark band across the face


def _pdf(word: str = "60g/255kcal", extra: str | None = None, helv: bool = True) -> bytes:
    doc = pymupdf.open()
    p = doc.new_page(width=PANEL[2], height=PANEL[3])
    for i in range(42):  # a yellow-to-grey gradient
        t = i / 41
        p.draw_rect(pymupdf.Rect(0, i * 10, 300, i * 10 + 10), color=None,
                    fill=(0.85 - 0.1 * t, 0.85 - 0.05 * t, 0.35 + 0.45 * t))
    p.insert_font(fontname="kr", fontbuffer=pymupdf.Font("korea").buffer)
    p.insert_text((24, 60), "OKRA PINEAPPLE", fontname="kr", fontsize=26, color=(1, 1, 1))
    p.insert_text((24, 96), "젠트라 오크라 파인애플", fontname="kr", fontsize=20, color=(1, 1, 1))
    p.insert_text((250, 390), "zentra", fontname="kr", fontsize=56, rotate=90, color=(1, 1, 1))
    p.insert_text((24, 330), word, fontname="kr", fontsize=22, color=(1, 1, 1))
    p.insert_text((24, 400), "tiny regulatory copy", fontname="kr", fontsize=4.5, color=(1, 1, 1))
    if helv:
        p.insert_text((24, 160), "Helv", fontname="helv", fontsize=22, color=(1, 1, 1))
    if extra:
        p.insert_text((40, 250), extra, fontname="kr", fontsize=30, color=(1, 1, 1))
    return doc.tobytes()


def _assets(pdf: bytes) -> list[dict]:
    out = []
    page = pymupdf.open(stream=pdf, filetype="pdf")[0]
    for b in page.get_text("dict")["blocks"]:
        for line in b.get("lines", []):
            for s in line["spans"]:
                if s["text"].strip():
                    out.append({"id": f"t{len(out)}", "kind": "text", "type": "TEXT", "text": s["text"],
                                "font": s["font"], "size": s["size"], "bbox": list(s["bbox"]),
                                "parent": None, "children": [], "selectable": True})
    return out


def _spec():
    panel = SimpleNamespace(id="front", name="앞면", bbox=PANEL, width_mm=100.0, height_mm=140.0)
    return SimpleNamespace(panels=[panel], scale=SimpleNamespace(mm_per_pt=1 / 3), version=1)


def _photo(pdf: bytes, quad=QUAD, shadow=True, overlay: str | None = None, occluder=False, scale=1.0):
    """Warp the panel print into a studio photo: grey backdrop, light falling off to the right,
    an optional dark band, an optional faint white watermark and a dark occluder."""
    w, h = int(SIZE[0] * scale), int(SIZE[1] * scale)
    q = np.asarray(quad, float) * scale
    tex = restore.render_panel(pdf, PANEL, (900, 1260))
    H = rg.homography(q)
    xs, ys = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
    u, v = rg.apply_h(np.linalg.inv(H), xs, ys)
    inside = (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
    img = np.ones((h, w, 3), np.float32) * np.array([0.72, 0.70, 0.68], np.float32)
    sampled = rg.sample(tex, u * tex.shape[1], v * tex.shape[0])
    light = (1.0 - 0.25 * xs / w)[..., None]
    if shadow:
        # A hard shadow: a flat dark core with soft 10 px edges.
        band = 1 - 0.45 * np.clip((45 * scale - np.abs(ys - sum(SHADOW) * scale / 2)) / (10 * scale), 0, 1)
        light = light * band[..., None]
    img = np.where(inside[..., None], sampled * light * np.array([1.0, 0.97, 0.92]), img)
    out = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
    if overlay:
        layer = Image.new("L", out.size, 0)
        ImageDraw.Draw(layer).text((int(260 * scale), int(600 * scale)), overlay, fill=255,
                                   font_size=int(70 * scale))
        a = np.asarray(layer, np.float32)[..., None] / 255 * 0.35
        arr = np.asarray(out, np.float32) / 255
        out = Image.fromarray((np.clip(arr * (1 - a) + a, 0, 1) * 255).astype(np.uint8))
    arr = np.asarray(out, np.float32) / 255
    if occluder:
        arr = arr.copy()
        arr[int(580 * scale) : int(700 * scale), int(440 * scale) : int(580 * scale)] = 0.12  # over the wordmark
    return arr


def _run(photo: np.ndarray, src_pdf: bytes, quad0=QUAD):
    items = manifest.build(_spec(), _assets(src_pdf), src_pdf, lambda _i: False)["items"]
    tex = restore.render_panel(src_pdf, PANEL, (300, 420))
    reg = rg.refine("front", rg.luminance(photo), rg.luminance(tex), quad0)
    src = restore.face_source(src_pdf, "front", "앞면", PANEL, reg.quad, items)
    res, layers = restore.correct_face(photo, reg, src, items)
    return items, reg, src, res, layers


@pytest.fixture(scope="module")
def scene():
    source = _pdf()
    raw = _photo(_pdf(word="60C/255kcal", extra="SEREN"), overlay="FLORA")
    items, reg, src, res, layers = _run(raw, source, QUAD + [[9, -7], [-8, 10], [11, 6], [-6, -9]])
    corrected, mask = restore.composite(raw, reg.H, *layers["text_corrected"])
    strict, smask = restore.composite(raw, reg.H, *layers["strict"])
    return SimpleNamespace(source=source, raw=raw, items=items, reg=reg, src=src, res=res,
                           corrected=corrected, mask=mask, strict=strict, smask=smask)


def _by_text(s, text):
    return next(v for v in s.res.items if v["text"] == text)


def test_manifest_is_verbatim_and_flags_missing_fonts():
    pdf = _pdf()
    m = manifest.build(_spec(), _assets(pdf), pdf, lambda _i: False)
    by = {i["text"]: i for i in m["items"]}
    assert "젠트라 오크라 파인애플" in by  # multibyte Korean kept exactly
    assert by["zentra"]["geometry"] == "pdf_outline"  # rotated, embedded outlines
    assert by["OKRA PINEAPPLE"]["role"] == "hero"
    assert by["tiny regulatory copy"]["role"] == "regulatory"
    assert by["Helv"]["geometry"] == "unresolved"  # base-14 font: not embedded, never re-typeset
    assert m["unresolved"] == [by["Helv"]["id"]]
    assert by["OKRA PINEAPPLE"]["panel_id"] == "front"
    assert by["OKRA PINEAPPLE"]["panel_mm"][0] == pytest.approx(24 / 3, abs=0.5)


def test_registration_recovers_the_face(scene):
    assert scene.reg.ok
    assert np.abs(scene.reg.quad - QUAD).max() < 2.0
    assert scene.reg.ncc > scene.reg.ncc_initial


def test_registration_rejects_a_wrong_panel():
    other = pymupdf.open()
    p = other.new_page(width=300, height=420)
    for i in range(30):
        p.draw_rect(pymupdf.Rect(i * 10, 0, i * 10 + 5, 420), color=None, fill=(0.1, 0.4, 0.2))
    photo = _photo(other.tobytes(), shadow=False)
    _items, reg, _src, res, layers = _run(photo, _pdf())
    assert not reg.ok and layers is None
    assert any("registration rejected" in r for r in res.review)


def test_verification_flags_hallucinated_reference_and_watermark_text(scene):
    assert _by_text(scene, "60g/255kcal")["status"] == "mismatch"
    assert _by_text(scene, "OKRA PINEAPPLE")["status"] in ("match", "approximate")
    assert _by_text(scene, "tiny regulatory copy")["status"] == "not_verifiable"
    assert _by_text(scene, "Helv")["status"] == "unresolved"
    # SEREN (reference lettering) and the FLORA watermark are content no source item explains.
    h, w = scene.src.rgb.shape[:2]
    boxes = [u["bbox_px"] for u in scene.res.unexpected]
    seren_y = 250 / 420 * h
    assert any(b[1] <= seren_y <= b[3] for b in boxes)
    assert all(not u["large"] for u in scene.res.unexpected)


def _panel_ncc(img, s, text):
    v = _by_text(s, text)
    x0, y0, x1, y1 = v["window_px"]
    want = rg.luminance(s.src.rgb)[y0:y1, x0:x1]
    got = rg.luminance(rg.to_panel(img, s.reg.H, s.src.rgb.shape[:2]))[y0:y1, x0:x1]
    return restore._gncc(got, want)


def test_corrected_lettering_is_the_source_geometry(scene):
    for text in ("60g/255kcal", "OKRA PINEAPPLE", "zentra", "젠트라 오크라 파인애플"):
        assert _panel_ncc(scene.corrected, scene, text) > 0.9
    assert _panel_ncc(scene.corrected, scene, "60g/255kcal") > _panel_ncc(scene.raw, scene, "60g/255kcal") + 0.3
    assert scene.res.after["text_corrected"]["remaining_unexpected"] == 0
    assert scene.res.after["strict"]["item_ncc_min"] > 0.95


def test_shadows_stay_dark_and_nothing_glows(scene):
    lum = rg.luminance
    mid = sum(SHADOW) // 2
    core, above = slice(mid - 8, mid + 8), slice(SHADOW[0] - 70, SHADOW[0] - 40)
    cols = slice(250, 300)  # plain paper left of the lettering

    def depth(img):
        return lum(img)[core, cols].mean() / lum(img)[above, cols].mean()

    assert depth(scene.raw) < 0.75  # the photo has a deep shadow band
    for out in (scene.corrected, scene.strict):
        assert depth(out) == pytest.approx(depth(scene.raw), abs=0.05)  # kept, not lifted
    for mode in ("text_corrected", "strict"):
        assert scene.res.after[mode]["shading"]["preserved"]
    assert not any(u["large"] for u in scene.res.unexpected)  # a shadow is light, not content


def test_outside_the_repair_the_photo_is_untouched(scene):
    same = scene.mask == 0
    assert same.any()
    assert np.array_equal(scene.corrected[same], scene.raw[same])
    assert np.array_equal(scene.strict[scene.smask == 0], scene.raw[scene.smask == 0])


def test_unresolved_type_is_left_as_generated(scene):
    v = _by_text(scene, "Helv")
    item = next(i for i in scene.items if i["text"] == "Helv")
    x0, y0, x1, y1 = restore._window(item, PANEL, scene.src.px_per_pt, scene.src.rgb.shape[:2])
    assert scene.src.unresolved[y0:y1, x0:x1].all()
    assert v["status"] == "unresolved"
    assert any("unavailable glyph outlines" in r for r in scene.res.review)


def test_an_occluder_is_never_painted_over():
    raw = _photo(_pdf(), occluder=True)
    _items, reg, _src, res, layers = _run(raw, _pdf())
    assert any(u["large"] for u in res.unexpected)
    out, _m = restore.composite(raw, reg.H, *layers["text_corrected"])
    assert np.array_equal(out[585:695, 445:575], raw[585:695, 445:575])
    assert any("large difference" in r for r in res.review)


def test_tiny_type_becomes_verifiable_at_higher_resolution():
    pdf = _pdf()
    small = _run(_photo(pdf, shadow=False), pdf)[3]
    big = _run(_photo(pdf, shadow=False, scale=3.0), pdf, QUAD * 3.0)[3]
    status = lambda r: next(v for v in r.items if v["text"] == "tiny regulatory copy")["status"]  # noqa: E731
    assert status(small) == "not_verifiable"
    assert status(big) != "not_verifiable"


def test_same_input_same_output(scene):
    _items, reg, _src, _res, layers = _run(scene.raw, scene.source, QUAD + [[9, -7], [-8, 10], [11, 6], [-6, -9]])
    again, _m = restore.composite(scene.raw, reg.H, *layers["text_corrected"])
    assert np.array_equal(again, scene.corrected)


def test_backdrop_watermark_is_removed_and_the_package_kept():
    raw = _photo(_pdf(), shadow=False)
    img = Image.fromarray((raw * 255).astype(np.uint8))
    ImageDraw.Draw(img).text((640, 300), "FLORA", fill=(235, 235, 235), font_size=40)
    raw = np.asarray(img, np.float32) / 255
    out, mask, rep = restore.clean_background(raw, [QUAD])
    assert mask[300:345, 645:780].max() > 0.9
    assert rep["removed_fraction"] < 0.05
    face = np.zeros(raw.shape[:2], bool)
    face[200:700, 300:500] = True
    assert np.array_equal(out[face], raw[face])
