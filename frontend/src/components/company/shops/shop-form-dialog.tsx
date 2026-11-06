"use client";

import { useRef, useState } from "react";
import { Eye, EyeOff, KeyRound, Loader2 } from "lucide-react";

import {
  FIELD_FOR_CODE,
  normalize,
  type ShopErrors,
  type ShopValues,
  tokenProblem,
  validateShop,
} from "@/components/company/shops/shop-validation";
import { ErrorAlert, Field, INPUT_CLASS, Pill, PRIMARY_BUTTON, SuccessNote } from "@/components/company/ui-kit";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { MASKED_TEXT, NO_CREDENTIAL_AUTOFILL } from "@/components/company/shops/no-autofill";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { Shop } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export type ShopAbilities = {
  create: boolean;
  edit: boolean;
  toggle: boolean;
  manageToken: boolean;
};

type Props = {
  /** Existing shop to view/edit; undefined adds a new shop. */
  shop?: Shop;
  can: ShopAbilities;
  onOpenChange: (open: boolean) => void;
  /** The server refused creation because the shop allowance is used up. */
  onLimitReached?: () => void;
  onSaved: (shop: Shop, message: string) => void;
  onStale: () => void;
};

const FIELDS: { key: keyof ShopValues; label: string; hint?: string; max: number }[] = [
  { key: "name", label: "Shop Name", max: 120 },
  { key: "branch_name", label: "Branch Name", max: 120 },
  { key: "code", label: "Shop Code", hint: "Unique. Letters, digits, - and _.", max: 20 },
  { key: "pos_id", label: "POS ID", hint: "Unique. Kept exactly as entered, leading zeros included.", max: 50 },
];

export function ShopFormDialog({ shop, can, onOpenChange, onSaved, onStale, onLimitReached }: Props) {
  const editing = Boolean(shop);
  const readOnly = editing && !can.edit;
  const [current, setCurrent] = useState<Shop | undefined>(shop);
  const [values, setValues] = useState<ShopValues>({
    name: shop?.name ?? "",
    branch_name: shop?.branch_name ?? "",
    code: shop?.code ?? "",
    pos_id: shop?.pos_id ?? "",
  });
  const [newToken, setNewToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [errors, setErrors] = useState<ShopErrors>({});
  const [serverError, setServerError] = useState<ApiError | null>(null);
  const [tokenNote, setTokenNote] = useState<string | null>(null);
  const [saving, setSaving] = useState<"profile" | "token" | null>(null);
  const inFlight = useRef(false);

  const dirty =
    !editing ||
    (current !== undefined &&
      (normalize(values.name) !== current.name ||
        normalize(values.branch_name) !== current.branch_name ||
        values.code.trim() !== current.code ||
        values.pos_id.trim() !== current.pos_id));

  function set(key: keyof ShopValues, value: string) {
    setErrors((e) => ({ ...e, [key]: undefined }));
    setServerError(null);
    setValues((v) => ({ ...v, [key]: value }));
  }

  function fail(error: unknown, fallback: string) {
    const err = error instanceof ApiError ? error : new ApiError(0, "unknown", fallback);
    const field = FIELD_FOR_CODE[err.code];
    if (field) setErrors((e) => ({ ...e, [field]: err.message }));
    else setServerError(err);
    if (err.code === "shop_limit_reached") onLimitReached?.();
  }

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault();
    if (inFlight.current || readOnly) return;
    const problems = validateShop(values);
    if (!editing && can.manageToken && newToken.trim()) {
      const t = tokenProblem(newToken);
      if (t) problems.fbr_token = t;
    }
    setErrors(problems);
    if (Object.values(problems).some(Boolean)) return;
    inFlight.current = true;
    setSaving("profile");
    setServerError(null);
    const payload = {
      name: normalize(values.name),
      branch_name: normalize(values.branch_name),
      code: values.code.trim(),
      pos_id: values.pos_id.trim(),
    };
    try {
      if (current) {
        const saved = await apiFetch<Shop>(`/company/shops/${current.id}`, {
          method: "PATCH",
          body: JSON.stringify({ ...payload, expected_version: current.version }),
        });
        setCurrent(saved);
        onSaved(saved, `${saved.name} was updated.`);
      } else {
        const token = can.manageToken && newToken.trim() ? newToken.trim() : null;
        const saved = await apiFetch<Shop>("/company/shops", {
          method: "POST",
          body: JSON.stringify(token ? { ...payload, fbr_token: token } : payload),
        });
        setNewToken("");
        onSaved(saved, `${saved.name} was added.`);
      }
    } catch (error) {
      fail(error, "The shop could not be saved.");
    } finally {
      inFlight.current = false;
      setSaving(null);
    }
  }

  async function saveToken() {
    if (!current || inFlight.current) return;
    const problem = tokenProblem(newToken);
    setErrors((e) => ({ ...e, fbr_token: problem ?? undefined }));
    if (problem) return;
    inFlight.current = true;
    setSaving("token");
    setServerError(null);
    setTokenNote(null);
    try {
      const saved = await apiFetch<Shop>(`/company/shops/${current.id}/fbr-token`, {
        method: "PUT",
        body: JSON.stringify({ fbr_token: newToken.trim(), expected_version: current.version }),
      });
      const replaced = current.fbr_token_status !== "not_configured";
      setCurrent(saved);
      setNewToken("");
      setShowToken(false);
      setTokenNote(replaced ? "FBR token replaced." : "FBR token saved.");
      onSaved(saved, `FBR token for ${saved.name} was ${replaced ? "replaced" : "saved"}.`);
    } catch (error) {
      fail(error, "The FBR token could not be saved.");
    } finally {
      inFlight.current = false;
      setSaving(null);
    }
  }

  const stale = serverError?.code === "stale_shop";
  const title = editing ? (readOnly ? current!.name : `Edit ${current!.name}`) : "Add shop";
  const busy = saving !== null;

  return (
    <Dialog open onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="text-lg font-semibold text-slate-900">{title}</DialogTitle>
          <DialogDescription>
            {editing
              ? readOnly
                ? "You can view this shop. Editing requires the Shops: Edit permission."
                : "Changes are saved only when you choose Save changes."
              : "Every shop needs a unique Shop Code and POS ID."}
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <ErrorAlert
            action={
              stale ? (
                <Button type="button" variant="outline" className="h-8 bg-white" onClick={onStale}>
                  Reload shops
                </Button>
              ) : undefined
            }
          >
            {serverError.message}
          </ErrorAlert>
        )}

        <form noValidate autoComplete="off" onSubmit={saveProfile} className="space-y-4" aria-label={title}>
          <div className="grid gap-4 sm:grid-cols-2">
            {FIELDS.map(({ key, label, hint, max }) => (
              <Field key={key} id={`shop-${key}`} label={label} error={errors[key]} hint={hint}>
                <Input
                  id={`shop-${key}`}
                  name={`shop_${key}`}
                  {...NO_CREDENTIAL_AUTOFILL}
                  className={INPUT_CLASS}
                  value={values[key]}
                  onChange={(e) => set(key, e.target.value)}
                  disabled={readOnly || busy}
                  aria-invalid={errors[key] ? true : undefined}
                  aria-describedby={errors[key] ? `shop-${key}-error` : hint ? `shop-${key}-hint` : undefined}
                  maxLength={max}
                  inputMode={key === "pos_id" ? "text" : undefined}
                />
              </Field>
            ))}
          </div>

          {!editing && can.manageToken && (
            <TokenInput
              value={newToken}
              onChange={(v) => {
                setNewToken(v);
                setErrors((e) => ({ ...e, fbr_token: undefined }));
              }}
              show={showToken}
              onToggle={() => setShowToken((s) => !s)}
              error={errors.fbr_token}
              label="FBR Token (optional)"
              hint="Leave blank to add it later. It is stored encrypted and never shown again."
              disabled={busy}
            />
          )}
          {!editing && !can.manageToken && (
            <p className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600 ring-1 ring-inset ring-slate-100">
              The FBR token is added by someone with the Shops: Manage FBR token permission.
            </p>
          )}

          {!readOnly && (
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button type="button" variant="outline" className="h-10" disabled={busy} onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={busy || !dirty} className={PRIMARY_BUTTON}>
                {saving === "profile" && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
                {saving === "profile" ? "Saving…" : editing ? "Save changes" : "Add shop"}
              </Button>
            </div>
          )}
        </form>

        {editing && current && (
          <form
            noValidate
            autoComplete="off"
            aria-labelledby="fbr-token-heading"
            className="space-y-3 border-t border-slate-100 pt-4"
            onSubmit={(e) => {
              e.preventDefault();
              void saveToken();
            }}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 id="fbr-token-heading" className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                <KeyRound className="size-4 text-blue-700" aria-hidden="true" />
                FBR Token
              </h3>
              <TokenBadge status={current.fbr_token_status} />
            </div>
            {current.fbr_token_updated_at && (
              <p className="text-xs text-slate-500">Last set {formatDateTime(current.fbr_token_updated_at)} PKT.</p>
            )}
            {tokenNote && <SuccessNote>{tokenNote}</SuccessNote>}
            {can.manageToken ? (
              <>
                <TokenInput
                  value={newToken}
                  onChange={(v) => {
                    setNewToken(v);
                    setTokenNote(null);
                    setErrors((e) => ({ ...e, fbr_token: undefined }));
                  }}
                  show={showToken}
                  onToggle={() => setShowToken((s) => !s)}
                  error={errors.fbr_token}
                  label={current.fbr_token_status === "not_configured" ? "New FBR token" : "Replacement FBR token"}
                  hint="Leave blank to keep the current token. The saved token is never displayed."
                  disabled={busy}
                />
                <div className="flex justify-end">
                  <Button
                    type="submit"
                    variant="outline"
                    className="h-10 gap-2"
                    disabled={busy || !newToken.trim()}
                  >
                    {saving === "token" && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
                    {saving === "token"
                      ? "Saving token…"
                      : current.fbr_token_status === "not_configured"
                        ? "Save token"
                        : "Replace token"}
                  </Button>
                </div>
              </>
            ) : (
              <p className="text-xs text-slate-500">
                Managing the FBR token requires the Shops: Manage FBR token permission.
              </p>
            )}
          </form>
        )}

        {readOnly && (
          <div className="flex justify-end">
            <Button type="button" variant="outline" className="h-10" onClick={() => onOpenChange(false)}>
              Close
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function TokenInput({
  value,
  onChange,
  show,
  onToggle,
  error,
  label,
  hint,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  show: boolean;
  onToggle: () => void;
  error?: string;
  label: string;
  hint: string;
  disabled: boolean;
}) {
  return (
    <Field id="shop-fbr-token" label={label} error={error} hint={hint}>
      <div className="relative">
        <Input
          id="shop-fbr-token"
          name="shop_fbr_integration_token"
          // Never type="password": that would make password managers offer
          // (or silently fill) a saved login password here. Masked with CSS.
          type="text"
          {...NO_CREDENTIAL_AUTOFILL}
          className={cn(INPUT_CLASS, "pr-11 font-mono", !show && MASKED_TEXT)}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          maxLength={2048}
          data-masked={show ? "false" : "true"}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "shop-fbr-token-error" : "shop-fbr-token-hint"}
        />
        <button
          type="button"
          onClick={onToggle}
          aria-label={show ? "Hide token" : "Show token"}
          aria-pressed={show}
          aria-controls="shop-fbr-token"
          className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-lg text-slate-500 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/40"
        >
          {show ? <EyeOff className="size-4" aria-hidden="true" /> : <Eye className="size-4" aria-hidden="true" />}
        </button>
      </div>
    </Field>
  );
}

export function TokenBadge({ status }: { status: Shop["fbr_token_status"] }) {
  if (status === "configured") return <Pill tone="green">Token configured</Pill>;
  if (status === "unreadable") return <Pill tone="amber">Token needs re-entry</Pill>;
  return <Pill tone="slate">Token not configured</Pill>;
}
