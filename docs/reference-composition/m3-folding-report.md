# M3 report: deterministic 3D folding

**Status:** implemented. It needs the user's **visual validation** before M4.

## Decisions applied
- **B1 = (a): Zentra's crash-lock bottom is folded closed only, as an approximation.**
  - The four bottom flaps turn in, the two big flaps interlock (the root side stays outermost),
    and the glued triangles lie flat on their flaps.
  - The fold sequence and an open bottom are not supported; the fold result says so in `notes`.
- **B3 = server-rendered preview** (recommended default, no new dependency). The preview *is* the
  export renderer.
- **B2 (the 3-step rule)** is not needed until M5/M7; I will ask before adding UI controls.

## What was built
- **`app/structure/fold.py`: `fold(topology, carton, state) -> Folded`.**
  - **Flat frame:** mm, X right, Y up, the print toward +Z.
  - **Folding:** a breadth-first tree from the root W panel (the one carrying the top lid). Each
    child turns rigidly about its crease axis, the fold axis from the M2 topology, in the
    direction away from the print side. The transform composes parent × hinge, so panels never
    stretch (tested).
  - **Angles:** body 90°, closure flaps 90°, crash-lock triangles 180° (glued flat).
  - **Fold states:** `closed`, `open_top` (lid −25°, tuck 0°, dust flaps −10°) and
    `partially_open` (lid 50°, tuck 20°, dust flaps −10°). Only the top end moves.
  - **Board thickness:** under-layers move inward by the caliper (0.46 mm) × their layer. These
    are the dust flaps, tuck flap, glue flap and crash-lock flaps.
  - **Checks:**
    - **Tube closure:** the free edge of the last body panel against the glue hinge.
    - **Lid closure:** the lid's far edge against the opposite W panel's edge.
    - **Containment:** the closed parts stay inside the body box (2 mm tolerance).
    - **No intersections:** an edge passing more than 1.5 mm through another panel's outline.
  - **Errors:** `STRUCTURE_UNSUPPORTED` (with the classifier's reasons), `FOLD_STATE_UNKNOWN`,
    `FOLD_STATE_UNSUPPORTED`, `NET_DISCONNECTED`.
- **`app/render/structure3d.py`: deterministic pinhole renderer.**
  - Planar panels, exact ray-plane depth (a z-buffer), and inside versus outside faces.
  - Per pixel: the panel, whether the print side is visible, and the **hit point in the panel's
    flat-net mm**. M4 samples the approved print through that point, so the mapping is exact by
    construction.
  - **Pose presets** (camera and placement, separate from the fold state): `standing_front`,
    `standing_three_quarter`, `standing_side`, `lying_down` (on its back, seen from the lid
    end), `open_top`.
  - Azimuth and elevation can be overridden.
- **API:**
  - `GET /api/projects/{pid}/structure/fold?state=` returns transforms, outlines and checks
    (409 when unsupported).
  - `GET .../structure/preview?pose&state&azimuth&elevation&width&height` returns a PNG.
- **Tests:** `tests/test_structure_fold.py` (15).
  - The closed STE box has the net's dimensions and closes.
  - Panels stay rigid.
  - Print faces end up outside.
  - RTE folds; a crash-lock bottom folds closed, with its note.
  - Open and partial states move only the top end.
  - The intersection detector fires on lid and dust flaps both at 45°.
  - Unsupported nets and unknown states fail safely.
  - The renderer is deterministic, and its hit points map back onto the net.
  - Every pose renders, and both endpoints work.

## Results

### Zentra (read from a data copy)
- **Closed:** 100.1 × 141.5 × 52.1 mm (stated 100 × 52 × 141).
  - **Tube closure:** 0.95 mm.
  - **Top lid closure:** 1.01 mm.
  - No panel outside the box, no intersections.
- **Open top / partially open:** OK (the tube closes, nothing intersects).
- **Timing:** folding takes about 3 ms per state; a 600 × 600 render takes 0.16–0.27 s.
- **Small visible gaps that come from the dieline itself, not from the solver:**
  - **Lid:** the lid is 51.2 mm deep against a 52.05 mm box, so a hairline behind its far edge
    can show the dust or tuck flaps (about 280 px of 140k at 600 px, 3/4 view).
  - **Seam:** the right side panel is 0.8 mm narrower, so the glue flap shows in the seam (side
    view). That is physically right.
- **Contact sheet (local, not committed: the user's design):** closed front, 3/4, side, lying
  down, open top, partially open, and the closed crash-lock bottom seen from below.

### Synthetic fixtures (reverse tuck end)

| Fixture | Closed size (mm) | Tube / top / bottom closure (mm) | States |
|---|---|---|---|
| named_spot | 60.0 × 99.9 × 30.0 | 0.17 / 0.29 / 0.23 | all OK |
| figma_outlined | 61.1 × 101.7 × 30.5 | 0.24 / 0.19 / 0.23 | all OK |

## Limitations (known)
- **Panel outlines are traced** (±0.1 mm at 8 px/mm). They are not yet snapped to the vector
  cut segments. This only shows at panel edges (hairline gaps or overlaps of about 0.1 mm).
- **Mountain/valley** is inferred as "away from the print" for every fold, which is right for
  printed-outside cartons. Reverse folds (print inside, e.g. a display insert) are not modelled.
- **Partial-fold intermediate states are fixed presets,** not a continuous slider. A slider
  would need the intersection check run live, which is cheap (a few ms).
- **Crash-lock bottoms are a closed-state approximation** only.
- **The preview is structural** (role colours). The approved print arrives in M4.
