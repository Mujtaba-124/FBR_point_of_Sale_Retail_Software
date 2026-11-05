import { redirect } from "next/navigation";

import { REMINDER_PAGE_SIZE } from "@/components/super-admin/email/reminder-constants";
import { EmailSettingsView } from "@/components/super-admin/email/email-settings-view";
import { DashboardError, DashboardForbidden } from "@/components/super-admin/states";
import type { EmailSettings, ReminderHistoryPage, ReminderOverview } from "@/lib/api/types";
import { fetchBackend, getCurrentUser } from "@/lib/auth-server";

/** Request-time data for the Email Settings page. Render inside <Suspense>. */
export async function EmailSettingsSection() {
  const [result, me, reminders, history] = await Promise.all([
    fetchBackend<EmailSettings>("/api/v1/super-admin/email-settings"),
    getCurrentUser(),
    fetchBackend<ReminderOverview>("/api/v1/super-admin/email-settings/reminders"),
    fetchBackend<ReminderHistoryPage>(
      `/api/v1/super-admin/email-settings/reminder-history?limit=${REMINDER_PAGE_SIZE}&offset=0`,
    ),
  ]);
  if (result.status === "unauthenticated") redirect("/login?reason=session_expired");
  if (result.status === "forbidden") return <DashboardForbidden />;
  if (result.status !== "ok") return <DashboardError />;

  return (
    <EmailSettingsView
      initial={result.data}
      defaultRecipient={me.status === "ok" ? me.data.email : ""}
      reminders={reminders.status === "ok" ? reminders.data : null}
      reminderHistory={history.status === "ok" ? history.data : null}
    />
  );
}
