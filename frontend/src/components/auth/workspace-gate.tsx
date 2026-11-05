import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AccessDenied } from "@/components/auth/access-denied";
import { SubscriptionRestricted } from "@/components/auth/subscription-restricted";
import { PlaceholderCard, WorkspaceShell } from "@/components/auth/workspace-shell";
import {
  SUBSCRIPTION_ERROR_CODES,
  type SubscriptionErrorCode,
  type WorkspaceResponse,
} from "@/lib/api/types";
import { checkWorkspaceAccess } from "@/lib/auth-server";

function isSubscriptionCode(code: string | null): code is SubscriptionErrorCode {
  return code !== null && (SUBSCRIPTION_ERROR_CODES as readonly string[]).includes(code);
}

/**
 * Server-side gate for a workspace page: the backend's workspace endpoint
 * decides access. Must be rendered inside <Suspense> (it reads the request).
 */
export async function WorkspaceGate({
  workspace,
  label,
  children,
}: {
  workspace: "super_admin" | "company";
  label: string;
  children: (data: WorkspaceResponse) => ReactNode;
}) {
  const access = await checkWorkspaceAccess(workspace);

  if (access.status === "unauthenticated") redirect("/login?reason=session_expired");
  if (access.status === "forbidden") {
    // The backend blocks Company access when the subscription is not valid;
    // the session stays signed in so the user can read why and sign out.
    if (isSubscriptionCode(access.code)) return <SubscriptionRestricted code={access.code} />;
    return <AccessDenied />;
  }
  if (access.status === "unavailable") {
    return (
      <WorkspaceShell label={label} showLogout={false}>
        <PlaceholderCard title="Service temporarily unavailable">
          <p>The server could not be reached. Please refresh the page in a moment.</p>
        </PlaceholderCard>
      </WorkspaceShell>
    );
  }

  return (
    <WorkspaceShell label={label} userName={access.data.user.full_name}>
      {children(access.data)}
    </WorkspaceShell>
  );
}

export function WorkspaceLoading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50" aria-busy="true">
      <p className="text-sm text-slate-500">Loading your workspace…</p>
    </div>
  );
}
