import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  CircleDashed,
  CircleSlash,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import type { SubscriptionStatus } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export const STATUS_META: Record<
  SubscriptionStatus,
  { label: string; icon: LucideIcon; className: string }
> = {
  active: {
    label: "Active",
    icon: CheckCircle2,
    className: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  },
  expiring_soon: {
    label: "Expiring Soon",
    icon: AlertTriangle,
    className: "bg-amber-50 text-amber-800 ring-amber-600/25",
  },
  expired: {
    label: "Expired",
    icon: XCircle,
    className: "bg-red-50 text-red-700 ring-red-600/20",
  },
  scheduled: {
    label: "Not Started",
    icon: CalendarClock,
    className: "bg-blue-50 text-blue-700 ring-blue-600/20",
  },
  not_configured: {
    label: "Not Configured",
    icon: CircleDashed,
    className: "bg-slate-100 text-slate-700 ring-slate-500/20",
  },
  invalid: {
    label: "Invalid Dates",
    icon: CircleSlash,
    className: "bg-red-50 text-red-700 ring-red-600/20",
  },
};

/** Colour is never the only signal: every status has an icon and a text label. */
export function StatusBadge({ status, className }: { status: SubscriptionStatus; className?: string }) {
  const { label, icon: Icon, className: tone } = STATUS_META[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset",
        tone,
        className,
      )}
    >
      <Icon className="size-3.5" aria-hidden="true" />
      {label}
    </span>
  );
}
