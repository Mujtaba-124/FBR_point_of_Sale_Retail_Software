import { ApiError, apiFetch } from "@/lib/api/client";
import { WORKSPACE_PATHS, type CurrentUser, type LoginResponse } from "@/lib/api/types";
import type { LoginValues } from "@/lib/validations/auth";

/** Start a session. The backend sets the HttpOnly session cookie. */
export async function signIn(values: LoginValues): Promise<CurrentUser> {
  const { user } = await apiFetch<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(values),
  });
  return user;
}

/** Revoke the current session. An already-expired session counts as signed out. */
export async function signOut(): Promise<void> {
  try {
    await apiFetch<void>("/auth/logout", { method: "POST" });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return;
    throw error;
  }
}

export function workspacePath(user: Pick<CurrentUser, "workspace">): string {
  return WORKSPACE_PATHS[user.workspace];
}
