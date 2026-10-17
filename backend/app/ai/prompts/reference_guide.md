# 레퍼런스 이미지 해석 가이드 (3단계 · 합성)

디자이너가 올린 레퍼런스 사진을 읽는다. 이 사진 속 패키지는 나중에 **우리 패키지로 교체**된다.
그래서 레퍼런스에서는 **사진의 모습**(카메라, 빛, 그림자, 재질감, 배경, 구도, 분위기)과
**레퍼런스 속 패키지가 놓인 자리와 형태**만 읽는다. 레퍼런스의 브랜드·글자·로고·그래픽은 기록만 하고 옮기지 않는다.

먼저 카테고리를 하나 고르고, 그 카테고리의 7개 항목을 모두 채운다.

## 출력 규칙
- `category`: `person` / `beverage` / `product_packaging` 중 하나.
- `summary`: 한국어 한 문장. 이 레퍼런스가 어떤 사진이고, 패키지가 어디에 어떻게 놓였는지.
- `sections[]`: 카테고리의 7개 key를 아래 순서 그대로, 빠짐없이. `title_ko`는 아래 제목, `text_en`은 영어 2–5문장.
  일반론이 아니라 **이미지에서 실제로 보이는 것**을 구체적으로 쓴다. 보이지 않으면 "Not visible in the reference."
- `packaging_form`: 레퍼런스 속 패키지가
  - `flat` — 펼쳐진 평면 상태(전개도·시트)로 놓여 있음
  - `folded` — 접혀서 세워지거나 조립된 박스로 보임
  - `none` — 패키지가 보이지 않음 (사람·음료 사진 등에서 패키지를 놓을 자리를 `camera.placement`로 고른다)
- `camera`: 레퍼런스에서 읽는다.
  - `azimuth`: 정면 기준 회전(도, −60…60). 음수면 패키지 왼쪽 옆면, 양수면 오른쪽 옆면이 보인다.
  - `elevation`: 패키지 중심보다 위에서 내려다보는 각도(도, 0…90). 완전한 탑뷰는 90.
  - `lens_mm`: 35mm 환산 초점거리 느낌(35/50/90).
  - `placement`: 프레임 안에서 패키지가 차지하는(또는 차지할) 영역 [x0, y0, x1, y1] (0–1 비율).
  - `aspect_ratio`: 1:1 / 4:5 / 3:2 / 16:9 중 레퍼런스에 가장 가까운 것.
- `light`: `key_azimuth`(빛이 오는 방향, 위=0 시계방향 도), `key_elevation`, `quality`(soft/hard),
  `shadow`(방향·길이·선명도 영어 한 문장), `temperature`(warm/neutral/cool).
- `prompt_en`: 7개 항목과 카메라·빛을 하나의 영어 사진 프롬프트로. 레퍼런스 패키지의 글자·로고는 쓰지 않는다.

---

## 👤 인물 (category: person)

1. `pose` — **인물의 주요 포즈 및 행동**: 구체적인 자세, 포즈, 손 동작.
   예: "A confident young woman posing stylishly against a clean, white studio backdrop."
   예: "She strikes a playful and dynamic pose, with one arm extended gracefully to the side and the other bent, her hand resting near her hip."
2. `face` — **얼굴 및 표정**: 얼굴 특징, 인종, 헤어스타일, 헤어 색깔, 표정, 시선 방향.
   예: "She has a warm and radiant complexion typical of East Asian descent, with sleek, straight black hair styled into a shoulder-length bob."
   예: "Her facial expression is charming and slightly mischievous, with a soft smile and her head tilted to the side, her almond-shaped eyes looking directly at the camera."
   예: "He is of African descent, with short curly hair dyed a striking platinum blonde. His expression is serious yet thoughtful, with a sharp jawline and piercing gaze directed slightly to the left."
3. `outfit` — **의상**: 상의, 하의, 신발. 색상, 재질, 디테일, 스타일.
   예: "She is wearing a bold and edgy outfit that features a black asymmetrical crop top with one-shoulder strap detailing, revealing a pink layer underneath for a vibrant contrast."
   예: "Her lower half is dressed in loose-fitting pink cargo pants with black printed patterns that add a grungy, artistic vibe."
4. `accessories` — **액세서리**: 헤어스타일, 장신구, 의상에 부착된 소품.
   예: "The pants are secured with a studded black belt that enhances the punk-inspired aesthetic."
   예: "Her sleek black hair is styled with two playful pink ribbons tied on each side, and she wears hoop earrings with a minimalist design."
5. `background` — **배경**: 공간의 특징과 분위기(실내/실외, 색상, 조명).
   예: "The background is minimalistic and bright, emphasizing her striking pose and vibrant outfit, which exudes confidence and individuality."
   예: "He stands on a bustling urban street, with graffiti-covered walls and warm, natural sunlight casting dramatic shadows."
6. `mood` — **전체적인 분위기와 주제**: 톤, 주제, 스타일.
   예: "Her outfit and posture exude confidence and individuality, perfectly blending youthful charm with punk-inspired aesthetics."
   예: "The atmosphere conveys a sense of dynamic energy, with an emphasis on urban culture and individuality."
7. `extras` — **추가 요소**: 색상 강조(배경 및 의상의 색조 조합), 소재 디테일(옷감의 텍스처, 질감), 조명(따뜻한, 차가운, 강렬한 등).

## 🥤 음료 제품 (category: beverage)

1. `container` — **제품 형태 및 용기 구조**: 병, 캔, 파우치 등 용기의 형태, 크기감, 실루엣, 뚜껑 및 마개 디테일.
   예: "A sleek, slim glass bottle with a rounded shoulder and a matte black twist-off cap, featuring a refined and minimalist silhouette that suggests premium quality."
   예: "The can features a slightly tapered cylindrical form with a standard pull-tab top, giving it a classic yet contemporary energy drink profile."
2. `label_typography` — **라벨 및 타이포그래피**: 브랜드명, 제품명, 주요 카피, 폰트 스타일, 텍스트 레이아웃, 언어.
   예: "The brand name is set in bold, uppercase sans-serif lettering centered on the label, with a secondary tagline printed in a lighter weight typeface directly below."
   예: "The label features a clear three-tier hierarchy: the product name dominates the upper third, a short functional descriptor sits in the middle, and a minimal ingredient callout appears at the base in the smallest weight."
3. `color` — **색상 및 그래픽 디자인**: 라벨과 용기의 주요 색상, 패턴, 일러스트, 그래픽 요소.
   예: "The label employs a deep forest green base with gold foil accents, evoking a premium, nature-forward brand identity with a sense of quiet sophistication."
   예: "A gradient wash of soft coral fading into warm amber flows across the label, complemented by a delicate botanical illustration rendered in fine white linework."
4. `material` — **소재 및 마감 질감**: 유리/플라스틱/알루미늄 등 소재 특성, 무광·유광·투명도, 엠보싱 등 마감 처리.
   예: "The glass bottle carries a frosted, semi-opaque finish that diffuses light softly across its surface, giving the product an understated luxury feel."
   예: "The label is printed on textured uncoated paper stock with a soft-touch matte lamination and subtle embossed lettering on the brand name for a tactile premium quality."
5. `background_styling` — **배경 및 스타일링**: 제품이 놓인 배경, 소품 구성, 조명, 스타일링 컨텍스트.
   예: "The bottle is placed on a smooth white marble surface against a soft cream background, accompanied by scattered dried botanicals and a shallow ceramic dish to the right."
   예: "The product is styled in an outdoor natural setting on a moss-covered stone surface, surrounded by muted green foliage with soft diffused daylight entering from the left."
6. `brand_mood` — **전체적인 브랜드 분위기와 포지셔닝**: 톤앤무드, 타깃 감성, 프리미엄/캐주얼 등 포지셔닝.
   예: "The overall image communicates a premium wellness positioning, appealing to health-conscious urban consumers who seek a sophisticated and functional beverage experience."
   예: "The visual tone is clean, calm, and restorative, suggesting a brand deeply rooted in natural ingredients and a mindful, intentional lifestyle."
7. `extras` — **추가 요소**: 투명도 연출(내용물 색상이나 병 소재의 투명도), 신선감 디테일(물방울, 결로, 얼음), 조명 반사(유리·금속에 반사된 하이라이트).

## 📦 일반 제품·패키지 디자인 (category: product_packaging)

1. `structure` — **제품 형태 및 구조**: 전체적인 형태, 비율, 박스·파우치·용기 등 패키지 구조.
   예: "A rigid, rectangular gift box with a lift-off lid, featuring sharply folded corners, a cloth ribbon pull tab at the center, and a consistent wall thickness that conveys solidity."
   예: "The outer pouch is a stand-up format with a matte surface, a tear notch at the top, and a resealable zipper closure that allows repeated opening without compromising structure."
2. `typography` — **타이포그래피 및 정보 구성**: 브랜드명, 제품명, 주요 카피, 성분/용량 표기, 텍스트 계층 구조.
   예: "The front panel leads with a large brand wordmark in a geometric sans-serif, followed by the product variant name in a contrasting script typeface for warmth and differentiation."
   예: "Text is organized in a clear three-tier hierarchy: the brand name anchors the top, the product descriptor sits in the middle zone, and a key ingredient callout appears at the base in the smallest weight."
3. `color` — **색상 및 그래픽 디자인**: 주요 색상 팔레트, 패턴, 일러스트, 아이콘, 그래픽 요소.
   예: "A bold cobalt blue dominates the package, contrasted with crisp white typography and a single warm orange accent stripe running diagonally across the lower panel for dynamic energy."
   예: "The packaging features an intricate hand-drawn botanical pattern in sage and cream tones covering the full surface, giving the product a rich, artisanal and handcrafted character."
4. `material` — **소재 및 마감**: 종이/플라스틱/패브릭 등 소재, 코팅·박·엠보싱 등 마감 디테일.
   예: "The box is constructed from uncoated natural kraft board with flexo-printed inks, giving it an honest, tactile texture that reinforces the brand's eco-forward positioning."
   예: "A high-gloss UV spot coating is applied selectively over the logo and key graphic elements, creating a striking contrast against the surrounding soft matte surface."
5. `background_styling` — **배경 및 스타일링**: 배치된 배경, 소품, 조명, 전체 비주얼 컨텍스트.
   예: "The package is laid flat on a raw concrete surface alongside a few loose product ingredients, with a single overhead soft-box light creating even, shadow-free illumination."
   예: "Multiple SKUs from the same range are arranged in a fanned layout on a warm oak surface, allowing the series' cohesive visual identity and color coding to read clearly."
6. `brand_mood` — **전체적인 브랜드 분위기와 포지셔닝**: 브랜드 세계관, 감성 방향, 타깃 소비자층.
   예: "The packaging communicates approachable sustainability — honest materials, warm tones, and friendly typography designed to resonate with eco-conscious millennial shoppers."
   예: "The bold graphic system projects confidence and modernity, positioning the product as a premium lifestyle brand aimed at design-savvy, urban consumers."
7. `extras` — **추가 요소**: 언박싱 디테일(내부 라이너, 티슈페이퍼, 인서트 카드), 친환경 요소(재활용 소재, 무잉크 각인), 시리즈 통일성(라인업 내 디자인 일관성, 컬러 변주).
