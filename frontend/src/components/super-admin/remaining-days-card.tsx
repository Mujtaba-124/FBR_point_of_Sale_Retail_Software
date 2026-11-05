import { Hourglass } from "lucide-react";

import { StatusBadge } from "@/components/super-admin/status-badge";
import type { Subscription } from "@/lib/api/types";
import { formatDate, pluralDays } from "@/lib/format";

function caption(s: Subscription): string {
  switch (s.status) {
    case "not_configured":
      return "No subscription has been configured yet.";
    case "invalid":
      return "The stored subscription dates are invalid.";
    case "scheduled":
      return `Starts on ${formatDate(s.start_date)} (in ${pluralDays(s.days_until_start ?? 0)}).`;
    case "expired":
      return `Expired after ${formatDate(s.expiry_date)}.`;
    default:
      return s.days_remaining === 0
        ? `Today is the last valid day (${formatDate(s.expiry_date)}).`
        : `Valid through ${formatDate(s.expiry_date)}.`;
  }
}

/** The headline number comes straight from the backend calculation. */
export function RemainingDaysCard({ subscription }: { subscription: Subscription }) {
  const known = subscription.days_remaining !== null;
  return (
    <section
      aria-labelledby="remaining-days-heading"
      className="relative flex flex-col overflow-hidden rounded-2xl bg-gradient-to-br from-[#0b1a3d] via-[#10275c] to-[#1b4fc4] p-5 text-white shadow-md"
    >
      <div
        aria-hidden="true"
        className="absolute -right-10 -top-10 size-40 rounded-full border border-white/10"
      />
      <div className="relative flex items-start justify-between gap-3">
        <h2
          id="remaining-days-heading"
          className="flex items-center gap-2.5 text-[15px] font-semibold text-blue-50"
        >
          <span className="flex size-8 items-center justify-center rounded-lg bg-white/10 ring-1 ring-white/15">
            <Hourglass className="size-4" aria-hidden="true" />
          </span>
          Remaining Days
        </h2>
        <StatusBadge status={subscription.status} className="bg-white/95" />
      </div>
      <p className="relative mt-5 flex items-baseline gap-2">
        <span
          className="text-5xl font-semibold tracking-tight tabular-nums"
          data-testid="days-remaining"
        >
          {known ? subscription.days_remaining!.toLocaleString("en-US") : "—"}
        </span>
        {known && (
          <span className="text-sm text-blue-100/85">
            {subscription.days_remaining === 1 ? "day left" : "days left"}
          </span>
        )}
      </p>
      <p className="relative mt-auto pt-4 text-sm text-blue-100/90">{caption(subscription)}</p>
    </section>
  );
}
