import { CompanyAccountCard } from "@/components/super-admin/company-account-card";
import { RemainingDaysCard } from "@/components/super-admin/remaining-days-card";
import { NotConfiguredNotice } from "@/components/super-admin/states";
import {
  SubscriptionDetails,
  SubscriptionStatusCard,
} from "@/components/super-admin/subscription-cards";
import { SubscriptionProgress } from "@/components/super-admin/subscription-progress";
import type { SuperAdminDashboard } from "@/lib/api/types";

/**
 * Pure presentation of the backend's dashboard payload.
 *
 * Layout: three summary cards per row from xl (1280px) up; below that two per
 * row with the Company Account card spanning the full width, so no card is
 * squeezed into a narrow, over-tall column next to the sidebar.
 */
export function DashboardView({ data }: { data: SuperAdminDashboard }) {
  const { subscription, company, company_admin } = data;
  return (
    <div className="space-y-5">
      {subscription.status === "not_configured" && <NotConfiguredNotice />}

      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        <RemainingDaysCard subscription={subscription} />
        <SubscriptionStatusCard subscription={subscription} />
        <CompanyAccountCard
          companyName={company.name}
          contact={company_admin}
          className="md:col-span-2 xl:col-span-1"
        />
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <SubscriptionProgress subscription={subscription} className="xl:col-span-2" />
        <SubscriptionDetails subscription={subscription} companyName={company.name} />
      </div>
    </div>
  );
}
