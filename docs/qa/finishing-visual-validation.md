# Finishing render fidelity: visual validation

**What this compares.** Our deterministic renderers (`render/finishing/material.py`) against
photographs of real manufactured samples.

**Method:**
- `scripts/finish_gallery.py` renders every catalogue finish on one test card, under top and
  raking light, next to the matching local study photos (`backend/image learning/`, 40 photos,
  never committed).
- Zentra crops come from `scripts/finishing_e2e.py`.
- Numbers come from `scripts/finish_calibrate.py`'s pixel selectors, extended per tone band
  where noted.
- Gallery and crops were written to the session scratchpad and are not committed (they
  contain the photos).

**What counts as evidence:**
- **Photo-compared:** our render was set beside a local photo of that finish and inspected,
  with numbers where they could be measured.
- **Text only:** no photo was available. Web research found manufacturer and vendor text
  (thickness, behaviour) but no usable sample photographs, so these are not photo-validated.

| Finish | Evidence | Confidence |
|---|---|---|
| Gold foil | 4 local photos + tone-band measurement | Medium-high |
| Silver foil | 2 local photos + calibration | Medium |
| Coloured metallic foils (적·녹·청박) | 2–3 local photos each, visual only | Medium |
| Pigment foils, black (먹박), white (백박) | 3 local photos each, visual only | Medium |
| Holographic foil | 2 local photos, visual only | Low-medium |
| Emboss / deboss | 5 / 3 local photos + calibration | Medium |
| Spot UV | 4 local photos + calibration | Medium |
| Gloss / matte lamination | 1 local photo each, visual only | Low-medium |
| Flood UV | 2 local photos, visual only | Low |
| Soft-touch, satin/matte varnish, uncoated | text only | Low |
| Raised UV | text only | Low |
| Epoxy / PU dome | text only | Low |

## Per finish

### Gold foil (`foil.gold`): corrected in this phase
- **Source:** `후가공_금박.png`, `후가공_금박2.jpeg`, `후가공_금박.jpg` (calibration crops), and
  `후가공_금박.jpeg`.
- **Observed in the photos:** a pale, warm gold. The body is RGB (0.83, 0.78, 0.59) with chroma
  about 0.24. The mean colour per luminance fifth runs from (0.55–0.59, 0.49–0.53, 0.25–0.30) in
  the darkest fifth to (0.90–0.99, 0.88–0.99, 0.78–0.83) in the brightest. Chroma per fifth is
  0.10–0.33, highest in the dark tones, about 0.15 in the bright ones.
- **Render before (`d119806`):**
  - Tint came from the catalogue swatch `#D4AF37` (chroma 0.62), boosted up to 2× in dark tones.
  - On Zentra the logo's chroma per fifth was **0.60, 0.60, 0.62, 0.41, 0.12**: the lower
    letters looked mustard and painted.
  - 27% of pixels were above L 0.9, with the highlight band going almost white.
- **Render after:**
  - The tint is the measured body colour.
  - Dark tones are 1.0–2.2× richer, highlights whiten at 0.45 instead of 0.7, and the reflector
    lift is halved.
  - Chroma per fifth is now **0.25, 0.26, 0.28, 0.24, 0.13**, inside the photos' range. The mean
    colour per fifth matches the photo bands within about 0.05 per channel, except the darkest
    blue, which is 0.34 against 0.25–0.30.
- **Remaining mismatch:**
  - Shadows are a little light: the 5th luminance percentile is 0.52 against the photos' 0.43.
  - The swatch card photo shows several golds, some more yellow. One "gold" cannot match all of
    them.
  - A designer used to the old look will find the new gold paler (champagne).
- **Recommendation:** offer gold variants (pale, yellow, rose) as catalogue parameters measured
  from swatch photos, rather than retuning one gold.
- **Confidence:** medium-high (3 measured photos).

### Silver foil (`foil.silver`)
- **Source:** `후가공_은박.jpg`, `후가공_은박2.jpeg`.
- **Observed in the photos:** a mirror that is almost neutral (chroma 0.02). It goes from very
  bright where it reflects the light to mid-grey.
- **Render:** a neutral gradient from white to dark grey along the strip light, with fine grain.
- **Mismatch:** on the test card, the far bars are darker grey (L about 0.4) than either photo
  shows. The photos are shot towards the light.
- **Recommendation:** none until photos at more angles exist.
- **Confidence:** medium.

### Coloured metallic and pigment foils, 먹박, 백박
- **Source:** `후가공_적박*`, `후가공_녹박*`, `후가공_청박*`, `후가공_먹박*`, `후가공_백박*`.
- **Observed in the photos:** metallic films keep their colour, with white specular streaks.
  Pigment foils are flat and opaque, with a soft sheen.
- **Render:** the same behaviour. Metallic films use their own colour and whiten only the
  highlights; pigments are flat.
- **Mismatch:** colour hue is the catalogue swatch, not measured.
- **Recommendation:** measure swatches the way gold was measured, when there are crops with
  enough foil pixels.
- **Confidence:** medium (visual only).

### Holographic foil (`foil.holographic`)
- **Source:** `후가공_홀로그램박.png`, `후가공_홀로그램박2.jpeg`.
- **Observed in the photos:** a bright silver base with pastel cyan, blue and pink diffraction,
  changing with the angle.
- **Render:** a pastel rainbow over silver in the bright band. The far bars go a dull grey-green
  or violet (L about 0.4).
- **Mismatch:** the dark end looks muddy. In both photos the foil stays bright silver where it
  is not iridescent.
- **Recommendation:** raise the holographic base's minimum tone, using the silver levels.
  Change it only with a measured crop.
- **Confidence:** low-medium.

### Emboss / deboss (`relief.*`)
- **Source:** `후가공_엠보싱*.jpg/jpeg`, `후가공_디보싱*.jpeg`, `후가공_엠보싱&디보싱.jpeg`.
- **Observed in the photos:** soft, shallow shading. One side of the shoulder is lighter by about
  +0.14 L and the other darker by about −0.23 L (calibrated). Edges are rounded; nothing is
  re-drawn.
- **Render:**
  - Top light: a subtle relief inside the calibrated limits.
  - Raking light: strong bevels.
  - Zentra Scenario B checks: the change stays on the shape and its shoulder, and there is a lit
    and a shaded side.
- **Mismatch:** at raking light the shoulders read as hard, straight bevels. The photos' shoulders
  are rounder and softer.
- **Recommendation:** a softer profile default for raking, or a rounder height profile. Test it
  against `후가공_엠보싱3.jpg` at a low light angle before changing.
- **Confidence:** medium.

### Spot UV (`coating.spot_uv`)
- **Source:** `후가공_부분(UV)코팅.webp`, `후가공_부분(Uv)코팅*.jpeg/jpg`.
- **Observed in the photos:** on dark matte stock, the gloss reads as a **deeper black with sharp
  specular streaks**. Calibration: matte base L 0.23, gloss peak 0.96.
- **Render:**
  - On light stock: a soft sheen with bright gradients.
  - On navy: a lighter sheen gradient on the shape.
- **Mismatch:** the photos show gloss mainly as *contrast*: darker darks, deeper colour, and a
  narrow highlight. Our render mainly *lightens*. Every photo is on dark stock; none show UV on
  light stock.
- **Recommendation:** add a small saturation and darkening of the ink under spot UV (the wet look)
  and keep the highlight narrow. Get a photo of UV on light stock first.
- **Confidence:** medium.

### Gloss / matte lamination (`surface.*_lamination`)
- **Source:** `후가공_유광코팅.jpeg` (red card, strong glare), `후가공_무광코팅.jpg` (blue card,
  soft broad sheen).
- **Observed in the photos:** gloss gives a mirror-like glare whose strength depends on the angle.
  Matte gives a broad, soft lift and slightly muted colour.
- **Render:**
  - Gloss: a faint broad sheen.
  - Matte: slightly lighter darks (the navy is a touch washed).
  - Both apply to the whole panel or sheet, which matches the process: lamination is a surface
    process.
- **Mismatch:** the gloss photo is taken at a glancing angle. Our flat, top-down studio view
  shows little glare, which is consistent with that view, but it under-sells gloss.
- **Recommendation:** none for the flat view. The light sweep shows the glare.
- **Confidence:** low-medium.

### Flood UV, varnishes, soft-touch, uncoated
- **Source:**
  - `후가공_UV코팅.jpeg`, `후가공 UV코팅 2.jpeg` (flood UV).
  - Text only: [jukeboxprint soft touch vs matte](https://www.jukeboxprint.com/business-cards/soft-touch-vs-matte),
    [4over4 soft touch vs matte](https://www.4over4.com/faqs/general/is-soft-touch-lamination-the-same-as-matte-lamination),
    [Printivity](https://insights.printivity.com/?p=1691),
    [newprint lamination vs AQ](https://www.newprint.ca/help/what-is-the-difference-between-lamination-and-aq-coating),
    [designyourway varnish vs lamination](https://www.designyourway.net/blog/varnish-vs-lamination-in-print/).
- **Observed in the sources:**
  - Soft-touch looks close to matte, slightly deeper, and dulls rich colours a little.
  - Aqueous varnish is a less hard, less glossy surface than UV.
- **Render:** consistent in direction: matte and soft-touch lower contrast slightly; satin sits
  between matte and gloss.
- **Mismatch:** unmeasured.
- **Recommendation:** photograph physical samples under the gallery's lighting before tuning.
- **Confidence:** low (text only, except flood UV, which is visual only).

### Raised UV (`coating.raised_uv`)
- **Source:** text only.
  [Duplo DDC-8000](https://www.duplousa.com/product/ddc-8000-b2-raised-spot-uv-coater/):
  10–80 µm.
  [Friesens](https://www.friesens.com/books/specialty-options/specialty-finishes/spotuv/):
  10 µm standard, 50 µm textured, 100 µm per pass.
  [4over4](https://www.4over4.com/help/finishes/whats-the-difference-between-spot-uv-and-raised-spot-uv):
  50 µm.
- **Observed in the sources:** a thicker clear layer you can feel, with rounded edges.
- **Render:** spot UV gloss plus a relief of `height_um` (20–100, default 50), which matches the
  sources' range.
- **Mismatch:** unknown; there is no photo.
- **Confidence:** low.

### Epoxy / PU dome (`dome.*`)
- **Source:** text only. Incure's doming guides
  ([1](https://incurelab.com/wp/resin-doming-the-ultimate-guide),
  [2](https://incurelab.com/wp/doming-resin)) are a vendor blog: a meniscus that stops at the
  edge ("cliff effect") and a lens effect.
- **Render:** a lens magnification and a rounded edge. A thin dark rim at the meniscus
  (refraction) and one soft highlight.
- **Mismatch:** unknown. The dark rim reads like a grey outline on light stock; that is plausible
  for refraction but unverified.
- **Recommendation:** take a macro photo of a domed sticker before any change.
- **Confidence:** low.

## Not claimed
None of the finishes is claimed to be photoreal. Gold, silver, the coloured foils and relief sit
in the same family as the photos. Every row marked "text only" is a modelled guess with
physically motivated parameters, not a validated appearance.
