"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, RefreshCw, ShieldCheck } from "lucide-react";

import { RoleFormDialog } from "@/components/company/roles/role-form-dialog";
import {
  ConfirmDialog,
  ErrorAlert,
  Field,
  Pill,
  PRIMARY_BUTTON,
  SELECT_CLASS,
  SuccessNote,
} from "@/components/company/ui-kit";
import { Topbar } from "@/components/super-admin/topbar";
import { Button } from "@/components/ui/button";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { CompanyRoleItem, PermissionCatalog, RoleListPayload } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type Editor = { mode: "create" } | { mode: "edit"; role: CompanyRoleItem } | null;

export function RolesView({
  initial,
  catalog,
}: {
  initial: CompanyRoleItem[];
  catalog: PermissionCatalog;
}) {
  const router = useRouter();
  const [roles, setRoles] = useState(initial);
  const [editor, setEditor] = useState<Editor>(null);
  const [editorKey, setEditorKey] = useState(0);
  const [retiring, setRetiring] = useState<CompanyRoleItem | null>(null);
  const [reassignTo, setReassignTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [retireError, setRetireError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  async function reload() {
    setLoading(true);
    setLoadError(null);
    try {
      setRoles((await apiFetch<RoleListPayload>("/company/roles")).items);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "The roles could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  function open(next: Editor) {
    setNotice(null);
    setEditorKey((k) => k + 1);
    setEditor(next);
  }

  async function retire() {
    if (!retiring || busy) return;
    setBusy(true);
    setRetireError(null);
    try {
      await apiFetch<CompanyRoleItem>(`/company/roles/${retiring.id}/retire`, {
        method: "POST",
        body: JSON.stringify({
          expected_version: retiring.version,
          reassign_to_role_id: retiring.total_users ? reassignTo || null : null,
        }),
      });
      setNotice(`${retiring.name} was retired.`);
      setRetiring(null);
      await reload();
    } catch (e) {
      setRetireError(e instanceof ApiError ? e.message : "The role could not be retired.");
    } finally {
      setBusy(false);
    }
  }

  const targets = roles.filter(
    (r) => r.is_active && r.system_key !== "company_admin" && r.id !== retiring?.id,
  );

  return (
    <div className="space-y-6">
      <Topbar
        title="Roles & Permissions"
        description="Define what each role can access in the Company Workspace."
        actions={
          <>
            <Button type="button" variant="outline" className="h-10 gap-2" disabled={loading} onClick={() => void reload()}>
              <RefreshCw className={cn("size-4", loading && "animate-spin")} aria-hidden="true" />
              Refresh
            </Button>
            <Button type="button" className={PRIMARY_BUTTON} onClick={() => open({ mode: "create" })}>
              <Plus className="size-4" aria-hidden="true" />
              Create Role
            </Button>
          </>
        }
      />
      {notice && <SuccessNote>{notice}</SuccessNote>}
      {loadError && <ErrorAlert>{loadError}</ErrorAlert>}

      <section aria-labelledby="roles-heading" className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 id="roles-heading" className="mb-4 flex items-center gap-2.5 text-[15px] font-semibold text-slate-900">
          <span className="flex size-8 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
            <ShieldCheck className="size-4" aria-hidden="true" />
          </span>
          Roles
        </h2>
        <div className="hidden overflow-x-auto md:block">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Company roles</caption>
            <thead className="text-xs text-slate-500">
              <tr className="border-b border-slate-200">
                <th scope="col" className="py-2 pr-3 font-medium">Role</th>
                <th scope="col" className="py-2 pr-3 font-medium">Description</th>
                <th scope="col" className="py-2 pr-3 font-medium">Assigned users</th>
                <th scope="col" className="py-2 pr-3 font-medium">Status</th>
                <th scope="col" className="py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {roles.map((r) => (
                <tr key={r.id} className="align-middle">
                  <td className="py-3 pr-3 font-medium text-slate-900">
                    <span className="flex flex-wrap items-center gap-2">
                      {r.name}
                      {r.is_system && <Pill tone="navy">System role</Pill>}
                    </span>
                  </td>
                  <td className="max-w-xs py-3 pr-3 text-slate-600">{r.description ?? "—"}</td>
                  <td className="py-3 pr-3 text-slate-700 tabular-nums">
                    {r.active_users} active{r.total_users > r.active_users ? ` · ${r.total_users - r.active_users} inactive` : ""}
                  </td>
                  <td className="py-3 pr-3">
                    <RoleStatus role={r} />
                  </td>
                  <td className="py-3 text-right">
                    <RoleActions role={r} onOpen={(role) => open({ mode: "edit", role })} onRetire={(role) => { setRetireError(null); setReassignTo(""); setRetiring(role); }} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="space-y-3 md:hidden" aria-label="Company roles">
          {roles.map((r) => (
            <li key={r.id} className="rounded-xl border border-slate-200 p-3 text-sm">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <span className="font-medium text-slate-900">{r.name}</span>
                <RoleStatus role={r} />
              </div>
              {r.description && <p className="mt-1 text-slate-600">{r.description}</p>}
              <p className="mt-1 text-xs text-slate-500">
                {r.active_users} active user{r.active_users === 1 ? "" : "s"}
                {r.is_system ? " · System role" : ""}
              </p>
              <div className="mt-2">
                <RoleActions role={r} onOpen={(role) => open({ mode: "edit", role })} onRetire={(role) => { setRetireError(null); setReassignTo(""); setRetiring(role); }} />
              </div>
            </li>
          ))}
        </ul>
      </section>

      {editor && (
        <RoleFormDialog
          key={editorKey}
          role={editor.mode === "edit" ? editor.role : undefined}
          catalog={catalog}
          onOpenChange={(o) => !o && setEditor(null)}
          onStale={() => {
            setEditor(null);
            void reload();
            router.refresh();
          }}
          onSaved={(saved) => {
            setEditor(null);
            setNotice(`${saved.name} was saved.`);
            void reload();
          }}
        />
      )}

      {retiring && (
        <ConfirmDialog
          open
          onOpenChange={(o) => !o && setRetiring(null)}
          busy={busy}
          destructive
          error={retireError}
          onConfirm={() => void retire()}
          title={`Retire ${retiring.name}?`}
          description={
            retiring.total_users
              ? `${retiring.total_users} user(s) have this role. Choose the role they move to. Retired roles grant nothing and cannot be assigned.`
              : "Retired roles grant nothing and cannot be assigned. The role stays in the list for history."
          }
          confirmLabel="Retire role"
          busyLabel="Retiring…"
        >
          {retiring.total_users > 0 && (
            <Field id="reassign-role" label="Move users to">
              <select id="reassign-role" className={SELECT_CLASS} value={reassignTo} onChange={(e) => setReassignTo(e.target.value)}>
                <option value="">Choose a role</option>
                {targets.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}

function RoleStatus({ role }: { role: CompanyRoleItem }) {
  return role.is_active ? <Pill tone="green">Active</Pill> : <Pill tone="slate">Retired</Pill>;
}

function RoleActions({
  role,
  onOpen,
  onRetire,
}: {
  role: CompanyRoleItem;
  onOpen: (role: CompanyRoleItem) => void;
  onRetire: (role: CompanyRoleItem) => void;
}) {
  const editable = !role.is_system && role.is_active;
  return (
    <span className="inline-flex flex-wrap justify-end gap-1.5">
      <Button type="button" variant="outline" className="h-8 px-2.5 text-xs" onClick={() => onOpen(role)}
        aria-label={`${editable ? "Edit" : "View"} ${role.name}`}>
        {editable ? "Edit" : "View"}
      </Button>
      {editable && (
        <Button type="button" variant="outline" className="h-8 px-2.5 text-xs text-red-700 hover:text-red-800"
          onClick={() => onRetire(role)} aria-label={`Retire ${role.name}`}>
          Retire
        </Button>
      )}
    </span>
  );
}
