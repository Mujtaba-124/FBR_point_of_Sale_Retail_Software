import Link from "next/link";
import {
  ArrowRight,
  BarChart3,
  Building2,
  ClipboardCheck,
  FileSpreadsheet,
  Inbox,
  Receipt,
  RefreshCcw,
  Store,
  Users,
  Zap,
  type LucideIcon,
} from "lucide-react";

import { DashboardCard } from "@/components/super-admin/dashboard-card";
import { shopLabel } from "@/components/company/shop-context/paths";
import type { CompanyDashboard, DashboardMetric, ShopAllowanceSummary } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/** Pure presentation of the backend's Company dashboard payload. */
export function CompanyDashboardView({ data }: { data: CompanyDashboard }) {
  const { metrics, company, shop_allowance: allowance, context } = data;
  const limitedTo = allowance.mode === "limited" ? allowance.max_shops : null;
  const shop = context.scope === "shop" ? context.shop : null;
  // Administrative counts are always company-wide; say so once a shop is selected.
  const companyWide = (key: string) => (shop && data.metric_scopes[key] === "company" ? "Company-wide" : undefined);
  const forShop = shop ? ` Will show ${shop.code} only.` : "";
  return (
    <div className="space-y-5">
      <div className="-mt-1 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs font-medium text-slate-500">
        {company.name && (
          <p className="flex items-center gap-1.5">
            <Building2 className="size-3.5" aria-hidden="true" />
            {company.name}
          </p>
        )}
        <p
          data-testid="dashboard-shop-context"
          className={cn(
            "flex min-w-0 items-center gap-1.5 rounded-full px-2.5 py-0.5 ring-1 ring-inset",
            shop ? "bg-blue-50 text-blue-800 ring-blue-600/20" : "bg-slate-100 text-slate-600 ring-slate-500/15",
          )}
        >
          <Store className="size-3.5 shrink-0" aria-hidden="true" />
          <span className="sr-only">Shop context: </span>
          <span className="min-w-0 truncate" title={shop ? shopLabel(shop) : "All Shops"}>
            {shop ? shopLabel(shop) : "All Shops"}
          </span>
        </p>
      </div>
      {shop && (
        <p className="-mt-2 text-xs text-slate-500">
          Sales, uploads, approvals and FBR sync will be filtered to this shop once those modules exist.
          Shop and user counts stay company-wide.
        </p>
      )}
      <section aria-label="Summary" className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard
          icon={Store}
          label="Total Shops"
          metric={metrics.total_shops}
          scopeLabel={companyWide("total_shops")}
          valueSuffix={limitedTo !== null ? ` / ${limitedTo.toLocaleString("en-US")}` : undefined}
          caption={shopCaption(metrics.total_shops, metrics.active_shops)}
          note={allowanceNote(allowance)}
        />
        <SummaryCard
          icon={Users}
          label="Active Users"
          metric={metrics.active_users}
          scopeLabel={companyWide("active_users")}
          caption="Active Company Admin and Company User accounts."
        />
        <SummaryCard
          icon={ClipboardCheck}
          label="Pending Approvals"
          metric={metrics.pending_approvals}
          pendingNote={`Available once the Approval workflow is added.${forShop}`}
        />
        <SummaryCard
          icon={RefreshCcw}
          label="Pending FBR Sync"
          metric={metrics.pending_fbr_sync}
          pendingNote={`Available once FBR Sync is added.${forShop}`}
        />
      </section>

      <div className="grid gap-5 xl:grid-cols-3">
        <SalesOverview className="xl:col-span-2" />
        <QuickActions />
      </div>

      <RecentUploads />
    </div>
  );
}

function allowanceNote(a: ShopAllowanceSummary): string {
  if (a.mode === "unlimited" || a.max_shops === null) return "Unlimited shops allowed";
  if (a.at_capacity) return "Shop limit reached";
  const n = a.available_slots ?? 0;
  return `${n.toLocaleString("en-US")} ${n === 1 ? "slot" : "slots"} available`;
}

function shopCaption(total: DashboardMetric, active: DashboardMetric): string {
  if (total.value === null || active.value === null) return "Registered shops.";
  if (total.value === 0) return "No shops registered yet.";
  return `${active.value.toLocaleString("en-US")} active · ${(total.value - active.value).toLocaleString("en-US")} inactive`;
}

export function SummaryCard({
  icon: Icon,
  label,
  metric,
  caption,
  pendingNote,
  valueSuffix,
  note,
  scopeLabel,
}: {
  icon: LucideIcon;
  label: string;
  metric: DashboardMetric;
  caption?: string;
  pendingNote?: string;
  /** Shown after the value, e.g. " / 10" for a limited shop allowance. */
  valueSuffix?: string;
  /** A second caption line, e.g. the shop allowance. */
  note?: string;
  /** e.g. "Company-wide" when a shop is selected but this figure is not filtered. */
  scopeLabel?: string;
}) {
  const id = `metric-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  const known = metric.available && metric.value !== null;
  return (
    <section
      aria-labelledby={id}
      className="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id={id} className="text-sm font-medium text-slate-600">
            {label}
          </h2>
          {scopeLabel && (
            <span
              data-testid={`${id}-scope`}
              className="mt-1 inline-block rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600 ring-1 ring-inset ring-slate-500/15"
            >
              {scopeLabel}
            </span>
          )}
        </div>
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
          <Icon className="size-4" aria-hidden="true" />
        </span>
      </div>
      <p
        className={cn(
          "mt-3 text-3xl font-semibold tracking-tight tabular-nums",
          known ? "text-slate-900" : "text-slate-400",
        )}
        data-testid={`${id}-value`}
      >
        {known ? metric.value!.toLocaleString("en-US") : "—"}
        {known && valueSuffix && <span className="text-xl font-medium text-slate-400">{valueSuffix}</span>}
        {!known && <span className="sr-only"> (not available yet)</span>}
      </p>
      <div className="mt-auto pt-3">
        {known ? (
          <>
            {caption && <p className="text-xs text-slate-500">{caption}</p>}
            {note && (
              <p className="mt-1 text-xs font-medium text-blue-700" data-testid={`${id}-note`}>
                {note}
              </p>
            )}
          </>
        ) : (
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
            <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600 ring-1 ring-inset ring-slate-500/15">
              Not available yet
            </span>
            {pendingNote}
          </p>
        )}
      </div>
    </section>
  );
}

const SALES_METRICS = ["Total Sales Amount", "Sales Tax Amount", "Net Sales Amount", "Uploaded Invoices"];

function SalesOverview({ className }: { className?: string }) {
  return (
    <DashboardCard title="Sales Overview" icon={Receipt} className={className}>
      <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {SALES_METRICS.map((label) => (
          <div key={label} className="min-w-0 rounded-xl bg-slate-50 p-3 ring-1 ring-inset ring-slate-100">
            <dt className="text-xs text-slate-500">{label}</dt>
            <dd className="mt-1 text-lg font-semibold text-slate-400">
              —<span className="sr-only"> (not available yet)</span>
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-4 text-sm text-slate-600">
        Sales analytics will be available once Excel Upload is implemented. No sales figures are
        shown until real uploaded data exists.
      </p>
    </DashboardCard>
  );
}

/** Only actions whose page exists get a link; the rest stay disabled. */
const QUICK_ACTIONS: { label: string; icon: LucideIcon; href?: string }[] = [
  { label: "Manage Shops", icon: Store, href: "/company/shops" },
  { label: "Manage Users", icon: Users, href: "/company/users" },
  { label: "Upload Excel", icon: FileSpreadsheet },
  { label: "View Reports", icon: BarChart3 },
];

function QuickActions() {
  return (
    <DashboardCard title="Quick Actions" icon={Zap}>
      <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
        {QUICK_ACTIONS.map(({ label, icon: Icon, href }) => (
          <li key={label}>
            {href ? (
              <Link
                href={href}
                className="flex w-full items-center gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-left text-sm font-medium text-slate-800 transition-colors hover:border-blue-300 hover:bg-blue-50/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/40"
              >
                <Icon className="size-4 shrink-0 text-blue-700" aria-hidden="true" />
                <span className="flex-1">{label}</span>
                <ArrowRight className="size-4 text-slate-400" aria-hidden="true" />
              </Link>
            ) : (
            <button
              type="button"
              disabled
              aria-disabled="true"
              aria-describedby="quick-actions-note"
              className="flex w-full cursor-not-allowed items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-left text-sm font-medium text-slate-500"
            >
              <Icon className="size-4 shrink-0 text-slate-400" aria-hidden="true" />
              <span className="flex-1">{label}</span>
              <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-medium text-slate-500 ring-1 ring-slate-200">
                Soon
              </span>
            </button>
            )}
          </li>
        ))}
      </ul>
      <p id="quick-actions-note" className="mt-3 text-xs text-slate-500">
        Remaining actions become available as each module is released.
      </p>
    </DashboardCard>
  );
}

function RecentUploads() {
  return (
    <DashboardCard title="Recent Excel Uploads" icon={FileSpreadsheet}>
      <div
        role="status"
        className="flex flex-col items-center rounded-xl border border-dashed border-slate-300 px-6 py-10 text-center"
      >
        <span className="mb-3 flex size-11 items-center justify-center rounded-2xl bg-blue-50 text-blue-700">
          <Inbox className="size-5" aria-hidden="true" />
        </span>
        <p className="text-sm font-semibold text-slate-900">No Excel uploads yet.</p>
        <p className="mt-1 max-w-md text-sm text-slate-500">
          Uploaded sales files and their approval status will appear here once Excel Upload is
          available.
        </p>
      </div>
    </DashboardCard>
  );
}

export function CompanyDashboardSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading dashboard" className="space-y-5">
      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-36 animate-pulse rounded-2xl bg-slate-200/70" />
        ))}
      </div>
      <div className="grid gap-5 xl:grid-cols-3">
        <div className="h-56 animate-pulse rounded-2xl bg-slate-200/70 xl:col-span-2" />
        <div className="h-56 animate-pulse rounded-2xl bg-slate-200/70" />
      </div>
      <div className="h-56 animate-pulse rounded-2xl bg-slate-200/70" />
      <span className="sr-only">Loading dashboard…</span>
    </div>
  );
}
