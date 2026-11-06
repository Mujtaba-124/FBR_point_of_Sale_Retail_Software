import type { Metadata } from "next";
import { Suspense } from "react";

import { CompanyDashboardSection } from "@/components/company/dashboard-section";
import { CompanyDashboardSkeleton } from "@/components/company/dashboard-view";
import { RefreshButton } from "@/components/super-admin/refresh-button";
import { Topbar } from "@/components/super-admin/topbar";

export const metadata: Metadata = {
  title: "Dashboard | Cheena FBR POS Software",
  robots: { index: false },
};

export default function CompanyDashboardPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return (
    <div className="space-y-6">
      <Topbar
        title="Dashboard"
        description="Overview of your shops, sales uploads and FBR activity."
        actions={<RefreshButton />}
      />
      <Suspense fallback={<CompanyDashboardSkeleton />}>
        <CompanyDashboardSection searchParams={searchParams} />
      </Suspense>
    </div>
  );
}
