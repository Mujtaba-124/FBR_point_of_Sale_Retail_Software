import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export function DashboardCard({
  title,
  icon: Icon,
  action,
  className,
  children,
  labelledBy,
}: {
  title: string;
  icon?: LucideIcon;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
  labelledBy?: string;
}) {
  const headingId = labelledBy ?? `card-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <section
      aria-labelledby={headingId}
      className={cn(
        "flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm",
        className,
      )}
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2
          id={headingId}
          className="flex items-center gap-2.5 text-[15px] font-semibold text-slate-900"
        >
          {Icon && (
            <span className="flex size-8 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
              <Icon className="size-4" aria-hidden="true" />
            </span>
          )}
          {title}
        </h2>
        {action}
      </div>
      <div className="flex flex-1 flex-col">{children}</div>
    </section>
  );
}

export function DetailList({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="divide-y divide-slate-100">
      {items.map(({ label, value }) => (
        <div
          key={label}
          className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-2.5 first:pt-0 last:pb-0"
        >
          <dt className="text-sm text-slate-500">{label}</dt>
          <dd className="min-w-0 break-words text-right text-sm font-medium text-slate-900">
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
