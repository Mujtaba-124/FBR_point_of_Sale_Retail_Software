import Link from "next/link";
import { ShieldAlert } from "lucide-react";

import { PlaceholderCard, WorkspaceShell } from "@/components/auth/workspace-shell";

export function AccessDenied() {
  return (
    <WorkspaceShell label="Access denied">
      <PlaceholderCard title="Access denied">
        <p className="flex items-center gap-2">
          <ShieldAlert className="size-4 text-destructive" aria-hidden="true" />
          Your account does not have access to this workspace.
        </p>
        <p>
          <Link
            href="/login"
            className="font-medium text-blue-700 underline-offset-4 hover:underline focus-visible:rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/50"
          >
            Go to your workspace
          </Link>
        </p>
      </PlaceholderCard>
    </WorkspaceShell>
  );
}
