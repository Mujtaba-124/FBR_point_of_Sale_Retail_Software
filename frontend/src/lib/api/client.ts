import { CSRF_COOKIE_NAMES, type ApiErrorBody } from "@/lib/api/types";

/** Error with a safe, user-presentable message. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const NETWORK_MESSAGE =
  "Unable to reach the server. Check your connection and try again.";
const TIMEOUT_MESSAGE = "The server took too long to respond. Please try again.";

/** Every request settles: a hung connection becomes a handled error, never an endless spinner. */
export const REQUEST_TIMEOUT_MS = 15_000;
const SERVER_MESSAGE = "Something went wrong on our side. Please try again.";

function readCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  for (const cookie of document.cookie.split("; ")) {
    const [name, ...rest] = cookie.split("=");
    if ((CSRF_COOKIE_NAMES as readonly string[]).includes(name)) {
      return decodeURIComponent(rest.join("="));
    }
  }
  return null;
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as Partial<ApiErrorBody>;
    if (body.error?.code && body.error.message) {
      return new ApiError(response.status, body.error.code, body.error.message);
    }
  } catch {
    // Non-JSON error (e.g. proxy failure); fall through to a generic message.
  }
  return new ApiError(response.status, "server_error", SERVER_MESSAGE);
}

/**
 * Browser-side call to the backend through the same-origin /api/v1 proxy.
 * Cookies travel automatically; state-changing requests carry the CSRF token.
 */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  const method = (init.method ?? "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = readCsrfToken();
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }

  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...init,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      signal: init.signal ?? AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === "TimeoutError";
    throw new ApiError(0, "network_error", timedOut ? TIMEOUT_MESSAGE : NETWORK_MESSAGE);
  }

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
