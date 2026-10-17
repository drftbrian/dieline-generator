# Manufacturing constraints for post-press finishes

Gathered 2026-10-17. Vendors often disagree. Each row keeps the source's own value so the app can choose a default (usually the **conservative** one) and show it as a *warning*, not a hard error. The "Auto?" column says whether the app can check the rule from the vector finish mask plus the dieline (cut, crease and glue layers):

- **Y**: checkable geometrically.
- **P**: partly checkable (needs text metadata or a user choice).
- **N**: needs human or material judgement.

Pages marked "(search-summary)" could not be fetched directly; their values come from a search engine's summary of the page.

## 1. Foil stamping (박)

| Rule | Value(s) and source | Suggested default | Auto? |
|---|---|---|---|
| Minimum positive line width | 0.3 mm ([TOPAC foil-embossing PDF, search-summary](https://www.topac.de/fileadmin/content/c_Leistungen/Foil_embossing.pdf)); 1 pt ≈ 0.35 mm ([WowPress 박](https://wowpress.co.kr/wow2.0/w_guide/doc/g4_1.html)); "hairlines below roughly half a point tend to break up" ([4OVER4 gold/silver](https://www.4over4.com/.well-known/okf/guide/gold-and-silver-foil-printing-explained.md)); 0.3 pt ([icomics, search-summary](https://www.icomics.co.kr/bbs/board.php?bo_table=su106&wr_id=16&list_style=list)) | **0.3 mm** warn, 0.2 mm error | **Y** (min stroke via medial axis or erosion) |
| Minimum gap between foil elements | ≥0.25 mm or "plugging" ([PrintNinja](https://printninja.com/foil-stamping-setup-guide/)); "no less than half the thickness of the stock" ([Kluge](https://www.kluge.biz/tips/press-tip-primary-design-considerations/)); narrow gaps cause 뭉침 (clumping) ([Redprinting](https://www.redprinting.co.kr/ko/product/item/BC/BCFOXXX)) | **max(0.3 mm, 0.5 × board caliper)** | **Y** (min gap via dilation) |
| Minimum text size | 8 pt ([WowPress](https://wowpress.co.kr/wow2.0/w_guide/doc/g4_1.html)); 10 pt ([Photomon](https://biz.photomon.com/products/106)); 7.5 pt coated / 8.5 pt cloth ([After Hours, search-summary](https://www.afterhourscreativestudio.com/faqs/artwork/what-size-text-is-needed-for-foil-blocking)); 12 pt (disc stamping, [Discmania, search-summary](https://www.discmania.net/pages/hotstamp-art-guide)) | **8 pt** (serif 10 pt) | **P** (needs text objects, or estimate from stroke width) |
| Holographic foil lines / type | ≥0.5 pt strokes; ~6 pt type, but small holo type is hard to read ([4OVER4 holo](https://v2.4over4.com/guide/holographic-foil-stamping-explained-effects-costs-and-artwork-setup)) | 0.3 mm / 8 pt | P |
| Foil + deboss line width and spacing | ≥1 mm ([PrintNinja](https://printninja.com/foil-stamping-setup-guide/)) | 1 mm | **Y** |
| Distance from trim / cut line | 5 mm ([WowPress](https://wowpress.co.kr/wow2.0/w_guide/doc/g4_1.html)); 3 mm ([Photomon](https://biz.photomon.com/products/106)); 0.125 in = 3.2 mm ([PrintNinja](https://printninja.com/foil-stamping-setup-guide/); [4OVER4 holo](https://v2.4over4.com/guide/holographic-foil-stamping-explained-effects-costs-and-artwork-setup)) | **3 mm** warn (5 mm conservative) | **Y** (distance field from cut lines) |
| Over folds / creases | Do not cross the spine or score areas, because of a "high potential for cracking" ([PrintNinja](https://printninja.com/foil-stamping-setup-guide/)); keep 3–5 mm from cuts and creases ([Digital Polo](https://www.digitalpolo.com/packaging-dieline-design/)) | 3 mm from crease | **Y** |
| Registration to print | 1–2 mm variance ([PrintNinja](https://printninja.com/foil-stamping-setup-guide/); [WowPress](https://wowpress.co.kr/wow2.0/w_guide/doc/g4_1.html)); ±1 mm ([Photomon](https://biz.photomon.com/products/106)) | Assume ±1 mm | **Y** (flag foil edges that butt fine print within 1 mm; suggest a ≥2 mm gap per Photomon) |
| Foil vs print | Kiss-fit, no trapping ([Kluge](https://www.kluge.biz/tips/press-tip-primary-design-considerations/)); foil covers any print under it ([Photomon](https://biz.photomon.com/products/106)); remove CMYK elements under foil so misregistration is tolerated ([PrintNinja](https://printninja.com/foil-stamping-setup-guide/)) | Info | **Y** (detect overlap of foil and important print) |
| Large solid areas | >30 mm per side may show grain ([Photomon](https://biz.photomon.com/products/106)); large solids trap air and pinholes ([4OVER4](https://www.4over4.com/.well-known/okf/guide/gold-and-silver-foil-printing-explained.md)); large solids plus fine detail need 2 passes ([Kluge](https://www.kluge.biz/tips/press-tip-primary-design-considerations/)) | Warn when the inscribed circle is >30 mm | **Y** (max inscribed circle) |
| No gradients or soft edges | ([PrintNinja](https://printninja.com/foil-stamping-setup-guide/)) | Mask must be binary vector | **Y** |
| Coverage | Surcharge when >25 % of the face (pricing; [Redprinting](https://www.redprinting.co.kr/ko/product/item/BC/BCFOXXX)) | Info | Y |
| Foil over lamination | Needs a lamination-compatible foil (API, KURZ grades); matte-laminated card showed poor transfer in a KMUTT study; thermal laminates are problematic ([Iggesund](https://www.iggesund.com/globalassets/iggesund/services/knowledge/iam/graphics-handbook/gh---full-copy---en/0_graphics_handbook_en.pdf)) | Warn "confirm foil grade" | N |
| Cold foil | Smooth substrate only; **no embossing** ([Resource Label, search-summary](https://www.resourcelabel.com/blog/2022/05/21/cold-foil-vs-hot-foil-for-labels/)) | Block cold foil + emboss | **Y** (finish combination rule) |
| Data format | Separate vector layer, K100 or named spot, outlined fonts ([Redprinting](https://www.redprinting.co.kr/ko/product/item/BC/BCFOXXX); [Photomon](https://biz.photomon.com/products/106)) | Export rule | Y |

## 2. Embossing / debossing (형압)

| Rule | Value(s) and source | Default | Auto? |
|---|---|---|---|
| Relief depth range | 0.15–2.5 mm; foil-emboss 0.25–0.60 mm ([Iggesund](https://www.iggesund.com/globalassets/iggesund/services/knowledge/iam/graphics-handbook/gh-pdf----en/embossing_and_debossing_in_practice.pdf)) | 0.3 mm blind default; clamp 0.15–1.0 mm for folding-carton board † | Y (parameter limit) |
| Minimum text | ~8 pt ([4OVER4](https://v2.4over4.com/guide/embossed-printing-explained)); 10 pt ([Print Peppermint](https://printpeppermint.com/blogs/graphic-design/embossing-vs-debossing-an-in-depth-guide)) | 10 pt | P |
| Minimum stroke / gap | Stroke 0.5 mm, gap 1 mm ([Print Peppermint](https://printpeppermint.com/blogs/graphic-design/embossing-vs-debossing-an-in-depth-guide)); remove hairline serifs ([4OVER4](https://v2.4over4.com/guide/embossed-printing-explained)) | 0.5 mm / 1 mm | **Y** |
| Distance from trim | ~1/8 in ≈ 3.2 mm ([4OVER4](https://v2.4over4.com/guide/embossed-printing-explained)); 5 mm ([WowPress 형압](https://wowpress.co.kr/wow2.0/w_guide/doc/g4_2.html)) | 3–5 mm | **Y** |
| Across folds | "Do not run an emboss across a fold" ([4OVER4](https://v2.4over4.com/guide/embossed-printing-explained)) | Error if the mask intersects a crease; warn within 3 mm | **Y** |
| Registration to print | 1–2 mm ([WowPress](https://wowpress.co.kr/wow2.0/w_guide/doc/g4_2.html)); make the print slightly wider than the emboss ([4OVER4](https://v2.4over4.com/guide/embossed-printing-explained)) | ±1 mm | Y (registered emboss: check print overlap margin) |
| Board | 24 pt min (light), 32 pt+ (deep) ([Print Peppermint](https://printpeppermint.com/blogs/graphic-design/embossing-vs-debossing-an-in-depth-guide)); ≥250 g/m² (Korean vendor, search-summary); SBB / long-fibre board best, FBB compresses ([Iggesund](https://www.iggesund.com/globalassets/iggesund/services/knowledge/iam/graphics-handbook/gh-pdf----en/embossing_and_debossing_in_practice.pdf)) | Warn on thin board | P (needs board caliper input) |
| Coated / laminated board | Coating or laminate can whiten or crack at the shoulder; coated stock only "workable at a shallow depth" ([4OVER4](https://v2.4over4.com/guide/embossed-printing-explained)) | Warn when depth >0.4 mm with lamination † | P |
| Emboss over print | Pressure can crack or strip ink, so avoid it or use coated stock ([WowPress](https://wowpress.co.kr/wow2.0/w_guide/doc/g4_2.html)) | Info | Y (overlap) |
| Reverse side | The back shows the inverse impression ([Morningprint](https://www.morningprint.co.kr/finishing/open_finishing3.php)) | Info: check the inside panel | Y (mirror the mask onto the inner face) |
| Order | Emboss last; foil-emboss simultaneous ([Iggesund](https://www.iggesund.com/globalassets/iggesund/services/knowledge/iam/graphics-handbook/gh-pdf----en/embossing_and_debossing_in_practice.pdf)) | Info | — |
| Size caps (commercial) | e.g. 40 × 20 mm base size ([Morningprint](https://www.morningprint.co.kr/finishing/open_finishing3.php)) | Vendor-specific | Y |

## 3. Spot UV / coatings

| Rule | Value(s) and source | Default | Auto? |
|---|---|---|---|
| Minimum positive line | Avoid <1 mm, 0.25 mm achievable ([PrintPlanet](https://printplanet.com/threads/the-limits-of-spot-uv.284838/)); 0.3 mm ([QinPrinting](https://www.qinprinting.com/spot-uv/)); 0.5 pt ([Worldwide, search-summary](https://www.worldwide.com.au/wp-content/uploads/2023/07/Setup-Clear-Gloss-Spot-UV-Artwork.pdf)); 1 pt ([4OVER4 line art, search-summary](https://www.4over4.com/help/artwork-and-design/line-art-and-text-recommendations-for-spot-uv-and-foil); [PrintSimple, search-summary](https://www.printsimple.eu/en/help/how-do-i-indicate-where-the-spot-uv-should-be-placed)) | **0.3 mm** warn | **Y** |
| Minimum reverse (knock-out) line | Avoid <2 mm, 1 mm achievable ([PrintPlanet](https://printplanet.com/threads/the-limits-of-spot-uv.284838/)); enclosed counters fill in ([Flexpress](https://www.flexpress.co.uk/spot-uv-guide/)) | **1 mm** | **Y** (min gap / hole size) |
| Minimum text | 8 pt ([QinPrinting](https://www.qinprinting.com/spot-uv/)) | 8 pt | P |
| Raised UV fine text | ≤20 µm build ([Flexpress](https://www.flexpress.co.uk/spot-uv-guide/)) | Info | P |
| Registration | ±0.5 mm (UK vendors, [Tradeprint, search-summary](https://blog.tradeprint.co.uk/why-choose-spot-uv-business-cards)); 0.5–2 mm, design for 1 mm ([PrintPlanet](https://printplanet.com/threads/the-limits-of-spot-uv.284838/)) | ±1 mm | Y |
| Distance from trim / folds | ≥5 mm from trim, never over a score or fold ([PrintPlanet](https://printplanet.com/threads/the-limits-of-spot-uv.284838/)); 1.5–3 mm from edge or fold ([Flexpress](https://www.flexpress.co.uk/spot-uv-guide/)); minimise near folded edges ([Friesens](https://www.friesens.com/books/specialty-options/specialty-finishes/spotuv/)) | 3 mm, error when crossing a crease | **Y** |
| Coverage | ≤25 % ([Flexpress](https://www.flexpress.co.uk/spot-uv-guide/)); ≤30 % ([PrintSimple, search-summary](https://www.printsimple.eu/en/help/how-do-i-indicate-where-the-spot-uv-should-be-placed)) | Warn >30 % | **Y** |
| Base finish | Not on uncoated stock (bleeds); not on gloss laminate (no contrast); best on matte or soft-touch ([Flexpress](https://www.flexpress.co.uk/spot-uv-guide/); [QinPrinting](https://www.qinprinting.com/spot-uv/)); KR: cover must be 무광 ([icomics, search-summary](https://www.icomics.co.kr/bbs/board.php?bo_table=su106&wr_id=16&list_style=list)) | Block spot UV + uncoated; warn spot UV + gloss | **Y** (combination rule) |
| Substrate weight | Avoid <175 gsm; ≥200 gsm compatible ([Flexpress](https://www.flexpress.co.uk/spot-uv-guide/)) | Info (cartons are heavier) | P |
| Spot UV + foil | Foil shine can confuse registration cameras, so consult ([Friesens](https://www.friesens.com/books/specialty-options/specialty-finishes/spotuv/)) | Warn when they overlap | Y |
| Spot UV + emboss | Registration concerns ([Friesens](https://www.friesens.com/books/specialty-options/specialty-finishes/spotuv/)) | Info | Y |
| No ink over cured UV | ([Flexpress](https://www.flexpress.co.uk/spot-uv-guide/)) | Info | — |

## 4. Lamination and glue areas (folding-carton specific)

| Rule | Value(s) and source | Default | Auto? |
|---|---|---|---|
| Glue tab free of coatings | "a glue tab must be kept free of ink, varnish, and especially any coating" ([Digital Polo](https://www.digitalpolo.com/packaging-dieline-design/)); keep knockout areas free of inks and varnishes ([DCG die template notes, search-summary](https://resources.dcgone.com/dies/4.125x9.5_SS_Num10_6up_23x35_out_15.pdf)) | **Error:** UV, varnish or foil inside the glue zone; warn for lamination (special adhesives exist for UV, BOPP and aqueous board: [Senda glue, search-summary](https://sendaglue.com/consumer-packaging/folding-carton-adhesives/)) | **Y** (mask ∩ glue polygon) |
| Glue area print | Not printed, but overfill 3 mm; keep important elements 2 mm from the glue line ([Labelprint24](https://www.labelprint24.com/en/data-check/artwork-requirements-for-folding-boxes-71)) | 2 mm | **Y** |
| Bleed | 3 mm folding carton ([Digital Polo](https://www.digitalpolo.com/packaging-dieline-design/)); 2 mm ([Labelprint24](https://www.labelprint24.com/en/data-check/artwork-requirements-for-folding-boxes-71)) | 3 mm | Y |
| Safe zone | 3–5 mm from cuts and creases ([Digital Polo](https://www.digitalpolo.com/packaging-dieline-design/)); 1.5 mm from die ([Labelprint24](https://www.labelprint24.com/en/data-check/artwork-requirements-for-folding-boxes-71)) | 3 mm | Y |
| Folds and cracking | Folds should show no cracks on "printed, varnished or laminated" surfaces; good creasing is needed ([Iggesund](https://www.iggesund.com/globalassets/iggesund/services/knowledge/iam/graphics-handbook/gh---full-copy---en/0_graphics_handbook_en.pdf), creasing chapter); ≥150 g stock needs 오시 (creasing) before folding ([WowPress 오시](https://wowpress.co.kr/wow2.0/w_guide/doc/g4_4.html)) | Info | N |
| Gloss / metallic film | Highlights every board irregularity; needs a smooth, dust-free surface ([Iggesund](https://www.iggesund.com/globalassets/iggesund/services/knowledge/iam/graphics-handbook/gh---full-copy---en/0_graphics_handbook_en.pdf)) | Info | N |
| General carton text minimum | 5 pt positive, 6 pt negative; lines 0.5 pt / 1 pt negative ([Labelprint24](https://www.labelprint24.com/en/data-check/artwork-requirements-for-folding-boxes-71)) | Info | P |

## 5. Doming (에폭시 / 도밍)

| Rule | Value(s) and source | Default | Auto? |
|---|---|---|---|
| Minimum part size | 5 × 5 mm ([Stickers International](https://www.stickersinternational.co.uk/products/domed-stickers/)); 8 × 8 mm (James Labels), 0.3 in ≈ 7.6 mm (Dometag), 0.5 in (Maverick) ([search-summary](https://dometag.com/help/dome)); 10 × 10 mm ([Redprinting EPX](https://www.redprinting.co.kr/ko/landing/EPX)); 12 × 12 mm ([Publog](https://www.publog.co.kr/blog/epoxy-sticker-guide)) | **10 mm** | **Y** (bounding box / inscribed circle) |
| Corner radius | ≥1 mm ([Stickers International](https://www.stickersinternational.co.uk/products/domed-stickers/)); ≥2.5 mm (Dometag); ≥3 mm (Sticky Things, Domestar) ([search-summary](https://www.stickythings.co.uk/product/resin-domed-labels/)) | **≥2.5 mm**; render sharper corners as rounded | **Y** (curvature) |
| Sharp peaks, valleys, inner cuts | No sharp peaks or valleys ([Redprinting EPX](https://www.redprinting.co.kr/ko/landing/EPX)); inner cut-outs only for smooth round shapes; sharp points round off ([Publog](https://www.publog.co.kr/blog/epoxy-sticker-guide)) | Warn on concave corners and holes | **Y** |
| Minimum stroke (domed letters) | ~5 mm (0.2 in) ([Dometag, search-summary](https://dometag.com/help/dome)) | 5 mm | **Y** |
| Separation between domes | 10 mm ([Domestar, search-summary](https://www.domestar.com/en/doming-service-for-professionals.html)); 0.25 in between labels ([Rippedsheets, search-summary](https://rippedsheets.com/technical-support/guidelines-trouble-free-dome-label-printing.html)) | 6–10 mm | **Y** |
| Dome height | ~1.5 mm ±0.5 ([Stickers International](https://www.stickersinternational.co.uk/products/domed-stickers/)); 1.5–2.0 mm ([Incure](https://incurelab.com/wp/resin-doming-the-ultimate-guide)) | 1.5 mm, not user-settable (flow-determined) | — |
| Substrate | Domes go on pre-cut labels with enough surface energy; plotter cuts are more consistent ([Screen Printing mag](https://screenprintingmag.com/?p=128)); avoid over-laminates or varnish (Rippedsheets, search-summary) | On a carton, model the dome as an *applied label* | N |
| Digital "에폭시" (Scodix-type raised UV, KR) | Text ≥7.5 pt; 2 mm from print; 3 mm safe zone; counters (ㅇ, ㅁ, 0, 8) fill; wide areas pool ([Photomon 109](https://biz.photomon.com/products/109?op1=3&op2=115&op3=10&op4=131&op5=15&op6=146)) | Separate finish type | **Y** |

## 6. Cross-finish combination rules the app can enforce

| Combination | Rule | Source |
|---|---|---|
| Cold foil + emboss | Not possible | Resource Label (search-summary) |
| Spot UV + uncoated base | Not recommended (bleeds) | Flexpress |
| Spot UV + gloss lamination or flood gloss | No visual effect; warn | Flexpress; QinPrinting; icomics (search-summary) |
| Any coating or foil + glue zone | Error | Digital Polo |
| Emboss / spot UV / foil crossing a crease | Error or warn | 4OVER4; PrintPlanet; PrintNinja |
| Foil over thermal laminate | Warn | Iggesund |
| Foil + spot UV overlap | Warn (registration cameras) | Friesens |
| Pigment / tint foil on coloured stock | Warn about colour shift | Kluge; Print Peppermint (search-summary) |
| Holographic + diffuse-light product shots | Info: effect will look grey | 4OVER4 |

### Geometry checks to implement (from §1–6)
1. **Minimum feature width** (medial-axis / erosion test) for each finish mask.
2. **Minimum gap / counter size** (dilation / closing test).
3. **Distance field** from cut lines, crease lines and the glue polygon; also detect where the mask crosses a crease.
4. **Coverage ratio** per panel or face.
5. **Largest solid** (maximum inscribed circle) for foil.
6. **Curvature / corner radius and holes** for domes.
7. **Overlap of finish masks** with each other and with critical print (text, barcode).
8. **Minimum size and spacing** for dome parts.

† = engineering suggestion, not sourced.
