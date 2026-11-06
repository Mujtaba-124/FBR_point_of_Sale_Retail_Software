import type { ShopAllowanceSummary } from "@/lib/api/types";

/** Mirrors backend `shop_allowance.MAX_LIMIT` (a typo guard; Unlimited has no ceiling). */
export const MAX_SHOP_LIMIT = 100_000;

export type AllowanceMode = ShopAllowanceSummary["mode"];

/** Whole numbers only: rejects "", "0", "-1", "2.5", "1e3", "5 shops". */
export function parseShopLimit(raw: string): { value: number | null; error: string | null } {
  const text = raw.trim();
  if (!text) return { value: null, error: "Enter the maximum number of shops." };
  if (!/^\d+$/.test(text)) return { value: null, error: "Enter a whole number, such as 5 or 10." };
  const value = Number(text);
  if (value < 1) return { value: null, error: "The maximum number of shops must be at least 1." };
  if (value > MAX_SHOP_LIMIT) {
    return {
      value: null,
      error: `The maximum must be at most ${MAX_SHOP_LIMIT.toLocaleString("en-US")}. Choose Unlimited Shops for no limit.`,
    };
  }
  return { value, error: null };
}

export function describeAllowance(mode: AllowanceMode, max: number | null): string {
  return mode === "unlimited" || max === null
    ? "Unlimited Shops"
    : `Maximum ${max.toLocaleString("en-US")} ${max === 1 ? "shop" : "shops"}`;
}

/** Available slots never go below zero, even when usage exceeds a reduced limit. */
export function slotsLeft(max: number | null, registered: number): number | null {
  return max === null ? null : Math.max(0, max - registered);
}
