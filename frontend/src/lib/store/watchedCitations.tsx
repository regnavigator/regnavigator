"use client";

/**
 * 관찰 중인 조문 집합 — 본문 인용 칩이 "이미 담았는지"를 알게 한다 (2026-10-02).
 *
 * 실사용 지적: "주석(숫자)에 관찰중인 것과 아닌 것을 구분할 수 있으면 좋겠음.
 * 눌러봐야 아니 좀 답답함." 맞다 — 담았는지 보려고 인용을 하나씩 여는 건 일이다.
 *
 * 칩은 `MarkdownContent` 깊숙이 있고, 관찰 목록을 읽어 오는 쪽은 `PageShellInner`
 * 다. prop 으로 끌고 내려가면 중간 컴포넌트가 전부 관찰을 알아야 한다.
 *
 * **상태를 provider 가 들고** 있는 이유: `PageShellInner` 는 좁은 화면·넓은 화면
 * 두 갈래로 return 하는데, 그 안에서 상태를 만들면 두 JSX 를 모두 감싸야 한다.
 * provider 가 들면 바깥에서 한 번만 감싸면 되고 JSX 를 건드릴 일이 없다.
 *
 * 모니터링 스레드가 아니면 빈 집합이라 아무 표시도 생기지 않는다.
 */

import {
  createContext,
  useContext,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";

type Ctx = {
  keys: ReadonlySet<string>;
  setKeys: Dispatch<SetStateAction<Set<string>>>;
};

const WatchedCtx = createContext<Ctx>({
  keys: new Set(),
  setKeys: () => undefined,
});

export function WatchedCitationsProvider({ children }: { children: ReactNode }) {
  const [keys, setKeys] = useState<Set<string>>(new Set());
  const value = useMemo(() => ({ keys, setKeys }), [keys]);
  return <WatchedCtx.Provider value={value}>{children}</WatchedCtx.Provider>;
}

export function useWatchedCitations(): Ctx {
  return useContext(WatchedCtx);
}

/** 이 조문을 관찰 중인가. `articleKey` 가 없으면(웹 인용 등) 항상 false. */
export function useIsWatched(articleKey: string | null | undefined): boolean {
  const { keys } = useContext(WatchedCtx);
  return !!articleKey && keys.has(articleKey);
}
