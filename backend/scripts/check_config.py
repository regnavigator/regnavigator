"""설정 점검 — 현재 env 노브 스냅샷(시크릿 마스킹) + prod 필수 검증.

운영 배포 전/부팅 전 "노브 한눈에" + 누락 사전 차단.
usage: python scripts/check_config.py
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    from src.config import dump, missing_prod_required

    by_group: dict[str, list] = {}
    for row in dump():
        by_group.setdefault(row["group"], []).append(row)

    for group, rows in by_group.items():
        print(f"[{group}]")
        for r in rows:
            mark = "✓" if r["set"] else ("✗필수" if r["prod_required"] else "·")
            print(f"  {mark} {r['key']}: {r['value']}")
        print()

    rc = 0
    missing = missing_prod_required()
    if missing:
        print(f"⚠ prod 필수 미설정: {missing}")
        rc = 1
    else:
        print("✓ prod 필수 env 모두 설정됨")

    # 서류 기입값 암호화 키 형식 — 부팅(lifespan)과 같은 검사(2026-09-21 키 끝 '=' 누락 사고)
    from src.persistence import field_crypto

    try:
        mode = field_crypto.validate_key()
        print(f"✓ 저장 암호화 키: {mode}")
    except RuntimeError as e:
        print(f"⚠ {e}")
        rc = 1
        mode = "error"

    # 시크릿 분리(2026-10-05, 감사 I5) — 경고만(rc 유지). 둘 다 "지금 돌아가긴 한다"가
    # 문제라, 배포를 막는 대신 점검 때마다 눈에 띄게 한다.
    import os

    if mode == "derived":
        print("⚠ 암호화 키가 NEXTAUTH_SECRET 파생 — 세션 시크릿을 돌리면 서식 기입값·기밀 "
              "메시지·조합 파일이 전부 복호화 불가가 된다. FILLED_VALUES_ENC_KEY 를 따로 두고 "
              "(쉼표로 기존 파생 키와 병기해 회전) NEXTAUTH_SECRET 과 분리할 것")
    rag = (os.getenv("RAG_SEARCH_API_KEY") or "").strip()
    shared = [k for k in ("PII_NER_API_KEY", "INTENT_API_KEY")
              if rag and (os.getenv(k) or "").strip() == rag]
    if shared:
        print(f"⚠ DGX API 키 공유: RAG_SEARCH_API_KEY == {', '.join(shared)} — 하나가 새면 "
              "검색·PII·의도 서버가 같이 뚫린다. 서비스별 키로 분리할 것(DGX 쪽 .env 동시 교체)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
