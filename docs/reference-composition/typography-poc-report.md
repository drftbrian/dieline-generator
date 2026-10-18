# Typography correction PoC: report (PRD v2 §4A)

**Input:**
- **Raw photo:** the external Flora prototype output (`ZENTRA Packaging Mockup.jpg`,
  3584×4800). It is the "successful ZENTRA benchmark" and is used as the raw AI candidate.
- **Source:** project `prj_3bd9b756ddb2`: the confirmed spec and the Figma tree (69 texts,
  51 vectors).
- **Artwork PDF:** Figma exports text as Type3 outline fonts, so the exact glyphs are embedded.

**No model was called.** The project data was only read.

**Outputs:** local only, because the images contain the user's design and an external
image: `scratchpad/tc/run24/` and `scratchpad/tc/benchmark/`.

## Method

1. **Manifest** (`figma_typography_manifest.json`): 73 items on the panels.
   - **Text:** every text item has its exact Unicode string, Korean included, with font,
     weight, size and colour.
   - **Logos:** each logo is one item (its maximal non-text subtree), not its vector pieces.
   - **Geometry:** for every item it comes from the PDF's embedded outlines, never
     re-typeset. A font that is not embedded and has no outline is `unresolved` and is left as
     generated.
2. **Registration** (`visible_face_registration.json`):
   - Rough corners of the two visible faces (side 옆면 좌 / panel7, front 앞면 / panel8) are
     refined coarse to fine.
   - The fit maximises the gradient correlation between the source panel and the photo,
     counted only near the source's own structure. Shadows, occluders and the model's extra
     marks cannot pull the fit.

   | Face | Corr. before | Corr. after | Corners moved |
   |---|---|---|---|
   | panel7 (side) | 0.28 | **0.94** | 45 px |
   | panel8 (front) | 0.50 | **0.91** | 65 px |

3. **Light:**
   - The photo/source ratio, with everything thinner than a stroke removed by grey
     morphology. Dark marks are held to one stroke width; bright marks to three, because light
     brightens broadly and a watermark is a crisp patch.
   - A hard shadow survives at full depth; a letter, the FLORA mark or the HACCP seal does not.
4. **Verification** (`text_logo_verification.json`):
   - Each item is compared with the prediction using its gradient correlation, its best local
     shift and its residual lettering in glyph cells.
   - Differences that no item explains are *unexpected*: hallucinated text, the FLORA overlay,
     a moved seal.
   - A solid difference where the source has print but the photo shows none of it is an
     **occluder**, never painted over.
5. **Correction:**
   - **`photo_first_text_corrected.png`:** the photo's own paper, modelled from the source
     paper (a per-face colour map plus a smooth residual), plus Figma's lettering as detail.
     The lettering's contrast and hue are matched to the photo's lettering by distribution,
     never by position. Repairs cover the item windows and the unexpected marks; everything
     else is the raw photo, bit for bit.
   - **`strict_artwork.png`:** the whole face is Figma's colours × the photo's light.
   - **Backdrop:** thin bright marks beside the package are removed. The package, its lid
     and its floor contact are never touched.

## Results (ZENTRA benchmark)

**Visual evidence:**
- **Comparison sheet:** `benchmark/zentra_typography.jpg` (raw | text-corrected | strict),
  plus one image per area.
- **Overview:** `benchmark/zentra_typography_overview.jpg`.

| What | Raw (Flora) | Text-corrected / strict |
|---|---|---|
| Front "60g/255kcal" | **"60C/255kcal"**: hallucinated character | "60G/255kcal": Figma glyphs |
| Front HACCP seal | Present on the front with garbled Korean; Figma has it on the *right* side panel | Removed (unexpected content) |
| FLORA overlay | Across both faces and the backdrop | Removed from both faces and the backdrop. A sliver of a few px remains exactly at the box outline. |
| Vertical "zentra" wordmark (front, side sachet) | Model-drawn, close to the original | Figma's logo outline, correct orientation |
| OKRA PINEAPPLE, Korean 젠트라 오크라 파인애플 | Model-drawn, soft, slightly different letterforms | Figma's glyphs, sharp at 400% |
| Nutrient list, sachet small text | Model-drawn, blurred | Figma's glyphs |
| Studio light, gradient, contact shadow | — | Kept. Low-pass luminance change outside removed content is within 0.98–1.02 on both faces. |

**Item verification of the raw image:**
- **No item is a pixel-level match.** Each comes out as "approximate" (logos, sachet) or
  "mismatch" (all text blocks).
- **What "mismatch" means:** the lettering differs from Figma's geometry by more than 1.5
  glyph cells. It does **not** by itself prove a misspelling; that needs OCR.
- **Confirmed by eye:** the misspelling ("60C") and the misplaced seal were checked visually
  in the crops.
- **This supports the hypothesis:** the model never reproduces Figma's letterforms exactly.

**After correction:**
- **Lettering:** every item's gradient correlation with the Figma prediction is 1.0 in both
  outputs.
- **Unexpected marks remaining:** 0.
- **Runtime:** 139 s for the 17-megapixel photo on CPU. The PoC is not optimised.

## Tests

`tests/test_typography.py`: 12 synthetic tests.
- **Source:** a real PDF with embedded Korean and Latin outlines, rotated type, tiny type and
  a non-embedded Helvetica.
- **Photo:** perspective, falling-off light, a hard shadow band, the "model's" misspelling
  ("60C"), reference-brand lettering ("SEREN") and a translucent watermark ("FLORA").

The tests cover:
- the manifest is verbatim (multibyte Korean) and flags missing fonts as `unresolved`;
- registration recovers the face within 2 px from perturbed corners;
- a wrong panel is rejected → `review_required`, nothing written;
- a hallucinated word is flagged `mismatch`; reference lettering and the watermark are
  flagged unexpected; tiny type is `not_verifiable`;
- corrected lettering is the source geometry (correlation > 0.9, Korean and rotated type
  included);
- the shadow band keeps its depth in both outputs (no lifting, no glow);
- pixels outside the repair are the raw photo, bit for bit;
- unresolved type is left as generated;
- an occluder over print is never painted over;
- tiny type becomes verifiable at 3× resolution (the 2K vs 4K case);
- same input gives the same output;
- a backdrop watermark is removed, the package untouched.

## Limitations (honest)

- **Corners are given by hand** for this PoC. Automatic proposals (structural pose / Claude)
  come with M4.
- **Thresholds are calibrated on one real image** plus the synthetic tests. They are not yet a
  validated delivery gate.
- **Planar faces only:**
  - A model that draws a bulging or curved face leaves a small offset near the face edges
    (visible on "DRINK YOUR ZEN", whose lines curve in the raw).
  - Folds, the lid and the bottom flap are not corrected.
- **Hidden paper under removed overlays is a model, not a measurement.** It comes from the
  source's gradient, a colour map and the surrounding photo. Where the model's gradient sits
  far from Figma's (the side face), a faint tonal seam can remain at a repair's edge.
- **Shadow edge sharpness:** a shadow valley narrower than a stroke (a thin sharp line) is
  softened. Wider hard shadows keep their depth.
- **An occluder over plain paper** (no print under it) cannot be told from a shadow. It is
  treated as light, which is harmless because nothing is painted there.
- **Backdrop:** a few-px sliver of an overlay can remain at the package outline.
- **Not done yet:**
  - finishing appearance (foil/UV) in the corrected faces;
  - multi-package photos;
  - integration as a job / UI mode.
