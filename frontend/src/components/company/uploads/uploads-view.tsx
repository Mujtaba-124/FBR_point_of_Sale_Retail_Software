"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ChevronLeft, ChevronRight, Download, Eye, FileDown, FileSpreadsheet, Plus, RefreshCw, Replace } from "lucide-react";

import { SHOP_PARAM } from "@/components/company/shop-context/paths";
import { type UploadFilters, UPLOADS_PAGE_SIZE, uploadsPath } from "@/components/company/uploads/constants";
import { useShopContext } from "@/components/company/shop-context/shop-context-provider";
import { ErrorAlert, Pill, PRIMARY_BUTTON, SELECT_CLASS, SuccessNote } from "@/components/company/ui-kit";
import { type ReplaceTarget, UploadDialog } from "@/components/company/uploads/upload-dialog";
import { money, originalUrl, STATUS_LABEL, TEMPLATE_URL } from "@/components/company/uploads/upload-format";
import { Topbar } from "@/components/super-admin/topbar";
import { Button } from "@/components/ui/button";
import { DatePicker } from "@/components/ui/date-picker";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { UploadBatch, UploadPage, UploadStatus } from "@/lib/api/types";
import { formatDate, formatDateTime, todayInBusinessTz } from "@/lib/format";
import { cn } from "@/lib/utils";


export type UploadAbilities = { upload: boolean; replace: boolean };
type Filters = UploadFilters;

export function StatusPill({ status }: { status: UploadStatus }) {
  return <Pill tone={status === "draft" ? "slate" : status === "accepted" ? "green" : status === "rejected" ? "amber" : "blue"}>{STATUS_LABEL[status]}</Pill>;
}

/** Upload History: filtered on the server, scoped to the user's shops; the shop comes from the shop selector. */
export function UploadsView({
  initial,
  initialFilters = { from: "", to: "", status: "", offset: 0 },
  can,
}: {
  initial: UploadPage;
  initialFilters?: UploadFilters;
  can: UploadAbilities;
}) {
  const search = useSearchParams();
  const shop = search.get(SHOP_PARAM) || null;
  const shopCtx = useShopContext();
  const [page, setPage] = useState(initial);
  const [filters, setFilters] = useState<Filters>(initialFilters);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dialog, setDialog] = useState<{ key: number; replace?: ReplaceTarget } | null>(null);
  const request = useRef(0);
  const first = useRef(true);

  async function load(nextShop: string | null, next: Filters) {
    const id = ++request.current;
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<UploadPage>(uploadsPath(nextShop, next));
      if (id === request.current) setPage(data);
    } catch (e) {
      if (id === request.current) setError(e instanceof ApiError ? e.message : "Uploads could not be loaded.");
    } finally {
      if (id === request.current) setLoading(false);
    }
  }

  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    void load(shop, filters);
  }, [shop, filters]);

  // Keep the date/status filters in the URL (ISO values), so reload and
  // Back/Forward show the same list. replaceState: filtering adds no history entries.
  useEffect(() => {
    const url = new URL(window.location.href);
    const wanted: [string, string][] = [["from", filters.from], ["to", filters.to], ["status", filters.status]];
    for (const [key, value] of wanted) {
      if (value) url.searchParams.set(key, value);
      else url.searchParams.delete(key);
    }
    if (url.href !== window.location.href) window.history.replaceState(null, "", url);
  }, [shop, filters.from, filters.to, filters.status]);

  function change(patch: Partial<Filters>) {
    setNotice(null);
    setFilters((f) => ({ ...f, offset: 0, ...patch }));
  }

  const invalidRange = Boolean(filters.from && filters.to && filters.from > filters.to);
  const today = todayInBusinessTz();
  const firstRow = page.total ? page.offset + 1 : 0;
  const lastRow = Math.min(page.offset + page.items.length, page.total);
  const scopeLabel = page.context.shop
    ? `${page.context.shop.name} — ${page.context.shop.code}`
    : shopCtx.accessKnown
      ? shopCtx.access.allLabel
      : "…";
  const noShops = shopCtx.enabled && shopCtx.status === "ready" && shopCtx.access.mode === "none";

  return (
    <div className="space-y-6">
      <Topbar
        title="Excel Uploads"
        description="Upload daily sales files per shop, check them, and keep them as Drafts."
        actions={
          <>
            <Button type="button" variant="outline" className="h-10 gap-2" disabled={loading} onClick={() => void load(shop, filters)}>
              <RefreshCw className={cn("size-4", loading && "animate-spin")} aria-hidden="true" />
              Refresh
            </Button>
            <a href={TEMPLATE_URL} className="inline-flex h-10 items-center gap-2 whitespace-nowrap rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium text-slate-800 shadow-xs hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-blue-600/30">
              <FileDown className="size-4" aria-hidden="true" />
              Download template
            </a>
            {can.upload && (
              <Button type="button" className={PRIMARY_BUTTON} disabled={noShops} onClick={() => setDialog({ key: Date.now() })}>
                <Plus className="size-4" aria-hidden="true" />
                New upload
              </Button>
            )}
          </>
        }
      />

      {noShops && (
        <div role="status" className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
          No shops have been assigned to your account. Contact your Company Admin.
        </div>
      )}
      {notice && <SuccessNote>{notice}</SuccessNote>}

      <section aria-labelledby="upload-history-heading" className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="upload-history-heading" className="text-[15px] font-semibold text-slate-900">
            Upload History
          </h2>
          <p className="text-xs text-slate-500" data-testid="uploads-scope">
            Showing: {scopeLabel}
          </p>
        </div>
        <form className="grid gap-3 sm:grid-cols-3" role="search" aria-label="Filter uploads" onSubmit={(e) => e.preventDefault()}>
          <FilterField id="uploads-from" label="Date From">
            <DatePicker id="uploads-from" labelId="uploads-from-label" value={filters.from} max={filters.to || today} onChange={(iso) => change({ from: iso })} />
          </FilterField>
          <FilterField id="uploads-to" label="Date To">
            <DatePicker id="uploads-to" labelId="uploads-to-label" value={filters.to} min={filters.from || null} max={today} onChange={(iso) => change({ to: iso })} />
          </FilterField>
          <FilterField id="uploads-status" label="Status">
            <select id="uploads-status" className={SELECT_CLASS} value={filters.status} onChange={(e) => change({ status: e.target.value as Filters["status"] })}>
              <option value="">All statuses</option>
              {(Object.keys(STATUS_LABEL) as UploadStatus[]).map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABEL[s]}
                </option>
              ))}
            </select>
          </FilterField>
        </form>
        {invalidRange && <p className="mt-2 text-xs text-destructive">Date From must be on or before Date To.</p>}

        <div className="mt-4">
          {error ? (
            <ErrorAlert action={<Button type="button" variant="outline" className="h-8 bg-white" onClick={() => void load(shop, filters)}>Try again</Button>}>
              {error}
            </ErrorAlert>
          ) : page.items.length === 0 ? (
            <div role="status" className="flex flex-col items-center gap-2 py-10 text-center text-sm text-slate-500">
              <FileSpreadsheet className="size-6 text-slate-400" aria-hidden="true" />
              {filters.from || filters.to || filters.status ? "No uploads match these filters." : "No uploads yet."}
            </div>
          ) : (
            <div className={cn(loading && "opacity-60")}>
              <div className="hidden overflow-x-auto xl:block">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">Excel uploads</caption>
                  <thead className="text-xs text-slate-500">
                    <tr className="border-b border-slate-200">
                      {["Sales Date", "Shop", "File", "Records", "Amount", "Sales Tax", "Net Amount", "Status", "Uploaded", "Actions"].map((h, i) => (
                        <th key={h} scope="col" className={cn("py-2 pr-3 font-medium whitespace-nowrap", i >= 3 && i <= 6 && "text-right", i === 9 && "text-right")}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {page.items.map((b) => (
                      <tr key={b.id}>
                        <td className="py-3 pr-3 font-medium whitespace-nowrap text-slate-900">{formatDate(b.sales_date)}</td>
                        <td className="max-w-48 py-3 pr-3">
                          <span className="block truncate" title={b.shop.name}>{b.shop.name}</span>
                          <span className="font-mono text-xs text-slate-500">{b.shop.code}</span>
                        </td>
                        <td className="max-w-48 truncate py-3 pr-3 text-slate-700" title={b.filename}>
                          {b.filename}
                          {b.current_revision > 1 && <span className="ml-1 text-xs text-slate-500">(rev {b.current_revision})</span>}
                        </td>
                        <td className="py-3 pr-3 text-right tabular-nums">{b.total_records.toLocaleString("en-US")}</td>
                        <td className="py-3 pr-3 text-right tabular-nums">{money(b.totals.amount)}</td>
                        <td className="py-3 pr-3 text-right tabular-nums">{money(b.totals.sales_tax)}</td>
                        <td className="py-3 pr-3 text-right font-medium tabular-nums">{money(b.totals.net_amount)}</td>
                        <td className="py-3 pr-3"><StatusPill status={b.status} /></td>
                        <td className="py-3 pr-3 text-xs whitespace-nowrap text-slate-600">
                          {b.uploaded_by ?? "—"}
                          <br />
                          {formatDateTime(b.uploaded_at)}
                        </td>
                        <td className="py-3 text-right">
                          <RowActions batch={b} can={can} onReplace={(t) => setDialog({ key: Date.now(), replace: t })} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul className="grid gap-3 md:grid-cols-2 xl:hidden" aria-label="Excel uploads">
                {page.items.map((b) => (
                  <li key={b.id} className="min-w-0 rounded-xl border border-slate-200 p-3 text-sm">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <span className="font-medium text-slate-900">{formatDate(b.sales_date)}</span>
                      <StatusPill status={b.status} />
                    </div>
                    <p className="mt-1 truncate text-slate-700" title={b.shop.name}>
                      {b.shop.name} <span className="font-mono text-xs text-slate-500">{b.shop.code}</span>
                    </p>
                    <p className="truncate text-xs text-slate-500" title={b.filename}>{b.filename}</p>
                    <dl className="mt-2 grid grid-cols-2 gap-1 text-xs">
                      <dt className="text-slate-500">Records</dt>
                      <dd className="text-right tabular-nums">{b.total_records.toLocaleString("en-US")}</dd>
                      <dt className="text-slate-500">Net amount</dt>
                      <dd className="text-right font-medium tabular-nums">{money(b.totals.net_amount)}</dd>
                      <dt className="text-slate-500">Uploaded</dt>
                      <dd className="text-right">{formatDateTime(b.uploaded_at)}</dd>
                    </dl>
                    <div className="mt-2">
                      <RowActions batch={b} can={can} onReplace={(t) => setDialog({ key: Date.now(), replace: t })} />
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {page.total > UPLOADS_PAGE_SIZE && (
          <nav aria-label="Upload pages" className="mt-4 flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600">
            <span>{firstRow}–{lastRow} of {page.total}</span>
            <div className="flex gap-2">
              <Button type="button" variant="outline" className="h-8 gap-1" disabled={loading || filters.offset === 0} onClick={() => setFilters((f) => ({ ...f, offset: Math.max(0, f.offset - UPLOADS_PAGE_SIZE) }))}>
                <ChevronLeft className="size-4" aria-hidden="true" /> Previous
              </Button>
              <Button type="button" variant="outline" className="h-8 gap-1" disabled={loading || lastRow >= page.total} onClick={() => setFilters((f) => ({ ...f, offset: f.offset + UPLOADS_PAGE_SIZE }))}>
                Next <ChevronRight className="size-4" aria-hidden="true" />
              </Button>
            </div>
          </nav>
        )}
      </section>

      {dialog && (
        <UploadDialog
          key={dialog.key}
          replace={dialog.replace}
          canReplace={can.replace}
          onOpenChange={(open) => !open && setDialog(null)}
          onSaved={(batch, replaced) => {
            setNotice(`${batch.shop.name} — ${formatDate(batch.sales_date)} was ${replaced ? "replaced (revision " + batch.current_revision + ")" : "saved as Draft"}.`);
            void load(shop, filters);
          }}
        />
      )}
    </div>
  );
}

function FilterField({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <label id={`${id}-label`} htmlFor={id} className="mb-1 block text-xs font-medium text-slate-500">{label}</label>
      {children}
    </div>
  );
}

function RowActions({ batch, can, onReplace }: { batch: UploadBatch; can: UploadAbilities; onReplace: (t: ReplaceTarget) => void }) {
  return (
    <div className="flex flex-wrap justify-end gap-1.5">
      <Link href={`/company/uploads/${batch.id}`} aria-label={`View upload ${batch.shop.code} ${formatDate(batch.sales_date)}`}
        className="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-medium text-slate-800 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/30">
        <Eye className="size-3.5" aria-hidden="true" /> View
      </Link>
      {can.replace && batch.can_replace && (
        <Button type="button" variant="outline" className="h-8 gap-1 px-2.5 text-xs" aria-label={`Replace Draft ${batch.shop.code} ${formatDate(batch.sales_date)}`}
          onClick={() => onReplace({ batchId: batch.id, shopId: batch.shop.id, shopLabel: `${batch.shop.name} — ${batch.shop.code}`, salesDate: batch.sales_date, revision: batch.current_revision })}>
          <Replace className="size-3.5" aria-hidden="true" /> Replace
        </Button>
      )}
      <a href={originalUrl(batch.id, batch.current_revision)} aria-label={`Download original file ${batch.filename}`}
        className="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-medium text-slate-800 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/30">
        <Download className="size-3.5" aria-hidden="true" /> Original
      </a>
    </div>
  );
}
