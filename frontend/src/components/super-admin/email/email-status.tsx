import { CheckCircle2, CircleDashed, History, MailX, type LucideIcon } from "lucide-react";

import { DashboardCard, DetailList } from "@/components/super-admin/dashboard-card";
import type { EmailSettings, EmailSettingsStatus } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export const EMAIL_STATUS_META: Record<
  EmailSettingsStatus,
  { label: string; icon: LucideIcon; className: string; description: string }
> = {
  not_configured: {
    label: "Not Configured",
    icon: CircleDashed,
    className: "bg-slate-100 text-slate-700 ring-slate-500/20",
    description: "No SMTP server has been saved. The application cannot send email yet.",
  },
  configured: {
    label: "Configured",
    icon: CheckCircle2,
    className: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
    description: "SMTP settings are saved and email sending is enabled.",
  },
  disabled: {
    label: "Email Sending Disabled",
    icon: MailX,
    className: "bg-amber-50 text-amber-800 ring-amber-600/25",
    description: "SMTP settings are saved, but the application will not send email.",
  },
};

/** Colour is never the only signal: every status has an icon and a text label. */
export function EmailStatusBadge({
  status,
  className,
}: {
  status: EmailSettingsStatus;
  className?: string;
}) {
  const { label, icon: Icon, className: tone } = EMAIL_STATUS_META[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset",
        tone,
        className,
      )}
    >
      <Icon className="size-3.5" aria-hidden="true" />
      {label}
    </span>
  );
}

const MODE_LABEL = { starttls: "STARTTLS", ssl: "SSL/TLS" } as const;

export function StatusOverview({ data }: { data: EmailSettings }) {
  const meta = EMAIL_STATUS_META[data.status];
  const s = data.settings;
  return (
    <section
      aria-labelledby="email-status-heading"
      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h2 id="email-status-heading" className="text-[15px] font-semibold text-slate-900">
            Email status
          </h2>
          <p className="text-sm text-slate-600">{meta.description}</p>
        </div>
        <EmailStatusBadge status={data.status} />
      </div>
      {s && (
        <dl className="mt-4 grid gap-3 rounded-xl bg-slate-50 p-4 text-sm ring-1 ring-inset ring-slate-100 sm:grid-cols-2 xl:grid-cols-4">
          {[
            ["SMTP server", `${s.smtp_host}:${s.smtp_port}`],
            ["Encryption", MODE_LABEL[s.encryption_mode]],
            ["Sender", s.sender_email],
            ["Last updated", formatDateTime(s.updated_at)],
          ].map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className="mt-0.5 break-words font-medium text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

const KIND_LABEL = { connection: "Connection test", email: "Test email" } as const;

export function TestHistoryCard({ data }: { data: EmailSettings }) {
  const h = data.history;
  return (
    <DashboardCard title="Test Results" icon={History}>
      {!h || !h.last_test_at ? (
        <p className="text-sm text-slate-600">
          {data.settings
            ? "No test has been run with the current settings yet."
            : "Save the SMTP settings, then run a connection test."}
        </p>
      ) : (
        <DetailList
          items={[
            {
              label: "Latest test",
              value: (
                <span
                  className={cn(
                    "inline-flex items-center gap-1",
                    h.last_test_status === "success" ? "text-emerald-700" : "text-red-700",
                  )}
                >
                  {h.last_test_status === "success" ? "Passed" : "Failed"}
                  {h.last_test_kind && ` · ${KIND_LABEL[h.last_test_kind]}`}
                </span>
              ),
            },
            { label: "Tested at", value: formatDateTime(h.last_test_at) },
            { label: "Last successful test", value: formatDateTime(h.last_success_at) },
            { label: "Last failed test", value: formatDateTime(h.last_failure_at) },
            ...(h.last_failure_message && h.last_failure_at
              ? [{ label: "Last failure reason", value: h.last_failure_message }]
              : []),
          ]}
        />
      )}
      <p className="mt-4 text-xs text-slate-500">Times are shown in Pakistan time (PKT).</p>
    </DashboardCard>
  );
}
