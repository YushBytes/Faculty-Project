/**
 * The one place the browser talks to the backend.
 *
 * - `/api/v1/*` is proxied same-origin to FastAPI (app/api/v1/[...path]/route.ts).
 * - The access token lives in memory only. A 401 triggers one silent refresh through
 *   `/api/session/refresh` (httpOnly cookie) and a single retry.
 * - Errors arrive in the backend envelope `{error:{code,message,details}}` and are raised as
 *   `ApiError`, so every page renders the server's own message.
 */
export type ErrorDetail = { loc?: (string | number)[]; message: string; code?: string };

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: ErrorDetail[] = [],
  ) {
    super(message);
  }
}

let accessToken: string | null = null;
let refreshing: Promise<string | null> | null = null;
let onSessionLost: (() => void) | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}
export function onUnauthenticated(handler: () => void) {
  onSessionLost = handler;
}

export async function refreshSession(): Promise<string | null> {
  if (!refreshing) {
    refreshing = fetch("/api/session/refresh", { method: "POST", credentials: "same-origin" })
      .then(async (r) => (r.status === 200 ? ((await r.json()).access_token as string) : null))
      .catch(() => null)
      .then((token) => {
        accessToken = token;
        return token;
      })
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

export type Query = Record<string, string | number | boolean | null | undefined | string[]>;

export function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
    else params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

async function toError(response: Response): Promise<ApiError> {
  const body = await response.json().catch(() => null);
  const error = body?.error;
  if (error) return new ApiError(response.status, error.code, error.message, error.details ?? []);
  if (Array.isArray(body?.detail)) {
    return new ApiError(response.status, "validation_error", body.detail.map((d: { msg: string }) => d.msg).join("; "));
  }
  return new ApiError(response.status, "http_error", `Request failed (${response.status}).`);
}

type Options = { method?: string; body?: unknown; query?: Query; form?: FormData; signal?: AbortSignal };

async function send(path: string, options: Options, retry = true): Promise<Response> {
  const headers: Record<string, string> = {};
  if (accessToken) headers.authorization = `Bearer ${accessToken}`;
  let body: BodyInit | undefined;
  if (options.form) body = options.form;
  else if (options.body !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  const response = await fetch(withQuery(`/api/v1${path}`, options.query), {
    method: options.method ?? (body ? "POST" : "GET"),
    headers,
    body,
    signal: options.signal,
    credentials: "same-origin",
  });
  if (response.status === 401 && retry) {
    const token = await refreshSession();
    if (token) return send(path, options, false);
    onSessionLost?.();
  }
  return response;
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const response = await send(path, options);
  if (!response.ok) throw await toError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Download a file the backend generated (reports, templates) and save it. */
export async function download(path: string, query?: Query): Promise<{ fileName: string; size: number }> {
  const response = await send(path, { query });
  if (!response.ok) throw await toError(response);
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") ?? "";
  const fileName = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? "download";
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
  return { fileName, size: blob.size };
}

export async function sessionLogin(email: string, password: string): Promise<string> {
  const response = await fetch("/api/session/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email, password }),
    credentials: "same-origin",
  });
  if (!response.ok) throw await toError(response);
  const token = (await response.json()).access_token as string;
  accessToken = token;
  return token;
}

export async function sessionLogout(): Promise<void> {
  await fetch("/api/session/logout", { method: "POST", credentials: "same-origin" }).catch(() => undefined);
  accessToken = null;
}

/** Multipart upload with progress (XMLHttpRequest; fetch cannot report upload progress). */
export function uploadWithProgress<T>(path: string, form: FormData, onProgress: (fraction: number) => void, retry = true): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1${path}`);
    if (accessToken) xhr.setRequestHeader("authorization", `Bearer ${accessToken}`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onerror = () => reject(new ApiError(0, "network_error", "The upload could not reach the server."));
    xhr.onload = async () => {
      if (xhr.status === 401 && retry) {
        const token = await refreshSession();
        if (token) return uploadWithProgress<T>(path, form, onProgress, false).then(resolve, reject);
      }
      let body: unknown = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(body as T);
      const error = (body as { error?: { code: string; message: string; details?: ErrorDetail[] } })?.error;
      reject(error ? new ApiError(xhr.status, error.code, error.message, error.details ?? []) : new ApiError(xhr.status, "http_error", `Upload failed (${xhr.status}).`));
    };
    xhr.send(form);
  });
}
