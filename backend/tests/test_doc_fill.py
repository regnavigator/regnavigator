"""서류 초안 기입(Phase ②, 2026-08-24) — 턴 대조·병합·SSE document_update.

"채팅만으로 채우기": 미기입 서류 초안이 있는 스레드에서 발화의 명시 값만
추출해 filled_values 에 병합하고 FE 에 document_update 를 보낸다.
초안 없는 스레드 = repo 조회 1번(LLM 콜 0) — 게이트 검증 포함.
"""
from __future__ import annotations

import json

import pytest

from src.doc_fill import (
    _parse_json_object,
    extract_unfilled_fields,
    match_turn_to_fields,
    run_turn_fill,
)
from src.persistence import get_report_runs_repo, get_reports_repo
from src.persistence.reports_repo import ReportMeta

_DOC = """# 연구계획심의 의뢰서 (초안)
[AI 생성 초안 — 제출 전 연구책임자/담당자 검토 필수]

## 개요
CNUHHIRB 서식 11 기준 초안.

1. 연구과제명: AI 심전도 분석 SW 탐색 임상
2. 연구책임자: [확인 필요: 연구책임자]
3. 연구 기간: [확인 필요: 연구 기간]
4. 목표 대상자 수: [확인 필요: 목표 대상자 수]

## 미확인 항목
- [확인 필요: 연구책임자]
- [확인 필요: 연구 기간]
"""


def test_extract_unfilled_dedupe_order():
    fields = extract_unfilled_fields(_DOC)
    assert fields == ["연구책임자", "연구 기간", "목표 대상자 수"]
    assert extract_unfilled_fields("빈칸 없음") == []


def test_apply_filled_values_partial():
    from src.doc_fill import apply_filled_values
    out = apply_filled_values(_DOC, {"연구 기간": "2026.10~2027.09"})
    assert "연구 기간: 2026.10~2027.09" in out
    assert "[확인 필요: 연구 기간]" not in out
    assert "[확인 필요: 연구책임자]" in out  # 미기입 마커 유지
    assert apply_filled_values(_DOC, {}) == _DOC


def test_parse_json_object_defensive():
    assert _parse_json_object('{"a": "1"}') == {"a": "1"}
    assert _parse_json_object('설명 텍스트 {"a": "1"} 꼬리') == {"a": "1"}
    assert _parse_json_object("JSON 아님") == {}
    assert _parse_json_object('["배열"]') == {}
    assert _parse_json_object('{"빈값": "", "숫자": 200}') == {"숫자": "200"}


class _FakeModel:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    async def ainvoke(self, prompt, cfg=None):
        self.calls += 1

        class _R:
            content = self.reply
        return _R()


@pytest.mark.asyncio
async def test_match_rejects_invented_keys():
    m = _FakeModel(json.dumps(
        {"연구 기간": "2026.10~2027.09", "모델이지어낸항목": "값"},
        ensure_ascii=False))
    out = await match_turn_to_fields("기간은 10월부터 1년", ["연구 기간"], model=m)
    assert out == {"연구 기간": "2026.10~2027.09"}


@pytest.mark.asyncio
async def test_match_skips_empty_inputs():
    m = _FakeModel("{}")
    assert await match_turn_to_fields("", ["a"], model=m) == {}
    assert await match_turn_to_fields("텍스트", [], model=m) == {}
    assert m.calls == 0  # LLM 미호출


def _seed_draft(tmp_path, thread_id="t_doc", body=_DOC):
    """완료된 document_draft run + report + 로컬 blob 세팅."""
    import os
    blob_dir = tmp_path / "blobs"
    os.environ["BLOB_LOCAL_DIR"] = str(blob_dir)
    from src.persistence import get_blob_store
    get_blob_store.cache_clear()  # lru_cache — env 반영
    uri = get_blob_store().put(f"{thread_id}/rep-doc.md", body)
    get_reports_repo().create(ReportMeta(
        id="rep-doc", thread_id=thread_id, mode="deep", kind="final",
        status="done", blob_uri=uri, title="의뢰서 초안"))
    runs = get_report_runs_repo()
    ok, _ = runs.acquire(idempotency_key="rpt_doc", thread_id=thread_id,
                         user_id="u-1", prompt="서류", purpose="document_draft")
    assert ok
    runs.finish("rpt_doc", status="completed", report_id="rep-doc")


@pytest.mark.asyncio
async def test_run_turn_fill_end_to_end(tmp_path, monkeypatch):
    _seed_draft(tmp_path)
    monkeypatch.setattr(
        "src.doc_fill._fill_model",
        lambda: _FakeModel(json.dumps(
            {"연구 기간": "2026.10~2027.09", "목표 대상자 수": "200명"},
            ensure_ascii=False)))
    events = []
    await run_turn_fill("t_doc", "기간은 10월부터 1년, 대상자 200명", events.append)
    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "document_update"
    assert ev["report_id"] == "rep-doc"
    assert {f["field"] for f in ev["filled"]} == {"연구 기간", "목표 대상자 수"}
    assert ev["remaining"] == ["연구책임자"]
    # 영속 확인 + 재실행 시 이미 채운 항목은 대조 대상에서 빠짐
    meta = get_reports_repo().get("rep-doc")
    assert "연구 기간" in json.loads(meta.filled_values)


@pytest.mark.asyncio
async def test_run_turn_fill_gate_without_draft(monkeypatch):
    """초안 없는 스레드 — LLM 미호출·emit 없음(비용 0 게이트)."""
    called = {"n": 0}

    def _boom():
        called["n"] += 1
        raise AssertionError("초안 없는데 모델 생성됨")

    monkeypatch.setattr("src.doc_fill._fill_model", _boom)
    events = []
    await run_turn_fill("t_no_draft", "아무 발화", events.append)
    assert events == [] and called["n"] == 0


def test_merge_filled_values_repo_roundtrip(tmp_path):
    _seed_draft(tmp_path, thread_id="t_doc2")
    repo = get_reports_repo()
    # 첫 병합
    merged = repo.merge_filled_values("rep-doc", {"a": "1"})
    assert merged == {"a": "1"}
    # 두 번째 병합 — 기존 유지 + 신규 추가, 빈 값 무시
    merged = repo.merge_filled_values("rep-doc", {"b": "2", "c": ""})
    assert merged == {"a": "1", "b": "2"}
    # 없는 report — 빈 dict, 예외 없음
    assert repo.merge_filled_values("no-such", {"x": "1"}) == {}


# ── 온프레미스 원문 처리 (2026-08-26) ───────────────────────────────

def test_onprem_flag_follows_base_url(monkeypatch):
    from src.doc_fill import onprem_fill
    monkeypatch.delenv("DOC_FILL_BASE_URL", raising=False)
    assert onprem_fill() is False
    monkeypatch.setenv("DOC_FILL_BASE_URL", "http://192.0.2.40:8080/v1")
    assert onprem_fill() is True
    monkeypatch.setenv("DOC_FILL_BASE_URL", "   ")   # 공백만 = 미설정
    assert onprem_fill() is False


@pytest.mark.asyncio
async def test_raw_text_only_when_onprem(tmp_path, monkeypatch):
    """**안전 불변식** — 상용 모델이면 원문이 절대 모델로 가지 않는다.

    서류 기입값은 성명·연락처 그 자체다. 온프레미스일 때만 원문을 쓰고,
    아니면 마스킹본으로 처리한다(그 대신 개인정보 칸은 안 채워진다).
    """
    _seed_draft(tmp_path, thread_id="t_onprem")
    seen: list[str] = []

    class _Spy:
        async def ainvoke(self, prompt, cfg=None):
            seen.append(prompt)

            class _R:
                content = "{}"
            return _R()

    monkeypatch.setattr("src.doc_fill._fill_model", lambda: _Spy())
    RAW = "연구책임자는 홍길동입니다"
    MASKED = "연구책임자는 [이름]입니다"

    # ① 상용(기본) — 마스킹본만 전달
    monkeypatch.delenv("DOC_FILL_BASE_URL", raising=False)
    await run_turn_fill("t_onprem", MASKED, lambda e: None, raw_text=RAW)
    assert seen and "홍길동" not in seen[-1], "상용 모델에 원문이 샜다"
    assert "[이름]" in seen[-1]

    # ② 온프레미스 — 원문 전달(그래야 성명 칸이 채워진다)
    monkeypatch.setenv("DOC_FILL_BASE_URL", "http://onprem/v1")
    await run_turn_fill("t_onprem", MASKED, lambda e: None, raw_text=RAW)
    assert "홍길동" in seen[-1]


def test_local_model_detect_skips_abliterated(monkeypatch):
    """가드레일 제거(abliterated) 변형은 자동 선택하지 않는다."""
    import src.doc_fill as df

    class _R:
        @staticmethod
        def json():
            return {"data": [{"id": "PocketAiHub/Qwen3.8-27B-Abliterated-MLX"},
                             {"id": "mlx-community/Qwen3.8-27B-4bit"}]}

    monkeypatch.setattr("httpx.get", lambda *a, **k: _R())
    assert df._detect_local_model("http://x/v1") == "mlx-community/Qwen3.8-27B-4bit"


def test_chat_loop_doc_fill_call_uses_valid_names():
    """호출부 변수명 회귀 방지 (2026-08-26).

    `run_turn_fill(thread_id, scrubbed, emit, raw_text=text)` 처럼 없는 이름을
    쓰면 NameError 가 나는데, 호출부가 예외를 삼켜 **전 사용자 기입이 조용히
    멈춘다**(실측). 함수 스코프에 실제로 있는 이름만 쓰는지 AST 로 확인한다.
    """
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("src/chat_loop.py").read_text(encoding="utf-8"))
    target = next(n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name == "_run_turn")
    # 스코프에 바인딩되는 이름 — 인자 + 대입 + with/for 바인딩
    bound = {a.arg for a in target.args.args + target.args.kwonlyargs}
    for node in ast.walk(target):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
    calls = [n for n in ast.walk(target)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "run_turn_fill"]
    assert calls, "chat_loop 에서 run_turn_fill 호출이 사라졌다"
    for c in calls:
        names = [a.id for a in c.args if isinstance(a, ast.Name)]
        names += [k.value.id for k in c.keywords if isinstance(k.value, ast.Name)]
        for n in names:
            assert n in bound, f"run_turn_fill 인자 '{n}' 이 스코프에 없다"


@pytest.mark.asyncio
async def test_onprem_failure_falls_back_to_masked(tmp_path, monkeypatch):
    """온프레미스 장애 시 전면 중단이 아니라 마스킹본 폴백 (2026-08-26).

    빌려 쓰는 장비라 언제든 죽을 수 있다 — 그때 개인정보 칸만 못 채우고
    나머지는 계속 채워져야 한다. **폴백 경로에도 원문은 가지 않는다.**
    """
    _seed_draft(tmp_path, thread_id="t_fb")
    # 기존 기입값(=개인정보)을 하나 넣어 둔다 — 폴백 프롬프트에 실리면 유출.
    get_reports_repo().merge_filled_values("rep-doc", {"연구책임자": "김철수"})
    monkeypatch.setenv("DOC_FILL_BASE_URL", "http://dead-host/v1")
    seen: list[str] = []

    class _Dead:
        async def ainvoke(self, prompt, cfg=None):
            seen.append(("onprem", prompt))
            raise RuntimeError("connection refused")

    class _Fallback:
        async def ainvoke(self, prompt, cfg=None):
            seen.append(("fallback", prompt))

            class _R:
                content = json.dumps({"연구 기간": "2026.10~2027.09"},
                                     ensure_ascii=False)
            return _R()

    monkeypatch.setattr("src.doc_fill._fill_model", lambda: _Dead())
    monkeypatch.setattr("src.models.build_chat_model",
                        lambda *a, **k: _Fallback())
    events = []
    await run_turn_fill("t_fb", "기간은 [이름]과 무관하게 10월부터 1년",
                        events.append, raw_text="기간은 홍길동과 무관하게 10월부터 1년")

    kinds = [k for k, _ in seen]
    assert kinds == ["onprem", "fallback"], kinds
    assert "홍길동" in seen[0][1]                    # 온프레미스엔 원문
    assert "홍길동" not in seen[1][1], "폴백(상용)에 원문이 샜다"
    # ★ 기존 기입값도 상용 폴백 프롬프트에 실리면 안 된다(정정은 온프레미스
    #   전용). 2026-08-27 정정 기능 추가 때 실제로 샜던 자리 — 회귀 고정.
    assert "김철수" not in seen[1][1], "폴백(상용)에 기입값이 샜다"
    assert events and events[0]["type"] == "document_update"   # 기입은 계속됨


# ── 두 입력 경로(직접 입력 ↔ 채팅)의 상호연동 (2026-08-27) ──────────────
#
# 실사용 요구: "UX가 중요해 상호연동이 잘 되어야 함". 같은 화면에 입력 경로가
# 둘인데 서로를 모르면 (a) 직접 넣은 값을 대화로 못 고치고 (b) 대화가 이미 채운
# 칸을 또 묻는다. 아래는 그 접점의 회귀.


@pytest.mark.asyncio
async def test_correction_only_when_explicit():
    """이미 채워진 항목도 대조 대상 — 단, 값이 같으면 정정이 아니다.

    같은 값을 되풀이 출력하면 화면에 "1개 수정됨"이 헛되이 뜬다.
    """
    prior = {"명칭(상호)": "(주)메디텍"}
    m = _FakeModel(json.dumps({"명칭(상호)": "(주)메디바이오"}, ensure_ascii=False))
    out = await match_turn_to_fields(
        "아니 상호는 (주)메디바이오야", [], model=m, filled=prior)
    assert out == {"명칭(상호)": "(주)메디바이오"}

    same = _FakeModel(json.dumps({"명칭(상호)": "(주)메디텍"}, ensure_ascii=False))
    assert await match_turn_to_fields(
        "메디텍 건으로 문의드려요", [], model=same, filled=prior) == {}


@pytest.mark.asyncio
async def test_correction_reaches_the_panel(tmp_path, monkeypatch):
    """직접 입력으로 채운 값을 대화로 고치면 document_update 가 그걸 알린다.

    `corrected` 가 비면 FE 는 "새로 채움"으로 표시하고, 사용자는 자기 값이
    바뀐 걸 모른 채 제출한다.
    """
    _seed_draft(tmp_path)
    get_reports_repo().merge_filled_values("rep-doc", {"연구책임자": "김철수"})
    # 정정은 온프레미스 전용(기입값을 프롬프트에 싣는 유일한 경로).
    monkeypatch.setenv("DOC_FILL_BASE_URL", "http://onprem/v1")
    monkeypatch.setattr(
        "src.doc_fill._fill_model",
        lambda: _FakeModel(json.dumps({"연구책임자": "이영희"}, ensure_ascii=False)))
    events = []
    await run_turn_fill("t_doc", "연구책임자는 이영희로 바꿔주세요", events.append,
                        raw_text="연구책임자는 이영희로 바꿔주세요")
    assert len(events) == 1
    assert events[0]["corrected"] == ["연구책임자"]
    assert json.loads(
        get_reports_repo().get("rep-doc").filled_values)["연구책임자"] == "이영희"


@pytest.mark.asyncio
async def test_all_filled_still_accepts_correction(tmp_path, monkeypatch):
    """미기입이 0이어도 대조를 돈다 — 다 채운 뒤 고치는 순간이 정확히 여기다."""
    _seed_draft(tmp_path)
    get_reports_repo().merge_filled_values("rep-doc", {
        "연구책임자": "김철수", "연구 기간": "2026", "목표 대상자 수": "10명"})
    monkeypatch.setenv("DOC_FILL_BASE_URL", "http://onprem/v1")
    monkeypatch.setattr(
        "src.doc_fill._fill_model",
        lambda: _FakeModel(json.dumps({"목표 대상자 수": "200명"}, ensure_ascii=False)))
    events = []
    await run_turn_fill("t_doc", "대상자 수는 200명으로 정정합니다", events.append,
                        raw_text="대상자 수는 200명으로 정정합니다")
    assert len(events) == 1
    assert events[0]["corrected"] == ["목표 대상자 수"]


def test_chat_is_told_what_remains(tmp_path):
    """대화 모델이 남은 항목을 안다 — 모르면 물어봐 주지도, 안 묻지도 못한다.

    값 자체는 절대 싣지 않는다(개인정보는 온프레미스 기입 모델만 본다).
    """
    from src.doc_fill import draft_context_note

    _seed_draft(tmp_path)
    get_reports_repo().merge_filled_values("rep-doc", {"연구책임자": "김철수"})
    note = draft_context_note("t_doc")
    assert note is not None
    assert "1/3" in note
    assert "연구 기간" in note          # 남은 항목은 이름으로 알린다
    assert "연구책임자" not in note      # 이미 채운 항목은 다시 묻지 않게
    assert "김철수" not in note          # ★ 값은 대화 모델에 안 간다

    assert draft_context_note("t_없는스레드") is None


# ── 독립 레인 정책 (2026-08-27) — 상용 모델은 개인정보를 보지 않는다 ─────


@pytest.mark.asyncio
async def test_commercial_default_path_never_gets_filled_values(
        tmp_path, monkeypatch):
    """온프레미스 미설정(상용 기본 경로) — 기존 기입값이 프롬프트에 안 실린다.

    기입값은 성명·연락처 그 자체다. 정정 기능은 온프레미스 전용이고,
    상용 경로는 미기입 항목명만 본다.
    """
    _seed_draft(tmp_path, thread_id="t_comm")
    get_reports_repo().merge_filled_values("rep-doc", {"연구책임자": "김철수"})
    monkeypatch.delenv("DOC_FILL_BASE_URL", raising=False)
    seen: list[str] = []

    class _Spy:
        async def ainvoke(self, prompt, cfg=None):
            seen.append(prompt)

            class _R:
                content = "{}"
            return _R()

    monkeypatch.setattr("src.doc_fill._fill_model", lambda: _Spy())
    await run_turn_fill("t_comm", "[이름] 관련 문의입니다", lambda e: None,
                        raw_text="김철수 관련 문의입니다")
    assert seen, "상용 경로가 아예 안 돌았다"
    assert "김철수" not in seen[-1], "상용 프롬프트에 기입값이 샜다"


@pytest.mark.asyncio
async def test_sparkle_hint_scrubbed_on_commercial(monkeypatch):
    """✨ 힌트는 사용자가 그대로 친 텍스트 — 상용이면 스크럽, 온프레미스면 원문.

    /documents/{id}/fill 은 채팅 입구 게이트를 안 지나는 우회로였다.
    """
    from src.doc_fill import generate_field_value

    seen: list[str] = []

    class _Spy:
        async def ainvoke(self, prompt, cfg=None):
            seen.append(prompt)

            class _R:
                content = "값"
            return _R()

    monkeypatch.setattr("src.doc_fill._fill_model", lambda: _Spy())
    monkeypatch.setattr("src.guardrail.gate.scrub_input",
                        lambda t, collect=None: (t.replace("홍길동", "[이름]"), []))

    # ① 상용 — 힌트가 마스킹돼 나간다
    monkeypatch.delenv("DOC_FILL_BASE_URL", raising=False)
    await generate_field_value("본문", "성명", hint="성명은 홍길동")
    assert "홍길동" not in seen[-1] and "[이름]" in seen[-1]

    # ② 온프레미스 — 원문 그대로(그래야 그 칸을 채운다)
    monkeypatch.setenv("DOC_FILL_BASE_URL", "http://onprem/v1")
    await generate_field_value("본문", "성명", hint="성명은 홍길동")
    assert "홍길동" in seen[-1]

    # ③ 스크럽 실패 — 힌트를 버리고 진행(안 보내는 쪽이 안전)
    monkeypatch.delenv("DOC_FILL_BASE_URL", raising=False)

    def _boom(t, collect=None):
        raise RuntimeError("scan failed")

    monkeypatch.setattr("src.guardrail.gate.scrub_input", _boom)
    await generate_field_value("본문", "성명", hint="성명은 홍길동")
    assert "홍길동" not in seen[-1]


@pytest.mark.asyncio
async def test_label_mapping_llm_skipped_without_onprem(monkeypatch):
    """원본 서식 라벨 매핑 — 프롬프트에 기입값(개인정보)이 실리므로
    온프레미스가 아니면 LLM 보강을 생략한다(휴리스틱만)."""
    from src.form_fill import map_values_to_labels

    called = {"n": 0}

    class _Spy:
        async def ainvoke(self, prompt, cfg=None):
            called["n"] += 1

            class _R:
                content = "{}"
            return _R()

    monkeypatch.setattr("src.doc_fill._fill_model", lambda: _Spy())
    monkeypatch.delenv("DOC_FILL_BASE_URL", raising=False)
    out = await map_values_to_labels(
        ["성명", "이상한라벨"], {"성명": "홍길동"})
    assert called["n"] == 0, "상용 환경에서 기입값이 LLM 으로 갔다"
    assert out == {"성명": "홍길동"}  # 휴리스틱(정규화 동등)은 동작

    monkeypatch.setenv("DOC_FILL_BASE_URL", "http://onprem/v1")
    await map_values_to_labels(["매칭안되는라벨"], {"항목": "값"})
    assert called["n"] == 1  # 온프레미스면 LLM 보강 동작


# ── 작성 도우미 챗 (전용 모달, 2026-08-27) ─────────────────────────────


@pytest.mark.asyncio
async def test_assistant_turn_extracts_and_replies():
    from src.doc_fill import assistant_turn

    m = _FakeModel(json.dumps({
        "values": {"성명(한글)": "홍길동"},
        "reply": "성명을 채웠습니다. 소재지를 알려주세요."}, ensure_ascii=False))
    reply, values = await assistant_turn(
        "허가신청서", ["성명(한글)", "소재지"], {}, "대표자는 홍길동입니다",
        model=m)
    assert values == {"성명(한글)": "홍길동"}
    assert "소재지" in reply


@pytest.mark.asyncio
async def test_assistant_turn_never_silent_on_garbage():
    """모델이 깨진 출력을 내도 도우미는 침묵하지 않는다 — 결정적 안내."""
    from src.doc_fill import assistant_turn

    reply, values = await assistant_turn(
        "허가신청서", ["소재지"], {"성명": "홍길동"}, "뭘 입력해야 해?",
        model=_FakeModel("JSON 아님"))
    assert values == {}
    assert "소재지" in reply  # 남은 항목을 구체적으로 안내


def test_assist_route_requires_onprem(tmp_path, monkeypatch):
    """도우미 창구는 온프레미스 전용 — 원문 개인정보가 들어오는 자리라
    상용 모델로는 절대 안 돌린다(503)."""
    from fastapi.testclient import TestClient
    from src.api import app

    _seed_draft(tmp_path, thread_id="t_assist")
    monkeypatch.delenv("DOC_FILL_BASE_URL", raising=False)
    c = TestClient(app)
    r = c.post("/documents/rep-doc/chat", json={"message": "성명은 홍길동"})
    assert r.status_code == 503
    assert "직접 입력" in r.json()["detail"]


@pytest.mark.asyncio
async def test_assistant_turn_includes_attachment():
    """첨부 문서 텍스트가 프롬프트에 실려 추출 대상이 된다(온프레미스 전용 창구)."""
    from src.doc_fill import assistant_turn

    seen = {}

    class _M:
        async def ainvoke(self, prompt, cfg=None):
            seen["p"] = prompt

            class _R:
                content = '{"values": {"명칭(상호)": "(주)메디텍"}, "reply": "채웠어요"}'
            return _R()

    reply, values = await assistant_turn(
        "허가신청서", ["명칭(상호)"], {}, "첨부에서 추출해줘",
        model=_M(), attachment_text="사업자등록증\n상호: (주)메디텍")
    assert "첨부 문서" in seen["p"] and "(주)메디텍" in seen["p"]
    assert values == {"명칭(상호)": "(주)메디텍"}
