# 무인용 사실 검증 확장 — 설계 (v0)

> 상태: 설계 초안 · 2026-07-22 · 대상: `chat_loop` + `grounding` + `eval`
> 목적: 환각 감축의 **본체** — 인용 없이 단정된 사실(조문번호·수수료·기한·날짜·판례)을
> 검증 범위로 끌어온다. 지금 grounding 은 **인용된 `[n]` 만** 보므로 무인용 사실은 무방비.

## 1. 문제 정의

현 방어는 두 곳에 집중:
- grounding: **인용된** claim ↔ source 원문 대조.
- contact guard: URL·전화(정규식).

→ **무인용 정량·특정 사실**이 통째로 빠진다: 틀린 조문번호(`제25조`인데 `제19조`),
지어낸 수수료·기한·날짜, 없는 판례. 이게 환각 표면의 대부분.

## 2. 설계 원칙 (앞선 결정에서 계승)

| 원칙 | 근거 |
|---|---|
| **자기모순 경고 금지** | "지가 답하고 지가 경고"는 신뢰를 깬다(contact guard B 강등 결정). 검증 결과는 *예방·측정·내부신호*로, 사용자 향 per-claim 경고 X |
| **측정 우선** | 무인용 사실 환각률을 **먼저 데이터로** 본 뒤 개입 강도 결정 |
| **비차단** | fast 레인(15~20s) 유지 — 검증은 done *뒤* trailing(grounding 패턴) |
| **오탐 회피** | 파괴적 재작성 X. check-worthy 만 좁게 추출(노이즈↓) |
| **thin-client** | 무거운 판정은 Haiku 1콜(배치) — grounding 인프라 재사용 |
| **무결·정확·정합** | 없는 근거 만들지 않음, 정합적 신호만 |

## 3. check-worthy 사실 분류 (핵심 — 좁게)

검증 대상은 **틀리면 실무 피해가 큰 정량·특정 사실**만. 넓히면 노이즈·비용 폭증.

| 대상 (검증함) | 비대상 (건너뜀) |
|---|---|
| 조문/고시 **번호**(제N조, 고시 제2026-N호) | 일반 절차 서술·상식 |
| **수수료·금액**, **기한·일수**, **유효기간** | 이미 hedge된 표현("대략", "확인 필요") |
| **날짜**(시행일·개정일) | 이미 `[n]` 인용된 claim(grounding 담당) |
| **판례 사건번호**·특정 기관/부서명 | 추론·해석 문장(별도 문제) |
| **요건 수치**(예: N일 이내, N% 이상) | URL·전화(contact guard 담당) |

## 4. 메커니즘 — 3계층 (측정 → 예방 → 교정)

### Phase 1 — 사실 감사(audit) 패스 = **내부 신호 (측정)** ✅ 구현됨(2026-07-22)

> 구현: `grounding.audit_uncited_claims`(별도 패스, D1) → verdict supported/contradicted/
> **unverified**(D2 별도 버킷). `chat_loop` done 뒤 비차단 호출 → `claim_audit` 이벤트
> (사용자 비노출). `eval/metrics.claim_groundedness` 지표. `CLAIM_AUDIT_DISABLE=1` 로 끔.

grounding 인프라 확장. done 뒤 trailing, 비차단.

```
audit_uncited_claims(body, haystack) -> list[{claim, verdict}]
  1. LLM(Haiku, 배치 1콜)로 body 에서 check-worthy 사실 추출
     — 단, 이미 [n] 인용된 문장·hedge된 문장은 제외.
  2. 각 claim 을 haystack(이번 턴 source 원문: qdrant full_text +
     tavily content + 레지스트리)에 대해 지지 여부 판정
     (grounding 의 supporting_quote 방식 재사용 — 원문에 실제 있나).
  3. verdict: supported | unsupported | uncertain
```

- **출력 처리**: `unsupported` 건수를 **events(`unsupported_claim`)+log** 로만 기록.
  사용자엔 안 보임(자기모순 회피). 어드민이 **환각률**을 관측.
- **재사용**: haystack 은 contact guard 의 `_turn_source_haystack` 그대로.
  판정 LLM 은 `grounding.ground_citations` 의 quote-추출·substring 검증 로직 확장.

### Phase 2 — 예방 (프롬프트, 측정 개선 확인용)

supervisor 프롬프트에 **정량 사실 규칙** 추가(가드 A 계열, stable 캐시):
> "조문번호·수수료·기한·날짜·수치 요건 등 **정량·특정 사실**은 검색 근거에 있으면
> `[n]` 인용, **없으면 단정하지 말고** '확인 필요'/'대략'으로 표기. 지어낸 숫자 금지."

→ check-worthy 사실을 **grounding 그물 안(인용)** 또는 **hedge**로 밀어넣음.
Phase 1 audit 로 **개선폭 측정**(unsupported율 하락 확인).

### Phase 3 — 교정 루프 (선택, 데이터가 필요하다 하면)

audit 가 unsupported check-worthy 사실을 잡고 예산 여유가 있으면 **1회 교정**:
- 겨냥 재검색(그 사실 관련) → 근거 확보되면 인용, 아니면 hedge 로 재작성.
- fast 레인 지연 우려 → 플래그(`CLAIM_CORRECTION_ENABLE`) 뒤, 또는 값 큰 질의만.
- 기존 coverage gate(`src/coverage.py`)의 gap-search 주입 패턴 재사용.

## 5. 관측·평가

- **events**: `unsupported_claim`(payload: claims·verdict). 어드민 stats 에 "무인용
  사실 환각률" 카드 추가 가능(기존 `/admin/stats` 패턴).
- **eval**: `src/eval/metrics.py` 에 **claim-groundedness** 지표 추가 —
  라벨셋 답변에서 unsupported check-worthy 비율. 회귀 감시(Phase 2 효과 측정).

## 6. 코드 통합 지점

| 파일 | 변경 |
|---|---|
| `src/grounding.py` | `audit_uncited_claims()` 추가(추출+지지판정, ground_citations 확장) |
| `src/chat_loop.py` | done 뒤 `_apply_grounding` 옆에서 audit 호출 → events emit(내부신호) |
| `src/prompts/supervisor.py` | Phase 2 정량 사실 규칙(stable) |
| `src/persistence/events_repo.py` | `unsupported_claim` 이벤트 등록 |
| `src/eval/metrics.py` | claim-groundedness 지표 |
| `src/coverage.py` | Phase 3 교정 재검색(재사용) |
| `src/config.py` | `CLAIM_AUDIT_ENABLE`·`CLAIM_CORRECTION_ENABLE` 노브 |

## 7. 비용·지연

- Phase 1: done 뒤 Haiku 1콜(배치) — **비차단**(사용자 답변은 이미 확정). grounding
  과 병렬 가능. 토큰 소량(추출+판정).
- Phase 2: stable 캐시 프롬프트 — 지속비용 ~0.
- Phase 3: 교정 시에만 재검색+재생성(지연↑) → 기본 off, 선택 활성.

## 8. 열린 결정

- **D1**: audit 판정 LLM = grounding 과 같은 Haiku 배치 1콜로 합칠까(추출·판정·인용검증
  통합), 별도 패스로 둘까? (통합=비용↓, 분리=관심사 분리)
- **D2**: uncertain(근거 애매) 처리 — unsupported 로 셀까, 별도 버킷?
- **D3**: Phase 2 프롬프트 규칙이 모델을 과하게 hedge 시켜 **유용성 저하**(맨날 "확인
  필요") 위험 — 강도 조절 필요. 측정으로 튜닝.
- **D4**: Phase 3 교정을 넣을지 = Phase 1 측정치가 결정(환각률이 낮으면 불필요).

## 9. 권고 착수 순서

1. **Phase 1(측정)부터** — audit 패스 + events + eval 지표. **환각률 실측 없이 개입
   강도를 못 정한다.** (가장 가치 큰 첫 수)
2. 데이터 확보 후 **Phase 2(예방)** → audit 로 효과 측정.
3. 필요성 확인되면 **Phase 3(교정)**.

> 핵심: 이건 "경고를 늘리는" 게 아니라 **"check-worthy 사실을 인용 아니면 hedge로
> 밀어넣고, 남는 무인용 환각을 측정·(선택)교정"** 하는 설계. 사용자에겐 조용하고,
> 운영자에겐 환각률이 보이며, 모델은 점점 근거 있는 것만 단정하게 된다.
