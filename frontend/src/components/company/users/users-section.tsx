import { redirect } from "next/navigation";
import { AlertCircle, ShieldAlert } from "lucide-react";

import { USERS_PAGE_SIZE_SERVER } from "@/components/company/users/constants";
import { UsersView } from "@/components/company/users/users-view";
import { StateCard } from "@/components/super-admin/states";
import type { CompanyUserPage, RoleListPayload } from "@/lib/api/types";
import { fetchBackend } from "@/lib/auth-server";

/** Request-time data for User Management (Company Admin only; the backend decides). */
export async function UsersSection() {
  const [users, roles] = await Promise.all([
    fetchBackend<CompanyUserPage>(
      `/api/v1/company/users?limit=${USERS_PAGE_SIZE_SERVER}&offset=0&sort=name&order=asc`,
    ),
    fetchBackend<RoleListPayload>("/api/v1/company/roles"),
  ]);
  if (users.status === "unauthenticated" || roles.status === "unauthenticated") {
    redirect("/login?reason=session_expired");
  }
  if (users.status === "forbidden" || roles.status === "forbidden") return <AdminOnly />;
  if (users.status !== "ok" || roles.status !== "ok") {
    return (
      <StateCard icon={AlertCircle} title="Users unavailable" tone="error" role="alert">
        <p>The user list could not be loaded. Please refresh in a moment.</p>
      </StateCard>
    );
  }
  return <UsersView initial={users.data} roles={roles.data.items} />;
}

export function AdminOnly() {
  return (
    <StateCard icon={ShieldAlert} title="Access denied" tone="error" role="alert">
      <p>This area is available to the Company Admin only.</p>
    </StateCard>
  );
}
