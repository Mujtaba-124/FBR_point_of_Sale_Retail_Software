import { ClipboardList, ShieldCheck } from "lucide-react";

import { DashboardCard, DetailList } from "@/components/super-admin/dashboard-card";
import { STATUS_META, StatusBadge } from "@/components/super-admin/status-badge";
import type { Subscription } from "@/lib/api/types";
import { formatDate, pluralDays } from "@/lib/format";

function statusExplanation(s: Subscription): string {
  switch (s.status) {
    case "active":
      return `More than ${s.expiring_soon_threshold_days} days remain.`;
    case "expiring_soon":
      return `${s.expiring_soon_threshold_days} or fewer days remain. Renewal will be needed soon.`;
    case "expired":
      return "The subscription period has ended.";
    case "scheduled":
      return "The subscription period has not started yet.";
    case "invalid":
      return "The expiry date is before the start date.";
    default:
      return "No subscription record exists.";
  }
}

export function SubscriptionStatusCard({ subscription: s }: { subscription: Subscription }) {
  return (
    <DashboardCard title="Subscription Status" icon={ShieldCheck}>
      <div className="flex flex-1 flex-col gap-3">
        <StatusBadge status={s.status} className="self-start px-3 py-1.5 text-sm" />
        <p className="text-sm leading-relaxed text-slate-600">{statusExplanation(s)}</p>
        <div className="mt-auto pt-1">
          <DetailList
            items={[
              { label: "Start Date", value: formatDate(s.start_date) },
              { label: "Expiry Date", value: formatDate(s.expiry_date) },
            ]}
          />
        </div>
      </div>
    </DashboardCard>
  );
}

export function SubscriptionDetails({
  subscription: s,
  companyName,
}: {
  subscription: Subscription;
  companyName: string | null;
}) {
  return (
    <DashboardCard title="Subscription Information" icon={ClipboardList}>
      <DetailList
        items={[
          { label: "Company Account", value: companyName ?? "Not configured" },
          { label: "Subscription Start Date", value: formatDate(s.start_date) },
          { label: "Expiry Date", value: formatDate(s.expiry_date) },
          { label: "Current Status", value: STATUS_META[s.status].label },
          {
            label: "Total Duration",
            value: s.total_days !== null ? pluralDays(s.total_days) : "—",
          },
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
