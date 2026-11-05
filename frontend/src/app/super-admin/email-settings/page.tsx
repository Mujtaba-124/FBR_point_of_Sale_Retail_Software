import type { Metadata } from "next";
import { Suspense } from "react";

import { EmailSettingsSection } from "@/components/super-admin/email/email-settings-section";
import { RefreshButton } from "@/components/super-admin/refresh-button";
import { DashboardSkeleton } from "@/components/super-admin/states";
import { Topbar } from "@/components/super-admin/topbar";

export const metadata: Metadata = {
  title: "Email Settings | Cheena FBR POS Software",
  robots: { index: false },
};

export default function EmailSettingsPage() {
  return (
    <div className="space-y-6">
      <Topbar
        title="Email Settings"
        description="Outgoing email (SMTP) configuration, sending control and tests."
        actions={<RefreshButton />}
      />
      <Suspense fallback={<DashboardSkeleton />}>
        <EmailSettingsSection />
      </Suspense>
    </div>
  );
}
