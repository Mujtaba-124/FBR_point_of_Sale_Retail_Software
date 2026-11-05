"use client";

import { useRef, useState } from "react";
import { AlertCircle, BellRing, CheckCircle2, Loader2 } from "lucide-react";

import { DashboardCard, DetailList } from "@/components/super-admin/dashboard-card";
import { Notice } from "@/components/super-admin/email/smtp-settings-form";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { ReminderOverview } from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export const RUN_RESULT_LABELS: Record<string, string> = {
  queued: "Reminders queued for sending",
  already_queued: "Today's reminders were already queued",
  no_reminder_due: "No reminder due today",
  waiting_for_send_time: "Waiting for today's send time",
  reminders_disabled: "Skipped: reminders are disabled",
  email_sending_disabled: "Skipped: email sending is disabled",
  email_not_configured: "Skipped: SMTP settings are not configured",
  subscription_not_configured: "Skipped: no subscription is configured",
  no_recipients: "Skipped: no eligible recipients",
};

const SUPER_ADMIN_STATUS: Record<ReminderOverview["recipients"]["super_admin_status"], string> = {
  selected: "",
  disabled: "",
  none: "No active Super Admin account was found.",
  ambiguous: "More than one active Super Admin exists, so none is selected automatically.",
  invalid: "The Super Admin account has no valid email address.",
};

export type ReminderForm = {
  is_enabled: boolean;
  notify_super_admin: boolean;
  notify_company_admin: boolean;
};

export function validateReminderForm(form: ReminderForm): string | null {
  if (form.is_enabled && !form.notify_super_admin && !form.notify_company_admin) {
    return "Choose at least one recipient group before enabling reminders.";
  }
  return null;
}

type Props = {
  data: ReminderOverview;
  onSaved: (data: ReminderOverview) => void;
  onStale: () => void;
};

export function ReminderSettingsCard({ data, onSaved, onStale }: Props) {
  const saved = data.settings;
  const [form, setForm] = useState<ReminderForm>({
    is_enabled: saved.is_enabled,
    notify_super_admin: saved.notify_super_admin,
    notify_company_admin: saved.notify_company_admin,
  });
  const [problem, setProblem] = useState<string | null>(null);
  const [serverError, setServerError] = useState<ApiError | null>(null);
  const [savedOk, setSavedOk] = useState(false);
  const [saving, setSaving] = useState(false);
  const inFlight = useRef(false);
  // Adopt newer saved settings (after saving, or a refresh from the server).
  const [syncedVersion, setSyncedVersion] = useState(saved.version);
  if (saved.version !== syncedVersion) {
    setSyncedVersion(saved.version);
    setForm({
      is_enabled: saved.is_enabled,
      notify_super_admin: saved.notify_super_admin,
      notify_company_admin: saved.notify_company_admin,
    });
  }

  const dirty =
    form.is_enabled !== saved.is_enabled ||
    form.notify_super_admin !== saved.notify_super_admin ||
    form.notify_company_admin !== saved.notify_company_admin;
  const { schedule, recipients, readiness, last_run } = data;

  function change(patch: Partial<ReminderForm>) {
    setSavedOk(false);
    setProblem(null);
    setServerError(null);
    setForm((f) => ({ ...f, ...patch }));
  }

  async function save() {
    if (inFlight.current) return;
    const invalid = validateReminderForm(form);
    setProblem(invalid);
    if (invalid) return;
    inFlight.current = true;
    setSaving(true);
    setServerError(null);
    try {
      const result = await apiFetch<ReminderOverview>("/super-admin/email-settings/reminders", {
        method: "PUT",
        body: JSON.stringify({ ...form, expected_version: saved.version }),
      });
      setSavedOk(true);
      onSaved(result);
    } catch (e) {
      setServerError(
        e instanceof ApiError
          ? e
          : new ApiError(0, "unknown", "The reminder settings could not be saved."),
      );
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  const companyList = recipients.company_admin_emails;
  return (
    <DashboardCard
      title="Subscription Expiry Reminders"
      icon={BellRing}
      action={
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset",
            saved.is_enabled
              ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20"
              : "bg-slate-100 text-slate-700 ring-slate-500/20",
          )}
        >
          {saved.is_enabled ? (
            <CheckCircle2 className="size-3.5" aria-hidden="true" />
          ) : (
            <BellRing className="size-3.5" aria-hidden="true" />
          )}
          {saved.is_enabled ? "Reminders On" : "Reminders Off"}
        </span>
      }
    >
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="min-w-0 space-y-4">
          {!readiness.email_configured ? (
            <Notice tone="warning" title="SMTP settings are not configured">
              Reminders cannot be sent until the SMTP settings above are saved.
            </Notice>
          ) : !readiness.email_enabled ? (
            <Notice tone="warning" title="Email sending is disabled">
              Reminders are only sent while Email Sending is turned on.
            </Notice>
          ) : null}

          <div className="flex items-start justify-between gap-4 rounded-xl border border-slate-200 p-4">
            <div className="min-w-0">
              <p id="reminders-enabled-label" className="text-sm font-medium text-slate-900">
                Send automatic reminders
              </p>
              <p id="reminders-enabled-hint" className="mt-0.5 text-sm text-slate-600">
                Off by default. Sent by the background scheduler, never from this page.
              </p>
            </div>
            <Switch
              checked={form.is_enabled}
              disabled={saving}
              onCheckedChange={(next) => change({ is_enabled: next })}
              aria-labelledby="reminders-enabled-label"
              aria-describedby="reminders-enabled-hint"
              className="mt-0.5 data-checked:bg-blue-700"
            />
          </div>

          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-semibold text-slate-900">Recipients</legend>
            <RecipientOption
              id="notify-super-admin"
              label="Notify Super Admin"
              checked={form.notify_super_admin}
              disabled={saving}
              onChange={(v) => change({ notify_super_admin: v })}
              detail={
                recipients.super_admin_email ??
                (SUPER_ADMIN_STATUS[recipients.super_admin_status] || "No recipient")
              }
              warning={!recipients.super_admin_email}
            />
            <RecipientOption
              id="notify-company-admin"
              label="Notify Company Admin"
              checked={form.notify_company_admin}
              disabled={saving}
              onChange={(v) => change({ notify_company_admin: v })}
              detail={
                companyList.length
                  ? companyList.join(", ")
                  : "No active Company Admin with a valid email address."
              }
              warning={!companyList.length}
            />
            <p className="text-xs text-slate-500">
              Only active accounts receive reminders. Company Users never do. An address in both
              groups gets one copy.
            </p>
          </fieldset>

          {problem && (
            <p role="alert" className="text-sm text-destructive">
              {problem}
            </p>
          )}
          {serverError && (
            <div
              role="alert"
              className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
            >
              <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <div className="space-y-2">
                <p>{serverError.message}</p>
                {serverError.code === "stale_reminder_settings" && (
                  <Button type="button" variant="outline" className="h-8 bg-white" onClick={onStale}>
                    Reload settings
                  </Button>
                )}
              </div>
            </div>
          )}
          {savedOk && !dirty && (
            <p
              role="status"
              className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900"
            >
              <CheckCircle2 className="size-4 shrink-0" aria-hidden="true" />
              Reminder settings saved.
            </p>
          )}
          <div className="flex justify-end">
            <Button
              type="button"
              onClick={() => void save()}
              disabled={!dirty || saving}
              className="h-10 gap-2 bg-gradient-to-r from-[#0b1a3d] to-[#1b4fc4] text-white hover:from-[#0f2352] hover:to-[#2260e0] focus-visible:ring-3 focus-visible:ring-blue-600/40 focus-visible:ring-offset-2"
            >
              {saving && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
              {saving ? "Saving…" : "Save reminder settings"}
            </Button>
          </div>
        </div>

        <div className="min-w-0 space-y-4">
          <div className="rounded-xl bg-slate-50 p-4 ring-1 ring-inset ring-slate-100">
            <p className="text-sm font-semibold text-slate-900">Fixed schedule</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-600">
              <li>Daily from {schedule.days_before} days before expiry to 1 day before</li>
              <li>Once on the expiry date (the last valid day)</li>
              <li>Daily for {schedule.days_after} days after expiry, then reminders stop</li>
            </ul>
            <p className="mt-2 text-xs text-slate-500">
              Sent from {schedule.send_time} Pakistan time (PKT). A missed day is not sent
              later. Renewing the subscription cancels reminders for the old expiry date.
            </p>
          </div>
          <DetailList
            items={[
              { label: "Expiry date", value: formatDate(schedule.expiry_date) },
              {
                label: "Reminder period",
                value:
                  schedule.window_start && schedule.window_end
                    ? `${formatDate(schedule.window_start)} – ${formatDate(schedule.window_end)}`
                    : "—",
              },
              { label: "Today", value: schedule.today_stage ?? "No reminder day" },
              {
                label: "Next reminder day",
                value: schedule.next_reminder_date ? formatDate(schedule.next_reminder_date) : "—",
              },
              { label: "Last processed", value: formatDateTime(last_run.at) },
              {
                label: "Last result",
                value: last_run.result
                  ? (RUN_RESULT_LABELS[last_run.result] ?? last_run.result) +
                    (last_run.queued ? ` (${last_run.queued})` : "")
                  : "Not run yet",
              },
            ]}
          />
        </div>
      </div>
    </DashboardCard>
  );
}

function RecipientOption({
  id,
  label,
  checked,
  disabled,
  onChange,
  detail,
  warning,
}: {
  id: string;
  label: string;
  checked: boolean;
  disabled: boolean;
  onChange: (value: boolean) => void;
  detail: string;
  warning: boolean;
}) {
  return (
    <label
      htmlFor={id}
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm transition-colors has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-blue-600/30",
        checked ? "border-blue-600 bg-blue-50/60" : "border-slate-200 hover:bg-slate-50",
      )}
    >
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        aria-describedby={`${id}-detail`}
        className="mt-0.5 size-4 accent-blue-700"
      />
      <span className="min-w-0">
        <span className="block font-medium text-slate-900">{label}</span>
        <span
          id={`${id}-detail`}
          className={cn("block break-words text-xs", warning ? "text-amber-700" : "text-slate-500")}
        >
          {detail}
        </span>
      </span>
    </label>
  );
}
