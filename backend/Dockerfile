# medi-back — self-hosted production image (GCP VM에 docker compose로 배포)
#
# 빌드:
#   docker build -t medi-back:latest .
# 실행 (보통 docker-compose로 호출):
#   docker run --rm -p 6000:8000 --env-file .env.docker medi-back:latest

# ── kordoc 빌드 스테이지 — 원본 서식(HWP/HWPX) 양식 채우기 (MIT, npm) ──
# ⚠️ `--omit=optional` 필수: optional deps(onnxruntime 211MB·pdfjs·sharp·
#    huggingface)는 PDF/OCR 전용이라 HWP/HWPX 기입에 불필요.
#    붙이면 1.4GB, 빼면 **43MB** — 실측(2026-08-25). `-g` 설치는 omit 이
#    무시되므로 전용 prefix 에 local install 한다.
# 버전 고정(^ 금지) — 06_parser 규약과 동일, 미검증 버전 유입 차단.
FROM node:20-slim AS kordoc-build
RUN mkdir -p /opt/kordoc && cd /opt/kordoc \
    && npm init -y > /dev/null \
    && npm install kordoc@4.2.7 --omit=optional --omit=dev --no-audit --no-fund \
    && rm -rf /root/.npm

FROM python:3.12-slim AS base

# 시스템 의존 (nodejs = kordoc 런타임)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        build-essential \
        nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY --from=kordoc-build /opt/kordoc /opt/kordoc
ENV KORDOC_CLI=/opt/kordoc/node_modules/kordoc/dist/cli.js

# Python 환경
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 의존만 먼저 설치 — layer 캐시 활용
# NOTE (2026-05-14 다이어트): [local-fallback] (sentence-transformers/bm25s) 는 일부러 안 깖.
# 원격 EMBEDDING_API_URL + USE_QDRANT_HYBRID=1 경로라 폴백 모듈 미설치여도 동작.
# 폴백 강제가 필요해지면 다음 줄을 ".[prod,local-fallback]" 으로 바꾸면 됨 (~1.5GB ↑).
COPY pyproject.toml ./
RUN pip install ".[prod]"

# 소스 복사 — data/는 image에 안 들어감 (.dockerignore + runtime named volume).
# blobs 는 named volume(medi_blob_data). thin-client 라 로컬 ML 모델 캐시 없음.
COPY src/ ./src/
COPY db/ ./db/
COPY scripts/ ./scripts/
# 약관·개인정보처리방침 정본(런타임 /legal/{doc} 서빙) — 이미지에 포함 필수.
COPY docs/legal/ ./docs/legal/
# 관리자 [운영 매뉴얼] 탭이 런타임에 읽는다(GET /admin/ops-manual).
COPY docs/product/ops_feature_manual.md ./docs/product/ops_feature_manual.md
# 첫 화면 가이드 질문 — /suggestions 가 런타임에 읽는다(.dockerignore 예외와 짝).
COPY data/suggested_questions.json ./data/suggested_questions.json

# 영속 디렉터리 — 컨테이너 시작 시 mount 지점 준비.
# (ADR-0001 Phase 5: langgraph dev 은퇴 — .langgraph_api/entrypoint 불요)
RUN mkdir -p /app/data/blobs

# .env 한글 주석을 기본 인코딩이 못 읽어 기동 실패하는 것 방지(startup.md 참조).
# 배포 식별(2026-09-15) — deploy.yml 이 넘기는 빌드 인자. /admin/build 가 노출.
ARG GIT_SHA=unknown
ARG BUILD_TIME=
ENV APP_GIT_SHA=$GIT_SHA APP_BUILD_TIME=$BUILD_TIME
ENV PYTHONUTF8=1

EXPOSE 8000

# 헬스체크 — /healthz는 인증 X 공개 라우트.
# 여유 상향: warmup(임베더 등 ~50s+) 동안 false-fail 방지(start-period 180s),
# 무거운 deep 중 잠깐 느려도 unhealthy 안 되게 timeout/retries 완화.
# (plain compose는 unhealthy로 재시작 안 함 — 모니터링/depends_on 신호 정확화 목적)
HEALTHCHECK --interval=60s --timeout=10s --start-period=180s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

# entry — 순수 uvicorn (ADR-0001 Phase 5: langgraph dev 은퇴).
# ⚠️ workers=1 고정 — 검색 백프레셔·보고서 큐·턴 락·LLM RPS 캡이 프로세스
# 로컬(CLAUDE.md §7). 스케일아웃은 scaling_roadmap.md 의 Redis 단계에서.
# --no-server-header: `server: uvicorn` 응답 헤더 제거(스택 정보 노출 차단).
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-server-header"]
