"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Info } from "lucide-react";

import { EmailTesting } from "@/components/super-admin/email/email-testing";
import { StatusOverview, TestHistoryCard } from "@/components/super-admin/email/email-status";
import { isDirty, valuesFrom } from "@/components/super-admin/email/email-validation";
import { ReminderActivity } from "@/components/super-admin/email/reminder-activity";
import { ReminderSettingsCard } from "@/components/super-admin/email/reminder-settings";
import { SendingToggle } from "@/components/super-admin/email/sending-toggle";
import { Notice, SmtpSettingsForm } from "@/components/super-admin/email/smtp-settings-form";
import type { EmailSettings, ReminderHistoryPage, ReminderOverview } from "@/lib/api/types";

type Props = {
  initial: EmailSettings;
  defaultRecipient: string;
  reminders: ReminderOverview | null;
  reminderHistory: ReminderHistoryPage | null;
};

export function EmailSettingsView({ initial, defaultRecipient, reminders, reminderHistory }: Props) {
  const router = useRouter();
  const [data, setData] = useState(initial);
  const [values, setValues] = useState(() => valuesFrom(initial.settings));
  const [reminderData, setReminderData] = useState(reminders);
  // Server data replaced (navigation or refresh): adopt it.
  const [source, setSource] = useState(initial);
  const [reminderSource, setReminderSource] = useState(reminders);
  if (source !== initial) {
    setSource(initial);
    setData(initial);
    setValues(valuesFrom(initial.settings));
  }
  if (reminderSource !== reminders) {
    setReminderSource(reminders);
    setReminderData(reminders);
  }

  function saved(next: EmailSettings) {
    setData(next);
    setValues(valuesFrom(next.settings)); // clears the typed password
  }

  const dirty = isDirty(values, data.settings);
  // SMTP state can change on this page; keep the reminder readiness in step.
  const reminderView = reminderData && {
    ...reminderData,
    readiness: {
      email_configured: data.settings !== null,
      email_enabled: Boolean(data.settings?.is_enabled),
    },
  };

  return (
    <div className="space-y-6">
      <StatusOverview data={data} />
      <div className="grid gap-6 xl:grid-cols-3">
        <div className="min-w-0 space-y-6 xl:col-span-2">
          <SmtpSettingsForm
            data={data}
            values={values}
            onChange={setValues}
            onSaved={saved}
            onStale={() => router.refresh()}
          />
          <GmailHelp />
        </div>
        <div className="min-w-0 space-y-6">
          <SendingToggle data={data} onChanged={setData} onStale={() => router.refresh()} />
          <EmailTesting
            data={data}
            defaultRecipient={defaultRecipient}
            unsavedChanges={dirty}
            onResult={setData}
          />
          <TestHistoryCard data={data} />
        </div>
      </div>

      {reminderView && reminderHistory ? (
        <>
          <ReminderSettingsCard
            data={reminderView}
            onSaved={setReminderData}
            onStale={() => router.refresh()}
          />
          <ReminderActivity initial={reminderHistory} />
        </>
      ) : (
        <Notice tone="error" title="Reminder settings are unavailable">
          The subscription reminder settings could not be loaded. Refresh the page to try again.
        </Notice>
      )}
    </div>
  );
}

function GmailHelp() {
  return (
    <Notice tone="info" title="Using Gmail">
      <span className="flex items-start gap-2">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <span>
          Turn on 2-Step Verification for the Google account, then create an App Password at{" "}
          <span className="font-medium">myaccount.google.com/apppasswords</span>. Use host{" "}
          <code>smtp.gmail.com</code>, port 587 with STARTTLS (or 465 with SSL/TLS), your full
          Gmail address as the username and sender email, and the 16-character App Password as the
          password. Never use your normal Google password.
        </span>
      </span>
    </Notice>
  );
}
