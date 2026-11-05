import type { NextRequest } from "next/server";

/**
 * Same-origin proxy for the FastAPI backend.
 *
 * The browser only ever talks to this origin, so session cookies stay
 * first-party (no CORS, no third-party cookies). Only an allowlist of request
 * headers is forwarded, plus the client IP (X-Forwarded-For, set by the
 * Next.js server) so the backend's per-IP login limit sees real clients.
 */
const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

const FORWARDED_REQUEST_HEADERS = [
  "accept",
  "content-type",
  "cookie",
  "origin",
  "user-agent",
  "x-csrf-token",
  "x-forwarded-for",
];

const DROPPED_RESPONSE_HEADERS = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "keep-alive",
  "set-cookie",
  "transfer-encoding",
]);

type Context = { params: Promise<{ path: string[] }> };

function errorResponse(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message } }, { status });
}

async function forward(request: NextRequest, { params }: Context): Promise<Response> {
  const { path } = await params;
  if (path.some((segment) => segment === "." || segment === "..")) {
    return errorResponse(404, "not_found", "Not Found");
  }

  const target = new URL(`/api/v1/${path.map(encodeURIComponent).join("/")}`, backendUrl);
  target.search = request.nextUrl.search;

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  const hasBody = !["GET", "HEAD"].includes(request.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: "manual",
      cache: "no-store",
    });
  } catch {
    return errorResponse(
      503,
      "service_unavailable",
      "The service is temporarily unavailable. Please try again shortly.",
    );
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, name) => {
    if (!DROPPED_RESPONSE_HEADERS.has(name)) responseHeaders.set(name, value);
  });
  for (const cookie of upstream.headers.getSetCookie()) {
    responseHeaders.append("set-cookie", cookie);
  }

  return new Response(upstream.status === 204 ? null : upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export { forward as DELETE, forward as GET, forward as PATCH, forward as POST, forward as PUT };
