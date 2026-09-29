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
        print(f"✓ filled_values 암호화 키: {field_crypto.validate_key()}")
    except RuntimeError as e:
        print(f"⚠ {e}")
        rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
