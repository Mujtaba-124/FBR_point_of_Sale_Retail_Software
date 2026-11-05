import type { Metadata } from "next";
import { Suspense } from "react";

import { DashboardSection } from "@/components/super-admin/dashboard-section";
import { RefreshButton } from "@/components/super-admin/refresh-button";
import { DashboardSkeleton } from "@/components/super-admin/states";
import { Topbar } from "@/components/super-admin/topbar";

export const metadata: Metadata = {
  title: "Super Admin Dashboard | Cheena FBR POS Software",
  robots: { index: false },
};

export default function SuperAdminDashboardPage() {
  return (
    <div className="space-y-6">
      <Topbar
        title="Dashboard"
        description="Subscription status and company account overview."
        actions={<RefreshButton />}
      />
      <Suspense fallback={<DashboardSkeleton />}>
        <DashboardSection />
      </Suspense>
    </div>
  );
}
