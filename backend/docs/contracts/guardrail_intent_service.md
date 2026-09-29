# Guardrail 의도 분류 서비스 — 계약 (medi-back 연동)

medi-back 입구 게이트의 **의도 분류**(기능1). 사용자 입력을 4분류해, 규제 질의엔
법령 검색을 **결정적으로 강제**(`IntentSearchMiddleware`)한다.

**왜 필요한가**: 답변 모델이 "검색할지"를 스스로 판단하면, 소형·고속 모델(Haiku
등)은 캐주얼·후속 어투에서 검색을 건너뛰고 자기 지식으로 답하며 인용을 날조한다
(실측 확인). 이 판정을 입구의 경량 분류기로 끌어올려 근거 확보를 모델 선택에서
분리 → **빠른 모델을 안전하게** 쓴다.

## 엔드포인트 (이진 — 4분류는 0.8B 에 부정확, 이진이 정확)

```
POST /classify   (헤더 X-API-Key)   { "text": "그럼 처벌은?", "context": "의료기기 광고 사전심의" }
→ { "search_needed": true, "label": "예" }
GET /health      → {status, model, smoke}
```
- `search_needed=true` → medi-back 이 qdrant_search 강제. `false` → 검색 없이 즉답.
- `context`(옵션): 직전 사용자 질문 — 후속("그럼 처벌은?")을 규제로 판별하게.
- medi-back 클라이언트: `src/guardrail/intent_client.py`, 판정: `src/guardrail/intent.py`.

### 판정 레이어는 하나 — 분류기 (2026-07-25)

메타 질문("너 누구야"·"지금 몇시야")에 검색이 강제되는 문제를 medi-back 쪽
**정규식으로 먼저 막으려다 되돌렸다**. 라이브 0.8B 실측에서 분류기가 메타 10건 중
**9건을 이미 정확히** 판정했고, 정규식이 놓친 "넌 뭐하는 애야"까지 맞혔다.
유일한 누락("현재 시각 알려줘")은 `serve_intent.py` few-shot 에 예시를 추가해
**분류기 쪽에서** 고쳤다.

- 원칙: 의도 판정 규칙을 medi-back 과 분류기 양쪽에 두지 않는다 — 갈라진다.
  medi-back 로컬 단축은 `_OFFTOPIC`/`_NO_QUESTION` **정확 일치 집합**까지만
  (분류기 호출조차 아까운 "안녕"·"대답해" 류). 그 이상의 의미 판단은 분류기.
- few-shot 에 메타 예시를 넣을 땐 **대조쌍**("의료기기 허가 몇 시간 걸려?"→예)을
  같이 넣는다. '시각' 예시가 소요기간 질문까지 '아니오'로 끌고 가면 규제 질문이
  무검색으로 새어 환각이 된다.

## 모델 / 배포 (✅ 완료 2026-07-08)

- **Qwen3.5-0.8B**(공개, 초경량 Dense, ~2GB) — few-shot 이진 프롬프트 + 대화맥락.
  DGX(GB10) `guardrail-server/serve_intent.py`, 포트 **8091**, systemd
  `guardrail-intent.service`(상시), 검색서버 venv 재사용. 지연 **~165ms**.
- **실측 정확도**: 4분류는 4/8(부정확·라벨 대신 답변) → 이진 few-shot 8/9 →
  **대화맥락 포함 시 위험오탐(규제 후속 스킵) 제거**, medi-back 연동 6/6.
- 왜 이진: 소형 0.8B 는 4분류의 미묘한 경계(법령문의 vs 업무절차 vs 일반)를
  신뢰 못 함. medi-back 이 실제 필요한 건 "검색 필요?"뿐이라 이진이 정확·충분.
  4분류 라우팅(Responder/Researcher)이 필요하면 더 큰 모델(2B/4B) 검토.

## medi-back 동작 (분류기 없이도 안전)

- `INTENT_API_URL` 미설정 → `intent.py` 휴리스틱 폴백: **정확히 인사말/감사(`_OFFTOPIC`)
  또는 물음없는 재촉·필러(`_NO_QUESTION`: "대답해"·"빨리"·"계속")인 전체 메시지만**
  off-topic(검색 스킵), 그 외 전부 검색(근거 우선). 규제 챗봇은 대부분 질의가 규제라
  폴백으로도 실용적. 분류기는 문맥·경계 케이스 정확도를 올린다.
- 검색강제 자체는 `INTENT_SEARCH_DISABLE=1` 로 끔.

## 검증 (도입 전)

- 한국어 4분류 정확도(특히 캐주얼·후속·경계). "좋아 그럼 처벌은?"→법령문의 같은
  케이스 포함.
- 지연 p95 < 200ms.

## 상태

- medi-back 미들웨어·클라이언트·휴리스틱 폴백 완료(동작 중).
- **분류기 서비스 배포 완료·동작 중**(2026-07-25 확인): DGX `spark-e125`,
  systemd `guardrail-intent` active, `/health` → `{status: ok, model:
  Qwen/Qwen3.5-0.8B}`. (구 "배포 미완" 기재는 오래된 것 — 정정.)
  - WorkingDirectory `/srv/guardrail-ner`,
    인터프리터는 openlaw-etl venv 재사용.
  - ⚠️ GPU VRAM 은 vLLM writer·KURE·NER 가 대부분 점유 — 검증용으로 모델을
    한 벌 더 띄우면 CUDA OOM. 프롬프트 실험은 `INTENT_DEVICE=cpu` 로.
