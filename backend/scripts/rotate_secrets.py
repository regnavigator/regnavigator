"""시크릿 로테이션 체크리스트 — 무엇을, 어디서, 어떤 순서로.

`.env.bak` 노출 사고(2026-04-30) 이후 키 회전이 필요하다. 이 스크립트는 **자동으로
돌리지 않는다**(각 발급처 콘솔에서 사람이 발급). 대신:

1. `ENV_REGISTRY` 의 `secret=True` 를 읽어 **회전 대상 목록**을 뽑고,
2. 현재 설정 여부(마스킹)와 **발급처 URL**, **회전 순서**를 출력한다.

회전 순서가 중요한 이유: 새 키를 넣고 재기동하기 전에 옛 키를 폐기하면 서비스가 죽는다.
반드시 **발급 → .env 교체 → 재기동 → 검증 → 옛 키 폐기** 순.

usage:
  python scripts/rotate_secrets.py            # 체크리스트 출력
  python scripts/rotate_secrets.py --verify   # 회전 후 실제 동작 검증
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()

# 발급처 — 콘솔에서 새 키 발급 후 .env / .env.docker 교체.
ISSUERS = {
    "ANTHROPIC_API_KEY": "https://console.anthropic.com/settings/keys",
    "OPENAI_API_KEY": "https://platform.openai.com/api-keys",
    "TAVILY_API_KEY": "https://app.tavily.com/home",
    "LANGSMITH_API_KEY": "https://smith.langchain.com/settings",
    "NEXTAUTH_SECRET": "직접 생성: openssl rand -base64 32  (⚠️medi-front 와 동일값)",
    "RAG_SEARCH_API_KEY": "openlaw-etl INSTANCE_API_KEY (DGX .env) — 양쪽 동시 교체",
    "PII_NER_API_KEY": "guardrail-server (DGX) — RAG 키와 공유 중, 분리 권장",
    "INTENT_API_KEY": "guardrail-server (DGX) — 상동",
    "REPORT_WRITER_API_KEY": "vLLM 인증(무인증이면 임의값)",
    "EMAIL_SERVER": "Resend 대시보드 API 키 재발급 (medi-front 와 동일값 — 양쪽 교체)",
    "SMTP_PASS": "메일 공급자 앱 비밀번호 재발급(EMAIL_SERVER 미사용 시)",
    "PG_PASS": "openlaw-etl PG (ETL 팀과 조율)",
    "NEO4J_PASS": "openlaw-etl Neo4j (ETL 팀과 조율)",
    "POSTGRES_PASSWORD": "운영 PG — 교체 시 DSN·볼륨 재설정 필요(다운타임)",
    "API_TOKEN": "직접 생성: openssl rand -hex 32",
}


def _verify() -> int:
    """회전 후 실제 동작하는지 — 검색 API·가드레일·LLM 키."""
    print("=== 회전 후 검증 ===")
    rc = 0
    from src.retrieval.search_api_client import is_available, ping
    if is_available():
        ok, detail = ping()
        print(f"  검색 API : {'OK' if ok else 'FAIL ' + str(detail)}")
        rc |= 0 if ok else 1
    else:
        print("  검색 API : 미설정 (RAG_SEARCH_API_URL/_KEY)"); rc |= 1

    for name, url_key, key_key in (
        ("PII NER ", "PII_NER_API_URL", "PII_NER_API_KEY"),
        ("의도분류", "INTENT_API_URL", "INTENT_API_KEY"),
    ):
        url = os.getenv(url_key)
        if not url:
            print(f"  {name} : 미설정(폴백 동작)"); continue
        try:
            import httpx
            r = httpx.get(f"{url.rstrip('/')}/health",
                          headers={"X-API-Key": os.getenv(key_key) or ""}, timeout=5)
            print(f"  {name} : {'OK' if r.status_code == 200 else f'FAIL {r.status_code}'}")
            rc |= 0 if r.status_code == 200 else 1
        except Exception as e:  # noqa: BLE001
            print(f"  {name} : FAIL {type(e).__name__}"); rc |= 1

    print(f"  ANTHROPIC_API_KEY: {'설정됨' if os.getenv('ANTHROPIC_API_KEY') else '미설정'}"
          " (실호출 검증은 scripts/bench_run.py)")
    return rc


def main() -> int:
    if "--verify" in sys.argv:
        return _verify()

    from src.config import ENV_REGISTRY

    secrets = [s for s in ENV_REGISTRY if s.secret]
    print("=== 시크릿 로테이션 체크리스트 ===")
    print("순서: ① 발급처에서 새 키 → ② .env/.env.docker 교체 → ③ 재기동")
    print("      → ④ python scripts/rotate_secrets.py --verify → ⑤ 옛 키 폐기\n")
    print(f"{'키':26} {'현재':8} 발급처")
    print("-" * 96)
    for s in secrets:
        cur = "설정됨" if (os.getenv(s.key) or "").strip() else "미설정"
        print(f"{s.key:26} {cur:8} {ISSUERS.get(s.key, '(발급처 미등록)')}")
    # 레지스트리에 없지만 회전 대상인 인프라 키
    for k in ("POSTGRES_PASSWORD",):
        if k not in {s.key for s in secrets}:
            cur = "설정됨" if (os.getenv(k) or "").strip() else "미설정"
            print(f"{k:26} {cur:8} {ISSUERS[k]}")

    print("\n⚠️ 주의")
    print("  · NEXTAUTH_SECRET 은 medi-front 와 **동일 값**이어야 한다(양쪽 동시 교체).")
    print("  · RAG_SEARCH_API_KEY 는 openlaw-etl INSTANCE_API_KEY 와 같은 값 — DGX 쪽도 교체.")
    print("  · 가드레일 키가 검색 키와 공유 중 — 이번 기회에 **서비스별 분리** 권장.")
    print("  · 옛 키 폐기는 **재기동·검증 후**. 먼저 폐기하면 서비스가 죽는다.")
    print("  · `.env*` 는 절대 커밋 금지. `chmod 600`. (`.env.bak` 사고 2026-04-30)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
