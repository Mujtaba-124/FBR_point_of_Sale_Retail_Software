"use client";

import { useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Check, ChevronsUpDown, Layers, Loader2, RotateCcw, Search, Store } from "lucide-react";

import { NO_SHOPS_MESSAGE, useShopContext } from "@/components/company/shop-context/shop-context-provider";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { ShopOption } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type Row = { id: string | null; name: string; code: string | null };

/**
 * Sidebar shop context control (desktop sidebar and mobile drawer).
 * A filter only: it never changes what the account may access. On the
 * company-wide administrative pages it is shown read-only.
 */
export function ShopSelector({ onSelected }: { onSelected?: () => void }) {
  const ctx = useShopContext();
  const assigned = ctx.access.mode !== "company";
  const noShops = ctx.access.mode === "none";
  // Company Users: "All" means the shops assigned to them, never the whole company.
  const allRow: Row = { id: null, name: ctx.access.allLabel, code: null };
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const baseId = useId();
  const listId = `${baseId}-list`;
  const labelId = `${baseId}-label`;

  const rows = useMemo<Row[]>(() => {
    const q = query.trim().toLowerCase();
    const shops = ctx.options
      .filter((o) => !q || o.name.toLowerCase().includes(q) || o.code.toLowerCase().includes(q))
      .map((o: ShopOption) => ({ id: o.id, name: o.name, code: o.code }));
    return !q || allRow.name.toLowerCase().includes(q) ? [allRow, ...shops] : shops;
    // allRow is derived from ctx.access.allLabel
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx.options, query, ctx.access.allLabel]);

  if (!ctx.enabled) return null;

  const current = ctx.selected;
  const pending = ctx.selectedId !== null && current === null; // waiting for the server's verdict
  const interactive = ctx.applies;

  function choose(row: Row) {
    setOpen(false);
    setQuery("");
    if (row.id !== ctx.selectedId) ctx.select(row.id);
    onSelected?.();
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, rows.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Home") {
      e.preventDefault();
      setActiveIndex(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setActiveIndex(rows.length - 1);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const row = rows[activeIndex];
      if (row) choose(row);
    }
  }

  // Before the server answers, the scope is unknown: say so rather than
  // showing a placeholder "All Shops" (wrong for Company Users and on errors).
  const unknown = interactive && !current && !pending && !ctx.accessKnown;
  const value = !interactive
    ? "Company-wide page"
    : current
      ? current.name
      : pending
        ? "Checking shop…"
        : unknown
          ? ctx.status === "error"
            ? "Shops unavailable"
            : "Loading shops…"
          : noShops
            ? "No shops assigned"
            : ctx.access.allLabel;
  const sub = !interactive
    ? "Not filtered by shop"
    : current
      ? current.code
      : pending
        ? null
        : unknown
          ? ctx.status === "error"
            ? "Open to try again"
            : null
          : noShops
            ? "Contact your Company Admin"
            : assigned
              ? "Your assigned shops"
              : "Consolidated view";

  return (
    <div className="rounded-xl bg-white/[0.06] p-2.5 ring-1 ring-white/10" data-testid="shop-selector">
      <p id={labelId} className="px-1 pb-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-blue-200/65">
        Shop context
      </p>
      <Popover
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (next) {
            setQuery("");
            const index = Math.max(0, [allRow, ...ctx.options].findIndex((o) => o.id === ctx.selectedId));
            setActiveIndex(index);
          }
        }}
      >
        <PopoverTrigger
          disabled={!interactive || noShops}
          aria-labelledby={`${labelId} ${baseId}-value`}
          aria-haspopup="listbox"
          aria-describedby={!interactive ? `${baseId}-why` : undefined}
          className={cn(
            "flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300/70",
            interactive ? "bg-white/[0.08] hover:bg-white/[0.12]" : "cursor-not-allowed opacity-70",
          )}
        >
          <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-sky-400/15 text-sky-300">
            {current ? <Store className="size-3.5" aria-hidden="true" /> : <Layers className="size-3.5" aria-hidden="true" />}
          </span>
          <span className="min-w-0 flex-1">
            <span id={`${baseId}-value`} className="block truncate text-sm font-medium text-white" title={value}>
              {value}
            </span>
            {sub && <span className="block truncate font-mono text-[11px] text-blue-200/70">{sub}</span>}
          </span>
          {interactive &&
            (pending || ctx.status === "loading" ? (
              <Loader2 className="size-4 shrink-0 animate-spin text-blue-200/70" aria-hidden="true" />
            ) : (
              <ChevronsUpDown className="size-4 shrink-0 text-blue-200/70" aria-hidden="true" />
            ))}
        </PopoverTrigger>
        <PopoverContent align="start" sideOffset={6} initialFocus={inputRef} className="w-[min(20rem,calc(100vw-2rem))] p-2">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-slate-400" aria-hidden="true" />
            <input
              ref={inputRef}
              type="search"
              name="shop_context_filter"
              role="combobox"
              aria-label="Find a shop by name or code"
              aria-expanded="true"
              aria-controls={listId}
              aria-autocomplete="list"
              aria-activedescendant={rows[activeIndex] ? `${baseId}-opt-${activeIndex}` : undefined}
              autoComplete="off"
              data-1p-ignore="true"
              data-lpignore="true"
              data-bwignore="true"
              data-form-type="other"
              spellCheck={false}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActiveIndex(0);
              }}
              onKeyDown={onKeyDown}
              placeholder="Find a shop"
              className="h-9 w-full rounded-md border border-slate-200 bg-white pr-2 pl-8 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus-visible:border-blue-600 focus-visible:ring-2 focus-visible:ring-blue-600/20"
            />
          </div>
          <ul id={listId} role="listbox" aria-label="Shops" className="max-h-72 overflow-y-auto py-1">
            {rows.map((row, i) => {
              const selected = row.id === ctx.selectedId;
              return (
                <li
                  key={row.id ?? "all"}
                  id={`${baseId}-opt-${i}`}
                  role="option"
                  aria-selected={selected}
                  onMouseEnter={() => setActiveIndex(i)}
                  onClick={() => choose(row)}
                  className={cn(
                    "flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm",
                    i === activeIndex ? "bg-blue-50 text-slate-900" : "text-slate-700",
                    row.id === null && "border-b border-slate-100",
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block break-words font-medium" title={row.name}>
                      {row.name}
                    </span>
                    <span className="block font-mono text-xs text-slate-500">
                      {row.code ?? (assigned ? "Every shop assigned to you" : "Consolidated company view")}
                    </span>
                  </span>
                  {selected && <Check className="size-4 shrink-0 text-blue-700" aria-hidden="true" />}
                </li>
              );
            })}
          </ul>
          {ctx.status === "ready" && ctx.options.length === 0 && (
            <p className="px-2 pb-1 text-xs text-slate-500">No active shops yet. Shops added in Shop Management appear here.</p>
          )}
          {ctx.status === "ready" && ctx.options.length > 0 && rows.length === 0 && (
            <p className="px-2 pb-1 text-xs text-slate-500">No shop matches “{query.trim()}”.</p>
          )}
          {ctx.status === "error" && (
            <div role="alert" className="flex items-center justify-between gap-2 px-2 pb-1 text-xs text-red-700">
              <span>Shops could not be loaded.</span>
              <button type="button" onClick={ctx.retry} className="inline-flex items-center gap-1 rounded px-1.5 py-1 font-medium text-blue-700 hover:bg-blue-50">
                <RotateCcw className="size-3" aria-hidden="true" />
                Retry
              </button>
            </div>
          )}
          {ctx.truncated && (
            <p className="px-2 pb-1 text-xs text-slate-500">Showing the first {ctx.options.length.toLocaleString("en-US")} shops. Search to narrow the list.</p>
          )}
        </PopoverContent>
      </Popover>
      {!interactive && (
        <p id={`${baseId}-why`} className="px-1 pt-1.5 text-[11px] leading-snug text-blue-200/60">
          This page is not filtered by shop. User Management, Roles and Shops always cover the whole company.
        </p>
      )}
      {interactive && noShops && ctx.status === "ready" && (
        <p className="px-1 pt-1.5 text-[11px] leading-snug text-blue-200/70">{NO_SHOPS_MESSAGE}</p>
      )}
    </div>
  );
}
