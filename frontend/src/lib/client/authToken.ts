/**
 * In-memory auth token store. NextAuth session.accessToken을 AuthProvider가 sync.
 * 변경 시 langgraph client cache invalidation을 위해 이벤트 발화.
 */

const TOKEN_CHANGE_EVENT = "medi-front-auth-token-changed";

let currentToken: string | null = null;

export function getAuthToken(): string | null {
  return currentToken;
}

export function setAuthToken(token: string | null): void {
  if (currentToken === token) return;
  currentToken = token;
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(TOKEN_CHANGE_EVENT));
  }
}

export function onAuthTokenChange(handler: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(TOKEN_CHANGE_EVENT, handler);
  return () => window.removeEventListener(TOKEN_CHANGE_EVENT, handler);
}

export { TOKEN_CHANGE_EVENT };
