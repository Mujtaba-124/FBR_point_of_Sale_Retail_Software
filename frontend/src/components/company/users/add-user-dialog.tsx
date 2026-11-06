"use client";

import { useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import {
  ErrorAlert,
  Field,
  INPUT_CLASS,
  PRIMARY_BUTTON,
  SELECT_CLASS,
  SuccessNote,
} from "@/components/company/ui-kit";
import { SetupLinkPanel } from "@/components/company/users/setup-link-panel";
import { ShopAccessField } from "@/components/company/users/shop-access-field";
import { shopAccessError } from "@/components/company/users/shop-access-rules";
import {
  type NewUserErrors,
  type NewUserValues,
  validateNewUser,
} from "@/components/company/users/user-validation";
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
import type { CompanyRoleItem, SetupLinkIssued, ShopAccessMode } from "@/lib/api/types";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  roles: CompanyRoleItem[];
  slotsAvailable: number;
  onCreated: (result: SetupLinkIssued) => void;
};

/** Mounted fresh per opening (keyed by the caller), so state never leaks between users. */
export function AddUserDialog({ open, onOpenChange, roles, slotsAvailable, onCreated }: Props) {
  const assignable = roles.filter((r) => r.is_active && r.system_key !== "company_admin");
  const defaultRole = assignable.find((r) => r.system_key === "company_user") ?? assignable[0];
  const [values, setValues] = useState<NewUserValues>({
    full_name: "",
    email: "",
    role_id: defaultRole?.id ?? "",
  });
  const [errors, setErrors] = useState<NewUserErrors>({});
  // Safe default: no shop data until the Company Admin assigns shops.
  const [shopMode, setShopMode] = useState<ShopAccessMode>("none");
  const [shopIds, setShopIds] = useState<Set<string>>(new Set());
  const [shopError, setShopError] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [created, setCreated] = useState<SetupLinkIssued | null>(null);
  const inFlight = useRef(false);
  const full = slotsAvailable <= 0;

  function set<K extends keyof NewUserValues>(key: K, value: string) {
    setErrors((e) => ({ ...e, [key]: undefined }));
    setServerError(null);
    setValues((v) => ({ ...v, [key]: value }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (inFlight.current || full) return;
    const problems = validateNewUser(values);
    setErrors(problems);
    const shopProblem = shopAccessError(shopMode, shopIds);
    setShopError(shopProblem);
    if (Object.values(problems).some(Boolean) || shopProblem) return;
    inFlight.current = true;
    setSaving(true);
    setServerError(null);
    try {
      const result = await apiFetch<SetupLinkIssued>("/company/users", {
        method: "POST",
        body: JSON.stringify({
          full_name: values.full_name.trim(),
          email: values.email.trim(),
          role_id: values.role_id,
          shop_access: { mode: shopMode, shop_ids: shopMode === "selected" ? [...shopIds] : [] },
        }),
      });
      setCreated(result);
      onCreated(result);
    } catch (error) {
      const err =
        error instanceof ApiError ? error : new ApiError(0, "unknown", "The user could not be added.");
      if (err.code === "email_already_exists" || err.code === "email_belongs_to_inactive_user") {
        setErrors({ email: err.message });
      } else if (err.code === "invalid_shop_access") {
        setShopError(err.message);
      } else {
        setServerError(err.message);
      }
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  const role = assignable.find((r) => r.id === values.role_id);

  return (
    <Dialog open={open} onOpenChange={(next) => !saving && onOpenChange(next)}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-lg font-semibold text-slate-900">
            {created ? "User added" : "Add user"}
          </DialogTitle>
          <DialogDescription>
            {created
              ? "The account is active and waiting for the user to set a password."
              : "The user sets their own password through a one-time link."}
          </DialogDescription>
        </DialogHeader>

        {created ? (
          <div className="space-y-4">
            <SuccessNote>
              <strong>{created.user.full_name}</strong> was added. Active users:{" "}
              {created.capacity.active} / {created.capacity.limit}.
            </SuccessNote>
            <SetupLinkPanel
              token={created.setup_token}
              expiresAt={created.setup_expires_at}
              name={created.user.full_name}
            />
            <div className="flex justify-end">
              <Button type="button" className={PRIMARY_BUTTON} onClick={() => onOpenChange(false)}>
                Done
              </Button>
            </div>
          </div>
        ) : (
          <form noValidate onSubmit={submit} className="min-w-0 space-y-4" aria-label="Add user">
            {full && (
              <ErrorAlert>
                All active user slots are in use. Deactivate a user to free a slot before adding
                another.
              </ErrorAlert>
            )}
            {serverError && <ErrorAlert>{serverError}</ErrorAlert>}
            <Field id="new-user-name" label="Full name" error={errors.full_name}>
              <Input
                id="new-user-name"
                className={INPUT_CLASS}
                value={values.full_name}
                onChange={(e) => set("full_name", e.target.value)}
                aria-invalid={errors.full_name ? true : undefined}
                aria-describedby={errors.full_name ? "new-user-name-error" : undefined}
                autoComplete="off"
                maxLength={200}
              />
            </Field>
            <Field
              id="new-user-email"
              label="Email address"
              error={errors.email}
              hint="The user signs in with this address."
            >
              <Input
                id="new-user-email"
                type="email"
                className={INPUT_CLASS}
                value={values.email}
                onChange={(e) => set("email", e.target.value)}
                aria-invalid={errors.email ? true : undefined}
                aria-describedby={errors.email ? "new-user-email-error" : "new-user-email-hint"}
                autoComplete="off"
                spellCheck={false}
                maxLength={320}
              />
            </Field>
            <Field
              id="new-user-role"
              label="Role"
              error={errors.role_id}
              hint={
                role
                  ? `${role.permissions.length} permission${role.permissions.length === 1 ? "" : "s"}${role.description ? ` · ${role.description}` : ""}`
                  : undefined
              }
            >
              <select
                id="new-user-role"
                className={SELECT_CLASS}
                value={values.role_id}
                onChange={(e) => set("role_id", e.target.value)}
                aria-invalid={errors.role_id ? true : undefined}
              >
                {assignable.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </Field>
            <ShopAccessField
              mode={shopMode}
              onModeChange={(m) => {
                setShopMode(m);
                setShopError(null);
              }}
              selected={shopIds}
              onSelectedChange={(next) => {
                setShopIds(next);
                setShopError(null);
              }}
              error={shopError}
              disabled={saving}
            />
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button
                type="button"
                variant="outline"
                className="h-10"
                disabled={saving}
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={saving || full} className={PRIMARY_BUTTON}>
                {saving && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
                {saving ? "Adding…" : "Add user"}
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
