"use client";

import { useRef, useState } from "react";
import { Loader2, ShieldCheck } from "lucide-react";

import { DetailList } from "@/components/super-admin/dashboard-card";
import {
  ErrorAlert,
  Field,
  INPUT_CLASS,
  PRIMARY_BUTTON,
  SELECT_CLASS,
} from "@/components/company/ui-kit";
import { ShopAccessSection } from "@/components/company/users/shop-access-section";
import { validateFullName } from "@/components/company/users/user-validation";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { CompanyRoleItem, CompanyUser } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

type Props = {
  user: CompanyUser;
  roles: CompanyRoleItem[];
  onOpenChange: (open: boolean) => void;
  onSaved: (user: CompanyUser) => void;
  /** Shop access was saved (the list badge should refresh). */
  onShopAccessSaved?: () => void;
};

/** User details plus the editable fields: full name and role (role is locked for the Company Admin). */
export function EditUserDialog({ user, roles, onOpenChange, onSaved, onShopAccessSaved }: Props) {
  const [name, setName] = useState(user.full_name);
  const [roleId, setRoleId] = useState(user.role?.id ?? "");
  const [nameError, setNameError] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const inFlight = useRef(false);

  const assignable = roles.filter(
    (r) => r.system_key !== "company_admin" && (r.is_active || r.id === user.role?.id),
  );
  const dirty = name.trim() !== user.full_name || (!user.is_protected && roleId !== user.role?.id);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (inFlight.current) return;
    const problem = validateFullName(name);
    setNameError(problem);
    if (problem) return;
    inFlight.current = true;
    setSaving(true);
    setServerError(null);
    const body: Record<string, string> = {};
    if (name.trim() !== user.full_name) body.full_name = name.trim();
    if (!user.is_protected && roleId && roleId !== user.role?.id) body.role_id = roleId;
    try {
      const saved = await apiFetch<CompanyUser>(`/company/users/${user.id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      onSaved(saved);
    } catch (error) {
      setServerError(
        error instanceof ApiError ? error.message : "The changes could not be saved.",
      );
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(next) => !saving && onOpenChange(next)}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-lg font-semibold text-slate-900">User details</DialogTitle>
          <DialogDescription>{user.email}</DialogDescription>
        </DialogHeader>
        <DetailList
          items={[
            { label: "Status", value: user.status === "active" ? "Active" : "Inactive" },
            {
              label: "Password",
              value: user.setup_pending
                ? user.setup_link_expires_at
                  ? `Setup link valid until ${formatDateTime(user.setup_link_expires_at)}`
                  : "Setup link expired"
                : "Set",
            },
            { label: "Last login", value: formatDateTime(user.last_login_at) },
            { label: "Added", value: formatDateTime(user.created_at) },
          ]}
        />
        <form noValidate onSubmit={save} className="space-y-4" aria-label="Edit user">
          {serverError && <ErrorAlert>{serverError}</ErrorAlert>}
          <Field id="edit-user-name" label="Full name" error={nameError}>
            <Input
              id="edit-user-name"
              className={INPUT_CLASS}
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setNameError(null);
              }}
              aria-invalid={nameError ? true : undefined}
              maxLength={200}
            />
          </Field>
          {user.is_protected ? (
            <p className="flex items-start gap-2 rounded-lg bg-slate-50 p-3 text-sm text-slate-600 ring-1 ring-inset ring-slate-100">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-blue-700" aria-hidden="true" />
              The Company Admin is protected: its role and status cannot be changed here.
            </p>
          ) : (
            <Field id="edit-user-role" label="Role">
              <select
                id="edit-user-role"
                className={SELECT_CLASS}
                value={roleId}
                onChange={(e) => setRoleId(e.target.value)}
              >
                {assignable.map((r) => (
                  <option key={r.id} value={r.id} disabled={!r.is_active}>
                    {r.name}
                    {r.is_active ? "" : " (retired)"}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              className="h-10"
              disabled={saving}
              onClick={() => onOpenChange(false)}
            >
              Close
            </Button>
            <Button type="submit" disabled={saving || !dirty} className={PRIMARY_BUTTON}>
              {saving && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
              {saving ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </form>
        <ShopAccessSection user={user} onSaved={() => onShopAccessSaved?.()} />
      </DialogContent>
    </Dialog>
  );
}
