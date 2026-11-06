import { NextResponse, type NextRequest } from "next/server";

import {
  CSRF_COOKIE_NAMES,
  SESSION_COOKIE_NAMES,
  WORKSPACE_PATHS,
  type CurrentUser,
  type Workspace,
} from "@/lib/api/types";

const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

type MeResult = CurrentUser | "unauthenticated" | "unavailable";

async function fetchMe(request: NextRequest, cookieHeader?: string): Promise<MeResult> {
  try {
    const response = await fetch(`${backendUrl}/api/v1/auth/me`, {
      headers: { cookie: cookieHeader ?? request.headers.get("cookie") ?? "" },
      cache: "no-store",
    });
    if (response.status === 200) return (await response.json()) as CurrentUser;
    if (response.status === 401) return "unauthenticated";
  } catch {
    // fall through
  }
  return "unavailable";
}

function requiredWorkspace(pathname: string): Workspace | null {
  if (pathname === "/super-admin" || pathname.startsWith("/super-admin/")) return "super_admin";
  if (pathname === "/company" || pathname.startsWith("/company/")) return "company";
  return null;
}

function redirectTo(request: NextRequest, path: string): NextResponse {
  return NextResponse.redirect(new URL(path, request.url));
}

/**
 * Delete a cookie. Both Max-Age=0 and a past Expires: on a pass-through
 * (NextResponse.next()) Next.js emits the cookie a second time without
 * Max-Age, which alone would leave an empty cookie behind instead of deleting it.
 * "__Host-" cookies are only replaced by a Secure Set-Cookie with Path=/.
 */
function expireCookie(response: NextResponse, name: string): void {
  response.cookies.set(name, "", {
    path: "/",
    maxAge: 0,
    expires: new Date(0),
    secure: name.startsWith("__Host-"),
  });
}

/** Drop dead session/CSRF cookies (the backend already revoked the session). */
function clearAuthCookies(response: NextResponse): NextResponse {
  for (const name of [...SESSION_COOKIE_NAMES, ...CSRF_COOKIE_NAMES]) {
    expireCookie(response, name);
  }
  return response;
}

/** The two cookie families the backend can use, depending on COOKIE_SECURE. */
const COOKIE_MODES = [
  { session: SESSION_COOKIE_NAMES[0], csrf: CSRF_COOKIE_NAMES[0] }, // "__Host-" (secure)
  { session: SESSION_COOKIE_NAMES[1], csrf: CSRF_COOKIE_NAMES[1] }, // plain (local HTTP)
] as const;
type CookieMode = (typeof COOKIE_MODES)[number];

/**
 * A browser can hold cookies of both families when COOKIE_SECURE changed at
 * some point. The backend reads only one; the other family's CSRF cookie is
 * then sent by mistake and every write fails CSRF ("The request could not be
 * verified"). Returns the leftover family's cookie names to expire, or none.
 */
export async function staleCookieNames(request: NextRequest): Promise<string[]> {
  const present = (mode: CookieMode) => request.cookies.has(mode.session) || request.cookies.has(mode.csrf);
  if (!COOKIE_MODES.every(present)) return [];
  const withSession = COOKIE_MODES.filter((mode) => request.cookies.has(mode.session));
  let active: CookieMode | undefined;
  if (withSession.length === 1) {
    active = withSession[0];
  } else if (withSession.length === 2) {
    // Ask the backend which session cookie it actually accepts.
    for (const mode of withSession) {
      const only = `${mode.session}=${request.cookies.get(mode.session)!.value}`;
      if (typeof (await fetchMe(request, only)) === "object") {
        active = mode;
        break;
      }
    }
  }
  if (!active) return [];
  const stale = COOKIE_MODES.find((mode) => mode !== active)!;
  return [stale.session, stale.csrf].filter((name) => request.cookies.has(name));
}

function expireCookies(response: NextResponse, names: string[]): NextResponse {
  for (const name of names) {
    expireCookie(response, name);
  }
  return response;
}

/**
 * Route gate for workspace pages. This is a first line of defence for page
 * navigation; every workspace page also asks the backend itself, and the
 * backend authorizes every API call.
 */
export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSession = SESSION_COOKIE_NAMES.some((name) => request.cookies.has(name));

  if (pathname === "/login") {
    if (!hasSession) return NextResponse.next();
    const me = await fetchMe(request);
    // Already signed in: go straight to the authorized workspace.
    if (typeof me === "object") {
      return expireCookies(redirectTo(request, WORKSPACE_PATHS[me.workspace]), await staleCookieNames(request));
    }
    if (me === "unauthenticated") return clearAuthCookies(NextResponse.next());
    return NextResponse.next();
  }

  const required = requiredWorkspace(pathname);
  if (!required) return NextResponse.next();

  if (!hasSession) return redirectTo(request, "/login");

  const me = await fetchMe(request);
  if (me === "unauthenticated") {
    return clearAuthCookies(redirectTo(request, "/login?reason=session_expired"));
  }
  if (me === "unavailable") {
    return new NextResponse("Service temporarily unavailable.", { status: 503 });
  }
  const stale = await staleCookieNames(request);
  if (me.workspace !== required) {
    return expireCookies(NextResponse.rewrite(new URL("/access-denied", request.url), { status: 403 }), stale);
  }
  return expireCookies(NextResponse.next(), stale);
}

export const config = {
  matcher: ["/login", "/super-admin/:path*", "/company/:path*"],
};
