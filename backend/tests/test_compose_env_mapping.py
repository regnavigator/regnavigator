"""운영 compose 가 ENV_REGISTRY 노브를 컨테이너로 전달하는지 검증.

⚠️ 실측 사고(2026-08-02): `.env.docker` 에 `EMAIL_FROM=noreply@…` 이 있는데도
`docker-compose.yml` 의 environment 매핑에 없어서 **컨테이너에 안 들어갔다**.
발신자가 폴백 `no-reply@medi` 로 나가 Resend 가 550 으로 전부 거절 → 보고서
완료 메일이 조용히 0통. env_file 이 아니라 키별 매핑 방식이라 생기는 함정이다.

새 노브를 `ENV_REGISTRY` 에 추가하면 compose 매핑도 함께 추가해야 한다.
"""
from __future__ import annotations

import re
from pathlib import Path

# 의도적으로 운영에 노출하지 않는 키 — 늘릴 때는 이유를 함께 적을 것.
INTENTIONALLY_UNMAPPED = {
    # dev 자동로그인. 운영에 들어가면 인증 우회가 되므로 매핑하지 않는다.
    "AUTH_DEV_BYPASS_USER",
    # 배포 식별(2026-09-15) — .env.docker 가 아니라 Dockerfile ARG→ENV 로 이미지에
    # 박힌다(deploy.yml 의 GIT_SHA/BUILD_TIME 빌드 인자). compose environment 로
    # 매핑하면 `docker compose up` 을 빌드 인자 없이 다시 띄울 때 unknown 으로 덮인다.
    "APP_GIT_SHA",
    "APP_BUILD_TIME",
    # dev→원격 PG 가드의 탈출구(2026-09-17) — 로컬 운영 스크립트 전용. 컨테이너는
    # APP_GIT_SHA 로 가드를 통과하므로 필요 없고, 매핑하면 가드를 끄는 손잡이만 늘어난다.
    "ALLOW_REMOTE_PG",
}


def test_every_env_registry_key_is_mapped_in_compose():
    from src.config import ENV_REGISTRY

    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    missing = [
        s.key for s in ENV_REGISTRY
        if s.key not in INTENTIONALLY_UNMAPPED
        and re.search(rf"^\s*{re.escape(s.key)}:\s", compose, re.M) is None
    ]
    assert not missing, (
        "docker-compose.yml environment 매핑 누락 — .env.docker 에 값을 넣어도 "
        f"컨테이너에 전달되지 않는다: {missing}"
    )


def test_intentionally_unmapped_keys_stay_unmapped():
    """dev 전용 위험 노브가 실수로 운영에 매핑되지 않았는지."""
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    for key in INTENTIONALLY_UNMAPPED:
        assert re.search(rf"^\s*{re.escape(key)}:\s", compose, re.M) is None, (
            f"{key} 는 운영 compose 에 매핑하면 안 된다")


def test_cron_disables_inherited_api_healthcheck():
    """medi-cron 은 API 를 띄우지 않으므로 이미지 HEALTHCHECK 를 물려받으면 안 된다.

    물려받으면 영구 unhealthy 로 떠서(2026-08-03 실측) 진짜 장애 신호를 가린다.
    """
    import re
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    block = re.search(r"container_name: medi-cron.*?(?=\n  [a-z-]+:\n|\nvolumes:)",
                      compose, re.S)
    assert block, "medi-cron 블록을 찾지 못함"
    assert "disable: true" in block.group(0), \
        "medi-cron 은 healthcheck.disable: true 여야 한다"


def test_cron_runs_prune_before_sleeping():
    """`sleep` 이 루프 앞이면 배포마다 타이머가 초기화돼 보존정리가 영영 안 돈다."""
    import re
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    block = re.search(r"container_name: medi-cron.*?(?=\n  [a-z-]+:\n|\nvolumes:)",
                      compose, re.S).group(0)
    body = block[block.index("while true"):]
    first_sleep = body.index("sleep ")
    first_prune = body.index("prune_threads.py")
    assert first_prune < first_sleep, (
        "보존정리를 sleep 보다 먼저 실행해야 한다 — 잦은 배포에서 한 번도 안 돌았다")


def test_cron_sets_pythonpath_for_scripts():
    """`python scripts/x.py` 는 sys.path[0] 가 scripts/ 라 `import src` 가 실패한다.

    medi-back 은 /app 에서 uvicorn 을 띄워 무사했지만, cron 은 스크립트를 직접
    실행하므로 PYTHONPATH 가 없으면 ModuleNotFoundError 로 매번 죽는다.
    """
    import re
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    block = re.search(r"container_name: medi-cron.*?(?=\n  [a-z-]+:\n|\nvolumes:)",
                      compose, re.S).group(0)
    assert re.search(r"^\s*PYTHONPATH:\s*/app\s*$", block, re.M), \
        "medi-cron 에 PYTHONPATH=/app 이 필요하다"


# ---------------------------------------------------------------------------
# compose 파일 자체의 유효성 — 2026-08-04 배포 실패 회귀
#
# `deploy:` 를 서비스에 **두 번** 선언해 배포가 죽었다
# ("line 318: mapping key deploy already defined at line 60").
# env 매핑 검사는 텍스트 기반이라 이런 구조 오류를 못 잡았다.
# ---------------------------------------------------------------------------
def test_compose_is_valid_yaml_without_duplicate_keys():
    """중복 키는 PyYAML 이 조용히 마지막 값으로 덮으므로 명시적으로 잡는다."""
    import yaml
    from pathlib import Path

    text = Path("docker-compose.yml").read_text(encoding="utf-8")

    class _StrictLoader(yaml.SafeLoader):
        pass

    def _no_dupes(loader, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=deep)
            assert key not in seen, (
                f"docker-compose.yml 중복 키 '{key}' (line {key_node.start_mark.line + 1}) "
                "— docker compose 가 파싱 단계에서 죽어 배포가 실패한다")
            seen.add(key)
        return yaml.SafeLoader.construct_mapping(loader, node, deep)

    _StrictLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes)
    conf = yaml.load(text, Loader=_StrictLoader)

    assert "medi-back" in conf["services"]


def test_medi_back_pinned_to_single_replica():
    """인스턴스 1개 불변식(CLAUDE.md §7) — compose 선언으로도 못 박는다."""
    import yaml
    from pathlib import Path

    conf = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    assert conf["services"]["medi-back"]["deploy"]["replicas"] == 1


# ── LangSmith 트레이싱 재유입 방지 (2026-09-10) ────────────────────────
# 제거한 이유: 대화 원문이 국외(LangChain, Inc.)로 나가는 경로였고, IRB/DRB
# 스킬 턴을 온프레미스 모델로 돌리는(SKILL_LOCAL_MODEL=1) 정책과 정면으로
# 어긋났다 — 트레이싱은 langchain-core 레벨이라 온프레미스 호출의 프롬프트까지
# 실려 나간다. 종전 매핑이 `${LANGSMITH_TRACING:-true}` 라 .env.docker 에서
# 줄을 지워도 켜지는 함정이 있었으므로, 여기서 "false 고정"을 못박는다.
# 되살리려면 개인정보처리방침 §5(국외이전) 재등재가 선행되어야 한다.
def test_langsmith_tracing_is_pinned_off():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert 'LANGSMITH_TRACING: "false"' in compose, (
        "LANGSMITH_TRACING 은 false 로 고정되어야 한다"
    )
    for key in ("LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT"):
        assert f"{key}:" not in compose, f"{key} 매핑이 되살아났다"
    assert "${LANGSMITH_TRACING" not in compose, (
        "env 로 켤 수 있게 되돌리면 안 된다(기본값 :-true 함정)"
    )


def test_privacy_policy_has_no_langsmith_transfer_row():
    """방침 §5 국외이전 표와 실제 전송처가 어긋나면 허위/과다 고지가 된다."""
    md = Path("docs/legal/privacy.md").read_text(encoding="utf-8")
    assert "LangChain" not in md, "트레이싱을 껐으면 국외이전 표에서도 빠져야 한다"
    # 실제로 전송하는 곳은 남아 있어야 한다(과소 고지 방지)
    for who in ("Anthropic", "Tavily"):
        assert who in md, f"{who} 는 실제 전송처이므로 방침에 남아야 한다"


def test_cron_sees_same_blob_store_as_api():
    """medi-cron 의 보존정리는 medi-back 과 같은 blob 위치를 봐야 한다.

    2026-09-23 실측: cron 에 BLOB_LOCAL_DIR 가 없어 기본값(./reports_blobs)을 보고
    "blob 0개" — 보고서 30일 정리가 몇 달간 실제로 한 번도 돌지 않았다.
    """
    import re
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    blocks = {name: re.search(rf"container_name: {name}\n.*?(?=\n  [a-z-]+:\n|\nvolumes:)",
                              compose, re.S).group(0)
              for name in ("medi-back", "medi-cron")}
    for key in ("BLOB_BACKEND", "BLOB_LOCAL_DIR"):
        vals = {n: re.search(rf"^\s*{key}:\s*(\S+)", b, re.M) for n, b in blocks.items()}
        assert all(vals.values()), f"{key} 매핑 누락: {[n for n, v in vals.items() if not v]}"
        assert vals["medi-back"].group(1) == vals["medi-cron"].group(1), key
