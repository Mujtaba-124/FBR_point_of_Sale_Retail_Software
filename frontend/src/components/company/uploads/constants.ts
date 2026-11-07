import type { UploadStatus } from "@/lib/api/types";
import { isIsoDate } from "@/lib/format";

/** Shared by the server page and the client view (must not live in a "use client" module). */
export const UPLOADS_PAGE_SIZE = 10;

const STATUSES: readonly UploadStatus[] = ["draft", "wait_for_approval", "accepted", "rejected"];

/** Upload History filters. Dates are ISO ("YYYY-MM-DD"); only the UI shows DD/MM/YYYY. */
export type UploadFilters = { from: string; to: string; status: "" | UploadStatus; offset: number };

/**
 * Filters kept in the page URL (`?from=2026-11-01&to=2026-11-07&status=draft`)
 * so reload and Back/Forward show the same list. Anything malformed is ignored.
 */
export function filtersFromParams(get: (name: string) => string | null | undefined): UploadFilters {
  const iso = (v: string | null | undefined) => (v && isIsoDate(v) ? v : "");
  const status = get("status");
  let from = iso(get("from"));
  let to = iso(get("to"));
  if (from && to && from > to) [from, to] = ["", ""];
  return { from, to, status: STATUSES.find((s) => s === status) ?? "", offset: 0 };
}

/** API path for one page of Upload History (inclusive date range). */
export function uploadsPath(shop: string | null, f: UploadFilters): `/company/uploads?${string}` {
  const params = new URLSearchParams({ limit: String(UPLOADS_PAGE_SIZE), offset: String(f.offset), sort: "sales_date", order: "desc" });
  if (shop) params.set("shop", shop);
  if (f.from) params.set("date_from", f.from);
  if (f.to) params.set("date_to", f.to);
  if (f.status) params.set("status", f.status);
  return `/company/uploads?${params}`;
}

/** Mirrors the backend: replacing a Draft needs View, Upload and Replace draft together. */
export const REPLACE_PERMISSIONS = ["uploads.view", "uploads.upload", "uploads.edit_draft"] as const;

export function mayReplaceDrafts(granted: ReadonlySet<string>): boolean {
  return REPLACE_PERMISSIONS.every((key) => granted.has(key));
}
