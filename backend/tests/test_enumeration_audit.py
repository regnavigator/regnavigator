"""열거 커버리지 감사(2026-08-21) — t_1398cb 침묵 누락 재현 케이스 고정.

첨부 보도자료의 인라인 ▲ 열거(개행 없음)와 행머리 불릿 양쪽에서 항목을 뽑고,
답변이 안 다룬 항목을 잡아내는지 검증한다. 관측 전용 모듈 — 순수 함수만.
"""
from src.enumeration_audit import audit_enumeration, extract_enumerated_items

# t_1398cb 첨부의 실제 열거부 축약(인라인 ▲, 개행 없음)
_PRESS = (
    "예정이다.▲ 심혈관질환의 진단 및 치료를 위한 다중융합영상 AI 솔루션 개발"
    "▲ 다중모드 광영상 기반 지능형 디지털병리기기 개발"
    "▲ 뇌영상-임상 빅데이터 기반 인공지능 뇌경색 진료 소프트웨어-의료기기 개발"
    "▲ 환자 맞춤형 정밀수술을 위한 확장현실 기반 로봇 수술 내비게이션 플랫폼 개발"
    "▲ 병원의료정보시스템(EMR) 연동 의료용 스마트 배설케어시스템 및 서비스 모델 개발"
    "▲ 국산 착용형 보행재활 로봇의 CE 및 허가용 임상시험"
    "▲ 신규 유전자가위를 활용한 혈액 기반의 폐암 진단 원천기술 및 진단키트 개발"
    "▲ 복합재료 기반 고밀도 유연 신경전극 및 이를 탑재한 인공달팽이관 장치 개발 및 사업화"
    "▲ 스마트 헬스케어 시스템 구축을 위한 초소형 연속혈당측정기 개발"
    "▲ 원격 모니터링 이동형 혈액투석 의료기기 개발\n"
    "< 범부처 전주기 의료기기 연구개발사업 10대 대표과제 >"
)

# 당시 실답변 요지 — 배설케어만 미커버(병합 3건은 키워드가 본문에 있어 커버로 침)
_ANSWER = (
    "AI 기반 영상 진단 소프트웨어(심혈관 다중융합영상, 디지털병리, 뇌경색) — SaMD 허가. "
    "로봇 수술 내비게이션(확장현실) — 임상시험계획 승인. "
    "착용형 보행재활 로봇 — CE 인증 동등성, 수입 허가. "
    "유전자가위 기반 폐암 진단키트 — 체외진단 임상적 성능시험. "
    "신경전극·인공달팽이관 — 생체적합성, GMP. "
    "초소형 연속혈당측정기 — 디지털의료제품법 제조허가. "
    "원격 모니터링 혈액투석 기기 — 품목허가."
)


def test_extract_inline_press_release_items():
    items = extract_enumerated_items("여기 있는 발표주제별 규제 이슈 정리\n" + _PRESS)
    assert len(items) == 10
    assert any("배설케어" in it for it in items)


def test_missing_item_detected():
    res = audit_enumeration(_PRESS, _ANSWER)
    assert res is not None
    assert res["items"] == 10
    assert any("배설케어" in m for m in res["missing"])
    # 병합 서술된 AI 3종은 누락으로 세지 않는다
    assert not any("디지털병리" in m for m in res["missing"])


def test_line_bullets_and_numbers():
    q = "다음 정리해줘\n1. 의료기기 광고 사전심의 절차\n2. 임상시험 계획 승인 요건\n- 체외진단기기 성능시험 기준\n① 소프트웨어 밸리데이션 문서"
    items = extract_enumerated_items(q)
    assert len(items) == 4


def test_no_enumeration_returns_none():
    assert audit_enumeration("의료기기 2등급 인증 절차 알려줘", "…") is None
    # 항목 2개는 열거로 안 봄(최소 3)
    assert audit_enumeration("1. 허가 절차\n2. 수수료", "…") is None


def test_all_covered_no_missing():
    q = "정리: ▲ 의료기기 광고 심의 ▲ 체외진단 성능시험 ▲ 소프트웨어 밸리데이션"
    a = "광고 심의는 …[1], 체외진단 성능시험은 …[2], 소프트웨어 밸리데이션은 …[3]"
    res = audit_enumeration(q, a)
    assert res is not None and res["missing"] == []
