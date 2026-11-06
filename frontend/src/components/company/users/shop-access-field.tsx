"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { Loader2, RotateCcw, Search, X } from "lucide-react";

import { INPUT_CLASS, Pill } from "@/components/company/ui-kit";
import {
  filterShops,
  MAX_VISIBLE_SHOPS,
  MODE_COPY,
} from "@/components/company/users/shop-access-rules";
import { Input } from "@/components/ui/input";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { AssignableShop, AssignableShops, ShopAccessMode } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type Load = { status: "loading" } | { status: "ready"; shops: AssignableShop[] } | { status: "error"; message: string };

/** All registered shops (ID, name, code, status) for the checklist; Company Admin only. */
export function useAssignableShops(enabled: boolean): Load & { retry: () => void } {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    apiFetch<AssignableShops>("/company/shop-assignment-options")
      .then((data) => alive && setLoad({ status: "ready", shops: data.items }))
      .catch((e: unknown) =>
        alive && setLoad({ status: "error", message: e instanceof ApiError ? e.message : "Shops could not be loaded." }),
      );
    return () => {
      alive = false;
    };
  }, [enabled, tick]);
  return {
    ...load,
    retry: () => {
      setLoad({ status: "loading" });
      setTick((t) => t + 1);
    },
  };
}

type Props = {
  mode: ShopAccessMode;
  onModeChange: (mode: ShopAccessMode) => void;
  selected: ReadonlySet<string>;
  onSelectedChange: (next: Set<string>) => void;
  error?: string | null;
  disabled?: boolean;
  /** Shops already assigned (shown even before the full list has loaded). */
  knownShops?: AssignableShop[];
  /** The surrounding section already has a visible "Shop Access" heading. */
  hideLegend?: boolean;
};

/**
 * Shop Access: All Shops / Selected Shops Only / No Shop Access, with a
 * searchable checklist that never renders more than MAX_VISIBLE_SHOPS rows.
 * Independent of the role select: it decides which shops, never which modules.
 */
export function ShopAccessField({ mode, onModeChange, selected, onSelectedChange, error, disabled, knownShops = [], hideLegend }: Props) {
  const id = useId();
  const shops = useAssignableShops(mode === "selected");
  const [query, setQuery] = useState("");

  const all = useMemo(() => {
    const list = shops.status === "ready" ? shops.shops : [];
    const known = knownShops.filter((k) => !list.some((s) => s.id === k.id));
    return [...list, ...known];
  }, [shops, knownShops]);
  const matches = useMemo(() => filterShops(all, query), [all, query]);
  const visible = matches.slice(0, MAX_VISIBLE_SHOPS);
  const chosen = all.filter((s) => selected.has(s.id));

  function toggle(shopId: string) {
    const next = new Set(selected);
    if (next.has(shopId)) next.delete(shopId);
    else next.add(shopId);
    onSelectedChange(next);
  }

  return (
    // min-w-0: a fieldset is min-content wide by default; long shop names must not widen the dialog.
    <fieldset className="min-w-0 space-y-3" aria-describedby={error ? `${id}-error` : undefined}>
      <legend className={hideLegend ? "sr-only" : "mb-1 text-sm font-medium text-slate-900"}>Shop Access</legend>
      <div className="grid gap-2">
        {(["all", "selected", "none"] as const).map((value) => (
          <label
            key={value}
            className={cn(
              "flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-blue-600/30",
              mode === value ? "border-blue-600 bg-blue-50/60" : "border-slate-200 bg-white hover:border-slate-300",
              disabled && "cursor-not-allowed opacity-60",
            )}
          >
            <input
              type="radio"
              name={`${id}-mode`}
              value={value}
              checked={mode === value}
              disabled={disabled}
              onChange={() => onModeChange(value)}
              className="mt-0.5 size-4 accent-[#1b4fc4]"
              aria-labelledby={`${id}-${value}-title`}
              aria-describedby={`${id}-${value}-hint`}
            />
            <span className="min-w-0">
              <span id={`${id}-${value}-title`} className="block text-sm font-medium text-slate-900">
                {MODE_COPY[value].title}
              </span>
              <span id={`${id}-${value}-hint`} className="block text-xs text-slate-500">
                {MODE_COPY[value].hint}
              </span>
            </span>
          </label>
        ))}
      </div>

      {mode === "selected" && (
        <div className="space-y-2 rounded-xl border border-slate-200 p-3" data-testid="shop-checklist">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium text-slate-900" aria-live="polite">
              {selected.size.toLocaleString("en-US")} {selected.size === 1 ? "shop" : "shops"} selected
            </p>
            {selected.size > 0 && (
              <button
                type="button"
                onClick={() => onSelectedChange(new Set())}
                disabled={disabled}
                className="rounded px-1.5 py-0.5 text-xs font-medium text-blue-700 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/30"
              >
                Clear selection
              </button>
            )}
          </div>

          {chosen.length > 0 && (
            <ul aria-label="Selected shops" className="flex min-w-0 flex-wrap gap-1.5">
              {chosen.slice(0, 8).map((s) => (
                <li key={s.id} className="inline-flex min-w-0 max-w-full items-center gap-1 rounded-full sm:max-w-[20rem] bg-blue-50 py-0.5 pr-1 pl-2.5 text-xs text-blue-800 ring-1 ring-inset ring-blue-600/20">
                  <span className="min-w-0 truncate" title={`${s.name} — ${s.code}`}>
                    {s.name} — <span className="font-mono">{s.code}</span>
                  </span>
                  <button
                    type="button"
                    onClick={() => toggle(s.id)}
                    disabled={disabled}
                    aria-label={`Remove ${s.name} ${s.code}`}
                    className="rounded-full p-0.5 hover:bg-blue-100"
                  >
                    <X className="size-3" aria-hidden="true" />
                  </button>
                </li>
              ))}
              {chosen.length > 8 && (
                <li className="text-xs text-slate-500">and {(chosen.length - 8).toLocaleString("en-US")} more</li>
              )}
            </ul>
          )}

          <div className="relative">
            <label htmlFor={`${id}-search`} className="sr-only">
              Search shops by name or code
            </label>
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
            <Input
              id={`${id}-search`}
              type="search"
              name="shop_access_filter"
              autoComplete="off"
              data-1p-ignore="true"
              data-lpignore="true"
              data-bwignore="true"
              data-form-type="other"
              placeholder="Search by shop name or code"
              className={cn(INPUT_CLASS, "pl-9")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              disabled={disabled}
            />
          </div>

          {shops.status === "loading" && (
            <p className="flex items-center gap-2 py-2 text-sm text-slate-500">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" /> Loading shops…
            </p>
          )}
          {shops.status === "error" && (
            <p role="alert" className="flex items-center justify-between gap-2 text-sm text-red-700">
              {shops.message}
              <button type="button" onClick={shops.retry} className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50">
                <RotateCcw className="size-3" aria-hidden="true" /> Retry
              </button>
            </p>
          )}
          {shops.status === "ready" && all.length === 0 && (
            <p className="py-2 text-sm text-slate-500">No shops are registered yet.</p>
          )}
          {shops.status === "ready" && all.length > 0 && matches.length === 0 && (
            <p className="py-2 text-sm text-slate-500">No shop matches “{query.trim()}”.</p>
          )}
          {visible.length > 0 && (
            <ul role="group" aria-label="Shops" className="max-h-60 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-100">
              {visible.map((s) => (
                <li key={s.id}>
                  <label className="flex cursor-pointer items-start gap-3 px-3 py-2 text-sm hover:bg-slate-50">
                    <input
                      type="checkbox"
                      checked={selected.has(s.id)}
                      onChange={() => toggle(s.id)}
                      disabled={disabled}
                      className="mt-0.5 size-4 shrink-0 accent-[#1b4fc4]"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block break-words text-slate-900">{s.name}</span>
                      <span className="block font-mono text-xs text-slate-500">{s.code}</span>
                    </span>
                    {s.status === "inactive" && <Pill tone="slate">Inactive</Pill>}
                  </label>
                </li>
              ))}
            </ul>
          )}
          {matches.length > MAX_VISIBLE_SHOPS && (
            <p className="text-xs text-slate-500">
              Showing the first {MAX_VISIBLE_SHOPS} of {matches.length.toLocaleString("en-US")} matching shops. Search to narrow the list.
            </p>
          )}
          <p className="text-xs text-slate-500">Inactive shops can be assigned for history; they cannot be used for new operations.</p>
        </div>
      )}

      {error && (
        <p id={`${id}-error`} role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </fieldset>
  );
}
