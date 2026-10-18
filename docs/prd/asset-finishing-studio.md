# PRD — Asset-Based Print Finishing Studio (후가공 스튜디오)

Status: implemented through Milestone 7 (see §9) · Branch: `feat/asset-based-finishing-studio`
Research basis: `docs/research/postpress/*.md` · Implementation plan: `docs/prd/finishing-implementation-plan.md`

## 1. Problem

Packaging designers decide on foil, embossing, coatings and resin domes long before a physical proof
exists. Today the Dieline Generator shows the exact printed artwork on a realistic flat board (② Flat
Render, deterministic v3/v4) but nothing of the post-press finishing, so designers either imagine it
or fake it in Photoshop on a flattened image, where finishes drift off the real artwork and nothing
can be handed to a finisher.

## 2. Goal

On the ② Flat Render page, a designer selects one or more **original Figma assets** (text, logos,
vectors, groups — or whole panels / the full sheet for surface finishes) directly on the canvas,
assigns post-press finishes, and sees a **physically informed preview** that:

- follows the exact source geometry (glyph outlines and counters, compound paths, clipping);
- behaves like the real material under light (metal reflects, pigment foil is near-diffuse, spot UV
  is a clear gloss contrast, emboss/deboss is relief, epoxy is a clear raised dome);
- never changes the design itself: removing a finish restores the original render byte for byte.

Non-goals (this release): character-range selection inside a text object, lasso selection, raised /
high-build UV (data model reserves it), guaranteeing manufacturability (warnings only), editing the
artwork.

## 3. Users and core user stories

Primary user: packaging designer preparing a design for production and for client presentation.

- **US-1 (main)** "As a packaging designer, I want to select one or multiple original Figma design
  elements on my unfolded packaging and apply physical print-finishing treatments to them, so I can
  realistically preview the manufactured appearance without changing the underlying design."
- **US-2** As a designer, I want different assets to carry different finishes (gold foil on the
  wordmark, deboss on the icon, spot UV on the title) and see them together.
- **US-3** As a designer, I want whole-surface finishes (matte/gloss lamination, uncoated, flood UV,
  varnish) on the full sheet or chosen panels, with glue areas kept free.
- **US-4** As a designer, I want to rake the light across the sheet to see foil, holographic foil,
  spot UV and relief react, then export the view I like.
- **US-5** As a designer, I want warnings when a finish is likely to be hard to produce (fine text
  under foil, emboss crossing a fold, coating on a glue flap), with the reason and its source.
- **US-6** As a designer/producer, I want to export per-finish vector plates (foil, emboss die,
  spot UV, epoxy) and the finishing spec to send to the finisher.
- **US-7** As a designer, I want to use the finished flat render in ③ Reference Merge so the folded
  box in the scene shows the same finishes.
- **US-8** As a designer of a PDF-only project (no Figma link), I want the same selection and
  finishing on the PDF's own vectors and text.

## 4. Main workflow (US-1)

1. Open ② Flat Render; the deterministic render is shown.
2. Hover highlights the asset under the pointer (exact outline, not a box).
3. Click selects the main logo; it is outlined and listed in the right panel.
4. Shift-click adds a text object (multi-select, across panels allowed). `[` / `]` or Alt-click
   cycles between overlapping or parent/child assets.
5. The panel shows "선택한 요소 (2)" with name, type, source panel and a remove action.
6. Choose a category: 박 · 형압 · 코팅 · 액상 코팅 · 에폭시.
7. Choose a subtype, e.g. 금박 (Gold foil); a material swatch shows its appearance.
8. Adjust the category's parameters (bounded, research-based defaults).
9. "후가공 적용 / Apply Finishing" creates an assignment for exactly those assets.
10. The preview updates at preview resolution; the finish appears only inside the exact masks.
11. Select other assets, apply a different finish; all assignments coexist in a layer stack.
12. Toggle visibility, edit parameters, remove, re-target an assignment; undo/redo any change.
13. Compare Original / Finished / side-by-side; toggle the raking light or play a light sweep.
14. Render the final 4096 px version (a new version; the original stays), export PNG and plates.

## 5. Functional requirements

### 5.1 Asset selection (Figma-aware)
- FR-S1 Asset tree from the Figma file version the project was imported from: node id, frame id,
  name, type, parent/children, transform, bounds, opacity, clipping, visibility, technical flag,
  panel mapping.
- FR-S2 Masks from source vectors: Figma per-node export with outlined text (exact glyphs),
  rasterised at the render's scale and origin with anti-aliasing; cached per file version + node.
- FR-S3 Never selectable: cut/fold lines, dimensions, bleed guides, technical notes, hidden or fully
  clipped nodes (reuses the technical-layer rules in `backend/app/pdf/rules.py`).
- FR-S4 Interaction: hover highlight, click, shift-click multi-select, deselect (Esc / click empty),
  cycling for overlaps, selection outlines, selection list in the panel.
- FR-S5 Whole-panel / full-sheet targets for surface finishes (panels from the confirmed structure).
- FR-S6 PDF-only projects: asset tree from PDF text spans (glyph outlines) and vector groups.
- FR-S7 Data model allows future character ranges (`target.range`), not exposed now.

### 5.2 Finishing catalogue (stable ids, ko/en labels)
Foil (`foil.*`): gold 금박, silver 은박, black 먹박, white 백박, red 적박, green 녹박, blue 청박,
holographic 홀로그램박 — extensible to custom swatches. Emboss (`relief.*`): emboss 엠보싱/볼록형압,
deboss 디보싱/오목형압, blind or registered. Surface (`surface.*`): gloss lamination 유광 라미네이팅,
matte lamination 무광 라미네이팅, uncoated 비코팅. Liquid (`coating.*`): spot UV 부분 UV, flood UV 전체
UV, varnish 바니시 (gloss / matte / satin); high-build UV reserved. Epoxy (`dome.*`): epoxy /
polyurethane resin dome 에폭시. Parameters per subtype, bounded, defaults cited in
`docs/research/postpress/material-behavior-matrix.md`.

### 5.3 Finishing data (non-destructive)
- FR-D1 A finishing spec per project, separate from source data: `schema`, `revision`,
  `assignments[]` with id, targets (asset ids / panel ids / sheet), category, subtype, preset,
  params, stack order, enabled, created/updated.
- FR-D2 Undo/redo (client history of spec edits), save/reload (server revisions).
- FR-D3 Re-import reconciliation: node ids matched against the new file version; ambiguous or
  missing targets are flagged for confirmation, never silently re-bound.
- FR-D4 Rendering a finished version stores the source version id and spec revision.

### 5.4 Rendering
- FR-R1 Deterministic geometry: masks, height fields, cut/fold geometry never come from AI.
- FR-R2 One scene-light model for board, folds and finishes: key direction/elevation, softness,
  exposure, reflection intensity, studio environment; default = current top-down look; optional
  raking light; light-sweep preview.
- FR-R3 Explicit layer stack: substrate → printed ink → surface treatment → selective treatments →
  relief → scene lighting; material-aware compositing, not additive brightness.
- FR-R4 Combinations: valid sequences from research (e.g. matte lamination + spot UV, foil +
  emboss); incompatible / high-risk combinations flagged.
- FR-R5 Preview resolution for interaction; final 4096 px as a job; only finish layers recomputed on
  parameter edits.

### 5.5 Protection and validation
- FR-P1 Outside finish masks (and outside a documented relief shoulder band) the result equals the
  source render, except for whole-surface finishes, which follow their documented bounded model.
- FR-P2 Inside a mask the finish replaces only optical appearance; source data is untouched; removing
  the finish restores the source render exactly.
- FR-P3 Cut silhouette, openings, fold positions and output size never change.
- FR-P4 Manufacturing warnings (configurable per supplier) from researched constraints; the preview
  never claims manufacturability.

### 5.6 Integration
- FR-I1 Finished renders are new versions, downloadable, usable as ③ merge sources.
- FR-I2 Optional AI appearance guidance (blank material inputs only); finish masks are protected;
  AI never decides boundaries or redraws artwork.
- FR-I3 Export: preview/final PNG, per-finish vector plates (PDF/SVG, dieline coordinates), spec JSON.

## 6. UX (right panel · "후가공 / Finishing")
A. Selected assets (count, name, type, panel, remove) · B. Category · C. Subtype · D. Material
swatch (rendered by the same renderer, not flat colour) · E. Category-relevant parameters ·
F. Apply · G. Applied finishes (visibility, edit, remove, re-target, order) · H. Original / Finished
/ Compare · lighting (default / raking, sweep). Existing AI enhancement section stays.

## 7. Success criteria
The 18 acceptance criteria of the master command, plus: plates export opens in Illustrator at the
dieline's coordinates; a PDF-only project can be finished; finished versions merge in ③.

## 8. Risks
- Realism of metals and holographic foil in a single top-down photo (mitigated by raking light /
  sweep and reference comparisons).
- Figma API availability for node export (cached; offline fixtures in tests).
- Performance at 4096 px (preview resolution, caching).
- Supplier-specific manufacturing rules (configurable profile, cited defaults).


## 9. Implementation status, QA and limitations (Milestones 2-7)

**Done**
- Selection on exact Figma geometry (outlined SVG per node, clipping, counters); PDF-only fallback
  from printed ink (approximate). Specification with revisions, conflict detection, undo/redo; the
  same finish on the same targets collapses to one.
- Preview = transparent overlay of only the finished pixels at the version's full resolution
  (outside: the version image, bit for bit). Removing or hiding a finish restores it exactly.
- Materials for all 26 catalogue finishes (`render/finishing/material.py`), tone levels measured
  from local reference photos (`calibration.json`); top or raking light; light sweep (GIF).
- Finished versions (`flat_mode: "finished"`) usable in ③; optional "AI 사실감": the model's picture
  of each foil / relief / spot-UV area only lends a bounded luminance map inside the mask, rejected
  when misaligned, too different, or measurably further from the photo tone levels.
- Manufacturing checks (`finishing/constraints.py`) from `manufacturing-constraints.md`; finishing
  plates (vector PDF per finish in 100% K, clipped to the board + 1 mm bleed, dieline as a separate
  `dieline.pdf`, spec JSON). Stabilization: see `docs/qa/finishing-studio-final-report.md`.

**Measured (Zentra, 4096 px render, 5 finishes, Apple silicon)**
- Preview overlay: ~8 s first time (board + masks at full size), ~2 s after, then cached per revision.
- Light sweep (12 frames, ≤900 px): ~2.5 s. Manufacturing checks: ~8 s cold, ~2 s warm, cached.
  Plates: <0.1 s. Finished version job (no AI): ~10-25 s.

**Comparison with real photos (honest reading of `scripts/finish_gallery.py`)**
- Gold / silver / coloured metal foil and blind emboss/deboss read as the same family as the photos
  (reflection sweep, deeper metal tones, rim; soft flank shading). Holographic: pastel silver with
  soft iridescence, saturating under raking light, as in the photos.
- Spot UV / varnish: deliberately subtle; on light stock it barely shows (as in reality).
- Not photo-identical: no camera perspective or depth of field, one fixed studio environment, no
  paper fibre change under raking light outside the finishes (the board keeps the flat render's
  light), domes are a simplified meniscus/refraction model. "AI 사실감" exists for this gap but is
  only used when it passes the checks.

**Limitations / not done**
- Character-range selection inside a text, lasso selection.
- Text size check uses Figma font size; outlined or PDF-only text falls back to stroke width.
- Glue flap is found by panel name (접착 / 풀칠 / glue); rename the panel if it is not detected.
- `ai_material` enhancement is not offered on finished versions (finish first, or enhance first and
  then finish — both orders keep the finishes exact).
- Reference photos are local only; without them the AI step runs with the prompt alone.
