"""규제 경로 분해 — <pathway> 마커 파싱·정제 (2026-10-01)."""

from __future__ import annotations

from src import pathway as pw

GOOD = """답변 본문입니다 [1].

<pathway>
[{"title":"위생교육 이수","what":"영업 전 위생교육을 받는다","where":"지정 교육기관",
  "form":null,"when":"영업신고 전","cites":[1]},
 {"title":"영업신고","what":"신고서를 제출한다","where":"관할 구청",
  "form":"별지 제37호서식","when":"영업 시작 전","cites":[1,2]}]
</pathway>
"""


def test_parse_extracts_steps_in_order():
    steps = pw.parse(GOOD)
    assert steps is not None and len(steps) == 2
    assert [s["no"] for s in steps] == [1, 2]
    assert steps[0]["title"] == "위생교육 이수"
    assert steps[1]["form"] == "별지 제37호서식"
    assert steps[1]["cites"] == [1, 2]


def test_strip_marker_removes_block():
    body = pw.strip_marker(GOOD)
    assert "<pathway>" not in body and "별지 제37호서식" not in body
    assert "답변 본문입니다 [1]." in body


def test_no_marker_returns_none():
    assert pw.parse("그냥 답변입니다.") is None
    assert pw.strip_marker("그냥 답변입니다.") == "그냥 답변입니다."


def test_broken_json_is_ignored():
    """파싱 실패로 답변을 잃지 않는다 — 경로가 없다고 답이 틀린 건 아니다."""
    assert pw.parse("본문 <pathway>[{not json</pathway>") is None


def test_accepts_wrapped_object_and_fence():
    """모델이 {"steps": …} 로 감싸거나 ```json 펜스를 붙여도 받는다."""
    body = '<pathway>```json\n{"steps":[{"title":"신고","what":"x"}]}\n```</pathway>'
    steps = pw.parse(body)
    assert steps and steps[0]["title"] == "신고"


def test_caps_step_count():
    items = ",".join(f'{{"title":"s{i}","what":"w"}}' for i in range(30))
    steps = pw.parse(f"<pathway>[{items}]</pathway>")
    assert steps is not None and len(steps) == pw.MAX_STEPS


def test_clips_long_fields():
    long = "가" * 900
    steps = pw.parse(f'<pathway>[{{"title":"{long}","what":"{long}"}}]</pathway>')
    assert steps is not None
    assert len(steps[0]["title"]) <= 80
    assert len(steps[0]["what"]) <= 300


def test_citation_numbers_are_sanitized():
    """문자열·대괄호·범위 밖 값이 섞여도 유효한 번호만 남는다."""
    steps = pw.parse('<pathway>[{"title":"t","what":"w","cites":["[3]",5,"x",0,9999,3]}]</pathway>')
    assert steps is not None
    assert steps[0]["cites"] == [3, 5]


def test_entry_without_title_or_what_is_dropped():
    steps = pw.parse('<pathway>[{"where":"구청"},{"title":"신고","what":"x"}]</pathway>')
    assert steps is not None and len(steps) == 1
    assert steps[0]["title"] == "신고"


def test_summary_has_no_body_text():
    """events 적재 요약에 본문·고객 정보가 섞이지 않는다."""
    steps = pw.parse(GOOD)
    assert steps is not None
    s = pw.summary(steps)
    assert s == {"steps": 2, "with_form": 1, "with_deadline": 2, "uncited": 0}
    assert all(isinstance(v, int) for v in s.values())
