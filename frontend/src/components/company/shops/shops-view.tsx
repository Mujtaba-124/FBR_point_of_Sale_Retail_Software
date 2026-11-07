"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  Gauge,
  Plus,
  RefreshCw,
  Search,
  Store,
  StoreIcon,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { type ShopAbilities, ShopFormDialog, TaxRateBadge, TokenBadge } from "@/components/company/shops/shop-form-dialog";
import { SHOPS_PAGE_SIZE } from "@/components/company/shops/constants";
import { NO_CREDENTIAL_AUTOFILL } from "@/components/company/shops/no-autofill";
import { ConfirmDialog, ErrorAlert, INPUT_CLASS, Pill, PRIMARY_BUTTON, SELECT_CLASS, SuccessNote } from "@/components/company/ui-kit";
import { Topbar } from "@/components/super-admin/topbar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { Shop, ShopAllowanceSummary, ShopPage, ShopSummary } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type SortKey = "name" | "code" | "branch" | "pos_id" | "status";
type Query = { search: string; status: "" | "active" | "inactive"; sort: SortKey; order: "asc" | "desc"; offset: number };

export function shopsPath(q: Query): string {
  const params = new URLSearchParams({
    limit: String(SHOPS_PAGE_SIZE),
    offset: String(q.offset),
    sort: q.sort,
    order: q.order,
  });
  if (q.search.trim()) params.set("search", q.search.trim());
  if (q.status) params.set("status", q.status);
  return `/company/shops?${params}`;
}

type Editor = { mode: "add" } | { mode: "edit"; shop: Shop } | null;

export function ShopsView({ initial, can }: { initial: ShopPage; can: ShopAbilities }) {
  const [page, setPage] = useState(initial);
  const [summary, setSummary] = useState<ShopSummary>(initial.summary);
  const [allowance, setAllowance] = useState<ShopAllowanceSummary>(initial.allowance);
  const [query, setQuery] = useState<Query>({ search: "", status: "", sort: "name", order: "asc", offset: 0 });
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editor, setEditor] = useState<Editor>(null);
  const [editorKey, setEditorKey] = useState(0);
  const [toggling, setToggling] = useState<Shop | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const request = useRef(0);
  const first = useRef(true);

  async function load(next: Query) {
    const id = ++request.current;
    setLoading(true);
    setLoadError(null);
    try {
      const data = await apiFetch<ShopPage>(shopsPath(next));
      if (id !== request.current) return;
      setPage(data);
      setSummary(data.summary);
      setAllowance(data.allowance);
    } catch (e) {
      if (id === request.current) setLoadError(e instanceof ApiError ? e.message : "The shops could not be loaded.");
    } finally {
      if (id === request.current) setLoading(false);
    }
  }

  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const timer = setTimeout(() => void load(query), query.search ? 250 : 0);
    return () => clearTimeout(timer);
  }, [query]);

  function change(patch: Partial<Query>) {
    setNotice(null);
    setQuery((q) => ({ ...q, offset: 0, ...patch }));
  }

  function sortBy(key: SortKey) {
    setQuery((q) => ({ ...q, sort: key, order: q.sort === key && q.order === "asc" ? "desc" : "asc", offset: 0 }));
  }

  function open(next: Editor) {
    setNotice(null);
    setEditorKey((k) => k + 1);
    setEditor(next);
  }

  async function toggle() {
    if (!toggling || busy) return;
    const activating = toggling.status === "inactive";
    setBusy(true);
    setActionError(null);
    try {
      const saved = await apiFetch<Shop>(`/company/shops/${toggling.id}/${activating ? "reactivate" : "deactivate"}`, {
        method: "POST",
        body: JSON.stringify({ expected_version: toggling.version }),
      });
      setNotice(`${saved.name} was ${activating ? "reactivated" : "deactivated"}.`);
      setToggling(null);
      void load(query);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "The shop status could not be changed.");
    } finally {
      setBusy(false);
    }
  }

  const filtered = Boolean(query.search.trim() || query.status);
  const firstRow = page.total ? page.offset + 1 : 0;
  const lastRow = Math.min(page.offset + page.items.length, page.total);

  return (
    <div className="space-y-6">
      <Topbar
        title="Shop Management"
        description="Manage your shops and FBR POS integration settings."
        actions={
          <>
            <Button type="button" variant="outline" className="h-10 gap-2" disabled={loading} onClick={() => void load(query)}>
              <RefreshCw className={cn("size-4", loading && "animate-spin")} aria-hidden="true" />
              Refresh
            </Button>
            {can.create && (
              <Button
                type="button"
                className={PRIMARY_BUTTON}
                // The backend enforces the limit too; this only avoids a doomed form.
                disabled={allowance.at_capacity}
                aria-describedby={allowance.at_capacity ? "shop-allowance-status" : undefined}
                onClick={() => open({ mode: "add" })}
              >
                <Plus className="size-4" aria-hidden="true" />
                Add Shop
              </Button>
            )}
          </>
        }
      />

      <section aria-label="Shop summary" className="grid gap-5 sm:grid-cols-3">
        <SummaryCard icon={Store} label="Total Shops" value={summary.total} caption="Active and inactive." />
        <SummaryCard icon={StoreIcon} label="Active Shops" value={summary.active} caption="Available for operations." />
        <SummaryCard icon={XCircle} label="Inactive Shops" value={summary.inactive} caption="Kept, not selectable for new uploads." />
      </section>

      <AllowanceIndicator allowance={allowance} canCreate={can.create} />

      {notice && <SuccessNote>{notice}</SuccessNote>}

      <section aria-labelledby="shops-heading" className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 id="shops-heading" className="sr-only">
          Shops
        </h2>
        <div className="flex flex-col gap-3 md:flex-row md:items-end">
          {/* A real search form (not formless), so password managers never pair this
              field with a token input elsewhere on the page. */}
          <form
            role="search"
            autoComplete="off"
            className="relative min-w-0 flex-1"
            onSubmit={(e) => e.preventDefault()}
          >
            <label htmlFor="shop-search" className="sr-only">
              Search by shop name, code, branch or POS ID
            </label>
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
            <Input
              id="shop-search"
              name="shop_list_filter"
              type="search"
              {...NO_CREDENTIAL_AUTOFILL}
              enterKeyHint="search"
              placeholder="Search by name, code, branch or POS ID"
              className={cn(INPUT_CLASS, "pl-9")}
              value={query.search}
              onChange={(e) => change({ search: e.target.value })}
              maxLength={100}
            />
          </form>
          <div className="md:w-48">
            <label htmlFor="shop-status" className="mb-1 block text-xs font-medium text-slate-500">
              Status
            </label>
            <select id="shop-status" className={SELECT_CLASS} value={query.status} onChange={(e) => change({ status: e.target.value as Query["status"] })}>
              <option value="">All statuses</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </div>
        </div>

        <div className="mt-4" aria-busy={loading}>
          {loadError ? (
            <ErrorAlert action={<Button type="button" variant="outline" className="h-8 bg-white" onClick={() => void load(query)}>Try again</Button>}>
              {loadError}
            </ErrorAlert>
          ) : page.items.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-200 p-8 text-center text-sm text-slate-600">
              {filtered ? (
                "No shops match your search or filters."
              ) : (
                <>
                  <p className="font-medium text-slate-900">No shops yet.</p>
                  <p className="mt-1">
                    {can.create ? "Add your first shop to prepare it for sales uploads." : "Shops added by your Company Admin will appear here."}
                  </p>
                </>
              )}
            </div>
          ) : (
            <div className={cn(loading && "opacity-60")}>
              <div className="hidden overflow-x-auto xl:block">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">Shops</caption>
                  <thead className="text-xs text-slate-500">
                    <tr className="border-b border-slate-200">
                      <SortHeader label="Shop Name" field="name" query={query} onSort={sortBy} />
                      <SortHeader label="Shop Code" field="code" query={query} onSort={sortBy} />
                      <SortHeader label="Branch Name" field="branch" query={query} onSort={sortBy} />
                      <SortHeader label="POS ID" field="pos_id" query={query} onSort={sortBy} />
                      <th scope="col" className="py-2 pr-3 font-medium whitespace-nowrap">Sales Tax %</th>
                      <SortHeader label="Status" field="status" query={query} onSort={sortBy} />
                      <th scope="col" className="py-2 pr-3 font-medium">FBR Token</th>
                      <th scope="col" className="py-2 text-right font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {page.items.map((s) => (
                      <tr key={s.id} className="align-middle">
                        <td className="py-3 pr-3 font-medium text-slate-900">{s.name}</td>
                        <td className="py-3 pr-3 font-mono text-xs text-slate-700">{s.code}</td>
                        <td className="py-3 pr-3 text-slate-700">{s.branch_name}</td>
                        <td className="py-3 pr-3 font-mono text-xs text-slate-700">{s.pos_id}</td>
                        <td className="py-3 pr-3 whitespace-nowrap"><TaxRateBadge rate={s.sales_tax_rate} /></td>
                        <td className="py-3 pr-3"><StatusPill shop={s} /></td>
                        <td className="py-3 pr-3"><TokenBadge status={s.fbr_token_status} /></td>
                        <td className="py-3 text-right">
                          <RowActions shop={s} can={can} onOpen={(shop) => open({ mode: "edit", shop })} onToggle={(shop) => { setActionError(null); setToggling(shop); }} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul className="grid gap-3 md:grid-cols-2 xl:hidden" aria-label="Shops">
                {page.items.map((s) => (
                  <li key={s.id} className="rounded-xl border border-slate-200 p-3 text-sm">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <span className="font-medium text-slate-900">{s.name}</span>
                      <StatusPill shop={s} />
                    </div>
                    <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                      <dt className="text-slate-500">Code</dt>
                      <dd className="break-all font-mono text-slate-800">{s.code}</dd>
                      <dt className="text-slate-500">Branch</dt>
                      <dd className="break-words text-slate-800">{s.branch_name}</dd>
                      <dt className="text-slate-500">POS ID</dt>
                      <dd className="break-all font-mono text-slate-800">{s.pos_id}</dd>
                      <dt className="text-slate-500">Sales Tax %</dt>
                      <dd><TaxRateBadge rate={s.sales_tax_rate} /></dd>
                    </dl>
                    <div className="mt-2"><TokenBadge status={s.fbr_token_status} /></div>
                    <div className="mt-2">
                      <RowActions shop={s} can={can} onOpen={(shop) => open({ mode: "edit", shop })} onToggle={(shop) => { setActionError(null); setToggling(shop); }} />
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {page.total > SHOPS_PAGE_SIZE && (
          <nav aria-label="Shop pages" className="mt-4 flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600">
            <span>{firstRow}–{lastRow} of {page.total}</span>
            <div className="flex gap-2">
              <Button type="button" variant="outline" className="h-8 gap-1" disabled={loading || page.offset === 0}
                onClick={() => setQuery((q) => ({ ...q, offset: Math.max(0, q.offset - SHOPS_PAGE_SIZE) }))}>
                <ChevronLeft className="size-4" aria-hidden="true" />
                Previous
              </Button>
              <Button type="button" variant="outline" className="h-8 gap-1" disabled={loading || lastRow >= page.total}
                onClick={() => setQuery((q) => ({ ...q, offset: q.offset + SHOPS_PAGE_SIZE }))}>
                Next
                <ChevronRight className="size-4" aria-hidden="true" />
              </Button>
            </div>
          </nav>
        )}
      </section>

      {editor && (
        <ShopFormDialog
          key={editorKey}
          shop={editor.mode === "edit" ? editor.shop : undefined}
          can={can}
          onOpenChange={(o) => !o && setEditor(null)}
          // Another shop took the last slot: refresh the indicator behind the dialog.
          onLimitReached={() => void load(query)}
          onStale={() => {
            setEditor(null);
            void load(query);
          }}
          onSaved={(saved, message) => {
            setNotice(message);
            if (editor.mode === "add") setEditor(null);
            void load(query);
          }}
        />
      )}

      {toggling && (
        <ConfirmDialog
          open
          onOpenChange={(o) => !o && setToggling(null)}
          busy={busy}
          error={actionError}
          destructive={toggling.status === "active"}
          onConfirm={() => void toggle()}
          title={toggling.status === "active" ? `Deactivate ${toggling.name}?` : `Reactivate ${toggling.name}?`}
          description={
            toggling.status === "active"
              ? "The shop and its FBR settings are kept, but it can no longer be chosen for new uploads. Nothing is deleted."
              : "The shop becomes available for operations again. Its FBR settings are unchanged."
          }
          confirmLabel={toggling.status === "active" ? "Deactivate" : "Reactivate"}
          busyLabel={toggling.status === "active" ? "Deactivating…" : "Reactivating…"}
        />
      )}
    </div>
  );
}

function SummaryCard({ icon: Icon, label, value, caption }: { icon: LucideIcon; label: string; value: number; caption: string }) {
  const id = `shops-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <section aria-labelledby={id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <h3 id={id} className="text-sm font-medium text-slate-600">{label}</h3>
        <span className="flex size-9 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
          <Icon className="size-4" aria-hidden="true" />
        </span>
      </div>
      <p className="mt-2 text-3xl font-semibold tracking-tight text-slate-900 tabular-nums" data-testid={`${id}-value`}>
        {value.toLocaleString("en-US")}
      </p>
      <p className="mt-1 text-xs text-slate-500">{caption}</p>
    </section>
  );
}

function SortHeader({ label, field, query, onSort }: { label: string; field: SortKey; query: Query; onSort: (f: SortKey) => void }) {
  const active = query.sort === field;
  return (
    <th scope="col" className="py-2 pr-3 font-medium" aria-sort={active ? (query.order === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" onClick={() => onSort(field)} className="inline-flex items-center gap-1 rounded hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/40">
        {label}
        {active && (query.order === "asc" ? <ArrowUp className="size-3" aria-hidden="true" /> : <ArrowDown className="size-3" aria-hidden="true" />)}
      </button>
    </th>
  );
}

function StatusPill({ shop }: { shop: Shop }) {
  return shop.status === "active" ? <Pill tone="green">Active</Pill> : <Pill tone="slate">Inactive</Pill>;
}

function RowActions({ shop, can, onOpen, onToggle }: { shop: Shop; can: ShopAbilities; onOpen: (s: Shop) => void; onToggle: (s: Shop) => void }) {
  const editable = can.edit || can.manageToken;
  return (
    <span className="inline-flex flex-wrap justify-end gap-1.5">
      <Button type="button" variant="outline" className="h-8 px-2.5 text-xs" onClick={() => onOpen(shop)} aria-label={`${editable ? "Edit" : "View"} ${shop.name}`}>
        {editable ? "Edit" : "View"}
      </Button>
      {can.toggle &&
        (shop.status === "active" ? (
          <Button type="button" variant="outline" className="h-8 px-2.5 text-xs text-red-700 hover:text-red-800" onClick={() => onToggle(shop)} aria-label={`Deactivate ${shop.name}`}>
            Deactivate
          </Button>
        ) : (
          <Button type="button" variant="outline" className="h-8 px-2.5 text-xs" onClick={() => onToggle(shop)} aria-label={`Reactivate ${shop.name}`}>
            Reactivate
          </Button>
        ))}
    </span>
  );
}

export function ShopsSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading shops" className="space-y-5">
      <div className="grid gap-5 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-32 animate-pulse rounded-2xl bg-slate-200/70" />
        ))}
      </div>
      <div className="h-80 animate-pulse rounded-2xl bg-slate-200/70" />
      <span className="sr-only">Loading shops…</span>
    </div>
  );
}

/** Read-only view of the Super Admin's shop allowance (aggregate numbers only). */
function AllowanceIndicator({ allowance, canCreate }: { allowance: ShopAllowanceSummary; canCreate: boolean }) {
  const fmt = (n: number) => n.toLocaleString("en-US");
  const limited = allowance.mode === "limited" && allowance.max_shops !== null;
  return (
    <section
      aria-label="Shop allowance"
      className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm sm:flex-row sm:items-center sm:justify-between"
    >
      <dl className="flex flex-wrap items-center gap-x-8 gap-y-2">
        <div className="flex items-center gap-2.5">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
            <Gauge className="size-4" aria-hidden="true" />
          </span>
          <div>
            <dt className="text-xs font-medium text-slate-500">Registered Shops</dt>
            <dd className="text-base font-semibold text-slate-900 tabular-nums" data-testid="allowance-registered">
              {limited ? `${fmt(allowance.registered_shops)} / ${fmt(allowance.max_shops!)}` : fmt(allowance.registered_shops)}
            </dd>
          </div>
        </div>
        <div>
          <dt className="text-xs font-medium text-slate-500">{limited ? "Available Slots" : "Allowance"}</dt>
          <dd className="text-base font-semibold text-slate-900 tabular-nums" data-testid="allowance-available">
            {limited ? fmt(allowance.available_slots ?? 0) : "Unlimited"}
          </dd>
        </div>
      </dl>
      {allowance.at_capacity ? (
        <div id="shop-allowance-status" role="status" className="flex items-start gap-2 text-sm text-amber-900 sm:max-w-md sm:text-right">
          <Pill tone="amber">Shop limit reached</Pill>
          <span className="text-xs text-slate-600">
            {allowance.over_limit
              ? `${fmt(allowance.registered_shops)} shops are registered, above the allowance of ${fmt(allowance.max_shops!)}. Existing shops stay available. `
              : canCreate
                ? "New shops cannot be added. "
                : ""}
            The shop allowance is assigned by the Super Admin.
          </span>
        </div>
      ) : (
        <p className="text-xs text-slate-500 sm:text-right">
          Active and inactive shops both count. The allowance is assigned by the Super Admin.
        </p>
      )}
    </section>
  );
}
