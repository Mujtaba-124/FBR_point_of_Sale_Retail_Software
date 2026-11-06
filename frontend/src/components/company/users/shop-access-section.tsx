"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
import { AlertTriangle, Loader2, ShieldCheck, Store } from "lucide-react";

import { ErrorAlert, PRIMARY_BUTTON, SuccessNote } from "@/components/company/ui-kit";
import { ShopAccessField } from "@/components/company/users/shop-access-field";
import { describeChange, MODE_COPY, shopAccessError } from "@/components/company/users/shop-access-rules";
import { Button } from "@/components/ui/button";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { CompanyUser, ShopAccessDetail, ShopAccessMode, ShopAccessUpdate } from "@/lib/api/types";

type Load = { status: "loading" } | { status: "ready"; detail: ShopAccessDetail } | { status: "error"; message: string };

/**
 * Edit User: the user's Shop Access, saved on its own (one atomic, versioned
 * request) with a review step for any expansion or revocation.
 */
export function ShopAccessSection({ user, onSaved }: { user: CompanyUser; onSaved: () => void }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [tick, setTick] = useState(0);
  const [mode, setMode] = useState<ShopAccessMode>("none");
  const [ids, setIds] = useState<Set<string>>(new Set());
  const [touched, setTouched] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const inFlight = useRef(false);

  function adopt(detail: ShopAccessDetail) {
    setLoad({ status: "ready", detail });
    if (detail.mode !== "company") setMode(detail.mode);
    setIds(new Set(detail.shops.map((s) => s.id)));
    setTouched(false);
    setReviewing(false);
  }

  useEffect(() => {
    let alive = true;
    apiFetch<ShopAccessDetail>(`/company/users/${user.id}/shop-access`)
      .then((d) => alive && adopt(d))
      .catch((e: unknown) => alive && setLoad({ status: "error", message: e instanceof ApiError ? e.message : "Shop access could not be loaded." }));
    return () => {
      alive = false;
    };
  }, [user.id, tick]);

  function reload() {
    setServerError(null);
    setLoad({ status: "loading" });
    setTick((t) => t + 1);
  }

  if (load.status === "loading") {
    return (
      <Section>
        <p className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="size-4 animate-spin" aria-hidden="true" /> Loading shop access…
        </p>
      </Section>
    );
  }
  if (load.status === "error") {
    return (
      <Section>
        <ErrorAlert action={<Button type="button" variant="outline" className="h-8 bg-white" onClick={reload}>Try again</Button>}>
          {load.message}
        </ErrorAlert>
      </Section>
    );
  }

  const detail = load.detail;
  if (!detail.editable || detail.mode === "company") {
    return (
      <Section>
        <p className="flex items-start gap-2 rounded-lg bg-slate-50 p-3 text-sm text-slate-600 ring-1 ring-inset ring-slate-100">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-blue-700" aria-hidden="true" />
          The Company Admin always has access to all shops. This cannot be changed.
        </p>
      </Section>
    );
  }

  const before = { mode: detail.mode, ids: new Set(detail.shops.map((s) => s.id)) };
  const after = { mode, ids };
  const change = describeChange(before, after);
  const dirty = mode !== detail.mode || change.added > 0 || change.removed > 0;
  const fieldError = touched ? shopAccessError(mode, ids) : null;
  const stale = serverError?.code === "stale_shop_access";

  async function confirm() {
    if (inFlight.current) return;
    inFlight.current = true;
    setSaving(true);
    setServerError(null);
    try {
      const result = await apiFetch<ShopAccessUpdate>(`/company/users/${user.id}/shop-access`, {
        method: "PUT",
        body: JSON.stringify({
          mode,
          shop_ids: mode === "selected" ? [...ids] : [],
          expected_version: detail.version,
        }),
      });
      adopt(result.access);
      setNotice(result.changed ? "Shop access saved." : "Nothing changed: this shop access was already saved.");
      onSaved();
    } catch (e) {
      setServerError(e instanceof ApiError ? e : new ApiError(0, "unknown", "Shop access could not be saved."));
      setReviewing(false);
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  return (
    <Section>
      <form
        noValidate
        autoComplete="off"
        aria-label="Shop access"
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          setTouched(true);
          setNotice(null);
          if (!shopAccessError(mode, ids) && dirty) setReviewing(true);
        }}
      >
        <ShopAccessField
          mode={mode}
          onModeChange={(m) => {
            setMode(m);
            setReviewing(false);
            setNotice(null);
          }}
          selected={ids}
          onSelectedChange={(next) => {
            setIds(next);
            setReviewing(false);
            setNotice(null);
          }}
          error={fieldError}
          disabled={saving}
          knownShops={detail.shops}
          hideLegend
        />

        {notice && <SuccessNote>{notice}</SuccessNote>}
        {serverError && (
          <ErrorAlert action={stale ? <Button type="button" variant="outline" className="h-8 bg-white" onClick={reload}>Load latest</Button> : undefined}>
            {serverError.message}
          </ErrorAlert>
        )}

        {reviewing ? (
          <div role="group" aria-label="Review shop access change" className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <p className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <span>
                <strong>{MODE_COPY[detail.mode].title}</strong> → <strong>{MODE_COPY[mode].title}</strong>.{" "}
                {change.expands && "This gives the user access to more shop data. "}
                {change.revokes && "This removes access immediately, including in open sessions. "}
                {mode === "selected" && `(${change.added} added, ${change.removed} removed)`}
              </span>
            </p>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button type="button" variant="outline" className="h-9 bg-white" disabled={saving} onClick={() => setReviewing(false)}>
                Back
              </Button>
              <Button type="button" className={PRIMARY_BUTTON} disabled={saving} onClick={() => void confirm()}>
                {saving && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
                {saving ? "Saving…" : "Confirm shop access"}
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex justify-end">
            <Button type="submit" variant="outline" className="h-10" disabled={saving || !dirty}>
              Save shop access
            </Button>
          </div>
        )}
      </form>
    </Section>
  );
}

function Section({ children }: { children: ReactNode }) {
  return (
    <section aria-labelledby="shop-access-heading" className="min-w-0 space-y-3 border-t border-slate-100 pt-4">
      <h3 id="shop-access-heading" className="flex items-center gap-2 text-sm font-semibold text-slate-900">
        <Store className="size-4 text-blue-700" aria-hidden="true" />
        Shop Access
      </h3>
      {children}
    </section>
  );
}
