"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ChevronLeft, ChevronRight, Download, FileSpreadsheet, History, Replace } from "lucide-react";

import { ErrorAlert, PRIMARY_BUTTON, SuccessNote } from "@/components/company/ui-kit";
import { RecordsTable } from "@/components/company/uploads/records-table";
import { UploadDialog } from "@/components/company/uploads/upload-dialog";
import {
  appliedRate,
  fileSize,
  money,
  originalUrl,
  TAX_SOURCE_LABEL,
  TEMPLATE_LABEL,
} from "@/components/company/uploads/upload-format";
import { StatusPill } from "@/components/company/uploads/uploads-view";
import { DashboardCard } from "@/components/super-admin/dashboard-card";
import { Topbar } from "@/components/super-admin/topbar";
import { Button } from "@/components/ui/button";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { SalesRecordPage, UploadDetail } from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const RECORDS_PAGE = 25;

/** One upload: summary, revision history and its sales rows (paginated). */
export function UploadDetailView({ detail, initialRecords, canReplace }: { detail: UploadDetail; initialRecords: SalesRecordPage; canReplace: boolean }) {
  const router = useRouter();
  const { batch, revisions } = detail;
  const [records, setRecords] = useState(initialRecords);
  const [revision, setRevision] = useState(batch.current_revision);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replacing, setReplacing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const first = useRef(true);

  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    let alive = true;
    setLoading(true);
    setError(null);
    apiFetch<SalesRecordPage>(`/company/uploads/${batch.id}/records?${new URLSearchParams({ revision: String(revision), limit: String(RECORDS_PAGE), offset: String(offset) })}`)
      .then((r) => alive && setRecords(r))
      .catch((e: unknown) => alive && setError(e instanceof ApiError ? e.message : "Records could not be loaded."))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [batch.id, revision, offset]);

  const shown = revisions.find((r) => r.revision_number === revision) ?? revisions[0];
  const last = Math.min(records.offset + records.items.length, records.total);

  return (
    <div className="space-y-6">
      <Link href="/company/uploads" className="inline-flex items-center gap-1 text-sm font-medium text-blue-700 hover:underline">
        <ArrowLeft className="size-4" aria-hidden="true" /> Upload History
      </Link>
      <Topbar
        title={`${batch.shop.name} — ${formatDate(batch.sales_date)}`}
        description={`${batch.shop.code} · ${batch.filename}`}
        actions={
          canReplace && batch.can_replace ? (
            <Button type="button" className={PRIMARY_BUTTON} onClick={() => setReplacing(true)}>
              <Replace className="size-4" aria-hidden="true" /> Replace Draft
            </Button>
          ) : undefined
        }
      />
      {notice && <SuccessNote>{notice}</SuccessNote>}

      <section aria-label="Upload summary" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <SummaryTile label="Status">
          <StatusPill status={batch.status} />
          <span className="mt-1 block text-xs text-slate-500">Not yet approved or sent to FBR.</span>
        </SummaryTile>
        <SummaryTile label="Applied Sales Tax %">
          <span data-testid="applied-tax-rate">{appliedRate(batch)}</span>
          <span className="mt-1 block text-xs font-normal text-slate-500">{TAX_SOURCE_LABEL[batch.tax_rate_source]}</span>
        </SummaryTile>
        <SummaryTile label="Records">{batch.total_records.toLocaleString("en-US")}</SummaryTile>
        <SummaryTile label="Amount / Sales Tax">
          {money(batch.totals.amount)}
          <span className="block text-xs font-normal text-slate-500">Tax {money(batch.totals.sales_tax)}</span>
        </SummaryTile>
        <SummaryTile label="Net Amount">{money(batch.totals.net_amount)}</SummaryTile>
      </section>

      <DashboardCard title="Revision history" icon={History}>
        <div className="max-w-full overflow-x-auto">
          <table className="w-full min-w-[820px] text-left text-sm">
            <caption className="sr-only">Revisions of this upload</caption>
            <thead className="text-xs text-slate-500">
              <tr className="border-b border-slate-200">
                {["Revision", "File", "Template", "Sales Tax %", "Records", "Net Amount", "Uploaded", "Original"].map((h) => (
                  <th key={h} scope="col" className="py-2 pr-3 font-medium whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {revisions.map((r) => (
                <tr key={r.revision_number} className={cn(r.revision_number === revision && "bg-blue-50/50")}>
                  <td className="py-2 pr-3 whitespace-nowrap">
                    <button type="button" className="font-medium text-blue-700 hover:underline" onClick={() => { setRevision(r.revision_number); setOffset(0); }}
                      aria-pressed={r.revision_number === revision} aria-label={`Show records of revision ${r.revision_number}`}>
                      {r.revision_number}
                    </button>
                    {r.is_current && <span className="ml-2 text-xs text-slate-500">current</span>}
                  </td>
                  <td className="max-w-56 truncate py-2 pr-3" title={r.filename}>{r.filename} <span className="text-xs text-slate-500">· {fileSize(r.file_size)}</span></td>
                  <td className="py-2 pr-3 text-xs whitespace-nowrap text-slate-600">{TEMPLATE_LABEL[r.template_format]}</td>
                  <td className="py-2 pr-3 whitespace-nowrap tabular-nums" title={TAX_SOURCE_LABEL[r.tax_rate_source]}>{appliedRate(r)}</td>
                  <td className="py-2 pr-3 tabular-nums">{r.total_records.toLocaleString("en-US")}</td>
                  <td className="py-2 pr-3 tabular-nums">{money(r.totals.net_amount)}</td>
                  <td className="py-2 pr-3 text-xs whitespace-nowrap text-slate-600">{r.uploaded_by ?? "—"} · {formatDateTime(r.uploaded_at)}</td>
                  <td className="py-2 pr-3">
                    <a href={originalUrl(batch.id, r.revision_number)} className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 hover:underline" aria-label={`Download original file of revision ${r.revision_number}`}>
                      <Download className="size-3.5" aria-hidden="true" /> .xlsx
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DashboardCard>

      <DashboardCard title={`Sales records — revision ${shown.revision_number}${shown.is_current ? " (current)" : ""}`} icon={FileSpreadsheet}>
        {error ? (
          <ErrorAlert>{error}</ErrorAlert>
        ) : (
          <div className={cn("min-w-0 space-y-3", loading && "opacity-60")}>
            <RecordsTable
              rows={records.items}
              caption={`Sales records of revision ${shown.revision_number}`}
              legacy={shown.template_format === "legacy_10col"}
            />
            <p className="text-xs text-slate-500">CNIC/NTN is shown masked. The full values stay in the original file.</p>
            {records.total > RECORDS_PAGE && (
              <nav aria-label="Record pages" className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600">
                <span>{records.total ? records.offset + 1 : 0}–{last} of {records.total.toLocaleString("en-US")}</span>
                <div className="flex gap-2">
                  <Button type="button" variant="outline" className="h-8 gap-1" disabled={loading || offset === 0} onClick={() => setOffset((o) => Math.max(0, o - RECORDS_PAGE))}>
                    <ChevronLeft className="size-4" aria-hidden="true" /> Previous
                  </Button>
                  <Button type="button" variant="outline" className="h-8 gap-1" disabled={loading || last >= records.total} onClick={() => setOffset((o) => o + RECORDS_PAGE)}>
                    Next <ChevronRight className="size-4" aria-hidden="true" />
                  </Button>
                </div>
              </nav>
            )}
          </div>
        )}
      </DashboardCard>

      {replacing && (
        <UploadDialog
          replace={{ batchId: batch.id, shopId: batch.shop.id, shopLabel: `${batch.shop.name} — ${batch.shop.code}`, salesDate: batch.sales_date, revision: batch.current_revision }}
          canReplace={canReplace}
          onOpenChange={(open) => !open && setReplacing(false)}
          onSaved={(saved) => {
            setNotice(`Draft replaced: revision ${saved.current_revision} is now current.`);
            setRevision(saved.current_revision);
            setOffset(0);
            router.refresh(); // summary and revision history from the server
          }}
        />
      )}
    </div>
  );
}

function SummaryTile({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <div className="mt-1 text-xl font-semibold tabular-nums text-slate-900">{children}</div>
    </div>
  );
}
