"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, History, Loader2 } from "lucide-react";

import { DashboardCard } from "@/components/super-admin/dashboard-card";
import { HISTORY_PAGE_SIZE } from "@/components/super-admin/subscription/constants";
import { Button } from "@/components/ui/button";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { RenewalPage } from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/format";

/** Read-only, newest first. There are deliberately no edit or delete controls. */
export function RenewalHistory({ initial }: { initial: RenewalPage }) {
  const [page, setPage] = useState(initial);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const from = page.total === 0 ? 0 : page.offset + 1;
  const to = page.offset + page.items.length;

  async function go(offset: number) {
    setLoading(true);
    setError(null);
    try {
      setPage(
        await apiFetch<RenewalPage>(
          `/super-admin/subscription/renewals?limit=${HISTORY_PAGE_SIZE}&offset=${offset}`,
        ),
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The renewal history could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <DashboardCard
      title="Renewal History"
      icon={History}
      action={
        page.total > 0 ? (
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
            {page.total} {page.total === 1 ? "renewal" : "renewals"}
          </span>
        ) : undefined
      }
    >
      {error && (
        <p role="alert" className="mb-3 text-sm text-destructive">
          {error}
        </p>
      )}

      {page.total === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center">
          <p className="text-sm font-medium text-slate-900">No renewals yet</p>
          <p className="mt-1 text-sm text-slate-500">
            Each renewal will appear here with its date, the previous and new expiry, and who
            performed it.
          </p>
        </div>
      ) : (
        <div aria-busy={loading || undefined} className={loading ? "opacity-60" : undefined}>
          {/* Table from md up */}
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Subscription renewals, newest first</caption>
              <thead>
                <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                  <th scope="col" className="py-2.5 pr-4 font-medium">Renewed</th>
                  <th scope="col" className="py-2.5 pr-4 font-medium">Previous expiry</th>
                  <th scope="col" className="py-2.5 pr-4 font-medium">New expiry</th>
                  <th scope="col" className="py-2.5 pr-4 font-medium">Renewed by</th>
                  <th scope="col" className="py-2.5 font-medium">Note</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {page.items.map((r) => (
                  <tr key={r.id} className="align-top">
                    <td className="whitespace-nowrap py-3 pr-4 tabular-nums text-slate-900">
                      {formatDateTime(r.renewed_at)}
                    </td>
                    <td className="whitespace-nowrap py-3 pr-4 text-slate-600">
                      {formatDate(r.previous_expiry_date)}
                    </td>
                    <td className="whitespace-nowrap py-3 pr-4 font-medium text-slate-900">
                      {formatDate(r.new_expiry_date)}
                    </td>
                    <td className="py-3 pr-4">
                      <p className="text-slate-900">{r.renewed_by.full_name}</p>
                      <p className="text-xs text-slate-500">{r.renewed_by.email}</p>
                    </td>
                    <td className="max-w-xs break-words py-3 text-slate-600">
                      {r.renewal_note ?? <span className="text-slate-400">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Stacked list on small screens */}
          <ul className="space-y-3 md:hidden">
            {page.items.map((r) => (
              <li key={r.id} className="rounded-xl p-4 ring-1 ring-inset ring-slate-200">
                <p className="text-xs font-medium text-slate-500">{formatDateTime(r.renewed_at)}</p>
                <p className="mt-1 text-sm font-semibold text-slate-900">
                  {formatDate(r.previous_expiry_date)} → {formatDate(r.new_expiry_date)}
                </p>
                <p className="mt-1 text-sm text-slate-600">
                  {r.renewed_by.full_name}
                  <span className="block break-all text-xs text-slate-500">{r.renewed_by.email}</span>
                </p>
                {r.renewal_note && (
                  <p className="mt-2 break-words text-sm text-slate-600">{r.renewal_note}</p>
                )}
              </li>
            ))}
          </ul>

          {page.total > HISTORY_PAGE_SIZE && (
            <nav
              aria-label="Renewal history pages"
              className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4"
            >
              <p className="text-xs text-slate-500">
                Showing {from}–{to} of {page.total}
              </p>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="h-9 gap-1"
                  disabled={loading || page.offset === 0}
                  onClick={() => go(Math.max(0, page.offset - HISTORY_PAGE_SIZE))}
                >
                  <ChevronLeft className="size-4" aria-hidden="true" />
                  Newer
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="h-9 gap-1"
                  disabled={loading || to >= page.total}
                  onClick={() => go(page.offset + HISTORY_PAGE_SIZE)}
                >
                  Older
                  {loading ? (
                    <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <ChevronRight className="size-4" aria-hidden="true" />
                  )}
                </Button>
              </div>
            </nav>
          )}
        </div>
      )}
    </DashboardCard>
  );
}
