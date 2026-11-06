"use client";

import { type ReactNode, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Store } from "lucide-react";

import { ConfirmDialog, ErrorAlert, INPUT_CLASS, Pill, PRIMARY_BUTTON, SuccessNote } from "@/components/company/ui-kit";
import { DashboardCard } from "@/components/super-admin/dashboard-card";
import {
  type AllowanceMode,
  describeAllowance,
  parseShopLimit,
  slotsLeft,
} from "@/components/super-admin/subscription/shop-allowance-rules";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { ShopAllowance, ShopAllowanceUpdate } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const fmt = (n: number) => n.toLocaleString("en-US");

/**
 * Super Admin: how many shops the company may register. Aggregate numbers
 * only; this card never receives shop names, codes, POS IDs or tokens.
 * Saving is a two-step review + confirm, guarded against double submits and
 * stale forms (expected_version).
 */
export function ShopAllowanceCard({ initial }: { initial: ShopAllowance }) {
  const router = useRouter();
  const [current, setCurrent] = useState(initial);
  const [mode, setMode] = useState<AllowanceMode>(initial.mode);
  const [limitText, setLimitText] = useState(initial.max_shops !== null ? String(initial.max_shops) : "");
  const [touched, setTouched] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const inFlight = useRef(false);
  const [seen, setSeen] = useState(initial);

  // After router.refresh() the server sends fresh values. Adopt them when they
  // differ from what this card holds (another admin's change, new usage), but
  // keep our own just-saved state and success message.
  if (initial !== seen) {
    setSeen(initial);
    if (initial.version !== current.version || initial.registered_shops !== current.registered_shops) {
      setCurrent(initial);
      setMode(initial.mode);
      setLimitText(initial.max_shops !== null ? String(initial.max_shops) : "");
      setTouched(false);
      setServerError(null);
    }
  }

  const parsed = mode === "limited" ? parseShopLimit(limitText) : { value: null, error: null };
  const newMax = mode === "limited" ? parsed.value : null;
  const valid = parsed.error === null;
  const changed = mode !== current.mode || (mode === "limited" && newMax !== current.max_shops);
  const used = current.registered_shops;
  const reducesBelowUsage = mode === "limited" && newMax !== null && newMax < used;
  const fillsExactly = mode === "limited" && newMax !== null && newMax === used;
  const stale = serverError?.code === "stale_shop_allowance";

  function chooseMode(next: AllowanceMode) {
    setMode(next);
    setNotice(null);
    setServerError(null);
    if (next === "limited" && !limitText) setLimitText(String(Math.max(used, 1)));
  }

  function review() {
    setTouched(true);
    setNotice(null);
    setServerError(null);
    if (valid && changed) setReviewing(true);
  }

  async function save() {
    if (inFlight.current) return;
    inFlight.current = true;
    setSaving(true);
    setServerError(null);
    try {
      const result = await apiFetch<ShopAllowanceUpdate>("/super-admin/shop-allowance", {
        method: "PUT",
        body: JSON.stringify({ mode, max_shops: newMax, expected_version: current.version }),
      });
      setCurrent(result.allowance);
      setMode(result.allowance.mode);
      setLimitText(result.allowance.max_shops !== null ? String(result.allowance.max_shops) : "");
      setReviewing(false);
      setTouched(false);
      setNotice(
        result.changed
          ? `Shop allowance saved: ${describeAllowance(result.allowance.mode, result.allowance.max_shops)}.`
          : "These settings were already saved. Nothing changed.",
      );
      router.refresh();
    } catch (error) {
      setServerError(
        error instanceof ApiError ? error : new ApiError(0, "unknown", "The shop allowance could not be saved. Please try again."),
      );
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  function reload() {
    setReviewing(false);
    setServerError(null);
    router.refresh(); // fresh server values are adopted above
  }

  const available = slotsLeft(current.max_shops, used);

  return (
    <DashboardCard title="Shop Allowance" icon={Store}>
      <p className="-mt-1 mb-4 text-sm leading-relaxed text-slate-600">
        How many shops the company may register. Active and inactive shops both use a slot. Only you can change
        this; the Company Admin sees it as read-only.
      </p>

      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" aria-label="Current shop allowance">
        <Stat label="Allowance Mode" testId="allowance-mode">
          {current.mode === "unlimited" ? "Unlimited" : "Limited"}
        </Stat>
        <Stat label="Maximum Allowed Shops" testId="allowance-max">
          {current.max_shops !== null ? fmt(current.max_shops) : "Unlimited Shops"}
        </Stat>
        <Stat label="Total Shops Used" testId="allowance-used">
          {current.max_shops !== null ? `${fmt(used)} / ${fmt(current.max_shops)}` : fmt(used)}
        </Stat>
        <Stat label="Available Shop Slots" testId="allowance-available">
          {available !== null ? fmt(available) : "Unlimited"}
        </Stat>
        <Stat label="Last Updated" testId="allowance-updated" muted={!current.last_updated_at}>
          {current.last_updated_at ? formatDateTime(current.last_updated_at) : "Not changed yet"}
        </Stat>
      </dl>

      {current.over_limit && (
        <div
          role="status"
          className="mt-4 flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <p>
            Over limit: {fmt(used)} shops are registered but the allowance is {fmt(current.max_shops!)}. Existing shops
            stay intact; the company cannot add shops until the allowance is higher than the registered count.
          </p>
        </div>
      )}
      {!current.over_limit && current.at_capacity && (
        <p className="mt-4 text-sm text-slate-600">
          <Pill tone="amber">Shop limit reached</Pill>{" "}
          <span className="align-middle">The company cannot add more shops until you raise the allowance.</span>
        </p>
      )}

      <form
        noValidate
        autoComplete="off"
        className="mt-5 space-y-4 border-t border-slate-100 pt-5"
        aria-label="Change shop allowance"
        onSubmit={(e) => {
          e.preventDefault();
          review();
        }}
      >
        <fieldset>
          <legend className="mb-2 text-sm font-medium text-slate-900">Allowance</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            <ModeOption
              value="limited"
              checked={mode === "limited"}
              onChange={chooseMode}
              title="Limited Shops"
              hint="Set a maximum number of registered shops."
              disabled={saving}
            />
            <ModeOption
              value="unlimited"
              checked={mode === "unlimited"}
              onChange={chooseMode}
              title="Unlimited Shops"
              hint="No limit on the number of shops."
              disabled={saving}
            />
          </div>
        </fieldset>

        {mode === "limited" ? (
          <div className="max-w-xs">
            <label htmlFor="shop-allowance-max" className="mb-1.5 block text-sm font-medium text-slate-900">
              Maximum Shops
            </label>
            <Input
              id="shop-allowance-max"
              name="allowance_max_shops"
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              autoComplete="off"
              className={INPUT_CLASS}
              value={limitText}
              onChange={(e) => {
                setLimitText(e.target.value);
                setNotice(null);
                setServerError(null);
              }}
              onBlur={() => setTouched(true)}
              disabled={saving}
              maxLength={7}
              aria-invalid={touched && parsed.error ? true : undefined}
              aria-describedby={touched && parsed.error ? "shop-allowance-max-error" : "shop-allowance-max-hint"}
            />
            {touched && parsed.error ? (
              <p id="shop-allowance-max-error" className="mt-1.5 text-xs text-destructive">
                {parsed.error}
              </p>
            ) : (
              <p id="shop-allowance-max-hint" className="mt-1.5 text-xs text-slate-500">
                A whole number, at least 1. Registered now: {fmt(used)}.
              </p>
            )}
          </div>
        ) : (
          <p className="text-sm text-slate-600">
            <Pill tone="blue">Unlimited Shops</Pill>{" "}
            <span className="align-middle">The company can register any number of shops.</span>
          </p>
        )}

        {valid && changed && reducesBelowUsage && (
          <ImpactNote tone="warn">
            {fmt(used)} shops are already registered, more than the new maximum of {fmt(newMax!)}. No shop will be
            deactivated or deleted, and existing shops stay usable. Adding shops will be blocked until the allowance is
            higher than the registered count.
          </ImpactNote>
        )}
        {valid && changed && fillsExactly && (
          <ImpactNote tone="warn">
            All {fmt(newMax!)} slots will be in use, so the company will not be able to add another shop.
          </ImpactNote>
        )}

        {notice && <SuccessNote>{notice}</SuccessNote>}
        {serverError && !reviewing && (
          <ErrorAlert
            action={
              stale ? (
                <Button type="button" variant="outline" className="h-8 bg-white" onClick={reload}>
                  Load latest values
                </Button>
              ) : undefined
            }
          >
            {serverError.message}
          </ErrorAlert>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" className={PRIMARY_BUTTON} disabled={saving || !changed}>
            Save Changes
          </Button>
          {!changed && <span className="text-xs text-slate-500">No changes to save.</span>}
        </div>
      </form>

      <ConfirmDialog
        open={reviewing}
        onOpenChange={(open) => {
          setReviewing(open);
          if (!open && !stale) setServerError(null);
        }}
        title="Review shop allowance"
        description="Check the change before saving. It applies to the Company Workspace immediately."
        confirmLabel="Confirm and save"
        busyLabel="Saving…"
        busy={saving}
        error={serverError?.message ?? null}
        onConfirm={() => void save()}
      >
        <dl className="divide-y divide-slate-100 rounded-lg border border-slate-200 text-sm">
          <ReviewRow label="Current">{describeAllowance(current.mode, current.max_shops)}</ReviewRow>
          <ReviewRow label="New">
            <strong>{describeAllowance(mode, newMax)}</strong>
          </ReviewRow>
          <ReviewRow label="Registered shops">{fmt(used)} (active and inactive)</ReviewRow>
          <ReviewRow label="Available after saving">
            {newMax === null ? "Unlimited" : fmt(slotsLeft(newMax, used)!)}
          </ReviewRow>
        </dl>
        {reducesBelowUsage && (
          <ImpactNote tone="warn">
            This is below current usage. Existing shops remain intact; only new shop registration will be blocked.
          </ImpactNote>
        )}
        {stale && (
          <Button type="button" variant="outline" className="h-9" onClick={reload}>
            Load latest values
          </Button>
        )}
      </ConfirmDialog>
    </DashboardCard>
  );
}

function Stat({
  label,
  testId,
  muted,
  children,
}: {
  label: string;
  testId: string;
  muted?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="rounded-xl bg-slate-50 p-3 ring-1 ring-inset ring-slate-100">
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd
        data-testid={testId}
        className={cn("mt-1 text-base font-semibold tabular-nums", muted ? "text-slate-500" : "text-slate-900")}
      >
        {children}
      </dd>
    </div>
  );
}

function ModeOption({
  value,
  checked,
  onChange,
  title,
  hint,
  disabled,
}: {
  value: AllowanceMode;
  checked: boolean;
  onChange: (value: AllowanceMode) => void;
  title: string;
  hint: string;
  disabled: boolean;
}) {
  const id = `shop-allowance-mode-${value}`;
  return (
    <label
      htmlFor={id}
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-blue-600/30",
        checked ? "border-blue-600 bg-blue-50/60" : "border-slate-200 bg-white hover:border-slate-300",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      <input
        id={id}
        type="radio"
        name="allowance_mode"
        value={value}
        checked={checked}
        disabled={disabled}
        onChange={() => onChange(value)}
        className="mt-0.5 size-4 accent-[#1b4fc4]"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-hint`}
      />
      <span>
        <span id={`${id}-title`} className="block text-sm font-medium text-slate-900">
          {title}
        </span>
        <span id={`${id}-hint`} className="block text-xs text-slate-500">
          {hint}
        </span>
      </span>
    </label>
  );
}

function ImpactNote({ tone, children }: { tone: "warn"; children: ReactNode }) {
  return (
    <div
      role="note"
      className={cn(
        "flex items-start gap-2.5 rounded-lg border p-3 text-sm",
        tone === "warn" && "border-amber-200 bg-amber-50 text-amber-900",
      )}
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <p>{children}</p>
    </div>
  );
}

function ReviewRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 px-3 py-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right font-medium text-slate-900">{children}</dd>
    </div>
  );
}

/** Shown in place of the card when the allowance could not be loaded. */
export function ShopAllowanceUnavailable() {
  return (
    <DashboardCard title="Shop Allowance" icon={Store}>
      <ErrorAlert>The shop allowance could not be loaded. Refresh the page to try again.</ErrorAlert>
    </DashboardCard>
  );
}
