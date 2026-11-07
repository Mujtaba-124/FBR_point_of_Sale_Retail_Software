"use client";

import { useRef, useState } from "react";
import { Eye, EyeOff, KeyRound, Loader2 } from "lucide-react";

import {
  FIELD_FOR_CODE,
  formatTaxRate,
  normalize,
  type ShopErrors,
  type ShopValues,
  toHundredths,
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

export const TAX_CHANGE_NOTE =
  "The new Sales Tax % applies to new upload batches. Existing saved uploads and revisions keep their original applied tax rate.";

const FIELDS: { key: Exclude<keyof ShopValues, "sales_tax_rate">; label: string; hint?: string; max: number }[] = [
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
    sales_tax_rate: shop?.sales_tax_rate ? formatTaxRate(shop.sales_tax_rate).replace(/%$/, "") : "",
  });
  const [confirmRate, setConfirmRate] = useState(false);
  const [newToken, setNewToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [errors, setErrors] = useState<ShopErrors>({});
  const [serverError, setServerError] = useState<ApiError | null>(null);
  const [tokenNote, setTokenNote] = useState<string | null>(null);
  const [saving, setSaving] = useState<"profile" | "token" | null>(null);
  const inFlight = useRef(false);

  const rateText = values.sales_tax_rate.trim().replace(/%$/, "").trim();
  // Changed only when it is a valid new value (an invalid one is reported on submit).
  const rateChanged =
    current !== undefined &&
    rateText !== "" &&
    (current.sales_tax_rate === null ||
      !/^\d{1,3}(\.\d{1,2})?$/.test(rateText) ||
      toHundredths(rateText) !== toHundredths(current.sales_tax_rate));
  const dirty =
    !editing ||
    (current !== undefined &&
      (normalize(values.name) !== current.name ||
        normalize(values.branch_name) !== current.branch_name ||
        values.code.trim() !== current.code ||
        values.pos_id.trim() !== current.pos_id ||
        rateChanged ||
        (rateText === "" && current.sales_tax_rate !== null)));

  function set(key: keyof ShopValues, value: string) {
    setErrors((e) => ({ ...e, [key]: undefined }));
    setServerError(null);
    if (key === "sales_tax_rate") setConfirmRate(false);
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
    // A new shop needs a rate; an older shop may stay "Not configured", but a
    // configured rate can only be changed, never removed.
    const problems = validateShop(values, {
      taxRateRequired: !editing || (current !== undefined && current.sales_tax_rate !== null),
    });
    if (!editing && can.manageToken && newToken.trim()) {
      const t = tokenProblem(newToken);
      if (t) problems.fbr_token = t;
    }
    setErrors(problems);
    if (Object.values(problems).some(Boolean)) return;
    // Changing a configured rate needs an explicit second step.
    if (editing && current?.sales_tax_rate !== null && rateChanged && !confirmRate) {
      setConfirmRate(true);
      return;
    }
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
          body: JSON.stringify({
            ...payload,
            ...(rateChanged ? { sales_tax_rate: rateText } : {}),
            expected_version: current.version,
          }),
        });
        setCurrent(saved);
        setConfirmRate(false);
        onSaved(
          saved,
          rateChanged
            ? `${saved.name} was updated. Sales Tax % is now ${formatTaxRate(saved.sales_tax_rate)} for new uploads.`
            : `${saved.name} was updated.`,
        );
      } else {
        const token = can.manageToken && newToken.trim() ? newToken.trim() : null;
        const body = { ...payload, sales_tax_rate: rateText };
        const saved = await apiFetch<Shop>("/company/shops", {
          method: "POST",
          body: JSON.stringify(token ? { ...body, fbr_token: token } : body),
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
            <Field
              id="shop-sales_tax_rate"
              label="Sales Tax %"
              error={errors.sales_tax_rate}
              hint={
                editing
                  ? current?.sales_tax_rate === null
                    ? "Not configured yet. Set it before this shop can take new Excel uploads."
                    : "Changes apply to new upload batches only."
                  : "Applied to this shop's Excel uploads (tax exclusive). 0 to 100, up to 2 decimals."
              }
            >
              <div className="relative">
                <Input
                  id="shop-sales_tax_rate"
                  name="shop_sales_tax_rate"
                  {...NO_CREDENTIAL_AUTOFILL}
                  className={cn(INPUT_CLASS, "pr-9 tabular-nums")}
                  value={values.sales_tax_rate}
                  onChange={(e) => set("sales_tax_rate", e.target.value)}
                  disabled={readOnly || busy}
                  inputMode="decimal"
                  placeholder="e.g. 18"
                  maxLength={7}
                  aria-invalid={errors.sales_tax_rate ? true : undefined}
                  aria-describedby={errors.sales_tax_rate ? "shop-sales_tax_rate-error" : "shop-sales_tax_rate-hint"}
                />
                <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-sm text-slate-500" aria-hidden="true">
                  %
                </span>
              </div>
            </Field>
          </div>

          {confirmRate && current && (
            <div role="group" aria-label="Confirm Sales Tax % change" className="space-y-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              <p>
                Change Sales Tax % from <strong>{formatTaxRate(current.sales_tax_rate)}</strong> to{" "}
                <strong>{formatTaxRate(rateText)}</strong>?
              </p>
              <p>{TAX_CHANGE_NOTE}</p>
            </div>
          )}

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
              <Button
                type="button"
                variant="outline"
                className="h-10"
                disabled={busy}
                onClick={() => (confirmRate ? setConfirmRate(false) : onOpenChange(false))}
              >
                {confirmRate ? "Back" : "Cancel"}
              </Button>
              <Button type="submit" disabled={busy || !dirty} className={PRIMARY_BUTTON}>
                {saving === "profile" && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
                {saving === "profile" ? "Saving…" : confirmRate ? "Confirm and save" : editing ? "Save changes" : "Add shop"}
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

/** Compact Sales Tax % for lists: "18%", "0%", or an amber "Not configured". */
export function TaxRateBadge({ rate }: { rate: string | null }) {
  if (rate === null) return <Pill tone="amber">Not configured</Pill>;
  return <span className="font-medium tabular-nums text-slate-800">{formatTaxRate(rate)}</span>;
}

export function TokenBadge({ status }: { status: Shop["fbr_token_status"] }) {
  if (status === "configured") return <Pill tone="green">Token configured</Pill>;
  if (status === "unreadable") return <Pill tone="amber">Token needs re-entry</Pill>;
  return <Pill tone="slate">Token not configured</Pill>;
}
