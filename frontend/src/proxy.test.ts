// @vitest-environment node
/**
 * Regression: leftover "__Host-cheena_*" cookies (from a time the backend ran
 * with COOKIE_SECURE=true) made the client send a stale CSRF token, so Sign out
 * and every other write failed with "The request could not be verified".
 * The page gate now removes the cookie family the backend does not use.
 */
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { proxy, staleCookieNames } from "@/proxy";

const ME = { id: "u1", full_name: "Admin", email: "a@example.test", workspace: "company" };

function request(path: string, cookies: Record<string, string>): NextRequest {
  const cookie = Object.entries(cookies)
    .map(([k, v]) => `${k}=${v}`)
    .join("; ");
  return new NextRequest(new URL(path, "http://localhost:3000"), { headers: { cookie } });
}

/** Backend stub: accepts only the given session cookie name/value. */
function backendAccepts(name: string, value: string) {
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    const sent = new Headers(init?.headers).get("cookie") ?? "";
    const ok = sent.split("; ").includes(`${name}=${value}`);
    return new Response(ok ? JSON.stringify(ME) : "{}", { status: ok ? 200 : 401 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

function expiredNames(response: Response): string[] {
  return response.headers
    .getSetCookie()
    .filter((c) => /Max-Age=0/i.test(c))
    .map((c) => c.split("=")[0]);
}

const BOTH_FAMILIES = {
  "__Host-cheena_session": "old-session",
  "__Host-cheena_csrf": "old-csrf",
  cheena_session: "live-session",
  cheena_csrf: "live-csrf",
};

describe("page gate cleans up a leftover cookie family", () => {
  it("expires the __Host- pair when the backend uses plain cookies", async () => {
    backendAccepts("cheena_session", "live-session");
    const response = await proxy(request("/company/shops", BOTH_FAMILIES));
    expect(response.status).toBe(200);
    expect(expiredNames(response).sort()).toEqual(["__Host-cheena_csrf", "__Host-cheena_session"]);
    // "__Host-" deletions must be Secure with Path=/ or the browser ignores them, and
    // must carry a past Expires: Next.js may re-emit the cookie without Max-Age on a
    // pass-through, which would otherwise leave an empty cookie instead of deleting it.
    for (const c of response.headers.getSetCookie()) {
      expect(c).toMatch(/Path=\//);
      expect(c).toMatch(/Secure/i);
      expect(c).toMatch(/Expires=Thu, 01 Jan 1970/);
    }
  });

  it("expires the plain pair when the backend uses __Host- cookies", async () => {
    backendAccepts("__Host-cheena_session", "old-session");
    expect((await staleCookieNames(request("/company", BOTH_FAMILIES))).sort()).toEqual([
      "cheena_csrf",
      "cheena_session",
    ]);
  });

  it("removes a lone stale CSRF cookie without probing the backend", async () => {
    const fetchMock = backendAccepts("cheena_session", "live-session");
    const names = await staleCookieNames(
      request("/company", { cheena_session: "live-session", cheena_csrf: "live", "__Host-cheena_csrf": "old" }),
    );
    expect(names).toEqual(["__Host-cheena_csrf"]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("changes nothing for a normal single-family browser", async () => {
    backendAccepts("cheena_session", "live-session");
    const response = await proxy(request("/company", { cheena_session: "live-session", cheena_csrf: "live" }));
    expect(response.status).toBe(200);
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it("heals on /login when the user is already signed in", async () => {
    backendAccepts("cheena_session", "live-session");
    const response = await proxy(request("/login", BOTH_FAMILIES));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/company");
    expect(expiredNames(response).sort()).toEqual(["__Host-cheena_csrf", "__Host-cheena_session"]);
  });

  it("still signs out a browser whose sessions are all invalid", async () => {
    backendAccepts("cheena_session", "something-else");
    const response = await proxy(request("/company", BOTH_FAMILIES));
    expect(response.headers.get("location")).toBe("http://localhost:3000/login?reason=session_expired");
    expect(expiredNames(response).sort()).toEqual([
      "__Host-cheena_csrf",
      "__Host-cheena_session",
      "cheena_csrf",
      "cheena_session",
    ]);
  });
});
