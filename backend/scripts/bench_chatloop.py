"""자체 /chat 루프 벤치 — `scripts/bench_run.py`(langgraph 경로)와 동등성 비교용.

사용:
    PYTHONUTF8=1 python scripts/bench_chatloop.py "<질문>" [thread_id]

같은 질문을 bench_run.py 와 여기 둘 다 돌려 답변·인용·TTFT 를 비교한다
(ADR-0001 Phase 1 검증 게이트). thread_id 를 주면 같은 thread 로 후속 턴 벤치.
"""

from __future__ import annotations

import asyncio
import sys
import time
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    question = sys.argv[1] if len(sys.argv) > 1 else "의료기기 임상시험 시 식약처 허가 절차가 어떻게 되나요?"
    thread_id = sys.argv[2] if len(sys.argv) > 2 else f"bench_{uuid4().hex[:10]}"

    from src.chat_loop import run_chat_turn

    print(f"=== /chat loop bench ===\nthread: {thread_id}\nQ: {question}\n")
    t0 = time.monotonic()
    ttft = None
    final = None

    async for ev in run_chat_turn(thread_id, question):
        et = ev.get("type")
        if et == "token":
            if ttft is None:
                ttft = time.monotonic() - t0
                print(f"[TTFT {ttft:.2f}s]")
            print(ev.get("text", ""), end="", flush=True)
        elif et == "tool_progress":
            print(f"\n  [{ev.get('tool')}·{ev.get('phase')}] {ev.get('message', '')}")
        elif et == "step_lifecycle":
            step = ev.get("step") or {}
            print(f"\n  [step:{ev.get('phase')}] {step.get('label', '')}")
        elif et == "clarify":
            print(f"\n[clarify] {ev.get('question')} options={ev.get('options')}")
        elif et == "error":
            print(f"\n[error] {ev.get('message')}")
        elif et == "done":
            final = ev

    total = time.monotonic() - t0
    print(f"\n\n[total {total:.2f}s | ttft {ttft:.2f}s]" if ttft else f"\n[total {total:.2f}s]")

    if final:
        steps = final.get("steps") or []
        cites = [c for s in steps for c in (s.get("citations") or [])]
        verified = sum(1 for c in cites if c.get("verified"))
        print(f"steps={len(steps)} citations={len(cites)} verified={verified}")
        for c in cites:
            mark = "✓" if c.get("verified") else "·"
            print(f"  [{c.get('number')}]{mark} {c.get('title', '')[:70]}")


if __name__ == "__main__":
    asyncio.run(main())
