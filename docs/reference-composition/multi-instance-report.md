# Multi-instance structural composition: report

- **Branch:** `feat/multi-instance-reference-composition`, from `feat/structural-reference-composition`
  (M1–M3).
- **Not merged.**

## 1. Root cause of the shadow inversion (legacy ③)

Measured on the failing Zentra merges (`prj_3bd9b756ddb2`, five `ARTWORK_MISMATCH` runs on the
SEREN three-box reference).

- **What fails:** only the colour gate. The overall ΔE is 3.4–4.4 against a limit of 3. Detail
  match (0.997), print residual (0.5 levels) and ghosting (< 0.3) all pass.
- **What changed:** Gemini's raw picture darkened the package with the leaf shadows (median
  luminance 0.88 of the print). The legacy composite *brightened* it: median 1.04, and 27% of
  the package more than 8% brighter.
- **Why**, in `backend/app/render/surface.py` `transfer()`:
  - **l.175, exposure-neutral normalisation:** `light /= median(light)`. A darkened box becomes
    "too bright" everywhere outside the shadows.
  - **l.176, clamp to `LIGHT_RANGE` (0.92–1.06):** a 0.57 shadow is lifted to 0.92, and the lit
    areas are capped at 1.06. The shadow nearly vanishes.
  - **l.178–179, zero-mean "detail" over a 4 mm window:** next to a shadow edge the local mean is
    pulled down, so the lit side reads > 1. These are the glowing fringes.
  - **l.181, edge band up to `EDGE_RANGE` 1.4:** the white frame around faces.
- **Conclusion:** the verify gate was right to reject these results. The legacy light model can
  only represent soft studio light, so every retry of a reference with hard cast shadows fails.
  Legacy ③ is kept unchanged (Mode A, for comparison).

## 2. What the new mode does (Mode B, "구조 합성")

### Pipeline (deterministic first)
1. **Structure** (M2/M3): the confirmed dieline is folded into a rigid carton. An unsupported
   structure gets a 409 with reasons.
2. **Instances:** one per package of the reference, each the image quad of its most visible face
   (≤ 1 hidden corner), plus a height for its removal outline.
   - Claude proposes them: `POST …/scene/detect`, prompt `prompts/reference_instances.md`.
   - The user confirms, edits, adds, disables or deletes them in the panel (corner drag,
     rotation, position, height).
   - They are stored per reference: `refs/<rid>_scene.json`.
3. **Camera and poses** (`app/scene/geometry.py`):
   - **Focal length:** the median over the rectangles' orthogonality constraints.
   - **Face plane:** each face's plane, centre and axes from the homography.
   - **Hidden corners:** completed in 3D from the shared ground normal (stacked lids are
     parallel).
   - **Our carton** is posed rigidly on each face with **one shared size**, so relative scale is
     kept and our proportions are never distorted.
   - **Instances are independent copies:** the z-buffer resolves overlap and stacking.
4. **Rendering** (`render/structure3d.rasterize`):
   - A z-buffer over planar panels of all instances.
   - Per pixel: instance, panel, outside/inside face, the point on the flat net, normal and
     depth.
5. **Layers** (`app/scene/compose.py`), multiplied only at the end:
   - **albedo:** the approved flat render (any finished version: foil, UV etc. come along)
     sampled through the flat-net point. Inside faces are plain board.
   - **direct light:** Lambert on each face normal, with the key light derived from the photo
     (see below).
   - **visibility:**
     - **The photo's own shadow field**, in screen space: luminance over the lit level of the
       surface it is on. The reference packages' printed text is removed first with a grey
       opening, and the lit level is measured over a quarter of the image so wide shadows
       survive.
     - **Our cartons' cast shadows on each other:** a light-space depth map of our geometry.
   - **light colour:** one constant from the reading's colour temperature ("warm"). It never
     varies over the package, so it cannot read as print.
   - **background:**
     - The reference's packages are removed (convex hull of each face, grown 3% in its plane,
       plus its height, plus 1%) and filled with the lit ground colour × the surrounding
       shading carried in, with a feathered edge.
     - Our cartons' ground shadow (the same depth map, intersected with the ground plane under
       the lowest carton) and a soft contact darkening are added.
   - **Composite:** `package = albedo × illumination × tint`, anti-aliased at the silhouette.
6. **Light estimation (no guess):**
   - **Azimuth:** from the reference's ground shadow, where the shadow the packages cast lies
     on the ground plane in 3D. The light is on the opposite side. Fallback: the reading.
   - **Elevation and ambient:** fitted to the reference packages' own shading (wall vs lid) and
     their lid shadow depth (shadow / lit = ambient / (ambient + (1 − ambient)·cos)).
   - **On SEREN:** azimuth 54.5° from the ground shadow (the reading said 45°), elevation 15°,
     ambient 0.25.
7. **Verify** (`verify_structural`):
   - `package == albedo × light` (residual 0).
   - The light carries no print: neither ours (correlation < 0.3) nor the reference packages'
     (`reference_print_leak` < 0.15, a white top-hat of the photo against the light's detail).
   - Light within 0.05–1.3.
   - **Deep shadows pass, because they are light.**
8. **Optional AI** (`harmonize`, Gemini, prompt `prompts/scene_harmonize.md`):
   - Only a smooth, bounded (0.75–1.2) achromatic light map is taken on our cartons, and only
     the model's ground inside the removal mask, unless it has 2.5× more structure than its
     surroundings (a new object).
   - A failure, timeout or failed check keeps the deterministic precomposition. The version
     never fails because of AI.
9. **Saved separately per version:**
   - `<vid>_structure.png` (deterministic)
   - `<vid>_raw.png` (model)
   - `<vid>.png` (delivered)
   - `<vid>_layer_*.png`: removal mask, background, albedo, lighting, shadow only, photo shadow
     field, cast shadow, ground shadow, placement
   - `<vid>_report.json`
   - Served at `GET …/versions/{vid}/layers/{name}`.

### API
- `GET|PUT /projects/{pid}/references/{rid}/scene`
- `POST …/scene/detect` (Claude)
- `GET /projects/{pid}/compose/preview?reference_id&flat_version_id&layer` (deterministic,
  1024 px; `X-Compose-Report`)
- `POST /projects/{pid}/compose` (`{reference_id, flat_version_id?, harmonize, strength}`):
  a job with stages `structure → compose → model → verify`.
- `GET /projects/{pid}/versions/{vid}/layers/{name}`

### UI (③, `src/features/merge/StructuralCompose.tsx`)
- **Mode switch:** 구조 합성 (권장) / 기존 AI 합성 (unchanged legacy).
- **Structure status:** type, W×D×H, and the unsupported reasons when there are any.
- **Packages:** "패키지 찾기 (AI)", a corner editor on the reference (drag; a dashed point is a
  computed hidden corner), and per package: enable, rotation, position along the long and
  short side, removal height, add, delete.
- **Scene:** shared size, shadow strength, and light (automatic from the photo's shadow, or
  manual azimuth/elevation).
- **Preview without AI**, by layer: composition, folded placement, removal area, background
  without packages, light/shadow, print.
- **Actions:** "구조 합성 저장 (AI 없음)", and "AI로 장면 다듬기" with a strength slider.

## 3. Three-package case (SEREN reference, Zentra)

**Before** (legacy, rejected): Gemini drew one carton filling the frame. The composite's shadow
was washed out, with a white frame. 5/5 runs were rejected.

**After** (deterministic, no AI, 5 s at 2048 px):
- Three independent folded Zentra cartons on the three box positions, in the reference's
  stacking order and camera (estimated lens ≈ 74 mm 35-eq).
- Correct print orientation; leaf shadows dark on the lids.
- Ground shadow toward the lower left, as in the photo.
- `reference_print_leak` 0.010: no SEREN lettering in the light.

**Diagnostics:** reference, instance quads, removal mask, background, placement, albedo,
shadow-only, lighting-only, precomposition, the old raw/rejected, a montage and before/after.
They are saved locally only (the reference photo and the design are not ours to commit).

**Honest assessment:**
- **Structure and placement are faithful;** the print is exact.
- **The look is not yet a finished photograph:**
  - The walls in shadow are very dark (ambient 0.25).
  - Our white carton keeps the light model's plain shading, with no bounce light or subsurface
    warmth.
  - The deterministic ground fill where the old boxes stood is smooth and featureless.
  - A few small slivers of the old boxes can remain where the hand-placed corners were
    imprecise. The removal area grows 3% + 1%; the rest is for the corner editor or the AI
    removal pass.
- **Not yet run with the real models:** Claude detection and the Gemini harmonization. Both are
  implemented and tested with fakes (timeout, garbage output). A real run costs money, and I
  will start it only with the user's go-ahead.

## 4. Tests

`tests/test_structural_compose.py`: 14 tests on synthetic references with known package
corners and a dark shadow band.
- Three packages become three cartons, each on its package, with no kraft left.
- **Dark shadows stay dark on our cartons:** under the band below 0.75× the outside, and never
  brighter (no inversion).
- **No reference print leaks into the light.** With the print removal disabled, the leak check
  fires.
- One and two packages.
- An environment-only reference with a user-placed carton, which casts a ground shadow.
- The albedo is the approved render.
- An unsupported structure is refused with 409.
- The job stages and every saved intermediate.
- The AI timeout and garbage-output fallbacks.
- Scene validation.
- A Claude detection proposal is saved for confirmation.

Plus M2/M3: `test_structure_topology.py` (13) and `test_structure_fold.py` (15). Full-suite
results are in the commit message.

## 5. Remaining limitations

- **Camera:** one pinhole camera; the focal length comes from the face rectangles, which needs
  at least one face with all four corners.
- **Shadow transfer:** the photo's leaf shadows are transferred in screen space. That is right
  where our surfaces are close to where the old ones were; a carton much taller than the
  reference's gets the floor's or its neighbour's shadow pattern.
- **Self-shadowing:** our own inter-carton and ground shadows come from the 3D light, but the
  shading model is plain Lambert (no bounce or ambient occlusion beyond the contact
  darkening).
- **Pose fitting:** a taller carton than the reference (Zentra 0.37 vs a mailer at 0.17) stands
  above the old one's base. It overlaps the carton below and is hidden by the z-buffer; there is
  no physical stacking solve.
- **Removal:** deterministic removal is a smooth fill. Realistic texture where the old packages
  stood needs the AI pass, or a reference where our cartons cover them.
- **Finishes:** they come in through the approved (finished) flat render as colour. Foil's
  view-dependent reflection is not re-lit in 3D yet.
- **Crash-lock bottom:** closed-state approximation only (decision B1).
