# Implementation plan, supported types, risks and blockers

## Milestones

| M | Deliverable | Validation gate |
|---|---|---|
| M1 ✅ | Audit (`docs/structural-composition/current-system-audit.md`), PRD, architecture, this plan | User review |
| M2 ✅ | `structure/topology.py`, `structure/carton.py`, `GET /structure`, `scripts/topology_diagram.py`, tests | Topology tests; Zentra + fixtures report (`m2-topology-report.md`) |
| M3 | Fold solver: a tree of rigid transforms from a root W panel. Each fold rotates its subtree about the crease axis by its angle (body 90°, lid 90°, tuck 90°, dust flaps 90° inward), with mountain/valley from `side_a` and the print side. Includes board thickness offset, closure check (lid edge meets the far W panel within tolerance; glue flap lands on the last body panel), intersection check (closure panels and dust flaps), fold states (closed / open top / partial) and pose presets. Preview via the server-side renderer. | **Stop for visual validation** (orbit renders at several poses, mm-accurate dims, closure residuals) |
| M4 | Per-panel textures from the flat render through `frame_json` (exact page → pixel). Outside = print; inside = unprinted board. Finishing masks per panel. Text-orientation and alignment tests. | 400% crops of small text on folded faces vs the flat render (ΔE / SSIM) |
| M5 | Reference reading → camera, ground and light with confidences. User controls (position, scale, rotation, pose, fold, camera, ground, light, shadow). Contact shadow and occlusion. Object mask + removal. Deterministic pre-composition saved. | Environment-only and with-package references |
| M6 | Optional harmonization (Gemini). The package region is protected: print × light map only, as in steps 2 and 3. Rejects drift, ghosting, duplicates and silhouette changes, with a fallback. | Fake-provider tests: timeout, invalid output, drift |
| M7 | ③ Mode A/B switch and Mode B panel, compare and export, versions, performance, QA report | Full suite, build, browser QA |

## Supported packaging types
See the PRD table.
- **M3 folds:** the tube (with or without a glue flap) and tuck ends (STE, RTE).
- **Everything else** is recognised as unsupported, with reasons, or fails validation.

## Risks
- **Line semantics in real files.** Zentra has stepped hinges and slits classified as creases.
  - Mitigation: only creases that separate two panels hinge, and every anomaly is an issue.
  - Still to decide: whether to block on warnings in M3.
- **Panel polygons are traced** (±0.1 mm at 8 px/mm). M3 should snap polygon edges to the
  crease axes and cut segments, so edges meet exactly when folded.
- **Board thickness:** without offsets, closed boxes z-fight at overlaps (lid over dust flaps).
  M3 offsets each folded layer by the caliper.
- **Camera from one photo** is an estimate. Exposing confidences and manual controls is required,
  not optional.
- **Object removal** needs inpainting. That is a model call (Gemini) or a manual mask, so it
  cannot be fully deterministic. Removal output is limited to outside the package and verified.
- **Performance:** the numpy z-buffer at 2048 px with polygonal panels is fine. 4K exports with
  supersampling need measuring in M5.

## Blockers / decisions needed from the user
- **B1: Zentra's bottom is a crash-lock (auto) bottom.** It has diagonal glued triangles. The
  command forbids claiming crash-lock folding before rules are implemented and validated.
  Options:
  - (a) Implement the crash-lock **closed** state in M3: the four bottom flaps folded in, with the
    glued triangles flat against them. This is visible only in poses that show the bottom; the
    open state stays unsupported.
  - (b) Support Zentra only in poses where the bottom is hidden, rendering the bottom as "not
    shown" (it is never invented).
  - (c) Leave Zentra unsupported until a full crash-lock solver exists.
  - *Recommendation:* (a), with (b) as the interim if M3 validation of (a) fails.
- **B2: Product rule.** `CLAUDE.md` says "Keep it 3 steps … no scene builder". Mode B adds
  placement and environment controls inside ③. Please confirm amending the rule: Mode B is
  part of ③, and step 3 keeps one primary action.
- **B3: Interactive 3D viewer.**
  - *Recommended:* server-rendered previews only for M3–M5 (no new dependency, identical to the
    export).
  - *Alternative:* a three.js viewer for orbiting (a new frontend dependency, viewer only).
- **B4: Zentra lines `p49.71` / `p49.77`.** These are 3.7 mm vertical "creases" inside the lid at
  the tuck corners; they are probably slits. They do not affect folding, because they hinge
  nothing. Correct them in the structural review if they are cuts.
