"""스킬 번들 서브시스템 — 기관 내부 지침(IRB/DRB SOP) progressive disclosure.

- `loader`: 번들 로더(런타임) — temp/medireg-irb-drb-bundle 이식
- `chat_integration`: chat_loop 접점(스위치·세션·도구 실행·판정 로그) — 스킬
  로직은 전부 여기에 격리, chat_loop 에는 `turn_skill` 가드 훅만 둔다
- `medireg_irb_drb/`: 지식 자산(SKILL.md + references) — 코드에서 파싱 금지,
  로더로만 접근. manifest 갱신: `python scripts/build_skill_manifest.py`
"""
