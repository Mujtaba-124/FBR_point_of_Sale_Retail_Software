"use client";

import { useRef, useState } from "react";
import { AlertCircle, Power } from "lucide-react";

import { DashboardCard } from "@/components/super-admin/dashboard-card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { EmailSettings } from "@/lib/api/types";

type Props = {
  data: EmailSettings;
  onChanged: (data: EmailSettings) => void;
  onStale: () => void;
};

export function SendingToggle({ data, onChanged, onStale }: Props) {
  const settings = data.settings;
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const enabled = Boolean(settings?.is_enabled);

  async function toggle(next: boolean) {
    if (!settings || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      onChanged(
        await apiFetch<EmailSettings>("/super-admin/email-settings/sending", {
          method: "PUT",
          body: JSON.stringify({ enabled: next, expected_version: settings.version }),
        }),
      );
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e
          : new ApiError(0, "unknown", "The change could not be saved. Please try again."),
      );
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <DashboardCard title="Email Sending" icon={Power}>
      <div className="space-y-3">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p id="sending-label" className="text-sm font-medium text-slate-900">
              {enabled ? "Email sending is enabled" : "Email sending is disabled"}
            </p>
            <p id="sending-hint" className="mt-0.5 text-sm text-slate-600">
              {settings
                ? enabled
                  ? "The application may send email using these settings."
                  : "No email is sent while this is off. Turn it on to send a test email."
                : "Save the SMTP settings before enabling email sending."}
            </p>
          </div>
          <Switch
            checked={enabled}
            disabled={!settings || busy}
            onCheckedChange={(next) => void toggle(next)}
            aria-labelledby="sending-label"
            aria-describedby="sending-hint"
            className="mt-0.5 data-checked:bg-blue-700"
          />
        </div>
        {error && (
          <div
            role="alert"
            className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
          >
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <div className="space-y-2">
              <p>{error.message}</p>
              {error.code === "stale_email_settings" && (
                <Button type="button" variant="outline" className="h-8 bg-white" onClick={onStale}>
                  Reload settings
                </Button>
              )}
            </div>
          </div>
        )}
      </div>
    </DashboardCard>
  );
}
