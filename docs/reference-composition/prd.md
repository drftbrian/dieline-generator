# PRD: Structural Reference Composition (Mode B of ③ 레퍼런스 합성)

## Problem
The current ③ (Mode A) poses a guessed cuboid and asks the image model to paint the scene.
Even with the print composited back, it inherits several weaknesses:
- **Structure is guessed:** faces are found by panel names, and flaps are missing.
- **Proportions and style are steered by the model and the reference package.**
- **Finishing and inside/outside surfaces are not modelled.**

We already hold the authoritative facts:
- the confirmed cut and crease lines;
- the panels and their sizes;
- the exact print (the flat render);
- the finishing assignments.

## Hypothesis
A carton folded deterministically from its own dieline, textured with its own approved print and
placed in the reference's environment gives more faithful and more consistent concept images than
reconstructing the package with a model.

## Users and use
A package designer has an approved flat render (② or a finished version) and a reference
photograph (studio or lifestyle, with or without another package). They want a concept photo of
**their** package in that setting.

## Principles (non-negotiable)
1. **The source is authority:**
   - The confirmed dieline: cut/crease classes, panels, folds, sizes.
   - The flat render's print.
   - The finishing specification.
2. **The reference is an environment guide:** camera, light, surface, framing, placement cue.
   Never its package's design or proportions.
3. **AI may not decide geometry or print.** Scene analysis may be assisted, with confidences and
   user correction. Harmonization is optional, masked and verified, with a fallback to the
   deterministic composition.
4. **Unsupported structures fail safely**, with reasons. Nothing is invented.
5. **Non-destructive:** Mode A, the flat renderer and the finishing studio stay as they are.
   Outputs are new versions; intermediate artefacts are saved separately.

## Scope by milestone
See `plan.md`.
- **M1/M2 (this delivery):** audit, PRD, architecture, topology and validation.
- **M3:** deterministic folding and poses.
- **M4:** artwork and finishing mapping.
- **M5:** scene placement and deterministic composition.
- **M6:** AI harmonization.
- **M7:** UI, QA and performance.

## Supported structures (initial)

| Structure | Recognised (M2) | Folding (M3 target) |
|---|---|---|
| Rectangular tube (W·D·W·D, ± glue flap) | yes | yes |
| Tuck end (lid ≈ D + tuck flap, dust flaps) | yes | yes |
| Straight tuck end (STE) / reverse tuck end (RTE) | yes | yes |
| Crash-lock (auto) bottom | yes (diagonal folds) | **no**, pending decision B1 |
| 1-2-3 snap lock, four-flap, tray, sleeve-with-flaps, curved, unusual interlocks | reported as unrecognised / unsupported | no |

## Acceptance criteria
These are the 16 criteria of the master command. M1/M2 address:
- **1:** uses Figma-derived structure.
- **2:** distinguishes confirmed cuts from folds.
- **13 (structural part):** unsupported geometry fails safely.

## Non-goals (for now)
- Generic origami or arbitrary nets.
- Physics simulation of board stiffness.
- Automatic and always-reliable object removal.
- Exact camera calibration from a single photo (it is estimated and user-corrected).
