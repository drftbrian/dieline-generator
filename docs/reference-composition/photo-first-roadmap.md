# Photo-first reconstruction: roadmap

**PRD:** `docs/prd/reference-photo-first-reconstruction.md` (v2, with §4A "Figma-Driven Typography
Fidelity").

**Branch:** `feat/reference-photo-first-v2`, from `feat/multi-instance-reference-composition`.

**Not merged.**

## The hypothesis (§4A)

A generative model (the Flora prototype, Gemini) gives the best photographic realism, but it
redraws every letter. Our app holds the authoritative source in Figma: exact strings, fonts,
glyph outlines, logo vectors and panel coordinates. Combining the two should give Flora-level
realism with Figma-level lettering.

**The method:** the model makes the photo; we register the visible faces and put Figma's own
glyphs back under the photo's own light. Exact text in the prompt alone does not guarantee
this, so the method never relies on it.

## Order of work

The user asked for the typography proof of concept first, on the existing successful
benchmark, before the rest. The milestones of PRD §10 stay; §4A is distributed over them.

| Milestone | Scope | §4A part | Status |
|---|---|---|---|
| **PoC** (pulled ahead of M4) | Typography correction on the existing Flora ZENTRA image. No model call. | manifest, registration, verification, text-corrected + strict outputs, quality report, 400% crops | **done**, see `typography-poc-report.md` |
| M0 | Audit of legacy ③ / structural ③ raw vs final; fixture manifests | — | open |
| M1 | Real two-image call (reference + flat ZENTRA) with a role-aware prompt; raw output saved | raw candidate kept (`model_raw.png`) | open: needs a paid model call, user's go-ahead |
| M2 | Photography-only reference schema, Figma panel manifest, prompt compiler | `figma_typography_manifest.json` feeds the prompt with hero copy only | open |
| M3 | Step ③ UI: photo-first mode, progress, raw vs final, regenerate | mode switch `photo_first` / `photo_first_text_corrected` / `strict_artwork` | open |
| M4 | Typography correction inside the job pipeline | registration from the structural pose (M3 fold) + corner refinement; corrected/strict saved as separate versions; quality gate → `review_required` | PoC done; integration open |
| M5 | Multi-instance, finishing, cancellation, cost, README | per-instance registration (reuse `scene` quads) | open |

## What the PoC adds to the architecture

These modules work on any generated photo; nothing in step ① or ② changes.

- **`app/typography/manifest.py`:** the text and logo manifest. For each item it records:
  - the exact string;
  - font, weight and size;
  - its panel and its millimetre position on that panel;
  - its role;
  - where its glyph geometry comes from: embedded outlines, an SVG outline, or `unresolved`.
- **`app/typography/register.py`:** visible-face registration. It refines a homography by
  correlating gradients only where the source has structure.
- **`app/typography/restore.py`:** light, verification, unexpected content and occluders,
  repair masks, the text-corrected and strict composites, backdrop overlays, quality checks.
- **`scripts/typography_poc.py`:**
  - writes every §4A output file to a folder outside `backend/data`;
  - only reads the project;
  - makes no model call.

## Open decisions for later milestones

- **Corners:**
  - **Now:** given by hand (the scene corner editor already supports this).
  - **In M4:** they come from the structural fold pose or from Claude's detection, refined
    automatically.
- **Thresholds:**
  - **Correlation scores** (`MATCH_NCC`, `APPROX_NCC`, `WRONG_GLYPHS`): calibrated on one
    real image and the synthetic tests only.
  - **Overlay detection** (`OVERLAY_*`): same calibration.
  - **What's needed:** more real model outputs before they can gate deliveries.
- **Default output in the UI:** text-corrected or strict, to be chosen after a review of real
  runs.
