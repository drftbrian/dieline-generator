# Plan: Asset-Based Print Finishing Studio (feat/asset-based-finishing-studio)

## Context
The user wants a post-press finishing simulator on the ② Flat Render page: select real Figma assets
on the canvas, assign foil / emboss-deboss / lamination / UV-varnish / epoxy, preview them
realistically, non-destructively, without touching the original artwork or dieline. The spec
(Phases 0-12) was reviewed against the repo for gaps; this plan adds the missing pieces and the
user's decisions:
- Stop for review after **every milestone**; commit **and push** the branch at each milestone
  (never merge to main).
- Extra scope: **PDF-upload projects**, **light-sweep preview**, **finished flat versions usable in
  ③ merge**, **finishing plate (mask) export**.
- Lighting: default stays the natural top-down v3/v4 look; an optional **raking/grazing light**
  toggle reveals foil/UV/emboss; export uses the chosen lighting.

Already done: branch `feat/asset-based-finishing-studio` (from feat/ai-prompt-enhancement);
Phase 0 audit; Phase 1 research agent running (writes docs/research/postpress/*.md); verified
Figma per-node SVG export with `svg_outline_text=true` returns exact outlined glyph paths.

## Gaps found in the spec (and how the plan closes them)
1. **Asset data is shallower than assumed** — `figma/layers.extract_content` keeps texts (id, bbox,
   style; no glyph outlines) and only depth-1 graphics (4 on Zentra); no tree, transforms, clipping,
   opacity. → New `figma/assets.py`: full visible node tree (id, parent, type, name, transform,
   bounds, opacity, clips, technical flag, panel) + on-demand per-node outlined SVG export, cached
   per file version, rasterised with PyMuPDF (opens SVG) at layer scale/origin → exact AA masks with
   counters/compound paths. Click selects the deepest asset; Alt/[ ] cycles to parent/siblings.
2. **Verification conflicts with intended optical change** — `look.verify_flat` requires
   final = print × achromatic gain; gold foil over a black logo legitimately breaks that. → Mask-aware
   verify: outside finish masks the existing gates apply unchanged; inside each mask, the result must
   equal that finish's deterministic material render (exact registration, no spill beyond mask +
   relief shoulder band, no change to unselected assets); finish removed ⇒ byte-identical to source.
3. **Whole-surface finishes vs "unselected artwork unchanged"** — gloss lamination legitimately
   changes how all print looks. → Define bounded, documented global material response (spec'd per
   finish from research) and verify against that model, not against "unchanged".
4. **Lighting/view model undefined** — orthographic top-down + soft light makes metals look flat;
   holographic needs angle dependence. → One scene-light model (key direction, elevation, softness,
   exposure, reflection intensity, studio-softbox environment term) shared by v4 folds and finishes;
   per-pixel light/view vectors from a finite light position give spatial angle variation (needed for
   holographic); raking-light toggle + light-sweep preview (frames/GIF) for review.
5. **Pipeline integration unspecified** — versions, ③ merge, AI enhance. → A finished render is a new
   version (`flat_mode: "finished"`, source + finishing-spec revision); mergeable in ③ (carton faces
   cut from it); AI enhance allowed on finished versions with the finish masks added to the protected
   zone; deterministic source never modified.
6. **Interactive performance** — 4096 renders take ~20 s and the preview endpoint was removed. →
   Preview-resolution render endpoint (~1400 px, cached layers + cached masks), final 4096 as a job;
   parameter edits re-render only finish layers.
7. **Glue areas / coating-free zones** — no data says which panel is the glue flap. → Use panel
   names (Claude-named, e.g. 접착 날개) + user override; configurable supplier constraint profile
   (`backend/app/finishing/constraints.yaml`) with research-cited defaults.
8. **Production deliverable** — spec exports only images. → Finishing plates export: one vector
   PDF/SVG per finish (foil, emboss die, spot UV, epoxy) in dieline coordinates + a JSON spec.
9. **PDF-only projects** — no Figma nodes. → Asset tree from the PDF itself (`pdf/analyze`
   ArtObjects: text spans with glyph outlines via PyMuPDF, vector groups); same mask/finishing path.
10. **Mask edge policy** — foil/UV are binary deposits; source assets may have partial opacity or
    gradients. → Mask = vector coverage (AA) only; opacity/gradient of the source never thins foil;
    raster images: alpha-threshold mask, flagged as approximate.
11. **Tests vs network** — glyph masks and re-import tests need Figma. → Recorded SVG/JSON fixtures
    (Zentra subset) for offline tests.
12. **Visual comparison to real photos** — copyrighted photos can't be committed. → Gallery pairs our
    renders with reference URLs; photos only viewed locally (scratchpad), never committed.
13. **Undo/redo scope** — client-side history of the finishing spec; server stores spec revisions
    (save/reload, stable render versioning, migration field `schema`).

## Milestones (stop for review + commit + push after each)
- **M1 Research & taxonomy** — the 4 research docs (agent), finishing catalogue
  (`backend/app/finishing/catalog.py`: stable ids, ko/en labels, params with bounded defaults from
  research), `docs/prd/asset-finishing-studio.md`, implementation plan doc. No renderer code.
- **M2 Asset selection** — `figma/assets.py` tree + node SVG export/cache + `finishing/masks.py`;
  PDF fallback; API: `GET /projects/{pid}/assets`, `GET .../assets/{id}/mask` (preview), hit-test;
  frontend canvas layer (hover, click, shift-multi, cycle, outlines) + right-panel selection list.
  Demo: Zentra logo + multiple texts selected with exact glyph masks.
- **M3 Finishing UI & data** — finishing spec model (assignments, stack order, enabled, revisions,
  migration), API CRUD + undo/redo client store, panel (categories, subtypes, swatches,
  category-relevant params, apply/edit/remove/visibility, before/after), placeholder deterministic
  effects, save/reload.
- **M4 Primary renderers** — `render/finishing/` (scene light, height fields/normals reusing
  `render/folds.py` patterns): gold/silver metallic foil, emboss/deboss (registered & blind), matte
  /gloss lamination, spot UV; layer stack (substrate → ink → surface → selective → relief → light);
  mask-aware verify; raking-light toggle.
- **M5 Extended** — colour/pigment foils, holographic (grating-inspired, angle-dependent), uncoated,
  flood UV, varnish presets, epoxy dome (meniscus profile, clarity, mild refraction), combination
  rules + manufacturing warnings, light-sweep preview, plate export, ③ merge with finished versions.
- **M6 AI** — optional appearance guidance on blank material inputs (reuse `services/enhance.py`
  extraction/registration), finish masks protected; adopt only if measurably better.
- **M7 QA** — automated tests (functional, fidelity, visual regression on white/dark/gradient/
  Korean-text/thin-line/compound fixtures, performance), comparison gallery vs research references,
  limitations, local testing guide.

## Critical files
- New: `backend/app/figma/assets.py`, `backend/app/finishing/{catalog,spec,masks,constraints}.py`,
  `backend/app/render/finishing/*.py`, `backend/app/api/finishing.py`, `src/features/finishing/*`,
  canvas selection layer in `src/features/canvas/`, docs under `docs/`.
- Extend: `figma/client.py` (node export), `render/look.py` (mask-aware verify),
  `services/pipeline.py` (finished versions, preview render), `services/merge.py`,
  `services/enhance.py` (protect finish masks), `api/schemas.py`, `spec/models.py`.
- Reuse: `render/layers.py` (frame/raster/coverage), `render/folds.py` (height→normal→Lambert),
  `render/shading.py` (render_parts, achromatic gain), `pipeline.get_layers`, `figma_colour_regions`.

## Verification (each milestone)
- `pnpm test:api`, `ruff`, `pnpm typecheck/lint/build`; v1–v4 checksums stay pinned; existing AI
  enhancement tests stay green.
- Milestone demos on Zentra (data copy in scratchpad): screenshots (headless Chrome via CDP),
  400% crops, difference maps, raking-light views, side-by-side with reference URLs.
- Finish removal ⇒ byte-identical to the source render; source files' sha256 unchanged.
