# guardrail-server — 입력 게이트 서비스 (DGX)

medi-back 입력 가드레일의 2차 게이트 모델을 DGX(GB10 GPU)에서 서빙.

> ## ⚠️ 여기가 원본 · 배포 미러는 별도 저장소
>
> ```
> medi-back/guardrail-server/          ← 원본(여기서 수정·테스트·CHANGELOG)
>         │  (수정할 때마다 복사·푸시)
>         ▼
> github.com/yabooung/guardrail-ner    ← 배포 미러. DGX 가 git pull 로 받음
> ```
>
> **코드를 고쳤으면 미러도 같이 푸시할 것.** 2026-08-01 까지 미러가 2026-07-15
> 상태로 방치돼(그동안 scp 로만 배포) `git pull` 이 **옛 코드로 덮어쓰는** 상태였다
> — NER 스팬 가드·intent few-shot 이 미러에 없었고, `deploy.sh`·유닛 파일조차
> 미러에 없어 git pull 배포 자체가 불가능했다.
>
> ```bash
> # 동기화 (medi-back 에서 수정 후)
> gh repo clone yabooung/guardrail-ner /tmp/gr && \
>   cp serve.py serve_intent.py requirements.txt deploy.sh \
>      guardrail-ner.service guardrail-intent.service /tmp/gr/ && \
>   cd /tmp/gr && git add -A && git commit -m "sync: …" && git push
> ```

| 서비스 | 포트 | 모델 | 역할 |
|---|---|---|---|
| PII NER (`serve.py`) | 8090 | Leo97/KoELECTRA-small-v3-modu-ner (2026-08-14 OpenMed 에서 교체 — 한국어 오탐 6/10→0/10 실측, DGX `guardrail.env` `NER_MODEL` 로 스위치) | 이름(PS)·주소(LC) 문맥 PII 스팬. DT/QT 는 의도적 미매핑(법령 날짜·연령 보호) |
| 의도 분류 (`serve_intent.py`) | 8091 | Qwen/Qwen3.5-0.8B | "검색 필요?" 이진 판정 |

- medi-back regex 1차(`src/guardrail/pii.py`)가 구조적 PII 를 결정적으로 잡고, NER 이
  나머지 문맥 PII 를 보강. 의도 분류는 규제 질의에 검색을 강제(환각 차단).
- 연결(미설정 시 폴백): `PII_NER_API_URL`·`INTENT_API_URL`(+`_KEY`).
- 계약: `../docs/contracts/guardrail_ner_service.md` · `../docs/contracts/guardrail_intent_service.md`.

## 서빙 방식 결정 (2026-07-08)

- **NER = transformers** — 토큰분류라 vLLM 불가(필수).
- **의도 = transformers, 별도 프로세스** — 단건 분류(6/9→맥락포함 정확·~165ms)엔
  충분하고, NER·리랭커·27B 와 **프로세스 분리해 부하 격리**(head-of-line 방지).
- **스케일업 경로**: QPS 증가 시 의도를 **vLLM + guided_choice**(예/아니오 강제·배치)로.
  NER 은 계속 transformers. 두 게이트를 한 컨테이너로 합치는 건 격리를 잃으므로 지양.
- torch 는 GB10(Blackwell)에서 `openlaw-search/.venv`(torch 2.11+cu128) 재사용이 안전.

## 배포 (재현 — `deploy.sh`)

ad-hoc ssh 대신 **한 명령 재현 배포**. 멱등(재실행 안전): 핀 의존 설치 → 코드 배치 →
모델 사전다운로드 → systemd 상시화(부팅 자동시작·크래시 자동복구) → 헬스체크.

```bash
# DGX 에서, guardrail-server/ 를 옮긴 뒤:
INSTANCE_API_KEY=<키> ./deploy.sh
#   옵션: GUARDRAIL_VENV=<venv> GUARDRAIL_DIR=<설치경로> NER_THRESHOLD=0.4
```

운영:
```bash
systemctl status guardrail-ner guardrail-intent
journalctl -u guardrail-intent -f
# 코드 수정 재배포: ./deploy.sh (또는 sudo systemctl restart guardrail-*)
```

## 계약

```
POST /detect    (X-API-Key)  { "text": "..." }
  → { "entities": [ {"start","end","label","text"}, … ] }        # 8090
POST /classify  (X-API-Key)  { "text": "...", "context": "직전 주제(옵션)" }
  → { "search_needed": bool, "label": "예"|"아니오" }             # 8091
GET  /health    (X-API-Key)  → {status, model, …}
```

## 튜닝

- `NER_THRESHOLD`(기본 0.4): 라벨 신뢰도 하한. 구 OpenMed 는 한국어 캘리브레이션이
  나빠 민감했으나(오탐-실명 score 겹침), KoELECTRA modu-ner 는 실명 0.87~0.98 로
  분리가 좋다. `NER_MODEL` env 로 모델 교체 가능(원복 = env 제거).
  medi-back `scripts/eval_pii.py` 로 측정해 조정.
- 첫 배포 시 모델 다운로드(deploy.sh 가 사전수행). 이후 HF 캐시. 웜 추론 NER ~50ms·의도 ~165ms.

## 하드닝 (후속)

- 전용 venv/컨테이너로 openlaw-search venv 의존 분리(GB10 torch 패키징 검증 후).
- 게이트 전용 API 키(현재 `INSTANCE_API_KEY` 공유 → 서비스별 키·로테이션).
