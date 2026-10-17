# Material behaviour matrix

The matrix compares the finishes by how they look and behave. Sources are in `finishing-research.md`, using the same source names. Cells marked † are optical inference rather than measured data.

**Target render setup:** top-down camera; flat carton; large soft overhead key light, roughly co-axial with the camera; soft fill; neutral studio environment.

**Key geometric fact for this setup.** With the camera and key both overhead, a perfectly flat mirror surface reflects *the camera's own surroundings* back to the camera, not the light. The key light only appears in a flat mirror if it surrounds the lens (ring or large softbox around the camera). Real overhead shoots show flat foil going dark unless a reflector or white card sits near the camera (tog.ink). The renderer therefore needs an explicit **environment / reflector model**, not just a key light.

## A. Optical properties

| Finish | Reflectivity | Roughness | Transparency | Height / displacement | Edge profile |
|---|---|---|---|---|---|
| **Gold foil (metallic)** | Very high specular, tinted yellow (lacquer over Al). Little diffuse light † | Gloss: very low; matt: moderate (Iggesund, 4OVER4) | Opaque | Flat stamp: ≈ a few µm (patents). Adds board deboss from the die †; foil-emboss 0.25–0.60 mm (Iggesund) | Sharp die-cut edge; slight impression (hot) or flat (cold) |
| **Silver foil** | Very high specular, neutral | Same as gold; chrome = lowest | Opaque | Same as gold | Same as gold |
| **Black foil 먹박** | Pigment: low, near-diffuse ("doesn't shine", tog.ink). Gloss metallic black: specular with dark base | Pigment matte: high | Opaque | ≈ flat | Crisp |
| **White foil 백박 (pigment)** | Diffuse, high albedo | High / medium | Opaque, but opacity varies (Briar Press) | ≈ flat | Crisp; may need multiple hits |
| **Red / green / blue — metallic** | Specular tinted by the coloured lacquer | Low | Opaque | ≈ flat | Crisp |
| **Red / green / blue — pigment** | Diffuse colour; gloss pigment versions have a mild sheen | Medium–high | Mostly opaque; tints and pastels are translucent (Kluge) | ≈ flat | Crisp |
| **Holographic** | Specular plus diffraction: colour depends on angle | Micro-grating (anisotropic) | Opaque (HRI version is transparent, Optaglio) | ≈ flat | Crisp |
| **Blind emboss** | Same as the substrate | Same as substrate; may whiten or crack on coated stock at the shoulder (4OVER4) | n/a | +0.15–2.5 mm (Iggesund) | Single-level = steep wall + flat plateau; bevel = angled wall; sculpted = continuous (4OVER4, Iggesund) |
| **Deboss** | Same as the substrate | Same | n/a | −0.15–2.5 mm | Same profiles, inverted |
| **Gloss lamination** | Strong specular (smooth PP) | Very low | Clear: transparent over print | ≈ 18–27 µm film (Cosmo / Arrsys); no visible relief | Covers the full panel; no visible edge on the panel face |
| **Matte lamination** | Broad, weak specular sheen | Medium micro-roughness (45° gloss <10 for one film) | Clear but slightly hazy † | ≈ 18–27 µm | Full panel |
| **Soft-touch** | Lowest sheen (≤20 GU at 60°, some 4–12 GU, patents) | High micro-roughness | Clear, hazier † | ≈ 30 µm incl. adhesive | Full panel |
| **Uncoated paper** | Diffuse; very weak sheen; fibre texture | High, macro fibre | Paper itself (ink absorbed) | n/a | n/a |
| **Spot UV (gloss)** | Strong specular (UV = highest gloss of varnishes, Iggesund) | Very low | Clear: transparent over print | 2–20 µm standard (Flexpress, QinPrinting, Friesens 10 µm) | Edge of a thin film; invisible as relief at standard thickness † |
| **Flood UV gloss** | Strong specular over the whole panel | Very low | Clear | ≈ 5–25 µm † (roller coater range, search) | Full panel |
| **Varnish: gloss / satin / matt (oil or aqueous)** | Gloss < UV; satin between; matt diffuse | Low → high | Clear | 1–few µm † | Full panel or spot |
| **Raised / 3D UV (future)** | Strong specular | Very low | Clear | 20–100 µm (up to 200 µm) | Rounded shoulder from flow; sharp outline |
| **Epoxy / PU dome** | Strong specular, clear lens | Very low | Clear: magnifies and distorts print † | ≈ 1.5–2 mm (±0.5) | Meniscus pinned at the cut edge; edge rounds sharp corners (Publog, Stickers Int.) |

## B. Light response and relationship to print

| Finish | Shadow response | Highlight response | Angle-dependent appearance | Relation to underlying print | Substrates | Common limitations |
|---|---|---|---|---|---|---|
| **Gold foil** | No self-shadow at stamp height; die impression gives a hairline dark rim † | Bright streak or flash only where the mirror angle sees a bright source | Extreme: dark ↔ bright (4OVER4) | **Covers** the print; foil replaces ink (Photomon) | Smooth coated board is best; textured stock gives patchy coverage | Fine lines plug; large solids pinhole; ±1–2 mm registration |
| **Silver foil** | Same as gold | Same, neutral colour | Extreme | Covers | Same | Same; shows scratches |
| **Black foil** | Pigment: none | Pigment: almost none; gloss black: sharp white streaks on a black field † | Pigment: low; gloss: high | Covers | Works on dark stock (tone-on-tone) | Low contrast by design |
| **White foil** | None | Little | Low | Covers (opaque on dark stock) | Dark board, museum board | Opacity varies; may need double hit |
| **Metallic colour foil** | Same as gold | Tinted flash | High | Covers | Like gold | Swatch ≠ screen |
| **Pigment colour foil** | None | Mild (gloss pigment) | Low | Covers, but tints let the stock show through (Kluge) | White stock best (Print Peppermint) | Less opaque than metallic (Friesens) |
| **Holographic** | None | Rainbow flashes **only under directional light**; grey-silver in diffuse light (4OVER4) | Very high, colour shift | Covers (HRI: transparent) | Smooth coated, laminate, black soft-touch | Scratch-prone on large areas (Redprinting); fine type unreadable |
| **Blind emboss** | Shading on the wall facing away from the key; tiny cast shadow † | Wall facing the key brightens; on gloss stocks the walls catch the highlight † | Moderate: grows with raking light, weak under overhead light † | Not a layer: deforms print and coating with it | Thick, elastic, long-fibre board (SBB) | Cracking on coated or laminated board; no emboss across folds |
| **Deboss** | Inner wall nearest the key is shadowed (inverted vs emboss) † | Opposite inner wall lit | Same as emboss | Same | Same | Same |
| **Gloss lamination** | None | Large, sharp reflection of the key or environment over the whole panel | High | Transparent over; deepens and saturates colour | Smooth board (defects show) | Shows board irregularities; foil adhesion issues |
| **Matte lamination** | None | Broad, soft sheen; can lift dark colours slightly † | Low–moderate | Transparent over, slightly flattened contrast † | Most boards | Scuffing on dark solids |
| **Soft-touch** | None | Very weak | Low | Transparent over; darks look rich, neons muted (4OVER4) | Most boards | Fingerprints; foil and spot UV need compatible grades |
| **Uncoated** | None | Almost none | Very low | Ink absorbed: lower density, more dot gain (PIWorld, SPIE) | n/a | No spot UV (bleeds, Flexpress) |
| **Spot UV** | None at standard build | Sharp highlight only where the mirror angle hits a bright source; elsewhere reads slightly darker or richer than matte † | High: flips visible ↔ invisible on dark matte (QinPrinting) | Transparent over; saturates colour (Iggesund) | Over matte or soft-touch laminate; not on gloss lam or uncoated (Flexpress) | ±0.5–2 mm registration; fill-in of small counters; cracks on folds |
| **Flood UV** | None | Panel-wide specular | High | Transparent; saturates | Coated board | Crack on creases (Iggesund folds note) |
| **Varnish matt / satin / gloss** | None | Scaled sheen | Low → high | Transparent; matt slightly lowers contrast † | Coated board | Oil varnish yellowing |
| **Raised UV (future)** | Slight cast shadow at 50–100 µm † | Highlight that follows the rounded shoulder | High | Transparent | Laminated stock (Friesens velvet) | Fill-in; max coverage ~25–30 % |
| **Dome** | Small soft shadow at the edge; dark line at the meniscus † | Compact highlight near the centre; bright rim ring † | High | Transparent lens: enlarges and distorts near the edge † | Pre-cut labels (vinyl, PET, synthetic paper) | Sharp corners round off; inner cuts limited; minimum size 5–12 mm |

## C. Implications for a top-down renderer (soft overhead key + soft fill)

| Finish | What the renderer must show |
|---|---|
| **Gold / silver / metallic colour foil** | Model as a **metal BRDF (F0 = foil tint)** with no diffuse term, reflecting an *environment* (studio surround plus key softbox). Top-down, most of a flat foil area reflects the darker environment around the camera, so it reads **dark, neutral or tinted**. Bright streaks appear where (a) the softbox edge is mirrored, (b) slight board waviness or die impression tilts the normal, and (c) substrate texture breaks the mirror into sparkle. Provide a "reflector card" control, because photographers add one (tog.ink). Matt foil = higher roughness: broader, dimmer, more uniform. Never render foil as a flat yellow fill. |
| **Black pigment foil** | Near-diffuse, very low albedo, with a faint matte sheen. Visible against print mainly through its edge and a slight sheen difference. Gloss black foil: dark base with sharp white environment streaks. |
| **White pigment foil** | Diffuse, high albedo, fully opaque over dark print. No metallic response. Allow a slight under-opacity option (opacity < 1 on very dark stock). |
| **Pigment colour foils** | Diffuse coloured layer that **replaces** the print beneath. Optional low gloss sheen. Allow translucency for tints. |
| **Metallic vs pigment choice** | Expose it explicitly for red, green and blue. They differ completely under overhead light: metallic = dark plus streaks; pigment = flat colour. |
| **Holographic** | Under a *soft* key it should look **mostly grey-silver**, with only modest rainbow banding where the softbox edge is mirrored (4OVER4). Rainbow strength scales with light directionality. Driving the rainbow by a fake angle gradient overstates it. |
| **Emboss / deboss** | Displacement or normal map from the mask, with a profile per die type (flat plateau + wall; bevel; rounded; sculpted). Under overhead light the visible cue is **subtle wall shading plus a very small cast shadow toward the side away from the key offset**. On a gloss coating, add the moving specular rim on the walls. Show embossed plateaus as the same tone as the surrounding board. Optional micro-whitening at the shoulder on laminated board. |
| **Gloss lamination** | Global clearcoat layer: low roughness, Fresnel at n ≈ 1.5, slight colour saturation boost. Top-down it gives a large soft reflection of the key across the panel. Shows board waviness. |
| **Matte / soft-touch** | Clearcoat with high roughness (soft-touch higher still). Small veiling lift on dark colours. No sparkle. |
| **Uncoated** | No clearcoat. Diffuse paper with a fibre-noise normal or albedo. Apply a print transfer that lowers solid density and adds dot gain (softer, lighter darks). This is the clearest visual difference from matte film. |
| **Spot UV** | Per-mask change of clearcoat roughness (very low) over the base finish. **Visible mainly as a gloss contrast: bright where it catches the key's mirror reflection, slightly deeper colour elsewhere.** No relief at 10 µm. Sharp mask edge; optional ±0.5–1 mm misregistration jitter vs print. |
| **Flood UV / varnish** | Global clearcoat roughness preset: gloss UV < gloss aqueous < satin < matt. |
| **Raised UV (future)** | Spot UV plus a 20–100 µm displacement with a rounded shoulder. |
| **Dome** | Height field from a capillary-meniscus profile: flat-ish top, steep pinned edge, rounded corners. Clear dielectric with refraction (n ≈ 1.5) distorting the print near the edge. Compact specular of the key near the centre plus an edge ring highlight. Small contact shadow. |


## D. Revisions after visual inspection (2026-10-17)

See `visual-reference-library.md` → "Visually inspected references".

| Finish | Revision |
|---|---|
| Metallic foils | Add a substrate-following micro-normal ("glint") term: real foil drapes over paper fibres and sparkles; large solids show a bright→dark gradient, never a flat fill. |
| 먹박 (black foil) | Default is **gloss black** (metal model, dark tint): visible as sheen contrast on matte stock. Matte pigment black kept as `foil.black_matte`. |
| Holographic | Under soft light: pale cyan/violet/pink iridescence; saturated rainbow only with a directional (raking) light. |
| Spot UV vs raised UV | Confirmed distinct: spot UV = gloss contrast only; raised UV shows thickness/bubbles (reserved). |
| Dome | Bright rim, dark edge outline, one dominant highlight band, magnified print near the edge. |
