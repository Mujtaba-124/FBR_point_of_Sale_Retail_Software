"use client";

import { useId, useRef, useState, type DragEvent } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AlertTriangle, CheckCircle2, FileSpreadsheet, Loader2, UploadCloud } from "lucide-react";

import { useShopContext } from "@/components/company/shop-context/shop-context-provider";
import { ErrorAlert, Field, PRIMARY_BUTTON, SELECT_CLASS } from "@/components/company/ui-kit";
import { RecordsTable } from "@/components/company/uploads/records-table";
import {
  fileSize,
  money,
  plain,
  STATUS_LABEL,
  TEMPLATE_URL,
  UPLOAD_TIMEOUT_MS,
  XLSX_TYPE,
} from "@/components/company/uploads/upload-format";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DatePicker } from "@/components/ui/date-picker";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { UploadBatch, UploadPreview } from "@/lib/api/types";
import { formatDate, todayInBusinessTz } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Replacing a Draft: shop and date are fixed by the existing upload. */
export type ReplaceTarget = {
  batchId: string;
  shopId: string;
  shopLabel: string;
  salesDate: string;
  revision: number;
};

type Props = {
  onOpenChange: (open: boolean) => void;
  onSaved: (batch: UploadBatch, replaced: boolean) => void;
  replace?: ReplaceTarget;
  canReplace: boolean;
};

const MAX_ERRORS_SHOWN = 200;
/** Conflicts that make the checked totals out of date: the file must be checked again. */
const RECHECK_CODES = new Set(["tax_rate_changed", "sales_tax_not_configured", "draft_tax_rate_unknown"]);

function detailHref(batchId: string): string {
  return `/company/uploads/${batchId}`;
}

/**
 * New upload (or Draft replacement): shop + sales date + one .xlsx file,
 * checked by the server first, then saved. The save re-sends the same file and
 * the checksum from the check, so a different file is refused; the server
 * validates everything again. Mounted fresh for every opening.
 */
export function UploadDialog({ onOpenChange, onSaved, replace, canReplace }: Props) {
  const id = useId();
  const pathname = usePathname();
  const shopCtx = useShopContext();
  const options = shopCtx.options;
  const [shopId, setShopId] = useState(replace?.shopId ?? shopCtx.selected?.id ?? (options.length === 1 ? options[0].id : ""));
  const [day, setDay] = useState(replace?.salesDate ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<UploadPreview | null>(null);
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmReplace, setConfirmReplace] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [saved, setSaved] = useState<UploadBatch | null>(null);
  const inFlight = useRef(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const today = todayInBusinessTz();

  function reset() {
    setPreview(null);
    setConfirmReplace(false);
    setError(null);
  }

  function chooseFile(next: File | null) {
    reset();
    if (next && !next.name.toLowerCase().endsWith(".xlsx")) {
      setFile(null);
      setError("Choose an Excel .xlsx file.");
      return;
    }
    setFile(next);
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    const files = e.dataTransfer.files;
    if (files.length > 1) {
      setError("Upload one file at a time.");
      return;
    }
    chooseFile(files[0] ?? null);
  }

  function missing(): string | null {
    if (!shopId) return "Choose a shop.";
    if (!day) return "Enter the sales date as DD/MM/YYYY.";
    if (day > today) return "The sales date cannot be in the future.";
    if (!file) return "Choose the Excel file.";
    return null;
  }

  async function send<T>(path: string, params: Record<string, string>): Promise<T> {
    return apiFetch<T>(`${path}?${new URLSearchParams(params)}`, {
      method: "POST",
      body: file!,
      headers: { "Content-Type": XLSX_TYPE },
      signal: AbortSignal.timeout(UPLOAD_TIMEOUT_MS),
    });
  }

  async function check() {
    const problem = missing();
    if (problem) {
      setError(problem);
      return;
    }
    if (inFlight.current) return;
    inFlight.current = true;
    setChecking(true);
    reset();
    try {
      setPreview(await send<UploadPreview>("/company/uploads/preview", { shop_id: shopId, sales_date: day, filename: file!.name }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The file could not be checked.");
    } finally {
      inFlight.current = false;
      setChecking(false);
    }
  }

  async function save() {
    if (!preview || inFlight.current) return;
    inFlight.current = true;
    setSaving(true);
    setError(null);
    const target = replace?.batchId ?? preview.existing?.id;
    const replacing = Boolean(replace || preview.existing);
    try {
      const batch = replacing
        ? await send<UploadBatch>(`/company/uploads/${target}/replace`, {
            filename: file!.name,
            expected_checksum: preview.checksum,
            expected_revision: String(replace?.revision ?? preview.existing!.current_revision),
            expected_tax_rate: preview.applied_sales_tax_rate,
          })
        : await send<UploadBatch>("/company/uploads", {
            shop_id: shopId,
            sales_date: day,
            filename: file!.name,
            expected_checksum: preview.checksum,
            expected_tax_rate: preview.applied_sales_tax_rate,
          });
      setSaved(batch);
      onSaved(batch, replacing);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The upload could not be saved.");
      setConfirmReplace(false);
      // The checked totals no longer hold (e.g. the shop's Sales Tax % changed): hide them.
      if (e instanceof ApiError && RECHECK_CODES.has(e.code)) setPreview(null);
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  const busy = checking || saving;
  const existing = preview?.existing ?? null;
  const replaceable = Boolean(preview && preview.error_count === 0 && (replace || (existing && existing.can_replace && canReplace)));
  const noShops = !replace && shopCtx.status === "ready" && options.length === 0;

  return (
    <Dialog open onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="text-lg font-semibold text-slate-900">
            {saved ? "Upload saved" : replace ? "Replace Draft" : "New Excel upload"}
          </DialogTitle>
          <DialogDescription>
            {replace
              ? `${replace.shopLabel} · ${formatDate(replace.salesDate)}. The new file must pass every check; the current file stays in the history.`
              : "One file per shop and sales date. The file is checked before anything is saved."}
          </DialogDescription>
        </DialogHeader>

        {saved ? (
          <div className="space-y-4">
            <div role="status" className="flex items-start gap-2.5 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <p>
                Saved as <strong>Draft</strong> (revision {saved.current_revision}): {saved.total_records.toLocaleString("en-US")} records,
                net amount {money(saved.totals.net_amount)}.
              </p>
            </div>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button type="button" variant="outline" className="h-10" onClick={() => onOpenChange(false)}>
                Close
              </Button>
              <Link
                href={detailHref(saved.id)}
                className={cn(PRIMARY_BUTTON, "inline-flex items-center justify-center rounded-lg px-4 text-sm font-medium")}
                onClick={(e) => {
                  // Already on this upload's page (Replace Draft from the detail view):
                  // a link to the current URL would do nothing, so close the dialog;
                  // the page already shows the new revision (onSaved refreshed it).
                  // Elsewhere the link navigates and the dialog closes with it.
                  if (pathname.toLowerCase() === detailHref(saved.id).toLowerCase()) e.preventDefault();
                  onOpenChange(false);
                }}
              >
                View upload
              </Link>
            </div>
          </div>
        ) : noShops ? (
          <ErrorAlert>
            {shopCtx.access.mode === "none"
              ? "No shops have been assigned to your account. Contact your Company Admin."
              : "There are no active shops to upload for."}
          </ErrorAlert>
        ) : (
          <form
            noValidate
            autoComplete="off"
            aria-label={replace ? "Replace Draft" : "New Excel upload"}
            className="min-w-0 space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              void check();
            }}
          >
            {!replace && (
              <div className="grid gap-4 sm:grid-cols-2">
                <Field id={`${id}-shop`} label="Shop" hint="Uploads are always for one shop.">
                  <select
                    id={`${id}-shop`}
                    className={SELECT_CLASS}
                    value={shopId}
                    disabled={busy}
                    onChange={(e) => {
                      setShopId(e.target.value);
                      reset();
                    }}
                  >
                    <option value="">Choose a shop</option>
                    {options.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.name} — {o.code}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field id={`${id}-date`} label="Sales date" hint="Every row in the file must have this date.">
                  <DatePicker
                    id={`${id}-date`}
                    labelId={`${id}-date-label`}
                    max={today}
                    value={day}
                    disabled={busy}
                    describedBy={`${id}-date-hint`}
                    onChange={(iso) => {
                      setDay(iso);
                      reset();
                    }}
                  />
                </Field>
              </div>
            )}

            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={cn(
                "flex flex-col items-center gap-2 rounded-xl border-2 border-dashed p-5 text-center transition-colors",
                dragging ? "border-blue-600 bg-blue-50" : "border-slate-200 bg-slate-50",
              )}
            >
              <UploadCloud className="size-6 text-blue-700" aria-hidden="true" />
              <p className="text-sm text-slate-700">Drag the Excel file here, or</p>
              <input
                ref={fileInput}
                id={`${id}-file`}
                type="file"
                accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                className="sr-only"
                disabled={busy}
                onChange={(e) => chooseFile(e.target.files?.[0] ?? null)}
              />
              <Button type="button" variant="outline" className="h-9 bg-white" disabled={busy} onClick={() => fileInput.current?.click()}>
                Choose .xlsx file
              </Button>
              <label htmlFor={`${id}-file`} className="sr-only">
                Excel file
              </label>
              {file ? (
                <p className="flex max-w-full items-center gap-1.5 text-xs text-slate-600" data-testid="chosen-file">
                  <FileSpreadsheet className="size-3.5 shrink-0" aria-hidden="true" />
                  <span className="min-w-0 truncate" title={file.name}>
                    {file.name}
                  </span>
                  <span className="shrink-0">· {fileSize(file.size)}</span>
                </p>
              ) : (
                <p className="text-xs text-slate-500">
                  One .xlsx file in the{" "}
                  <a href={TEMPLATE_URL} className="font-medium text-blue-700 underline-offset-2 hover:underline">
                    8-column Excel template
                  </a>
                  . Sales tax is calculated from the shop&apos;s Sales Tax %.
                </p>
              )}
            </div>

            {error && <ErrorAlert>{error}</ErrorAlert>}

            {preview && <PreviewPanel preview={preview} />}

            {preview && existing && !replace && (
              <div role="status" className="flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                <p>
                  An upload already exists for this shop and date ({STATUS_LABEL[existing.status]}, revision {existing.current_revision},{" "}
                  {existing.total_records.toLocaleString("en-US")} records).{" "}
                  {existing.can_replace && canReplace
                    ? "You can replace that Draft with this file; the current file stays in the history."
                    : existing.status === "draft"
                      ? "Your role cannot replace Drafts."
                      : "It is past Draft, so it cannot be replaced."}
                </p>
              </div>
            )}

            {confirmReplace && preview && (
              <div role="group" aria-label="Confirm replacement" className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                <p>
                  Replace revision {replace?.revision ?? existing?.current_revision} with this file ({preview.valid_rows.toLocaleString("en-US")} records, net{" "}
                  {money(preview.totals.net_amount)})? It keeps this Draft&apos;s Sales Tax % of {plain(preview.applied_sales_tax_rate)}%. It
                  becomes the new current Draft; the earlier file and its records stay in the history.
                </p>
                <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                  <Button type="button" variant="outline" className="h-9 bg-white" disabled={saving} onClick={() => setConfirmReplace(false)}>
                    Back
                  </Button>
                  <Button type="button" className={PRIMARY_BUTTON} disabled={saving} onClick={() => void save()}>
                    {saving && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
                    {saving ? "Replacing…" : "Confirm replacement"}
                  </Button>
                </div>
              </div>
            )}

            {!confirmReplace && (
              <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                <Button type="button" variant="outline" className="h-10" disabled={busy} onClick={() => onOpenChange(false)}>
                  Cancel
                </Button>
                <Button type="submit" variant={preview ? "outline" : "default"} className={preview ? "h-10" : PRIMARY_BUTTON} disabled={busy}>
                  {checking && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
                  {checking ? "Checking…" : preview ? "Check again" : "Check file"}
                </Button>
                {preview?.can_save && !replace && (
                  <Button type="button" className={PRIMARY_BUTTON} disabled={busy} onClick={() => void save()}>
                    {saving && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
                    {saving ? "Saving…" : "Save as Draft"}
                  </Button>
                )}
                {replaceable && (
                  <Button type="button" className={PRIMARY_BUTTON} disabled={busy} onClick={() => setConfirmReplace(true)}>
                    Replace Draft…
                  </Button>
                )}
              </div>
            )}
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function PreviewPanel({ preview }: { preview: UploadPreview }) {
  const ok = preview.error_count === 0;
  // With rejected rows the totals cover the valid rows only; say so on the figures.
  const partial = preview.invalid_rows > 0 ? " (valid rows only)" : "";
  return (
    <section aria-label="File check result" className="min-w-0 space-y-3">
      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        <Stat label="Shop" value={`${preview.shop.name} — ${preview.shop.code}`} wide />
        <Stat label="Sales date" value={formatDate(preview.sales_date)} />
        <Stat
          label="Sales Tax % (applied)"
          value={`${plain(preview.applied_sales_tax_rate)}%`}
          note={preview.tax_rate_source === "draft" ? "Kept from the existing Draft" : "From Shop Management"}
        />
        <Stat label="File" value={`${preview.filename} · ${fileSize(preview.file_size)}`} wide />
        <Stat label="Rows" value={preview.total_rows.toLocaleString("en-US")} />
        <Stat label="Valid rows" value={preview.valid_rows.toLocaleString("en-US")} />
        <Stat label="Rows with errors" value={preview.invalid_rows.toLocaleString("en-US")} tone={preview.invalid_rows ? "bad" : undefined} />
        <Stat label={`Amount${partial}`} value={money(preview.totals.amount)} />
        <Stat label={`Sales tax${partial}`} value={money(preview.totals.sales_tax)} note="Calculated" />
        <Stat label={`Net amount${partial}`} value={money(preview.totals.net_amount)} note="Calculated" />
      </dl>
      <p className="text-xs text-slate-500">
        Tax exclusive: Sales Tax = Amount × {plain(preview.applied_sales_tax_rate)}% (rounded per row); Net = Amount + Sales Tax. The
        server calculates and saves these values.
      </p>
      {ok ? (
        <p role="status" className="flex items-start gap-2 text-sm text-emerald-800">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          All {preview.total_rows.toLocaleString("en-US")} rows passed the checks
          {preview.rounding_differences > 0 ? ` (${preview.rounding_differences} within the 0.01 rounding tolerance)` : ""}.
        </p>
      ) : (
        <div role="alert" className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900">
          <p className="font-medium">
            {preview.error_count.toLocaleString("en-US")} problem{preview.error_count === 1 ? "" : "s"} found. Nothing can be saved until the file is corrected.
          </p>
          <ul className="max-h-56 space-y-1 overflow-y-auto pr-1" aria-label="Problems by row">
            {preview.errors.slice(0, MAX_ERRORS_SHOWN).map((e, i) => (
              <li key={i}>
                <strong>{e.row ? `Row ${e.row}` : "File"}</strong>
                {e.column ? ` — ${e.column}` : ""}: {e.message}
              </li>
            ))}
          </ul>
          {(preview.errors_truncated || preview.errors.length > MAX_ERRORS_SHOWN) && (
            <p className="text-xs">Only the first problems are listed. Fix them and check the file again.</p>
          )}
        </div>
      )}
      {preview.rows.length > 0 && (
        <div>
          <p className="mb-1 text-xs text-slate-500">
            First {preview.rows.length} valid row{preview.rows.length === 1 ? "" : "s"} (CNIC/NTN shown masked)
          </p>
          <RecordsTable rows={preview.rows} caption="Preview of valid rows" />
        </div>
      )}
    </section>
  );
}

function Stat({ label, value, wide, tone, note }: { label: string; value: string; wide?: boolean; tone?: "bad"; note?: string }) {
  return (
    <div className={cn("min-w-0 rounded-lg bg-slate-50 p-2 ring-1 ring-inset ring-slate-100", wide && "col-span-2")}>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className={cn("truncate font-medium tabular-nums", tone === "bad" ? "text-red-700" : "text-slate-900")} title={value}>
        {value}
      </dd>
      {note && <dd className="truncate text-[11px] text-slate-500">{note}</dd>}
    </div>
  );
}
