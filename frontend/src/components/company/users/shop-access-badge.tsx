"use client";

import { useState } from "react";
import { ChevronDown, Loader2 } from "lucide-react";

import { Pill } from "@/components/company/ui-kit";
import { shopAccessLabel } from "@/components/company/users/shop-access-rules";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { CompanyUser, ShopAccessDetail } from "@/lib/api/types";

/**
 * Compact Shop Access indicator for the user list. For "Selected Shops Only"
 * it opens a read-only list of the assigned shops, fetched on demand (the
 * list endpoint carries counts only). Visible in User Management only, which
 * is Company Admin only.
 */
export function ShopAccessBadge({ user }: { user: CompanyUser }) {
  const access = user.shop_access;
  const label = shopAccessLabel(access);
  const tone = access.mode === "none" ? "amber" : access.mode === "selected" ? "slate" : "blue";
  if (access.mode !== "selected") {
    return (
      <span data-testid="shop-access-badge">
        <Pill tone={tone}>{label}</Pill>
      </span>
    );
  }
  return <SelectedShopsBadge user={user} label={label} />;
}

function SelectedShopsBadge({ user, label }: { user: CompanyUser; label: string }) {
  const [detail, setDetail] = useState<ShopAccessDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  function open(next: boolean) {
    if (!next || detail) return;
    setError(null);
    apiFetch<ShopAccessDetail>(`/company/users/${user.id}/shop-access`)
      .then(setDetail)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Shops could not be loaded."));
  }

  return (
    <Popover onOpenChange={open}>
      <PopoverTrigger
        data-testid="shop-access-badge"
        aria-label={`${label}: show shops assigned to ${user.full_name}`}
        className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium whitespace-nowrap text-slate-700 ring-1 ring-inset ring-slate-500/20 hover:bg-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/40"
      >
        {label}
        <ChevronDown className="size-3" aria-hidden="true" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(18rem,calc(100vw-2rem))] p-3">
        <p className="text-xs font-semibold text-slate-900">Assigned shops</p>
        {!detail && !error && (
          <p className="flex items-center gap-2 text-xs text-slate-500">
            <Loader2 className="size-3 animate-spin" aria-hidden="true" /> Loading…
          </p>
        )}
        {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
        {detail && (
          <ul className="max-h-56 space-y-1 overflow-y-auto text-xs" aria-label={`Shops assigned to ${user.full_name}`}>
            {detail.shops.map((s) => (
              <li key={s.id} className="flex items-start justify-between gap-2">
                <span className="min-w-0 break-words text-slate-800">
                  {s.name} — <span className="font-mono text-slate-500">{s.code}</span>
                </span>
                {s.status === "inactive" && <span className="shrink-0 text-slate-500">Inactive</span>}
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}
