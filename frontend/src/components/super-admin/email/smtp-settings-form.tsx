"use client";

import { useRef, useState } from "react";
import { AlertCircle, Eye, EyeOff, KeyRound, Loader2, Server, ShieldCheck } from "lucide-react";

import { DashboardCard } from "@/components/super-admin/dashboard-card";
import {
  DEFAULT_PORT,
  GMAIL_HOST,
  type SmtpFormErrors,
  type SmtpFormValues,
  toRequest,
  validateSmtpForm,
} from "@/components/super-admin/email/email-validation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { EmailSettings, EncryptionMode } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const PRIMARY =
  "h-10 gap-2 bg-gradient-to-r from-[#0b1a3d] to-[#1b4fc4] text-white hover:from-[#0f2352] hover:to-[#2260e0] focus-visible:ring-3 focus-visible:ring-blue-600/40 focus-visible:ring-offset-2";
const INPUT =
  "h-10 bg-white focus-visible:border-blue-600 focus-visible:ring-blue-600/20 aria-invalid:focus-visible:border-destructive";

type Props = {
  data: EmailSettings;
  values: SmtpFormValues;
  onChange: (values: SmtpFormValues) => void;
  onSaved: (data: EmailSettings) => void;
  onStale: () => void;
};

export function SmtpSettingsForm({ data, values, onChange, onSaved, onStale }: Props) {
  const settings = data.settings;
  const [errors, setErrors] = useState<SmtpFormErrors>({});
  const [serverError, setServerError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const inFlight = useRef(false);

  const passwordStored = Boolean(settings?.password_set && settings.password_readable);
  const passwordUnreadable = Boolean(settings?.password_set && !settings.password_readable);

  function set<K extends keyof SmtpFormValues>(key: K, value: SmtpFormValues[K]) {
    setSaved(false);
    setErrors((e) => ({ ...e, [key]: undefined }));
    onChange({ ...values, [key]: value });
  }

  function setMode(mode: EncryptionMode) {
    setSaved(false);
    // Switch to the matching standard port when the current one is the other mode's default.
    const port =
      values.smtp_port === String(DEFAULT_PORT[mode === "ssl" ? "starttls" : "ssl"])
        ? String(DEFAULT_PORT[mode])
        : values.smtp_port;
    setErrors((e) => ({ ...e, smtp_port: undefined }));
    onChange({ ...values, encryption_mode: mode, smtp_port: port });
  }

  function applyGmailPreset() {
    setSaved(false);
    setErrors({});
    onChange({
      ...values,
      smtp_host: GMAIL_HOST,
      smtp_port: "587",
      encryption_mode: "starttls",
    });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (inFlight.current) return;
    const problems = validateSmtpForm(values, {
      allowedPorts: data.allowed_ports,
      passwordStored,
    });
    setErrors(problems);
    setServerError(null);
    if (Object.values(problems).some(Boolean)) return;

    inFlight.current = true;
    setSaving(true);
    try {
      const result = await apiFetch<EmailSettings>("/super-admin/email-settings", {
        method: "PUT",
        body: JSON.stringify(toRequest(values, settings?.version ?? null)),
      });
      setShowPassword(false);
      setSaved(true);
      onSaved(result);
    } catch (error) {
      setServerError(
        error instanceof ApiError
          ? error
          : new ApiError(0, "unknown", "The settings could not be saved. Please try again."),
      );
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  const stale = serverError?.code === "stale_email_settings";
  const field = (key: keyof SmtpFormValues) => ({
    id: `smtp-${key}`,
    "aria-invalid": errors[key] ? true : undefined,
    "aria-describedby": errors[key] ? `smtp-${key}-error` : undefined,
  });

  return (
    <DashboardCard
      title="SMTP Settings"
      icon={Server}
      action={
        <Button type="button" variant="outline" className="h-8 text-xs" onClick={applyGmailPreset}>
          Use Gmail settings
        </Button>
      }
    >
      <form noValidate onSubmit={submit} className="space-y-5" aria-label="SMTP settings">
        {!data.encryption_ready && (
          <Notice tone="error" title="Encryption key not set up">
            The server has no encryption key for SMTP passwords, so a password cannot be saved.
            Ask the system operator to set <code>EMAIL_SETTINGS_ENCRYPTION_KEY</code> and restart
            the backend.
          </Notice>
        )}
        {passwordUnreadable && (
          <Notice tone="warning" title="Re-enter the SMTP password">
            The saved password can no longer be decrypted because the server&apos;s encryption key
            changed. Enter the password again and save.
          </Notice>
        )}
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
                  Reload settings
                </Button>
              )}
            </div>
          </div>
        )}
        {saved && !serverError && (
          <p
            role="status"
            className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900"
          >
            <ShieldCheck className="size-4 shrink-0" aria-hidden="true" />
            Settings saved. The password is stored encrypted.
          </p>
        )}

        <fieldset className="grid gap-4 sm:grid-cols-6">
          <legend className="sr-only">Server</legend>
          <Field className="sm:col-span-4" label="SMTP host" error={errors.smtp_host} id="smtp-smtp_host">
            <Input
              {...field("smtp_host")}
              className={INPUT}
              value={values.smtp_host}
              onChange={(e) => set("smtp_host", e.target.value)}
              placeholder="smtp.gmail.com"
              autoComplete="off"
              spellCheck={false}
              inputMode="url"
              maxLength={253}
            />
          </Field>
          <Field className="sm:col-span-2" label="Port" error={errors.smtp_port} id="smtp-smtp_port">
            <Input
              {...field("smtp_port")}
              className={INPUT}
              value={values.smtp_port}
              onChange={(e) => set("smtp_port", e.target.value.replace(/\D/g, "").slice(0, 5))}
              inputMode="numeric"
              autoComplete="off"
              placeholder="587"
            />
          </Field>

          <div className="space-y-2 sm:col-span-6">
            <span id="smtp-mode-label" className="text-sm font-medium text-slate-700">
              Encryption
            </span>
            <div
              role="radiogroup"
              aria-labelledby="smtp-mode-label"
              className="grid gap-2 sm:grid-cols-2"
            >
              {(
                [
                  ["starttls", "STARTTLS", "Port 587 · recommended for Gmail"],
                  ["ssl", "SSL/TLS", "Port 465 · encrypted from the start"],
                ] as const
              ).map(([mode, label, hint]) => (
                <label
                  key={mode}
                  className={cn(
                    "flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm transition-colors has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-blue-600/30",
                    values.encryption_mode === mode
                      ? "border-blue-600 bg-blue-50/60"
                      : "border-slate-200 hover:bg-slate-50",
                  )}
                >
                  <input
                    type="radio"
                    name="encryption_mode"
                    value={mode}
                    checked={values.encryption_mode === mode}
                    onChange={() => setMode(mode)}
                    className="mt-0.5 size-4 accent-blue-700"
                  />
                  <span>
                    <span className="block font-medium text-slate-900">{label}</span>
                    <span className="block text-xs text-slate-500">{hint}</span>
                  </span>
                </label>
              ))}
            </div>
            <p className="text-xs text-slate-500">
              Unencrypted connections are not offered; certificates are always verified.
            </p>
          </div>
        </fieldset>

        <fieldset className="grid gap-4 sm:grid-cols-2">
          <legend className="mb-1 text-sm font-semibold text-slate-900">Sign-in</legend>
          <Field label="SMTP username" error={errors.smtp_username} id="smtp-smtp_username">
            <Input
              {...field("smtp_username")}
              className={INPUT}
              value={values.smtp_username}
              onChange={(e) => set("smtp_username", e.target.value)}
              placeholder="your.account@gmail.com"
              autoComplete="off"
              spellCheck={false}
              maxLength={320}
            />
          </Field>
          <Field
            label={
              <span className="flex flex-wrap items-center gap-2">
                SMTP password
                {passwordStored && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
                    <KeyRound className="size-3" aria-hidden="true" />
                    Password configured
                  </span>
                )}
              </span>
            }
            error={errors.smtp_password}
            id="smtp-smtp_password"
            hint={
              passwordStored
                ? "Leave blank to keep the saved password."
                : "For Gmail, use a 16-character App Password."
            }
          >
            <div className="relative">
              <Input
                {...field("smtp_password")}
                aria-describedby={
                  errors.smtp_password ? "smtp-smtp_password-error" : "smtp-smtp_password-hint"
                }
                className={cn(INPUT, "pr-11")}
                type={showPassword ? "text" : "password"}
                value={values.smtp_password}
                onChange={(e) => set("smtp_password", e.target.value)}
                placeholder={passwordStored ? "••••••••••••" : "App Password"}
                autoComplete="new-password"
                spellCheck={false}
                maxLength={256}
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                aria-pressed={showPassword}
                aria-controls="smtp-smtp_password"
                className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-lg text-slate-500 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/40"
              >
                {showPassword ? (
                  <EyeOff className="size-4" aria-hidden="true" />
                ) : (
                  <Eye className="size-4" aria-hidden="true" />
                )}
              </button>
            </div>
          </Field>
        </fieldset>

        <fieldset className="grid gap-4 sm:grid-cols-2">
          <legend className="mb-1 text-sm font-semibold text-slate-900">Sender</legend>
          <Field
            label="Sender email"
            error={errors.sender_email}
            id="smtp-sender_email"
            hint="For Gmail, use the same address as the username."
          >
            <Input
              {...field("sender_email")}
              aria-describedby={
                errors.sender_email ? "smtp-sender_email-error" : "smtp-sender_email-hint"
              }
              className={INPUT}
              type="email"
              value={values.sender_email}
              onChange={(e) => set("sender_email", e.target.value)}
              placeholder="your.account@gmail.com"
              autoComplete="off"
              spellCheck={false}
              maxLength={320}
            />
          </Field>
          <Field label="Sender name" error={errors.sender_name} id="smtp-sender_name">
            <Input
              {...field("sender_name")}
              className={INPUT}
              value={values.sender_name}
              onChange={(e) => set("sender_name", e.target.value)}
              placeholder="Cheena FBR POS"
              autoComplete="off"
              maxLength={100}
            />
          </Field>
        </fieldset>

        <div className="flex flex-col-reverse gap-3 border-t border-slate-100 pt-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-slate-500">
            Passwords are encrypted before they are stored and are never shown again.
          </p>
          <Button type="submit" disabled={saving} className={PRIMARY}>
            {saving && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
            {saving ? "Saving…" : settings ? "Save changes" : "Save settings"}
          </Button>
        </div>
      </form>
    </DashboardCard>
  );
}

function Field({
  id,
  label,
  error,
  hint,
  className,
  children,
}: {
  id: string;
  label: React.ReactNode;
  error?: string;
  hint?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("min-w-0 space-y-2", className)}>
      <Label htmlFor={id} className="text-sm font-medium text-slate-700">
        {label}
      </Label>
      {children}
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-xs text-slate-500">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function Notice({
  tone,
  title,
  children,
}: {
  tone: "error" | "warning" | "info";
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "note"}
      className={cn(
        "rounded-lg border p-3 text-sm",
        tone === "error" && "border-red-200 bg-red-50 text-red-900",
        tone === "warning" && "border-amber-200 bg-amber-50 text-amber-900",
        tone === "info" && "border-blue-200 bg-blue-50/60 text-blue-950",
      )}
    >
      <p className="font-semibold">{title}</p>
      <div className="mt-1 leading-relaxed">{children}</div>
    </div>
  );
}
