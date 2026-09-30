"""HTTP 라우트 모듈 — `src/api.py` 의 비대화를 해소하기 위해 도메인별 APIRouter 분리.

`src/api.py` 가 `app` 생성·미들웨어 스택·공개 라우트(/healthz, /suggestions)만 들고,
나머지 엔드포인트는 이 패키지의 라우터를 `app.include_router(...)` 로 마운트한다.
미들웨어는 `app` 레벨에 붙으므로 모든 라우터 엔드포인트에 동일하게 적용된다.
"""

from __future__ import annotations

from src.routes.admin import router as admin_router
from src.routes.admin_reviews import router as admin_reviews_router
from src.routes.admin_newsletters import router as admin_newsletters_router
from src.routes.admin_usage import router as admin_usage_router
from src.routes.announcements import router as announcements_router
from src.routes.articles import router as articles_router
from src.routes.beta import router as beta_router
from src.routes.bookmarks import router as bookmarks_router
from src.routes.chat import router as chat_router
from src.routes.feedback import router as feedback_router
from src.routes.files import router as files_router
from src.routes.health import router as health_router
from src.routes.law_graph import router as law_graph_router
from src.routes.monitor import router as monitor_router
from src.routes.notices import router as notices_router
from src.routes.privacy import router as privacy_router
from src.routes.reports import router as reports_router

__all__ = [
    "admin_router",
    "admin_reviews_router",
    "admin_newsletters_router",
    "admin_usage_router",
    "announcements_router",
    "privacy_router",
    "articles_router",
    "beta_router",
    "chat_router",
    "feedback_router",
    "files_router",
    "bookmarks_router",
    "health_router",
    "law_graph_router",
    "monitor_router",
    "notices_router",
    "reports_router",
]
