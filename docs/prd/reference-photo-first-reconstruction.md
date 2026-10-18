# PRD + Implementation Command — Reference-Guided Folded Packaging Photography
**Project:** Dieline Generator  
**Feature:** Reference Photo → Figma Dieline → Photorealistic Folded Package  
**Proposed branch:** `feat/reference-photo-first-v2`  
**Status:** Implementation specification / benchmark-driven work / typography-fidelity revision

## 0. EXECUTIVE IMPLEMENTATION COMMAND

You are Claude Code working in `https://github.com/drftbrian/dieline-generator`.

**Do not implement another generic “place a 3D mesh into a background” system as the sole solution.** The user has demonstrated a successful *multimodal, prompt-driven* prototype: (1) a product photography reference, (2) a detailed structured analysis of its photographic presentation, (3) an exact flat ZENTRA dieline image, (4) a dynamic reconstruction-and-photography prompt, (5) a multimodal image-generation call using the reference photograph and flat dieline together. The output is the product-quality target.

Your task is to reproduce this workflow inside the existing ③ 레퍼런스 합성 page while preserving the approved Figma source and retaining structural/strict fallback modes. **Make output quality comparable to the supplied ZENTRA target photo the primary acceptance criterion.** Implement an end-to-end vertical slice and prove its output before investing in a general system.

Create a new branch safely from the actual latest working integration branch. Inspect uncommitted changes. Preserve all existing flat-render, finishing, legacy merge, and structural composition features. Do not automatically merge into main.

## 1. PRODUCT PROBLEM & NORTH STAR

### Problem
The current app can render a precise unfolded carton, but the reference-composition results are far below the attached external node-workflow example. Existing implementations over-constrain the generated result, rely on insufficient image-model context, reconstruct a visually bland 3D proxy, use contradictory composition instructions, or apply subsequent compositing that washes out realistic lighting and printed shadows. These are hypotheses, **not established root causes**; confirm by auditing the actual code and raw generation artifacts.

### North-star experience
The user uploads a POSITIVE HOTEL-style studio photo of a beige upright package and selects an approved flat ZENTRA OKRA PINEAPPLE dieline. The resulting image is a single, realistic **folded, standing ZENTRA carton**, positioned, scaled and lit like the reference photograph. It shows the correct hero/front panel with vertical `zentra`, and the sachet-illustration side panel if geometrically visible. It reproduces ZENTRA’s gradient, visual hierarchy, text, logo, panel arrangement and carton proportions as faithfully as possible. The reference package’s branding/ink color are not copied. No extraneous watermark, pseudo-brand (“FLORA”), ghosted lettering or generated overlay may remain.

The uploaded external example image is a **visual target**, not verified proof of typography fidelity: the provided target itself includes a large unwanted translucent FLORA-like mark. Do not treat that mark as acceptable output.

### Core invariant
- **Reference photo controls HOW the product is photographed:** framing, pose, perspective, placement, backdrop, lighting, shadow, lens feel, scale, editorial quality.
- **Approved Figma + confirmed dieline controls WHAT the product is:** its physical dimensions/topology, which panel is front/side/back, colors/graphics/text, and applied finishing.
- **Image model generates the creative photographic realization.** Unlike the existing strictly limited illumination-only pipeline, it must be allowed to synthesize the **folded package view** in *photo-first mode*. This inherently carries some text-fidelity risk, so add verification and an optional strict artwork-protection path; do not claim that prompts alone guarantee pixel-perfect text.

### Not in scope for v1
- Manufacture-certified 3D CAD reconstruction for all dieline topologies
- Guaranteed pixel-exact text in raw generative output
- Automatic reliable extraction of arbitrary hidden rear faces
- Mandatory 3D mesh stage before every generation
- Redesigning the existing flat renderer / finishing studio

## 2. INPUTS, DATA AUTHORITY & OUTPUTS

Input A — **reference photograph** (attached POSITIVE HOTEL studio shot in benchmark). Detect reference object(s), scene and photographic attributes. Its product branding/graphics/geometry are not the source for our carton.

Input B — **approved ZENTRA flat dieline render** (or another selected Figma-derived package). Pass actual image bytes to the multimodal image provider; do not replace with a textual description. Retain source resolution and aspect ratio; only downsample to an explicit, documented provider limit. No crop that loses flaps, panels, or text.

Input C — **structured Figma specification**: confirmed cut/fold lines, panel geometry, actual dimensions, front/side/back semantic mapping, artwork transforms, source text, logo/vector masks, approved finish metadata, version id. This **augments**, not replaces, Input B.

Optional Input D — transparent structural guide or folded preview if the provider supports additional images. This is advisory; do not force the model to copy a low-quality rigid proxy. Test whether it improves results.

Outputs (save each separately):
1. `reference_scene_analysis.json`
2. `package_panel_manifest.json`
3. `generation_prompt.md`
4. `generation_payload_manifest.json` (image roles, dimensions, image order, model/settings; no credentials)
5. `model_raw.png`
6. `quality_report.json`
7. `final_concept.png` (or candidate marked rejected/review-required)
8. Strict/fallback output when requested

## 3. REFERENCE ANALYSIS: STOP ANALYZING THE REFERENCE BRAND

Audit `reference_guide.md` and code that invokes it. The existing seven-item generic person/beverage/product description can remain for other features but should **not** be pasted wholesale into the final packaging-generation prompt.

Build a compact schema for photography-only observations, with:
- `reference_subjects`: count, bounding regions, object masks if available
- `composition`: centered/offset, relative size, margins, crop, foreground/background relationships
- `camera`: approximate front/3/4/side, elevation, perspective, lens *estimate* with uncertainty
- `environment`: seamless studio/retail/outdoor, wall/floor color, substrate, props
- `lighting`: light direction, softness, color temp, shadows, bounce and ambient occlusion
- `material_and_photographic_treatment`: reflections, grain, focus, depth of field, contrast
- `reference_package_excluded`: brand names, actual printed words, reference color/graphics excluded from transfer
- `scene_confidence`, `needs_user_confirmation`

For the benchmark: upright centered portrait carton, subtle three-quarter view, light gray/white seamless studio backdrop, soft diffused directional light, contact shadow, clean editorial product-photo style.

The analysis may recognize that a box exists, but must not present “POSITIVE HOTEL”, its beige package ink, or its product facts as design instructions for the final ZENTRA carton.

Save the structured analysis and allow advanced users to inspect/edit it.

## 4. FIGMA PANEL MAP / FOLD INSTRUCTIONS

Do not infer the ZENTRA panel arrangement by guessing pixels if it is already available from the confirmed Figma topology. Derive authoritative:
- panel ID, size, 2D bounds, adjacency, assigned face (`front`, `back`, `left/right side`, `top/bottom`)
- recognized fold/cut topology and flap closure
- approved text and vector graphics by panel
- physical carton proportions, paperboard finish

For ZENTRA fixture **verify against actual Figma**, do not hardcode:
- large Korean product/nutrition details = back panel
- sachet illustration = narrow side panel
- large vertical `zentra` and `OKRA PINEAPPLE` = front/hero panel
- `OKRA PINEAPPLE` + smaller vertical `zentra` = opposite narrow side
- the photo should reveal **hero/front at viewer-right with sachet side at viewer-left**, if this is structurally feasible and matches the reference pose.

Require selection or confirmation of the hero panel if topology is ambiguous. Never swap panel faces to satisfy an image prompt.


## 4A. FIGMA-DRIVEN TYPOGRAPHY FIDELITY — REQUIRED HYBRID PIPELINE

**User hypothesis to test:** Because Figma supplies exact strings, font properties, original glyph geometry and source coordinates, the application can produce more faithful lettering than an image-only generative workflow like the demonstrated Flora prototype. **Availability of Figma data alone does NOT guarantee that an image generator will accurately render text.** Implement explicit source-aware restoration and compare outcomes.

### Authoritative text and logo manifest

For every source Figma text/vector asset, derive a versioned manifest containing:
- node ID, parent and panel/face ID, exact Unicode string (including Korean, spaces, punctuation and line breaks)
- font family, style, weight, size, kerning/tracking, line-height, alignment, color, opacity and transformations where available
- source vector outline or high-resolution transparent alpha/texture rendered from the correct fonts
- panel-local 2D corners/coordinates and dimensions in the same metric coordinate system as fold geometry
- flags for primary visible branding vs tiny regulatory copy; clipping and text-counter holes
- asset hash, approved source version and available font/outline status
- logo/vector asset data as geometry and alpha; logos are **not** treated as plain text.

Produce `figma_typography_manifest.json` linked to `package_panel_manifest.json`, and secure asset masks/renders. Never invent text that Figma didn't provide or treat text recognized from the reference photo as our source copy. Do not pass full regulatory paragraphs indiscriminately to the image model; select panel-visible hero copy for guidance and rely on vector rendering for true detail.

### Two-stage photo-first result (plus strict fallback)

1. **Creative candidate:** Keep the demonstrated two-image multimodal generation workflow. Ask for accurate original text and panel placement, but retain the raw generated candidate, even when it contains errors.
2. **Typography and logo verification:** Compare the candidate's visible panel content against the Figma manifest. Distinguish source-authoritative information from uncertain visual recognition and tiny text that is illegible at final resolution. Report missing, duplicated, hallucinated, warped or reference-brand glyphs.
3. **Visible-face registration:** Determine which source panels are visible, their 3D orientation and projected quadrilateral/mesh mapping in the generated photograph. Use existing confirmed 3D structure where available; otherwise use constrained plane/homography fits with confidence scores. Maintain perspective, scale, occlusion and folded boundaries. Never stretch one panel's artwork over a different panel.
4. **Corrected composition:** Optionally remove the model's incorrect lettering/ghost text inside the affected surface with carefully bounded inpainting/clean plate processing. Reproject the exact **source Figma text and logo glyph shapes** or, when needed to suppress ghosting, the verified original panel texture via UV mapping/homography into the photographed panel. Keep Figma masks as the definitive shapes, not AI-generated glyphs. Handle occluders, perspective and anti-aliasing.
5. **Photographic integration:** Match existing panel illumination in a **separate shading/material pass** (local diffuse shading, color-temperature influence, contact/occlusion, controlled material reflection). Never force printed surfaces back to unlit/flat colors, erase real leaf shadows or create glass-like text overlays. Do not alter underlying source artwork metadata. Report when lighting estimation is uncertain.
6. **Quality gate:** Require face alignment, edge sharpness and text/logo fidelity above documented thresholds, validated on real examples. If mapping or masking confidence is insufficient, preserve the original raw candidate and mark `review_required` or offer a strict structural render. **Do not claim a text-corrected image is exact when it is not.**

### User modes and outputs

The baseline `photo_first` produces a natural photographic raw candidate. Add a non-destructive **`photo_first_text_corrected`** output using exact Figma artwork projected onto visible package faces. Keep `strict_artwork` for cases where accurate geometry and glyphs are more important than best possible photo realism. The corrected output must never overwrite `model_raw.png`.

Save:
- `figma_typography_manifest.json`
- `text_logo_verification.json`
- `visible_face_registration.json` (face IDs, coordinates, pose, confidence)
- `text_repair_masks.png` or per-face alpha masks
- `text_repair_preview.png`
- `photo_first_text_corrected.png`
- `text_correction_quality_report.json`

Use asset-level source coordinates and rendered vector shapes; do not substitute look-alike typefaces. If a font is unavailable, request outlined text and mark that asset unresolved. Avoid exposing or packaging font binaries. Small glyph readability is limited by final image resolution and is not solved by higher-confidence prompting alone.

### Benchmarks and acceptance tests

Use the POSITIVE HOTEL reference + approved ZENTRA dieline with the visible front `zentra` wordmark, `OKRA PINEAPPLE` details and sachet-illustration side. Compare three images side by side: **raw AI**, **Figma text-corrected**, **strict artwork**. Include 400% crops for:
- vertical `zentra` wordmark in front and side, exact shape/orientation
- `OKRA PINEAPPLE` and any clearly visible Korean copy
- small ingredient text when legible at output resolution
- gradients, panel edges and shadows around corrected text
- non-source ghost/watermark text such as FLORA.

Required tests: missing/unavailable font; multibyte Korean text; mixed-size labels; rotated vertical lettering; glyph holes; perspective distortion; partial occlusion; tiny text at 2K and 4K; AI-generated pseudo text; reference-package text contamination; registration rejection/fallback; color/shadow preservation; non-destructive reversibility and same-input reproducibility.

**First verify an actual gain in letter correctness at equal output resolution.** Do not assume the corrected pipeline is better without side-by-side visual and source-geometry evidence.

## 5. THE ACTUAL MULTIMODAL GENERATION CALL: REPRODUCE THE WORKING NODE GRAPH

**Highest-priority experiment**: create an isolated provider-level vertical slice that faithfully recreates the demonstrated sequence, with the same two actual input images and dynamically assembled prompt. Confirm model identifier, input-image order/roles, supported multimodal payload structure, safety settings, image dimensions, output resolution, number of images, cost, raw output and provider error handling. No silent fallback to text-only. Log sanitized manifest without API keys or full private image bytes.

Model-facing roles:
- IMAGE 1 — REFERENCE PHOTO: photography, subject staging, camera, studio environment, soft light and shadow **only**.
- IMAGE 2 — APPROVED ZENTRA FLAT DIELINE: exact package artwork and structural reference; clearly state that this is an UNFOLDED net to be assembled.
- STRUCTURED PACKAGE METADATA — user-confirmed sizes, panel order, hero face and closure info.

If actual provider image ordering differs, make role labels explicit and test for accidental reversal.

Create `backend/app/ai/prompts/reference_reconstruction_v2.md` or an equivalent audited template, using a template engine with validated variables. Do not concatenate the whole generic long category prompt twice. The generated instructions should be precise, image-role-aware, and dynamically populated.

### Required model prompt content / exemplar (English)

**TASK: Reconstruct and Photograph the Approved Package**

Create one photorealistic folded carton by combining the supplied reference photograph and approved unfolded packaging dieline.

**REFERENCE IMAGE — PHOTOGRAPHY & COMPOSITION ONLY:** Adopt this photograph’s camera, product placement, framing, background, studio lighting, contact shadow, photographic quality and atmosphere. Do not copy its package branding, text, printing, or ink color.

**SOURCE IMAGE — OUR FLAT DIELINE, DESIGN & STRUCTURE AUTHORITY:** The source image shows an unfolded printed folding carton. Fold only along confirmed creases, cut only at confirmed cuts, assemble the actual carton proportions, close the appropriate flaps and preserve the correct panel order. The source is NOT a photograph of the finished box.

**PANEL MAP — VERIFIED FROM FIGMA:** [insert verified face / side adjacency and subject-critical descriptions]. The selected hero front face MUST become the primary visible front face; selected adjacent side face may be visible according to pose.

**ARTWORK:** Preserve the source logo, Korean/English text, fonts, layout, graphics, gradients, colors, proportions and panel-local positions as faithfully as possible. Do not borrow any graphics, brand names or typography from the reference. Do not add watermarks, extra words, semi-transparent pseudo logos or overlays.

**MATERIAL & PHOTOGRAPHY:** Render the folded carton as real professionally printed paperboard with clean folds, plausible panel seams, proper top/bottom closure, matte/satin print finish, physically natural illumination and cast/contact shadows. Keep the camera and background consistent with the reference.

**OUTPUT:** A single natural studio photograph of OUR assembled carton in the reference composition. Not an unfolded net, not a label pasted onto the reference package, not a redesign.

**Priority:** Our dieline determines the package; the reference determines the photography.

Add negative constraints only to address demonstrated failures. Avoid overly repetitive, contradictory absolutes that harm model performance.

## 6. TWO MODES, EXPLICIT TRADE-OFFS

### Primary — `photo_first` (default for ③ concept generation)
Generate the entire folded, photographed product via the multimodal model. This is the path most likely to match the successful example's natural appearance. Preserve the raw candidate. Do not flatten lighting by replacing every face with unlit source pixels or by applying global color matching that removes real shadows.

### Optional — `photo_first_text_corrected` (Figma exact typography projection)
Use the generated photo as photographic context while projecting exact Figma letterforms/logos onto registered visible package panels and respecting material lighting. Preserve raw result and explicit validation/fallback. Follow Section 4A; do not promise exact results if face registration fails.

### Optional — `strict_artwork`
Use verified structural reprojection and source vector/artwork overlay on the model's candidate or deterministic folded render for higher text/logo accuracy. Preserve original scene lighting via physically meaningful shading, soft occlusion and local environment harmonization. It may be less photorealistic; disclose that trade-off. Do not make this mode mandatory before validating the `photo_first` path.

Both modes must be non-destructive. They can share scene analysis, package manifest and QA.

## 7. COMPOSITING RULES AND LIGHT

Audit current `backend/app/services/merge.py`, `backend/app/render/carton3d.py`, prompt templates and generation pipeline. Investigate:
- Is the selected approved version really used or is it regenerated with a different look?
- Does the provider receive both actual images with correct order and sufficient detail?
- Are repeated/wrong prompts or role contradictions degrading quality?
- Is the AI raw image materially better than the app's final composite?
- Are face-compositing color constraints whitening realistic shadows or adding halos?
- Does the current low-detail 3D proxy force an unrealistic pose/proportion?
- Are canvas size and reference photograph aspect ratio maintained?
- Is typography re-created with approximate OCR rather than source?

Never assert a cause without a controlled raw-vs-final comparison.

Preserve reference background and authentic lighting in `photo_first`. For multiple source packages: detect/select count, replace each old box with our approved model while respecting arrangement and occlusion. For the benchmark, **one** package is expected. Reject leftover reference-brand text, duplicate boxes, unwanted overlaid typography and visible dieline guides.

## 8. USER INTERFACE — STEP ③ REFERENCE COMPOSITION

Retain the existing page and prior modes. Add a clearly labeled “참고 사진 기준 AI 패키지 재구성 (Photo-first)” choice.

Right panel:
- approved flat-render version + finish state
- reference image upload + preview
- detected reference composition summary, editable
- hero/front face selector and adjacent visible-side preview
- output mode `photo_first` / `photo_first_text_corrected` / `strict_artwork`
- scene fidelity ↔ artwork fidelity explanation (not a misleading “perfect accuracy” toggle)
- optional user photography instruction (appearance only)
- Generate button and progress stages
- raw candidate vs final/fallback before/after
- warnings for text/structure mismatch, regenerate button, download

Use the reference image's aspect ratio by default; don't force the flat dieline landscape ratio onto the concept-photo output.

Do not require users to build an accurate 3D model manually before trying `photo_first`.

## 9. VALIDATION / ACCEPTANCE

Introduce **benchmark-first evaluation** with these 3 attached fixtures:
- `positive_hotel_reference.png` (reference photograph; one upright carton)
- `zentra_flat.png` (approved flat dieline)
- `zentra_desired_concept.png` (external target; contains an unwanted overlay and is only a photographic/composition reference)
If these uploads are unavailable in the agent's workspace, request them explicitly from the user; do not invent or substitute test images.

Report:
- photo similarity: placement, camera, background, light, material, composition (human-rated rubric, qualitative)
- package identity: correct hero front / visible side / proportion / closed-fold form
- Figma text/logo correctness: compare to source text/assets; flag hallucinated letters and misplacements rather than claiming exactness
- no reference branding, no FLORA/watermark overlay, no duplicate package
- image quality: sharp text, realistic shadows, no ghost letters, no glass texture or glow
- latency and cost for full API generation, failure/cancellation behavior
- status of raw model output vs final app output

**Release gate:** For one-box POSITIVE HOTEL × ZENTRA benchmark, produce a compelling upright folded-carton photograph that a reviewer judges comparable in photographic staging to the supplied successful prototype, without alien text overlays. Do not mark ready based on successful API response alone.

Tests must include: reference with 1 product, three products, background-only, visible side swap, unsupported carton topology, invalid provider response, small Korean text, foil/UV finishing, retry/timeouts. Automated checks plus real image visual review. If the model cannot preserve exact text, mark `review_required` and provide strict rendering or a redo path.

## 10. PHASED IMPLEMENTATION (REVIEW GATES)

**M0 — Audit / benchmark plumbing:** Inspect current code and current branch, compare raw and final outputs; prepare sanitized fixture manifests; document suspected quality-loss points. Deliver `docs/reference-composition/photo-first-audit.md`.

**M1 — Working minimal vertical slice (MUST DEMONSTRATE BEFORE REFACTOR):** Send exactly the user's reference photo + approved ZENTRA flat image + role-specific generated prompt to the configured multimodal image provider. Save raw output and run settings. Compare it to attached target. Prove real model call receives both images. Do not proceed until visual result is reviewed.

**M2 — Structured analysis and dynamic prompt compiler:** Class-specific concise reference photography analysis + Figma panel manifest + tested prompt assembly; ability to edit incorrect inferred scene/hero face. Unit tests.

**M3 — Integrate into Step ③ UI:** New photo-first mode, version selection, progress/errors, raw/final comparisons, regenerate and output storage. Keep legacy and structural modes functional.

**M4 — Figma-aware text/logo accuracy and strict fallback:** Implement the authoritative typography/logo manifest, face registration, visibility checking, corrected-composite output and quality gating from Section 4A. Compare raw vs text-corrected vs strict outputs at full resolution; include 400% crops. Do not silently claim exact Figma typography.

**M5 — Broader scenarios and stabilization:** multi-instance, no package in reference, finishing fidelity, cancellation, cost, tests and README. Do not merge without acceptance evidence.

Commit by milestone. Avoid scope creep such as universal manufacturing-grade carton folding solver in the photo-first MVP. Reuse the existing verified structural model for prompting and validation.

## 11. REQUIRED DELIVERABLES

- PRD: `docs/prd/reference-photo-first-reconstruction.md`
- code audit and architecture diagram
- new model prompt template(s)
- reference photography JSON schema
- Figma panel mapping/manifest and typography/logo manifest
- visible-face registration and vector text/graphic projection with quality gates
- raw vs photo-first text-corrected vs strict comparison previews
- provider image-role payload with diagnostics
- working `photo_first` vertical slice
- updated Step ③ UI
- raw vs app-processed comparison for ZENTRA
- unit/integration + human visual QA
- cost, time, safety and unsupported-case notes
- merge-readiness summary with code/test references

**Do not stop after writing documentation. Implement M0 and M1 first, present the real raw generated image and comparison for review, then proceed through further milestones after verifying the target behavior. Do not auto-merge.**
