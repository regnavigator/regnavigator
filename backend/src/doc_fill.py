"""서류 초안 기입 — 미기입 항목 파싱·발화 대조·병합 (Phase ②, 2026-08-24).

시나리오("채팅만으로 채우기"): 서류 초안(document_draft) 완료 후 사용자가
채팅으로 정보를 말하면, 매 턴 뒤 trailing 패스가 발화 ↔ 미기입 항목을 대조
(Haiku 1콜)해 `reports.filled_values` 에 병합하고 SSE `document_update` 로
FE 문서 패널을 갱신한다. **초안이 없는 스레드에서는 아무것도 하지 않는다**
(게이트 = report_runs.latest_draft_report_for_thread — 평상시 비용 0).

날조 금지 규율 동일: 발화에 **명시된** 값만 추출한다 — 추론·보완 금지.

**독립 레인 정책(2026-08-27).** 서류 기입은 개인정보 레인이다 — 기입값
(filled_values)·발화 원문·✨ 힌트 원문은 **온프레미스 모델에만** 간다.
상용 모델은 이 레인에서 (a) 온프레미스 미설정(dev)·장애 폴백에서만 쓰이고
(b) 그때도 **마스킹본만** 보며 (c) 기존 기입값은 프롬프트에 싣지 않는다
(→ 정정 기능은 온프레미스 전용). 채팅 레인과 모델·프롬프트·데이터가 겹치지
않으므로, 정식 모델 편입 시 이 모듈만 바꾸면 된다(docs/spec/onprem_pii_model.md).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Optional

_log = logging.getLogger(__name__)

# 온프레미스 기입 레인 동시 요청 수(프로세스 로컬 — 단일 인스턴스 강제라
# 우리 서비스 트래픽에 한해 정확). FE 가 "대기 중(앞에 요청 있음)" 과
# "생성 지연" 을 구분해 표현하는 근거(2026-08-27). 빌린 장비를 우리 밖에서
# 쓰는 부하는 안 보인다 — 그래서 FE 문구도 단정이 아니라 관측 사실만 말한다.
_ASSIST_INFLIGHT = 0
_ASSIST_LOCK = __import__("threading").Lock()


def assist_inflight() -> int:
    return _ASSIST_INFLIGHT


class assist_slot:
    """with assist_slot(): — 기입 레인 LLM 호출 구간 표시."""

    def __enter__(self):
        global _ASSIST_INFLIGHT
        with _ASSIST_LOCK:
            _ASSIST_INFLIGHT += 1
        return self

    def __exit__(self, *a):
        global _ASSIST_INFLIGHT
        with _ASSIST_LOCK:
            _ASSIST_INFLIGHT = max(0, _ASSIST_INFLIGHT - 1)
        return False

# writer 지시문(_DOCUMENT_DRAFT_INSTRUCTIONS)·irb-form-filler 스킬과 동일 규격.
UNFILLED_RE = re.compile(r"\[확인 필요:\s*([^\]]+)\]")

_MATCH_PROMPT = """사용자 발화에서 아래 서류 항목의 값을 추출하라.

규칙(엄수):
- 발화에 **명시적으로 언급된** 항목만 추출한다. 추론·보완·기본값 금지.
- 값은 서류에 그대로 기입할 형태로 정리한다(예: "올 10월부터 1년" → 기간 표기).
- 해당 항목이 하나도 없으면 빈 객체 {{}} 를 출력한다.
- **JSON 객체만** 출력(다른 텍스트 금지). 키는 아래 항목명 그대로.

미기입 항목: {fields}
{filled_block}사용자 발화: {text}"""

# 이미 채워진 항목을 프롬프트에 함께 실을 때 붙는 정정 규칙. 사용자가 직접
# 입력한 값을 대화가 조용히 덮으면 안 되지만, 반대로 "아니 상호는 X야" 라는
# 정정이 무시되는 것도 UX 파탄이다 — 명시적 정정만 통과시킨다.
_CORRECTION_BLOCK = """이미 작성된 항목(현재 값): {filled}
- 위 항목은 **사용자가 그 항목을 콕 집어 고쳐 말한 경우에만** 새 값을 낸다.
  ("아니 상호는 ○○야", "주소 바꿔줘: ○○" 처럼 정정 의도가 분명할 때)
- 지나가듯 같은 값이 다시 언급된 정도로는 출력하지 않는다.
"""

_FILL_PROMPT = """서류 초안의 특정 항목을 작성하라.

서류 본문(맥락):
{body}
{chat_block}작성할 항목: {field}
사용자 힌트: {hint}

규칙(엄수):
- 본문 맥락과 힌트에 근거한 내용만 작성한다. 사실(성명·날짜·수치)을 지어내지 않는다.
- 근거가 부족해 작성할 수 없으면 정확히 `INSUFFICIENT` 만 출력한다.
- 항목에 들어갈 텍스트만 출력(항목명·설명 문구 없이)."""


def extract_unfilled_fields(body: str) -> list[str]:
    """본문의 `[확인 필요: 항목명]` 마커 → 항목명 목록(등장 순서, dedupe)."""
    out: list[str] = []
    seen: set[str] = set()
    for m in UNFILLED_RE.finditer(body or ""):
        f = m.group(1).strip()
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def apply_filled_values(body: str, filled: dict) -> str:
    """기입된 값으로 `[확인 필요: X]` 마커 치환 — 미기입 마커는 그대로 둔다
    (다운로드본에서 검토자가 빈 항목을 알아볼 수 있게)."""
    if not filled:
        return body or ""

    def _sub(m: re.Match) -> str:
        return str(filled.get(m.group(1).strip()) or m.group(0))

    return UNFILLED_RE.sub(_sub, body or "")


def _parse_json_object(raw: Any) -> dict:
    if isinstance(raw, list):  # anthropic content blocks
        raw = "".join(b.get("text", "") for b in raw if isinstance(b, dict))
    s = str(raw or "").strip()
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return {}
    if not isinstance(obj, dict):
        return {}
    return {str(k).strip(): str(v).strip() for k, v in obj.items()
            if isinstance(v, (str, int, float)) and str(v).strip()}


def _fill_model():
    """서류 기입 대조·작성 모델.

    `DOC_FILL_BASE_URL` 이 있으면 **온프레미스 OpenAI 호환 서버**를 쓴다
    (2026-08-26). 이 경로가 중요한 이유:

    - 서류 기입값은 성명·연락처·주소 같은 **개인정보 그 자체**다. 상용 모델을
      쓰면 마스킹본만 볼 수 있어 정작 그 칸을 못 채운다("문서를 작성해 주는 게
      아니다"). 온프레미스면 원문을 그대로 줘도 유출이 아니다.
    - 보고서 writer(DGX 27B)와는 **다른 호스트**여야 한다. 실측(2026-08-26):
      같은 vLLM 에 짧은 추출을 얹으면 배칭이 안 돼 긴 보고서 생성이 끝날 때까지
      막힌다(단독 29초 → 보고서 동시 161초). 별도 장비면 경합이 없다.
    - 실측: MLX Qwen3.8-27B 4bit 로 4항목(실명·연락처 포함) 7.3초 정확 추출.

    미설정 시 종전대로 상용 모델(마스킹본 처리) — 기능은 열화되지만 동작한다.

    ⚠️ **현 구성은 임시다(2026-08-26).** 지금은 사내 MLX 서버
    (192.0.2.40:8080, Qwen3.8-27B-4bit)를 빌려 쓰는 상태 — 이 장비는
    서비스 인프라가 아니라 가용성·용량 보장이 없다. 궁극적으로는
    **개인정보 처리 전용 모델을 정식 편입**해야 한다(서빙 위치·모델 선정·
    가용성 SLA 포함). 그때 바꿀 것은 env 뿐이도록 노브로만 열어 뒀다.
    후속 과제: docs/spec/onprem_pii_model.md
    """
    from src.models import build_chat_model

    base_url = (os.getenv("DOC_FILL_BASE_URL") or "").strip()
    if base_url:
        name = ((os.getenv("DOC_FILL_MODEL") or "").strip()
                or _detect_local_model(base_url))
        return build_chat_model(
            f"openai:{name}", max_tokens=600, max_retries=1,
            base_url=base_url,
            api_key=os.getenv("DOC_FILL_API_KEY") or None,
            timeout=float((os.getenv("DOC_FILL_TIMEOUT_S") or "").strip() or "60"),
        )
    return build_chat_model(
        os.getenv("DOC_FILL_MODEL")
        or os.getenv("SUBAGENT_MODEL")
        or "anthropic:claude-haiku-4-5-20251001",
        max_tokens=600,
    )


def _detect_local_model(base_url: str) -> str:
    """`/v1/models` 첫 항목 — 모델 교체 시 env 불일치로 404 나는 것 방지.

    writer 와 같은 규약(models._detect_served_model). 실패 시 빈 문자열이면
    ChatOpenAI 가 400 을 내므로 보수적 기본값을 둔다.
    """
    try:
        import httpx

        r = httpx.get(base_url.rstrip("/") + "/models", timeout=5.0)
        data = (r.json() or {}).get("data") or []
        for m in data:
            mid = str((m or {}).get("id") or "")
            # abliterated(안전장치 제거) 변형은 피한다 — 의료 규제·개인정보를
            # 다루는 경로에 가드레일 없는 모델을 쓰지 않는다.
            if mid and "abliterated" not in mid.lower():
                return mid
        if data:
            return str(data[0].get("id") or "")
    except Exception:  # noqa: BLE001 — 감지 실패는 기본값으로
        _log.info("doc fill 모델 자동 감지 실패 — 기본값 사용")
    return "qwen"


async def match_turn_to_fields(
    text: str, fields: list[str], *, model: Any | None = None,
    strict: bool = False, filled: Optional[dict] = None,
) -> dict:
    """발화 ↔ 서류 항목 대조 — 명시된 값만 {항목: 값}. 실패 시 {}.

    `filled` 를 주면 **이미 채워진 항목의 정정**까지 받는다. 안 주면 종전대로
    미기입 항목만 본다. 정정을 받는 이유: 직접 입력으로 채운 값을 대화로 못
    고치면 사용자는 "왜 반응이 없지"를 겪는다(두 입력 경로가 따로 노는 것).
    반대로 아무 언급이나 덮어쓰면 사용자가 확정한 값이 조용히 바뀐다 —
    그래서 프롬프트가 **명시적 정정만** 통과시킨다.

    `strict=True` 면 호출 실패를 **전파**한다 — 온프레미스 모델이 죽었을 때
    "매칭 없음"과 구분해 폴백을 태우기 위해서다(둘 다 {} 로 뭉뚱그리면
    장애가 조용히 기능 열화로 둔갑한다).
    """
    if not text.strip() or not (fields or filled):
        return {}
    llm = model or _fill_model()
    allowed = set(fields) | set(filled or {})
    prompt = _MATCH_PROMPT.format(
        fields=json.dumps(fields, ensure_ascii=False),
        filled_block=(_CORRECTION_BLOCK.format(
            filled=json.dumps(filled, ensure_ascii=False)) if filled else ""),
        text=text[:2000])
    try:
        res = await llm.ainvoke(prompt)
    except Exception:  # noqa: BLE001 — 대조 실패는 무해(다음 턴에 재시도됨)
        if strict:
            raise
        _log.debug("doc fill match call failed", exc_info=True)
        return {}
    values = _parse_json_object(getattr(res, "content", ""))
    # 키 검증 — 목록에 없는 항목(모델 창작 키)은 버린다.
    out = {k: v for k, v in values.items() if k in allowed}
    # 값이 그대로면 정정이 아니다 — document_update 에 "수정됨"이 헛되이 뜨는 걸 막는다.
    return {k: v for k, v in out.items()
            if not (filled and str(filled.get(k, "")) == str(v))}


_ASSIST_PROMPT = """당신은 관공서 제출 서류 작성을 돕는 도우미다.

서류: {title}
전체 항목: {fields}
이미 작성됨: {filled}
남은 항목: {remaining}

지금까지 대화:
{history}
{attachment_block}사용자: {message}

아래 JSON 형식으로만 답하라(다른 텍스트 금지):
{{"values": {{"항목명": "값"}}, "reply": "사용자에게 할 말"}}

규칙(엄수):
- values 에는 사용자 메시지에 **명시된** 항목 값만 넣는다. 추측·창작·기본값
  금지. 해당 값이 없으면 빈 객체 {{}}.
- 이미 작성된 항목은 사용자가 그 항목을 콕 집어 고쳐 말할 때만 values 에 넣는다.
- reply 는 한두 문장. 채운 항목을 확인해 주고, **위 '남은 항목' 목록에 있는
  것만** 2~3개 구체적으로 요청한다(이미 작성된 항목을 다시 요청하지 마라 —
  실측에서 채운 성명을 또 묻는 오류가 있었다). "뭘 입력해야 해" 같은 질문에는
  남은 항목에 어떤 값이 들어가는지 설명한다. 모두 작성됐으면 내보내기(원본
  서식 다운로드)를 안내한다."""


def _assist_fallback_reply(remaining: list[str], newly: dict) -> str:
    """모델 응답이 깨졌을 때의 결정적 안내 — 도우미가 침묵하면 안 된다."""
    parts = []
    if newly:
        parts.append(f"{len(newly)}개 항목을 채웠습니다.")
    if remaining:
        head = ", ".join(remaining[:3])
        parts.append(f"남은 항목은 {head}"
                     + (f" 등 {len(remaining)}개" if len(remaining) > 3 else "")
                     + "입니다. 아는 값부터 알려주세요.")
    else:
        parts.append("모든 항목이 작성됐습니다. 내보내기로 내려받아 검토하세요.")
    return " ".join(parts)


async def assistant_turn(
    title: str, fields: list[str], filled: dict, message: str,
    history: str = "", *, model: Any | None = None,
    attachment_text: str = "",
) -> tuple[str, dict]:
    """서식 작성 도우미 한 턴 — (안내 답변, 새 기입값).

    **온프레미스 전용 전제**(라우트가 강제) — 사용자가 성명·연락처를 원문
    그대로 치는 창구다. 저장 대화(마스킹본)로는 개인정보 칸을 영영 못 채우는
    구조적 한계("PII 필터링되는데 어떻게 대화로 작성하냐")를 푸는 정공법:
    이 대화는 채팅 스레드에 저장하지 않고, 로컬 모델로 직행한다.
    """
    remaining = [f for f in fields if f not in filled]
    llm = model or _fill_model()
    prompt = _ASSIST_PROMPT.format(
        title=(title or "서식")[:100],
        fields=json.dumps(fields, ensure_ascii=False),
        filled=json.dumps(filled, ensure_ascii=False),
        remaining=json.dumps(remaining, ensure_ascii=False),
        history=(history or "(없음)")[:2000],
        # 첨부 문서(사업자등록증·기존 신청서 등)에서 값 추출(2026-08-27) —
        # 이 창구는 온프레미스 전용이라 원문 그대로 안전. 규율 동일: 명시 값만.
        attachment_block=(
            "첨부 문서(여기 명시된 값도 추출 대상):\n"
            + attachment_text[:12000] + "\n\n"
            if attachment_text.strip() else ""),
        message=message[:2000])
    try:
        res = await llm.ainvoke(prompt)
        raw = getattr(res, "content", "")
    except Exception:  # noqa: BLE001 — 도우미 실패는 안내로 강등
        _log.warning("doc assist: 모델 호출 실패", exc_info=True)
        return _assist_fallback_reply(remaining, {}), {}
    obj = _parse_json_object(raw)
    # values 는 문자열 dict 로 정규화돼 나오지만, reply 까지 섞인 평면 파싱일 수
    # 있어 재추출한다.
    values_raw = obj.get("values") if isinstance(obj.get("values"), dict) else {}
    if not values_raw and isinstance(obj, dict):
        # _parse_json_object 가 중첩 dict 값을 버리므로 원문에서 한 번 더.
        m = re.search(r'"values"\s*:\s*(\{[^{}]*\})', str(raw), re.S)
        if m:
            try:
                values_raw = json.loads(m.group(1))
            except ValueError:
                values_raw = {}
    allowed = set(fields)
    values = {str(k).strip(): str(v).strip()
              for k, v in (values_raw or {}).items()
              if str(k).strip() in allowed and str(v).strip()}
    # 값이 그대로면 변경이 아니다.
    values = {k: v for k, v in values.items()
              if str(filled.get(k, "")) != str(v)}
    reply = ""
    m = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', str(raw), re.S)
    if m:
        try:
            reply = json.loads(f'"{m.group(1)}"')
        except ValueError:
            reply = m.group(1)
    reply = str(reply or "").strip()
    if not reply:
        reply = _assist_fallback_reply(
            [f for f in fields if f not in {**filled, **values}], values)
    return reply[:1000], values


def chat_context_for_fill(thread_id: str, *, max_chars: int = 4000) -> str:
    """✨ AI 작성의 근거가 될 최근 대화 발췌(마스킹 저장본).

    from-form 문서의 본문은 항목 뼈대뿐이라, 본문만 보고는 ✨ 가 전부
    "근거 부족"을 냈다("동작 자체가 안 됨" 지적의 실체). 실제 근거는 대화에
    있다. 저장 메시지는 입구 게이트를 지난 **마스킹본**이므로 상용 모델에
    보내도 안전하다(독립 레인 정책과 모순 없음).
    """
    try:
        from src.persistence.threads_repo import get_threads_repo

        msgs = get_threads_repo().get_state(thread_id).messages
    except Exception:  # noqa: BLE001 — 맥락 없이도 ✨ 는 동작(부족하면 비움)
        return ""
    out: list[str] = []
    used = 0
    for m in reversed(msgs):  # 최근 발화 우선
        role = getattr(m, "type", "")
        if role not in ("human", "ai"):
            continue
        text = m.text() if callable(getattr(m, "text", None)) else str(
            getattr(m, "content", ""))
        text = str(text or "").strip()
        if not text:
            continue
        line = ("사용자: " if role == "human" else "상담원: ") + text[:600]
        if used + len(line) > max_chars:
            break
        out.append(line)
        used += len(line)
    return "\n".join(reversed(out))


async def generate_field_value(
    body: str, field: str, hint: str = "", *, model: Any | None = None,
    chat_context: str = "",
) -> Optional[str]:
    """항목 단위 AI 작성(✨ 버튼) — 근거 부족이면 None.

    `hint` 는 에디터에서 사용자가 **그대로 친** 텍스트다("성명은 홍길동" 처럼
    개인정보가 실릴 수 있다). 온프레미스면 원문 그대로, 상용이면 마스킹 후
    전달한다 — 채팅 입구 게이트와 같은 원칙을 이 우회로에도 적용(독립 레인
    정책). 스크럽 자체가 실패하면 힌트를 버린다(안 보내는 쪽이 안전).

    `body` 는 스크럽하지 않는다 — 불변식: blob 본문에는 기입값이 치환되지
    않고(`[확인 필요:]` 마커 유지, 치환은 다운로드 시점) 초안 자체가 마스킹된
    대화 코퍼스에서 생성되므로 본문에 개인정보가 없다.
    """
    llm = model or _fill_model()
    if hint and not onprem_fill():
        try:
            from src.guardrail.gate import scrub_input

            hint, _cats = scrub_input(hint)
        except Exception:  # noqa: BLE001 — 검사 불가면 버리는 쪽이 안전
            _log.warning("doc fill: 힌트 스크럽 실패 — 힌트 제외하고 진행")
            hint = ""
    chat_block = (
        "\n상담 대화(발췌 — 여기 명시된 사실만 근거로 쓴다):\n"
        f"{chat_context[:4000]}\n\n"
        if chat_context else "\n")
    prompt = _FILL_PROMPT.format(
        body=(body or "")[:12000], chat_block=chat_block,
        field=field, hint=(hint or "(없음)")[:500])
    try:
        with assist_slot():
            res = await llm.ainvoke(prompt)
    except Exception:  # noqa: BLE001
        _log.debug("doc fill generate call failed", exc_info=True)
        return None
    raw = getattr(res, "content", "")
    if isinstance(raw, list):
        raw = "".join(b.get("text", "") for b in raw if isinstance(b, dict))
    text = str(raw or "").strip()
    if not text or text.upper().startswith("INSUFFICIENT"):
        return None
    return text[:2000]


def load_draft_state(thread_id: str) -> Optional[dict]:
    """스레드의 최신 서류 초안 상태 — 없으면 None(게이트).

    반환: {report_id, body, fields(전체), filled(dict), remaining(list)}.
    """
    from src.persistence import get_report_runs_repo, get_reports_repo
    from src.persistence import get_blob_store

    rid = get_report_runs_repo().latest_draft_report_for_thread(thread_id)
    if not rid:
        return None
    meta = get_reports_repo().get(rid)
    if not meta or meta.status != "done" or not meta.blob_uri:
        return None
    try:
        body = get_blob_store().get(meta.blob_uri)
    except Exception:  # noqa: BLE001
        _log.warning("doc fill: blob 읽기 실패 report=%s", rid)
        return None
    fields = extract_unfilled_fields(body)
    try:
        filled = json.loads(meta.filled_values or "{}")
    except ValueError:
        filled = {}
    remaining = [f for f in fields if f not in filled]
    return {"report_id": rid, "body": body, "fields": fields,
            "filled": filled, "remaining": remaining}


def draft_context_note(thread_id: str, *, title: str = "") -> Optional[str]:
    """작성 중인 서식을 **대화 모델에게** 알리는 한 줄 — 없으면 None.

    종전엔 기입이 순수 trailing 패스라 대화 모델이 서식의 존재조차 몰랐다.
    그래서 (a) 남은 칸을 물어봐 주지 못하고 (b) 사용자가 직접 입력으로 이미
    채운 값을 또 묻는 일이 생겼다 — 두 입력 경로가 한 화면에 있는데 서로를
    모르는 상태. 진행 상황을 시스템 가변부에 얹어 대화가 기입을 **거들게**
    한다. 값 자체는 넣지 않는다(개인정보를 대화 모델에 보내지 않는다 —
    기입 대조는 온프레미스 모델이 따로 한다).
    """
    state = load_draft_state(thread_id)
    if not state:
        return None
    remaining = state["remaining"]
    total = len(state["fields"])
    name = title
    if not name:
        from src.persistence import get_reports_repo

        meta = get_reports_repo().get(state["report_id"])
        name = (getattr(meta, "title", None) or "") if meta else ""
    name = name or "서식"
    if not remaining:
        # 정정(고쳐 말하기)은 온프레미스 기입 모델 전용 — 없는 환경에서 "고쳐
        # 말하면 된다"고 안내하면 사용자가 시도해도 아무 일도 안 일어난다.
        correction = ("사용자가 값을 고쳐 말하면 그 항목만 갱신된다. "
                      if onprem_fill()
                      else "값 수정은 문서에서 항목을 눌러 직접 하도록 안내하라. ")
        return (f"[작성 중인 서류] {name} — {total}개 항목 **모두 작성됨**. "
                f"{correction}다 됐으니 내려받아 검토하시라고 안내하라.")
    head = ", ".join(remaining[:6]) + ("…" if len(remaining) > 6 else "")
    return (
        f"[작성 중인 서류] {name} — {total - len(remaining)}/{total} 작성됨. "
        f"남은 항목: {head}\n"
        "- 사용자가 서류 얘기를 하면 **남은 항목을 짚어** 물어라. 한 번에 하나씩 "
        "몰지 말고 관련된 것끼리 묶어 묻는다.\n"
        "- 이미 작성된 항목은 다시 묻지 마라(위 '남은 항목'에 없는 것).\n"
        "- 값 기입은 시스템이 자동으로 한다 — 네가 값을 되풀이해 적거나 "
        "'기입했습니다'라고 단정하지 마라. 우측 문서에서 확인하시라고 안내한다.\n"
        "- 개인정보(성명·주민등록번호·연락처)는 사용자가 직접 입력하도록 "
        "권해도 된다 — 문서 항목을 클릭하면 그 자리에서 넣을 수 있다."
    )


def onprem_fill() -> bool:
    """서류 기입 모델이 온프레미스인가 — 원문 사용 가부의 **단일 판정**."""
    return bool((os.getenv("DOC_FILL_BASE_URL") or "").strip())


async def run_turn_fill(thread_id: str, user_text: str, emit,
                        raw_text: str | None = None) -> None:
    """채팅 턴 trailing 패스 — 발화로 미기입 항목을 채우고 FE 에 알린다.

    `user_text` 는 **마스킹본**, `raw_text` 는 원문(호출자가 갖고 있을 때만).
    원문은 **온프레미스 모델일 때만** 쓴다 — 서류의 성명·연락처·주소 칸은
    마스킹본으로는 영영 못 채우는데(값이 `[이름]` 으로 지워짐), 그 값을 상용
    모델에 보내는 것도 안 된다. 온프레미스면 유출이 아니므로 원문을 준다.
    """
    state = await asyncio.to_thread(load_draft_state, thread_id)
    if not state:
        return
    prior = dict(state["filled"] or {})
    use_onprem = bool(raw_text and onprem_fill())
    # 정정(이미 채운 값 고치기)은 기존 기입값을 프롬프트에 실어야 해서
    # **온프레미스 전용**이다 — 기입값은 성명·연락처 그 자체라 상용 모델에
    # 보낼 수 없다. 온프레미스면 미기입 0이어도 정정을 받고, 아니면 미기입이
    # 있을 때만 돈다.
    if use_onprem:
        if not (state["remaining"] or prior):
            return
    elif not state["remaining"]:
        return
    if use_onprem:
        # 온프레미스 — 원문으로 대조(성명·연락처 칸을 채우려면 필수).
        try:
            values = await match_turn_to_fields(
                raw_text, state["remaining"], strict=True, filled=prior)
        except Exception:  # noqa: BLE001 — 엔드포인트 장애·타임아웃
            # 폴백은 **마스킹본 + 상용 모델**. 개인정보 칸은 못 채우지만
            # 나머지는 계속 채워진다(전면 중단보다 낫다). 조용히 넘어가면
            # 안 되는 상황이라 warning — 임시 구성의 알려진 위험이다
            # (docs/spec/onprem_pii_model.md).
            # ⚠️ `filled` 는 여기 못 싣는다 — 기존 기입값(성명·연락처)을 상용
            #    모델에 보내는 셈이 된다. 폴백 중엔 정정이 안 되는 게 맞다.
            _log.warning(
                "doc fill: 온프레미스 모델(%s) 실패 — 마스킹본으로 폴백"
                "(개인정보 항목 미기입·정정 비활성)",
                os.getenv("DOC_FILL_BASE_URL"), exc_info=True)
            if not state["remaining"]:
                return  # 폴백으로 할 수 있는 일(미기입 채우기)이 없다
            from src.models import build_chat_model

            fb = build_chat_model(
                os.getenv("SUBAGENT_MODEL")
                or "anthropic:claude-haiku-4-5-20251001", max_tokens=600)
            values = await match_turn_to_fields(
                user_text, state["remaining"], model=fb)
    else:
        # 상용 기본 경로(온프레미스 미설정) — 마스킹본, 정정 없음(위 정책).
        values = await match_turn_to_fields(user_text, state["remaining"])
    if not values:
        return
    from src.persistence import get_reports_repo

    merged = await asyncio.to_thread(
        get_reports_repo().merge_filled_values, state["report_id"], values)
    remaining = [f for f in state["fields"] if f not in merged]
    # 새로 채운 것과 **고친 것**을 구분해 알린다 — FE 가 "3개 작성" 과
    # "1개 수정" 을 다르게 보여줘야 사용자가 자기 값이 바뀐 걸 알아챈다.
    corrected = sorted(k for k in values if k in prior)
    emit({
        "type": "document_update",
        "report_id": state["report_id"],
        "filled": [{"field": k, "value": v} for k, v in values.items()],
        "corrected": corrected,
        "remaining": remaining,
    })
    _log.info("doc fill: %d개 항목 기입(잔여 %d) report=%s",
              len(values), len(remaining), state["report_id"])
    # 관측 — 값은 사용자 정보라 비적재, 항목명·건수만.
    try:
        from src.persistence import get_events_repo
        from src.persistence.events_repo import Event

        await asyncio.to_thread(get_events_repo().emit, Event(
            id="", ts="", event_type="doc_fill",
            user_id=None, thread_id=thread_id, run_id=state["report_id"],
            payload_json=json.dumps({
                "filled_fields": sorted(values.keys()),
                "corrected_fields": corrected,
                "remaining": len(remaining),
                "source": "chat_turn",
            }, ensure_ascii=False)))
    except Exception:  # noqa: BLE001
        _log.debug("doc_fill event emit failed", exc_info=True)
