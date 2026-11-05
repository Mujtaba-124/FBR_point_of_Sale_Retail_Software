import type { Metadata } from "next";
import { Suspense } from "react";

import { RefreshButton } from "@/components/super-admin/refresh-button";
import { DashboardSkeleton } from "@/components/super-admin/states";
import { SubscriptionSection } from "@/components/super-admin/subscription/subscription-section";
import { Topbar } from "@/components/super-admin/topbar";

export const metadata: Metadata = {
  title: "Subscription Management | Cheena FBR POS Software",
  robots: { index: false },
};

export default function SubscriptionManagementPage() {
  return (
    <div className="space-y-6">
      <Topbar
        title="Subscription Management"
        description="Current subscription, renewals and renewal history."
        actions={<RefreshButton />}
      />
      <Suspense fallback={<DashboardSkeleton />}>
        <SubscriptionSection />
      </Suspense>
    </div>
  );
}
