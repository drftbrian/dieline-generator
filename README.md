# Dieline Generator

패키지 전개도(칼선 도면)를 받아서, 인쇄된 글자와 그림은 **원본 그대로** 지키면서 사진처럼 보이는 이미지를 만들어 주는 앱입니다.

English summary: [아래 English 섹션](#english)을 보세요.

---

## 한눈에 보기: 3단계

이 앱은 딱 세 단계만 합니다. 요리로 치면 "재료 손질 → 기본 반죽 굽기 → 원하는 접시에 담기"입니다.

### ① 원본 (Figma 스캔)

- **기본 방법은 Figma 프레임 링크 붙여넣기**입니다. 대시보드에서 Figma 프레임 링크를 넣으면 앱이 그 프레임을 가져옵니다.
- Figma가 없을 때를 위한 **예비 수단으로 PDF 업로드**도 작게 남겨 두었습니다.
- 가져온 뒤 앱이 자동으로 **분석**합니다: 칼선/접는선/인쇄 요소 구분, 정확한 글자와 폰트, 로고, 치수.
- 그다음 **구조 확인** 화면에서 사람이 애매한 선을 확정합니다. 확정해야 다음 단계가 열립니다.

### ② 플랫 렌더

- 펼친 상태의 패키지를 **위에서 내려다본 사진처럼** 한 장 만듭니다.
- 고정된 룩 (`flat_look.png`를 기준으로 맞춤): 검은 배경, 정면 탑뷰, 무광 판지, 은은한 종이결, 접는선은 얇은 홈 + 빛 받는 쪽 밝은 선, 뚫린 구멍(창·슬롯)은 검게 보임.
- **기본은 AI 없이 코드가 그립니다** (`FLAT_RENDER_MODE=deterministic`).
  - Figma/PDF 벡터를 **최종 크기(기본 4096px)에서 한 번** 래스터화합니다. AI 이미지를 키운 게 아니라서 작은 한글도 선명합니다.
  - 종이결·접는 자국·빛은 **회색조 밝기(gain)만** 곱합니다. 글자·로고·그라데이션의 모양과 색은 그대로입니다.
  - 칼선 외곽·구멍·검은 배경은 Figma 구조에서 정확히 나옵니다.
  - 같은 입력이면 **매번 똑같은 이미지**가 나옵니다. Gemini 키가 없어도 됩니다.
  - 판지 룩은 세 가지입니다 (`FLAT_LOOK`, 또는 API에서 `{"look": "v2"}`):
    - **v4 (선택, 실물 접는선)**: v3에 접는선만 물리 모델로 바꾼 룩. Figma 접는선 위치로 높이 지도(가운데 눌린 홈 + 양옆 살짝 솟은 어깨, 약 2mm 안에서 평평해짐)를 만들고, 표면 방향(노멀)과 부드러운 키 라이트로 음영을 계산합니다. 빛을 향한 어깨는 은은하게 밝고 반대쪽은 살짝 어둡고, 홈은 약간 그늘집니다. 가로·세로·대각선 접는선이 각자 방향대로 빛을 받고, 교차점은 한 덩어리로 섞이고, 접는선 끝과 칼선 0.5mm 앞에서 자연스럽게 사라지며, 작은 날개 경첩은 조금 더 또렷합니다. 접는선 3mm 밖은 v3와 픽셀 단위로 같습니다. 세기는 `FLAT_FOLD_PRESET=low|medium|high` (기본 medium) 또는 API `{"look": "v4", "fold_preset": "high"}`.
    - **v3 (기본, 마감 패스)**: v2에 더해 아주 약한 톤 변화와 조금 더 고운 섬유결, 바깥 칼선의 가장자리 픽셀에만 어두운 웜그레이 판지 단면, 칼선에 딱 붙는 접지 그림자, 조금 더 깊은 접는선, 패널마다 ±0.5% 밝기 차이(판지 면이 살짝 다르게 놓인 느낌). 배경은 검정처럼 보이는 #040404이고, 그림자는 칼선 바로 옆에서 #000까지 내려갑니다.
    - **v2 (실물 판지)**: 가까이 확대해야 보이는 아주 고운 종이 섬유결(가로 방향), 칼선 바로 안쪽 0.3mm의 은은한 두께감, 부드럽게 눌린 접는선 홈, 위에서 고르게 비추는 소프트박스 조명. 배경 #000.
    - **v1 (첫 룩)**: 비교용으로 그대로 남겨 둔 첫 번째 결정적 룩.
- 선택: **AI 조명 모드** (`FLAT_RENDER_MODE=ai_appearance`, 또는 API에서 `{"mode": "ai_appearance"}`).
  - Gemini(Nano Banana Pro)에 `flat_render.md` 프롬프트 + Image 1(우리 렌더) + Image 2(`flat_look.png`)를 보냅니다.
  - 모델 결과에서는 **글자보다 훨씬 큰 크기의 부드러운 빛 얼룩만** 가져옵니다 (최대 −4%~+3%). 모델이 그린 글자·종이결·테두리·배경은 버립니다.
  - 모델이 판지 모양을 바꾸거나 엉뚱한 곳에 그렸으면 **빛도 쓰지 않고** 코드 렌더 그대로 냅니다.
### ②+ AI 재질 보정 (선택)

- ② 코드 렌더(AI 없음)가 **완성된 뒤에만**, 원할 때 누르는 별도 버튼입니다. **원본은 절대 바뀌지 않고 새 버전**이 생깁니다.
- AI(Gemini)에는 **글자·로고가 하나도 없는 빈 판지**(칼선·구멍·접는선만 그대로)와 레퍼런스 사진(재질·조명 참고용, 없으면 `flat_look.png`)만 보냅니다. 다시 그릴 인쇄가 없으니 글자를 망칠 수 없습니다.
- AI가 만든 판지 사진을 우리 좌표에 맞추고(어긋나거나 없는 선을 그렸으면 거부), 거기서 두 가지 지도만 뽑습니다:
  - **빛 지도**: 15mm 이상으로 부드러운 오버헤드 조명 (−4%~+3%)
  - **종이 질감 지도**: 0.4~3mm 크기의 은은한 종이 결 (최대 ±1.5%, 글자·로고 주변과 AI가 그린 자국에서는 0)
- 최종 이미지는 **원본 벡터 인쇄 × v3 밝기 × 빛 × 질감**으로 다시 만듭니다. 강도(0~100%)를 고를 수 있고, Figma 색이 흔들리거나 얼룩져 보이면 앱이 강도를 **전체적으로 고르게** 낮춥니다 (적용된 강도가 표시됨).
- 저장된 지도로 **다른 강도를 다시 적용**하면 AI를 다시 부르지 않습니다 (비용 없음).
- 검사(`verify_flat` + 원본 대비 검사: 크기·외곽/구멍 동일, 밝기 변화 ≤6%, 글자 선명도, 원본 파일 불변)에 떨어지면 `ENHANCE_REJECTED`로 실패하고 **원본 v3가 그대로 결과**입니다.
- 진단 파일: `<버전ID>_source.png`, `_blank.png`, `_raw.png`, `_registered.png`, `_light.png/.npy`, `_detail.png/.npy`, `_enhance.json` (모델·레퍼런스·강도·설정·검사).
- 비교 이미지: `cd backend && uv run python scripts/enhance_compare.py <프로젝트ID> <보정버전ID> --out enhance.png`
- v4 접는선 진단 (v3/v4 렌더, 접는선 마스크·높이·노멀·그림자·하이라이트 지도, 차이 히트맵, 400% 크롭): `cd backend && uv run python scripts/fold_diagnostics.py <프로젝트ID> --out-dir folds_qa`

### ②+ AI 보정 요청 (프롬프트)

- AI 보정 패널에 **보정 요청**을 한국어나 영어로 적을 수 있습니다 (최대 1000자, 예: "접는선 그림자를 더 사실적으로", "무광 종이 질감을 살짝"). 빠른 프리셋 3개(사실적인 접는선 / 무광 종이 질감 / 부드러운 스튜디오 조명)는 기존 글 뒤에 덧붙습니다.
- **원본 디자인은 항상 보호됩니다** (끌 수 없음): 글자·폰트·바코드, 로고, 인쇄 그래픽·색·그라데이션, 칼선·접는선·구멍·패널, 펼친 평면·탑뷰·검은 배경.
- 요청은 서버에서 먼저 읽습니다 (`backend/app/services/enhance_prompt.py`):
  1. 규칙 판독(한국어·영어): 문장마다 "동작 + 보호 대상"을 찾습니다. "로고는 그대로 두고"처럼 유지하라는 말은 문제 삼지 않습니다.
  2. Claude 판독(키가 있을 때, `prompts/enhance_interpret.md`, 스키마 검증): 보호 위반을 **더 찾을 수만** 있고 규칙의 판단을 풀 수는 없습니다.
  3. 보호 대상을 바꾸려는 문장이 하나라도 있으면 이미지 모델을 부르기 전에 `422 PROMPT_PROTECTED`로 거절합니다. 허용된 부분이 있으면 사용자가 **"허용된 부분만 적용"**을 눌러 확인해야만 실행되고, 빠진 문장은 기록됩니다.
- 요청은 **정해진 범위의 값(spec)**으로만 바뀝니다: 재질 디테일, 종이 질감, 조명 부드러움·방향, 접는선 깊이감·그림자·하이라이트, 모서리 음영, 접지 그림자(바닥은 고정이라 기록만), 전체 효과 세기. 사용자 원문은 이미지 모델에 가지 않고, 백엔드가 쓴 문장(`material_enhance.md`의 `$appearance`)만 갑니다.
- 값은 결정적 합성에서 적용됩니다: AI 빛·질감 지도 크기, 기존 접는선 위치에 더하는 접는선 음영(v4 접는선 모델), 칼선 안쪽 음영. 범위를 넘을 것 같으면 그 부분만 부드럽게 눌러 넣습니다(소프트 니). 강도 0%는 원본과 바이트 단위로 같습니다.
- API: `POST /api/projects/{pid}/versions/{vid}/enhance` 에 `user_prompt`, `confirm_allowed_only` 추가. `POST /api/projects/{pid}/enhance/interpret` 로 실행 없이 판독 결과(차단 여부, 문장별 분류, spec, 메모)를 미리 봅니다.

### ②+ 후가공 스튜디오 (박·형압·코팅·에폭시)

② 플랫 렌더 위에서 **Figma 원본 요소를 직접 골라** 후가공을 입혀 봅니다. 디자인 파일은 절대 바뀌지 않고, 후가공은 "어디에 무엇을" 적은 **별도 기록**(리비전)으로만 저장됩니다. 투명 필름을 여러 장 겹쳐 보는 것과 같아서, 필름을 빼면 원래 그림이 그대로 있습니다.

**쓰는 순서**
1. ② 화면 오른쪽 **요소 선택** → 캔버스에서 로고·글자를 클릭 (Shift: 여러 개, Alt 또는 `[` `]`: 겹친 요소 바꾸기).
2. 종류 고르기: 박(금·은·먹·컬러·홀로그램·안료) · 형압(엠보싱/디보싱) · 코팅(라미네이팅·무코팅) · 액상 코팅(부분 UV·바니시·입체 UV) · 에폭시.
3. 세부 값(거칠기, 깊이 mm 등)을 조절하고 **"선택한 요소 N개에 적용"**. 라미네이팅처럼 종이 전체에 하는 공정은 전체 시트나 패널을 직접 체크해야 적용됩니다(요소만 반짝이게 하려면 부분 UV).
4. 캔버스 위 **원본 / 후가공 / 비교**, 조명 **위 / 측면광**으로 확인. **빛 움직여 보기**는 빛을 좌우로 흔든 움직이는 그림을 만듭니다.
5. **제조 점검**: 선이 너무 가늘다, 칼선·접는 선에 가깝다, 접착 날개에 코팅, 유광 위 부분 UV처럼 만들기 어려운 경우를 알려 줍니다 (조사한 일반 기준값, 인쇄소마다 다를 수 있음).
6. **후가공 버전 저장**: 후가공을 입힌 새 플랫 버전(③ 합성에도 사용 가능). **AI 사실감으로 저장**은 Gemini가 실제 후가공 사진을 참고해 박·형압·부분 UV **영역 안의 빛과 질감만** 다듬습니다. 모양·글자·색과 영역 밖은 그대로이고, 어긋나거나 실제 사진에서 잰 값보다 나빠지면 쓰지 않습니다.
7. **판 파일 내려받기**: 후가공마다 K 100% 벡터 PDF + 칼선·접는선만 담은 `dieline.pdf` + 사양 JSON. 모두 실제 크기(mm)로 저장됩니다. 근사치·빠진 모양이 있거나 실제 크기 비율이 확인되지 않았으면 생산용 판은 막히고, 'DRAFT'가 붙은 검토용 초안만 받을 수 있어요. 판은 화면 미리보기와 같은 모양(종이 밖 1mm 여유 포함)이고, 칼선은 판에 넣지 않습니다(“출력 안 함” 레이어도 일부 장비에서는 찍히기 때문). 인쇄소 전달용 작업 판이지 인쇄소 검수를 대신하지는 않습니다.

**어떻게 사실적으로 그리나**
- 미리보기는 후가공이 들어간 픽셀만 원래 해상도로 그린 **투명 스티커**를 렌더 위에 붙입니다. 나머지 픽셀은 원본 그대로입니다.
- 재질은 `backend/image learning/`의 실제 후가공 사진(저장소에는 올리지 않음)에서 **잰 숫자**로 그립니다: `cd backend && uv run python scripts/finish_calibrate.py` → `app/render/finishing/calibration.json`.
- 재질별 비교 갤러리(우리 렌더 위/측면광 + 실제 사진): `cd backend && uv run python scripts/finish_gallery.py 갤러리폴더` (결과 이미지는 로컬에만).

**직접 확인해 보기 (로컬 테스트 가이드)**
1. `pnpm dev`로 앱을 켜고 Figma 프로젝트의 ②에서 플랫 렌더를 하나 만듭니다.
2. 로고에 금박, 제목에 엠보싱, 전체 시트에 무광 라미네이팅 → **후가공** 보기 → **측면광**으로 바꿔 형압이 더 또렷해지는지 확인.
3. 400% 확대해서 후가공 밖의 작은 글자가 원본과 똑같이 선명한지 확인.
4. 적용 목록에서 숨기기(눈)·삭제 후 원본으로 돌아오는지, Cmd+Z / Cmd+Shift+Z.
5. **후가공 버전 저장** → 히스토리에 "후가공" 배지 → 그 버전으로 ③ 합성.
6. 판 파일 ZIP을 열어 각 PDF를 `dieline.pdf`와 겹쳐 보고 위치가 맞는지 확인 (Illustrator 등). `finishing.json`의 `missing_targets`(빠진 요소)·`approximate_assets`(근사치)가 비어 있는지도 보세요.
7. 실제 프로젝트 복사본으로 자동 점검: `DATA_DIR=<복사본> uv run python scripts/finishing_e2e.py <프로젝트> <버전> <출력폴더> --logo <id> --emboss <id> --uv <id>` (원본 `backend/data`에서는 실행을 거부합니다).

### ③ 레퍼런스 합성

- 사용자가 **레퍼런스 사진 한 장**을 끌어다 놓습니다.
- **Claude가 사진을 읽습니다** (`reference_guide.md` 기준):
  - 카테고리: `person`(사람) / `beverage`(음료) / `product_packaging`(제품 패키지)
  - 카테고리마다 7개 항목 (예: 패키지라면 structure, typography, color, material, background_styling, brand_mood, extras)
  - 카메라(방위각·높이각·렌즈·화면 속 위치·비율), 조명
  - `packaging_form`: 사진 속 패키지가 `flat`(펼쳐짐) / `folded`(접힌 박스) / `none`(패키지 없음)
- 그다음 **이미지 모델(Gemini)** 이 우리가 승인한 ② 플랫 렌더 + 레퍼런스 사진을 받아서, **레퍼런스 속 패키지 자리에 우리 패키지를 넣습니다** (`merge.md`).
- **형태(평면/입체) 고르기**: 기본값 "자동"은 Claude가 읽은 `packaging_form`을 따릅니다 (`flat`이면 평면, `folded`와 `none`이면 입체). 화면에서 **자동 / 평면 / 입체**로 직접 바꿀 수도 있습니다.
  - **입체(folded)**: `backend/app/render/carton3d.py`가 플랫 렌더에서 각 면을 잘라 Claude가 읽은 카메라 각도로 **박스를 직접 접어 세웁니다.** 모델에는 Image A = 접힌 박스, Image B = 레퍼런스, Image C = 플랫 렌더(글자 디테일 참고용)를 보냅니다.
  - **평면(flat)**: Image A = 플랫 렌더, Image B = 레퍼런스.
- 입체 합성을 하려면 구조 확인에서 "앞면" 패널을 찾을 수 있어야 합니다. 못 찾으면 `409 FACES_UNKNOWN`이 나오니 패널 이름을 확인하거나 평면을 고르세요.

---

## 칼선(레드라인) 규칙

전개도의 선은 세 가지로 읽습니다.

| 선 | 의미 | 결과 |
|---|---|---|
| 가장 바깥 외곽선 | 칼선 (cut) | 판지의 모양 |
| 그 안쪽 선 | 접는선 (crease/fold) | 은은한 접힘 자국 |
| 안쪽에 있는 닫힌 고리 | 뚫린 구멍 (창·구멍·슬롯) | 검게 비어 보임 |

앱이 판단하는 순서 (`backend/app/pdf/dieline.py`, `backend/app/pdf/rules.py`):

1. **이름이 있으면 이름을 먼저 믿습니다.** 별색(스팟 컬러), PDF 레이어, Figma 레이어 이름을 봅니다. 대소문자, 띄어쓰기, `-` `_` `.` `/`는 무시하고 비교하고, 앞부분만 맞아도 됩니다 (예: `Die_Line_01`).
   - 칼선: `Die`, `Dieline`, `Redline`, `레드라인`, `다이라인`, `Cut`, `CutContour`, `칼선`, `재단`, `도무송` 등
   - 접는선: `Crease`, `Fold`, `Score`, `Perf`, `접는선`, `오시`, `접지` 등
   - 그 밖: 치수/가이드(`Dimension`, `Guide`, `치수`…), 블리드(`Bleed`, `도련`), 후가공(`SpotUV`, `Foil`, `박`…)
2. **칼선이라는 이름의 레이어 하나에 모든 선이 다 들어 있으면** (예: "redline" 레이어 하나), 모양으로 나눕니다: 바깥 테두리 = 칼선, 안쪽 = 접는선. 접는선 레이어가 따로 있으면 그 레이어를 그대로 씁니다.
3. **이름이 없으면 모양으로 판단합니다.** 가는 선들이 서로 연결되어 가장 넓은 면적을 감싸는 묶음을 전개도로 봅니다. 그 바깥 테두리 = 칼선, 안쪽 = 접는선, 전개도 밖의 선 = 치수 같은 기술 표시.
4. **확신이 없으면 지우지 않습니다.** 전개도와 연결되지 않은 안쪽 닫힌 고리는 "창·구멍일 수 있음"으로 표시하고, 사람이 구조 확인에서 정할 때까지 인쇄 요소로 남겨 둡니다. 칼선으로 확정하면 그 부분이 구멍(검정)이 됩니다.

> Figma 팁: 칼선 레이어 이름을 `Dieline`이나 `칼선`으로, 접는선을 `Fold`나 `접는선`으로 지어 두면 가장 정확합니다.

---

## 글자가 절대 바뀌지 않는 이유 (Exact-text 보장)

AI 이미지 모델은 글자를 잘 틀립니다. 그래서 이 앱은 **모델에게 인쇄를 맡기지 않습니다.**

비유하면, 모델은 "조명과 종이 질감만 칠하는 화가"이고, 글자와 그림은 우리가 마지막에 **원본 스티커를 그대로 다시 붙이는** 셈입니다.

1. ② 플랫 렌더는 **인쇄를 원본 벡터에서 직접** 그립니다. 그 위에는 회색조 밝기(종이결·접는선·빛)만 곱하고, 바깥은 Figma 칼선 그대로의 검은 배경입니다. AI 모드여도 모델에서는 **부드러운 빛**만 가져옵니다.
2. ③ 합성은 모델이 만든 장면(레퍼런스 세계) 위에, 우리 판지 자리에 **원본 인쇄 × 종이 밝기 × 장면의 부드러운 빛**을 다시 넣습니다 (`services/pipeline.py`의 `composite`, 입체는 `services/merge.py`의 `composite`).
3. **모든 결과를 검사합니다.** 통과해야만 저장되고 화면에 보입니다.
   - ② 플랫 렌더: `render/look.py`의 `verify_flat`
     - 인쇄 일치: 결과 = 원본 인쇄 × 회색조 밝기 (8비트 기준 1.5단계 이내), 디테일 상관도 0.98 이상
     - 밝기 범위 0.8~1.1
     - 번짐(halo) 없음: 밝기 지도에 글자 윤곽이 같은 자리든 밀린 자리든 섞여 있지 않음
     - 배경: 판지 밖은 정확히 검정, 두 번째 외곽선·회색 번짐 0픽셀
     - 종이결: 은은함 (구름 얼룩 없음), 무채색
     - 색: 전체 ΔE 중앙값 3 이하, Figma 지정 색 ΔE 6 이하
   - ③ 합성: `render/look.py`의 `verify` (같은 원리, 장면 배경 허용)
4. **검사에 떨어지면** 그 버전은 `ARTWORK_MISMATCH`(422)로 실패 처리되고, **아무것도 전달되지 않습니다.** "다시 생성해주세요"라고 안내합니다.

진단용 파일은 `backend/data/projects/<프로젝트ID>/versions/`에 저장됩니다.

| 파일 | 언제 | 내용 |
|---|---|---|
| `<버전ID>.png` | 통과 시 | 최종 결과 (다운로드되는 파일) |
| `<버전ID>_thumb.jpg` | 통과 시 | 썸네일 |
| `<버전ID>_deterministic.png` | ② | AI 없이 코드가 그린 기준 렌더 |
| `<버전ID>_raw.png` | ② AI 모드, ③ | 모델이 준 날것 그대로의 이미지 |
| `<버전ID>_structure.png` | ③ 합성만 | 모델에 Image A로 보낸 것 (접힌 박스 또는 플랫 렌더) |
| `<버전ID>_rejected.png` | 검사 실패 시 | 떨어진 합성 결과 (보여주지 않고 진단용으로만 보관) |

검사 수치는 버전 정보의 `verify` 항목에서 볼 수 있습니다.

**눈으로 확인하기 (QA 몽타주):** 원본·코드 렌더·모델 원본·밝기 지도·최종본과, 가장 작은 글자/가장 큰 글자/칼선+접는선의 400% 확대를 한 장으로 만듭니다.

```
cd backend && uv run python scripts/flat_qa.py <프로젝트ID> <버전ID> --compare <예전버전ID> --out qa.png
```

**판지 룩 전/후 비교 (기본 v2 ↔ v3):** 같은 레이어로 두 룩을 그려 작은 한글·워드마크·칼선 모서리·접는선·그라데이션 전환·빈 판지를 100%와 400%로 나란히 보여 주고, 인쇄가 밝기만 달라졌는지(색 비율 차이 0)와 종이결 세기를 숫자로 출력합니다.

```
cd backend && uv run python scripts/look_compare.py <프로젝트ID> --a v2 --b v3 --out looks.png
```

---

## 처음 설치하고 실행하기

### 준비물

- Node.js와 **pnpm**
- **uv** (파이썬 도구. 백엔드 실행에 필요합니다. 설치: `brew install uv`)

### API 키 넣기: `backend/.env`

`backend/.env` 파일에 아래처럼 적습니다. 이 파일은 git에 올라가지 않습니다. 키는 서버에만 있고 브라우저로 나가지 않습니다.

```
ANTHROPIC_API_KEY=...   # Claude: 구조 제안, 패널 이름, 레퍼런스 읽기
GEMINI_API_KEY=...      # Gemini: ③ 합성, ② AI 조명 모드 (기본 ②에는 필요 없음)
FIGMA_TOKEN=...         # Figma 개인 액세스 토큰 (권한: file_content:read)
FLAT_RENDER_MODE=deterministic   # 선택: ai_appearance 로 바꾸면 ②에 AI 조명을 더함
FLAT_LONG_EDGE=4096              # 선택: ② 결과의 긴 변 픽셀 (1024~8192)
FLAT_LOOK=v3                     # 선택: v4(실물 접는선), v2, v1
FLAT_FOLD_PRESET=medium          # 선택: v4 접는선 세기 low / medium / high
```

- 빈 줄(`KEY=`)은 "설정 안 됨"으로 취급합니다.
- **`OPENAI_API_KEY`는 더 이상 쓰지 않습니다.** 지워도 됩니다.
- 선택 설정 (안 적으면 기본값): `DATA_DIR`(기본 `backend/data`), `MAX_UPLOAD_MB`(25), `MAX_REFERENCE_MB`(10), `MAX_CONCURRENT_GENERATIONS`(2), `PREVIEW_LONG_EDGE`(1200). 정의는 `backend/app/config.py`.
- 키가 제대로 되는지 비용 없이 확인: `cd backend && uv run python scripts/check_providers.py`
- `.env`를 바꾼 뒤에는 서버를 다시 시작하세요.

### 실행

```
pnpm install
pnpm dev
```

`pnpm dev`는 두 개를 한 번에 켭니다.

- **web**: Vite 프론트엔드 (보통 http://localhost:5173)
- **api**: FastAPI 백엔드 (uvicorn, http://localhost:8000)

브라우저에서 **Vite 주소(터미널에 찍히는 http://localhost:5173)** 를 여세요. 프론트가 `/api` 요청을 자동으로 8000번 백엔드로 넘겨줍니다 (`vite.config.ts`의 proxy).

---

## 프롬프트 파일 고치기

AI에게 보내는 모든 글은 `backend/app/ai/prompts/`에만 있습니다. 코드를 몰라도 이 파일들의 **문장은 자유롭게** 고칠 수 있습니다.

| 파일 | 쓰임 | 자리표시자 (꼭 남겨 둘 것) |
|---|---|---|
| `flat_render.md` | ② 플랫 렌더 (Master Prompt A) | `$figma_url` `$dims` `$panels` `$fonts` `$logos` `$colours` `$texts_by_panel` |
| `merge.md` | ③ 레퍼런스 합성 | `$figma_url` `$form_rule` `$category` `$dims` `$colours` `$texts_by_face` `$reference_sections` `$camera` `$light` |
| `reference_guide.md` | ③ Claude가 레퍼런스를 읽는 기준 | 없음 (그대로 Claude에게 전달) |
| `flat_look.png` | ② Image 2, 룩 참고 사진 | (이미지) |

**자리표시자란?** `$dims` 같은 단어는 빈칸입니다. 앱이 실행될 때 `backend/app/ai/prompts.py`의 `render(name, **vars)`가 파이썬 `string.Template.substitute`로 이 빈칸에 실제 값(치수, 글자 목록 등)을 채웁니다. 편지 양식의 "OOO님께"에 이름을 넣는 것과 같습니다.

안전하게 고치는 규칙:

- 문장은 마음대로 바꿔도 됩니다. **`$`로 시작하는 자리표시자는 지우거나 이름을 바꾸지 마세요.** 하나라도 빠진 값이 있으면 오류가 나서 생성이 멈춥니다 (빈칸이 있는 프롬프트가 모델에 가는 일은 없습니다).
- `flat_render.md`, `merge.md`에서 **진짜 달러 기호**를 쓰려면 `$$`로 적으세요. 그냥 `$`를 쓰면 자리표시자로 오해해 오류가 납니다.
- 새 자리표시자를 추가하려면 코드도 같이 고쳐야 합니다 (`services/pipeline.py`의 `flat_prompt`, `services/merge.py`의 `merge_prompt`). 테스트 `backend/tests/test_prompts.py`가 이를 확인합니다.
- **고친 뒤 반영 시점:**
  - `flat_render.md`, `merge.md`: 처음 읽을 때 메모리에 저장(캐시)해 두므로 **백엔드를 다시 시작해야** 반영됩니다. `pnpm dev`를 Ctrl+C로 끄고 다시 켜세요. (자동 재시작은 `.py` 파일 변경만 감지합니다.)
  - `reference_guide.md`, `flat_look.png`: 쓸 때마다 새로 읽으므로 **재시작 없이** 다음 요청부터 반영됩니다. 단, 이미 읽은 레퍼런스는 다시 읽지 않습니다. 새 기준으로 읽히려면 레퍼런스를 다시 올리세요.

---

## 예전 데이터에 대해

앱이 3단계로 줄어들기 전에 만든 데이터는 이렇게 처리됩니다.

- **예전 버전(결과 이미지)**: 목록에 "legacy"로 표시됩니다. 볼 수는 있지만 ③ 합성의 플랫 원본으로는 쓸 수 없습니다. ②에서 새로 플랫 렌더를 만드세요.
- **예전 레퍼런스 분석**: "오래된 분석"으로 보고 백그라운드에서 **새 기준으로 다시 읽습니다** (레퍼런스 목록을 열 때, Claude 키가 있으면 자동). 다시 읽는 동안 합성은 `409`(`REFERENCE_STALE` / `REFERENCE_PENDING`)를 돌려줍니다. 잠시 후 다시 시도하세요.
- **예전 프로젝트의 미리보기(`flat.jpg`)**: 예전의 베이지 배경 그대로 남아 있습니다. **구조 확인에서 구조를 다시 확정하면** 검은 배경의 새 미리보기로 바뀝니다.
- **`backend/data/library` 폴더**: 이제 쓰지 않으니 지워도 됩니다. 데이터베이스의 예전 표(instructions, exports, library_items)는 앱이 시작할 때 자동으로 지웁니다.
- 디스크에 남은 예전 파일들은 무시됩니다. `~/Documents/Dieline References` 폴더는 건드리지 않습니다.

---

## 문제가 생겼을 때

| 증상 / 코드 | 뜻 | 해결 |
|---|---|---|
| `FIGMA_TOKEN_MISSING` (503) | Figma 토큰 없음 | `backend/.env`에 `FIGMA_TOKEN` 추가 후 서버 재시작 |
| `FIGMA_NOT_FOUND`, `FIGMA_NOT_FRAME` | 링크가 틀렸거나 프레임이 아님 | Figma에서 프레임을 선택하고 "링크 복사"한 주소를 쓰기 |
| `PROVIDER_UNAVAILABLE` (503) | Gemini 키 없음 | `GEMINI_API_KEY` 추가 후 재시작 |
| `CLAUDE_UNAVAILABLE` (503), 레퍼런스가 "skipped" | Claude 키 없음 | `ANTHROPIC_API_KEY` 추가 후 재시작, 레퍼런스 다시 분석 |
| `STRUCTURE_UNCONFIRMED` (409) | 구조 확인이 안 끝남 | 구조 확인 화면에서 남은 선을 확정 |
| `TOO_MANY_GENERATIONS` (429) | 이미 생성이 2개 진행 중 | 끝날 때까지 기다리기 |
| `FLAT_VERSION_MISSING` / `FLAT_VERSION_INVALID` (409) | 합성할 플랫 렌더가 없음 / legacy 버전 선택 | ②에서 플랫 렌더를 먼저 만들기 |
| `REFERENCE_PENDING` / `REFERENCE_STALE` (409) | Claude가 레퍼런스를 읽는 중 | 잠시 후 다시 시도 |
| `FACES_UNKNOWN` (409) | 입체로 접을 앞면을 못 찾음 | 패널 이름 확인, 또는 "평면" 선택 |
| `ARTWORK_MISMATCH` (422) | 결과 글자·색이 원본과 달라 버림 | 다시 생성. `_rejected.png`로 원인 확인 가능 |

---

## 폴더 지도

```
src/                      프론트엔드 (React + TypeScript)
  api/                    백엔드 호출
  features/               화면 기능별 코드 (업로드, 구조 검토, 플랫, 합성, 기록 등)
  pages/                  페이지
  i18n/ko/                한국어 화면 문구
  types/api.gen.ts        백엔드에서 자동 생성되는 타입 (직접 고치지 않음)
backend/
  .env                    API 키 (git 제외)
  app/
    api/                  HTTP 엔드포인트
    services/             pipeline(분석·② 플랫), merge(③ 합성), brief(Figma 정보 정리), finish_realism(후가공 버전·AI 사실감)
    finishing/            후가공: catalog(종류·값), spec(저장 기록), assets·masks(요소·마스크), compose, constraints(제조 점검), plates(판 파일)
    ai/                   claude.py, prompts.py, prompts/(프롬프트 파일), providers/gemini.py
    figma/                Figma 가져오기
    pdf/                  전개도 분석 (dieline.py, rules.py 등)
    render/               결정적 렌더, 표면·빛 처리, carton3d(박스 접기), verify, finishing/material.py(후가공 재질)
    jobs/runner.py        백그라운드 작업
    storage/db.py         SQLite
  data/                   프로젝트, 결과 이미지, DB (git 제외)
  tests/                  테스트
```

---

<a id="english"></a>

## English

Dieline Generator turns a packaging dieline into photoreal images while keeping the printed artwork pixel-exact.

**Three steps**

1. **Source (Figma scan).** Paste a Figma frame link (main path; a small PDF upload remains as a fallback). The app analyzes geometry, cut/fold lines, exact text and fonts, logos and measurements, then you confirm the structure.
2. **Flat render.** One flat, unfolded, top-down render on black, deterministic by default (`FLAT_RENDER_MODE=deterministic`): the vectors are rasterized once at the final size (`FLAT_LONG_EDGE`, 4096), board fibres, fold scores, light and the edge catch-light are one achromatic gain over the print, and the silhouette, openings and black ground come from the Figma structure. Optional `ai_appearance` sends `flat_render.md` + [Image 1: our render, padded to the provider aspect; Image 2: `flat_look.png`] to Gemini and keeps only a smooth, clamped, neutral light map measured away from print edges, and only if the model's board matches ours. Gated by `look.verify_flat`; QA montage: `scripts/flat_qa.py`.
3. **Reference merge.** Drop one reference photo. Claude reads it with `reference_guide.md` (category person / beverage / product_packaging, seven sections each, camera, light, and `packaging_form` flat|folded|none). Gemini then puts our approved flat render in place of the reference's packaging (`merge.md`). Form: auto follows `packaging_form` (`none` becomes folded), or override to flat/folded. Folded: `render/carton3d.py` folds the carton at Claude's camera; images are A folded carton, B reference, C flat render. Flat: A flat render, B reference.

**Redline rule.** Outer outline = cut, inner lines = fold, inner closed loops = openings (rendered black). Layer or spot-colour names (`Dieline`, `Redline`, `칼선`, `Cut`, `Fold`, `Crease`, `접는선`…, see `backend/app/pdf/rules.py`) win; a single named cut layer holding everything is split by topology; unnamed lines are split by topology; uncertain closed loops wait for a human.

**Exact text.** The model never decides the artwork. The original print is composited back over the model's light and surface, and `verify` (`render/look.py`) gates every delivery. A failure marks the version `ARTWORK_MISMATCH` and nothing is delivered. Diagnostics in `backend/data/projects/<pid>/versions/`: `<vid>_raw.png`, `<vid>_structure.png` (merge), `<vid>_rejected.png` (failed).

**Setup.** Needs pnpm and uv. Put `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` and `FIGMA_TOKEN` in `backend/.env` (`OPENAI_API_KEY` is unused and can be removed). Run `pnpm install`, then `pnpm dev` (Vite web + uvicorn API on :8000), and open the Vite URL (default http://localhost:5173; `/api` is proxied).

**Prompts.** `backend/app/ai/prompts/*.md`, filled by `prompts.render()` with `string.Template.substitute`. Edit wording freely, keep every `$placeholder`, write `$$` for a literal dollar sign. `flat_render.md` and `merge.md` are cached: restart the backend after editing. `reference_guide.md` and `flat_look.png` are read on every use.

**Old data.** Old versions show as legacy and cannot be merge sources. Old reference readings are re-read in the background (merge returns 409 until done). Old projects keep the beige `flat.jpg` until the structure is re-confirmed. `backend/data/library` can be deleted.
