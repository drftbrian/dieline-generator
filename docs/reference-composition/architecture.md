# Architecture: Structural Reference Composition

```
spec.paths (confirmed cut/crease) ──► structure.topology  ──► structure.carton
spec.panels / scale / box               panels, polygons,       family, body W·D·H,
                                        folds, cuts, issues     ends, style, supported
                                                │
                                                ▼
                                        fold solver (M3) ──► panel transforms (mm, rigid)
                                                │
flat render + frame_json ──► textures (M4) ─────┤   finishing masks ──► panel material masks
                                                ▼
reference + reading (M5) ──► camera / ground / light (estimated + user-corrected)
                                                ▼
                       deterministic scene renderer (backend, numpy) ──► pre-composition (saved)
                                                ▼
                       optional AI harmonization (M6, masked, verified) ──► final (or fallback)
```

## Modules (backend)
- **`app/structure/topology.py` (M2):**
  - Labels the board between cut and crease lines; the board comes from `render.layers.board`,
    so openings are excluded.
  - Matches regions to the review's panels by box, then traces their polygons.
  - Builds **fold edges only from crease lines that separate two different panels**. A cut
    between panels is a *cut contact*, never a hinge.
  - Reports the fold axis (on the crease line itself), its length in mm and orientation, and the
    side each panel lies on.
  - Raises issues: unresolved lines, an unconfirmed structure, a disconnected net, creases on
    the outline or inside a panel, stepped or curved hinges, unmatched panels.
- **`app/structure/carton.py` (M2):**
  - Recognises the W·D·W·D tube from the fold graph alone, then each end (tuck end / crash lock /
    unknown) and the style (STE / RTE).
  - Cross-checks against the stated box size.
- **`GET /api/projects/{pid}/structure` (M2):** topology + carton, cached per spec version.
- **`scripts/topology_diagram.py` (M2):** a review image (roles, hinges, issues).
- **Next:**
  - `structure/fold.py` (M3): a tree of rigid transforms over the fold graph, rooted at a
    W panel, and closure checks.
  - `render/scene.py` (M5).

## 3D rendering choice
- **Authoritative renders on the backend** use numpy, extending the existing `carton3d`
  approach. Every panel is planar, so mapping the print onto a panel is an exact homography,
  with no GPU and no new dependencies. The output is deterministic (byte-reproducible), and
  `verify` can be run on it as in steps 2 and 3. Polygonal panels need a per-panel polygon
  mask plus a z-buffer in place of the painter's order. Cost is about 1–2 s at 2048 px for
  ~15 panels.
- **Frontend preview (decision B3):**
  - *Recommended for M3–M5:* server-rendered preview images. They need no new dependency,
    match the export pixel for pixel, and fit the "keep it simple" rule.
  - *Optional later:* a three.js viewer for interactive orbiting, used only as a viewer and fed
    the same transforms and textures. It is never the export path.

## Data and storage
- The topology is derived on demand (`GET /structure`), never stored as truth, so it always
  follows the confirmed spec.
- Mode B outputs are versions with `kind: "merge"` and `settings_json.mode: "structural"`, with
  separate files:
  - `<vid>_structure.png` (deterministic pre-composition)
  - `<vid>_raw.png` (model)
  - `<vid>.png` (delivered)
  - `<vid>_scene.json` (pose, fold state, camera, placement, light, confidences)
