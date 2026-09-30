/**
 * Server-only helpers for talking to the FastAPI backend.
 *
 * The browser never sees the backend's refresh token: the session routes keep it in an
 * httpOnly, SameSite=Strict cookie scoped to /api/session, and hand the browser only the
 * short-lived access token, which lives in memory.
 */
export const BACKEND_URL = (process.env.ACADLYTICS_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const REFRESH_COOKIE = "acadlytics_rt";
const SEVEN_DAYS = 7 * 24 * 60 * 60;

export function refreshCookie(value: string, maxAge = SEVEN_DAYS) {
  return {
    name: REFRESH_COOKIE,
    value,
    httpOnly: true,
    sameSite: "strict" as const,
    secure: process.env.NODE_ENV === "production" && process.env.ACADLYTICS_INSECURE_COOKIES !== "1",
    path: "/api/session",
    maxAge,
  };
}

export type TokenPair = { access_token: string; refresh_token: string; token_type: string; access_token_expires_at: string };
