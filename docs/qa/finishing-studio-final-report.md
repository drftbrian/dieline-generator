# Finishing Studio: stabilization final report

- **Branch:** `fix/finishing-studio-stabilization`, based on `feat/asset-based-finishing-studio`
  at `d119806`.
- **Not merged** into the base branch or `main`. Section 9 is the final production-safety review.
- **Details:** `finishing-studio-audit.md` (issues) and `finishing-visual-validation.md`
  (render fidelity).

## 1. Issues found

The audit table lists 15 items:

- **Confirmed:** 13, of which 4 are P0, 6 are P1 and 3 are P2.
- **Not confirmed:** 1. A Figma re-import cannot serve stale geometry, because there is no
  in-place re-import: every import is a new project with an immutable source.
- **Measured, left as a known limitation:** 1 (a whole-sheet finish at 4K is heavy).

The confirmed P0 and P1 issues, with code references:

- **P0:**
  - `plates.build` drew panel targets as their bounding box, and did not clip asset or sheet art
    to the board or its openings. It drew the dieline into every plate on a "do not print" OCG,
    which still prints. It replaced Figma assets without an outline by a bitmap guessed from
    the printed ink, which the preview never shows.
- **P1:**
  - `masks.place_svg` relied on MuPDF, which ignores SVG `clip-path` and `mask`.
  - `spec.save` had a check-then-write race: 8 concurrent saves from one revision all returned
    revision 1.
  - Its writes were non-atomic.
  - `FinishingSync` threw away unsaved edits on a 409.
  - Cache keys did not depend on the outline content, the node boxes or the spec version.
  - A removed target was skipped silently, and blocked every later save.

## 2. Fixes implemented

| Commit | Files / functions | Why |
|---|---|---|
| `2047132` P0 | `finishing/plates.py`: `board_outline`, `_loops`, `_simplify`, `_clip_to`, `_to_k`, `_dieline_pdf`, `build`, `plate_coverage` | A plate is clipped to the same board silhouette as the preview (`render.layers.board`, openings included) plus 1 mm bleed, as a vector clip path. Panels are box ∩ board. Plate art is 100% K. The dieline goes into its own `dieline.pdf`. Missing outlines are listed in `missing_targets`, never guessed. |
| | `finishing/svgclip.py` (new), `masks.place_svg`, `masks.svg_exact` | SVG clip-paths and masks are split into pieces, each drawn clipped to its box. Box clips are exact; other shapes are approximated and reported (`approximate_assets`, `MASK_APPROXIMATE`). The preview and the plates share this code. |
| | `masks.asset_mask` | The cache key includes the SVG hash, the box, the clip and the colour. |
| `fbe71f7` P1 | `finishing/spec.py`: `save`, `_save`, `_lock`, `_write_atomic`, `load`, `_latest_revision`, `validate` | A per-project lock, plus an exclusive `rev-N.json` claim via `os.link` (also safe across processes), plus atomic `finishing.json`. `load()` adopts the newest revision file after an interrupted save. Saved targets whose node vanished stay on their own assignment but cannot be added anywhere else. |
| | `api/finishing.py`: `_source_key`, `save_finishing` | Overlay, sweep and warnings caches are keyed by structure, spec version and the asset-geometry stamp. |
| | `finishing/assets.py`: `_check_version`, `geometry_stamp`, `VERSION_FILE` | The tree and outlines are stamped with their Figma file version and dropped on a mismatch. |
| | `finishing/constraints.py` | `TARGET_MISSING` (error) and `MASK_APPROXIMATE` (info) per assignment. |
| | `src/stores/useFinishingStore.ts`, `FinishingSync.tsx`, `FinishingAssign.tsx`, `i18n/ko/studio.ts` | A 409 keeps the working list. The panel says another tab saved first and offers 내 변경으로 저장 / 최신 불러오기. |
| P2 (QA commit) | `render/finishing/material.py`: `_tint`, `metal` | Gold uses the measured photo body colour. It now has chroma 0.13–0.28 per tone band (photos 0.10–0.33), where it had 0.12–0.62. |
| | `services/finish_realism.py` `REFERENCE_WORDS` | Gloss and matte lamination and flood UV now find their study photos. |
| | `finishing/plates.py` `compare`, `scripts/finishing_e2e.py` | A reproducible plate ↔ preview comparison, and the end-to-end regression on a data copy. |

Untouched: Figma import, text/font/logo extraction, dieline geometry, the deterministic flat
render (v1–v4 checksums pinned in tests), AI appearance/enhancement, undo/redo, project storage.

## 3. Test results

- **Backend (`pnpm test:api`):** **241 passed, 0 failed, 0 skipped** (5:40) at the stabilization commit; **245 passed** after the final review (section 9). That includes the new
  `test_finishing_plates.py` (7), `test_finishing_reliability.py` (10) and 2 new regression
  tests; one existing plate test was updated to the new, intended behaviour (separate dieline,
  K fill).
- **Ruff:** check and format clean.
- **Frontend:** `pnpm typecheck`, `pnpm lint` and `pnpm build` pass. The repository has no
  frontend unit-test runner.
- **Regression proof:** the new tests were also run against the old modules. 6 of the 7 plate
  tests and 2 of the save tests fail on `d119806`.
- **Zentra end-to-end** (`scripts/finishing_e2e.py` on a scratch copy of `prj_b8fca58bfcd4`,
  version `ver_f20dfed3e319`, logo `23:832`, emboss `27:1296`, spot UV `27:1292`): 29 of 29 checks pass (`report.json`: `"pass": true`).

| Scenario | What passed |
|---|---|
| A | Gold changes only pixels inside the logo mask and covers ≥98% of it. |
| B | The emboss stays on the shape plus its shoulder, with a lit and a shaded side. |
| C | Gold + emboss on the logo and spot UV on the badge: nothing outside them changed. |
| D | Reload returns the same revision and assignments. Undo/redo (as saves) gives identical pixels. Removing every finish gives the version image bit for bit. |
| E | An edited outline gives a new (narrower) preview, and restoring it gives the original. A removed node is reported (`TARGET_MISSING`), nothing is drawn for it, and nothing is reattached. |
| F | Every plate equals the preview inside the board (`wrong_px` 0, IoU 1.0) and stays within the bleed. Plates have no layers and use K, not RGB. Every PDF is the source page size (512 × 288 mm). |

The source PDF, the version image and all cached outlines had unchanged hashes afterwards.

- **Browser** (QA instance on the copy, headless Chrome): another "tab" saved revision 43 while
  the page removed a finish.
  - The panel showed "다른 탭에서 먼저 저장했습니다 (리비전 43). 내 변경은 그대로 있어요." with
    both buttons, and the working list kept the edit.
  - "내 변경으로 저장" saved revision 44 with the user's list.
- **Skipped:**
  - No real Gemini or Figma calls; the fakes were used.
  - Undo/redo was exercised through the API and through store logic, not by pressing ⌘Z in the
    browser.

## 4. Visual comparisons

See `finishing-visual-validation.md`.

- **Gold before and after:** the Zentra logo crops `gold_before.png` / `gold_after.png` are in
  the session scratchpad (`stab/evidence/`).
- **Gallery:** 26 finishes × top/raking light next to the photos, in `gallery_v2/`. It is not
  committed, because it contains the study photos.
- **Changed:** only gold.
- **Documented with a recommendation:** holographic (dull dark end), raking emboss (hard bevels)
  and spot UV (lightens where photos show contrast). These were not changed without a measured
  crop.

## 5. Export validation

- **Method:** `plates.compare(pid, spec, vid, fin)` rasterises each plate PDF on the version's
  own pixel grid and compares it with the preview's union mask for that finish. It reports
  `wrong_px` (disagreement inside the board, away from the 2 px anti-aliased edge),
  `beyond_bleed_px` and `iou`. Plates are at real size, so it maps them back by
  `physical_factor` first.
- **Tolerance:** the bleed edge is a traced outline, accurate to `OUTLINE_TOL_MM` (0.19 mm).
  That tolerance only moves the outer edge of the bleed, outside the product.
- **Covered by tests:**
  - A ring with a counter (text-like holes) and a group.
  - An asset clipped by its frame.
  - Two assignments of one finish.
  - Every panel of an irregular carton (tuck and dust flaps).
  - A sheet target, and a window cut through a logo and its panel.
  - SVG clip-paths and masks, and a missing outline.
  - Real size (a 0.2667 mm/unit ruler gives a plate 16.0 mm wide for a 60-unit ring).
  - Self-check failures: wrong page size, layers, RGB paint, no K.
- **Zentra:** `foil.gold`, `relief.emboss`, `coating.spot_uv` and `surface.matte_lamination`
  all had `wrong_px` 0, `beyond_bleed_px` 0 and IoU 1.0 at 10.36 px/mm. In the visual overlay
  `F_gold_plate_vs_preview.png`, white means both agree; it has no red or cyan pixels.
- **PDF structure on Zentra** (as a PDF reader measures it; points are 1/72 in):
  - Every plate and `dieline.pdf` is **512.0 × 288.0 mm**, the carton's size from its
    dimension marks.
  - One page each, no optional-content layers.
  - Fills `0 0 0 1 k`, no RGB operators, no embedded images.
  - The dieline is separate.
  - The manifest's `status` is `exact_geometry_needs_printer_preflight`, and every plate's
    `self_check` is `passed`.
- **Not verified by a person:** opening the files in Illustrator or Acrobat, or sending them to
  a RIP. The procedure is in section 9.

## 6. Remaining limitations

- **Performance:** a whole-sheet finish at 4K takes about 10–12 s cold and 4–7 s per edit, with
  2.4–2.7 GB peak memory. This is unchanged from `d119806`.
- **Plate export time:** about 1 s, because the board is traced.
- **Registration with the source PDF:** plates are written at real size. For a Figma source
  (pixels), overlaying a plate on the *original source PDF* needs that PDF scaled by
  `physical_factor` (Zentra: 0.7559). Plates register with each other and with `dieline.pdf`
  as they are.
- **Real size depends on the ruler:**
  - It comes from the project's ruler (dimension marks or a user value).
  - A guessed ruler (a Figma project with no marks) blocks a production export, as does a weak
    one (dimension marks below 0.9 confidence; the synthetic fixture reads 0.75).
  - The user then confirms mm per unit in the structural review.
- **Approximated clips:** non-rectangular SVG clips and masks are approximated by their box,
  which blocks a production export. Nested transforms are supported; CSS-class styling in SVGs
  is not.
- **Ignored SVG effects:** filters such as drop shadows are ignored in both the preview and the
  plates, which is right for finishing.
- **Glue flap:** still found by panel name only.
- **No in-place re-import:** a changed Figma frame is a new project, and finishing assignments do
  not carry over.
- **Unvalidated looks:** finishes without photo evidence (epoxy/PU dome, raised UV, soft-touch,
  satin/matte varnish, uncoated) are modelled, not validated.
- **New gold look:** gold now reads paler (champagne), as in the photos.

## 7. Visual simulation vs. manufacturing specification

| What | What it is | Verified by |
|---|---|---|
| The preview, light sweep and finished versions | **Visual simulation.** Material looks with tone levels from a few study photos. They show *where* finishes go exactly, and *how they look* only approximately. | Gallery comparison (section 4, visual validation doc). Not a colour or gloss proof. |
| AI 사실감 | **Visual simulation.** It may only adjust light inside the masks, and is dropped unless closer to the photos. | Automated checks only. |
| Manufacturing checks (line width, gaps, distances, glue flap, combinations) | **Advice** from research defaults. | Not a printer's specification. |
| Plate geometry (shape, position, real size, cut-outs) | **Exact source geometry**, automatically checked against the preview and the source. | Tests + Zentra E2E + `self_check`. |
| Plate suitability for production (bleed amount, trapping, minimum line width, foil/die tolerances, emboss depth, coating order, colour/ink setup) | **Not verified.** | Only the printer / die maker, with a physical proof. |

## 8. Manufacturing disclaimer

- **What the app shows is a visual simulation.**
- **The plates are working files with registered vector geometry.** They are not a verified
  production specification.
- **"Exact geometry" means exactly that:** the shapes are the source's. It is not production
  approval.
- **A DRAFT export must never be used for production.** It is marked in every file name, in the
  PDF title and subject, in `finishing.json` (`status`) and in `README.txt` / `PREFLIGHT.txt`.
- **Before production,** the printer must confirm the plates, bleed, emboss depth, foil choice and
  coating order against their process and a physical proof.
- **Passing tests proves only consistency:** the preview and plates agree with each other, with
  the source and with the ruler. It does not prove a manufactured result.

## 9. Final production-safety review

### Findings in this review

1. **Unverified geometry could be exported as if final.**
   - **Before:** plates with approximate or missing geometry were listed only in
     `finishing.json`.
   - **Now:**
     - `GET /finishing/preflight` lists every approximate or missing target and an unverified
       ruler.
     - A production export is refused with **409 `PLATES_NOT_VERIFIED`**, and the panel shows
       the reasons in red.
     - The only other export is `?draft=true` (button "검토용 초안 받기 (생산 불가 · DRAFT
       표시)"), marked DRAFT everywhere.
     - Every plate also passes `self_check` (size, single page, no layers, K only, no images)
       or the production export fails with 409 `PLATES_SELF_CHECK_FAILED`.
     - The preview is unchanged.
2. **P0, found in this review: plates were not at physical size for Figma sources.**
   - **Cause:** Figma pages are in pixels. Zentra's page is 1920 × 1080 units, which a PDF
     reader reads as **677.3 × 381.0 mm**, while the carton (dimension marks, 0.2667 mm/unit) is
     **512 × 288 mm**. Every plate and the dieline would have been made 1.32× too large.
   - **Why the earlier check missed it:** it multiplied PDF points by the project's own ruler,
     the same wrong conversion the plate used.
   - **Now:** plates and `dieline.pdf` are written at real size (`physical_factor`). The E2E
     measures them as a PDF reader does: 512.0 × 288.0 mm. A guessed or weak ruler blocks a
     production export.
   - **Covered by:** `test_plates_are_written_at_real_size_and_need_a_confirmed_ruler`.

### Regression verification
- **Backend:** `pnpm test:api` **245 passed, 0 failed, 0 skipped** (5:34); ruff check and format clean.
- **Frontend:** `pnpm typecheck`, `pnpm lint` and `pnpm build` pass.
- **Branch scope:** it changes only finishing code, tests and docs (`git diff d119806 --stat`).
  Nothing changed in `figma/`, `pdf/`, `render/layers.py`, `render/shading.py`,
  `render/folds.py`, `services/pipeline.py`, `services/merge.py` or the AI code.
- **Deterministic renders unchanged:**
  - On a copy of Zentra, the deterministic v4 flat render was produced again with this branch.
    It is **pixel-identical** (max difference 0) to `ver_f20dfed3e319`, made earlier with the
    same settings.
  - v1–v4 checksums stay pinned in `tests/test_flat_render.py`.
- **Source unchanged:** the source PDF and existing version images had identical SHA-256 hashes
  before and after (E2E and determinism runs). Finishing never writes to the source, the Figma
  tree, or a render.

### Manual preflight: Illustrator
1. Unzip, and open `dieline.pdf` and one plate. In *Document Setup*, the artboard must equal
   `finishing.json` → `page_mm` (Zentra: 512 × 288 mm).
2. *File → Place* the plate onto `dieline.pdf` at (0, 0) at 100%, or paste in place. The art
   must sit inside the cut line, with no more than `bleed_mm` (1 mm) past it, and windows must
   be open.
3. *Window → Separations Preview*: only **Black** shows ink, at 100%. No C/M/Y and no spot
   colours on a plate.
4. *Window → Document Info → Linked/Embedded images*: none, unless the file is a DRAFT.
5. *Layers*: no hidden layers; the plate holds only the finish art.
6. Zoom 400% on small text and thin lines; compare against the manufacturing checks' warnings.
7. Check that file names, titles and `finishing.json` → `status` contain no `DRAFT`.

### Manual preflight: Acrobat Pro
1. *Document Properties → Description*: page size = `page_mm`; title without "DRAFT".
2. *Print Production → Output Preview*: Separations show only Process Black; Total Area
   Coverage stays at 100% max.
3. *Print Production → Preflight* → PDF/X-4 or the printer's profile → *Analyze*. Expected:
   no RGB, no transparency issues, and the one page. Missing OutputIntent / TrimBox warnings
   are expected, because the plate carries no print profile. The printer sets those.
4. *Layers panel*: empty.
5. Overlay check: *Compare Files* of a plate against `dieline.pdf`, or print both on film and
   overlay them.

## 10. Merge recommendation

**READY WITH KNOWN LIMITATIONS** (into `feat/asset-based-finishing-studio`)

- **No blocking issue remains.**
  - The plates are exact source geometry, at real size, in 100% K, clipped to the board with
    openings, with a separate dieline.
  - Anything unverified (approximate or missing geometry, an unconfirmed ruler, a failed
    self-check) cannot be exported for production, only as a clearly marked DRAFT.
  - Saves are race-free, and the deterministic renders and sources are unchanged.
- **What keeps it from "READY":**
  - No person has yet opened the plates in Illustrator/Acrobat or with a printer (procedure
    above).
  - Several finishes have no photo evidence.
  - A whole-sheet finish at 4K is slow.
