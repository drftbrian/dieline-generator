# Dieline Generator — Rendering Fidelity Fix
## Repository-specific implementation brief for a coding agent

Target repository: https://github.com/drftbrian/dieline-generator  
Target outcome: Figma vector artwork (text, logos, colors, precise locations, technical lines) rendered on an unfolded printed cardboard sheet, top-down against a solid black background, with **crisp printing and restrained paperboard realism** like the supplied photography reference.

**Scope:** Primarily the **Step 2 flat render**. Apply the corresponding compositing principles to Step 3 `flat` reference merge. Do **not** change the folded-package workflow until baseline flat output is verified.

### IMPORTANT
This document is a development task/acceptance specification, **not** a runtime prompt. The app does not automatically read this file. Give it to your code agent and instruct the agent to implement the changes, tests, and diagnostics below. `backend/app/ai/prompts/flat_render.md` is the runtime prompt for Step 2; a separate concise replacement is provided.

## 1. Reproduction and root causes

The current repo already has:
- a Figma import and vector extraction path (`backend/app/figma/`, `backend/app/services/pipeline.py`);
- deterministic artwork and silhouette layers (`backend/app/render/layers.py`);
- a deterministic package renderer (`backend/app/render/shading.py`);
- a generative Step 2 render (`backend/app/services/pipeline.py::run_generate`);
- post-processing to transfer AI appearance to exact printed artwork (`backend/app/render/surface.py::transfer`, `pipeline.py::composite`);
- checks (`backend/app/render/look.py::verify`).

Suspected/confirmed-from-code causes to address, not unverified claims about a particular output:
1. `surface.transfer()` divides model luminance by print luminance; any unmatched gradient, differently drawn text, or misregistered edge becomes a *false texture/shading signal*. Specifically, `ratio = scene_luma / print_luma`, edge detection, `PRINT_ZONE_MM = 2.0`, `_fill_blur`, and the zone feather can yield dark/bright halos around text.
2. `pipeline.composite()` uses `scene` **outside** the exact dieline silhouette (`out = scene * ... * (1-s) + pkg*s`). It can preserve a model-invented edge, board thickness, halo, displacement, or gray background even when the original silhouette is correct.
3. `look.py::verify()` checks mostly whether `final ≈ base × gain`, color, and detail correlation. That equation does **not** prove that `gain` looks like natural board, and `print_echo` is reported but explicitly **not** a hard gate.
4. `pipeline.py::gen_size` creates a size rounded to multiples of 16 and `run_generate` resizes a separately rasterized `base_img`. `pipeline.cover` then rescales / center-crops the model output. Even small discrepancies make image-derived texture unsuitable for registration to precise glyphs and cut edges.
5. The model is asked to redraw a *complete detailed package* despite already having an exact vector print layer. More prompt instructions cannot guarantee glyph or registration fidelity.
6. The image-model request uses 2K, which may be inadequate for tiny Korean labeling and dense nutrition panels if the entire dieline is visible. Always rasterize original vector artwork at the **final** resolution rather than upscaling an AI result.

## 2. Implementation strategy (priority order)

### P0 — deterministic flat baseline with zero AI
- Add a selectable `flat_render_mode = "deterministic" | "ai_appearance"` (default `"deterministic"` for now; old mode remains available for comparison).
- Reuse `get_layers()` and `shading.render()` for all geometry and source printing. Return the full-size PNG directly, not the `flat.jpg` thumbnail.
- Target 4096 px on longest edge initially (configurable, preserve aspect and pixel-aligned framing). Test memory/performance; 2K remains preview, not master.
- Keep all Figma text, logos, icons, barcode and the actual gradient as source artwork. Use PDF/Figma vector rasterization at target pixels. No model redrawing or retyping.
- Use the Figma-approved cut silhouette and internal hole masks for exact coverage, not an AI mask.
- Black ground outside, soft *contact shadow only* near the contour, with no global milky lift and no edge glow.
- Use subtle **achromatic** (same gain for R/G/B) board texture: e.g. low-amplitude fine paper fibers, 0.5–1.5% luminance modulation at final scale; avoid large cloudy gray patches, oily glare, chromatic noise, fake embossing or glass.
- Creases are narrow shallow physical score lines, not bold strokes or duplicated cut edges.
- Add debug baseline image `<vid>_deterministic.png`.
- Assert Figma's gradient and typography remain visible and placed correctly even when the reference photo is mostly white.

Suggested logic:
```python
# Pseudocode only. Fit existing APIs, job cancellation, status and storage.
layers = get_layers(pid, spec, final_long_edge, FLAT_LOOK.lighting.margin)
rgba, silhouette = shading.render(layers, calibrated_flat_look)
final_rgb = rgba[..., :3].copy()
save_png(final_rgb, version_id)
# Validate artwork/geometry against the original layers, not against an AI reconstruction.
```
Review current `shading.py` constants (`GRADIENT`, `AMBIENT`, texture noise, `crease_relief`, edge and shadow strength) against the target photo. Tighten shadows and noise if necessary. The deterministic baseline must be good *before* reintroducing AI.

### P1 — never inherit model pixels around exact dieline exterior
In `backend/app/services/pipeline.py::composite`:
- For flat mode, NEVER take the final outside-package background from `scene`.
- Generate background `#000000` and shadow deterministically using the **exact** silhouette and verified board thickness; the shadow must affect only a narrow region outside the package.
- Strictly mask anything model-derived to the actual paperboard interior; use geometry-derived antialiasing on the boundary.
- Do not use `scene` to determine cut-line locations, board thickness, slots, or tabs.
- Compare output alpha/outer-edge distance to the deterministic mask. Any secondary or shifted contour is a failure.
- Preserve high-resolution source vector print. Do not interpolate it from the 2K image generated by the model.

Suggested compositing structure:
```python
# Pseudocode, not an exact drop-in patch.
paper_rgb = exact_print_with_safe_substrate_texture(...)
shadow = deterministic_contact_shadow(exact_silhouette)
background = np.zeros_like(paper_rgb)  # exact black
background *= (1 - shadow[..., None])
final = paper_rgb * exact_silhouette[..., None] + background * (1 - exact_silhouette[..., None])
```
If adding AI illumination, apply it only as a *smooth, clamped, low-frequency neutral map inside the silhouette*.

### P2 — replace full-print texture extraction with protected appearance transfer
Do not use `scene / print` at glyph scale.
- Preferred: Nano Banana Pro supplies only a **blank/unprinted-paper appearance example** or a **lighting guide**, not a fully re-lettered product mockup.
- For the appearance map: exclude text, logos, barcode, strong image edges, cut edges, and artificial shadows from samples. If too little uncontaminated paper is available, **skip the appearance transfer** and keep P0 output.
- Build only a low-spatial-frequency neutral lighting map from clean paper areas, registered to deterministic canvas coordinates. Clamp per-pixel illumination near 1.0; permit only gentle variation. Do not infer detailed shadow/texture by dividing an AI image by the Figma artwork.
- Use a separate, deterministic, physically scaled paper-fiber texture layer, never raw AI 'fibers' on top of text.
- Do NOT blur any source text pixels, logos, barcode elements, or original printed vectors. Overprint source art at native resolution after substrate texture and lighting are computed; optionally use a very small, bounded ink-paper interaction only if it passes closeup review.
- Make the whole pipeline fail-safe: if Nano Banana changes object silhouette, print registration, type or background, its result is **not** used as-is.
- If retaining `surface.transfer()` for experiments, disable ink starvation (`INK_STARVE`) and disable `PRINT_ZONE_MM`/`_fill_blur` near type in the production flat path until visual QA demonstrates their value.

### P3 — improve 2D spatial/size fidelity
- Render the vector artwork once at the final output size; do not resize that raster merely to meet provider format constraints. The model can receive a separate preview.
- Track `render_size`, `provider_size`, `provider_aspect`, crop offset, scale, and transform. Verify consistent coordinate frames before transferring any lighting map.
- If the provider's output ratio differs (see `backend/app/ai/providers/gemini.py::nearest_ratio`), avoid `cover()` and blind center-crop for registered transfer. Reject or explicitly compute and validate a registered transform. Prefer never requiring AI image registration for Step 2.
- Preserve the cut silhouettes and nested holes from `layers.silhouette`; avoid optical edge detection in generative imagery.
- Detect font export problems by comparing a Figma frame export, the source PDF, and the deterministic render. Missing glyphs, font substitutions, wrong line wrapping, incorrect rotations or sizes are blocking defects, **not** AI-fixable artifacts.

### P4 — deterministic visual-quality tests
Add regression tests using one sample dieline with:
- Korean/English fine print and paragraph text,
- a large vertical logo,
- an actual colored printed gradient,
- technical redlines combined in one Figma layer,
- notches, glued tabs, internal slots and creases.

Tests and acceptance criteria:
1. **Exactly one outer package silhouette**, no luminous/gray “echo” along edges. Black background outside the narrow physical shadow band.
2. **Print registration**: source text and logo pixel locations, rotation and line breaks match Figma-exported vectors, allowing only intended antialiasing; no AI-generated characters.
3. **No type halo / glass look**: on 200–400% closeup, letters have one crisp edge, not an offset bright duplicate or frosted border.
4. **Texture**: visually subtle, monochromatic, across unprinted board areas; no gray cloud patches; gradients remain gradients defined by Figma.
5. **Fold/cut geometry** matches approved structure mask exactly. Creases are continuous paper; cutouts show black.
6. **Color fidelity**: printed-region representative colors match source, within predeclared small allowable lighting/ink tolerances.
7. **Higher-resolution baseline**: compare 2K to 4K export; fine labels should improve through source re-rasterization (not model upscaling).
8. **Deterministic reproducibility**: same Figma source/settings => same output/checksum.

Add a QA montage with: (a) Figma/source vector; (b) clean deterministic output; (c) optional model raw; (d) appearance gain heatmap; (e) final output; (f) 4× text/logo crop; (g) edge/crease crop. Log exact sizes and crop transforms.

## 3. Clarify redline semantics before changing extraction
The repository currently states **outermost contour = CUT**, **inner panel seams = CREASE**, **internal closed slot/hole loops = CUT** (`README.md`, `flat_render.md`, `backend/app/pdf/...`). This is also the normal interpretation for the sample shown.

Previous user-language in this conversation said "outside = folding, inside = cutting"; this conflicts with the repository and the visible sample if "outside" means the entire exterior boundary. Do not blindly flip all classes.

Use this evidence hierarchy:
1. explicit Figma layer or per-path metadata for Cut / Crease / Slot, if unambiguous;
2. geometrical/topological role of the *actual closed outer silhouette*, internal panel-to-panel creases, and enclosed cutouts;
3. a **human-confirmed** per-path classification.

If the user has a genuine unconventional positional naming convention, document exactly what "outside" and "inside" mean relative to which geometry and save user-confirmed overrides. Do not infer cutting/folding from red color alone.

## 4. Where to change the current project
- `backend/app/services/pipeline.py` — Step 2 routing, provider optionality, compositing; create deterministic baseline mode and diagnostics.
- `backend/app/render/shading.py` — board material, low-amplitude texture, folds, physically restrained edges/shadows.
- `backend/app/render/surface.py` — avoid full generative appearance division over artwork; if retained, restrict to safe low-frequency map.
- `backend/app/render/look.py` — quality checks beyond the trivial `final == base × gain`, including actual print-source sharpness, mask/edge coherence, halo and background tests.
- `backend/app/ai/providers/gemini.py` — separate provider preview size from native final vector-raster size; do not assume a 2K generative result is a 4K print master.
- `backend/app/ai/prompts/flat_render.md` — only when optional Nano Banana appearance mode runs. Keep the existing `$figma_url`, `$dims`, `$panels`, `$fonts`, `$logos`, `$colours`, `$texts_by_panel` placeholders; the renderer uses `string.Template.substitute`.
- `backend/app/ai/prompts/flat_look.png` — photography look reference, NOT a geometry or type source.
- `backend/tests/` — new regression tests for flat-only, typography, background/halo, technical geometry.

**Runtime behavior:** prompt `.md` changes are cached; restart the backend before testing. The repo README documents this.

## 5. How to debug a failed real run
The repository writes diagnostics under `backend/data/projects/<project_id>/versions/`:
- `<version_id>_raw.png` = the returned Nano Banana image;
- `<version_id>.png` = approved composited result;
- `<version_id>_rejected.png` = failed verification (if rejected);
- `<version_id>_structure.png` = reference-merge input structure;
- version JSON `verify` = numerical QA.

Request these for the same project/version. If the **raw** contains cloudy letters but **final** is clean, leave the model alone. If final has a halo but deterministic baseline is crisp, inspect `surface.transfer` and `pipeline.composite`. If deterministic baseline already has bad characters, fix PDF/Figma rasterization or source scale **before** using Nano Banana.

## 6. Definition of done
- The Step 2 default output looks like a real, very clean printed die-cut sheet on black, not a frosted-plastic or glowing effect.
- The package outline, cuts, folds, text, branding, and gradient are deterministically sourced from Figma and independently QA'd.
- Nano Banana Pro remains optional for appearance/reference scenes; it can **never repaint precise source typography or redraw structural geometry**.
- Old Step 3 folded handling remains untouched unless a separate test suite shows it benefits.
- Deliver before/after images, closeups, tests, and a short explanation of any remaining limitations.

## Instruction to the coding agent
Read this document plus `README.md`, `CLAUDE.md`, `backend/app/services/pipeline.py`, `backend/app/render/shading.py`, `backend/app/render/surface.py`, `backend/app/render/layers.py`, and `backend/app/render/look.py`. Implement P0 and P1 first with tests and diagnostic outputs. Demonstrate a crisp deterministic result before introducing optional AI appearance mode. Preserve all Figma data and user-confirmed classifications. Do not claim the fix succeeded until the actual sample is compared at 100% and 400% zoom.
