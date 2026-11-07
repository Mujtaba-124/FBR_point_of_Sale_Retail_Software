import Link from "next/link";
import { redirect } from "next/navigation";
import { AlertCircle, LayoutDashboard, ShieldAlert } from "lucide-react";

import { CompanyDashboardView } from "@/components/company/dashboard-view";
import { navFor } from "@/components/company/nav-items";
import { StateCard } from "@/components/super-admin/states";
import type { CompanyDashboard } from "@/lib/api/types";
import { fetchBackendDetailed, getCurrentUser } from "@/lib/auth-server";

const SHOP_CONTEXT_ERRORS = new Set(["invalid_shop_id", "shop_not_found", "shop_inactive"]);

function summaryPath(shop: string | null): `/api/v1/${string}` {
  const base = "/api/v1/company/dashboard/summary" as const;
  return shop ? `${base}?${new URLSearchParams({ shop_id: shop })}` : base;
}

/** Request-time data for the Company dashboard. Render inside <Suspense>. */
export async function CompanyDashboardSection({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
} = {}) {
  const params = searchParams ? await searchParams : {};
  const shop = typeof params.shop === "string" && params.shop ? params.shop : null;
  const me = await getCurrentUser();
  if (me.status === "unauthenticated") redirect("/login?reason=session_expired");
  if (me.status !== "ok") return <CompanyDashboardError />;

  // The company-wide summary is Company Admin only; Company Users get their modules.
  if (me.data.access_category !== "company_admin") {
    const modules = navFor(me.data.access_category, (me.data as { permissions?: string[] }).permissions ?? []).filter((m) => m.key !== "dashboard");
    return <CompanyUserWelcome modules={modules.map(({ key, label, href }) => ({ key, label, href: href ?? "" }))} />;
  }

  let result = await fetchBackendDetailed<CompanyDashboard>(summaryPath(shop));
  if (result.status === "rejected" && shop && SHOP_CONTEXT_ERRORS.has(result.code ?? "")) {
    // The backend refused the selected shop (inactive, unknown or invalid). Show
    // All Shops; the shop context provider explains why and cleans up the URL.
    result = await fetchBackendDetailed<CompanyDashboard>(summaryPath(null));
  }
  if (result.status === "unauthenticated") redirect("/login?reason=session_expired");
  if (result.status === "forbidden") {
    // Subscription restrictions are shown by the workspace layout; anything else is denial.
    return (
      <StateCard icon={ShieldAlert} title="Access denied" tone="error" role="alert">
        <p>Your account does not have access to the Company dashboard.</p>
      </StateCard>
    );
  }
  if (result.status !== "ok") return <CompanyDashboardError />;
  return <CompanyDashboardView data={result.data} />;
}

export function CompanyDashboardError() {
  return (
    <StateCard icon={AlertCircle} title="Dashboard unavailable" tone="error" role="alert">
      <p>The dashboard data could not be loaded. Please refresh in a moment.</p>
    </StateCard>
  );
}

export function CompanyUserWelcome({ modules = [] }: { modules?: { key: string; label: string; href: string }[] }) {
  if (modules.length === 0) {
    return (
      <StateCard icon={LayoutDashboard} title="Welcome to the Company Workspace" role="status">
        <p>No released modules are assigned to your account yet.</p>
        <p>Modules your Company Admin grants appear here as soon as they are available.</p>
      </StateCard>
    );
  }
  return (
    <StateCard icon={LayoutDashboard} title="Welcome to the Company Workspace" role="status">
      <p>Open the modules assigned to you:</p>
      <ul className="mt-2 flex flex-wrap justify-center gap-2">
        {modules.map((m) => (
          <li key={m.key}>
            <Link href={m.href} className="font-medium text-primary underline-offset-4 hover:underline">
              {m.label}
            </Link>
          </li>
        ))}
      </ul>
    </StateCard>
  );
}
