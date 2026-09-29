# DRB 슬롯 레지스트리 (Slot Registry)

판정에 필요한 사실 항목의 정의다. **슬롯은 추가만 하고, 의미를 바꾸지 않는다.** 의미를 바꿔야 하면 새 ID를 만든다(`_v2`). 의미가 조용히 바뀌면 과거 판정 로그가 오염되어 회귀 테스트가 무효화된다.

값이 확인되지 않으면 `UNKNOWN`으로 둔다. **추정해서 채우지 않는다.**

> `irb-triage`의 슬롯 레지스트리와 **ID 공간을 공유**한다. 같은 이름의 슬롯은 같은 의미여야 하며, 한쪽에서만 의미를 바꾸면 안 된다.

---

## 대상 판단용

| 슬롯 | 값 | 확인 질문 | 근거 |
|---|---|---|---|
| `uses_hospital_data` | true/false/UNKNOWN | "병원이 보유·관리하는 진료·검사·영상·병리·처방·임상연구·유전체 정보를 이용합니까?" | 제3조1호 |
| `data_purpose` | `research` / `education` / `other` | "이용 목적이 교육·연구입니까? (신청서상 통계작성 / 공익적 기록보존 / 과학적 연구 중 어느 것입니까?)" | 제1조, 별지서식 10 |
| `data_action` | `use` / `provide` / `export` / `combine` (복수 가능) | "데이터를 이용만 합니까, 제공·반출·결합합니까?" | 제1조 |

`uses_hospital_data = false`이면 `NOT_APPLICABLE`.

---

## 데이터 성격

| 슬롯 | 값 | 확인 질문 | 근거 |
|---|---|---|---|
| `data_state` | `pseudonymized` / `anonymized` / `identifiable` / `consented` / `UNKNOWN` | "가명정보입니까, 익명정보입니까, 아니면 연구대상자의 데이터 활용 동의를 받았습니까?" | 제3조2호, 제32조①1호 |
| `includes_genomic` | true/false/UNKNOWN | "유전체정보가 포함됩니까?" | 제3조1호 |
| `includes_sensitive` | true/false/UNKNOWN | "「개인정보 보호법」제23조 민감정보(희귀난치 진단명 등)가 포함됩니까?" | 별지서식 10 예시 |
| `uses_linkage_file` | true/false/UNKNOWN | "재식별 또는 데이터 연계를 위한 연결파일을 사용합니까?" | 제3조5호 |

---

## 처리·반출 환경

| 슬롯 | 값 | 확인 질문 | 근거 |
|---|---|---|---|
| `data_export_type` | `none` / `analysis_result` / `raw_data` / `UNKNOWN` | "데이터를 병원 밖으로 내보냅니까? 원시데이터 반출입니까, 분석결과만 반출입니까?" | 제3조3호 |
| `closed_analysis_room` | true/false/UNKNOWN | "원내 폐쇄형 분석실에서 데이터를 처리합니까?" | 제24조④5호, 제32조①5호 |
| `data_combination` | true/false/UNKNOWN | "결합전문기관을 통한 가명정보 결합이 있습니까?" | 제3조9호 |
| `external_provision` | true/false/UNKNOWN | "외부기관에 데이터를 제공합니까?" | 제3조3호 |
| `recipient_orgs` | 기관명 목록 | "데이터를 제공받는 기관은 어디입니까?" | 별지서식 10 '활용 주체' |
| `repeated_provision` | `once` / `repeated` | "데이터를 1회 제공합니까, 반복 제공합니까?" | 별지서식 10 |
| `privacy_risk` | `none_or_minimal` / `present` / `UNKNOWN` | "연구대상자 등의 개인정보 침해 위험이 없거나 미미합니까?" | 제32조①2호 |

**용어 정의 (제3조3호)**
- **원시데이터 반출**: 가명처리된 개별 환자 단위의 데이터를 외부로 복제하여 이동하는 행위
- **분석결과 반출**: 원내 폐쇄형 분석실에서 데이터 분석 후, 개인 식별이 불가능한 통계표·모델 가중치 등의 결과물만을 외부로 이동하는 행위

---

## 신청 유형

| 슬롯 | 값 | 확인 질문 | 근거 |
|---|---|---|---|
| `drb_submission_type` | `new` / `amendment` / `continuing` / `completion` / `supplementary` / `appeal` / `expedited` | "DRB 신규·변경·지속·종료·보완·이의신청 중 어느 것입니까?" | 제27~32조 |
| `prior_committee_approval` | true/false/UNKNOWN | "기관 협약 등을 통해 운영되는 공용 데이터심의위원회의 승인을 이미 받았습니까?" | 제24조④4호, 별지서식 16 |
| `prior_decision` | `none` / `conditional_approval` / `corrective_approval` / `supplement` / `reject` | "이전 심의 결정이 있었다면 무엇이었습니까?" | 제21조①, 제32조①4호 |
| `change_scope` | `duration_only` / `data_items` / `method` / `subject` / `safeguards` / `export_scope` (복수 가능) | "변경 내용이 기간 연장뿐입니까, 아니면 데이터 항목·활용 방법·활용 주체·안전조치·반출 범위도 바뀝니까?" | 제30조⑥ |
| `drb_change_impact` | `minor` / `major` / `UNKNOWN` | "변경이 정보주체 보호에 중대한 영향을 미칠 우려가 있습니까?" | 제30조⑤ |

⭐ `drb_change_impact = major`이면 변경심의를 **정규심의에 회부**할 수 있다 (제30조⑤). IRB의 `change_significance`와는 판단 기준이 다르므로 **ID를 분리**했다.

⭐ `drb_submission_type = continuing`이고 `change_scope`에 `duration_only` 외의 값이 있으면 **변경심의를 함께 신청**해야 한다 (제30조⑥).

---

## 심의면제 판단용 (제32조⑦)

| 슬롯 | 값 | 확인 질문 | 근거 |
|---|---|---|---|
| `no_pseudonymization_needed` | true/false/UNKNOWN | "IRB 승인을 이미 받았고, 가명처리가 필요 없는 데이터입니까?" | 제32조⑦1호 |
| `no_personal_info` | true/false/UNKNOWN | "개인을 식별할 수 있는 정보가 포함되지 않습니까?" | 제32조⑦2호 |
| `collected_with_consent` | true/false/UNKNOWN | "동의를 받고 수집한 데이터입니까?" | 제32조⑦3호 |
| `from_crf` | true/false/UNKNOWN | "증례보고서(CRF)를 통해 수집된 데이터입니까?" | 제32조⑦4호 |

⭐ 1호(`no_pseudonymization_needed`)는 **IRB 승인이 이미 있는 것을 전제**한다. `irb_approval_status = approved`가 아니면 적용하지 않는다.

---

## IRB 연동

| 슬롯 | 값 | 확인 질문 | 근거 |
|---|---|---|---|
| `irb_approval_status` | `approved` / `submitted` / `not_yet` / `not_required` / `UNKNOWN` | "IRB 승인을 이미 받았습니까, 접수만 했습니까, 아직입니까, 아니면 IRB 대상이 아닙니까?" | 제27조②7호 |
| `irb_approval_no` | 승인번호 | "IRB 승인번호가 있습니까?" | 별지서식 10 |
| `irb_expiry_date` | 날짜 | "IRB 승인유효기간 만료일은 언제입니까?" | 제29조② |
| `drb_expiry_date` | 날짜 | "DRB 승인유효기간 만료일은 언제입니까?" | 제29조③ |
| `requested_period` | 시작일~종료일 | "신청하려는 데이터 활용기간은 언제부터 언제까지입니까?" | 제27조③ |

> `irb_approval_status = not_required`라고 사용자가 주장하면 **근거를 확인한다.** 확인되지 않으면 `irb-triage` 호출을 권한다. 사람 대상·인체유래물이 얽힌 데이터 연구에서 IRB 대상 아님을 스스로 단정하는 것은 흔한 오류다.

---

## 활용기간 적정성 점검용

| 슬롯 | 값 | 확인 질문 | 근거 |
|---|---|---|---|
| `disposal_plan` | true/false/UNKNOWN | "활용 종료 후 데이터 보존·파기 계획이 있습니까?" | 제27조④, 제31조③3호 |
| `internal_mgmt_plan` | true/false/UNKNOWN | "수령기관의 내부관리계획서가 준비되었습니까?" | 제27조②5호 |
| `security_certification` | ISMS / ISMS-P / 없음 / UNKNOWN | "제공받는 기관이 가명정보처리시스템에 대한 인증을 보유하고 있습니까?" | 별지서식 10 예시 |
