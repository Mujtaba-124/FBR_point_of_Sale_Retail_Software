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

async function fetchMe(request: NextRequest): Promise<MeResult> {
  try {
    const response = await fetch(`${backendUrl}/api/v1/auth/me`, {
      headers: { cookie: request.headers.get("cookie") ?? "" },
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

/** Drop dead session/CSRF cookies (the backend already revoked the session). */
function clearAuthCookies(response: NextResponse): NextResponse {
  for (const name of [...SESSION_COOKIE_NAMES, ...CSRF_COOKIE_NAMES]) {
    // "__Host-" cookies are only replaced by a Secure Set-Cookie with Path=/.
    response.cookies.set(name, "", { path: "/", maxAge: 0, secure: name.startsWith("__Host-") });
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
    if (typeof me === "object") return redirectTo(request, WORKSPACE_PATHS[me.workspace]);
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
  if (me.workspace !== required) {
    return NextResponse.rewrite(new URL("/access-denied", request.url), { status: 403 });
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/login", "/super-admin/:path*", "/company/:path*"],
};
