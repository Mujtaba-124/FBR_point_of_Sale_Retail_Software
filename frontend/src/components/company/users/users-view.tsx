"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
  UserCheck,
  UserPlus,
  Users,
  UserX,
  type LucideIcon,
} from "lucide-react";

import { ConfirmDialog, ErrorAlert, INPUT_CLASS, Pill, PRIMARY_BUTTON, SELECT_CLASS, SuccessNote } from "@/components/company/ui-kit";
import { AddUserDialog } from "@/components/company/users/add-user-dialog";
import { EditUserDialog } from "@/components/company/users/edit-user-dialog";
import { SetupLinkPanel } from "@/components/company/users/setup-link-panel";
import { ShopAccessBadge } from "@/components/company/users/shop-access-badge";
import { Topbar } from "@/components/super-admin/topbar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, apiFetch } from "@/lib/api/client";
import type {
  CompanyRoleItem,
  CompanyUser,
  CompanyUserPage,
  SetupLinkIssued,
  UserActionResult,
  UserCapacity,
} from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { USERS_PAGE_SIZE_SERVER } from "@/components/company/users/constants";

export const USERS_PAGE_SIZE = USERS_PAGE_SIZE_SERVER;
type SortKey = "name" | "email" | "role" | "status" | "last_login" | "created";
type Query = {
  search: string;
  status: "" | "active" | "inactive";
  role: string;
  sort: SortKey;
  order: "asc" | "desc";
  offset: number;
};

export function usersPath(q: Query): string {
  const params = new URLSearchParams({
    limit: String(USERS_PAGE_SIZE),
    offset: String(q.offset),
    sort: q.sort,
    order: q.order,
  });
  if (q.search.trim()) params.set("search", q.search.trim());
  if (q.status) params.set("status", q.status);
  if (q.role) params.set("role_id", q.role);
  return `/company/users?${params}`;
}

type Pending =
  | { kind: "deactivate" | "reactivate" | "link"; user: CompanyUser }
  | null;

export function UsersView({ initial, roles }: { initial: CompanyUserPage; roles: CompanyRoleItem[] }) {
  const [page, setPage] = useState(initial);
  const [capacity, setCapacity] = useState<UserCapacity>(initial.capacity);
  const [query, setQuery] = useState<Query>({
    search: "",
    status: "",
    role: "",
    sort: "name",
    order: "asc",
    offset: 0,
  });
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [adding, setAdding] = useState(0); // >0: open; value keys a fresh dialog
  const [editing, setEditing] = useState<CompanyUser | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [issued, setIssued] = useState<SetupLinkIssued | null>(null);
  const request = useRef(0);
  const first = useRef(true);

  async function load(next: Query) {
    const id = ++request.current;
    setLoading(true);
    setLoadError(null);
    try {
      const data = await apiFetch<CompanyUserPage>(usersPath(next));
      if (id !== request.current) return;
      setPage(data);
      setCapacity(data.capacity);
    } catch (e) {
      if (id === request.current) {
        setLoadError(e instanceof ApiError ? e.message : "The users could not be loaded.");
      }
    } finally {
      if (id === request.current) setLoading(false);
    }
  }

  // Debounced reload whenever the query changes (not on first render: server data).
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
    setQuery((q) => ({
      ...q,
      sort: key,
      order: q.sort === key && q.order === "asc" ? "desc" : "asc",
      offset: 0,
    }));
  }

  async function runAction() {
    if (!pending || busy) return;
    setBusy(true);
    setActionError(null);
    try {
      if (pending.kind === "link") {
        const result = await apiFetch<SetupLinkIssued>(`/company/users/${pending.user.id}/setup-link`, {
          method: "POST",
        });
        setIssued(result);
        setPending(null);
      } else {
        const result = await apiFetch<UserActionResult>(
          `/company/users/${pending.user.id}/${pending.kind}`,
          { method: "POST" },
        );
        setCapacity(result.capacity);
        setNotice(
          `${result.user.full_name} was ${pending.kind === "deactivate" ? "deactivated" : "reactivated"}.`,
        );
        setPending(null);
      }
      void load(query);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "The action could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  const filtered = Boolean(query.search.trim() || query.status || query.role);
  const firstRow = page.total ? page.offset + 1 : 0;
  const lastRow = Math.min(page.offset + page.items.length, page.total);
  const full = capacity.available <= 0;

  return (
    <div className="space-y-6">
      <Topbar
        title="User Management"
        description="Manage company users, their access and permissions."
        actions={
          <>
            <Button
              type="button"
              variant="outline"
              className="h-10 gap-2"
              disabled={loading}
              onClick={() => void load(query)}
            >
              <RefreshCw className={cn("size-4", loading && "animate-spin")} aria-hidden="true" />
              Refresh
            </Button>
            <Button type="button" className={PRIMARY_BUTTON} onClick={() => setAdding((n) => n + 1)}>
              <UserPlus className="size-4" aria-hidden="true" />
              Add User
            </Button>
          </>
        }
      />

      <section aria-label="User capacity" className="grid gap-5 sm:grid-cols-3">
        <CapacityCard icon={Users} label="Active Users" value={`${capacity.active} / ${capacity.limit}`} caption="Company Admin included." />
        <CapacityCard
          icon={UserCheck}
          label="Available Slots"
          value={String(capacity.available)}
          caption={full ? "All slots are in use." : "Active accounts that can still be added."}
          tone={full ? "warn" : undefined}
        />
        <CapacityCard icon={UserX} label="Inactive Users" value={String(capacity.inactive)} caption="Do not use a slot." />
      </section>

      {full && (
        <p role="note" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          All {capacity.limit} active user slots are occupied. Deactivate a user to add or reactivate
          another.
        </p>
      )}
      {notice && <SuccessNote>{notice}</SuccessNote>}

      <section aria-labelledby="users-heading" className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 id="users-heading" className="sr-only">
          Users
        </h2>
        <div className="flex flex-col gap-3 md:flex-row md:items-end">
          <div className="relative min-w-0 flex-1">
            <label htmlFor="user-search" className="sr-only">
              Search by name or email
            </label>
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
            <Input
              id="user-search"
              type="search"
              placeholder="Search by name or email"
              className={cn(INPUT_CLASS, "pl-9")}
              value={query.search}
              onChange={(e) => change({ search: e.target.value })}
              maxLength={100}
            />
          </div>
          <div className="grid grid-cols-2 gap-3 md:w-96">
            <div>
              <label htmlFor="user-status" className="mb-1 block text-xs font-medium text-slate-500">
                Status
              </label>
              <select
                id="user-status"
                className={SELECT_CLASS}
                value={query.status}
                onChange={(e) => change({ status: e.target.value as Query["status"] })}
              >
                <option value="">All statuses</option>
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
            </div>
            <div>
              <label htmlFor="user-role" className="mb-1 block text-xs font-medium text-slate-500">
                Role
              </label>
              <select
                id="user-role"
                className={SELECT_CLASS}
                value={query.role}
                onChange={(e) => change({ role: e.target.value })}
              >
                <option value="">All roles</option>
                {roles.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                    {r.is_active ? "" : " (retired)"}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div className="mt-4" aria-busy={loading}>
          {loadError ? (
            <ErrorAlert action={<Button type="button" variant="outline" className="h-8 bg-white" onClick={() => void load(query)}>Try again</Button>}>
              {loadError}
            </ErrorAlert>
          ) : page.items.length === 0 ? (
            <p className="rounded-xl border border-dashed border-slate-200 p-8 text-center text-sm text-slate-600">
              {filtered ? "No users match your search or filters." : "No company users yet. Add the first user."}
            </p>
          ) : (
            <div className={cn(loading && "opacity-60")}>
              <div className="hidden overflow-x-auto xl:block">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">Company users</caption>
                  <thead className="text-xs text-slate-500">
                    <tr className="border-b border-slate-200">
                      <SortHeader label="Name" field="name" query={query} onSort={sortBy} />
                      <SortHeader label="Email" field="email" query={query} onSort={sortBy} />
                      <SortHeader label="Role" field="role" query={query} onSort={sortBy} />
                      <th scope="col" className="py-2 pr-3 font-medium">
                        Shop Access
                      </th>
                      <SortHeader label="Status" field="status" query={query} onSort={sortBy} />
                      <SortHeader label="Last login" field="last_login" query={query} onSort={sortBy} />
                      <th scope="col" className="py-2 text-right font-medium">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {page.items.map((u) => (
                      <tr key={u.id} className="align-middle">
                        <td className="py-3 pr-3 font-medium text-slate-900">
                          <span className="flex flex-wrap items-center gap-2">
                            {u.full_name}
                            {u.is_protected && <ProtectedBadge />}
                          </span>
                        </td>
                        <td className="max-w-56 truncate py-3 pr-3 text-slate-700" title={u.email}>
                          {u.email}
                        </td>
                        <td className="py-3 pr-3 text-slate-700">{u.role?.name ?? "—"}</td>
                        <td className="py-3 pr-3">
                          <ShopAccessBadge user={u} />
                        </td>
                        <td className="py-3 pr-3">
                          <StatusBadges user={u} />
                        </td>
                        <td className="py-3 pr-3 whitespace-nowrap text-slate-700">{formatDateTime(u.last_login_at)}</td>
                        <td className="py-3 text-right">
                          <RowActions user={u} full={full} onEdit={setEditing} onAction={(kind) => { setActionError(null); setPending({ kind, user: u }); }} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul className="grid gap-3 md:grid-cols-2 xl:hidden" aria-label="Company users">
                {page.items.map((u) => (
                  <li key={u.id} className="rounded-xl border border-slate-200 p-3 text-sm">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <span className="font-medium text-slate-900">{u.full_name}</span>
                      <StatusBadges user={u} />
                    </div>
                    <p className="mt-1 break-all text-slate-600">{u.email}</p>
                    <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      {u.role?.name ?? "—"}
                      {u.is_protected && <ProtectedBadge />}
                      <span>· Last login {formatDateTime(u.last_login_at)}</span>
                    </p>
                    <div className="mt-1.5">
                      <ShopAccessBadge user={u} />
                    </div>
                    <div className="mt-2">
                      <RowActions user={u} full={full} onEdit={setEditing} onAction={(kind) => { setActionError(null); setPending({ kind, user: u }); }} />
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {page.total > USERS_PAGE_SIZE && (
          <nav aria-label="User pages" className="mt-4 flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600">
            <span>
              {firstRow}–{lastRow} of {page.total}
            </span>
            <div className="flex gap-2">
              <Button type="button" variant="outline" className="h-8 gap-1" disabled={loading || page.offset === 0}
                onClick={() => setQuery((q) => ({ ...q, offset: Math.max(0, q.offset - USERS_PAGE_SIZE) }))}>
                <ChevronLeft className="size-4" aria-hidden="true" />
                Previous
              </Button>
              <Button type="button" variant="outline" className="h-8 gap-1" disabled={loading || lastRow >= page.total}
                onClick={() => setQuery((q) => ({ ...q, offset: q.offset + USERS_PAGE_SIZE }))}>
                Next
                <ChevronRight className="size-4" aria-hidden="true" />
              </Button>
            </div>
          </nav>
        )}
      </section>

      {adding > 0 && (
        <AddUserDialog
          key={adding}
          open
          onOpenChange={(open) => !open && setAdding(0)}
          roles={roles}
          slotsAvailable={capacity.available}
          onCreated={(result) => {
            setCapacity(result.capacity);
            void load(query);
          }}
        />
      )}

      {editing && (
        <EditUserDialog
          key={editing.id}
          user={editing}
          roles={roles}
          onOpenChange={(open) => !open && setEditing(null)}
          onSaved={(saved) => {
            setEditing(null);
            setNotice(`${saved.full_name} was updated.`);
            void load(query);
          }}
          onShopAccessSaved={() => void load(query)}
        />
      )}

      {pending && (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setPending(null)}
          busy={busy}
          error={actionError}
          onConfirm={() => void runAction()}
          destructive={pending.kind === "deactivate"}
          title={
            pending.kind === "deactivate"
              ? `Deactivate ${pending.user.full_name}?`
              : pending.kind === "reactivate"
                ? `Reactivate ${pending.user.full_name}?`
                : `New setup link for ${pending.user.full_name}?`
          }
          description={
            pending.kind === "deactivate"
              ? "They are signed out immediately and cannot sign in. Their history is kept and the slot becomes free."
              : pending.kind === "reactivate"
                ? `This uses one active slot (${capacity.available} available).`
                : "Any earlier link stops working. The new link is shown once."
          }
          confirmLabel={pending.kind === "deactivate" ? "Deactivate" : pending.kind === "reactivate" ? "Reactivate" : "Create link"}
          busyLabel={pending.kind === "deactivate" ? "Deactivating…" : pending.kind === "reactivate" ? "Reactivating…" : "Creating…"}
        />
      )}

      {issued && (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setIssued(null)}
          busy={false}
          onConfirm={() => setIssued(null)}
          title="Setup link created"
          description="Share this link with the user. It replaces any earlier link."
          confirmLabel="Done"
          busyLabel="Done"
        >
          <SetupLinkPanel token={issued.setup_token} expiresAt={issued.setup_expires_at} name={issued.user.full_name} />
        </ConfirmDialog>
      )}
    </div>
  );
}

function CapacityCard({
  icon: Icon,
  label,
  value,
  caption,
  tone,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  caption: string;
  tone?: "warn";
}) {
  const id = `capacity-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <section aria-labelledby={id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <h3 id={id} className="text-sm font-medium text-slate-600">
          {label}
        </h3>
        <span className={cn("flex size-9 items-center justify-center rounded-lg", tone ? "bg-amber-50 text-amber-700" : "bg-blue-50 text-blue-700")}>
          <Icon className="size-4" aria-hidden="true" />
        </span>
      </div>
      <p className="mt-2 text-3xl font-semibold tracking-tight text-slate-900 tabular-nums" data-testid={`${id}-value`}>
        {value}
      </p>
      <p className={cn("mt-1 text-xs", tone ? "text-amber-700" : "text-slate-500")}>{caption}</p>
    </section>
  );
}

function SortHeader({
  label,
  field,
  query,
  onSort,
}: {
  label: string;
  field: SortKey;
  query: Query;
  onSort: (field: SortKey) => void;
}) {
  const active = query.sort === field;
  return (
    <th scope="col" className="py-2 pr-3 font-medium" aria-sort={active ? (query.order === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        onClick={() => onSort(field)}
        className="inline-flex items-center gap-1 rounded hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/40"
      >
        {label}
        {active &&
          (query.order === "asc" ? (
            <ArrowUp className="size-3" aria-hidden="true" />
          ) : (
            <ArrowDown className="size-3" aria-hidden="true" />
          ))}
      </button>
    </th>
  );
}

function ProtectedBadge() {
  return (
    <Pill tone="navy">
      <ShieldCheck className="size-3" aria-hidden="true" />
      Protected Admin
    </Pill>
  );
}

function StatusBadges({ user }: { user: CompanyUser }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      {user.status === "active" ? <Pill tone="green">Active</Pill> : <Pill tone="slate">Inactive</Pill>}
      {user.setup_pending && (
        <Pill tone="amber">{user.setup_link_expires_at ? "Setup pending" : "Setup link expired"}</Pill>
      )}
    </span>
  );
}

function RowActions({
  user,
  full,
  onEdit,
  onAction,
}: {
  user: CompanyUser;
  full: boolean;
  onEdit: (user: CompanyUser) => void;
  onAction: (kind: "deactivate" | "reactivate" | "link") => void;
}) {
  return (
    <span className="inline-flex flex-wrap justify-end gap-1.5">
      <Button type="button" variant="outline" className="h-8 px-2.5 text-xs" onClick={() => onEdit(user)}
        aria-label={`View or edit ${user.full_name}`}>
        Details
      </Button>
      {!user.is_protected && user.status === "active" && user.setup_pending && (
        <Button type="button" variant="outline" className="h-8 px-2.5 text-xs" onClick={() => onAction("link")}
          aria-label={`New setup link for ${user.full_name}`}>
          New link
        </Button>
      )}
      {!user.is_protected &&
        (user.status === "active" ? (
          <Button type="button" variant="outline" className="h-8 px-2.5 text-xs text-red-700 hover:text-red-800"
            onClick={() => onAction("deactivate")} aria-label={`Deactivate ${user.full_name}`}>
            Deactivate
          </Button>
        ) : (
          <Button type="button" variant="outline" className="h-8 px-2.5 text-xs" disabled={full}
            title={full ? "No active slot available" : undefined}
            onClick={() => onAction("reactivate")} aria-label={`Reactivate ${user.full_name}`}>
            Reactivate
          </Button>
        ))}
    </span>
  );
}

export function UsersSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading users" className="space-y-5">
      <div className="grid gap-5 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-32 animate-pulse rounded-2xl bg-slate-200/70" />
        ))}
      </div>
      <div className="h-80 animate-pulse rounded-2xl bg-slate-200/70" />
      <span className="sr-only">Loading users…</span>
      <Loader2 className="hidden" aria-hidden="true" />
    </div>
  );
}
