import { redirect } from "next/navigation";
import { CalendarDays } from "lucide-react";

import { DashboardView } from "@/components/super-admin/dashboard-view";
import { DashboardError, DashboardForbidden } from "@/components/super-admin/states";
import type { SuperAdminDashboard } from "@/lib/api/types";
import { fetchBackend } from "@/lib/auth-server";
import { formatDate } from "@/lib/format";

/** Request-time data for the dashboard. Render inside <Suspense>. */
export async function DashboardSection() {
  const result = await fetchBackend<SuperAdminDashboard>("/api/v1/super-admin/dashboard");

  if (result.status === "unauthenticated") redirect("/login?reason=session_expired");
  if (result.status === "forbidden") return <DashboardForbidden />;
  if (result.status === "unavailable") return <DashboardError />;

  return (
    <>
      <p className="mb-4 flex items-center gap-1.5 text-xs font-medium text-slate-500">
        <CalendarDays className="size-3.5" aria-hidden="true" />
        As of {formatDate(result.data.today)} (Pakistan time)
      </p>
      <DashboardView data={result.data} />
    </>
  );
}
