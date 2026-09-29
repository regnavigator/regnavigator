"""스킬 번들(src/skills/) — 로더·스위치·매니페스트 무결성.

게이트 1(매니페스트 최신성)은 번들 README 의 CI 계약 이식: SKILL.md 만 고치고
manifest.json 을 안 돌린 커밋을 잡는다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.skills import chat_integration as ci
from src.skills.loader import SkillLoader

BUNDLE = Path(__file__).resolve().parents[1] / "src" / "skills" / "medireg_irb_drb"


@pytest.fixture()
def loader() -> SkillLoader:
    return SkillLoader(BUNDLE, BUNDLE / "manifest.json")


# ── 게이트 1: 매니페스트 최신성 ─────────────────────────────────────────
def test_manifest_up_to_date():
    from scripts.build_skill_manifest import build

    committed = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    rebuilt = build(BUNDLE)
    assert rebuilt["version"] == committed["version"], (
        "SKILL.md/references 가 바뀌었는데 manifest.json 미갱신 — "
        "`python scripts/build_skill_manifest.py` 실행 후 함께 커밋"
    )


def test_manifest_files_exist(loader):
    for s in loader.manifest["skills"]:
        assert (BUNDLE / s["dir"] / "SKILL.md").is_file()
        for r in s["references"]:
            assert (BUNDLE / s["dir"] / r).is_file(), f"{s['name']}/{r} 없음"


# ── 로더 ────────────────────────────────────────────────────────────────
def test_load_skill_and_dedup(loader):
    body = loader.load_skill("irb-triage")
    assert "IRB 심의 판정" in body
    again = loader.load_skill("irb-triage")
    assert "이미 로드됨" in again  # 세션 내 중복 억제


def test_unknown_skill_is_error_not_exception(loader):
    content, is_error = loader.dispatch("load_skill", {"name": "no-such"})
    assert is_error and "사용 가능" in content


def test_path_traversal_blocked(loader):
    content, is_error = loader.dispatch(
        "read_skill_reference", {"skill": "drb-triage", "path": "../../etc/passwd"})
    assert is_error  # manifest 등록 목록 대조에서 차단


def test_seed_suppresses_reload(loader):
    loader.seed(["irb-triage/SKILL.md"])
    assert "이미 로드됨" in loader.load_skill("irb-triage")


def test_tool_defs_openai_format(loader):
    defs = loader.tool_defs()
    assert [d["function"]["name"] for d in defs] == [
        "load_skill", "read_skill_reference"]
    for d in defs:
        assert d["type"] == "function" and "parameters" in d["function"]
    enum = defs[0]["function"]["parameters"]["properties"]["name"]["enum"]
    assert set(enum) == set(loader.skill_names)


# ── 스위치 ──────────────────────────────────────────────────────────────
def test_off_when_env_unset(monkeypatch):
    monkeypatch.delenv("SKILL_BUNDLE_DIR", raising=False)
    attach, force = ci.resolve_turn_skill(
        "u@x.com", [], None, "차트리뷰인데 IRB 받아야 하나요?")
    assert (attach, force) == (False, False)  # env 없음 = 기능 자체 없음


def test_pregate_positive_negative(monkeypatch):
    monkeypatch.setenv("SKILL_BUNDLE_DIR", str(BUNDLE))
    monkeypatch.delenv("SKILL_WHITELIST_EMAILS", raising=False)
    attach, force = ci.resolve_turn_skill(
        None, [], None, "후향적 차트리뷰인데 IRB 받아야 하나요?")
    assert (attach, force) == (True, True)
    attach, force = ci.resolve_turn_skill(
        None, [], None, "의료기기 광고 사전심의 대상인가요?")
    assert (attach, force) == (False, False)  # 비 IRB/DRB — 완전 무개입


def test_sticky_from_history_without_keyword(monkeypatch):
    monkeypatch.setenv("SKILL_BUNDLE_DIR", str(BUNDLE))
    monkeypatch.delenv("SKILL_WHITELIST_EMAILS", raising=False)

    class _Ai:
        tool_calls = [{"name": "load_skill", "args": {"name": "irb-triage"}}]

    attach, force = ci.resolve_turn_skill(
        None, [_Ai()], None, "네, 후향적이고 동의는 안 받았어요")
    assert attach is True   # 스티키 — 문진 후속 턴 유지
    assert force is False   # 부착 ≠ 강제 (히스토리의 지침이 이끈다)


def test_hint_forces_without_keyword(monkeypatch):
    """IRB/DRB 버튼(skill_hint) — 키워드 없는 질의도 부착·강제 (이중 접근)."""
    monkeypatch.setenv("SKILL_BUNDLE_DIR", str(BUNDLE))
    monkeypatch.delenv("SKILL_WHITELIST_EMAILS", raising=False)
    attach, force = ci.resolve_turn_skill(
        None, [], None, "우리 연구 심사 받아야 하는지 봐주세요", hint=True)
    assert (attach, force) == (True, True)
    # 힌트가 있어도 화이트리스트 게이트는 우회하지 않는다.
    monkeypatch.setenv("SKILL_WHITELIST_EMAILS", "@cnuhh.com")
    attach, force = ci.resolve_turn_skill(
        "someone@else.com", [], None, "심사 봐주세요", hint=True)
    assert (attach, force) == (False, False)


def test_catalog_block_institution_and_no_leak_rules(monkeypatch, loader):
    """전체 노출 규칙 — 기관(화순전남대병원) 명시 + 원문 재배포 금지 문구."""
    block = ci.catalog_block(loader)
    assert "화순전남대학교병원" in block
    assert "재배포" in block and "원본 파일 제공" in block


def test_whitelist(monkeypatch):
    monkeypatch.setenv("SKILL_WHITELIST_EMAILS", "@cnuhh.com, ra@corp.kr")
    assert ci.user_allowed("kim@cnuhh.com")
    assert ci.user_allowed("ra@corp.kr")
    assert not ci.user_allowed("someone@else.com")
    assert not ci.user_allowed(None)
    monkeypatch.delenv("SKILL_WHITELIST_EMAILS", raising=False)
    assert ci.user_allowed("anyone@x.com")  # 미설정=전면 허용


# ── 판정 로그 ───────────────────────────────────────────────────────────
_BODY = (
    "결론: 심의면제 대상으로 보입니다.\n\n<verdict>\n```json\n"
    '{"irb": {"verdict": "EXEMPT", "trace": [], "cited_loci": []}}\n'
    "```\n</verdict>"
)


def test_find_and_strip_verdict():
    v = ci.find_verdict(_BODY)
    assert v and v["irb"]["verdict"] == "EXEMPT"
    stripped = ci.strip_verdict_marker(_BODY)
    assert "<verdict>" not in stripped and "결론" in stripped


def test_find_verdict_fallback_bare_json_block():
    body = '판정합니다.\n```json\n{"drb": {"verdict": "HOLD"}}\n```'
    v = ci.find_verdict(body)
    assert v and v["drb"]["verdict"] == "HOLD"


def test_no_verdict_in_normal_answer():
    assert ci.find_verdict("일반 규제 답변입니다. [1]") is None


# ── 도구 실행(step 발행) ────────────────────────────────────────────────
def test_exec_tool_emits_steps(loader):
    r = ci.exec_tool(loader, "load_skill", {"name": "irb-triage"}, {}, "tc_x")
    assert r.clarify is None
    assert "IRB 심의 판정" in r.tool_message.content
    statuses = [s.get("status") for s in r.steps]
    assert statuses == ["running", "done"]
    assert r.steps[0]["tool_name"] == "load_skill"
    assert "내부 지침 확인" in r.steps[0]["label"]


def test_exec_tool_error_step(loader):
    r = ci.exec_tool(loader, "load_skill", {"name": "nope"}, {}, "tc_x")
    assert r.steps[-1]["status"] == "error"
    assert "사용 가능" in r.tool_message.content  # 모델 복구용 안내


# ── 참조 자동 로드(2026-09-02) — 소요기간 오답 운영 사고 회귀 ─────────────
def test_load_skill_auto_attaches_matching_reference(loader):
    """질문에 '소요기간' 단서 → load_skill 응답에 timeline.md 가 동봉된다.

    모델(특히 로컬 27B)이 read_skill_reference 를 재량으로 호출하지 않아
    지침에 있는 답을 '확인 못함'으로 부정한 사고(t_6951632f) 재발 방지.
    """
    from src.skills import chat_integration as ci

    res = ci.exec_tool(loader, "load_skill", {"name": "irb-procedure"},
                       {"skill_user_text": "심의 소요기간 얼마나 걸려?"}, "tc1")
    c = res.tool_message.content
    assert "자동 첨부" in c and "timeline" in c
    assert any("timeline.md" in str(s.get("label")) for s in res.steps
               if s.get("label"))


def test_load_skill_no_auto_ref_without_cue(loader):
    from src.skills import chat_integration as ci

    res = ci.exec_tool(loader, "load_skill", {"name": "irb-procedure"},
                       {"skill_user_text": "IRB 가 뭐예요?"}, "tc2")
    assert "자동 첨부" not in res.tool_message.content


# ── 광의(soft) 게이트 — 심의 가능성 고지 (2026-09-10) ────────────────────
# 배경: 엄격 게이트는 사용자가 'IRB·심의·차트리뷰'를 직접 써야 걸린다. 운영 실측
# (2026-09-10)에서 "환자 100명 처방데이터로 연구 기획 중"이 안 잡혀, 뉴스레터가
# 약속한 "무심코 던진 질문에서도 놓치지 않는다"가 지켜지지 않았다. 엄격 게이트를
# 넓히는 대신(부착 비용 = 온프레미스 60s+·웹 제외) 고지 전용 게이트를 뒀다.
def test_soft_gate_catches_research_without_review_keywords():
    from src.skills.chat_integration import is_review_adjacent, is_skill_query

    t = "생성형 AI로 퇴원약 안내문을 만드는 연구를 기획 중입니다. 환자 100명 처방데이터를 쓰려고 해요."
    assert is_skill_query(t) is False, "엄격 게이트엔 안 걸리는 게 전제"
    assert is_review_adjacent(t) is True


def test_soft_gate_defers_to_strict_gate():
    """엄격 게이트가 걸린 턴은 이미 판정을 하므로 고지를 중복하지 않는다."""
    from src.skills.chat_integration import is_review_adjacent

    for t in ("IRB 심의 대상인가요?", "심의면제 기준 알려줘", "차트리뷰 연구인데요"):
        assert is_review_adjacent(t) is False, t


def test_soft_gate_ignores_non_research_and_general_regulatory():
    """오탐 비용은 작지만, 무관한 질의까지 번지면 안 된다."""
    from src.skills.chat_integration import is_review_adjacent

    for t in ("의료기기 품목허가 절차 알려줘",
              "진료기록 사본 발급 어떻게 받나요?",   # 연구 맥락 없음
              "임상시험 IND 승인 절차",
              "의료광고 사전심의 대상인가요?"):
        assert is_review_adjacent(t) is False, t


def test_review_nudge_states_possibility_not_verdict():
    """고지는 '가능성'이어야 한다 — 단정하면 예비판단 고지 정책과 충돌."""
    from src.skills.chat_integration import REVIEW_NUDGE

    assert "일 수 있" in REVIEW_NUDGE and "단정하지" in REVIEW_NUDGE
    assert "next_steps" in REVIEW_NUDGE


# ── 면제 오판 가드 (2026-09-15, t_95386a) ─────────────────────────────────
# 배경: 후향적 의무기록 연구(의무기록번호 대응표 보관)를 로컬 27B 가 EXEMPT 로
# 판정. 전남대 사용자 피드백 = 사무국 정답은 신속심의. used_slots 에
# interaction_type=identifiable_info 와 collects_identifiable_info=false 가 동시에
# 있었다(9/10 관리자 테스트도 동일). 이 모순은 코드가 잡는다.
_T95386A_VERDICT = {
    "rulepack_version": "cnuhh-irb-2026.03",
    "irb": {"verdict": "EXEMPT", "trace": [], "cited_loci": ["IRB SOP 5-가(2)㈎"],
            "unknowns": []},
    "used_slots": {
        "is_research": True, "subject_human": True, "subject_biospecimen": False,
        "interaction_type": "identifiable_info", "regulated_trial": "none",
        "minimal_risk_to_public": True, "is_public_data": False,
        "collects_identifiable_info": False, "uses_existing_records": True,
        "vulnerable_subjects": False,
    },
}


def test_guard_downgrades_exempt_with_identifiable_contradiction():
    from src.skills import chat_integration as ci

    out, note = ci.guard_verdict(_T95386A_VERDICT)
    assert out["irb"]["verdict"] == "HOLD"
    assert out["guard"] == {"rule": "exempt_identifiable_contradiction",
                            "original_verdict": "EXEMPT"}
    assert any("대응표" in u for u in out["irb"]["unknowns"])
    assert note and "신속심의" in note
    # 순수 함수 — 원본 불변
    assert _T95386A_VERDICT["irb"]["verdict"] == "EXEMPT"


def test_guard_triggers_on_existing_records_alone():
    """interaction_type 이 없어도 기존 자료 이용 + 식별정보 미수집이면 잡는다."""
    import copy

    from src.skills import chat_integration as ci

    v = copy.deepcopy(_T95386A_VERDICT)
    v["used_slots"].pop("interaction_type")
    v["used_slots"]["collects_identifiable_info"] = "false"  # 문자열도 허용
    out, note = ci.guard_verdict(v)
    assert out["irb"]["verdict"] == "HOLD" and note


def test_guard_passes_when_no_linking_key_confirmed():
    """사용자 확인으로 has_linking_key=false 가 명시되면 EXEMPT 통과."""
    import copy

    from src.skills import chat_integration as ci

    v = copy.deepcopy(_T95386A_VERDICT)
    v["used_slots"]["has_linking_key"] = False
    out, note = ci.guard_verdict(v)
    assert out["irb"]["verdict"] == "EXEMPT" and note is None and "guard" not in out


def test_guard_leaves_other_verdicts_and_shapes_alone():
    import copy

    from src.skills import chat_integration as ci

    v = copy.deepcopy(_T95386A_VERDICT)
    v["irb"]["verdict"] = "EXPEDITED"
    assert ci.guard_verdict(v) == (v, None)
    # 공개 데이터 면제(H2) — 식별정보 미수집이지만 기존 의무기록 아님 → 통과
    v2 = copy.deepcopy(_T95386A_VERDICT)
    v2["used_slots"].update({"interaction_type": "none", "uses_existing_records": False,
                             "is_public_data": True})
    assert ci.guard_verdict(v2)[1] is None
    assert ci.guard_verdict(None) == (None, None)
    assert ci.guard_verdict({"drb": {"verdict": "EXEMPT"}})[1] is None


def test_insert_guard_note_before_next_steps():
    from src.skills import chat_integration as ci

    body = "결론 본문\n\n<next_steps>\n[]\n</next_steps>\n"
    out = ci.insert_guard_note(body, "\n\nNOTE")
    assert out.index("NOTE") < out.index("<next_steps>")
    assert ci.insert_guard_note("본문", "\n\nNOTE").endswith("NOTE\n")
    assert ci.insert_guard_note("본문", "") == "본문"


def test_load_irb_triage_auto_attaches_both_decision_trees(loader):
    """심의대상·면제·후향 단서 → irb-exemption + irb-review-type 동봉.

    t_95386a: 모델이 review-type 을 안 읽어 STEP D 가 없는 채로 EXEMPT.
    """
    from src.skills import chat_integration as ci

    res = ci.exec_tool(loader, "load_skill", {"name": "irb-triage"},
                       {"skill_user_text": "첨부는 IRB 심의 요청한 연구계획서야. "
                                           "승인 가능할지 판단해줘"}, "tc3")
    c = res.tool_message.content
    assert "자동 첨부" in c
    assert "irb-exemption.md" in c and "irb-review-type.md" in c
    assert "STEP D3" in c  # review-type 원문이 실제로 들어갔다


def test_bundle_h3_mentions_linking_key(loader):
    """번들 결정트리 H3 에 대응표(연결키) 규칙이 있고 슬롯이 등록돼 있다."""
    ex, err = loader.dispatch("read_skill_reference",
                              {"skill": "irb-triage", "path": "references/irb-exemption.md"})
    assert not err and "대응표" in ex and "has_linking_key" in ex
    sl, err = loader.dispatch("read_skill_reference",
                              {"skill": "irb-triage", "path": "references/slots.md"})
    assert not err and "has_linking_key" in sl


def test_replace_message_persists_guard_note(tmp_path):
    """가드 문구가 붙은 AI 메시지가 저장본에도 반영된다(새로고침·다음 턴 컨텍스트)."""
    from langchain_core.messages import AIMessage, HumanMessage

    from src import chat_loop
    from src.persistence.threads_repo import SqliteThreadsRepo

    repo = SqliteThreadsRepo(str(tmp_path / "t.db"))
    repo.ensure_thread("t_x")
    ai = AIMessage(content="결론 EXEMPT\n\n<verdict>\n```json\n{}\n```\n</verdict>\n"
                           "<next_steps>[]</next_steps>", id="m1")
    repo.append_messages("t_x", [HumanMessage(content="q", id="h1"), ai])
    ai2 = chat_loop._with_guard_note(ai, "\n\nGUARD")
    assert repo.replace_message("t_x", ai2) is True
    msgs = repo.get_state("t_x").messages
    assert [m.id for m in msgs] == ["h1", "m1"]  # seq 유지
    assert "GUARD" in msgs[-1].content
    assert msgs[-1].content.index("GUARD") < msgs[-1].content.index("<next_steps>")
    assert repo.replace_message("t_x", AIMessage(content="x", id="nope")) is False
    # 블록 리스트 content 도 문구가 붙는다
    blocks = chat_loop._with_guard_note(AIMessage(content=[{"type": "text", "text": "a"}], id="m2"), "N")
    assert blocks.content[-1] == {"type": "text", "text": "N"}
