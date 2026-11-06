"use client";

import { AlertTriangle, Info, X } from "lucide-react";

import { NO_SHOPS_MESSAGE, useShopContext } from "@/components/company/shop-context/shop-context-provider";

/** Tells the user why the selection fell back to All Shops (shown above page content). */
export function ShopContextNoticeBar() {
  const { notice, dismissNotice, access, applies, enabled, status } = useShopContext();
  if (enabled && applies && status === "ready" && access.mode === "none" && !notice) {
    // A shop-aware page for an account without assigned shops: nothing to show.
    return (
      <div role="status" className="mb-5 flex items-start gap-2.5 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <p className="min-w-0 flex-1">{NO_SHOPS_MESSAGE}</p>
      </div>
    );
  }
  if (!notice) return null;
  return (
    <div
      role="status"
      className="mb-5 flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <p className="min-w-0 flex-1">{notice.message}</p>
      <button
        type="button"
        onClick={dismissNotice}
        aria-label="Dismiss"
        className="-m-1 rounded p-1 text-amber-800 hover:bg-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/50"
      >
        <X className="size-4" aria-hidden="true" />
      </button>
    </div>
  );
}
