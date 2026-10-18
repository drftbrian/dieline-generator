# M2 report: structural topology

## What was built
- **`app/structure/topology.py`: `analyze(spec) -> Topology`.**
  - **Panels:** id, name, provenance, box, a traced polygon (page units) and size in mm.
  - **Fold edges:** panels a/b, an axis on the crease line, length in mm, orientation, the side
    of panel a, and the source crease ids.
  - **Cut contacts** between panels, which are never hinges.
  - **Connected components through folds**, and **issues** with level, code, Korean message, and
    the paths and panels involved.
- **`app/structure/carton.py`: `classify(topology, box)`.**
  - The family (rectangular folding carton), the body (order, roles W/D/glue, W·D·H in mm), each
    end (tuck end / crash lock / unknown / none: lid, lid_on, tuck flap, dust flaps), the style
    (STE / RTE / tuck top + crash-lock bottom / unrecognised) and whether it is supported, with
    reasons.
  - Checks: lid depth vs D, and measured vs stated box size.
- **`GET /api/projects/{pid}/structure`:** read-only, cached per spec version.
- **`scripts/topology_diagram.py`:** a review image.
- **Refactor:** `pdf.geometry.trace_loops` / `simplify_loop`, moved from `finishing.plates`
  without changing behaviour; the plate tests still pass.

## Rules enforced
- Only `cls` from the confirmed review is used; colour is never read.
- A fold exists only where a crease separates **two different panels**. A cut between two panels
  is a contact and is never a hinge (tested).
- A crease on the outline, a crease ending inside a panel, a stepped or curved hinge, unresolved
  lines, an unconfirmed structure, a disconnected net and an unmatched panel all become issues.
  The errors stop classification.
- Diagonal folds in an end mean crash lock: recognised, and not supported.

## Results

### Zentra (`prj_b8fca58bfcd4`, read from a copy; 1.9 s)
- **15 panels, 14 folds, one component, `ok`.**
- **Body:** glue (panel5) | back W (panel6) | left D (panel7) | front W (panel8) | right D
  (panel9).
- **W×D×H:** 99.8 × 51.2 × 141.4 mm. The stated size is 100 × 52 × 141: within 2 mm ✅.
- **Top:** a tuck end. The lid (panel2, 51.2 mm deep, which equals D ✅) is hinged on the front
  (panel8), with tuck flap panel1 and dust flaps panel3/panel4.
- **Bottom:** crash lock. Diagonal folds `p49.88` / `p49.89` split the glued triangles panel14 /
  panel15 off the W-side bottom flaps. **Not supported** (blocker B1).
- **Style:** `tuck_top_crash_lock_bottom`, `supported: false`.
- **Warnings:**
  - `FOLD_NOT_COLLINEAR`: the tuck hinge is stepped by 1.2 mm; the long crease is the axis.
  - `CREASE_INSIDE_PANEL`: `p49.71` / `p49.77` (blocker B4).
- **Review image:** generated locally with `scripts/topology_diagram.py`. It is not committed,
  because it is the user's design.

### Synthetic PDF fixtures (through the real upload and analysis)

| Fixture | Confirmed | Panels / folds | Result |
|---|---|---|---|
| named_spot | yes | 13 / 12 | reverse tuck end, supported |
| ocg_layers | yes | 13 / 12 | reverse tuck end, supported |
| named_single_sep | yes | 13 / 12 | reverse tuck end, supported |
| figma_outlined | yes | 13 / 12 | reverse tuck end, supported |
| unnamed_mixed | no | 13 / 12 | refused: `STRUCTURE_UNCONFIRMED` |
| unnamed_solid | no | 13 / 12 | refused: `STRUCTURE_UNCONFIRMED` |

### Tests (`tests/test_structure_topology.py`, 13 tests, all pass; full suite 258 passed)
Nets are generated from rectangles and creases:
- STE recognised with W/D/H within 1–2 mm.
- RTE (lids on opposite W panels).
- Fold axes lie on crease lines; 4 body folds.
- A cut between lid and dust flap is not a hinge.
- A body fold drawn as a cut disconnects the net.
- A crash-lock bottom is recognised and unsupported.
- An unresolved line stops the analysis.
- An unconfirmed structure is refused.
- A crease on the outline is reported.
- An irregular (L-shaped) net is unsupported with reasons.
- With and without a glue flap.
- The API endpoint.

## Not done in M2 (by design)
- **No folding, poses or rendering.** That is M3, after review.
- **Polygons are traced, not snapped to the vector segments.** Snapping is planned for M3.
- **Fold sense (mountain/valley)** is derived for M3 from `side_a` and the print side; it is not
  yet validated.
