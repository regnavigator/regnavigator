"""medi-back API — 보고서 메타 조회 + .md 다운로드 + 가이드 질문 + thread 자동 제목.

langgraph dev에 `http.app`(`langgraph.json`)으로 마운트되어 **port 2024**에서 함께 서빙.
별도 sidecar 프로세스 불필요 — 단일 origin·단일 CORS·단일 인증.

이 파일은 `app` 생성·미들웨어 스택·공개 라우트(/healthz, /suggestions)만 보유하고,
도메인별 엔드포인트는 `src/routes/` 의 APIRouter 를 `include_router` 로 마운트한다.

routes (모두 langgraph 기본 라우트와 같은 origin):
- GET  /healthz                                — 상태 (인증 X)            [api.py]
- GET  /suggestions                            — 가이드 질문 (인증 X)     [api.py]
- GET  /me/usage                               — 본인 토큰 사용량         [routes/reports]
- GET  /threads/{thread_id}/reports            — 메타 목록                [routes/reports]
- GET  /reports/{report_id}                    — 메타 1건 + presigned URL [routes/reports]
- GET  /reports/{report_id}/download           — .md 본문 attachment      [routes/reports]
- POST /threads/{thread_id}/auto-title         — 첫 user message → 제목   [routes/auto_title]
- POST /threads/{tid}/messages/{mid}/feedback  — ai 메시지 평가           [routes/feedback]
- POST /reports/{report_id}/feedback           — 보고서 평가              [routes/feedback]
- POST /feedback/general                       — @feedback 자유 코멘트    [routes/feedback]
- GET  /admin/feedback                         — admin: 누적 코멘트·평가  [routes/feedback]
- GET  /annex                                  — 별표·서식 본문           [routes/articles]
- GET  /annex/list                             — 법령 내 별표 목록        [routes/articles]
- GET  /article                                — 법령 조문 본문 + 메타    [routes/articles]
- GET  /law/{lawId}/articles                   — 법령에 속한 조문 목록    [routes/articles]
- GET  /admin/users                            — admin: 사용자 목록       [routes/admin]
- PATCH /admin/users/{user_id}                 — admin: 한도·is_admin     [routes/admin]
- GET  /admin/users/{user_id}/usage            — admin: 사용량 상세       [routes/admin]

보안 (production): 환경변수 `API_TOKEN` 설정 시 보고서 라우트에 `Authorization: Bearer <token>` 검사.
가이드(`/suggestions`)와 헬스체크는 인증 없이 공개 — 첫 화면용.

빌드: langgraph dev / langgraph up 가 자동으로 이 파일을 import해 라우트 마운트.
독립 디버깅이 필요하면 `uvicorn src.api:app --port 2025` 로 따로 띄울 수 있음 (운영 흐름엔 불필요).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.middleware import (
    AuthMiddleware,
    QuotaMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from src.routes import (
    admin_reviews_router,
    admin_newsletters_router,
    admin_router,
    admin_usage_router,
    announcements_router,
    monitor_router,
    articles_router,
    beta_router,
    bookmarks_router,
    chat_router,
    feedback_router,
    files_router,
    health_router,
    law_graph_router,
    notices_router,
    privacy_router,
    reports_router,
)

# 테스트 하위호환 re-export — tests/test_law_go_kr_url.py 가 `from src.api import
# _build_law_go_kr_url` 로 직접 참조. 실 구현은 routes/articles.py.
from src.routes.articles import _build_law_go_kr_url  # noqa: F401

_log = logging.getLogger(__name__)


_SUGGESTIONS_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "data" / "suggested_questions.json"
)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """부팅 설정 검증 — prod 필수 env(NEXTAUTH_SECRET·ANTHROPIC_API_KEY 등) 누락 시
    경고. `STRICT_CONFIG=1` 이면 부팅 차단(fail-fast — 오설정으로 조용히 뜨는 사고 방지).
    """
    from src.config import missing_prod_required

    missing = missing_prod_required()
    if missing:
        msg = f"[config] prod 필수 env 미설정: {missing}"
        if (os.getenv("STRICT_CONFIG") or "").strip() == "1":
            raise RuntimeError(msg + " — STRICT_CONFIG=1 로 부팅 차단")
        _log.warning("%s (STRICT_CONFIG=1 로 부팅 차단 가능, check_config.py 로 점검)", msg)
    else:
        _log.info("[config] prod 필수 env 점검 OK")

    # 서류 기입값 암호화 키 — 첫 암호화까지 지연 생성이라 잘못된 키가 부팅·/readyz 를
    # 통과하고 서식 작성만 500 을 냈다(2026-09-21, 3일간 전건 실패). 여기서 막아
    # 배포 healthz 단계에서 실패로 드러나게 한다. 키는 배포 때만 바뀌므로 fail-fast 가 맞다.
    from src.persistence import field_crypto

    _log.info("[config] filled_values 암호화 키: %s", field_crypto.validate_key())

    # 단일 인스턴스 강제 — 프로세스 로컬 동시성 제어(턴 락·RPS 캡·검색 백프레셔·
    # 보고서 큐)가 2번째 프로세스에서 통째로 무력화되는 걸 **런타임에** 막는다.
    # 지금까지는 Dockerfile CMD 와 문서뿐이라 --scale·WEB_CONCURRENCY 로 뚫렸고,
    # 뚫려도 아무 신호가 없었다(2026-08-04 감사 C-4).
    from src import single_instance

    single_instance.assert_worker_count()
    single_instance.acquire()

    # 레거시 서류 종별 교정(2026-08-27, 일회성·멱등) — kind="doc" 분리 이전에
    # 생성된 서류가 kind="final" 로 남아 보고서 목록에 "종합 보고서"로 떴다
    # ("서식은 보고서가 아닌데 왜 보고서 목록에 들어가냐" — 배포 후에도 과거
    # 데이터가 남는 게 2차 원인). 부팅마다 돌지만 교정 대상이 없으면 no-op.
    try:
        from src.persistence import get_report_runs_repo, get_reports_repo

        _reports = get_reports_repo()
        _fixed = 0
        for _rid in get_report_runs_repo().all_draft_report_ids():
            _m = _reports.get(_rid)
            if _m and _m.kind == "final":
                _reports.set_kind(_rid, "doc")
                _fixed += 1
        if _fixed:
            _log.info("레거시 서류 종별 교정: final→doc %d건", _fixed)
    except Exception as e:  # noqa: BLE001 — 교정 실패가 부팅을 막으면 안 됨
        _log.warning("서류 종별 교정 스킵: %s", e)

    # 운영진 라벨 → 실사용자 이관(2026-09-22 관리자·운영진 통합, 멱등 — 관리자 지정은 운영자가 직접)
    try:
        from src.account_class import migrate_staff_labels

        _moved = migrate_staff_labels()
        if _moved:
            _log.info("운영진 라벨 → 실사용자 이관: %d명", _moved)
    except Exception as e:  # noqa: BLE001 — 이관 실패가 부팅을 막으면 안 됨
        _log.warning("운영진 라벨 이관 스킵: %s", e)

    # 재시작으로 죽은 보고서 잡 복원 — 배포/크래시 후 running 잔재를 같은
    # 멱등키로 재기동(진행 중 보고서 조용한 증발 방지, 2026-07-24).
    try:
        from src.report_runner import resume_orphan_runs
        resume_orphan_runs()
    except Exception as e:  # noqa: BLE001 — 복원 실패가 부팅을 막으면 안 됨
        _log.warning("orphan report 복원 스킵: %s", e)

    # 리랭커 keepalive — idle 후 첫 검색이 콜드(~7.5s) 맞는 걸 방지. 주기 웜핑.
    ka_task = None
    try:
        interval = float((os.getenv("SEARCH_KEEPALIVE_S") or "").strip() or "240")
    except ValueError:
        interval = 240.0
    if interval > 0:
        ka_task = asyncio.create_task(_reranker_keepalive(interval))

    # 프롬프트 캐시 웜퍼 — stable 프리픽스(tools+supervisor ≈2만 토큰)를 1h TTL
    # 캐시에 상주시켜 1차 LLM 콜 콜드 처리(6~7s)를 제거(2026-08-14 실측 기반).
    # 리랭커 keepalive 와 같은 패턴. 0=끔. 회당 비용 ≈$0.002(캐시 히트 시).
    warm_task = None
    try:
        warm_interval = float(
            (os.getenv("PROMPT_WARM_INTERVAL_S") or "").strip() or "2700")
    except ValueError:
        warm_interval = 2700.0
    if warm_interval > 0 and (os.getenv("CHAT_PROMPT_CACHE_DISABLE") or "") != "1":
        warm_task = asyncio.create_task(_prompt_cache_warmer(warm_interval))

    # 예약 공지 발송 루프 — 워커 1개 전제(CLAUDE.md §7). 여러 프로세스가 돌면
    # 같은 공지를 중복 발송할 수 있다.
    try:
        notice_interval = float((os.getenv("NOTICE_SCHEDULER_INTERVAL_S") or "").strip() or "60")
    except ValueError:
        notice_interval = 60.0
    notice_task = (asyncio.create_task(_scheduled_notice_loop(notice_interval))
                   if notice_interval > 0 else None)
    # 주간 이용 집계 스냅샷(2026-09-21) — 끝난 주가 저장돼 있지 않으면 만든다. 이벤트·
    # 대화는 90일 뒤 정리되므로 제때 떠 두지 않으면 장기 추이가 사라진다. 0=끔.
    try:
        usage_interval = float(
            (os.getenv("USAGE_WEEKLY_SNAPSHOT_INTERVAL_S") or "").strip() or "21600")
    except ValueError:
        usage_interval = 21600.0
    usage_task = (asyncio.create_task(_usage_weekly_loop(usage_interval))
                  if usage_interval > 0 else None)
    # 주간 이용 보고서 메일(2026-09-21) — 월요일 WEEKLY_REPORT_SEND_HOUR(KST) 이후 첫 점검에
    # 직전 주를 1회 발송(보낸 주는 app_settings 기록 → 재시작 중복 없음). 0=끔.
    try:
        report_interval = float(
            (os.getenv("WEEKLY_REPORT_CHECK_INTERVAL_S") or "").strip() or "900")
    except ValueError:
        report_interval = 900.0
    report_task = (asyncio.create_task(_weekly_report_loop(report_interval))
                   if report_interval > 0 else None)
    try:
        monitor_interval = float(
            (os.getenv("MONITOR_REPORT_CHECK_INTERVAL_S") or "").strip() or "900")
    except ValueError:
        monitor_interval = 900.0
    monitor_task = (asyncio.create_task(_monitor_report_loop(monitor_interval))
                    if monitor_interval > 0 else None)
    # 스킬 로컬 모델 워밍(2026-09-15) — 첫 사용자 턴이 tool 지원 확인 비용을 내지
    # 않게 부팅 직후 백그라운드로 한 번 확인(성공은 KV 에 남아 재시작에도 유지).
    try:
        from src import skill_local as _skill_local

        if _skill_local.enabled():
            asyncio.get_running_loop().run_in_executor(None, _skill_local.warm_up)
    except Exception:  # noqa: BLE001 — 워밍 실패가 부팅을 막으면 안 됨
        _log.debug("skill_local warm-up 스케줄 실패", exc_info=True)

    try:
        yield
    finally:
        tasks = [t for t in (ka_task, warm_task, notice_task, usage_task, report_task,
                             monitor_task)
                 if t is not None]
        for t in tasks:
            t.cancel()
        # cancel 만 하고 끝내면 "Task was destroyed but it is pending" 이 뜬다 —
        # 취소가 실제로 반영될 때까지 수거.
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # 락 해제 — 배포 시 새 컨테이너가 유예 대기 없이 바로 뜬다.
        single_instance.release()
        # 외부 커넥션 정리 — 안 닫으면 재배포마다 PG/Neo4j 에 좀비 세션이 쌓인다.
        from src.shutdown import close_all
        close_all()


async def _scheduled_notice_loop(interval: float) -> None:
    """예정 시각이 지난 예약 공지를 발송(best-effort, 실패는 로그).

    ⚠️ 예외를 삼키되 **로그는 남긴다** — 조용히 죽으면 예약이 영영 안 나간다
    (CLAUDE.md 주의 6). SMTP·DB 는 블로킹이라 to_thread 로.
    """
    from src.notices import run_due

    while True:
        await asyncio.sleep(interval)
        try:
            fired = await asyncio.to_thread(run_due)
            if fired:
                _log.info("[notice] 예약 공지 %d건 발송", len(fired))
        except Exception:  # noqa: BLE001 — 한 주기 실패가 루프를 끝내면 안 됨
            _log.exception("[notice] 예약 공지 처리 실패 — 다음 주기 재시도")


async def _usage_weekly_loop(interval: float) -> None:
    """직전 2주 스냅샷 보장. 부팅 직후 부하를 피해 1분 뒤 첫 실행, 이후 interval 주기.
    실패는 로그만 — 관리자 화면 조회 시에도 없는 주는 계산·저장된다(이중 안전망)."""
    from src.usage_weekly import ensure_recent_snapshots

    await asyncio.sleep(min(60.0, interval))
    while True:
        try:
            made = await asyncio.to_thread(ensure_recent_snapshots, 2)
            if made:
                _log.info("[usage] 주간 스냅샷 %d건 저장", made)
        except Exception:  # noqa: BLE001 — 한 주기 실패가 루프를 끝내면 안 됨
            _log.exception("[usage] 주간 스냅샷 실패 — 다음 주기 재시도")
        await asyncio.sleep(interval)


async def _weekly_report_loop(interval: float) -> None:
    """주간 보고서 발송 점검. 부팅 직후 2분 뒤 첫 점검(배포 직후 몰림 회피).
    ⚠️ 예외는 삼키되 로그는 남긴다 — 조용히 죽으면 보고서가 영영 안 온다(CLAUDE.md 주의 6)."""
    from src.weekly_report import run_due

    await asyncio.sleep(min(120.0, interval))
    while True:
        try:
            await asyncio.to_thread(run_due)
        except Exception:  # noqa: BLE001 — 한 주기 실패가 루프를 끝내면 안 됨
            _log.exception("[weekly_report] 점검 실패 — 다음 주기 재시도")
        await asyncio.sleep(interval)


async def _monitor_report_loop(interval: float) -> None:
    """고객사 규제 모니터링 리포트 발송 점검. 부팅 직후 3분 뒤 첫 점검.
    ⚠️ 예외는 삼키되 로그는 남긴다 — 조용히 죽으면 고객사 리포트가 영영 안 간다."""
    from src.monitor_report import run_due

    await asyncio.sleep(min(180.0, interval))
    while True:
        try:
            await asyncio.to_thread(run_due)
        except Exception:  # noqa: BLE001 — 한 주기 실패가 루프를 끝내면 안 됨
            _log.exception("[monitor_report] 점검 실패 — 다음 주기 재시도")
        await asyncio.sleep(interval)


async def _reranker_keepalive(interval: float) -> None:
    """주기적으로 최소 검색을 돌려 검색서버 리랭커를 웜 유지(best-effort)."""
    from src.retrieval.search_api_client import keepalive

    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(keepalive)
        except Exception:  # noqa: BLE001 — keepalive 실패는 무시(다음 주기 재시도)
            pass


async def _prompt_cache_warmer(interval: float) -> None:
    """주기적으로 Anthropic 프롬프트 캐시(stable 프리픽스)를 웜 유지(best-effort).

    부팅 직후 1회 즉시 웜핑(첫 사용자 보호) 후 interval 주기. LLM 호출은
    블로킹이라 to_thread 로. 실패는 warm_prompt_cache 가 로그 후 False.
    """
    from src.chat_loop import warm_prompt_cache

    first = True
    while True:
        if not first:
            await asyncio.sleep(interval)
        first = False
        try:
            await asyncio.to_thread(warm_prompt_cache)
        except Exception:  # noqa: BLE001 — 웜핑 실패는 무시(다음 주기 재시도)
            pass


app = FastAPI(title="medi-back reports API", version="0.2.0", lifespan=_lifespan)


# CORS — 프런트(localhost:3000 등) 브라우저 호출 허용.
# 운영에선 `API_CORS_ORIGINS` env (콤마 구분)으로 한정.
_cors_origins = [
    o.strip()
    for o in (
        os.getenv(
            "API_CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173",
        )
    ).split(",")
    if o.strip()
]
# Starlette 미들웨어 stack은 마지막 add_middleware가 OUTERMOST (request 먼저 받음,
# response 마지막 처리). 따라서 *안쪽 → 바깥쪽* 순서로 등록:
#   request : 클라 → CORS → Auth → RateLimit → Quota → SecurityHeaders → app
#   response: app → SecurityHeaders → Quota → RateLimit → Auth → CORS → 클라
# 핵심 의존:
#  - Auth 가 Quota/RateLimit 보다 *바깥* — request.state.user_id 를 먼저 박아야
#    Quota 가 누구 한도인지 알 수 있음 (안 그러면 quota check 스킵돼 404 새어나감).
#  - CORS 가 *가장 바깥* — Auth 401·Quota 429 같은 미들웨어 에러 응답에도 CORS
#    헤더 부착돼야 브라우저 CORS 위반 안 뜸.

# 보안 헤더 — 모든 응답에 X-Content-Type-Options 등 부착.
app.add_middleware(SecurityHeadersMiddleware)

# 토큰 한도 — LLM 호출 라우트 진입 시 누적 사용량 vs limit 비교 (user_id 필요).
app.add_middleware(QuotaMiddleware)

# Rate limit — per-IP + per-user 분/시간 단위.
app.add_middleware(RateLimitMiddleware)

# NextAuth JWT 검증 — request.state.user_id / user_email / is_admin 박음.
# Quota/RateLimit 위에 등록해서 *먼저 실행*되도록.
# 공개 라우트(/healthz, /suggestions, /docs)는 자동 우회. dev 모드 bypass.
app.add_middleware(AuthMiddleware)

# CORS — *가장 마지막에 등록 = outermost*. Auth 401·Quota 429 등 에러 응답에도
# CORS 헤더가 붙어야 브라우저 CORS 위반 안 뜸.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/suggestions")
def get_suggestions():
    """첫 화면용 환영 메시지 + 카테고리별 가이드 질문.

    프런트는 사용자가 빈 입력으로 들어오거나 인사("ㅎㅇ", "안녕") 같은 짧은 메시지를 보낼 때
    이 엔드포인트의 questions를 칩·버튼 형태로 노출한다.

    수정은 `data/suggested_questions.json` 파일만 변경하면 즉시 반영.
    """
    try:
        with _SUGGESTIONS_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="suggestions file missing")
    except json.JSONDecodeError as e:
        # 파싱 에러 문자열엔 파일 내용 일부가 실린다 — 상세는 로그로만.
        logging.getLogger(__name__).error("suggestions parse error: %s", e)
        raise HTTPException(status_code=500, detail="suggestions unavailable")


# 도메인별 라우터 마운트 — 미들웨어는 app 레벨에 붙어 모든 라우터에 동일 적용.
app.include_router(health_router)   # /readyz (공개 — LB/모니터용)
app.include_router(reports_router)
app.include_router(admin_usage_router)  # /admin/stats/weekly — 주간 이용 집계·저장(2026-09-21)
app.include_router(admin_router)
app.include_router(admin_reviews_router)  # /admin/review-queue · /admin/reviews — 답변 검수
app.include_router(admin_newsletters_router)  # /admin/newsletters — 뉴스레터 작성·발송·이력(2026-09-22)
app.include_router(feedback_router)
app.include_router(bookmarks_router)  # /bookmarks — 개인 근거 라이브러리
app.include_router(articles_router)
app.include_router(law_graph_router)
app.include_router(privacy_router)  # /me/consent · /me/data · /me/erase
app.include_router(chat_router)     # POST /chat — 자체 SSE 루프 (ADR-0001 Phase 1)
app.include_router(files_router)    # POST /files/extract — 채팅 첨부 텍스트 추출
app.include_router(beta_router)     # POST /beta/check — 가입 화이트리스트 확인 (공개)
app.include_router(monitor_router)  # /monitor/targets — 고객사 규제 모니터링
app.include_router(announcements_router)  # /announcements — 패치노트(최초 접속 팝업)
app.include_router(notices_router)  # /me/notices · /admin/notices — 사용자별 앱 내 알림(2026-09-15)
