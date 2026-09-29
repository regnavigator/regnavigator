# 슬롯 레지스트리 (Slot Registry)

판정에 필요한 사실 항목의 정의다. **슬롯은 추가만 하고, 의미를 바꾸지 않는다.** 의미를 바꿔야 하면 새 ID를 만든다(`_v2`). 의미가 조용히 바뀌면 과거 판정 로그가 오염되어 회귀 테스트가 무효화된다.

값이 확인되지 않으면 `UNKNOWN`으로 둔다. **추정해서 채우지 않는다.**

---

## 공통 — 연구 해당성

| 슬롯 | 값 | 확인 질문 | 근거 |
|---|---|---|---|
| `is_research` | true/false/UNKNOWN | "일반화 가능한 지식을 만드는 것이 목적입니까? (출구조사·여론조사·시장조사·제품만족도조사는 해당 없음)" | IRB SOP 4-나 |
| `is_exempt_org_research` | true/false | "국가·지자체가 공공복리·서비스 프로그램 평가를 위해 직접 또는 위탁 수행하는 연구입니까?" / "학교의 통상적 교육실무 관련 연구입니까?" | IRB SOP 4-다(4) |

`is_research = false`이면 IRB 트랙은 `NOT_SUBJECT`.

---

## IRB — 대상 유형

| 슬롯 | 값 | 확인 질문 | 근거 |
|---|---|---|---|
| `subject_human` | true/false/UNKNOWN | "사람을 대상으로 물리적 개입, 상호작용(설문·면접·관찰), 또는 개인식별정보 이용이 있습니까?" | IRB SOP 4-다 |
| `subject_biospecimen` | true/false/UNKNOWN | "인체로부터 수집·채취한 조직·세포·혈액·체액, 또는 그로부터 분리된 혈청·혈장·염색체·DNA·RNA·단백질을 직접 조사·분석합니까?" | IRB SOP 4-라 |
| `interaction_type` | `physical` / `interaction` / `identifiable_info` / `none` | 위 질문의 세부 구분 | IRB SOP 4-다(1)~(3) |

---

## IRB — 심의면제 판단용

| 슬롯 | 값 | 확인 질문 | 근거 |
|---|---|---|---|
| `minimal_risk_to_public` | true/false/UNKNOWN | "연구대상자 및 공공에 미치는 위험이 미미합니까?" | IRB SOP 5-가(1) |
| `is_public_data` | true/false/UNKNOWN | "일반 대중에게 공개된 정보만 이용합니까?" | IRB SOP 5-가(1) |
| `collects_identifiable_info` | true/false/UNKNOWN | "연구대상자를 직접·간접적으로 식별할 수 있는 정보를 수집하거나 기록합니까?" | IRB SOP 5-가(2) |
| `has_linking_key` | true/false/UNKNOWN | "의무기록번호·등록번호와 연구번호의 대응표(연결키)를 연구진이 보관합니까?" — true 면 `collects_identifiable_info` 는 true(간접 식별) | IRB SOP 4-다(3), 5-가(2) |
| `uses_existing_records` | true/false/UNKNOWN | "연구대상자에 대한 기존의 자료나 문서를 이용하는 연구입니까?(후향적)" | IRB SOP 5-가(2)㈎ |
| `subject_not_specified` | true/false/UNKNOWN | "직접 대면하더라도 연구대상자가 특정되지 않습니까?" | IRB SOP 5-가(2)㈏ |
| `collects_sensitive_info` | true/false/UNKNOWN | "「개인정보 보호법」 제23조 민감정보(사상·신념, 노동조합·정당 가입, 정치적 견해, 건강, 성생활, 유전정보 등)를 수집·기록합니까?" | IRB SOP 5-가(2)㈏ |
| `manipulation_type` | `non_invasive` / `contact_device_only` / `food_test` / `cosmetic_test` / `none` / `other` | "연구대상자나 그 환경을 조작하는 연구라면 어떤 유형입니까?" | IRB SOP 5-가(2)㈐ |
| `vulnerable_subjects` | true/false/UNKNOWN | "취약한 환경에 있는 연구대상자를 대상으로 합니까?" | IRB SOP 5-가(3) |

---

## IRB — 인체유래물연구 면제 판단용

| 슬롯 | 값 | 확인 질문 | 근거 |
|---|---|---|---|
| `bio_collects_personal_info` | true/false/UNKNOWN | "개인정보를 수집·기록합니까?" | IRB SOP 5-나(1) |
| `bio_exempt_type` | `biobank_provided` / `residual_clinical` / `public_material` / `no_identifier_no_genetic` / `none` | 면제 유형 4가지 중 해당 여부 | IRB SOP 5-나(1)㈎~㈑ |
| `embryonic_stem_cell` | true/false | "배아줄기세포주를 이용합니까?" | IRB SOP 5-나(1)㈑ 단서 |

---

## IRB — 하드 게이트 (면제 절대 불가)

| 슬롯 | 값 | 확인 질문 | 근거 |
|---|---|---|---|
| `regulated_trial` | `drug` / `device` / `ivd_performance` / `bioequivalence` / `none` / `UNKNOWN` | "의약품 임상시험, 의료기기 임상시험, 체외진단의료기기 임상적 성능시험, 생물학적동등성시험 중 하나에 해당합니까?" | IRB SOP 5-가(5) |

`none`이 아니면 **즉시 심의면제 불가**. 다른 조건을 보지 않는다.

---

## IRB — 신속/정규 구분용

| 슬롯 | 값 | 확인 질문 | 근거 |
|---|---|---|---|
| `submission_type` | `new` / `amendment` / `continuing` / `completion` / `sae` / `deviation` / `appeal` / `other_report` | "신규 신청입니까, 변경·지속·종료·이상반응·위반·이의신청 중 어느 것입니까?" | IRB SOP 48 |
| `minimal_risk` | true/false/UNKNOWN | "연구로 생길 수 있는 위험·불편이 일상생활이나 일상적 신체·심리검사 수준을 넘지 않습니까?" | IRB SOP 48-바(1) |
| `invasive` | true/false/UNKNOWN | "약물투여·채혈 등 침습적 행위가 있습니까?" | IRB SOP 48-바(1)㈏ |
| `blood_sampling` | 채혈량(ml) / 기간 / 빈도 / 대상자 체중·임신 여부 | "채혈이 있다면 정맥·모세혈관 단순 채혈입니까? 8주간 총량과 주당 횟수는?" | IRB SOP 48-바(1)㈏ |
| `radiation_sedation` | true/false/UNKNOWN | "마취제·진정제를 사용하거나 방사선·Microwave를 이용하는 검사가 포함됩니까?" | IRB SOP 48-바(1)㈑ |
| `device_within_approval` | true/false/UNKNOWN | "사용하는 의료기기가 시판 허가를 받았고 허가사항대로 이용됩니까?" | IRB SOP 48-바(1)㈎ |
| `change_significance` | `minor` / `major` / `UNKNOWN` | "변경 내용이 위험을 최소한으로 유지하고 위험대비이익을 나쁘게 바꾸지 않습니까?" | IRB SOP 48-라(1)㈎, 48-바(5) |
| `subject_count_change` | 증감 인원 / 기존 등록 인원 | "연구대상자 수 변경이 있다면 기존 등록 인원과 증감은?" | IRB SOP 48-다(3)㈑ |
| `legal_or_reputational_risk` | true/false/UNKNOWN | "응답 내용이나 신원 노출로 연구대상자가 민형사상 책임을 지거나, 재정·고용·보험·명성에 손해를 입을 수 있습니까?" | IRB SOP 48-마 |
| `enrollment_status` | `open` / `closed_followup_only` / `none_enrolled` / `analysis_only` | 지속심사 시: "신규 등록이 중단되었습니까? 남은 활동이 자료분석뿐입니까?" | IRB SOP 48-바(1)㈕ |

`legal_or_reputational_risk = true`이면 **신속심사 불가** → 정규심의.

---

## 다른 위원회 슬롯

DRB(의료정보데이터심의위원회) 판정용 슬롯과 IRB↔DRB 연동 슬롯은 **`drb-triage` 스킬의 슬롯 레지스트리**에 있다. 이 스킬은 그 슬롯을 채우지도, 사용하지도 않는다.

두 레지스트리는 **ID 공간을 공유**한다. 같은 이름의 슬롯은 같은 의미여야 하며, 한쪽에서만 의미를 바꾸면 안 된다.
