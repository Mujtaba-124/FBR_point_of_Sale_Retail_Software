import { TrendingUp } from "lucide-react";

import { DashboardCard } from "@/components/super-admin/dashboard-card";
import type { Subscription } from "@/lib/api/types";
import { formatDate, pluralDays } from "@/lib/format";
import { cn } from "@/lib/utils";

const BAR_TONE: Partial<Record<Subscription["status"], string>> = {
  active: "bg-gradient-to-r from-[#0b1a3d] to-[#1b4fc4]",
  expiring_soon: "bg-gradient-to-r from-amber-500 to-amber-400",
  expired: "bg-red-500",
  scheduled: "bg-blue-300",
};

function DateLabel({ label, date, align }: { label: string; date: string | null; align: "start" | "end" }) {
  return (
    <div className={align === "end" ? "text-right" : undefined}>
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <p className="text-sm font-semibold text-slate-900">{formatDate(date)}</p>
    </div>
  );
}

export function SubscriptionProgress({
  subscription: s,
  className,
}: {
  subscription: Subscription;
  className?: string;
}) {
  const measurable = s.total_days !== null && s.progress_percent !== null;

  return (
    <DashboardCard
      title="Subscription Period"
      icon={TrendingUp}
      className={className}
      action={
        measurable ? (
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold tabular-nums text-slate-700">
            {s.progress_percent}% elapsed
          </span>
        ) : undefined
      }
    >
      {!measurable ? (
        <p className="text-sm text-slate-500">
          Progress is shown once a valid subscription period is configured.
        </p>
      ) : (
        <div className="flex flex-1 flex-col gap-4">
          <div className="flex items-end justify-between gap-4">
            <DateLabel label="Start Date" date={s.start_date} align="start" />
            <DateLabel label="Expiry Date" date={s.expiry_date} align="end" />
          </div>
          <div
            role="progressbar"
            aria-label="Subscription period elapsed"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={s.progress_percent!}
            aria-valuetext={`${pluralDays(s.days_used!)} of ${pluralDays(s.total_days!)} used`}
            className="h-4 overflow-hidden rounded-full bg-slate-100 ring-1 ring-inset ring-slate-200"
          >
            <div
              className={cn("h-full rounded-full", BAR_TONE[s.status] ?? "bg-slate-400")}
              style={{ width: `${Math.min(100, Math.max(0, s.progress_percent!))}%` }}
            />
          </div>
          <dl className="grid grid-cols-3 gap-3 text-center">
            {[
              { label: "Days Used", value: s.days_used! },
              { label: "Days Remaining", value: s.days_remaining! },
              { label: "Total Duration", value: s.total_days! },
            ].map(({ label, value }) => (
              <div
                key={label}
                className="rounded-xl bg-slate-50 px-2 py-3 ring-1 ring-inset ring-slate-100"
              >
                <dt className="text-xs font-medium text-slate-500">{label}</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums text-slate-900">
                  {value.toLocaleString("en-US")}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-auto text-xs leading-relaxed text-slate-500">
            Calendar days in Pakistan time. The expiry date is the last valid day.
          </p>
        </div>
      )}
    </DashboardCard>
  );
}
