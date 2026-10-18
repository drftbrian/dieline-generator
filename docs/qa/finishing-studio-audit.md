# Finishing Studio: stabilization audit

Branch `fix/finishing-studio-stabilization`, from `feat/asset-based-finishing-studio` at
`d119806` (M7). The audit was done on 2026-10-17/18. Every issue below was checked against the
code at that commit and, where marked "reproduced", by a test that fails on `d119806` and
passes after the fix.

Severity:

- **P0**: incorrect output, corrupted data, or an unsafe production export.
- **P1**: reliability, consistency, or a major functional problem.
- **P2**: visual polish, usability, or a minor improvement.

## Summary

| # | Sev | Issue | Status |
|---|-----|-------|--------|
| 1 | P0 | Panel plates are the panel's bounding box, not the board | reproduced, fixed |
| 2 | P0 | Asset plates are not clipped to the board; openings are ignored | reproduced, fixed |
| 3 | P0 | The dieline is drawn on every plate (OCG "do not print" still prints) | reproduced, fixed |
| 4 | P0 | A Figma asset with no outline is guessed from printed ink on the plate only | reproduced, fixed |
| 5 | P1 | `clip-path` and `mask` inside Figma SVGs are ignored (preview and plates) | reproduced, fixed |
| 6 | P1 | Concurrent saves from one revision all succeed (silent loss) | reproduced, fixed |
| 7 | P1 | Non-atomic JSON writes; no recovery after an interrupted save | confirmed by reading, fixed |
| 8 | P1 | The frontend discards unsaved edits on a 409 | confirmed by reading, fixed (browser-checked) |
| 9 | P1 | Mask, preview, sweep and warnings caches are not keyed by the geometry or spec version | confirmed by reading, fixed |
| 10 | P1 | Removed or unexported targets are skipped silently; one lost node blocks every save | reproduced, fixed |
| 11 | P2 | Plate art is DeviceRGB black, not 100% K | confirmed, fixed |
| 12 | P2 | Gold foil is about 2.5× more saturated than the measured photos | measured, fixed |
| 13 | P2 | Lamination and flood-UV study photos never reach AI 사실감 | confirmed, fixed |
| 14 | — | "Re-import into the same project serves stale geometry" | **not confirmed**, see below |
| 15 | P2 | A whole-sheet finish at 4K is heavy (4–7 s per edit, about 2.5 GB) | measured, not fixed (known limitation) |

## Details

### 1. P0: panel plates leave the carton outline
- **Where:** `backend/app/finishing/plates.py` `build()`, the `t.kind == "panel"` branch.
- **Root cause:** It ran `page.draw_rect(Rect(*panel.bbox))`. The preview (`compose.target_mask`)
  uses the box multiplied by the board silhouette. On `named_spot` the tuck and dust flaps are
  not rectangles, so the plate covered waste board outside the cut.
- **Reproduce:**
  `tests/test_finishing_plates.py::test_panel_plates_follow_the_irregular_outline` and
  `::test_plates_match_the_preview_for_assets_panels_and_sheet` (both fail on `d119806`).

### 2. P0: asset plates ignore the board and openings
- **Where:** same function. Sheet targets used `_sheet()`, which fills the raw cut polylines
  even-odd. That is not the silhouette rule in `render.layers.board()`: the outer outline may
  be open pieces, an outlined stroke counts as board, and so does a flap loop on the edge.
  Asset SVGs were not clipped at all.
- **Reproduce:** `::test_openings_are_cut_out_of_every_plate` adds a window through the logo
  and its panel.

### 3. P0: the dieline prints on the plates
- **Where:** `plates._dieline()` drew cut and crease lines into each plate on an OCG created
  with `on=True` and no print usage.
- **Root cause:** a visible OCG with no `/Usage /Print` prints by default, and RIPs that ignore
  OCGs print it anyway. Rasterising the old plates put the crease dashes inside the finish area.
  In the old-code run, 7 px inside the board differed from the preview because of them.
- **Reproduce:** `::test_plates_register_on_the_page_in_k_without_the_dieline`.

### 4. P0: a guessed bitmap on the plate
- **Where:** `plates.build()` fell back to `_bitmap()` (printed-ink coverage) for any asset not
  in `svgs`, including Figma assets whose SVG export failed.
- **Root cause:** the preview (`compose.target_mask`) returns `None` for those assets ("never
  guessed from the printed ink"), so the plate held geometry the preview never showed.
- **Reproduce:** `::test_a_figma_asset_without_its_outline_is_reported_not_guessed`.

### 5. P1: clipping inside Figma SVGs is ignored
- **Where:** `masks.place_svg()` → `pymupdf.open(stream=svg, filetype="svg")`.
- **Root cause:** MuPDF's SVG reader draws `clip-path` and `mask` groups unclipped. A probe
  showed it: a disc clipped to its left half covered 0.787 of the box (the full disc) instead
  of 0.393. Figma exports a frame that clips its content, and a mask layer, exactly this way,
  so the finish covered hidden artwork in both the preview and the plate. Zentra's 151
  cached outlines happen to contain neither, so the bug was latent there.
- **Reproduce:** `::test_clip_paths_and_masks_inside_an_svg_are_honoured`.

### 6. P1: concurrent saves both win
- **Where:** `finishing/spec.py` `save()`: `load()` → compare revision → `write_text`, with no
  lock.
- **Root cause:** FastAPI runs the sync `PUT` handler in a thread pool. With 8 threads saving
  from revision 0 on the old code, all 8 returned revision 1; the last write won and 7 edits
  were lost silently.
- **Reproduce:** `tests/test_finishing_reliability.py::test_two_saves_from_the_same_revision_cannot_both_win`.

### 7. P1: non-atomic writes
- **Where:** `spec.save()` wrote `rev-N.json`, then `finishing.json`, with plain
  `write_text`.
- **Root cause:** A crash could leave a half-written file. If `finishing.json` lagged behind
  `rev-N.json`, the next save reused revision N.
- **Reproduce:** `::test_reload_after_an_interrupted_save_uses_the_revision_file` and
  `::test_a_failed_write_leaves_the_last_good_state`.

### 8. P1: a conflict throws away the user's edits
- **Where:** `src/features/finishing/FinishingSync.tsx`, the 409 branch called
  `hydrate(fresh)`, which replaced the working list and cleared undo, and then showed a toast.
- **Root cause:** the conflict was resolved for the user, always in favour of the server copy.

### 9. P1: caches not tied to the geometry
- **Where:**
  - `masks.asset_mask` keyed on `(pid, structure, long_edge, asset id, exact)`.
  - `api/finishing.py` `_cached` keys for the overlay, sweep and warnings used the revision plus
    `structure_key` only. `structure_key` hashes `(source_ref, cls)`, so it changes with neither
    panel names (the glue-flap check) nor the physical scale (`mm_per_pt`: relief depth, line
    widths).
  - Neither key depends on an outline's content or a node's box.
- **Reproduce:** `::test_a_changed_outline_refreshes_mask_preview_and_plates` and
  `::test_a_changed_text_node_box_is_followed`.

### 10. P1: missing targets
- **Where:**
  - `compose`, `plates` and `constraints` dropped targets whose node is gone, without a word.
  - `spec.validate` rejected the whole save while any assignment still named a removed node,
    so nothing else could be saved (the client reverted on 422).
- **Reproduce:** `::test_a_removed_node_is_reported_and_never_reattached`.

### 11. P2: RGB black plates
MuPDF writes `0 0 0 rg` for the recoloured SVG and the shapes, but the README promised
"검정 100%". A RIP may separate RGB black into four inks. The plates are now rewritten to
`0 0 0 1 k`.

### 12. P2: gold too saturated
- **Where:** `render/finishing/material.py` `_tint()` used the catalogue swatch `#D4AF37`
  (chroma 0.62), and `rich` doubled the tint in dark tones.
- **Measured:** on Zentra, the median chroma of the gold logo was 0.596. The local photos
  measure 0.10–0.33 per tone band, 0.237 for the body colour in `calibration.json`. See
  `finishing-visual-validation.md`.

### 13. P2: photo keywords
`finish_realism.REFERENCE_WORDS` had no entry for `surface.gloss_lamination`,
`surface.matte_lamination` or `coating.flood_uv`, although `후가공_유광코팅`, `후가공_무광코팅`
and `후가공_UV코팅` exist locally. Those finishes could not get photo references or appear in
the gallery.

### 14. Not confirmed: stale geometry after a Figma re-import
- **What was claimed:** some cache keys depend on project and node IDs without identifying the
  source revision, so a changed Figma frame that is re-imported reuses old geometry.
- **What the code does:**
  - There is no in-place re-import. `POST /projects/figma` (`api/figma.py` `_import`) always
    creates a new project id.
  - `repo.write_source_once` makes the source PDF immutable (it refuses a second write).
  - Every on-disk cache (`figma_assets.json`, `asset_svg/`) and every in-memory key includes the
    project id.
  - So an edited Figma frame becomes a new project with no finishing assignments, and no
    assignment can attach to new geometry.
- **Hardening anyway (item 9):**
  - Caches are keyed by content.
  - The tree and outlines are stamped with the Figma file version they came from
    (`figma_assets.version`) and dropped if it ever differs.
- **Simulation:** the E2E Scenario E edits an outline in place and removes a node, the closest
  equivalent to a re-import.

### 15. P2: whole-sheet finish at 4K
- **Measured:** five finishes, one of them a sheet matte lamination, on the 4096 px Zentra
  version.
  - Compose: 10–12 s cold, 3.9–7.4 s per edit.
  - Peak RSS: 2.4–2.7 GB.
- **Cause:** the work area becomes the whole image.
- **Not a regression:** the same script on `d119806` measured 9.8 s / 3.9 s / 2.7 GB. Left as a
  known limitation, because a fix would redesign `material.render` for tiles.

## How the audit was run
- `pnpm test:api` before and after.
- The new tests were also run against the old modules: 6 of the 7 plate tests fail on the old
  `plates.py`/`masks.py`, and 2 of the reliability tests fail on the old `spec.py`.
- `backend/scripts/finishing_e2e.py` ran on a scratch copy of the Zentra project; it refuses to
  run on `backend/data`.
- The browser conflict scenario ran on a QA instance (API :8001 on the copy, Vite :5174,
  headless Chrome).
