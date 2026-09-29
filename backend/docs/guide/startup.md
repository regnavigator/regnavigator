# 재부팅 후 기동 체크리스트

재부팅 뒤 medi-back 을 바로 띄우는 순서. 복붙용. (상세 사고대응은 [`runbook.md`](../ops/runbook.md).)

구성 요약: **medi-back**(로컬, uvicorn `src.api:app`) → **DGX**(검색·가드레일·writer, Tailscale
`192.0.2.10`) → **GCP DB**(공인 IP, 항상 up). 대부분 DGX 서비스는 systemd/docker 로
**부팅 자동시작**이라, 로컬만 재부팅했으면 아래 1·3·4 만 하면 된다.

---

## 0. Tailscale 연결 (필수 — 이거 없으면 검색·가드레일 전부 실패)

DGX 는 Tailscale 내부망(`192.0.2.10`)으로만 닿는다. 로컬에서:
```powershell
tailscale status            # 연결 확인. 안 되면 로그인:
tailscale up                # 브라우저 인증(만료 시 재인증 필요)
ping 192.0.2.10           # 응답 오면 OK
```

## 1. medi-back 기동 (로컬 dev)

```powershell
cd <workspace>\medi-back
.\venv\Scripts\Activate.ps1
# ⚠️ PYTHONUTF8 필수 — .env 의 한글 주석을 Windows 기본(cp949)이 못 읽어 기동 실패
$env:PYTHONUTF8 = "1"
python -c "from dotenv import load_dotenv; load_dotenv(); import uvicorn; uvicorn.run('src.api:app', port=2024)"
#  → http://127.0.0.1:2024   (기동 ~3초)
```
- `UnicodeDecodeError: 'cp949' codec can't decode` → `PYTHONUTF8=1` 누락.
- 멀티 워커 금지(`--workers 1` 상당의 단일 프로세스) — 검색 백프레셔·보고서 큐·턴 락·LLM RPS 캡이 전부 프로세스 로컬.
- ~~`langgraph dev` + `--no-reload --allow-blocking` + `.langgraph_api` stale 삭제~~ — **2026-07-14 은퇴**(ADR-0001 Phase 5 컷오버). 관련 증상(watchfiles loop·blockbuster 500·SSE heartbeat 좀비)도 함께 소멸.

## 2. DGX 서비스 확인 (DGX 도 재부팅했을 때만)

systemd 3종은 `enabled`(부팅 자동). 안 떠 있으면 수동 기동:
```bash
ssh <user>@192.0.2.10
systemctl is-active openlaw-search guardrail-ner guardrail-intent
#  하나라도 inactive 면:
sudo systemctl start openlaw-search guardrail-ner guardrail-intent
# vLLM(writer :8000 / KURE :8001)은 docker — 확인:
docker ps | grep -iE "vllm|qwen|gemma|kure"
#  안 떠 있으면 해당 컨테이너 start(openlaw-search 쪽 런처)
```

> **writer vLLM 기동 플래그 권장(챗 우선 정책, 2026-07-24)** — writer 는 초장기
> 허용이고 챗(리랭커·임베딩과 GPU 공유) 즉각성이 우선이므로, writer 컨테이너에
> 점유 억제 플래그를 권장:
> `--max-num-seqs 1 --max-num-batched-tokens 2048 --gpu-memory-utilization 0.5`
> (동시 시퀀스 1·decode 배치 축소·KV 캐시 상한 — 생성은 느려지지만 검색 지연
> 스파이크가 줄어든다. medi-back 은 REPORT_WRITER_TIMEOUT_S=1800·stale 3h 로
> 장기화를 이미 수용.)
> 가드레일 재배포가 필요하면(코드 변경): `guardrail-server/deploy.sh` ([README](../../guardrail-server/README.md)).

## 3. 헬스 체크 (전부 200 이어야 정상)

`$KEY` = `.env` 의 `RAG_SEARCH_API_KEY`(=INSTANCE_API_KEY).
```powershell
$KEY = (Select-String '^RAG_SEARCH_API_KEY=' .env).Line.Split('=',2)[1]
curl.exe -s -H "X-API-Key: $KEY" http://192.0.2.10:8080/search/health   # 검색
curl.exe -s -H "X-API-Key: $KEY" http://192.0.2.10:8090/health          # PII NER
curl.exe -s -H "X-API-Key: $KEY" http://192.0.2.10:8091/health          # 의도분류
curl.exe -s http://192.0.2.10:8000/v1/models                            # 보고서 writer vLLM(서빙 모델 확인)
curl.exe -s http://127.0.0.1:2024/readyz                                   # medi-back(의존성)
curl.exe -s http://127.0.0.1:2024/load                                     # 부하(원활/혼잡)
```

## 4. 스모크 테스트 (한 턴 실제 동작 확인)

```powershell
# fast 한 턴 (신경로 벤치 — chat_loop 직접)
.\venv\Scripts\python.exe scripts\bench_chatloop.py "의료기기 광고 사전심의 절차 알려줘"

# HTTP 경로까지 확인하려면 (dev 는 JWT 미설정 시 dev identity)
curl.exe -s -N -X POST http://127.0.0.1:2024/chat -H "Content-Type: application/json" `
  -d '{\"message\": \"의료기기 광고 사전심의 절차 알려줘\"}'      # SSE: meta→tool_progress→token→done
curl.exe -s http://127.0.0.1:2024/chat/threads                     # 방금 thread 가 목록에 보이면 영속 OK
```
기대: 검색(qdrant_search) 1회 + 인용 달린 한국어 답변. (첫 검색은 리랭커 콜드로 느릴 수
있으나 keepalive 가 곧 웜업 — `SEARCH_KEEPALIVE_S`.)

---

## 자주 걸리는 것

| 증상 | 원인 → 조치 |
|---|---|
| 기동 즉시 `UnicodeDecodeError: 'cp949'` | **`PYTHONUTF8=1` 누락**(.env 한글 주석) → `$env:PYTHONUTF8="1"` |
| `/readyz` = degraded, postgres down | **운영 PG DSN(REPORTS/CHECKPOINT) 미설정** — dev 는 SQLite 폴백이라 정상. psycopg 는 설치됨(2026-07-10) → `/article`·`/annex`(별표) openlaw PG 조회 동작. 만약 psycopg 가 없으면(새 venv) `pip install "psycopg[binary,pool]>=3.2"` — 없을 땐 citation 본문이 "불러오지 못했다"로 조용히 실패한다 |
| 검색 "일시 실패"/인용 0 | Tailscale 끊김 or DGX 검색서버 down → 0·2 확인 |
| 대화 이력·thread 목록이 안 보임 | thread 상태는 `threads_repo` — dev `./medi_reports.db`(SQLite)·prod `REPORTS_PG_DSN`. 파일/DSN 확인. (~~`.langgraph_api` stale·blockbuster 500~~ 은 2026-07-14 은퇴로 소멸) |
| 이름·주소 마스킹 안 됨 | NER(:8090) down → regex 만 동작(정상 폴백), 필요시 서비스 start |
| 보고서 이메일 안 옴 | `SMTP_HOST` 미설정(stub) — 발송하려면 `.env` SMTP_* 설정 |

## 선택 — docker 운영 모드 (dev 아닌 컨테이너)

```bash
docker compose --env-file .env.docker up -d --build   # → :6000
```
상세: [`deployment_docker.md`](../ops/deployment_docker.md).
