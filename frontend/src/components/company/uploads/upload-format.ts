import type { UploadTaxContext, UploadStatus } from "@/lib/api/types";

/**
 * Formats an exact decimal string with thousand separators and 2 decimals,
 * without converting to a binary float. "2459.9" -> "2,459.90".
 */
export function money(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const negative = value.startsWith("-");
  const [intPart, fracPart = ""] = value.replace(/^-/, "").split(".");
  let cents = (fracPart + "00").slice(0, 2);
  let whole = intPart.replace(/^0+(?=\d)/, "") || "0";
  // Round half up on the third decimal, still as text.
  if ((fracPart[2] ?? "0") >= "5") {
    const n = (BigInt(whole) * BigInt(100) + BigInt(cents) + BigInt(1)).toString().padStart(3, "0");
    whole = n.slice(0, -2);
    cents = n.slice(-2);
  }
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "-" : ""}${grouped}.${cents}`;
}

/** Quantities and rates keep their own precision; only trailing zeros go. */
export function plain(value: string): string {
  if (!value.includes(".")) return value.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const [i, f] = value.split(".");
  const fraction = f.replace(/0+$/, "");
  const grouped = i.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return fraction ? `${grouped}.${fraction}` : grouped;
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** The saved (applied) rate: "18%", or "Mixed" for a legacy revision with different row rates. */
export function appliedRate(ctx: Pick<UploadTaxContext, "applied_sales_tax_rate">): string {
  return ctx.applied_sales_tax_rate === null ? "Mixed" : `${plain(ctx.applied_sales_tax_rate)}%`;
}

export const TAX_SOURCE_LABEL: Record<UploadTaxContext["tax_rate_source"], string> = {
  shop: "Shop rate when first saved",
  draft: "Kept from the Draft",
  legacy_rows: "From the uploaded rows (previous template)",
  legacy_mixed: "Rows use different rates (previous template)",
};

export const TEMPLATE_LABEL: Record<UploadTaxContext["template_format"], string> = {
  standard_8col: "8 columns",
  legacy_10col: "10 columns (previous)",
};

export const STATUS_LABEL: Record<UploadStatus, string> = {
  draft: "Draft",
  wait_for_approval: "Wait for Approval",
  accepted: "Accept",
  rejected: "Reject",
};

export const TEMPLATE_URL = "/api/v1/company/uploads/template";
export const XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
export const UPLOAD_TIMEOUT_MS = 120_000;

export function originalUrl(batchId: string, revision: number): string {
  return `/api/v1/company/uploads/${batchId}/revisions/${revision}/original`;
}
