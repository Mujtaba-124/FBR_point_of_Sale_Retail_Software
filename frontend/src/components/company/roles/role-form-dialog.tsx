"use client";

import { useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { PermissionMatrix } from "@/components/company/roles/permission-matrix";
import { ErrorAlert, Field, INPUT_CLASS, PRIMARY_BUTTON } from "@/components/company/ui-kit";
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
import type { CompanyRoleItem, PermissionCatalog } from "@/lib/api/types";

const CONTROL_RE = /[\u0000-\u001f\u007f]/;

export function validateRoleName(raw: string): string | null {
  const name = raw.trim().replace(/\s+/g, " ");
  if (name.length < 2 || name.length > 60) return "The role name must be 2-60 characters.";
  if (CONTROL_RE.test(raw)) return "The role name contains characters that are not allowed.";
  return null;
}

type Props = {
  /** Existing role to edit or view; undefined creates a new custom role. */
  role?: CompanyRoleItem;
  catalog: PermissionCatalog;
  onOpenChange: (open: boolean) => void;
  onSaved: (role: CompanyRoleItem) => void;
  onStale: () => void;
};

export function RoleFormDialog({ role, catalog, onOpenChange, onSaved, onStale }: Props) {
  const readOnly = Boolean(role?.is_system || (role && !role.is_active));
  const [name, setName] = useState(role?.name ?? "");
  const [description, setDescription] = useState(role?.description ?? "");
  const [selected, setSelected] = useState<Set<string>>(() => new Set(role?.permissions ?? []));
  const [nameError, setNameError] = useState<string | null>(null);
  const [serverError, setServerError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);
  const inFlight = useRef(false);

  function toggle(key: string, checked: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (readOnly || inFlight.current) return;
    const problem = validateRoleName(name);
    setNameError(problem);
    if (problem) return;
    inFlight.current = true;
    setSaving(true);
    setServerError(null);
    const body = {
      name: name.trim(),
      description: description.trim() || null,
      permissions: [...selected].sort(),
    };
    try {
      const saved = role
        ? await apiFetch<CompanyRoleItem>(`/company/roles/${role.id}`, {
            method: "PATCH",
            body: JSON.stringify({ ...body, expected_version: role.version }),
          })
        : await apiFetch<CompanyRoleItem>("/company/roles", {
            method: "POST",
            body: JSON.stringify(body),
          });
      onSaved(saved);
    } catch (error) {
      const err =
        error instanceof ApiError ? error : new ApiError(0, "unknown", "The role could not be saved.");
      if (err.code === "role_name_taken" || err.code === "invalid_role") setNameError(err.message);
      else setServerError(err);
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  const title = role ? (readOnly ? role.name : `Edit ${role.name}`) : "Create role";

  return (
    <Dialog open onOpenChange={(next) => !saving && onOpenChange(next)}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="text-lg font-semibold text-slate-900">{title}</DialogTitle>
          <DialogDescription>
            {role?.is_system
              ? "Protected system role. It cannot be changed."
              : role && !role.is_active
                ? "This role has been retired and cannot be edited."
                : "Users with this role receive exactly the permissions selected below."}
          </DialogDescription>
        </DialogHeader>
        <form noValidate onSubmit={save} className="space-y-4" aria-label={title}>
          {serverError && (
            <ErrorAlert
              action={
                serverError.code === "stale_role" ? (
                  <Button type="button" variant="outline" className="h-8 bg-white" onClick={onStale}>
                    Reload roles
                  </Button>
                ) : undefined
              }
            >
              {serverError.message}
            </ErrorAlert>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="role-name" label="Role name" error={nameError}>
              <Input
                id="role-name"
                className={INPUT_CLASS}
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  setNameError(null);
                }}
                disabled={readOnly}
                aria-invalid={nameError ? true : undefined}
                maxLength={60}
              />
            </Field>
            <Field id="role-description" label="Description" hint="Optional.">
              <Input
                id="role-description"
                className={INPUT_CLASS}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                disabled={readOnly}
                maxLength={300}
              />
            </Field>
          </div>
          <fieldset>
            <legend className="mb-2 text-sm font-semibold text-slate-900">Permissions</legend>
            <PermissionMatrix
              catalog={catalog}
              selected={selected}
              onToggle={toggle}
              readOnly={readOnly}
              adminRole={role?.system_key === "company_admin"}
            />
          </fieldset>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              className="h-10"
              disabled={saving}
              onClick={() => onOpenChange(false)}
            >
              {readOnly ? "Close" : "Cancel"}
            </Button>
            {!readOnly && (
              <Button type="submit" disabled={saving} className={PRIMARY_BUTTON}>
                {saving && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
                {saving ? "Saving…" : role ? "Save role" : "Create role"}
              </Button>
            )}
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
