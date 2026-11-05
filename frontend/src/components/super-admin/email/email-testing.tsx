"use client";

import { useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, PlugZap, Send, TestTube2 } from "lucide-react";

import { isValidEmail } from "@/components/super-admin/email/email-validation";
import { DashboardCard } from "@/components/super-admin/dashboard-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { EmailCheckResult, EmailSettings } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { uuidv4 } from "@/lib/uuid";
import { cn } from "@/lib/utils";

/** SMTP tests can take several network round trips; allow more than the default timeout. */
export const SMTP_TEST_TIMEOUT_MS = 90_000;

type Result =
  | { kind: "result"; result: EmailCheckResult }
  | { kind: "error"; error: ApiError; action: "connection" | "email" };

type Props = {
  data: EmailSettings;
  defaultRecipient: string;
  unsavedChanges: boolean;
  onResult: (data: EmailSettings) => void;
};

export function EmailTesting({ data, defaultRecipient, unsavedChanges, onResult }: Props) {
  const settings = data.settings;
  const [recipient, setRecipient] = useState(defaultRecipient);
  const [recipientError, setRecipientError] = useState<string | null>(null);
  const [running, setRunning] = useState<"connection" | "email" | null>(null);
  const [outcome, setOutcome] = useState<Result | null>(null);
  const inFlight = useRef(false);
  // Reused only when a send ended without an answer (network error), so a
  // retry of the same attempt can never deliver the message twice.
  const pendingKey = useRef<{ key: string; recipient: string } | null>(null);

  const enabled = Boolean(settings?.is_enabled);
  const blocked = !settings || unsavedChanges || (settings.password_set && !settings.password_readable);

  async function run(action: "connection" | "email") {
    if (inFlight.current || blocked) return;
    let body: string | undefined;
    if (action === "email") {
      const to = recipient.trim();
      if (!isValidEmail(to)) {
        setRecipientError("Enter a valid recipient email address.");
        return;
      }
      if (pendingKey.current?.recipient !== to) pendingKey.current = { key: uuidv4(), recipient: to };
      body = JSON.stringify({ recipient_email: to, idempotency_key: pendingKey.current.key });
    }
    inFlight.current = true;
    setRunning(action);
    setOutcome(null);
    try {
      const result = await apiFetch<EmailCheckResult>(
        `/super-admin/email-settings/${action === "email" ? "test-email" : "test-connection"}`,
        { method: "POST", body: body ?? "{}", signal: AbortSignal.timeout(SMTP_TEST_TIMEOUT_MS) },
      );
      if (action === "email") pendingKey.current = null;
      setOutcome({ kind: "result", result });
      onResult(result.email_settings);
    } catch (e) {
      const error =
        e instanceof ApiError ? e : new ApiError(0, "unknown", "The test could not be run.");
      if (action === "email" && error.status !== 0) pendingKey.current = null;
      setOutcome({ kind: "error", error, action });
    } finally {
      inFlight.current = false;
      setRunning(null);
    }
  }

  return (
    <DashboardCard title="Test Email Settings" icon={TestTube2}>
      <div className="space-y-5">
        {unsavedChanges && settings && (
          <p role="note" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            You have unsaved changes. Tests use the saved settings, so save first.
          </p>
        )}

        <div className="space-y-2">
          <p className="text-sm text-slate-600">
            Connects to the SMTP server, secures the connection and signs in.{" "}
            <strong className="font-medium text-slate-800">No email is sent.</strong>
          </p>
          <Button
            type="button"
            variant="outline"
            disabled={blocked || running !== null}
            onClick={() => void run("connection")}
            className="h-10 w-full gap-2 sm:w-auto"
          >
            {running === "connection" ? (
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            ) : (
              <PlugZap className="size-4" aria-hidden="true" />
            )}
            {running === "connection" ? "Testing connection…" : "Test Connection"}
          </Button>
        </div>

        <div className="space-y-2 border-t border-slate-100 pt-4">
          <Label htmlFor="test-recipient" className="text-sm font-medium text-slate-700">
            Send a test email to
          </Label>
          <Input
            id="test-recipient"
            type="email"
            value={recipient}
            onChange={(e) => {
              setRecipient(e.target.value);
              setRecipientError(null);
            }}
            aria-invalid={recipientError ? true : undefined}
            aria-describedby={recipientError ? "test-recipient-error" : "test-recipient-hint"}
            autoComplete="email"
            spellCheck={false}
            maxLength={320}
            className="h-10 bg-white focus-visible:border-blue-600 focus-visible:ring-blue-600/20"
          />
          {recipientError ? (
            <p id="test-recipient-error" role="alert" className="text-sm text-destructive">
              {recipientError}
            </p>
          ) : (
            <p id="test-recipient-hint" className="text-xs text-slate-500">
              {enabled
                ? "Sends one short, fixed test message. Limited to a few per 15 minutes."
                : "Enable email sending to send a test email."}
            </p>
          )}
          <Button
            type="button"
            disabled={blocked || !enabled || running !== null}
            onClick={() => void run("email")}
            className="h-10 w-full gap-2 bg-gradient-to-r from-[#0b1a3d] to-[#1b4fc4] text-white hover:from-[#0f2352] hover:to-[#2260e0] focus-visible:ring-3 focus-visible:ring-blue-600/40 focus-visible:ring-offset-2 sm:w-auto"
          >
            {running === "email" ? (
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            ) : (
              <Send className="size-4" aria-hidden="true" />
            )}
            {running === "email" ? "Sending…" : "Send Test Email"}
          </Button>
        </div>

        <div aria-live="polite">{outcome && <Outcome outcome={outcome} />}</div>
      </div>
    </DashboardCard>
  );
}

function Outcome({ outcome }: { outcome: Result }) {
  if (outcome.kind === "error") {
    const network = outcome.error.status === 0 && outcome.action === "email";
    return (
      <div
        role="alert"
        className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
      >
        <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <div className="space-y-1">
          <p>{outcome.error.message}</p>
          {network && (
            <p className="text-xs">
              The result is unknown. Retrying is safe: the same request will not send a second
              email.
            </p>
          )}
        </div>
      </div>
    );
  }
  const { result } = outcome;
  return (
    <div
      role="status"
      className={cn(
        "flex items-start gap-3 rounded-lg border p-3 text-sm",
        result.ok
          ? "border-emerald-200 bg-emerald-50 text-emerald-900"
          : "border-red-200 bg-red-50 text-red-900",
      )}
    >
      {result.ok ? (
        <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      ) : (
        <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      )}
      <div className="space-y-1">
        <p className="font-medium">
          {result.kind === "connection"
            ? result.ok
              ? "Connection test passed"
              : "Connection test failed"
            : result.ok
              ? "Test email accepted"
              : "Test email failed"}
        </p>
        <p>{result.message}</p>
        <p className="text-xs opacity-80">
          {formatDateTime(result.tested_at)} PKT
          {result.replayed && " · result of the earlier identical request (not sent again)"}
        </p>
      </div>
    </div>
  );
}
