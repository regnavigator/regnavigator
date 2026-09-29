/**
 * Settings helper — 03 §11, 05 §3.1.
 *
 * **권위 순서 (높음 → 낮음)**:
 *  1) 환경변수 — `NEXT_PUBLIC_DEPLOYMENT_URL`, `NEXT_PUBLIC_ASSISTANT_ID`,
 *     (선택) `NEXT_PUBLIC_LANGSMITH_KEY`. production 권위.
 *  2) localStorage `medi-front-config` — SettingsDialog로 입력된 dev override.
 *
 * `Settings` 타입의 모든 필드는 *optional* — env로 충족 가능 (05 §3.1).
 * `getEffectiveSettings()`가 두 소스를 merge해 *실제 사용할* 값을 반환한다.
 */

export const SETTINGS_STORAGE_KEY = "medi-front-config";

/**
 * 1차 인증 = LangSmith key. v2에서 `user_jwt` 등이 추가될 자리 (00 §8 H6).
 * 모든 필드 optional — env가 채울 수 있고, dev override가 위에 덮어쓸 수도 있다.
 */
export type Settings = {
  deployment_url?: string;
  /** ⛔ 폐기(2026-07-16) — langgraph 은퇴(ADR-0001)로 소비처 없음. 저장값 무시. */
  assistant_id?: string;
  // ※ assistant_id_deep 제거 — 단일 thread 전환(2026-05-19)으로 agent_deep
  //   그래프 폐기. 보고서는 같은 chat thread의 일반 턴 + GET /reports.
  /** ⛔ 폐기(2026-07-16) — 소비처 없음(구 sidecar 헤더 폐기). 저장값 무시. */
  langsmith_key?: string;
  user_jwt?: string;
  // ※ Reports API는 LangGraph dev에 통합됨(`langgraph.json` `http.app`).
  //   별도 base/token 필드 불필요 — deployment_url + langsmith_key 그대로 사용.
};

/**
 * env vars만 읽어 부분 settings 반환 (server·client 모두 안전 — `process.env`는
 * Next.js가 빌드 타임에 인라이닝).
 */
function readEnvSettings(): Settings {
  const out: Settings = {};
  const url = process.env.NEXT_PUBLIC_DEPLOYMENT_URL;
  const aid = process.env.NEXT_PUBLIC_ASSISTANT_ID;
  const key = process.env.NEXT_PUBLIC_LANGSMITH_KEY;
  if (url && url.length > 0) out.deployment_url = url;
  if (aid && aid.length > 0) out.assistant_id = aid;
  if (key && key.length > 0) out.langsmith_key = key;
  return out;
}

/**
 * localStorage override만 읽음 — dev에서 SettingsDialog로 입력한 값. 빈 문자열은 제외.
 */
function readStoredSettings(): Settings {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Partial<Settings>;
    const out: Settings = {};
    if (parsed.deployment_url && parsed.deployment_url.length > 0)
      out.deployment_url = parsed.deployment_url;
    if (parsed.assistant_id && parsed.assistant_id.length > 0)
      out.assistant_id = parsed.assistant_id;
    if (parsed.langsmith_key && parsed.langsmith_key.length > 0)
      out.langsmith_key = parsed.langsmith_key;
    if (parsed.user_jwt && parsed.user_jwt.length > 0) out.user_jwt = parsed.user_jwt;
    return out;
  } catch {
    return {};
  }
}

/** LangGraph graph id로 유효한 형태인지 — 공백·@·:·/ 등 명백히 잘못된 글자 거름.
 *  주: backend graph 이름 컨벤션 = 영문자·숫자·`_`·`-`. 이메일/공백 등은 즉시 invalid.
 *  (브라우저 autofill이 assistant_id 입력에 이메일을 넣어 runs.stream이 실패하던
 *   사고가 있어 self-heal 추가 — 잘못된 값은 무시하고 env/기본값으로 떨어지게.) */
function isValidAssistantId(v: unknown): v is string {
  return typeof v === "string" && /^[A-Za-z0-9_-]+$/.test(v);
}

/**
 * env + localStorage override 머지 — 후자가 위에 덮어쓴다 (dev convenience).
 * 충족 여부 판단(`isConfigured`)도 본 함수 결과로만 한다.
 * `assistant_id`는 형식 검증을 거쳐 잘못된 값(예: 자동완성 이메일)은 *drop*.
 */
export function getEffectiveSettings(): Settings {
  const env = readEnvSettings();
  const stored = readStoredSettings();
  // localStorage override의 assistant_id가 invalid면 *override만 무시* →
  // env의 정상값(예: "agent")이 살아 있도록.
  if (stored.assistant_id !== undefined && !isValidAssistantId(stored.assistant_id)) {
    delete stored.assistant_id;
  }
  return { ...env, ...stored };
}

/**
 * 충족 여부 — 백엔드 호출 가능한가.
 * ADR-0001 Phase 4: 자체 SSE 전환으로 assistant_id 불요 — deployment_url 만.
 * dummy 모드면 항상 true.
 */
export function isConfigured(): boolean {
  if (isDummyMode()) return true;
  return !!getEffectiveSettings().deployment_url;
}

/**
 * (legacy 호환) — 기존 호출처가 `readSettings()` 결과를 그대로 썼던 것을
 * 점진 전환. 이제 *효과적* 값을 반환한다 (env + override).
 * 미충족이면 null.
 */
export function readSettings(): Settings | null {
  const s = getEffectiveSettings();
  if (!s.deployment_url || !s.assistant_id) return null;
  return s;
}

/**
 * 다이얼로그가 폼에 표시할 *override 원본만* — env는 절대 폼에 넣지 않음
 * (사용자가 env 값을 실수로 localStorage에 옮겨 쓰는 사고 방지).
 */
export function readStoredOverride(): Settings {
  return readStoredSettings();
}

export function writeSettings(settings: Settings): void {
  if (typeof window === "undefined") return;
  // 빈 문자열은 저장하지 않음 — env가 살아있도록.
  const cleaned: Settings = {};
  if (settings.deployment_url && settings.deployment_url.trim().length > 0)
    cleaned.deployment_url = settings.deployment_url.trim();
  if (settings.assistant_id && settings.assistant_id.trim().length > 0)
    cleaned.assistant_id = settings.assistant_id.trim();
  if (settings.langsmith_key && settings.langsmith_key.trim().length > 0)
    cleaned.langsmith_key = settings.langsmith_key.trim();
  if (settings.user_jwt && settings.user_jwt.trim().length > 0)
    cleaned.user_jwt = settings.user_jwt.trim();
  window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(cleaned));
}

export function clearStoredSettings(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(SETTINGS_STORAGE_KEY);
}

export function emptySettings(): Settings {
  return {};
}

/** 더미 모드 활성 여부 — 03 §11, 05 §3.1. */
export function isDummyMode(): boolean {
  return process.env.NEXT_PUBLIC_DUMMY_MODE === "true";
}

/**
 * 동일 origin의 모든 탭에 변경 알림 — config 변경 시 client 재생성을 위해
 * `storage` 이벤트(다른 탭) + `medi-front-config-changed` CustomEvent(같은 탭).
 */
export const SETTINGS_CHANGE_EVENT = "medi-front-config-changed";

export function notifySettingsChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(SETTINGS_CHANGE_EVENT));
}
