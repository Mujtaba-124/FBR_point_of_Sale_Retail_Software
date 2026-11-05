"use client";

import { useRef, useState } from "react";
import { AlertCircle, ChevronLeft, ChevronRight, ListChecks, Loader2 } from "lucide-react";

import { DashboardCard } from "@/components/super-admin/dashboard-card";
import { Button } from "@/components/ui/button";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { OutboxStatus, ReminderHistoryItem, ReminderHistoryPage } from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { REMINDER_PAGE_SIZE as PAGE_SIZE } from "@/components/super-admin/email/reminder-constants";

export { PAGE_SIZE };

export const DELIVERY_STATUS: Record<OutboxStatus, { label: string; className: string }> = {
  pending: { label: "Pending", className: "bg-slate-100 text-slate-700 ring-slate-500/20" },
  processing: { label: "Processing", className: "bg-blue-50 text-blue-700 ring-blue-600/20" },
  retry_scheduled: {
    label: "Retry Scheduled",
    className: "bg-amber-50 text-amber-800 ring-amber-600/25",
  },
  accepted: {
    label: "Accepted by SMTP Server",
    className: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  },
  failed_permanent: {
    label: "Failed Permanently",
    className: "bg-red-50 text-red-700 ring-red-600/20",
  },
  cancelled_obsolete: {
    label: "Cancelled / Obsolete",
    className: "bg-slate-100 text-slate-600 ring-slate-500/20",
  },
  cancelled: { label: "Cancelled", className: "bg-slate-100 text-slate-600 ring-slate-500/20" },
};

const FILTERS: (OutboxStatus | "all")[] = [
  "all",
  "accepted",
  "pending",
  "retry_scheduled",
  "failed_permanent",
  "cancelled_obsolete",
  "cancelled",
];

const CATEGORY_LABEL = { super_admin: "Super Admin", company_admin: "Company Admin" } as const;

export function historyPath(status: OutboxStatus | "all", offset: number): string {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
  if (status !== "all") params.set("status", status);
  return `/super-admin/email-settings/reminder-history?${params}`;
}

export function ReminderActivity({ initial }: { initial: ReminderHistoryPage }) {
  const [page, setPage] = useState(initial);
  const [status, setStatus] = useState<OutboxStatus | "all">("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const request = useRef(0);

  async function load(nextStatus: OutboxStatus | "all", offset: number) {
    const id = ++request.current;
    setStatus(nextStatus);
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<ReminderHistoryPage>(historyPath(nextStatus, offset));
      if (id === request.current) setPage(data);
    } catch (e) {
      if (id === request.current) {
        setError(
          e instanceof ApiError ? e : new ApiError(0, "unknown", "The activity could not be loaded."),
        );
      }
    } finally {
      if (id === request.current) setLoading(false);
    }
  }

  const all = Object.values(page.counts).reduce((a, b) => a + b, 0);
  const first = page.total ? page.offset + 1 : 0;
  const last = Math.min(page.offset + page.items.length, page.total);

  return (
    <DashboardCard
      title="Reminder Activity"
      icon={ListChecks}
      action={
        <Button
          type="button"
          variant="outline"
          className="h-8 text-xs"
          disabled={loading}
          onClick={() => void load(status, page.offset)}
        >
          {loading && <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />}
          Refresh
        </Button>
      }
    >
      <div className="space-y-4">
        <div role="group" aria-label="Filter by delivery status" className="flex flex-wrap gap-2">
          {FILTERS.map((f) => {
            const count = f === "all" ? all : page.counts[f];
            const active = status === f;
            return (
              <button
                key={f}
                type="button"
                aria-pressed={active}
                onClick={() => void load(f, 0)}
                className={cn(
                  "rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/50",
                  active
                    ? "bg-blue-700 text-white ring-blue-700"
                    : "bg-white text-slate-700 ring-slate-200 hover:bg-slate-50",
                )}
              >
                {f === "all" ? "All" : DELIVERY_STATUS[f].label} ({count})
              </button>
            );
          })}
        </div>

        <p className="text-xs text-slate-500">
          &quot;Accepted by SMTP Server&quot; means the mail server took the message; it does not
          prove it reached the inbox.
        </p>

        {error && (
          <div
            role="alert"
            className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
          >
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <p>{error.message}</p>
          </div>
        )}

        <div aria-busy={loading} className={cn(loading && "opacity-60")}>
          {page.items.length === 0 ? (
            <p className="rounded-xl border border-dashed border-slate-200 p-6 text-center text-sm text-slate-600">
              {status === "all"
                ? "No reminders yet. They appear here once the scheduler queues them."
                : "No reminders with this status."}
            </p>
          ) : (
            <>
              <div className="hidden overflow-x-auto md:block">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">Subscription reminder deliveries</caption>
                  <thead className="text-xs text-slate-500">
                    <tr className="border-b border-slate-200">
                      <th scope="col" className="py-2 pr-3 font-medium">Scheduled</th>
                      <th scope="col" className="py-2 pr-3 font-medium">Stage</th>
                      <th scope="col" className="py-2 pr-3 font-medium">Recipient</th>
                      <th scope="col" className="py-2 pr-3 font-medium">Status</th>
                      <th scope="col" className="py-2 pr-3 font-medium">Last attempt</th>
                      <th scope="col" className="py-2 font-medium">Attempts</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {page.items.map((item) => (
                      <tr key={item.id} className="align-top">
                        <td className="py-2.5 pr-3 whitespace-nowrap text-slate-900">
                          {formatDate(item.scheduled_date)}
                        </td>
                        <td className="py-2.5 pr-3 text-slate-700">{item.stage}</td>
                        <td className="py-2.5 pr-3">
                          <span className="block text-slate-900">{item.recipient}</span>
                          <span className="block text-xs text-slate-500">{categories(item)}</span>
                        </td>
                        <td className="py-2.5 pr-3">
                          <StatusPill status={item.status} />
                          {item.reason && (
                            <span className="mt-1 block max-w-xs text-xs text-slate-500">
                              {item.reason}
                            </span>
                          )}
                        </td>
                        <td className="py-2.5 pr-3 whitespace-nowrap text-slate-700">
                          {formatDateTime(item.last_attempt_at)}
                        </td>
                        <td className="py-2.5 text-slate-700">
                          {item.attempt_count}/{item.max_attempts}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul className="space-y-3 md:hidden" aria-label="Subscription reminder deliveries">
                {page.items.map((item) => (
                  <li key={item.id} className="rounded-xl border border-slate-200 p-3 text-sm">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <span className="font-medium text-slate-900">
                        {formatDate(item.scheduled_date)} · {item.stage}
                      </span>
                      <StatusPill status={item.status} />
                    </div>
                    <p className="mt-1 break-words text-slate-700">
                      {item.recipient}{" "}
                      <span className="text-xs text-slate-500">({categories(item)})</span>
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      Last attempt {formatDateTime(item.last_attempt_at)} · Attempts{" "}
                      {item.attempt_count}/{item.max_attempts}
                    </p>
                    {item.reason && <p className="mt-1 text-xs text-slate-500">{item.reason}</p>}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>

        {page.total > PAGE_SIZE && (
          <nav
            aria-label="Reminder activity pages"
            className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600"
          >
            <span>
              {first}–{last} of {page.total}
            </span>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                className="h-8 gap-1"
                disabled={loading || page.offset === 0}
                onClick={() => void load(status, Math.max(0, page.offset - PAGE_SIZE))}
              >
                <ChevronLeft className="size-4" aria-hidden="true" />
                Previous
              </Button>
              <Button
                type="button"
                variant="outline"
                className="h-8 gap-1"
                disabled={loading || last >= page.total}
                onClick={() => void load(status, page.offset + PAGE_SIZE)}
              >
                Next
                <ChevronRight className="size-4" aria-hidden="true" />
              </Button>
            </div>
          </nav>
        )}
      </div>
    </DashboardCard>
  );
}

function categories(item: ReminderHistoryItem): string {
  return item.recipient_categories.map((c) => CATEGORY_LABEL[c]).join(" + ");
}

function StatusPill({ status }: { status: OutboxStatus }) {
  const meta = DELIVERY_STATUS[status];
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset",
        meta.className,
      )}
    >
      {meta.label}
    </span>
  );
}
