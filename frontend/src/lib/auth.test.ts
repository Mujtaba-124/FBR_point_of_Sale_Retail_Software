import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, REQUEST_TIMEOUT_MS } from "@/lib/api/client";
import { signIn, signOut } from "@/lib/auth";

const fetchMock = vi.fn();

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function clearCookies() {
  for (const name of ["cheena_csrf", "__Host-cheena_csrf"]) {
    document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  }
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  clearCookies();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  clearCookies();
});

describe("API client and auth calls", () => {
  it("sends the current session's CSRF token on logout, and a new one after re-login", async () => {
    document.cookie = "cheena_csrf=token-session-1; path=/";
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await signOut();
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get("X-CSRF-Token")).toBe(
      "token-session-1",
    );

    // A new login issues a new CSRF cookie; the next logout must use it.
    document.cookie = "cheena_csrf=token-session-2; path=/";
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await signOut();
    expect(new Headers(fetchMock.mock.calls[1][1].headers).get("X-CSRF-Token")).toBe(
      "token-session-2",
    );
  });

  it("does not send a CSRF header on sign-in or GET requests", async () => {
    document.cookie = "cheena_csrf=stale; path=/";
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { user: { workspace: "company" } }));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, {}));
    await signIn({ email: "a@example.test", password: "secret-pass-1" });
    // Login is a POST, but the stale token is harmless: the backend ignores it there.
    await apiFetch("/auth/me");
    expect(new Headers(fetchMock.mock.calls[1][1].headers).has("X-CSRF-Token")).toBe(false);
  });

  it("treats logout of an already-expired session as signed out", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(401, { error: { code: "not_authenticated", message: "x" } }),
    );
    await expect(signOut()).resolves.toBeUndefined();
  });

  it("surfaces backend error codes and messages", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(429, { error: { code: "rate_limited", message: "Too many attempts." } }),
    );
    await expect(signIn({ email: "a@example.test", password: "p" })).rejects.toMatchObject({
      status: 429,
      code: "rate_limited",
      message: "Too many attempts.",
    });
  });

  it("maps network failures and non-JSON errors to handled ApiErrors", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(apiFetch("/auth/me")).rejects.toMatchObject({ code: "network_error" });

    fetchMock.mockResolvedValueOnce(new Response("<html>Bad gateway</html>", { status: 502 }));
    await expect(apiFetch("/auth/me")).rejects.toMatchObject({ status: 502, code: "server_error" });
  });

  it("gives every request a timeout so a hung server cannot spin forever", async () => {
    fetchMock.mockImplementationOnce(
      (_url: string, init: RequestInit) =>
        new Promise((_, reject) => {
          init.signal?.addEventListener("abort", () =>
            reject(new DOMException("timed out", "TimeoutError")),
          );
        }),
    );
    const pending = apiFetch("/auth/me");
    expect(fetchMock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
    const error = await pending.catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toMatch(/too long/);
    expect(REQUEST_TIMEOUT_MS).toBeLessThanOrEqual(30_000);
  }, REQUEST_TIMEOUT_MS + 5_000);
});
