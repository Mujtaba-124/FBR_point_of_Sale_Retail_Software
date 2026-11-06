import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { AlertCircle } from "lucide-react";

import { RolesView } from "@/components/company/roles/roles-view";
import { AdminOnly } from "@/components/company/users/users-section";
import { StateCard } from "@/components/super-admin/states";
import { Topbar } from "@/components/super-admin/topbar";
import type { PermissionCatalog, RoleListPayload } from "@/lib/api/types";
import { fetchBackend } from "@/lib/auth-server";

export const metadata: Metadata = {
  title: "Roles & Permissions | Cheena FBR POS Software",
  robots: { index: false },
};

async function RolesSection() {
  const [roles, catalog] = await Promise.all([
    fetchBackend<RoleListPayload>("/api/v1/company/roles"),
    fetchBackend<PermissionCatalog>("/api/v1/company/permissions"),
  ]);
  if (roles.status === "unauthenticated" || catalog.status === "unauthenticated") {
    redirect("/login?reason=session_expired");
  }
  if (roles.status === "forbidden" || catalog.status === "forbidden") return <AdminOnly />;
  if (roles.status !== "ok" || catalog.status !== "ok") {
    return (
      <StateCard icon={AlertCircle} title="Roles unavailable" tone="error" role="alert">
        <p>The roles could not be loaded. Please refresh in a moment.</p>
      </StateCard>
    );
  }
  return <RolesView initial={roles.data.items} catalog={catalog.data} />;
}

export default function RolesPage() {
  return (
    <Suspense
      fallback={
        <div className="space-y-6">
          <Topbar
            title="Roles & Permissions"
            description="Define what each role can access in the Company Workspace."
          />
          <div aria-busy="true" aria-label="Loading roles" className="h-80 animate-pulse rounded-2xl bg-slate-200/70" />
        </div>
      }
    >
      <RolesSection />
    </Suspense>
  );
}
