"""입력 게이트 오케스트레이션 — regex 1차 + NER 2차 조합.

`scrub_input(text)` 이 파이프라인 입구의 단일 진입점:
1. regex(`pii.py`)로 구조적 PII(주민번호·전화·카드·이메일·IP·차량·여권·사업자·
   지갑) 결정적 마스킹.
2. NER 서비스(`ner_client`)가 설정돼 있으면 그 결과(이름·주소 등 문맥 PII)를
   추가 마스킹. 미설정/실패 시 regex 결과 그대로(안전).

NER 라벨(OpenMed 54종) 중 **화이트리스트만** 한국어 placeholder 로 마스킹한다.
의료 규제 상담 맥락에서 마스킹 대상은 개인 식별자(이름·주소·생년월일·나이)뿐 —
금액·날짜·문서번호·기관명(식약처 등)은 **법령 콘텐츠**라 건드리면 검색 품질이
깎이므로 무시한다. 구조적 PII(주민번호·전화·카드…)는 regex 1차가 이미 커버.
"""

from __future__ import annotations

import logging
import os
import re

from src.guardrail import ner_client
from src.guardrail.pii import scrub as _regex_scrub

_log = logging.getLogger(__name__)

# 라벨별 NER 신뢰도 하한(env, 기본 0.0=끔 — 종전 동작 유지).
# 서버(NER_THRESHOLD=0.4) 위에 얹는 **2차 기준**. `[이름]` 오탐이 압도적이라
# 이름만 따로 올릴 수 있게 분리했다. 예: PII_NER_MIN_SCORE_NAME=0.9
_MIN_SCORE_ENV = {
    "[이름]": "PII_NER_MIN_SCORE_NAME",
    "[주소]": "PII_NER_MIN_SCORE_ADDRESS",
}


def _min_score_for(placeholder: str) -> float:
    """placeholder 별 신뢰도 하한. 미설정·오입력이면 0.0(필터 안 함)."""
    key = _MIN_SCORE_ENV.get(placeholder)
    raw = (os.getenv(key) if key else None) or os.getenv("PII_NER_MIN_SCORE")
    try:
        return max(0.0, min(1.0, float(raw))) if raw else 0.0
    except (TypeError, ValueError):
        return 0.0

# OpenMed 라벨 → placeholder(화이트리스트). 라벨에 아래 키워드가 포함되면 매핑.
# 여기 없는 라벨(AMOUNT·DATE·ORG·DOCNUMBER…)은 마스킹하지 않음(None → 스킵).
_LABEL_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("NAME", "PERSON", "PATIENT", "FIRSTNAME", "LASTNAME", "USERNAME"), "[이름]"),
    (("ADDRESS", "STREET", "CITY", "STATE", "ZIP", "POSTCODE", "BUILDING",
      "COUNTY", "LOCATION"), "[주소]"),
    (("BIRTH", "DOB"), "[생년월일]"),
    (("AGE",), "[나이]"),
]

# NER 오탐 가드 — 규제 도메인 어휘가 이름/주소로 오분류돼 질문이 손상되는 것 차단.
# 실측(2026-07-21): OpenMed 가 "유권해석"→NAME, "비대면진료"→ADDRESS 로 마스킹
# → 모델이 질문 핵심어를 못 봐 검색·답변이 왜곡됨. 스팬이 아래 어휘와 일치하면 스킵.
_DOMAIN_TERM_STOPLIST = frozenset({
    # 법령·해석 용어
    "유권해석", "법령해석", "해석례", "법령해석례", "질의회신",
    "판례", "판결", "행정규칙", "자치법규", "고시", "훈령", "예규",
    # 의료·진료 용어
    "비대면진료", "비대면 진료", "원격의료", "원격진료", "대면진료",
    "의료기기", "의료기관", "의료행위", "임상시험", "인허가",
    # 기관·제도
    "식약처", "식품의약품안전처", "건강보험", "요양급여", "심사평가원",
    "보건복지부", "질병관리청",
    # 성능·통계 지표 — 실측(2026-08-13, 운영 이력): "민감도·특이도" 의 '민감도'가
    # NAME 마스킹돼 보완요청 문서 핵심어가 사라졌다. '-도' 접미를 통째로 풀면
    # 행정구역(강원도)·주소 마스킹이 약화되므로 어휘로 등재한다.
    "민감도", "특이도", "정확도", "재현율", "양성예측도", "음성예측도",
    # 법·제도 용어 — '평가 유예'(신의료기술평가 유예 제도)의 '유예'가 NAME 오탐.
    # 2자라 접미 가드(3~8자) 밖 — 어휘로 등재. 배포 검증(2026-08-13)에서 '유예'를
    # 풀자 인접한 '제도의'가 대신 NAME 으로 잡혀(스팬 이동) 2자 제도 용어를 함께 등재.
    "유예", "특례", "면제", "제도", "지침", "정책", "체계", "요령",
    # 규제 문서 빈출 일반명사 — 조사 붙은 형태로 NAME 오탐(실측 2026-08-02:
    # "서류가" 0.7296 이 진짜 이름 최저값과 겹쳐 신뢰도로는 분리 불가).
    # 사람 이름과 겹치지 않는 것만 넣는다.
    # 대명사 — 절대 사람 이름이 아닌데 고신뢰로 NAME 오탐(실측: '저희' 0.8997).
    "저희", "우리", "본인", "귀사", "당사", "폐사",
    "서류", "제재", "규정", "현행", "자료", "절차", "요건", "기준", "서식",
    "신고", "허가", "인증", "심사", "승인", "등록", "갱신", "변경", "취소",
    "보고", "평가", "관리", "표시", "광고", "제조", "수입", "판매", "임상",
})


# 용언 조건·연결 어미 — 이걸로 끝나는 마지막 어절은 활용형(술어)이지 행정구역
# '면'(오포면·대소면)이 아니다. `_looks_unmaskable` ⑤ 에서 사용.
_PREDICATE_ENDINGS = (
    "하면", "되면", "지면", "으면", "려면", "다면", "라면", "보면", "시면",
)

# 행정구역·도로명 접미 — 스팬의 다른 어절이 이걸로 끝나면 주소 맥락으로 보고
# ⑤ 가드를 적용하지 않는다(마스킹 유지). '가'(종로1가)는 숫자 뒤에만 오므로
# 숫자 검사로 커버 — 여기 넣으면 주격조사('대화가')와 충돌해 가드가 무력화된다.
_ADMIN_SUFFIXES = ("시", "도", "군", "구", "읍", "면", "동", "리", "로", "길")


# 제도·행위·문서를 가리키는 한자어 접미 — 단일 어절이 이걸로 끝나면 **사람 이름일 수
# 없다**. 어휘 스토플리스트(`_DOMAIN_TERM_STOPLIST`)와 달리 새 합성어에도 자동 적용된다:
# '통합운영'을 등재하는 대신 '-운영'으로 끝나는 한 어절을 통째로 배제하므로
# '위탁운영'·'품질관리'·'사후평가' 같은 미등재 조어도 같이 막힌다.
#
# 실측(2026-08-10): "신의료기술평가 통합운영 제도의 자세한 내용은?" → '통합운영'이
# NAME 0.6611 로 마스킹돼 질문 핵심어가 `[이름]` 으로 사라졌다. 같은 배치에서 진짜
# 이름은 0.7709~0.9421(이수현씨·박민수·김영희) — score 로도 갈리지만, 종전 실측
# (`서류가` 0.7296 vs `한소희` 0.729)처럼 분포가 겹치는 사례가 있어 **형태로** 막는다.
#
# 누락(false negative) 위험: 한국어 인명·지명이 이 접미로 끝나는 경우는 없다
# (김운영·이관리 같은 이름은 존재하지 않는다). 적용 조건도 아래에서 좁게 건다 —
# 공백 없는 순수 한글 3~8자에만.
_INSTITUTIONAL_SUFFIXES = (
    # 제도·행정 행위
    "운영", "관리", "평가", "심사", "심의", "제도", "체계", "사업", "정책", "지침",
    "규정", "기준", "절차", "방안", "방식", "방법", "계획", "현황", "실적", "성과",
    "점검", "조사", "분석", "검사", "시험", "감시", "감독", "통제", "개선", "지원",
    # 문서·산출물
    "서류", "자료", "정보", "보고", "신고", "신청", "허가", "인증", "승인", "등록",
    "갱신", "변경", "취소", "고시", "공고", "훈령", "예규", "요령", "해석",
    # 대상·객체
    "시설", "장비", "제품", "기기", "기술", "서비스", "시스템", "의료", "진료",
    "치료", "처방", "급여", "수가", "약제", "성분",
    # 조직 — 기관명이 이름으로 잡히는 것도 개인정보가 아니다
    "기관", "기구", "단체", "협회", "학회", "재단", "본부", "센터", "위원회",
)


def _is_institutional_term(span: str) -> bool:
    """제도·행위·조직을 가리키는 **한 어절 한자어** 인가 — 사람 이름일 수 없다.

    조건을 좁게 건다(누락 0 원칙):
      · 공백 없음 — 진짜 주소는 다어절이라, 다어절 스팬에 이 규칙을 적용하면
        "… 테헤란로 의료기관" 같은 주소가 통째로 미마스킹될 수 있다.
      · 순수 한글(가-힣) — 숫자·영문 섞인 파편은 다른 가드가 본다.
      · 3~8자 — 2자는 접미 그 자체(운영·관리)라 판단 근거가 없고, 9자 이상은
        스팬 오인식일 가능성이 커 다른 가드에 맡긴다.
    """
    s = span.strip()
    if not s or " " in s or "\t" in s:
        return False
    if not all("가" <= c <= "힣" for c in s):
        return False
    # 모델이 조사를 스팬에 포함해 뱉는다("통합운영을") — 조사를 뗀 형태도 함께 본다.
    # ⚠️ **원형을 먼저** 판정해야 한다. 조사 목록에 '가'·'로'가 있어 먼저 떼면
    #    "사후평가"→"사후평", "변경허가"→"변경허" 가 되어 접미 매칭이 깨진다.
    candidates = [s]
    for p in _TRAILING_PARTICLES:
        if s.endswith(p) and len(s) - len(p) >= 3:
            candidates.append(s[: -len(p)])
            break
    return any(3 <= len(c) <= 8 and c.endswith(_INSTITUTIONAL_SUFFIXES)
               for c in candidates)


# 스팬 끝에 붙어 오는 조사·어미 — 모델이 명사+조사를 통째 스팬으로 뱉는다.
# 스토플리스트 대조 전에 떼어내 "서류가"·"제재를" 이 "서류"·"제재" 로 매칭되게.
_TRAILING_PARTICLES = (
    "으로써", "으로서", "이라고", "라고", "으로", "에서", "에게", "부터", "까지",
    "이나", "라도", "만큼", "처럼", "보다", "마다", "조차", "밖에", "한테",
    "을", "를", "이", "가", "은", "는", "의", "에", "로", "와", "과", "도", "만",
    "된", "될", "한", "할", "인",
)


def _stoplisted(span: str) -> bool:
    """도메인 어휘(또는 그 조사 변형)인가 — 개인정보가 아니므로 마스킹 제외.

    실측 2026-08-02: `서류가`(score 0.7296)가 진짜 이름 최저값(`한소희` 0.729)과
    **겹쳐** 신뢰도로는 분리 불가. 형태로도 진짜 이름과 구분되지 않는다.
    이 잔여분은 어휘로 거를 수밖에 없는데, 활용형을 일일이 등재하지 않도록
    **조사를 떼어 원형으로 대조**한다(긴 조사부터 — "으로"가 "로"에 선점되지 않게).

    코드 스토플리스트에 더해 **사용자 신고→관리자 승인 허용어**(`pii_terms`,
    DB 기반)도 같은 규칙으로 본다 — 새 오탐을 재배포 없이 풀 수 있는 경로
    (2026-08-13, 오탐 피드백 루프).
    """
    from src.guardrail.pii_terms import allowed_terms

    s = span.strip()
    dynamic = allowed_terms()
    if s in _DOMAIN_TERM_STOPLIST or s in dynamic:
        return True
    for p in _TRAILING_PARTICLES:
        if s.endswith(p) and len(s) > len(p):
            base = s[: -len(p)]
            if base in _DOMAIN_TERM_STOPLIST or base in dynamic:
                return True
    return False


def _looks_unmaskable(span: str) -> bool:
    """이 스팬은 **한국어 이름·주소일 수 없다** — 형태만 보는 구조적 가드.

    어휘 나열(`_DOMAIN_TERM_STOPLIST`)은 새 오탐마다 단어를 추가해야 해서 확장되지
    않는다(사용자 지적 2026-07-26: "비슷한 게 한두 개가 아님"). 여기서는 *무엇이
    개인정보일 수 없는 모양인가*로 거른다 — 새 어휘에도 자동 적용된다.

    실측 오탐(2026-07-26, 실사용 질문 120건):
      · `ㄴ`(ㄴㄴ괜찮의 첫 글자) → ADDRESS
      · `병원(B2` (B2B 걸침)     → ADDRESS
    ※ 이 가드는 **누락(false negative) 위험이 0** 이어야 한다 — 진짜 이름·주소가
      아래 조건에 걸리는 경우는 없다. 판단이 애매한 형태는 통과시켜 마스킹한다.
    """
    s = span.strip()
    if not s:
        return True
    # ① 완성형 한글(가-힣)도 영숫자도 없음 = 자모/기호 뿐 → 이름·주소일 수 없음.
    #    ("ㄴㄴ"·"ㅋㅋ"·"ㄱㅅ" 류 축약 리액션이 여기 걸린다)
    if not any("가" <= c <= "힣" or c.isalnum() for c in s):
        return True
    # ② 한 글자 → 한국어 이름·주소의 최소 단위 미만.
    if len(s) == 1:
        return True
    # ③ 괄호·슬래시가 섞인 스팬 = 토큰 경계 오인식 파편("병원(B2", "(EHR/P").
    #    진짜 이름·주소 표기에는 이 기호들이 들어가지 않는다.
    if any(c in s for c in "()[]{}/\\|<>"):
        return True
    # ④ 한글 없는 **두 글자 이하 ASCII** → 사람 이름·주소일 수 없다.
    #    실측(2026-08-03, 베타 첫날): 사용자가 `hi` 만 입력했는데 NAME 0.4991 로
    #    잡혀 입력 전체가 `[이름]` 이 되고, 모델이 "개인정보가 포함되어 필터됐다"고
    #    되물었다 — 인사만 해도 훈계당하는 첫인상. (`Hi`·`hello`·`안녕` 은 정상)
    #    가장 짧은 로마자 이름도 3자(Kim·Lee)라 2자 이하는 누락 위험이 없다.
    #    ※ 신뢰도 임계값으로는 못 막는다 — 진짜 이름 최저값(0.729)과의 사이에
    #      선을 그으려 했다가 실명이 새어 철회했다(2026-08-01, CHANGELOG).
    if len(s) <= 2 and not any("가" <= c <= "힣" for c in s) and s.isascii():
        return True
    # ⑤ 조건 어미로 끝나는 술어 스팬("…가 길어지면") → 주소일 수 없다.
    #    실측(2026-08-07): "너 토큰 한도가 얼마야? 대화가 길어지면 힘든가?" 에서
    #    ' 대화가 길어지면' 이 ADDRESS 0.671 — 행정구역 '면' 과 용언의 조건 어미
    #    '-면' 을 혼동. score 로는 못 거른다(진짜 주소 '음성군 대소면' 0.503 <
    #    오탐 0.671 — 분포 역전, DGX 실측 같은 날).
    #    누락 0 원칙 방어: ⓐ 2어절 이상일 때만(단독 '수지면' 류 옛 지명 보호)
    #    ⓑ 스팬에 숫자가 있으면 통과(번지·도로번호) ⓒ 앞 어절이 행정구역
    #    접미(시/군/구…)로 끝나면 통과(진짜 주소 맥락, '용인군 수지면').
    words = s.split()
    if (len(words) >= 2
            and words[-1].endswith(_PREDICATE_ENDINGS)
            and not any(c.isdigit() for c in s)
            and not any(w.endswith(_ADMIN_SUFFIXES) for w in words[:-1])):
        return True
    # ⑥ 제도·행위·조직 한자어 한 어절("통합운영"·"품질관리") → 사람 이름일 수 없다.
    #    어휘가 아니라 접미로 판정하므로 미등재 합성어에도 자동 적용된다.
    if _is_institutional_term(s):
        return True
    # ⑦ 부사 어미('-적으로'·'-하게'·'-스럽게')로 끝나는 한 어절 → 이름·주소일 수
    #    없다. 실측(2026-08-14, 사용자 신고): '구체적으로'가 ADDRESS 로 마스킹.
    #    '-으로' 전체는 위험('종로'는 아니지만 조사 중첩 등) — 부사 파생 어미만.
    if " " not in s and s.endswith(("적으로", "하게", "스럽게", "듯이")):
        return True
    return False


# ── 도로명 꼬리 확장 (2026-08-16) ─────────────────────────────────────────
# KoELECTRA modu-ner 의 알려진 한계: 도로명이 AF(인공물) 라벨로 나와 주소가
# 시·군·구까지만 마스킹된다("서울 성동구 성수이로 113" → "[주소] 성수이로 113").
# NER 이 [주소] 로 판정한 스팬 **바로 뒤**에 도로명+번지 패턴이 이어지면 마스킹을
# 우측으로 확장한다. 주소 문맥이 이미 확정된 곳에서만 동작하므로 "회의로 5명"
# 류('로' 조사)가 단독으로 걸릴 일은 없다(주소 스팬 없이는 발동 안 함).
_ROAD_TAIL_RE = re.compile(
    r"^[\s,]{0,3}[가-힣A-Za-z\d]{1,15}(?:대로|로|길)"
    r"(?:\s?\d{1,3}번(?:길|안길))?"
    r"\s?\d{1,4}(?:-\d{1,4})?"
    r"(?:\s?,?\s?\d{1,4}\s?(?:층|호|동)){0,3}")
# 스팬 자체가 '…로/길' 로 끝난 경우(도로명까지는 잡고 번지를 놓침) — 숫자 꼬리만 확장.
_ROAD_NUM_TAIL_RE = re.compile(
    r"^\s?\d{1,4}(?:-\d{1,4})?(?:\s?,?\s?\d{1,4}\s?(?:층|호|동)){0,3}")


def _extend_address_end(text: str, end: int, span: str) -> int:
    m = _ROAD_TAIL_RE.match(text[end:])
    if m is None and re.search(r"(?:로|길)$", span):
        m = _ROAD_NUM_TAIL_RE.match(text[end:])
    return end + m.end() if m else end


# ── 자기소개 문맥 이름 마스킹 (2026-08-16) ────────────────────────────────
# KoELECTRA 의 다른 한계: 희귀 이름을 놓친다('최다온입니다' 미탐, '독고영재'→TM
# 오라벨). 자기소개 정형 문맥("저는 X입니다"·"제 이름은 X"·"X라고 합니다")에서
# **성씨로 시작하는 2~4자 한글**만 결정적으로 마스킹 — NER 와 독립인 3중 방어선.
# 성씨 게이트 + 역할/신분 명사 차단으로 "저는 의사입니다"(의)·"저는 한국인입니다"
# (stoplist) 류 오탐을 막는다. 도메인 스토플리스트(_stoplisted)도 함께 적용.
_COMPOUND_SURNAMES = ("남궁", "황보", "제갈", "선우", "사공", "서문", "독고", "동방")
_SURNAMES = frozenset(
    "김이박최정강조윤장임한오서신권황안송류유전홍고문양손배백허남심노하곽성차주우"
    "구민진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁")
# 자기소개 위치에 오는 이름 아닌 명사(성씨 첫 글자와 겹치는 것 위주).
_INTRO_NON_NAMES = frozenset({
    "한국인", "외국인", "신입", "신참", "고객", "문외한", "임산부", "장남", "장녀",
    "성인", "주부", "노인", "임원", "원장", "이사", "전문의", "한의사", "간호사",
    "최선", "최고", "최초", "진심", "문제", "백수", "신부", "신랑", "임차인", "임대인",
})
_INTRO_NAME_RE = re.compile(
    # 이름 후보는 **lazy** — 탐욕이면 '김지원이라고' 에서 조사 '이' 까지 삼켜
    # '[이름]라고' 가 된다(이름은 잡히지만 문장이 깨짐).
    r"(?:제\s?이름은|성함은|저는|안녕하세요[,.!]?)\s*([가-힣]{2,4}?)"
    r"(?=\s?(?:입니다|이에요|예요|(?:이?라고)\s?(?:합니다|해요|불러)))")


def _looks_like_person_name(token: str) -> bool:
    if token in _INTRO_NON_NAMES or _stoplisted(token):
        return False
    if len(token) >= 3 and token[:2] in _COMPOUND_SURNAMES:
        return True
    return token[0] in _SURNAMES


def _contextual_name_scrub(text: str,
                           collect: list | None = None) -> tuple[str, list[str]]:
    """자기소개 문맥의 이름을 결정적 마스킹. (치환 텍스트, 카테고리)."""
    found: list[str] = []

    def _sub(m: re.Match) -> str:
        token = m.group(1)
        if not _looks_like_person_name(token):
            return m.group(0)
        found.append("이름")
        if collect is not None:
            collect.append({"term": token, "placeholder": "[이름]"})
        return m.group(0)[: m.start(1) - m.start(0)] + "[이름]"

    return _INTRO_NAME_RE.sub(_sub, text), found


def _placeholder_for(label: str) -> str | None:
    """화이트리스트 매핑. 대상 아니면 None(마스킹 안 함)."""
    up = (label or "").upper()
    # 한국어 특화 모델(KLUE·모두 계열) 라벨 — **정확 일치**로만 매핑한다.
    # 부분 일치 목록에 넣으면 'PS' 가 NEARBYGPSCOORDINATE 등에 오매칭된다.
    if up == "PS":
        return "[이름]"
    if up == "LC":
        return "[주소]"
    for keywords, ph in _LABEL_KEYWORDS:
        if any(k in up for k in keywords):
            return ph
    return None


def _apply_spans(text: str, spans: list[dict],
                 collect: list | None = None) -> tuple[str, list[str]]:
    """NER 스팬을 placeholder 로 치환. (치환 텍스트, 카테고리 라벨 리스트).

    오른쪽(끝 오프셋 큰 것)부터 적용해 오프셋 밀림 방지. 겹치는 스팬은 건너뜀.
    범위 밖·역전 스팬은 무시(방어적).

    collect 가 주어지면 **실제로 마스킹된 단어**를 {"term","placeholder"} 로
    담아 준다(2026-08-13 오탐 개선리스트 전수 수집용). regex 1차분(주민번호·
    전화 등 확정 PII)은 여기 오지 않는다 — 수집 대상은 NER 판정분(이름·주소류,
    오탐 가능성이 있는 것)뿐이다.
    """
    # ① 유효 스팬 수집 + **마스킹 대상만 남기기**(placeholder·오탐 가드).
    #    ⚠️ 이 필터를 겹침 제거보다 **먼저** 해야 한다. 순서가 반대면 마스킹하지도
    #    않을 스팬(PREFIX·ORG 등)이 겹침 슬롯을 차지해 **진짜 PII 를 밀어낸다** —
    #    실측(2026-07-26): "김영희 님 서울특별시 …" 에서 PREFIX(' 님')가
    #    ADDRESS('님 서울특별시 강남구 …')와 겹쳐 **주소가 통째로 미마스킹**됐다.
    maskable: list[tuple[int, int, str]] = []
    for s in spans:
        try:
            start, end = int(s["start"]), int(s["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= start < end <= len(text)):
            continue
        ph = _placeholder_for(str(s.get("label") or ""))
        if ph is None:  # 화이트리스트 밖(금액·날짜·기관 등) — 마스킹 안 함.
            continue
        span = text[start:end]
        # 신뢰도 임계값(2026-08-01) — 일반명사가 NAME 으로 새는 오탐(`현행`·
        # `서류가`)은 **형태로 구분되지 않는다**(진짜 이름과 모양이 같다).
        # 스팬 확장 차단(serve.py `_should_extend`)으로도 못 잡는다 — 모델이
        # 그 단어를 통째 스팬으로 뱉는 경우가 있기 때문(DGX 회신 2026-08-01).
        # 남은 레버는 신뢰도뿐. 서버는 NER_THRESHOLD(0.4) 1차 필터만 하므로
        # 여기서 **라벨별로 더 높은 기준**을 건다.
        # 기본 0.0 = 종전 동작 유지 — 실트래픽 score 분포(아래 로깅)를 보고
        # env 로 올린다. **서버 재배포 없이 튜닝 가능**한 것이 요점.
        score = s.get("score")
        if score is not None:
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = None
        if score is not None and score < _min_score_for(ph):
            _log.info("ner 저신뢰 스킵 %s score=%.3f span=%r", ph, score, span)
            continue
        if score is not None:
            # 임계값 튜닝용 관측 — 마스킹된 스팬의 score 분포를 남긴다.
            _log.debug("ner mask %s score=%.3f span=%r", ph, score, span)
        # 이름 오탐 가드 — 진짜 한국어 이름은 숫자를 포함하지 않는다. "제2026-" 같은
        # 문서번호/법령참조가 NAME 으로 잘못 라벨링된 경우 스킵(법령 콘텐츠 보호).
        if ph == "[이름]" and any(c.isdigit() for c in span):
            continue
        # 도메인 어휘 오탐 가드 — "유권해석"→이름, "비대면진료"→주소 같은 오분류 스킵.
        # 조사 변형까지 흡수한다("서류가"→"서류") — 목록에 활용형을 일일이 넣지
        # 않게. 모델이 조사를 스팬에 포함해 뱉는 일이 잦다(실측: 서류가·제재를).
        if _stoplisted(span):
            continue
        # 구조적 오탐 가드 — 개인정보일 수 없는 *모양*(자모뿐·1글자·괄호 파편).
        if _looks_unmaskable(span):
            continue
        # 주소 스팬 우측의 도로명+번지 꼬리 흡수(AF 라벨 한계 보정).
        if ph == "[주소]":
            end = _extend_address_end(text, end, span)
        maskable.append((start, end, ph))

    # ② 겹침 제거 — 같은 시작이면 **긴 스팬 우선**(부분 마스킹으로 PII 꼬리가
    #    남는 것 방지). 그 외엔 앞선 것 우선.
    maskable.sort(key=lambda t: (t[0], -(t[1] - t[0])))
    picked: list[tuple[int, int, str]] = []
    last_end = -1
    for start, end, ph in maskable:
        if start >= last_end:
            picked.append((start, end, ph))
            last_end = end

    # ③ 오른쪽부터 치환 — 오프셋 밀림 방지.
    found: list[str] = []
    out = text
    for start, end, ph in sorted(picked, key=lambda t: t[0], reverse=True):
        found.append(ph.strip("[]"))
        if collect is not None:
            collect.append({"term": text[start:end], "placeholder": ph})
        out = out[:start] + ph + out[end:]
    found.reverse()  # 등장 순서로
    return out, found


class PiiScanIncomplete(RuntimeError):
    """문맥 PII(이름·주소) 검사가 입력 전 구간을 덮지 못했다.

    regex 1차는 구조적 PII(주민번호·전화·카드)만 잡는다. **이름·주소는 NER 이
    유일한 방어선**이라, NER 스캔이 불완전하면 그 구간은 마스킹 없이 DB 에
    저장되고 Anthropic 으로 나간다.

    예전엔 이걸 경고만 찍고 통과시켰다(fail-open). 의료 규제 상담이라 입력에
    진료기록·환자정보가 실릴 수 있고, 한 번 새면 되돌릴 수 없다 — 그래서
    **차단**으로 바꿨다(2026-08-04). 호출자가 사용자에게 재시도를 안내한다.
    """


def _strict() -> bool:
    """1(기본)=불완전 스캔 시 차단. 0=경고만 남기고 통과(종전 fail-open).

    끄면 가용성은 올라가지만 **이름·주소가 마스킹되지 않은 채 저장·전송될 수
    있다**. 끄기 전에 그 의미를 이해할 것.
    """
    return (os.getenv("PII_GATE_STRICT") or "1").strip() != "0"


def scrub_input(text: str,
                collect: list | None = None) -> tuple[str, list[str]]:
    """입구 게이트 — regex 1차 + NER 2차. (치환 텍스트, 카테고리).

    NER 스캔이 전 구간을 덮지 못하면 `PiiScanIncomplete` — 기본 동작이 차단이다.
    collect: NER 마스킹 단어 수집 리스트(`_apply_spans` 참조) — 사용자 입력
    1회 경로(chat_loop at-rest)에서만 넘긴다. egress 재스크럽에 넘기면 같은
    턴이 매 호출 중복 집계된다.
    """
    out, cats = _regex_scrub(text)
    if not ner_client.is_available():
        # 서비스 미설정 = 이름·주소 방어선 없음. dev 는 이 상태가 정상이므로
        # strict 여도 통과시키되(설정으로 끈 것), 운영은 /readyz 가 경고한다.
        out, intro_cats = _contextual_name_scrub(out, collect)
        return out, cats + intro_cats

    spans, complete = ner_client.detect_spans(out)
    if spans:
        out, ner_cats = _apply_spans(out, spans, collect)
        cats = cats + ner_cats
    # 자기소개 문맥 이름(성씨 게이트) — NER 미탐 보정. NER 이 이미 마스킹한
    # 구간은 placeholder 라 재매칭되지 않는다(멱등).
    out, intro_cats = _contextual_name_scrub(out, collect)
    cats = cats + intro_cats
    if not complete:
        _log.error(
            "PII 문맥 검사 불완전 — 입력 %d자. 이름·주소가 마스킹되지 않았을 수 "
            "있다. strict=%s", len(text), _strict())
        if _strict():
            raise PiiScanIncomplete(
                "개인정보 검사를 끝내지 못했습니다. 잠시 후 다시 시도하거나 "
                "입력을 더 짧게 나눠서 보내주세요.")
    return out, cats


def scrub_content(content):
    """메시지 content(str 또는 Anthropic 블록 리스트) 스크럽 — (새 content, 카테고리).

    구 `middleware/pii_gate._scrub_content` 이관(ADR-0001 Phase 5).
    regex 1차 + (설정 시) NER 2차 = `scrub_input`.
    """
    if isinstance(content, str):
        return scrub_input(content)
    if isinstance(content, list):
        found = []
        out_blocks = []
        for b in content:
            if isinstance(b, dict) and isinstance(b.get("text"), str):
                new_text, f = scrub_input(b["text"])
                found.extend(f)
                out_blocks.append({**b, "text": new_text})
            else:
                out_blocks.append(b)
        return out_blocks, found
    return content, []
