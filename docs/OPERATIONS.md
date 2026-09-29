# MEDIREG AI — 운영 가이드

백엔드(`backend/`, FastAPI)와 프런트엔드(`frontend/`, Next.js 15)를 함께 운영하기 위한 한 장짜리 요약.
세부 계약·설계는 아래 문서를 본다.

- 아키텍처 정본: `backend/docs/guide/architecture.md`
- 온보딩: `backend/docs/guide/onboarding.md`
- 프런트 계약(SSE·폴링·REST): `backend/docs/contracts/frontend_chat_v2.md` · API 명세: `backend/docs/contracts/API.md`
- 마이그레이션 결정 기록: `backend/docs/spec/ADR-0001-fastapi-migration.md`

표기: `<APP_DOMAIN>`(서비스 도메인), `<VM_HOST>`(앱 VM), `<DGX_HOST>`(온프레미스 GPU 서버, Tailscale 내부 주소),
`<OPENLAW_DB_HOST>`(법령 DB 호스트), `<DEPLOY_DIR>`(VM 배포 디렉터리) 는 환경별 값으로 바꿔 읽는다.

---

## 1. 토폴로지 한 장

```
 [브라우저]
     │ HTTPS (<APP_DOMAIN>)
     ▼
 [리버스 프록시 nginx/Caddy — SSE 버퍼링 off]
     │                         │
     ▼                         ▼
 ┌──────────── 앱 VM (<VM_HOST>, docker compose, 네트워크 medi-net) ────────────┐
 │  frontend  :3000  Next.js + NextAuth(JWT 발급) ──Prisma──┐                    │
 │     │  Bearer JWT (NEXTAUTH_SECRET 공유)                   │                    │
 │     ▼                                                    ▼                    │
 │  backend   :6000→8000  FastAPI(uvicorn 1 worker)   postgres :6001→5432        │
 │     │                                              ├─ medi      (운영 데이터) │
 │     │                                              └─ medi_auth (인증, 프런트)│
 │  medi-cron (보존정리·야간 회귀)   medi-backup (일일 pg_dump)                  │
 └─────┼────────────────────────────────────────────────────────────────────────┘
       │
       ├── Tailscale ──► [DGX GPU 서버 <DGX_HOST>]
       │                   :8080 검색 API (/search, 하이브리드+리랭커)
       │                   :8090 PII NER        :8091 의도 분류
       │                   :8000 보고서 writer (vLLM, 서빙 모델 자동 감지)
       │                   :8001 임베딩 (vLLM, 검색서버 내부용)
       │
       ├── [openlaw 법령 DB <OPENLAW_DB_HOST>] PG / Mongo / Neo4j — 읽기 전용
       │        (/article·/law-graph·pinned 전용. RAG 검색은 검색 API 경유)
       │
       └── [외부 API] Anthropic(Haiku 기본·Sonnet 폴백) · OpenAI(옵션 폴백)
                      Tavily(웹 검색) · SMTP(보고서 완료 메일)
```

| 구성요소 | 포트 | 기동 방식 | 외부 노출 |
|---|---|---|---|
| frontend | 3000 | compose `medi-front` | 프록시 뒤 공개 |
| frontend migrator | — | compose `medi-front-migrate`(1회 실행 후 종료) | — |
| backend | 6000 (컨테이너 8000) | compose `medi-back` | 프록시 뒤 공개 |
| postgres | 6001 (컨테이너 5432) | compose `postgres` | 비공개 권장(방화벽 화이트리스트 또는 매핑 제거) |
| medi-cron / medi-backup | — | compose | — |
| 검색 API | 8080 | DGX systemd `openlaw-search` | Tailscale 내부 |
| PII NER | 8090 | DGX systemd `guardrail-ner` | Tailscale 내부 |
| 의도 분류 | 8091 | DGX systemd `guardrail-intent` | Tailscale 내부 |
| 보고서 writer | 8000 | DGX docker(vLLM) | Tailscale 내부 |
| 임베딩 | 8001 | DGX docker(vLLM) | Tailscale 내부 |
| 로컬 dev backend | 2024 | uvicorn 직접 | 로컬 |

두 흐름:
- **fast** — `POST /chat`(SSE, 15~20초): PII 게이트 → 의도 판정 → 검색 강제 → 답변 스트리밍 → 인용 검증.
- **deep** — `POST /reports` + 폴링(백그라운드, 서빙 모델에 따라 5~40분): 분해 → 수집 → 로컬 vLLM writer.
  채팅과 완전히 분리된다. 결과물은 사이드바·우측 패널·이메일 첨부로만 전달.

---

## 2. 로컬 개발 기동

### 2-1. 백엔드 (`backend/`)

```bash
cd backend
python -m venv venv && source venv/bin/activate      # Windows: .\venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env                                  # 키 채우기 (설명은 .env.example 주석)

# PYTHONUTF8 필수 — .env 의 한글 주석을 Windows 기본 코덱(cp949)이 못 읽는다
PYTHONUTF8=1 python -c "from dotenv import load_dotenv; load_dotenv(); import uvicorn; uvicorn.run('src.api:app', port=2024)"
#   PowerShell: $env:PYTHONUTF8="1"  후 같은 명령
```

- dev 는 **SQLite 고정**(`REPORTS_BACKEND=sqlite`, `./medi_reports.db`). 대화·보고서·사용자 상태가 모두 여기에 남는다.
- dev 프로세스가 원격 PG 에 붙으려 하면 부팅 가드가 막는다. 운영 DB 읽기가 꼭 필요한 스크립트는 그 실행에만
  `ALLOW_REMOTE_PG=1 REPORTS_BACKEND=postgres REPORTS_PG_DSN=...` 를 명시한다.
- 노브(환경변수) 목록·기본값의 단일 진실원은 `backend/src/config.py` 의 `ENV_REGISTRY`.
- 테스트: `pytest tests/ -q` · 설정 점검: `python scripts/check_config.py`

### 2-2. 프런트엔드 (`frontend/`)

```bash
cd frontend
npm install
cp .env.example .env.local        # NEXT_PUBLIC_DEPLOYMENT_URL(백엔드 주소)·NEXTAUTH_SECRET·DATABASE_URL
npx prisma migrate dev            # 인증 DB
npm run dev                       # http://localhost:3000

npm run lint && npx tsc --noEmit && npm run build   # CI 와 같은 게이트
```

- `NEXTAUTH_SECRET` 은 백엔드와 **같은 값**이어야 한다(백엔드가 프런트 발급 JWT 를 검증).
- 백엔드 없이 UI 만 볼 때: `NEXT_PUBLIC_DUMMY_MODE=true`.
- `NEXT_PUBLIC_*` 는 빌드 시 번들에 박힌다 — 값을 바꾸면 재빌드해야 반영된다.

### 2-3. 재부팅 후 기동 체크리스트

로컬만 재부팅했다면 0·1·3·4 만 하면 된다(DGX 서비스는 systemd/docker 로 부팅 자동 시작).

| 단계 | 할 일 | 확인 |
|---|---|---|
| 0 | Tailscale 연결 — `tailscale status`, 끊겼으면 `tailscale up` | `<DGX_HOST>` ping 응답 |
| 1 | 백엔드 기동(2-1, `PYTHONUTF8=1`) | `http://127.0.0.1:2024` 3초 내 응답 |
| 2 | (DGX 도 재부팅했을 때만) `systemctl is-active openlaw-search guardrail-ner guardrail-intent`, 비활성이면 `sudo systemctl start ...`; `docker ps` 로 vLLM(writer·임베딩) 확인 | 전부 active |
| 3 | 헬스 체크(아래) | 전부 200 |
| 4 | 스모크: `python scripts/bench_chatloop.py "의료기기 광고 사전심의 절차 알려줘"` | 검색 1회 + 인용 달린 한국어 답변 |

```bash
KEY=<RAG_SEARCH_API_KEY>
curl -s -H "X-API-Key: $KEY" http://<DGX_HOST>:8080/search/health   # 검색
curl -s -H "X-API-Key: $KEY" http://<DGX_HOST>:8090/health          # PII NER
curl -s -H "X-API-Key: $KEY" http://<DGX_HOST>:8091/health          # 의도 분류
curl -s http://<DGX_HOST>:8000/v1/models                            # writer 서빙 모델
curl -s http://127.0.0.1:2024/readyz                                 # 백엔드 의존성
curl -s http://127.0.0.1:2024/load                                   # 부하(원활/혼잡)
```

자주 걸리는 것:
- 기동 즉시 `UnicodeDecodeError: 'cp949'` → `PYTHONUTF8=1` 누락.
- dev 에서 `/readyz` 가 degraded(postgres down) → 운영 PG DSN 미설정 때문. dev 는 SQLite 폴백이라 채팅·검색·조문 조회 모두 정상.
- 첫 검색이 느림 → 리랭커 콜드. keepalive(`SEARCH_KEEPALIVE_S`)가 곧 워밍한다.

---

## 3. 배포

### 3-1. 구성

| 대상 | compose 파일 | env 파일(VM 에만 존재) | 서비스 |
|---|---|---|---|
| 백엔드 | `backend/docker-compose.yml` | `<DEPLOY_DIR>/medi-back/.env.docker` | `medi-back`·`postgres`·`medi-cron`·`medi-backup` |
| 프런트 | `frontend/docker-compose.yml` | `<DEPLOY_DIR>/medi-front/.env.docker` | `medi-front-migrate`→`medi-front` |

- 두 compose 는 외부 네트워크 `medi-net` 을 공유한다(백엔드가 만들고 프런트가 재사용). 프런트 인증 DB 는
  백엔드 postgres 인스턴스 안의 별도 DB `medi_auth`(`DATABASE_URL` 의 호스트는 compose 서비스명 `postgres`, 포트 5432, DB `medi_auth`).
- 템플릿: `backend/.env.docker.example`, `frontend/.env.docker.example`. 복사 후 `chmod 600`.
- 수동 기동: `docker compose --env-file .env.docker up -d --build`

### 3-2. 자동 배포 흐름 (main push)

`main` 에 push 하면 VM 의 **self-hosted runner** 가 워크플로(`.github/workflows/deploy.yml`)를 실행한다.

백엔드:
1. 체크아웃 → `rsync --delete` 로 `<DEPLOY_DIR>/medi-back` 동기화(`.env.docker`·`data/`·`.git/` 제외)
2. **점검 모드 ON** (`scripts/maintenance.py on "..."`) — 재기동 직전 드레인 구간을 덮는다
3. `docker compose --env-file .env.docker up -d --build` (커밋 SHA·빌드 시각을 이미지에 주입 → `/admin/build`)
4. `/healthz` 를 5초 간격 최대 300초 대기. 실패 시 `compose ps` + 로그 150줄 출력 후 실패 처리
5. **점검 모드 OFF** — 성공/실패와 무관하게 항상 실행(플래그가 켜진 채 방치되는 것을 막는다)
6. 성공했을 때만 dangling 이미지 정리(실패 시 이전 이미지는 롤백용으로 보존)

- 트리거 경로를 명시한다(`src/`·`scripts/`·`data/`·`db/`·`docs/legal/`·Dockerfile·compose·pyproject).
  `docs/legal/` 은 런타임에 서빙되므로(약관·방침) 반드시 배포 대상이다. 그 밖의 문서 변경은 배포하지 않는다.
- `concurrency: cancel-in-progress: true` — 멈춘 run 이 쌓이지 않게 한다.

프런트:
1. `rsync --delete` 로 `<DEPLOY_DIR>/medi-front` 동기화(`.env*`·`node_modules/`·`.next/` 제외)
2. `build --no-cache medi-front medi-front-migrate` — `NEXT_PUBLIC_*` 변경이 캐시에 묻히지 않게
3. `up -d --force-recreate` — `medi-front-migrate`(`prisma migrate deploy`, 멱등)가 **성공해야** `medi-front` 가 뜬다
   (스키마 없는 채로 앱이 떠서 500 을 쏟는 사고 방지)
4. `/api/health` 대기 → dangling 이미지 정리

### 3-3. VM 에서 손으로 해야 하는 것

- **`.env.docker` 는 git 에 없다.** VM 에서 직접 편집한다(rsync 가 덮지 않는다).
- **새 env 키는 두 곳에 넣어야 컨테이너에 전달된다**: VM 의 `.env.docker` + `backend/docker-compose.yml` 의
  해당 서비스 `environment:` 매핑(`KEY: ${KEY:-기본값}`). compose 매핑이 없으면 `.env.docker` 에 적어도 앱이 못 본다.
  `medi-cron` 처럼 같은 값을 써야 하는 보조 서비스에도 매핑이 있는지 확인한다.
- env 만 바꿨다면 재생성해야 반영된다: `docker compose --env-file .env.docker up -d --force-recreate medi-back`
  (파일만 고치면 옛 env 로 계속 돈다).
- 배포 전: `python scripts/check_config.py` — prod 필수 env 누락이면 exit 1. 컨테이너는 `STRICT_CONFIG=1` 이면
  필수 키(검색 API URL/키·`NEXTAUTH_SECRET`·`ANTHROPIC_API_KEY` 등) 누락 시 부팅을 거부한다.
- 새 소스 디렉터리를 추가했다면 `.dockerignore`(예: `data/`)에 걸리지 않는지 확인. 이미지에서 빠지면
  `/healthz` 는 200 인데 `/chat` 만 500 이 난다(브라우저에는 CORS 오류로 보인다).
- 예약 발송류 기능은 **꺼진 상태로 첫 배포**한다. 발송 시각이 이미 지난 날 배포하면 즉시 발송된다.

### 3-4. 점검 모드 (서버는 켠 채 일반 사용자만 차단)

비관리자 API 는 503(점검 안내), 관리자는 통과. 상태는 DB(`app_settings`)에 있어 재기동해도 유지되고,
실행 중 서버에 5초 내 반영된다. 프런트는 백엔드 **무응답 자체도 점검 화면**으로 처리한다.

```bash
docker compose --env-file .env.docker exec -T -e PYTHONPATH=/app medi-back \
  python scripts/maintenance.py on "데이터 갱신 중"
python scripts/maintenance.py status
python scripts/maintenance.py off
python scripts/maintenance.py schedule 04:00 04:20 "데이터 갱신 중"   # 매일 반복 예약(KST)
```

관리자 화면(설정 > 서버 점검)과 `POST /admin/maintenance` 로도 켜고 끌 수 있다. 관리자 판정은 프런트·백엔드
양쪽 `ADMIN_EMAILS` 로 한다 — 프런트 쪽이 비어 있으면 관리자도 점검 화면에 갇힌다.

### 3-5. 백업·복구

- `medi-backup` 이 매일 `medi`·`medi_auth` 를 pg_dump → `medi_backups` 볼륨(`BACKUP_RETENTION_DAYS`, 기본 14일).
- 복구: `gunzip -c medi_YYYYMMDD.sql.gz | docker compose exec -T postgres psql -U medi -d medi`
- 분기 1회 복구 리허설(복구해 보지 않은 백업은 백업이 아니다).

---

## 4. 운영 불변식

어기면 조용히 망가지는 규칙들. 코드·테스트·부팅 가드로 강제되는 것이 대부분이다.

1. **단일 워커·단일 인스턴스.** 검색 백프레셔(`SEARCH_MAX_CONCURRENCY`=2)·보고서 큐(`REPORT_MAX_CONCURRENCY`=1)·
   스레드별 턴 락·전역 LLM RPS 캡·rate limit 이 전부 **프로세스 로컬**이다. uvicorn `--workers 1` 고정(Dockerfile).
   - 부팅 시 `src/single_instance.py` 가 PG 어드바이저리 락을 잡고, 두 번째 인스턴스는 부팅을 거부한다
     (`SINGLE_INSTANCE_LOCK=strict|warn|off`, dev SQLite 는 건너뜀). `/readyz` 의 `single_instance` 로 확인.
   - `WEB_CONCURRENCY` 가 1 이 아니면 부팅이 거부된다.
   - 수평 확장이 필요하면 먼저 이 상태들을 공유 저장소(Redis)로 옮긴다(6장).
2. **라우트 async 규약.** `async def` 라우트는 반드시 `await` 를 가져야 하고, 없으면 `def` 로 선언해 스레드풀에
   맡긴다. 동기 DB·SMTP·urllib 을 이벤트 루프에서 부르면 SSE·보고서가 함께 멈춘다.
   `tests/test_async_route_convention.py` 가 AST 로 강제.
3. **규제 질의는 검색이 강제된다.** `chat_loop._should_force_search` 가 `tool_choice` 로 검색 도구를 강제 바인딩한다.
   검색 여부를 모델에 맡기면 캐주얼한 질문에서 인용을 날조한다(실측). 근거 확보를 모델 선택에서 분리한 설계다.
4. **보고서 트리거는 자유 텍스트가 아니다.** `POST /reports` + `idempotency_key`(`^rpt_…`) 멱등 락으로만 시작한다.
   재시작으로 끊긴 잡은 새 키로 재요청. 보고서는 채팅 대화록에 섞지 않는다(의도된 분리).
5. **채널 분리.** 본문에 참고문헌·다음 단계 안내를 넣지 않는다. `<next_steps>` 마커 계약과 전용 UI 로 전달.
6. **클로즈 베타 게이트.** `BETA_WHITELIST_EMAILS` 가 설정되면 목록 밖 사용자는 유효 JWT 여도 403(매 요청 검사).
   `ADMIN_EMAILS` 는 항상 허용. 정식 오픈 = 해당 env 제거.
7. **보존 정리(`medi-cron`, 일 1회).** `prune_threads`·`prune_blobs`·`prune_events` 실행.
   - 기본 DRY_RUN — 며칠 관찰 후 `.env.docker` 에 `PRUNE_APPLY=1`.
   - 보존 기간: `CHAT_RETENTION_DAYS`(90)·`EVENT_CONTENT_RETENTION_DAYS`(90)·`EVENT_METRIC_RETENTION_DAYS`(90)·
     `BLOB_RETENTION_DAYS`(30).
   - `medi-cron` 은 `medi-back` 과 **같은 blob 위치**를 봐야 한다(compose 매핑 확인).
   - 야간 골든셋 회귀(`quality_regression.py`)도 여기서 돈다 — 배포 커밋·프롬프트·모델이 바뀐 날만, 최소 주 1회.
8. **시크릿 규칙.**
   - `.env`·`.env.docker` 의 **백업 사본(`.env.bak` 등)을 만들지 않는다.** 과거 노출 사고의 원인이었다.
   - `.env*` 는 `chmod 600`, 커밋 금지. 커밋은 경로를 명시해 stage 한다(`git add -A` 금지).
   - 로테이션: `python scripts/rotate_secrets.py`(체크리스트) → 교체 → `--verify`.
   - 기입값 암호화 키(`FILLED_VALUES_ENC_KEY`)는 Fernet urlsafe base64 **44자, 끝 `=` 포함**. 이미 암호화된 행이
     있으면 새 키로 갈아 끼우지 말고 이전 키를 쉼표로 함께 둔다.
   - `/readyz` 는 공개 엔드포인트라 예외 문자열(DSN·내부 주소)을 싣지 않는다 — 이 원칙을 유지할 것.
9. **best-effort `except` 주의.** 배선 오류를 조용히 삼킨다. 드물게 실행되는 분기(메일 발송 등)는 e2e 로 검증하고,
   사용자에게 나가는 기능의 e2e 는 로컬이 아니라 **배포 컨테이너 안에서**(`docker compose exec`) 돌린다.
10. **은퇴한 경로를 되살리지 않는다.** langgraph 런타임·checkpointer·`assistant_id` 트리거는 2026-07-14 은퇴(ADR-0001).

---

## 5. 장애 대응

첫 점검: `docker compose exec medi-back python scripts/check_connection.py` (라우트·CORS·검색 도달성 일괄).

### 5-1. 헬스 엔드포인트

| 엔드포인트 | 인증 | 의미 |
|---|---|---|
| `GET /healthz` | 없음 | liveness. 프로세스가 살아 있으면 항상 200. 배포 대기에 사용 |
| `GET /readyz` | 없음 | readiness. 외부 의존을 병렬 probe(`READYZ_PROBE_TIMEOUT_S`, 기본 4초). critical 하나라도 down 이면 **503 degraded** |
| `GET /load` | 없음 | 부하(원활/혼잡)·점검 메시지·writer 도달 여부 |
| 프런트 `GET /api/health` | 없음 | 프런트 배포 대기용 |

`/readyz` 응답: `{ "status": "ok|degraded", "checks": { <dep>: {status, critical, latency_ms, detail?} }, "single_instance": {...} }`

| check | critical | 다운 시 영향 / 폴백 |
|---|---|---|
| `postgres` | 예 | 인용 원문(/article)·pinned grounding 불가 |
| `search_api` | 예 | 답변에 근거 없음 — 사실상 서비스 정지 |
| `neo4j` | 아니오 | 법령 그래프·즉답만 영향 |
| `pii_ner` | 아니오(경고 알림) | regex 마스킹만 동작 — 이름·주소 미탐. **컴플라이언스 리스크라 조용히 넘기지 말 것** |
| `intent` | 아니오(경고 알림) | 휴리스틱 폴백(규제면 검색 강제 = 안전 기본값) |

- LB 헬스체크를 `/readyz` 로 걸면 critical 다운 노드가 자동으로 빠진다.
- `OPS_ALERT_WEBHOOK_URL`(Slack 등)을 설정하면 critical 다운·가드레일 저하를 자동 통보(`OPS_ALERT_DEDUP_S`, 기본 600초 dedup).
  운영에서는 반드시 설정.

### 5-2. 증상 → 확인 → 조치

| # | 증상 | 확인 | 조치 |
|---|---|---|---|
| 1 | `medi-back` 이 `Restarting`/`Exited` | `docker compose logs --tail=100 medi-back` | 원인별로 아래 항목. 코드 버그면 `git revert <sha>` 후 push(자동 재배포) |
| 2 | 부팅 거부 "다른 인스턴스가 이미 실행 중" | `docker ps -a \| grep medi-back` | 의도된 차단. 남은 옛 컨테이너를 `docker rm -f`. 락은 최대 `SINGLE_INSTANCE_WAIT_S`(20초) 스스로 기다린다 |
| 3 | 부팅 거부 "WEB_CONCURRENCY=N" | `.env.docker`·compose | 키 삭제 또는 1 |
| 4 | 부팅 거부 — 필수 env 누락 / 암호화 키 형식 | 로그 메시지 | `check_config.py` 로 누락 확인, 키 길이(44자·`=`) 확인 후 `up -d --force-recreate` |
| 5 | 답변에 "검색 일시 실패"·인용 0, `/readyz` search_api down | `/search/health`, Tailscale 도달, `RAG_SEARCH_API_URL`·키 | DGX `systemctl status openlaw-search` → 재시작. 의존(임베딩 :8001·리랭커) 확인 |
| 6 | 이름·주소가 마스킹 안 됨 | `/readyz` pii_ner, `:8090/health` | DGX `sudo systemctl restart guardrail-ner`. 코드 변경 재배포는 `backend/guardrail-server/deploy.sh`(멱등) |
| 7 | DGX 전체 무응답 | `ping <DGX_HOST>`, `tailscale status` | Tailscale 재연결·DGX 복구. 길어지면 점검 모드 ON 으로 사용자 안내 |
| 8 | "답변이 안 옴" (LLM) | 로그 `503`/`RateLimitError`, 공급사 상태 페이지 | 폴백 설정 확인, 계정 한도 확인. 양쪽 다 다운이면 점검 모드 |
| 9 | SSE 가 무응답·턴이 시작 안 됨 | `POST /chat` 진입 로그, `/load` | 같은 스레드는 턴 락으로 직렬화되므로 앞 턴 대기가 정상일 수 있음. 막혔으면 `docker compose restart medi-back` — 스레드 상태는 PG 영속이라 대화 유실 없음(진행 중 보고서만 재요청) |
| 10 | 브라우저에 "CORS 오류" | `docker compose logs --tail=120 medi-back \| grep -iA40 traceback` | Starlette 는 unhandled 500 에 CORS 헤더를 안 붙인다 → 실제로는 500 인 경우가 많다. `/healthz` 200 인데 `/chat` 만 죽으면 지연 import 모듈 누락(.dockerignore) 의심. 진짜 CORS 면 `API_CORS_ORIGINS` 에 origin 추가(정확 매칭·끝 슬래시 없음) |
| 11 | 401 / 429 | DevTools Network, 429 본문의 `scope` | 401: `NEXTAUTH_SECRET` 양쪽 일치 확인. 429 quota: 관리자가 `/admin/users/{id}` 로 한도 조정. 429 rate: 잠시 후 재시도 |
| 12 | Postgres 연결 실패·디스크 참 | `docker compose logs postgres`, `pg_isready -U medi -d medi`, `df -h` | 비밀번호 불일치 확인, 오래된 이미지·로그 정리. 손상 시 백업 복구(maintenance 창에서) |
| 13 | 배포가 `Queued / Waiting for a runner` 에서 멈추고 취소도 안 됨 | runner 서비스 상태, `_diag/Runner_*.log` 의 broker 연결 오류 | runner 서비스 재시작. 이미 굳은 phantom run 은 취소 불가 — 워크플로 `concurrency.group` 이름을 바꿔 우회하고 phantom 은 GitHub GC 에 맡긴다 |
| 14 | 보고서 이메일이 안 옴 | `SMTP_HOST` 설정 여부 | 미설정이면 stub. 설정 후 `scripts/send_test_email.py <주소> --with-attachment` 로 도착 확인 |
| 15 | LLM 비용 급증 | events 테이블에서 사용자별 24시간 토큰 합계 | 해당 사용자 한도 즉시 하향(`daily_token_limit_override=0` 은 사실상 차단), 필요 시 `DEFAULT_DAILY_TOKEN_LIMIT` 하향 후 재기동 |

### 5-3. 긴급 정지

- 권장: 점검 모드(3-4) — 관리자는 계속 접근해 확인·해제할 수 있다.
- 전면 차단: `docker compose stop medi-back` 또는 프록시에서 503. 복구는 `start` + 프록시 reload.

### 5-4. 정기 점검

- 매일: `df -h`, `docker compose logs --since=24h medi-back | grep ERROR`, `medi-cron`·`medi-backup` 로그
- 매주: 의존성 보안 업데이트 확인(langchain-core·langchain-anthropic·jwt 등)
- 분기: 백업 복구 리허설, 시크릿 로테이션 검토
- TLS: Let's Encrypt 자동 갱신 cron(`certbot renew --quiet && systemctl reload nginx`)

---

## 6. 확장 임계점 요약

**첫 병목은 앱 프로세스가 아니라 DGX 단일 GPU 다.** 리랭커·NER·의도 분류·보고서 writer 가 한 GPU 를 공유한다.

| 자원 | 실제 상한 |
|---|---|
| DGX GPU | 동시 요청 한 자릿수. 검색 단건 웜 ~0.8초, writer 가동 중 경합 시 ~3.4초 스파이크 |
| 검색 동시성 | `SEARCH_MAX_CONCURRENCY=2` — 초과분은 대기, `/load` 에 '혼잡' 표시 |
| 보고서 writer | `REPORT_MAX_CONCURRENCY=1` — 채팅 레인 우선. writer 는 대화 직후 `REPORT_YIELD_HOLD_S` 동안 양보 |
| 백엔드 프로세스 | 워커 1개 고정(4장 1번) |

설계 목표 부하는 **단일 VM·동시 사용자 한 자릿수**. 확장 순서:

1. **GPU/서빙 분리** — writer 를 채팅용 GPU 에서 떼고, 리랭커 배칭(검색 서버 쪽 과제).
   writer 컨테이너에는 점유 억제 플래그 권장: `--max-num-seqs 1 --max-num-batched-tokens 2048 --gpu-memory-utilization 0.5`.
2. **Redis** — 백엔드 인스턴스를 2개 이상 띄워야 할 때. 프로세스 로컬 상태(백프레셔·quota·rate limit·턴 락)를
   옮기지 않으면 single-instance 락이 부팅을 막으므로 **수평 확장의 전제 조건**이다.
3. **작업 큐**(Celery+Redis 또는 Cloud Tasks) — 백그라운드 작업이 보고서 외로 다양해지거나 보고서를 별도 워커로 분리할 때.
4. **이벤트 버스**(Pub/Sub 또는 Kafka) — 일 events 100만 이상, 실시간 알림·다중 분석 consumer 가 필요할 때.

판단 신호는 사용자 수가 아니라 `/load` 대기 시간, `/readyz` 지연, 체감 혼잡이다.
DGX 이중화는 현 단계에서 하지 않는다(비용). 대신 "죽으면 보이고, 부분 장애는 대화를 막지 않는다"를 보장한다(5-1).

---

## 7. 기관 지침 스킬(IRB/DRB) 번들

특정 기관의 연구 심의(IRB/DRB) 내부 지침을 채팅에서 안내하는 선택 기능이다.

- **지침 번들(.md 자산)은 `backend/src/skills/medireg_irb_drb/`** — 제휴 기관 내부 지침이라 관련자 외
  재배포 금지. `SKILL_BUNDLE_DIR=src/skills/medireg_irb_drb` 로 가리킨다. 번들 내용은 코드가 파싱하지 않는 자산으로 취급하며, 원문을 응답에 그대로 노출하지 않는다.
- 로더·연동 코드는 `backend/src/skills/{loader,chat_integration}.py` 에 격리돼 있다. 이 모듈과 채팅 루프의 가드 분기를
  걷어내면 기능이 흔적 없이 제거된다.

3단 스위치:

| 단계 | 스위치 | 동작 |
|---|---|---|
| 1. 서비스 | `SKILL_BUNDLE_DIR` | **미설정 = 기능 off.** 카탈로그·도구·강제 로직이 전혀 붙지 않고 기존 채팅과 완전히 동일 |
| 2. 대상 | `SKILL_WHITELIST_EMAILS` | 노출 대상(이메일 또는 `@도메인`, 콤마). 미설정 = 전면 허용. 단일 기관 번들이면 해당 기관 도메인으로 잠근다 |
| 3. 스레드 | 자동 판정 | 이번 턴 질의가 IRB/DRB 관련이거나(프리게이트), 스레드 히스토리에 스킬 로드 흔적이 있으면(스티키) on. 도구 강제는 이번 턴 질의가 해당될 때만 |

관련 옵션:
- `SKILL_LOCAL_MODEL=1` — 스킬 턴을 온프레미스 vLLM 으로 라우팅(상용 모델에 기관 지침을 보내지 않음). vLLM 이
  tool-calling 을 지원해야 한다(`--enable-auto-tool-choice --tool-call-parser hermes`). 로컬 다운 시 상용 폴백 없이 안내 후 종료.
- `SKILL_LOCAL_BASE_URL`(미설정 시 writer 주소 공유), `SKILL_LOCAL_MAX_TOKENS`(기본 8192 — 짧으면 판정 블록이 잘린다).
- 운영에서 켤 때는 `.env.docker` 에 값을 넣고, 번들 디렉터리를 컨테이너에 마운트하고, compose 매핑을 확인한 뒤
  `up -d --force-recreate medi-back`. 번들 경로가 이미지 빌드 컨텍스트에 있다면 `.dockerignore` 에 걸리지 않는지도 확인한다.
