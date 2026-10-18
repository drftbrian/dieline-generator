# Structural reference composition: current system audit (M1)

- **Branch:** `feat/structural-reference-composition`.
- **Base:** `feat/asset-based-finishing-studio` at `2a65904`.
- **Why that base:** PR #1 merged into it, and it contains every other feature branch. `main`
  (`7daa614`) is behind it and does not contain the finishing studio or the v4 look.
- **Working tree:** clean at branch creation.

## What exists and can be reused

| Area | Where | What it gives | Reuse |
|---|---|---|---|
| Line semantics | `spec.paths` (`StructuralPath.cls`: cut / crease / artwork / annotation / finish / bleed; `status` auto / unresolved / confirmed), set by `pdf/dieline.py` + structural review (`PATCH /specification`, `confirm`) | Confirmed cut vs crease per path, as flattened polylines in page units | **Authoritative input.** The new code reads only `cls`; it never reads colour. |
| Board silhouette | `render/layers.board` (outer cut minus closed inner cut loops) | Board mask incl. openings | Panel labelling. |
| Panels | `pdf/analyze.find_panels` | Regions between cut and crease lines, **bbox only** (no polygon, no adjacency), names from Claude (`name_provenance`) | Ids and names. Polygons and adjacency are new (M2). |
| Physical scale | `spec.scale` (dimension marks / user), `spec.box` (title text "100*52*141") | mm per unit; a stated size for cross-checks | Units for 3D (M3), plus a dimension check. |
| 3D carton (legacy) | `render/carton3d.py` | A **6-face cuboid**: faces chosen by panel **name regex** or bbox heuristics (`map_faces`), size from the title text or bboxes, pinhole camera, exact planar homography texture mapping, painter's order | Camera/projection and homography sampling can be reused for M3/M4. Face guessing, cuboid-only shape and the missing flaps are **not** reused for the new mode. |
| Legacy merge (③) | `services/merge.py` `run_merge` | Claude reads the reference (camera az/el/lens/placement, light). Gemini paints the scene from Image A (our posed cuboid), B (reference) and C (flat). Print is composited back per face (`composite`, `surface.transfer`), then `pipeline.verify` and `deliver`. | Stays as **Mode A**. Its reference reading, `surface.transfer` and the verify/deliver gate are reusable in M5/M6. |
| Flat render | `services/pipeline` (deterministic v1–v4) | The approved print, with `frame_json` mapping page units ↔ pixels | **Texture source** (M4). |
| Finishing | `finishing/compose` (masks on the flat frame), finished versions (`flat_mode: "finished"`) | Finish masks per asset in flat-frame pixels; finished renders usable in ③ | M4 maps them per panel. |
| Jobs | `jobs/runner` (stages, cancel flag, progress, orphan reaping) | Background jobs with stages | M5/M6 jobs. |
| Versions | `versions` table + `versions/<vid>*.png` | Per-version images and settings (`scene_json`, `settings_json`) | Store deterministic and harmonized outputs separately. |
| Frontend ③ | `src/features/merge/MergePanel.tsx`, `ReferenceDrop`, `ReferenceReading` | Reference upload, Claude's reading, form 자동/평면/입체, flat-version picker | Mode switch A/B (M7). |
| 3D libraries | — | None in `package.json`. The backend has numpy, scipy and PIL; no GL. | Architecture decision below. |

## What is missing (to implement)
- **M2 (done on this branch):**
  - Panel polygons, a panel adjacency graph (folds) and cut contacts.
  - Structure validation and carton recognition.
- **M3:**
  - Real hinge folding (panel-local frames, fold transforms, fold angles), driven by the graph
    rather than by face guessing.
  - Closure validation and intersection checks.
  - Pose presets.
- **M4:**
  - Per-panel texture mapping with outside/inside faces (inside = unprinted board).
  - Finishing masks per panel.
- **M5:**
  - Reference scene analysis with confidences and user correction.
  - A ground plane, placement, contact shadow and object removal (mask + inpaint).
  - A deterministic pre-composition saved on its own.
- **M6:** constrained AI harmonization with protected geometry and print, and a fallback.
- **M7:**
  - The UI (Mode B controls).
  - Comparison, export, QA and performance work.

## Findings during the audit
1. **The legacy mode guesses structure.**
   - `carton3d.map_faces` matches panel names (Claude-inferred) with regexes, or picks the
     "right-most wide" body panel as the front.
   - It ignores flaps, dust flaps and tucks.
   - Dimensions come from the title text when present.
   - This is the behaviour the new mode must not inherit.
2. **Panels had no polygon or adjacency.** Fold relationships existed only implicitly in the
   crease polylines. M2 adds them.
3. **One crease polyline can hinge several panel pairs.** Zentra's `p49.90` runs along the whole
   bottom edge (back, side, front, side). The topology splits it into one fold per pair.
4. **Zentra's tuck hinge is stepped.** It is drawn as a long crease at y=133.8 and two short
   pieces at y=129.3 (1.2 mm off). It is reported (`FOLD_NOT_COLLINEAR`), and the long line is
   the axis.
5. **Two "creases" do not separate panels.** Zentra `p49.71` and `p49.77` (3.7 mm vertical, at
   the lid's tuck corners) end inside the lid. They are most likely tuck-lock slits classified as
   crease. They are reported (`CREASE_INSIDE_PANEL`), not used as hinges, and need a human look.
6. **Zentra's bottom is a crash-lock (auto) bottom.**
   - It has diagonal creases (`p49.88`, `p49.89`) splitting glued triangles off the two W-side
     bottom flaps.
   - Per the command, crash-lock folding is **not claimed**. The structure is recognised and
     marked unsupported.
   - Zentra therefore cannot be fully folded until a decision is made (see
     `../reference-composition/plan.md`, blocker B1).
7. **Product rule conflict.** `CLAUDE.md` says "Keep it 3 steps. No library, … scene builder …".
   Mode B lives inside ③, but its placement and environment controls are scene-builder-like.
   This needs the user's confirmation to amend the rule (blocker B2).
