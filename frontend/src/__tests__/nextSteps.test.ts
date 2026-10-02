import { describe, expect, it } from "vitest";

import { parseNextStepsMarker } from "@/lib/parse/nextSteps";

describe("parseNextStepsMarker", () => {
  it("닫힌 마커를 파싱하고 본문에서 제거한다", () => {
    const { clean, items } = parseNextStepsMarker(
      "본문\n\n<next_steps>\n[{\"title\":\"면제\",\"prompt\":\"면제 대상은?\"}]\n</next_steps>",
    );
    expect(clean.trim()).toBe("본문");
    expect(items).toEqual([{ title: "면제", prompt: "면제 대상은?", kind: "chat" }]);
  });

  it("스트리밍 중 열린 마커는 본문에서 숨기고 items 는 비운다", () => {
    const { clean, items } = parseNextStepsMarker("본문\n<next_steps>\n[{\"ti");
    expect(clean.trim()).toBe("본문");
    expect(items).toEqual([]);
  });

  it("깨진 꼬리(<next_step)도 숨긴다", () => {
    expect(parseNextStepsMarker("본문 <next_step").clean.trim()).toBe("본문");
  });

  it("보고서 어휘면 kind=report, 명시 kind 가 있으면 그걸 우선", () => {
    const { items } = parseNextStepsMarker(
      "x<next_steps>[{\"title\":\"종합 보고서\",\"prompt\":\"보고서 작성해줘\"},{\"title\":\"a\",\"prompt\":\"보고서\",\"kind\":\"chat\"}]</next_steps>",
    );
    expect(items.map((i) => i.kind)).toEqual(["report", "chat"]);
  });

  it("prompt 없는 항목은 버린다 · 마커 없으면 본문 그대로", () => {
    expect(parseNextStepsMarker("x<next_steps>[{\"title\":\"t\"}]</next_steps>").items).toEqual([]);
    expect(parseNextStepsMarker("그대로").clean).toBe("그대로");
  });
});
