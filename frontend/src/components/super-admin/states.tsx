import type { ReactNode } from "react";
import { AlertCircle, CircleDashed, ShieldAlert, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export function StateCard({
  icon: Icon,
  title,
  children,
  tone = "neutral",
  role,
}: {
  icon: LucideIcon;
  title: string;
  children: ReactNode;
  tone?: "neutral" | "error";
  role?: "alert" | "status";
}) {
  return (
    <section
      role={role}
      className="flex flex-col items-center rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center"
    >
      <span
        className={cn(
          "mb-4 flex size-12 items-center justify-center rounded-2xl",
          tone === "error" ? "bg-red-50 text-red-600" : "bg-blue-50 text-blue-700",
        )}
      >
        <Icon className="size-6" aria-hidden="true" />
      </span>
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      <div className="mt-2 max-w-md space-y-2 text-sm text-slate-500">{children}</div>
    </section>
  );
}

export function NotConfiguredNotice() {
  return (
    <StateCard icon={CircleDashed} title="Subscription not configured" role="status">
      <p>No subscription record exists for this company yet, so no dates or days are shown.</p>
      <p>
        The initial subscription is set up by the system operator. Renewal becomes available after
        that.
      </p>
    </StateCard>
  );
}

export function DashboardError() {
  return (
    <StateCard icon={AlertCircle} title="Dashboard unavailable" tone="error" role="alert">
      <p>The server could not be reached. Please refresh in a moment.</p>
    </StateCard>
  );
}

export function DashboardForbidden() {
  return (
    <StateCard icon={ShieldAlert} title="Access denied" tone="error" role="alert">
      <p>Your account does not have access to the Super Admin workspace.</p>
    </StateCard>
  );
}

export function DashboardSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading dashboard" className="space-y-5">
      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className={`h-52 animate-pulse rounded-2xl bg-slate-200/70 ${i === 2 ? "md:col-span-2 xl:col-span-1" : ""}`}
          />
        ))}
      </div>
      <div className="grid gap-5 xl:grid-cols-3">
        <div className="h-60 animate-pulse rounded-2xl bg-slate-200/70 xl:col-span-2" />
        <div className="h-60 animate-pulse rounded-2xl bg-slate-200/70" />
      </div>
      <span className="sr-only">Loading dashboard…</span>
    </div>
  );
}
