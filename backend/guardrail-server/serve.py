"""Guardrail PII NER 서비스 — OpenMed 다국어 PII 토큰분류 모델 서빙.

medi-back 입력 게이트의 2차 탐지(이름·주소 등 문맥 PII). DGX(GPU)에서 실행.
계약: medi-back `docs/contracts/guardrail_ner_service.md` — POST /detect → {entities:[…]}.
      각 entity: {start, end, label, text, **score**}.

`score`(2026-08-01 추가): 병합 스팬 구성 조각의 **최대 신뢰도**(0~1). 서버는
`NER_THRESHOLD`(기본 0.4)로 1차 필터만 하고 **라벨별 추가 임계값은 medi-back 이
정한다**. 배경: 일반명사가 NAME 으로 새는 오탐(`현행`·`서류가`)은 스팬 확장
차단만으로 못 잡는다 — 모델이 그 단어를 통째 스팬으로 뱉는 경우가 있어
결국 신뢰도로 걸러야 하는데, 서버가 score 를 버려서 불가능했다. 이제
medi-back 이 실트래픽 분포를 로깅해 임계값을 정한다(**서버 재배포 불필요**).

env:
- GUARDRAIL_API_KEY (또는 INSTANCE_API_KEY): X-API-Key 검증.
- NER_MODEL     : HF 모델 id (기본 OpenMed/privacy-filter-multilingual).
- NER_THRESHOLD : 신뢰도 임계값(기본 0.4). 낮추면 recall↑·오탐↑.
- NER_DEVICE    : 0=cuda:0(기본), -1=cpu.
- NER_WINDOW_STRIDE : 윈도 겹침 토큰 수(기본 64). 경계 스팬 보호.
- NER_BATCH_SIZE    : 윈도 GPU 배치 크기(기본 8 — 활성화 메모리 피크 억제).

## 긴 입력 — 서버가 윈도잉+배치로 처리한다 (2026-08-04)

예전엔 `_pipe(text)` 를 그대로 호출했다. 토큰 분류 파이프라인은 모델 상한
(이 모델은 512토큰)을 넘으면 **뒷부분을 조용히 버린다** — 사용자가 문서를
붙여넣으면 뒤쪽 이름·주소가 통째로 미탐됐다.

medi-back 이 클라이언트에서 잘라 보내는 것으로 우회했지만, 그러면 **입력 길이에
비례해 HTTP 왕복이 늘어** 큐 대기가 지배적이 된다(실측 2026-08-04: 36,000자에서
64청크 → 45~100초, 마스킹 실패). 청크 크기·병렬도·타임아웃을 바꿔도 개선되지
않았다.

그래서 서버가 직접 처리한다:
  ① 토크나이저 오프셋으로 **정확히** 512토큰 윈도로 자른다(문자 수 추정 아님).
  ② 겹치는 윈도를 **한 번의 GPU 배치**로 추론한다 — 왕복 1회, 배치 1회.
  ③ 각 윈도 스팬을 원문 오프셋으로 되돌려 기존 `_merge` 로 합친다.

`/health` 가 `long_input: true` 를 보고하므로 클라이언트는 이 기능이 있는 서버엔
통짜로 보내면 된다(medi-back `PII_NER_CHUNK_CHARS=0`).

기동:  uvicorn serve:app --host 0.0.0.0 --port 8090
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

_API_KEY = os.getenv("GUARDRAIL_API_KEY") or os.getenv("INSTANCE_API_KEY") or ""
_MODEL = os.getenv("NER_MODEL", "OpenMed/privacy-filter-multilingual")
_THRESH = float(os.getenv("NER_THRESHOLD", "0.4"))
_DEVICE = int(os.getenv("NER_DEVICE", "0"))
_STRIDE = int(os.getenv("NER_WINDOW_STRIDE", "64"))
# 배치가 클수록 활성화 메모리 피크가 커진다 — 8/4 호스트 OOM 의 병목이 정확히
# 그 지점이라 16 대신 8 로 시작한다(2026-08-04 DGX 회신 A-1 권고).
_BATCH = int(os.getenv("NER_BATCH_SIZE", "8"))

app = FastAPI(title="guardrail-ner")
_pipe = None


def _get_pipe():
    global _pipe
    if _pipe is None:
        from transformers import pipeline

        _pipe = pipeline(
            "token-classification", model=_MODEL, trust_remote_code=True,
            aggregation_strategy="simple", device=_DEVICE,
        )
    return _pipe


class _Req(BaseModel):
    text: str


# 세부 라벨 → 패밀리. 한글 이름/주소가 subword 로 쪼개지고 FIRSTNAME/LASTNAME·
# CITY/COUNTY/STREET 처럼 다른 라벨로 나오므로, 패밀리로 묶어 인접 병합해야
# 온전한 스팬이 된다(가운데 미탐 char 은 gap 으로 브리지).
_FAMILY = {}
for _l in ("FIRSTNAME", "LASTNAME", "MIDDLENAME", "NAME", "USERNAME"):
    _FAMILY[_l] = "NAME"
for _l in ("CITY", "COUNTY", "STATE", "STREET", "ZIPCODE", "BUILDINGNUMBER",
           "SECONDARYADDRESS", "ADDRESS", "NEARBYGPSCOORDINATE"):
    _FAMILY[_l] = "ADDRESS"
# 한국어 특화 모델(KLUE·모두의말뭉치 계열, 예: Leo97/KoELECTRA-small-v3-modu-ner)
# 라벨 체계(2026-08-14 교체 평가): PS=인명, LC=지명. DT(날짜)·QT(수량)는 **매핑하지
# 않는다** — 규제 본문의 시행일·기한·연령 기준이 전부 날짜/수량이라 마스킹하면
# 콘텐츠가 파괴된다(생년월일 최고위험 케이스는 medi-back regex 가 문맥 한정으로 커버).
_FAMILY["PS"] = "NAME"
_FAMILY["LC"] = "ADDRESS"


def _fam(label: str) -> str:
    return _FAMILY.get(label, label)


def _is_hangul(ch: str) -> bool:
    return "가" <= ch <= "힣"


# 이름 동반 단서 — 한국어 텍스트에서 사람 이름은 보통 호칭·직함을 동반한다.
# 일반명사("서류가"·"제재를")는 동반하지 않으므로, **1글자 씨앗 확장의 허용 조건**
# 으로 쓴다(아래 _should_extend 참조).
_NAME_CUE_RIGHT = ("님", "씨", "군", "양", "과장", "부장", "차장", "대리", "원장",
                   "선생", "교수", "박사", "환자", "의사", "간호사", "약사")
_NAME_CUE_LEFT = ("환자", "담당", "성함", "이름", "보호자", "수급자", "대상자",
                  "신청인", "민원인", "의뢰인", "대표자", "책임자",
                  # 직함·직종이 **이름 앞**에 오는 형태("간호사 한소희") — 실측
                  # 2026-08-02: 좌측 단서에 없어 1글자 씨앗 '한' 이 확장되지 못했고
                  # medi-back 1글자 가드가 폐기해 **한소희가 통째로 미마스킹**됐다.
                  "간호사", "의사", "약사", "교수", "원장", "과장", "부장",
                  "선생", "박사", "실장", "팀장")


def _should_extend(text: str, start: int, end: int) -> bool:
    """스팬 확장을 허용할지 — **1글자 노이즈 증폭 차단**.

    실측(2026-07-26, medi-back 실사용 질문 코퍼스): 이 모델은 한국어에서 **1글자
    조각**을 자주 뱉는다(예: "…할 때 현행 규제…" → ORGANIZATION ' 현', NAME '현').
    그 1글자 NAME 을 `_extend_name` 이 한글 런 끝까지 확장해 **'현행' 이라는 멀쩡한
    단어를 이름으로 만들어** 버렸다. 같은 경로로 '서류가'·'제재를'·'규정된'·
    '크로스보더' 가 마스킹돼 사용자 질문이 훼손됐다(오탐률 3.3%).

    규칙: 씨앗이 완성형 한글 2자 이상이면 확장(진짜 파편 복원 — '길동'→'홍길동').
    1자면 **호칭·직함 단서가 인접할 때만** 확장한다("김 과장", "박 님").
    단서 없는 1자 씨앗은 확장하지 않아 1글자로 남고, medi-back 의 1글자 가드가 폐기.
    """
    seed = text[start:end]
    if sum(1 for c in seed if _is_hangul(c)) >= 2:
        return True
    right = text[end:end + 4].lstrip()
    if any(right.startswith(c) for c in _NAME_CUE_RIGHT):
        return True
    left = text[max(0, start - 5):start]
    return any(c in left for c in _NAME_CUE_LEFT)


def _extend_name(text: str, start: int, end: int) -> tuple[int, int]:
    """NAME 스팬을 인접 한글 음절로 확장 — 모델이 이름 일부만 잡는 파편화 보정.

    공백·문장부호·숫자에서 멈춤(예: "환자 홍길동," 에서 '길동' 만 잡혀도 '홍'까지
    확장해 '홍길동' 온전 마스킹, 앞의 공백에서 정지).
    """
    while start > 0 and _is_hangul(text[start - 1]):
        start -= 1
    while end < len(text) and _is_hangul(text[end]):
        end += 1
    return start, end


def _merge(ents, text: str, gap: int = 1) -> list[dict]:
    """임계값 필터 + 패밀리 기준 인접 병합(한글 subword 파편 복원). char 오프셋 스팬."""
    kept = sorted(
        (e for e in ents if float(e["score"]) >= _THRESH),
        key=lambda e: int(e["start"]),
    )
    out: list[dict] = []
    for e in kept:
        g, s, en = _fam(e["entity_group"]), int(e["start"]), int(e["end"])
        sc = float(e["score"])
        if out and out[-1]["label"] == g and s - out[-1]["end"] <= gap:
            out[-1]["end"] = en
            # 병합 스팬의 score = 구성 조각 중 **최댓값**(가장 강한 근거).
            out[-1]["score"] = max(out[-1]["score"], sc)
        else:
            out.append({"start": s, "end": en, "label": g, "score": sc})
    # NAME/ADDRESS 스팬 정제 — 한글 subword 파편·역할어 오병합 보정.
    for o in out:
        if o["label"] == "NAME":
            # 한국어 이름엔 내부 공백이 없다 → 공백 있으면 마지막 공백 뒤로 트림
            # (앞 단어 오병합 제거: "담당의 김영수" → "김영수").
            sp = text[o["start"]:o["end"]].rfind(" ")
            if sp != -1:
                o["start"] = o["start"] + sp + 1
        if o["label"] in ("NAME", "ADDRESS") and _should_extend(
                text, o["start"], o["end"]):
            # 인접 한글로 확장(공백/비한글에서 정지): "길동"→"홍길동", "강남"→"강남구".
            # ※ 1글자 씨앗은 호칭 단서가 있을 때만 — 노이즈 증폭 차단(_should_extend).
            o["start"], o["end"] = _extend_name(text, o["start"], o["end"])
    for o in out:
        o["text"] = text[o["start"]:o["end"]]
        o["score"] = round(o["score"], 4)
    return out


def _auth(key: str | None) -> None:
    if _API_KEY and key != _API_KEY:
        raise HTTPException(status_code=403, detail="invalid X-API-Key")


def _max_window_tokens(tok) -> int:
    """모델이 한 번에 볼 수 있는 토큰 수(특수토큰 여유 2 제외)."""
    m = getattr(tok, "model_max_length", 512) or 512
    if m > 100000:          # 일부 토크나이저는 상한을 매우 큰 값으로 둔다
        m = 512
    return max(64, int(m) - 2)


def _line_windows(text: str) -> list[tuple[int, int]]:
    """줄 경계 윈도 — **이름 리콜 회복용**(2026-08-04 실측).

    이 모델은 이름 앞에 문맥이 붙으면 신뢰도가 급락한다:

        앞 문맥 0자 → score 0.707 ✅ / 40자 → 0.534 ✅ / 100자 이상 → 임계 미만 ❌

    그래서 512토큰 윈도로 아무리 정확히 잘라도 윈도 **내부**에 앞 문맥이 남아
    `담당자: 홍길동` 같은 명시적 이름조차 놓친다(실측 2/3). 줄 단위로 쪼개면
    각 줄이 문맥 없이 평가돼 리콜이 회복된다(실측 **3/3**).

    문서는 보통 이름을 자기 줄에 둔다(`담당자: …`, `작성자: …`) — 이 구조를 쓴다.
    비용은 배치가 흡수한다: 왕복은 여전히 1회이고 GPU 배치만 늘어난다.

    긴 줄은 512토큰을 넘을 수 있으므로 호출자가 토큰 윈도로 한 번 더 자른다.
    """
    out: list[tuple[int, int]] = []
    pos = 0
    for line in text.split("\n"):
        end = pos + len(line)
        if line.strip():
            out.append((pos, end))
        pos = end + 1
    return out or [(0, len(text))]


def _windows(text: str, tok) -> list[tuple[int, int]]:
    """[(char_start, char_end)] — 토크나이저 오프셋 기준 겹치는 512토큰 윈도.

    문자 수로 추정하지 않는다. 한국어는 subword 분해율이 커서 문자↔토큰 비율이
    문서마다 달라 추정하면 상한을 넘기거나(뒷부분 유실) 지나치게 잘게 쪼갠다.
    """
    enc = tok(text, return_offsets_mapping=True, add_special_tokens=False,
              truncation=False)
    offs = [o for o in enc["offset_mapping"] if o[1] > o[0]]
    if not offs:
        return [(0, len(text))]
    win = _max_window_tokens(tok)
    if len(offs) <= win:
        return [(0, len(text))]
    step = max(1, win - _STRIDE)
    out: list[tuple[int, int]] = []
    for i in range(0, len(offs), step):
        part = offs[i:i + win]
        if not part:
            break
        out.append((part[0][0], part[-1][1]))
        if i + win >= len(offs):
            break
    return out


@app.post("/detect")
def detect(req: _Req, x_api_key: str | None = Header(None, alias="X-API-Key")):
    _auth(x_api_key)
    text = req.text
    pipe = _get_pipe()

    # 줄 단위 우선(이름 리콜) → 각 줄이 모델 상한을 넘으면 토큰 윈도로 재분할.
    wins: list[tuple[int, int]] = []
    for ls, le in _line_windows(text):
        seg = text[ls:le]
        for ws, we in _windows(seg, pipe.tokenizer):
            wins.append((ls + ws, ls + we))
    wins = wins or [(0, len(text))]

    if len(wins) == 1 and wins[0] == (0, len(text)):
        ents = pipe(text)
    else:
        # 겹치는 윈도를 **한 번의 배치**로 — 왕복·큐 대기가 길이에 비례하지 않게.
        chunks = [text[s:e] for s, e in wins]
        results = pipe(chunks, batch_size=_BATCH)
        ents = []
        for (s, _e), res in zip(wins, results):
            for r in res:
                ents.append({**r, "start": int(r["start"]) + s,
                             "end": int(r["end"]) + s})
    # _merge 가 임계 필터 + 패밀리 인접 병합을 하므로 윈도 겹침 중복도 함께 정리된다.
    return {"entities": _merge(ents, text)}


@app.get("/health")
def health(x_api_key: str | None = Header(None, alias="X-API-Key")):
    _auth(x_api_key)
    t = time.monotonic()
    pipe = _get_pipe()  # 로드 보장
    pipe("워밍")
    return {"status": "ok", "model": _MODEL, "threshold": _THRESH,
            "warm_ms": round((time.monotonic() - t) * 1000),
            # 클라이언트가 통짜 전송 가능 여부를 판단하는 신호(2026-08-04).
            # 이 키가 없으면 구 서버 → medi-back 이 직접 잘라 보낸다.
            "long_input": True,
            "max_window_tokens": _max_window_tokens(pipe.tokenizer),
            "window_stride": _STRIDE,
            "batch_size": _BATCH}
