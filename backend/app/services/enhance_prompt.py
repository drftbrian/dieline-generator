"""Natural-language enhancement prompts -> a validated appearance specification.

Priority (server-enforced, never overridable by the prompt):
  1. the immutable design policy (``PROTECTED``): typography, logos, printed artwork and colours,
     dieline geometry, panels, the flat top-down presentation;
  2. the approved appearance capabilities (``EnhanceSpec`` fields);
  3. the user's prompt, treated as untrusted data and only ever turned into an ``EnhanceSpec``.

The raw prompt never reaches the image model. Two independent readers find what each clause
asks for: deterministic rules (Korean and English, operation = action + protected object, with
preservation phrases such as "keep the logo" recognised) and, when available, Claude with a
strict schema. A protected operation found by either one blocks the request; the user can then
confirm the permitted-only part explicitly, which is recorded with what was dropped.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field

from app.ai import claude
from app.errors import ApiError

MAX_PROMPT = 1000

LightDirection = Literal["overhead", "top_left", "top", "top_right", "left", "right"]
LIGHT_ANGLES: dict[str, int] = {
    "overhead": 315,  # the v3/v4 key light: soft, from the upper left
    "top_left": 315,
    "top": 0,
    "top_right": 45,
    "left": 270,
    "right": 90,
}


class EnhanceSpec(BaseModel):
    """The only things a prompt can change: physical appearance, each in a documented range.

    0.5 is "as the standard enhancement"; 0 is "none of this extra"; 1 is the validated maximum.
    Fold, edge and contact-shadow extras default to 0 (the source render already has its own).
    """

    material_detail: float = Field(0.5, ge=0, le=1)  # overall material realism
    paper_texture: float = Field(0.5, ge=0, le=1)  # fibre / matte surface detail
    lighting_softness: float = Field(0.5, ge=0, le=1)  # 1 = softest, most even light
    lighting_direction: LightDirection = "overhead"
    fold_depth_appearance: float = Field(0.0, ge=0, le=1)  # extra perceived crease depth
    fold_shadow: float = Field(0.0, ge=0, le=1)  # extra groove / shoulder shadow
    fold_highlight: float = Field(0.0, ge=0, le=1)  # extra light on the fold shoulders
    edge_shading: float = Field(0.0, ge=0, le=1)  # extra board-thickness shading at cuts
    contact_shadow: float = Field(0.0, ge=0, le=1)  # requested contact shadow (see notes)
    overall_strength: float = Field(1.0, ge=0, le=1)  # "subtle" lowers every effect


Category = Literal[
    # allowed
    "paper_material",
    "lighting",
    "shadows",
    "fold_appearance",
    "edge_appearance",
    # protected
    "typography",
    "logo_brand",
    "colour",
    "artwork",
    "geometry",
    "presentation",
    "policy_override",
    # neither
    "preserve",  # "keep the graphics exactly as designed": agrees with the policy, no effect
    "other",  # not an appearance request we recognise: no effect, reported in notes
]
APPEARANCE_CATS: set[str] = {
    "paper_material",
    "lighting",
    "shadows",
    "fold_appearance",
    "edge_appearance",
}
PROTECTED_CATS: set[str] = {
    "typography",
    "logo_brand",
    "colour",
    "artwork",
    "geometry",
    "presentation",
    "policy_override",
}

PROTECTED_MESSAGE = (
    "이 요청에는 보호된 디자인 요소를 바꾸는 내용이 있습니다. AI 보정은 재질·조명·그림자·물리적 "
    "표현만 바꿀 수 있고, 글자·로고·색·패키지 구조는 바꿀 수 없습니다."
)


class Operation(BaseModel):
    text: str  # the clause, as written
    category: Category
    allowed: bool  # False only for protected operations


class Interpretation(BaseModel):
    prompt: str
    operations: list[Operation]
    spec: EnhanceSpec
    notes: list[str]  # what could not be applied as asked, in Korean
    reader: Literal["rules", "rules+claude"]

    @property
    def forbidden(self) -> list[Operation]:
        return [o for o in self.operations if not o.allowed]


# ---- deterministic reader ---------------------------------------------------------------

_W = r"[\w가-힣]*"  # Korean particles / English inflections after a stem


def _rx(*words: str) -> re.Pattern:
    return re.compile("|".join(rf"(?:{w}){_W}" for w in words), re.IGNORECASE)


PROTECTED_OBJECTS: dict[str, re.Pattern] = {
    "typography": _rx(
        r"\btext(?!ur)",  # text, not texture
        r"\btype(face|setting)?\b",
        r"\bfont",
        r"\bletter",
        r"\bword",
        r"\bheadline",
        r"\btitle",
        r"\bcopy\b",
        r"\bspelling",
        r"\bkerning",
        r"\btracking",
        r"\bbarcode",
        "글자",
        "글씨",
        "텍스트",
        "문구",
        "폰트",
        "서체",
        "타이포",
        "제목",
        "제품명",
        "자간",
        "행간",
        "바코드",
    ),
    "logo_brand": _rx(r"\blogo", r"\bbrand", r"\bwordmark", r"\bicon", "로고", "브랜드", "아이콘"),
    "colour": _rx(
        r"\bcolou?r",
        r"\bhue\b",
        r"\bred\b",
        r"\bblue\b",
        r"\bgreen\b",
        r"\byellow\b",
        r"\bpink\b",
        r"\bpurple\b",
        r"\borange\b",
        r"\bgold(en)?\b",
        r"\bsilver\b",
        "색",
        "컬러",
        "빨간",
        "파란",
        "초록",
        "노란",
        "분홍",
        "보라",
        "금색",
        "은색",
    ),
    "artwork": _rx(
        r"\bartwork",
        r"\bgraphic",
        r"\bpattern",
        r"\billustration",
        r"\bgradient",
        r"\bdesign",
        r"\blayout",
        r"\bimage\b",
        "그래픽",
        "패턴",
        "일러스트",
        "그라데이션",
        "디자인",
        "레이아웃",
        "그림(?!자)",  # 그림 (picture), not 그림자 (shadow)
    ),
    "geometry": _rx(
        r"\bhole",
        r"\bslot",
        r"\bcut(s|ting)?\b",
        r"\bdieline",
        r"\bsilhouette",
        r"\bshape",
        r"\bpanel",
        r"\bflap",
        r"\btab\b",
        r"\boutline",
        r"\bdimension",
        r"\bsize\b",
        r"\bproportion",
        "구멍",
        "칼선",
        "재단",
        "모양",
        "형태",
        "패널",
        "날개",
        "외곽",
        "치수",
        "크기",
        "비율",
    ),
    "presentation": _rx(
        r"\bbackground",
        r"\bscene",
        r"\btable",
        r"\bwood",
        r"\bperspective",
        r"\bcamera",
        r"\bangle\b",
        r"\b3d\b",
        r"\bfold(ed)? (it )?into",
        r"\bbox\b",
        r"\bprops?\b",
        "배경",
        "장면",
        "테이블",
        "나무",
        "원근",
        "카메라",
        "각도",
        "입체",
        "상자",
        "소품",
    ),
}
CHANGE_VERBS = _rx(
    r"\bchang",
    r"\breplac",
    r"\bswap",
    r"\bmov",
    r"\bshift",
    r"\brotat",
    r"\bturn",
    r"\brecolou?r",
    r"\bredraw",
    r"\bredesign",
    r"\brewrit",
    r"\bremov",
    r"\bdelet",
    r"\berase",
    r"\badd",
    r"\binsert",
    r"\bcreat",
    r"\bput\b",
    r"\bmake\b",
    r"\bset\b",
    r"\bresiz",
    r"\benlarg",
    r"\bshrink",
    r"\bbigger",
    r"\bsmaller",
    r"\blarger",
    r"\bbolder",
    r"\btranslat",
    r"\bcut\b",
    r"\bpunch",
    r"\bfold\b",
    r"\bplace",
    "바꿔",
    "바꾸",
    "변경",
    "교체",
    "이동",
    "옮겨",
    "옮기",
    "회전",
    "돌려",
    "추가",
    "넣어",
    "삭제",
    "지워",
    "없애",
    "키워",
    "줄여",
    "크게",
    "작게",
    "새로",
    "다시 그려",
    "만들어",
    "뚫어",
    "접어",
    "재디자인",
)
PRESERVE = _rx(
    r"\bkeep",
    r"\bpreserv",
    r"\bretain",
    r"\bmaintain",
    r"\bwithout (chang|alter|mov|touch|modif)",
    r"\bdo ?n['o]?t (chang|alter|mov|touch|modif)",
    r"\bnever (chang|alter|mov)",
    r"\bunchanged",
    r"\bas designed",
    r"\bexactly as",
    r"\bintact",
    r"\bleave .* (alone|as)",
    "유지",
    "그대로",
    "바꾸지 ?말",
    "건드리지",
    "변경하지 ?말",
    "손대지",
)
OVERRIDE = re.compile(
    r"ignore (all |any |the )?(previous|prior|above|earlier|system)|disregard (the |all )?"
    r"(previous|prior|above|rules|instructions)|system prompt|you are now|new instructions|"
    r"jailbreak|override (the )?(policy|rules|protection)|이전 (지시|명령|규칙).{0,6}무시|"
    r"(지시|규칙|명령|정책).{0,4}무시|시스템 프롬프트|보호.{0,6}(끄|해제|무시)",
    re.IGNORECASE,
)
# "Add another fold" is geometry; "make the folds deeper" is appearance.
NEW_STRUCTURE = re.compile(
    r"\b(add|insert|create|another|extra|new)\b"
    r"(?:(?!realis|depth|shadow|highlight|texture|look|light|detail)[^.]){0,20}"
    r"\b(fold|crease|score|cut|hole|slot|"
    r"panel|flap|tab)\w*(?! ?(shadow|highlight|depth|appearance|look|realism|line shadow))|"
    r"(접는선|칼선|구멍|패널|날개|탭).{0,6}(추가|더 만들|하나 더|새로)|"
    r"(새|새로운|추가) ?(접는선|칼선|구멍|패널|날개|탭)",
    re.IGNORECASE,
)

APPEARANCE: dict[str, re.Pattern] = {
    "fold_appearance": _rx(
        r"\bfold",
        r"\bcrease",
        r"\bscor(e|ed|ing)",
        r"\bhinge",
        r"\bgroove",
        r"\bshoulder",
        "접는선",
        "접힘",
        "접힌",
        "접지선",
        "크리즈",
        "오시",
        "홈",
        "경첩",
    ),
    "paper_material": _rx(
        r"\bpaper",
        r"\bcardboard",
        r"\bboard\b",
        r"\bmatte?\b",
        r"\btexture",
        r"\bfib(er|re)",
        r"\bgrain",
        r"\bmaterial",
        r"\bsurface",
        r"\bstock\b",
        "종이",
        "판지",
        "보드",
        "무광",
        "질감",
        "재질",
        "섬유",
        "결",
        "표면",
        "소재",
    ),
    "lighting": _rx(
        r"\blight",
        r"\bstudio",
        r"\billuminat",
        r"\bexposure",
        r"\bsoftbox",
        r"\breflect",
        r"\bhighlight",
        r"\bphoto",
        "조명",
        "빛",
        "스튜디오",
        "반사",
        "하이라이트",
        "사진",
        "광",
    ),
    "shadows": _rx(
        r"\bshadow", r"\bshade", r"\bocclusion", r"\bdepth", "그림자", "음영", "그늘", "깊이"
    ),
    "edge_appearance": _rx(
        r"\bedge",
        r"\bthickness",
        r"\bdie[- ]?cut edge",
        r"\bcut edge",
        "모서리",
        "가장자리",
        "단면",
        "두께",
        "엣지",
    ),
}
SUBTLE = _rx(
    r"\bsubtl",
    r"\bdelicat",
    r"\bslight",
    r"\bgentl",
    r"\bfaint",
    r"\bsoft(er|ly)?\b",
    r"\blight(ly)? touch",
    "은은",
    "살짝",
    "미세",
    "약간",
    "부드럽",
    "섬세",
)
MORE = _rx(
    r"\bmore\b",
    r"\bincreas",
    r"\bdeeper",
    r"\bstronger",
    r"\benhanc",
    r"\bimprov",
    r"\brealistic",
    r"\bphysical",
    "더",
    "강하게",
    "깊게",
    "진하게",
    "사실적",
    "실감",
    "개선",
    "향상",
)
MUCH = _rx(r"\bmuch\b", r"\bsignificant", r"\bstrong(ly)?\b", r"\bdramatic", "훨씬", "많이", "확실")
LESS = _rx(r"\bless\b", r"\breduc", r"\bweaker", r"\blighter\b", "덜", "줄여", "약하게", "연하게")
SOFT = _rx(r"\bsoft", r"\bdiffus", r"\beven(ly)?\b", "부드럽", "확산", "고르게", "은은")
HARD = _rx(r"\bhard\b", r"\bcontrast", r"\bcrisp light", r"\bdirectional", "강한 빛", "대비")
DIRECTIONS = [
    ("top_left", _rx(r"\b(upper|top)[- ]left", "왼쪽 위", "좌상단")),
    ("top_right", _rx(r"\b(upper|top)[- ]right", "오른쪽 위", "우상단")),
    ("left", _rx(r"\bfrom the left", r"\bleft side", "왼쪽")),
    ("right", _rx(r"\bfrom the right", r"\bright side", "오른쪽")),
    ("top", _rx(r"\bfrom (the )?top", r"\bfrom above", "위에서", "위쪽")),
    ("overhead", _rx(r"\boverhead", r"\btop[- ]down", "정면 위", "머리 위")),
]
CONTACT = _rx(
    r"\bcontact shadow", r"\bdrop shadow", r"\bground shadow", "접지 그림자", "바닥 그림자"
)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    return re.sub(r"[ \t]+", " ", text).strip()


def clauses(text: str) -> list[str]:
    """Split into instructions: sentences, then ';' and 'and/but/while/그리고/하지만' joins."""
    parts = re.split(
        r"(?<=[.!?。])\s+|\n+|;|(?:,\s*)?\b(?:and|but|while|then)\b|그리고|하지만|그런데|,", text
    )
    pieces = [p.strip(" ,.") for p in parts if p and p.strip(" ,.")]
    # A one- or two-word fragment ("Soft", "더") belongs to the instruction after it.
    out: list[str] = []
    carry = ""
    for piece in pieces:
        if len(piece.split()) <= 2 and not re.search(r"[가-힣]{4,}", piece):
            carry = f"{carry} {piece}".strip()
            continue
        out.append(f"{carry} {piece}".strip() if carry else piece)
        carry = ""
    if carry:
        out.append(carry)
    return out


def _level(clause: str) -> float:
    if LESS.search(clause):
        return 0.15
    if MUCH.search(clause):
        return 0.9
    if SUBTLE.search(clause):
        return 0.35
    if MORE.search(clause):
        return 0.6
    return 0.5


def classify(clause: str) -> Category:
    """What one clause asks for: a protected operation, or an appearance category."""
    if OVERRIDE.search(clause):
        return "policy_override"
    if NEW_STRUCTURE.search(clause):
        return "geometry"
    preserving = bool(PRESERVE.search(clause))
    if not preserving and CHANGE_VERBS.search(clause):
        for cat in ("typography", "logo_brand", "artwork", "geometry", "presentation", "colour"):
            if PROTECTED_OBJECTS[cat].search(clause):
                # "make the fold shadows deeper" mentions no protected object; "change the
                # background" does. Appearance words next to a geometry noun ("panel edges")
                # are still appearance.
                if cat == "geometry" and any(
                    APPEARANCE[a].search(clause) for a in ("shadows", "edge_appearance", "lighting")
                ):
                    continue
                return cat
    if not preserving and PROTECTED_OBJECTS["presentation"].search(clause):
        return "presentation"  # "on a wooden table", "in perspective": no verb needed
    for cat in ("fold_appearance", "edge_appearance", "shadows", "paper_material", "lighting"):
        if APPEARANCE[cat].search(clause):
            return cat
    return "preserve" if preserving else "other"


def rules_spec(ops: list[Operation]) -> tuple[EnhanceSpec, list[str]]:
    spec = EnhanceSpec()
    notes: list[str] = []
    values = spec.model_dump()
    levels = []
    for op in ops:
        if op.category not in APPEARANCE_CATS:
            if op.category == "other":
                notes.append(f"외관 요청으로 인식하지 못해 반영하지 않음: {op.text}")
            continue
        c, lv = op.text, _level(op.text)
        levels.append(lv)
        if op.category == "fold_appearance" or (
            op.category in ("shadows", "lighting") and APPEARANCE["fold_appearance"].search(c)
        ):
            shadow = bool(APPEARANCE["shadows"].search(c))
            light = bool(APPEARANCE["lighting"].search(c))
            depth = bool(re.search(r"depth|deep|groove|compress|press|깊|눌", c, re.I))
            if not (shadow or light or depth):
                shadow = light = depth = True
            if shadow:
                values["fold_shadow"] = max(values["fold_shadow"], lv)
            if light:
                values["fold_highlight"] = max(values["fold_highlight"], lv)
            if depth or shadow:
                values["fold_depth_appearance"] = max(values["fold_depth_appearance"], lv)
        if op.category == "paper_material" or APPEARANCE["paper_material"].search(c):
            values["paper_texture"] = max(values["paper_texture"], 0.5 + 0.5 * (lv - 0.15))
            values["material_detail"] = max(values["material_detail"], 0.5 + 0.5 * (lv - 0.15))
            if LESS.search(c):
                values["paper_texture"] = min(values["paper_texture"], 0.3)
        if op.category == "lighting":
            if SOFT.search(c):
                values["lighting_softness"] = max(values["lighting_softness"], 0.75)
            if HARD.search(c):
                values["lighting_softness"] = min(values["lighting_softness"], 0.25)
            for name, rx in DIRECTIONS:
                if rx.search(c):
                    values["lighting_direction"] = name
                    break
        if op.category == "edge_appearance":
            values["edge_shading"] = max(values["edge_shading"], lv)
        if CONTACT.search(c):
            values["contact_shadow"] = max(values["contact_shadow"], lv)
            notes.append(
                "접지 그림자는 원본 렌더의 바닥·외곽과 함께 고정되어 있어 AI 보정으로 바꾸지 "
                "않습니다 (외곽 보호)."
            )
        if op.category == "shadows" and not APPEARANCE["fold_appearance"].search(c):
            values["fold_shadow"] = max(values["fold_shadow"], lv * 0.6)
            values["edge_shading"] = max(values["edge_shading"], lv * 0.6)
    if levels and all(lv <= 0.35 for lv in levels):
        values["overall_strength"] = 0.7
    return EnhanceSpec(**values), notes


def read_rules(prompt: str) -> list[Operation]:
    ops = []
    for c in clauses(prompt):
        cat = classify(c)
        ops.append(Operation(text=c, category=cat, allowed=cat not in PROTECTED_CATS))
    return ops


# ---- Claude reader (optional, schema-validated) ------------------------------------------


def read_claude(prompt: str) -> tuple[list[Operation], EnhanceSpec] | None:
    if not claude.available():
        return None
    try:
        reading = claude.interpret_enhancement(prompt)
    except ApiError:
        return None
    ops = [
        Operation(text=o.text, category=o.category, allowed=o.category not in PROTECTED_CATS)
        for o in reading.operations
    ]
    raw = reading.spec.model_dump()
    clamped = {k: (min(1.0, max(0.0, v)) if isinstance(v, float) else v) for k, v in raw.items()}
    spec = EnhanceSpec(**clamped)  # validated ranges and enums
    return ops, spec


# ---- entry point --------------------------------------------------------------------------


def interpret(prompt: str | None) -> Interpretation:
    """Read a prompt into operations and a spec. An empty prompt is the standard enhancement.

    A protected operation found by the rules *or* by Claude is a protected operation."""
    text = normalize(prompt or "")
    if len(text) > MAX_PROMPT:
        raise ApiError(
            422,
            "PROMPT_TOO_LONG",
            f"요청은 {MAX_PROMPT}자 이내로 적어주세요.",
            details={"length": len(text), "max": MAX_PROMPT},
        )
    if not text:
        return Interpretation(
            prompt="", operations=[], spec=EnhanceSpec(), notes=[], reader="rules"
        )
    ops = read_rules(text)
    spec, notes = rules_spec(ops)
    reader: Literal["rules", "rules+claude"] = "rules"
    second = read_claude(text)
    if second is not None:
        c_ops, c_spec = second
        reader = "rules+claude"
        flagged = {_key(o.text) for o in ops if not o.allowed}
        for o in c_ops:  # Claude can only add protected findings, never clear the rules'
            if not o.allowed and _key(o.text) not in flagged:
                ops.append(o)
                flagged.add(_key(o.text))
        if all(o.allowed for o in ops):
            spec = c_spec
    if not any(o.category in APPEARANCE_CATS for o in ops) and not interp_forbidden(ops):
        notes.append("인식된 외관 요청이 없어 기본 보정으로 진행합니다.")
    return Interpretation(prompt=text, operations=ops, spec=spec, notes=notes, reader=reader)


def _key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text).lower()


def interp_forbidden(ops: list[Operation]) -> list[Operation]:
    return [o for o in ops if not o.allowed]


def permitted(interp: Interpretation, confirm_allowed_only: bool) -> Interpretation:
    """Raise unless the request is safe to run: no protected operation, or the user confirmed
    running only the permitted part (and there is one)."""
    forbidden = interp.forbidden
    if not forbidden:
        return interp
    allowed = [o for o in interp.operations if o.category in APPEARANCE_CATS]
    details = {
        "forbidden": [o.model_dump() for o in forbidden],
        "allowed": [o.model_dump() for o in allowed],
        "allowed_only_prompt": ". ".join(o.text for o in allowed),
    }
    if confirm_allowed_only and allowed:
        spec, notes = rules_spec(allowed)
        return Interpretation(
            prompt=interp.prompt,
            operations=interp.operations,
            spec=spec,
            notes=notes + [f"제외된 요청: {o.text}" for o in forbidden],
            reader=interp.reader,
        )
    raise ApiError(
        422,
        "PROMPT_PROTECTED",
        PROTECTED_MESSAGE,
        hint="허용된 부분만 적용하려면 확인해주세요."
        if allowed
        else "재질, 조명, 그림자, 접는선 표현에 대한 요청으로 바꿔주세요.",
        details=details,
    )


def appearance_text(spec: EnhanceSpec) -> str:
    """The spec as backend-written prompt lines for the image model (no user text)."""

    def amount(v: float) -> str:
        return (
            "none"
            if v < 0.05
            else "subtle"
            if v < 0.4
            else "moderate"
            if v < 0.75
            else "pronounced"
        )

    softness = spec.lighting_softness
    light = (
        "very soft and even"
        if softness >= 0.7
        else "soft"
        if softness >= 0.35
        else "gently directional"
    )
    return "\n".join(
        [
            f"- Paperboard fibre / matte surface detail: {amount(spec.paper_texture)}.",
            f"- Overall material realism: {amount(spec.material_detail)}.",
            f"- Studio light: {light}, key light from the {spec.lighting_direction.replace('_', ' ')}.",
            f"- Fold score impressions: {amount(max(spec.fold_depth_appearance, 0.3))}.",
            f"- Cut-edge board thickness cues: {amount(max(spec.edge_shading, 0.2))}.",
        ]
    )
