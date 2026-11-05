import type { Metadata } from "next";
import { Suspense } from "react";

import { WorkspaceGate, WorkspaceLoading } from "@/components/auth/workspace-gate";
import { PlaceholderCard } from "@/components/auth/workspace-shell";

export const metadata: Metadata = {
  title: "Company Workspace | Cheena FBR POS Software",
  robots: { index: false },
};

const ROLE_LABELS = {
  company_admin: "Company Admin",
  company_user: "Company User",
  super_admin: "Super Admin",
} as const;

export default function CompanyPage() {
  return (
    <Suspense fallback={<WorkspaceLoading />}>
      <WorkspaceGate workspace="company" label="Company Workspace">
        {({ user }) => (
          <PlaceholderCard title="Company workspace">
            <p>
              Signed in as <span className="font-medium text-slate-900">{user.email}</span> (
              {ROLE_LABELS[user.access_category]}).
            </p>
            <p>Business modules will be added in upcoming phases.</p>
          </PlaceholderCard>
        )}
      </WorkspaceGate>
    </Suspense>
  );
}
