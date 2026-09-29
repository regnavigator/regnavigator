"""저장 필드 암호화 — 서류 기입값(`reports.filled_values`) 전용 (2026-09-18).

성명·연락처·주소처럼 서식에 적는 값은 개인정보 그 자체다. DB 덤프·백업·
관리 콘솔에서 평문으로 보이지 않도록 컬럼 값을 Fernet(AES-128-CBC+HMAC)
으로 감싼다. 컬럼 타입은 TEXT 그대로 — 스키마 변경 없음.

키 결정(우선순위):
  1. `FILLED_VALUES_ENC_KEY` — Fernet 키(urlsafe base64 32B). 쉼표로 여러 개
     주면 첫 키로 암호화·전부로 복호화(회전용 MultiFernet).
  2. 미설정이면 `NEXTAUTH_SECRET` 에서 파생(SHA-256) — 운영 VM 에 새 env 를
     넣기 전에도 배포 즉시 암호화가 켜지게. 명시 키를 나중에 넣어도 파생 키를
     복호 후보에 남겨 두므로 기존 행이 깨지지 않는다.
  3. 둘 다 없으면(테스트·맨 dev) 평문 — 1회 경고.

값 형식: `enc1:<token>`. 접두 없는 값은 레거시 평문으로 보고 그대로 돌려준다
(마이그레이션 없이 읽기 호환 — 다음 merge 때 암호문으로 재기록된다).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from functools import lru_cache
from typing import Optional

_log = logging.getLogger(__name__)

PREFIX = "enc1:"


def _derived_key(secret: str) -> bytes:
    digest = hashlib.sha256(b"medireg.filled_values.v1:" + secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _fernet():
    """MultiFernet 또는 None(평문 모드). env 는 프로세스 수명 동안 고정."""
    try:
        from cryptography.fernet import Fernet, MultiFernet
    except ImportError:  # pragma: no cover — base deps 에 선언되어 있음
        _log.warning("cryptography 미설치 — filled_values 평문 저장")
        return None
    keys: list = []
    explicit = (os.getenv("FILLED_VALUES_ENC_KEY") or "").strip()
    for k in (x.strip() for x in explicit.split(",") if x.strip()):
        try:
            keys.append(Fernet(k.encode("ascii")))
        except Exception as e:  # noqa: BLE001 — 잘못된 키는 부팅 때 바로 드러나야(validate_key)
            raise RuntimeError(
                "FILLED_VALUES_ENC_KEY 형식 오류(Fernet 키 필요 — urlsafe base64 44자, "
                f"끝 '=' 포함. 현재 길이 {len(k)}자)") from e
    secret = (os.getenv("NEXTAUTH_SECRET") or "").strip()
    if secret:
        keys.append(Fernet(_derived_key(secret)))
    if not keys:
        _log.warning("FILLED_VALUES_ENC_KEY / NEXTAUTH_SECRET 둘 다 없음 — "
                     "filled_values 평문 저장(dev/test 전용)")
        return None
    if not explicit:
        _log.info("filled_values 암호화: NEXTAUTH_SECRET 파생 키 사용"
                  "(FILLED_VALUES_ENC_KEY 설정 권장)")
    return MultiFernet(keys)


def validate_key() -> str:
    """부팅 검증 — 키를 **지금** 한 번 만들어 형식 오류를 즉시 드러낸다.

    `_fernet()` 은 첫 암호화 때 지연 생성되므로, 키가 잘못돼도 부팅·`/readyz`
    는 멀쩡하고 서식을 만드는 순간에만 500 이 났다(2026-09-18 배포 → 09-21 발견:
    VM `.env.docker` 의 키 끝 `=` 누락으로 3일간 서식 작성 전건 실패, CORS 없는
    500 이라 화면엔 "열 수 없어요"만). lifespan 이 부르고, 실패면 부팅을 막아
    배포 healthz 단계에서 바로 드러나게 한다. 반환: "explicit" | "derived" | "off".
    키 값은 어디에도 남기지 않는다.
    """
    _fernet.cache_clear()
    f = _fernet()  # 형식 오류면 RuntimeError
    if f is None:
        return "off"
    # 왕복까지 확인 — 생성만 되고 쓰지 못하는 경우까지 막는다
    probe = f.encrypt(b"probe")
    if f.decrypt(probe) != b"probe":  # pragma: no cover — Fernet 보장
        raise RuntimeError("filled_values 암호화 왕복 실패")
    return "explicit" if (os.getenv("FILLED_VALUES_ENC_KEY") or "").strip() else "derived"


def reset_cache() -> None:
    """테스트용 — env 변경 후 키 재계산."""
    _fernet.cache_clear()


def is_enabled() -> bool:
    return _fernet() is not None


def encrypt_text(plain: Optional[str]) -> Optional[str]:
    """None/빈 문자열은 그대로. 이미 암호문이면 재암호화하지 않는다."""
    if plain is None or plain == "":
        return plain
    if plain.startswith(PREFIX):
        return plain
    f = _fernet()
    if f is None:
        return plain
    return PREFIX + f.encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_text(stored: Optional[str]) -> Optional[str]:
    """암호문이면 복호, 레거시 평문이면 그대로. 복호 실패는 예외로 — 조용히
    빈 값으로 바꾸면 사용자가 채운 칸이 사라진 것처럼 보인다."""
    if stored is None or stored == "":
        return stored
    if not stored.startswith(PREFIX):
        return stored
    f = _fernet()
    if f is None:
        raise RuntimeError("filled_values 가 암호화돼 있는데 복호 키가 없다 "
                           "(FILLED_VALUES_ENC_KEY 또는 NEXTAUTH_SECRET 필요)")
    from cryptography.fernet import InvalidToken
    try:
        return f.decrypt(stored[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise RuntimeError("filled_values 복호 실패 — 키가 바뀌었나? "
                           "이전 키를 FILLED_VALUES_ENC_KEY 에 쉼표로 함께 두라") from e
