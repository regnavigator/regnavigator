# Guardrail PII NER 서비스 — 계약 (medi-back 연동)

medi-back 입력 게이트의 **2차 탐지**(이름·주소 등 문맥 PII)를 담당하는 별도
서비스. regex 1차(`src/guardrail/pii.py`)가 구조적 PII 를 잡고, 이 서비스가
NER 로 문맥 PII 스팬을 돌려주면 medi-back 이 마스킹한다.

**왜 별도 서비스인가**: medi-back 은 thin-client(로컬 ML 없음, 검색도 openlaw-etl
API 위임). PII NER 모델도 이 서비스가 소유·호스팅한다.

**현행 모델(2026-08-14 교체)**: `Leo97/KoELECTRA-small-v3-modu-ner`(모두의말뭉치
NER, 한국어 특화). 종전 `OpenMed/privacy-filter-multilingual`(다국어)은 한국어
오탐이 과다해('운'→FIRSTNAME 0.95, '구체적으로'→ADDRESS 등, 비교 평가에서 오탐
문장 6/10 vs 신모델 0/10) 교체 — DGX `guardrail.env` 의 `NER_MODEL` env 스위치,
원복은 env 제거. 라벨: PS→NAME, LC→ADDRESS (serve.py `_FAMILY`). **DT(날짜)·
QT(수량)는 의도적 미매핑** — 법령 시행일·연령 기준 보호(생년월일은 medi-back
regex 가 문맥 한정으로 커버). 상세: CHANGELOG 2026-08-14 (5).

## 엔드포인트

```
POST /detect            (헤더: X-API-Key)
Content-Type: application/json
{ "text": "홍길동 환자가 서울 강남구에서 내원" }
```
응답:
```json
{ "entities": [
  { "start": 0, "end": 3, "label": "PERSON_NAME", "text": "홍길동" },
  { "start": 8, "end": 13, "label": "ADDRESS", "text": "서울 강남구" }
] }
```
- `start`/`end`: **요청 text 기준 char 오프셋**(파이썬 슬라이스 규약, end 배타).
- `label`: 모델 카테고리 문자열(서비스가 패밀리로 정규화 — NAME/ADDRESS 등).
  medi-back 은 라벨 키워드로 한국어 placeholder 를 매핑
  (`src/guardrail/gate.py::_LABEL_KEYWORDS` + PS/LC 정확 일치) — NAME/PERSON/PS→
  `[이름]`, ADDRESS/LOCATION/LC→`[주소]`, BIRTH→`[생년월일]`, AGE→`[나이]`.
  화이트리스트 밖 라벨(CV·TM·AF·DT·QT 등)은 마스킹하지 않는다.
- 엔티티 없으면 `{"entities": []}`.

## medi-back 측 동작

- env `PII_NER_API_URL`/`PII_NER_API_KEY` 설정 시 활성(미설정=regex-only).
- 입구 저지연 유지 위해 타임아웃 `PII_NER_TIMEOUT_S`(기본 3s). **서비스 오류·
  타임아웃은 best-effort — regex 결과로 안전 진행**(대화 안 막음).
- 클라이언트: `src/guardrail/ner_client.py`. 조합: `src/guardrail/gate.py::scrub_input`.

## 요구사항 / 검증 (도입 전 필수)

- **한국어 recall 측정**: OpenMed 다국어 모델은 공개 한국어 지표가 없다. 도입 전
  `data/pii_eval_ko.jsonl` + `scripts/eval_pii.py` 로 한국어(환자명·주소·생년월일)
  recall 을 자체 측정. 목표: 이름·주소 recall ≥ 0.9.
- **지연**: 문장당 p95 < 200ms(입구 예산). 초과 시 배치·비동기·경량 변형 검토.
- **오탐 억제**: 법령명·조문·기관명(식약처 등)·질병명을 인명/주소로 오탐하면
  검색 쿼리가 훼손된다 — 오탐 케이스도 평가셋에 포함해 측정.
- **부속서**: 서비스는 원문 text 를 로깅/영속하지 말 것(air-gapped 처리).

## 실측 결과 (2026-08-14, KoELECTRA 교체 후 — 현행)

운영 전체 파이프라인(regex+NER+가드) 21케이스: **recall 9/9 · precision 12/12**.
비교 평가(동일 셋): OpenMed 오탐 문장 6/10 → KoELECTRA 0/10, 이름·주소 리콜
동등 이상. 알려진 한계: 희귀 이름 일부 미탐('최다온입니다'·'독고영재'→TM),
도로명이 AF 라벨로 나와 시·군·구까지만 마스킹되는 케이스.

**한계 보정(2026-08-16, medi-back gate.py)**: ① [주소] 스팬 우측의 도로명+
번지 꼬리 확장(주소 문맥 확정 시에만 — '회의로 5명' 류 조사 오탐 없음)
② 자기소개 정형 문맥("저는 X입니다"·"제 이름은 X"·"X라고 합니다")의 성씨
게이트 결정적 이름 마스킹(역할·신분 명사 + 도메인 스토플리스트 차단). 확장
평가셋 26문장: regex 13/13 · NER 9/9 · **오탐 0**.

## 실측 결과 (2026-07-07, 구 OpenMed — 역사 기록)

DGX(spark-e125, GB10)에 `guardrail-server/serve.py` 로 배포(포트 8090, 검색서버
venv 재사용). `OpenMed/privacy-filter-multilingual`, threshold **0.4**, 웜 추론
~20–50ms(<200ms 예산 충족). `scripts/eval_pii.py`(한국어 22문장) 측정:

- **regex 1차: recall 1.00 · 오탐 0** (구조적 PII — 신뢰 가능한 주력).
- **NER 2차 주소·생년월일·나이: 양호** (서울특별시 강남구·1978년 3월 14일 등 온전 마스킹).
- **NER 2차 한국어 이름: 부분적·불안정** (recall ≈0.85–1.0, 문맥 의존. 같은 이름도
  주변 문맥 따라 놓칠 수 있음 — 다국어 모델의 한국어 약점). 파편화·역할어 오병합
  (담당의·환자→이름)은 서비스 후처리(패밀리 병합·공백 트림·한글 확장·이름-숫자
  가드)로 억제해 **오탐 0** 달성.

**해석**: regex 가 고위험 식별자를 확실히 커버, NER 은 이름·주소 보조. 한국어 이름
recall 을 높이려면 한국어 특화 NER 이 필요(로드맵). 현재 조합은 "확실한 구조적
마스킹 + 부분적 이름·주소 마스킹, 검색 품질 무손상(오탐 0)".

## 운영 메모

- 현재 기동: `nohup uvicorn`(재부팅 시 자동 복구 X). 지속화하려면 systemd 유닛 또는
  `openlaw-etl/scripts/refresh_dgx.sh` 에 편입 필요 — **후속 과제**.
- medi-back 연결: prod `.env.docker` 에 `PII_NER_API_URL=http://192.0.2.10:8090`,
  `PII_NER_API_KEY=<INSTANCE_API_KEY>` 설정(도커가 Tailscale 도달 필요).
