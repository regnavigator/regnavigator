"""IRB/DRB 스킬 턴 로컬 모델 라우팅 (2026-08-28).

배경: 심의 질의는 연구계획·환자군 서술 등 민감 정보가 실리기 쉽다. NER
마스킹이 상용 모델 유출을 줄이지만 미탐이 남는다 — 운영 결정(2026-08-28):
**스킬 턴은 로컬 vLLM(writer 슬롯)으로 보내 상용 노출 자체를 없앤다.**

정책(서식 도우미 독립 레인과 동일 원칙):
- 로컬이 죽어 있으면 **상용으로 폴백하지 않는다** — 안내 후 턴 종료.
  (새벽 4시대 vLLM 재구동 시간대 포함. 폴백을 열면 유출 정책이 시간대에
  따라 구멍 나는 것과 같다.)
- 저장·표시는 종전대로 마스킹본(at-rest 정책 불변) — 이 모듈은 어느 모델이
  프롬프트를 보느냐만 바꾼다.
- GPU 경합은 llm_priority 로 해결 — 대화형 우선, 보고서 양보.

전제: writer vLLM 이 tool-calling 을 지원해야 한다(`--enable-auto-tool-choice
--tool-call-parser hermes`). 미지원 서버면 첫 스킬 턴이 400 으로 죽으므로
**probe 단계에서 tool 지원까지 확인**하고, 미지원이면 다운과 동일 취급한다.

스위치: `SKILL_LOCAL_MODEL=1` + base URL(`SKILL_LOCAL_BASE_URL`, 미설정 시
`REPORT_WRITER_BASE_URL` 공유). 기본 off — 켜기 전 DGX vLLM 재기동 필요.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

_log = logging.getLogger(__name__)

UNAVAILABLE_NOTICE = (
    "지금은 기관 심의(IRB·DRB) 상담 엔진이 점검 중입니다. 심의 관련 질의는 "
    "개인정보 보호를 위해 원내(온프레미스) 모델로만 처리하도록 되어 있어, "
    "엔진이 복구될 때까지 잠시 기다렸다가 다시 질문해 주세요. "
    "(새벽 시간대에는 데이터 갱신으로 몇 분간 중단될 수 있습니다. "
    "일반 규제 질의는 지금도 정상 이용 가능합니다.)"
)


def base_url() -> str:
    return ((os.getenv("SKILL_LOCAL_BASE_URL") or "").strip()
            or (os.getenv("REPORT_WRITER_BASE_URL") or "").strip())


def enabled() -> bool:
    return (os.getenv("SKILL_LOCAL_MODEL") or "").strip() == "1" and bool(base_url())


def probe() -> Optional[str]:
    """서빙 모델 id 반환(사용 가능 판정 겸). 다운·tool 미지원이면 None.

    tool 지원 확인: `tool_choice="auto"` 더미 요청 — 파서 플래그 없는 서버는
    여기서 400("requires --enable-auto-tool-choice")을 돌려준다. 이걸 첫 실제
    턴에서 맞으면 사용자 앞에서 죽으므로 probe 로 앞당긴다(수 초 캐시).
    """
    url = base_url()
    if not url:
        return None
    from src.models import _detect_served_model

    mid = _detect_served_model(url)
    if not mid:
        return None
    if not _tool_support_ok(url, mid):
        return None
    return mid


# tool 지원 캐시 — **성공만** 캐시한다(서버 재기동 전엔 안 바뀜; 모델 교체 시
# 키가 달라져 자연 재검사). 실패는 캐시하지 않는다: 운영 실측(2026-08-28)에서
# GPU 워밍업 중 1회 타임아웃이 캐시에 박혀, 서버가 멀쩡해진 뒤에도 프로세스
# 재시작 전까지 IRB 가 전부 "점검 중"으로 막혔다.
#
# (2026-09-15) 두 겹으로 바꿈 — 운영 실측: 배포 직후(캐시 빈 상태) 다른 생성이
# GPU 를 점유하면 1토큰 확인 호출이 큐에 밀려 30s 를 넘기고, 사용자는 멀쩡한 엔진을
# "점검 중"으로 안내받았다.
#   ① 성공은 app_settings KV(`skill_local_tool_ok:<model_id>`)에도 남겨 컨테이너
#      재시작 후 재확인이 필요 없다(tool 지원은 서버 배포 속성 — 부하와 무관).
#   ② 확인 호출이 **타임아웃**이면 '바쁨'으로 보고 통과시킨다 — /v1/models 가 이미
#      응답했으니 서버는 살아 있다. 실제 턴은 180s 타임아웃·llm_priority 로 처리된다.
#      다운(연결 실패)·미지원(4xx)만 False.
_tool_ok_cache: dict[str, bool] = {}
_KV_PREFIX = "skill_local_tool_ok:"
_PROBE_TIMEOUT_S = 30.0


def _kv_get(model_id: str) -> bool:
    try:
        from src.persistence.settings_repo import get_settings_repo

        return (get_settings_repo().get(_KV_PREFIX + model_id) or "") == "1"
    except Exception:  # noqa: BLE001 — KV 장애가 probe 를 막으면 안 됨
        return False


def _kv_set(model_id: str) -> None:
    try:
        from src.persistence.settings_repo import get_settings_repo

        get_settings_repo().set(_KV_PREFIX + model_id, "1", updated_by="skill_local")
    except Exception as e:  # noqa: BLE001
        _log.info("skill_local: tool ok KV 저장 실패(무시): %s", e)


def _tool_support_ok(url: str, model_id: str) -> bool:
    if _tool_ok_cache.get(model_id):
        return True
    if _kv_get(model_id):
        _tool_ok_cache[model_id] = True
        return True
    try:
        import httpx

        try:
            r = httpx.post(
                url.rstrip("/") + "/chat/completions",
                timeout=_PROBE_TIMEOUT_S,
                headers={"Authorization":
                         f"Bearer {os.getenv('REPORT_WRITER_API_KEY') or 'EMPTY'}"},
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                    "tools": [{"type": "function", "function": {
                        "name": "noop", "description": "probe",
                        "parameters": {"type": "object", "properties": {}}}}],
                    "tool_choice": "auto",
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
        except httpx.TimeoutException:
            # 서버는 살아 있는데(모델 목록 응답) 생성 큐가 밀린 것 — 바쁨. 통과.
            _log.warning("skill_local probe 타임아웃(%.0fs) — 서버 응답은 있어 '바쁨'으로 "
                         "보고 진행(캐시 안 함)", _PROBE_TIMEOUT_S)
            return True
        ok = r.status_code == 200
        if not ok:
            _log.warning("skill_local: vLLM tool 미지원/오류(%d) — %s",
                         r.status_code, r.text[:150])
            # 5xx 는 일시 장애일 수 있어 다운 취급(캐시 안 함), 4xx 는 미지원.
            return False
    except Exception as e:  # noqa: BLE001 — 연결 실패 = 다운(캐시 안 함 — 다음 턴 재시도)
        _log.info("skill_local probe 실패: %s", e)
        return False
    _tool_ok_cache[model_id] = True
    _kv_set(model_id)
    return True


def warm_up() -> Optional[str]:
    """부팅 직후 백그라운드 확인(2026-09-15) — 첫 사용자 턴이 probe 비용을 내지 않게.

    실패해도 아무것도 바꾸지 않는다(다음 턴 재확인). lifespan 이 to_thread 로 호출.
    """
    if not enabled():
        return None
    try:
        mid = probe()
        _log.info("skill_local warm-up: %s", mid or "unavailable")
        return mid
    except Exception as e:  # noqa: BLE001
        _log.info("skill_local warm-up 실패(무시): %s", e)
        return None


def build_model(model_id: str, *, max_tokens: int):
    """스킬 턴용 로컬 chat model — build_chat_model 경유(토큰 로거 부착).

    ⚠️ 폴백 없음: 상용으로 새는 폴백은 이 기능의 존재 이유를 부순다.
    """
    from src.models import build_chat_model

    return build_chat_model(
        f"openai:{model_id}",
        max_tokens=max_tokens,
        base_url=base_url(),
        api_key=os.getenv("REPORT_WRITER_API_KEY") or "EMPTY",
        timeout=180.0,  # 대화형 — writer(1800s)와 달리 짧게
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
