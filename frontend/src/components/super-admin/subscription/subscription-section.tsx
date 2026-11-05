import { redirect } from "next/navigation";
import { CalendarDays } from "lucide-react";

import { DashboardError, DashboardForbidden } from "@/components/super-admin/states";
import { HISTORY_PAGE_SIZE } from "@/components/super-admin/subscription/constants";
import { SubscriptionManagementView } from "@/components/super-admin/subscription/subscription-management-view";
import type { RenewalPage, SubscriptionManagement } from "@/lib/api/types";
import { fetchBackend } from "@/lib/auth-server";
import { formatDate } from "@/lib/format";

/** Request-time data for the Subscription Management page. Render inside <Suspense>. */
export async function SubscriptionSection() {
  const [overview, history] = await Promise.all([
    fetchBackend<SubscriptionManagement>("/api/v1/super-admin/subscription"),
    fetchBackend<RenewalPage>(
      `/api/v1/super-admin/subscription/renewals?limit=${HISTORY_PAGE_SIZE}&offset=0`,
    ),
  ]);

  if (overview.status === "unauthenticated" || history.status === "unauthenticated") {
    redirect("/login?reason=session_expired");
  }
  if (overview.status === "forbidden" || history.status === "forbidden") {
    return <DashboardForbidden />;
  }
  if (overview.status !== "ok" || history.status !== "ok") return <DashboardError />;

  return (
    <>
      <p className="mb-4 flex items-center gap-1.5 text-xs font-medium text-slate-500">
        <CalendarDays className="size-3.5" aria-hidden="true" />
        As of {formatDate(overview.data.today)} (Pakistan time)
      </p>
      <SubscriptionManagementView data={overview.data} history={history.data} />
    </>
  );
}
