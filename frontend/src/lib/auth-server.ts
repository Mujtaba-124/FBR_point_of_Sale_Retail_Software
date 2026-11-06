import { headers } from "next/headers";
import { cache } from "react";

import type { CurrentUser, WorkspaceResponse } from "@/lib/api/types";

const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

export type BackendResult<T> =
  | { status: "ok"; data: T }
  | { status: "unauthenticated" }
  | { status: "forbidden"; code: string | null }
  | { status: "unavailable" };

async function errorCode(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { error?: { code?: string } };
    return body.error?.code ?? null;
  } catch {
    return null;
  }
}

/**
 * Server-only GET to the backend, forwarding the browser's cookies. The
 * backend makes every authorization decision (401/403); the frontend never
 * trusts a role of its own. Must run inside <Suspense> (it reads the request).
 */
export async function fetchBackend<T>(path: `/api/v1/${string}`): Promise<BackendResult<T>> {
  const cookie = (await headers()).get("cookie") ?? "";
  let response: Response;
  try {
    response = await fetch(`${backendUrl}${path}`, {
      headers: { cookie },
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    return { status: "unavailable" };
  }
  if (response.status === 200) return { status: "ok", data: (await response.json()) as T };
  if (response.status === 401) return { status: "unauthenticated" };
  if (response.status === 403) return { status: "forbidden", code: await errorCode(response) };
  return { status: "unavailable" };
}

/** Like fetchBackend, but keeps the error code of 404/409/422 answers. */
export type DetailedBackendResult<T> =
  | BackendResult<T>
  | { status: "rejected"; httpStatus: number; code: string | null };

export async function fetchBackendDetailed<T>(
  path: `/api/v1/${string}`,
): Promise<DetailedBackendResult<T>> {
  const cookie = (await headers()).get("cookie") ?? "";
  let response: Response;
  try {
    response = await fetch(`${backendUrl}${path}`, {
      headers: { cookie },
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    return { status: "unavailable" };
  }
  if ([404, 409, 422].includes(response.status)) {
    return { status: "rejected", httpStatus: response.status, code: await errorCode(response) };
  }
  if (response.status === 200) return { status: "ok", data: (await response.json()) as T };
  if (response.status === 401) return { status: "unauthenticated" };
  if (response.status === 403) return { status: "forbidden", code: await errorCode(response) };
  return { status: "unavailable" };
}

const WORKSPACE_ENDPOINTS = {
  super_admin: "/api/v1/super-admin/workspace",
  company: "/api/v1/company/workspace",
} as const;

export type WorkspaceAccess = BackendResult<WorkspaceResponse>;

export function checkWorkspaceAccess(
  workspace: keyof typeof WORKSPACE_ENDPOINTS,
): Promise<WorkspaceAccess> {
  return fetchBackend<WorkspaceResponse>(WORKSPACE_ENDPOINTS[workspace]);
}

/**
 * The signed-in user, fetched at most once per server render: React's
 * `cache` dedupes the desktop sidebar and mobile drawer profile, which both
 * render it in the same request.
 */
export const getCurrentUser = cache(
  (): Promise<BackendResult<CurrentUser>> => fetchBackend<CurrentUser>("/api/v1/auth/me"),
);
