import { money, plain } from "@/components/company/uploads/upload-format";
import { formatDate } from "@/lib/format";
import type { SalesRecordRow } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const INPUT_COLUMNS = ["Date", "Time", "Item", "Customer Name", "CNIC/NTN", "Quantity", "Rate", "Amount"];
const TAX_COLUMNS = ["Sales Tax %", "Sales Tax Amount", "Net Amount"];

/**
 * Sales rows: the 8 Excel input columns, then the tax columns. For the current
 * template the tax columns are calculated by the system from the applied shop
 * rate; for a previous 10-column revision (``legacy``) they are the values that
 * were uploaded in the file. Items missing from legacy rows show "—" (never
 * invented). The table scrolls inside its own container on narrow screens.
 */
export function RecordsTable({
  rows,
  caption,
  legacy = false,
}: {
  rows: SalesRecordRow[];
  caption: string;
  legacy?: boolean;
}) {
  return (
    <div className="max-w-full overflow-x-auto rounded-lg border border-slate-200" tabIndex={0} aria-label={`${caption} (scrolls sideways)`}>
      <table className="w-full min-w-[1080px] text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-slate-50 text-xs text-slate-500">
          <tr className="border-b border-slate-200 text-[11px] uppercase tracking-wide">
            <th scope="colgroup" colSpan={1 + INPUT_COLUMNS.length} className="px-3 pt-2 pb-1 font-semibold text-slate-500">
              {legacy ? "From the file (previous 10-column template)" : "Excel input"}
            </th>
            <th scope="colgroup" colSpan={TAX_COLUMNS.length} className="border-l border-slate-200 bg-blue-50/60 px-3 pt-2 pb-1 text-right font-semibold text-blue-800">
              {legacy ? "Tax as uploaded" : "Calculated by the system"}
            </th>
          </tr>
          <tr>
            {["Row", ...INPUT_COLUMNS, ...TAX_COLUMNS].map((h, i) => (
              <th
                key={h}
                scope="col"
                className={cn(
                  "px-3 py-2 font-medium whitespace-nowrap",
                  i >= 6 && "text-right",
                  i > INPUT_COLUMNS.length && "bg-blue-50/60 text-blue-900",
                  i === INPUT_COLUMNS.length + 1 && "border-l border-slate-200",
                )}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r) => (
            <tr key={r.excel_row}>
              <td className="px-3 py-2 text-slate-500 tabular-nums">{r.excel_row}</td>
              <td className="px-3 py-2 whitespace-nowrap">{formatDate(r.sale_date)}</td>
              <td className="px-3 py-2 tabular-nums">{r.sale_time.slice(0, 5)}</td>
              <td className="max-w-56 truncate px-3 py-2" title={r.item ?? "Not recorded (previous template)"}>
                {r.item ?? (
                  <span className="text-slate-400" aria-label="Not recorded">
                    —
                  </span>
                )}
              </td>
              <td className="max-w-48 truncate px-3 py-2" title={r.customer_name ?? ""}>
                {r.customer_name ?? <span className="text-slate-400">—</span>}
              </td>
              <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">{r.cnic_ntn ?? <span className="text-slate-400">—</span>}</td>
              <td className="px-3 py-2 text-right tabular-nums">{plain(r.quantity)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{plain(r.rate)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{money(r.amount)}</td>
              <td className="border-l border-slate-200 bg-blue-50/30 px-3 py-2 text-right tabular-nums">{plain(r.tax_percent)}%</td>
              <td className="bg-blue-50/30 px-3 py-2 text-right tabular-nums">{money(r.tax_amount)}</td>
              <td className="bg-blue-50/30 px-3 py-2 text-right font-medium tabular-nums">{money(r.net_amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
