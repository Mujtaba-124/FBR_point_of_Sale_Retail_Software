import { ClipboardList } from "lucide-react";

import { DashboardCard, DetailList } from "@/components/super-admin/dashboard-card";
import { RemainingDaysCard } from "@/components/super-admin/remaining-days-card";
import { NotConfiguredNotice } from "@/components/super-admin/states";
import { STATUS_META } from "@/components/super-admin/status-badge";
import { SubscriptionStatusCard } from "@/components/super-admin/subscription-cards";
import { SubscriptionProgress } from "@/components/super-admin/subscription-progress";
import { RenewalHistory } from "@/components/super-admin/subscription/renewal-history";
import { RenewalPanel } from "@/components/super-admin/subscription/renewal-panel";
import type { RenewalPage, SubscriptionManagement } from "@/lib/api/types";
import { formatDate, pluralDays } from "@/lib/format";

function OverviewDetails({ data }: { data: SubscriptionManagement }) {
  const s = data.subscription;
  return (
    <DashboardCard title="Subscription Overview" icon={ClipboardList}>
      <DetailList
        items={[
          { label: "Company Name", value: data.company.name ?? "Not configured" },
          { label: "Start Date", value: formatDate(s.start_date) },
          { label: "Expiry Date", value: formatDate(s.expiry_date) },
          { label: "Status", value: STATUS_META[s.status].label },
          { label: "Total Duration", value: s.total_days !== null ? pluralDays(s.total_days) : "—" },
          { label: "Days Used", value: s.days_used !== null ? pluralDays(s.days_used) : "—" },
          {
            label: "Last Renewal Date",
            value: s.last_renewed_on ? (
              formatDate(s.last_renewed_on)
            ) : (
              <span className="text-slate-500">No renewal recorded</span>
            ),
          },
        ]}
      />
    </DashboardCard>
  );
}

/** Pure presentation of the backend payloads; all values come from PostgreSQL. */
export function SubscriptionManagementView({
  data,
  history,
}: {
  data: SubscriptionManagement;
  history: RenewalPage;
}) {
  const s = data.subscription;
  // Remount history (back to page 1) whenever the backend data changes.
  const historyKey = `${history.total}:${history.items[0]?.id ?? "none"}`;

  return (
    <div className="space-y-5">
      {s.status === "not_configured" && <NotConfiguredNotice />}

      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        <RemainingDaysCard subscription={s} />
        <SubscriptionStatusCard subscription={s} />
        <RenewalPanel
          companyName={data.company.name}
          subscription={s}
          rules={data.renewal}
          today={data.today}
          className="md:col-span-2 xl:col-span-1"
        />
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <SubscriptionProgress subscription={s} className="xl:col-span-2" />
        <OverviewDetails data={data} />
      </div>

      <RenewalHistory key={historyKey} initial={history} />
    </div>
  );
}
