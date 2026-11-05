"use client";

import { useRef, useState } from "react";
import { AlertCircle, ArrowRight, CalendarCheck2, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { DatePicker } from "@/components/ui/date-picker";
import { Label } from "@/components/ui/label";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { RenewResponse, RenewalRules, Subscription } from "@/lib/api/types";
import { daysBetween, formatDate, isIsoDate, pluralDays } from "@/lib/format";
import { uuidv4 } from "@/lib/uuid";

const NOTE_MAX = 500;

export function validateNewExpiry(value: string, rules: RenewalRules): string | null {
  if (!value) return "Choose a new expiry date.";
  if (!isIsoDate(value)) return "Enter a valid date.";
  if (rules.min_new_expiry_date && value < rules.min_new_expiry_date) {
    return `The new expiry date must be on or after ${formatDate(rules.min_new_expiry_date)}.`;
  }
  if (rules.max_new_expiry_date && value > rules.max_new_expiry_date) {
    return `The new expiry date must be on or before ${formatDate(rules.max_new_expiry_date)}.`;
  }
  return null;
}

type Props = {
  companyName: string | null;
  subscription: Subscription;
  rules: RenewalRules;
  today: string;
  onRenewed: (result: RenewResponse) => void;
  onCancel: () => void;
  onStale: () => void;
};

const INPUT_FOCUS =
  "focus-visible:border-blue-600 focus-visible:ring-blue-600/20 aria-invalid:focus-visible:border-destructive";

/**
 * Two steps: choose the date, then review the impact and confirm.
 * Mounted fresh every time the dialog opens, so each attempt gets its own
 * idempotency key; retrying after a network error reuses it safely.
 */
export function RenewForm({ companyName, subscription, rules, today, onRenewed, onCancel, onStale }: Props) {
  const [step, setStep] = useState<"form" | "review">("form");
  const [newExpiry, setNewExpiry] = useState(rules.min_new_expiry_date ?? "");
  const [note, setNote] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [serverError, setServerError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [idempotencyKey] = useState(uuidv4);
  const inFlight = useRef(false);

  const currentExpiry = subscription.expiry_date!;
  const startDate = subscription.start_date!;
  const valid = validateNewExpiry(newExpiry, rules) === null;

  function review() {
    const problem = validateNewExpiry(newExpiry, rules);
    if (!problem && note.trim().length > NOTE_MAX) {
      setFieldError(`The note must be at most ${NOTE_MAX} characters.`);
      return;
    }
    setFieldError(problem);
    if (!problem) {
      setServerError(null);
      setStep("review");
    }
  }

  async function confirm() {
    if (inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    setServerError(null);
    try {
      const result = await apiFetch<RenewResponse>("/super-admin/subscription/renew", {
        method: "POST",
        body: JSON.stringify({
          new_expiry_date: newExpiry,
          expected_expiry_date: currentExpiry,
          idempotency_key: idempotencyKey,
          renewal_note: note.trim() || null,
        }),
      });
      onRenewed(result);
    } catch (error) {
      const apiError =
        error instanceof ApiError
          ? error
          : new ApiError(0, "unknown", "The renewal could not be saved. Please try again.");
      setServerError(apiError);
      if (apiError.status === 422) setStep("form");
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }

  const stale = serverError?.status === 409 && serverError.code === "stale_subscription";

  return (
    <div className="space-y-5">
      {serverError && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div className="space-y-2">
            <p>{serverError.message}</p>
            {stale && (
              <Button type="button" variant="outline" className="h-8 bg-white" onClick={onStale}>
                Reload subscription
              </Button>
            )}
          </div>
        </div>
      )}

      <dl className="grid gap-3 rounded-xl bg-slate-50 p-4 text-sm ring-1 ring-inset ring-slate-100 sm:grid-cols-3">
        {[
          ["Company", companyName ?? "—"],
          ["Current start date", formatDate(startDate)],
          ["Current expiry date", formatDate(currentExpiry)],
        ].map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs text-slate-500">{label}</dt>
            <dd className="mt-0.5 font-medium text-slate-900">{value}</dd>
          </div>
        ))}
      </dl>

      {step === "form" ? (
        <form
          noValidate
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            review();
          }}
        >
          <div className="space-y-2">
            <Label
              id="new-expiry-label"
              htmlFor="new-expiry"
              className="text-sm font-medium text-slate-700"
            >
              New expiry date
            </Label>
            <DatePicker
              id="new-expiry"
              labelId="new-expiry-label"
              value={newExpiry}
              min={rules.min_new_expiry_date}
              max={rules.max_new_expiry_date}
              onChange={(iso) => {
                setNewExpiry(iso);
                setFieldError(null);
              }}
              invalid={Boolean(fieldError)}
              describedBy={fieldError ? "new-expiry-error" : "new-expiry-hint"}
            />
            {fieldError ? (
              <p id="new-expiry-error" role="alert" className="text-sm text-destructive">
                {fieldError}
              </p>
            ) : (
              <p id="new-expiry-hint" className="text-xs text-slate-500">
                Must be after {formatDate(currentExpiry)}
                {today >= currentExpiry ? ` and after today (${formatDate(today)})` : ""}. The
                start date does not change.
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="renewal-note" className="text-sm font-medium text-slate-700">
              Renewal note <span className="font-normal text-slate-500">(optional)</span>
            </Label>
            <textarea
              id="renewal-note"
              rows={3}
              maxLength={NOTE_MAX}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              aria-describedby="renewal-note-count"
              placeholder="For example: annual contract renewal"
              className={`w-full resize-y rounded-lg border border-input bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-xs outline-none placeholder:text-muted-foreground focus-visible:ring-3 ${INPUT_FOCUS}`}
            />
            <p id="renewal-note-count" className="text-right text-xs text-slate-500">
              {note.length}/{NOTE_MAX}
            </p>
          </div>

          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" className="h-10" onClick={onCancel}>
              Cancel
            </Button>
            <Button
              type="submit"
              className="h-10 gap-2 bg-gradient-to-r from-[#0b1a3d] to-[#1b4fc4] text-white hover:from-[#0f2352] hover:to-[#2260e0] focus-visible:ring-3 focus-visible:ring-blue-600/40 focus-visible:ring-offset-2"
            >
              Review renewal
              <ArrowRight className="size-4" aria-hidden="true" />
            </Button>
          </div>
        </form>
      ) : (
        <div className="space-y-4">
          <div className="rounded-xl border border-blue-200 bg-blue-50/60 p-4">
            <p className="flex items-center gap-2 text-sm font-semibold text-blue-950">
              <CalendarCheck2 className="size-4" aria-hidden="true" />
              Review the change
            </p>
            {valid && (
              <dl className="mt-3 space-y-2 text-sm">
                <ImpactRow label="Expiry date" value={`${formatDate(currentExpiry)} → ${formatDate(newExpiry)}`} />
                <ImpactRow label="Extension" value={`+${pluralDays(daysBetween(currentExpiry, newExpiry))}`} />
                <ImpactRow label="Start date" value={`${formatDate(startDate)} (unchanged)`} />
                <ImpactRow label="New total duration" value={pluralDays(daysBetween(startDate, newExpiry) + 1)} />
                <ImpactRow label="Remaining after renewal" value={pluralDays(Math.max(0, daysBetween(today, newExpiry)))} />
                {note.trim() && <ImpactRow label="Note" value={note.trim()} />}
              </dl>
            )}
            <p className="mt-3 text-xs text-blue-900/80">
              The renewal is recorded permanently in the renewal history and cannot be edited or
              deleted.
            </p>
          </div>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              className="h-10"
              disabled={submitting}
              onClick={() => setStep("form")}
            >
              Back
            </Button>
            <Button
              type="button"
              disabled={submitting}
              onClick={confirm}
              className="h-10 gap-2 bg-gradient-to-r from-[#0b1a3d] to-[#1b4fc4] text-white hover:from-[#0f2352] hover:to-[#2260e0] focus-visible:ring-3 focus-visible:ring-blue-600/40 focus-visible:ring-offset-2"
            >
              {submitting && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
              {submitting ? "Renewing…" : "Confirm renewal"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function ImpactRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-wrap justify-between gap-x-4 gap-y-0.5">
      <dt className="text-slate-600">{label}</dt>
      <dd className="min-w-0 break-words text-right font-medium text-slate-900">{value}</dd>
    </div>
  );
}
