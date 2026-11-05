import { useState } from "react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { historyPath, ReminderActivity } from "@/components/super-admin/email/reminder-activity";
import {
  ReminderSettingsCard,
  validateReminderForm,
} from "@/components/super-admin/email/reminder-settings";
import { EmailSettingsView } from "@/components/super-admin/email/email-settings-view";
import { ApiError, apiFetch } from "@/lib/api/client";
import type {
  EmailSettings,
  ReminderHistoryItem,
  ReminderHistoryPage,
  ReminderOverview,
} from "@/lib/api/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/super-admin/email-settings",
}));
vi.mock("@/lib/api/client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/client")>()),
  apiFetch: vi.fn(),
}));
const mockedFetch = vi.mocked(apiFetch);

beforeEach(() => mockedFetch.mockReset());
afterEach(cleanup);

function overview(overrides: Partial<ReminderOverview> = {}): ReminderOverview {
  return {
    settings: {
      is_enabled: false,
      notify_super_admin: true,
      notify_company_admin: true,
      version: 1,
      updated_at: "2026-11-05T09:00:00Z",
    },
    schedule: {
      days_before: 15,
      days_after: 5,
      send_time: "09:00",
      timezone: "Asia/Karachi",
      expiry_date: "2027-11-05",
      window_start: "2027-10-21",
      window_end: "2027-11-10",
      today: "2026-11-05",
      today_stage: null,
      next_reminder_date: "2027-10-21",
    },
    recipients: {
      super_admin_status: "selected",
      super_admin_email: "ow***@example.test",
      company_admin_emails: ["ad***@example.test"],
      company_admins_without_valid_email: 0,
    },
    readiness: { email_configured: true, email_enabled: true },
    last_run: { at: null, business_date: null, result: null, queued: null, already_queued: null },
    ...overrides,
  };
}

const COUNTS = {
  pending: 0,
  processing: 0,
  retry_scheduled: 0,
  accepted: 0,
  failed_permanent: 0,
  cancelled_obsolete: 0,
  cancelled: 0,
};

function item(overrides: Partial<ReminderHistoryItem> = {}): ReminderHistoryItem {
  return {
    id: crypto.randomUUID(),
    scheduled_date: "2027-10-21",
    expiry_date: "2027-11-05",
    days_offset: -15,
    stage: "15 days before expiry",
    recipient_categories: ["company_admin"],
    recipient: "ad***@example.test",
    status: "accepted",
    attempt_count: 1,
    max_attempts: 5,
    last_attempt_at: "2027-10-21T04:05:00Z",
    next_attempt_at: null,
    accepted_at: "2027-10-21T04:05:01Z",
    reason_code: null,
    reason: null,
    ...overrides,
  };
}

function page(items: ReminderHistoryItem[], total = items.length, offset = 0): ReminderHistoryPage {
  const counts = { ...COUNTS };
  for (const i of items) counts[i.status] += 1;
  return { items, total, limit: 10, offset, counts };
}

function renderCard(data = overview()) {
  const onSaved = vi.fn();
  render(<ReminderSettingsCard data={data} onSaved={onSaved} onStale={vi.fn()} />);
  return onSaved;
}

describe("ReminderSettingsCard", () => {
  it("renders disabled by default with the fixed schedule", () => {
    renderCard();
    expect(screen.getByText("Reminders Off")).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Send automatic reminders" })).toBeTruthy();
    expect(screen.getByText(/Daily from 15 days before expiry to 1 day before/)).toBeTruthy();
    expect(screen.getByText(/Daily for 5 days after expiry/)).toBeTruthy();
    expect(screen.getByText("21 Oct 2027 – 10 Nov 2027")).toBeTruthy();
    expect(screen.getByText("Not run yet")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Save reminder settings" })).toHaveProperty(
      "disabled",
      true,
    );
  });

  it("shows masked recipients only", () => {
    renderCard();
    expect(screen.getByText("ow***@example.test")).toBeTruthy();
    expect(screen.getByText("ad***@example.test")).toBeTruthy();
  });

  it("explains an ambiguous Super Admin", () => {
    renderCard(
      overview({
        recipients: {
          super_admin_status: "ambiguous",
          super_admin_email: null,
          company_admin_emails: [],
          company_admins_without_valid_email: 0,
        },
      }),
    );
    expect(screen.getByText(/More than one active Super Admin/)).toBeTruthy();
    expect(screen.getByText(/No active Company Admin/)).toBeTruthy();
  });

  it("enables reminders and saves with the expected version", async () => {
    const user = userEvent.setup();
    const saved = overview({
      settings: { ...overview().settings, is_enabled: true, version: 2 },
    });
    mockedFetch.mockResolvedValue(saved);
    const onSaved = vi.fn();
    function Harness() {
      const [data, setData] = useState(overview());
      return (
        <ReminderSettingsCard
          data={data}
          onSaved={(next) => {
            onSaved(next);
            setData(next);
          }}
          onStale={vi.fn()}
        />
      );
    }
    render(<Harness />);
    await user.click(screen.getByRole("switch", { name: "Send automatic reminders" }));
    await user.click(screen.getByRole("button", { name: "Save reminder settings" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
    expect(await screen.findByText("Reminders On")).toBeTruthy();
    const [path, init] = mockedFetch.mock.calls[0];
    expect(path).toBe("/super-admin/email-settings/reminders");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({
      is_enabled: true,
      notify_super_admin: true,
      notify_company_admin: true,
      expected_version: 1,
    });
    expect(await screen.findByText("Reminder settings saved.")).toBeTruthy();
  });

  it("requires a recipient group when enabling", async () => {
    const user = userEvent.setup();
    renderCard();
    await user.click(screen.getByRole("switch", { name: "Send automatic reminders" }));
    await user.click(screen.getByLabelText(/Notify Super Admin/));
    await user.click(screen.getByLabelText(/Notify Company Admin/));
    await user.click(screen.getByRole("button", { name: "Save reminder settings" }));
    expect(await screen.findByText(/Choose at least one recipient group/)).toBeTruthy();
    expect(mockedFetch).not.toHaveBeenCalled();
    expect(
      validateReminderForm({
        is_enabled: false,
        notify_super_admin: false,
        notify_company_admin: false,
      }),
    ).toBeNull();
  });

  it("shows a loading state while saving and the server error after", async () => {
    const user = userEvent.setup();
    let reject!: (e: unknown) => void;
    mockedFetch.mockImplementationOnce(() => new Promise((_, r) => (reject = r)));
    renderCard();
    await user.click(screen.getByLabelText(/Notify Company Admin/));
    await user.click(screen.getByRole("button", { name: "Save reminder settings" }));
    expect(await screen.findByRole("button", { name: /Saving/ })).toHaveProperty("disabled", true);
    reject(new ApiError(409, "stale_reminder_settings", "The reminder settings were changed."));
    expect(await screen.findByText("The reminder settings were changed.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload settings" })).toBeTruthy();
  });

  it("warns when email sending is off or SMTP is missing", () => {
    renderCard(overview({ readiness: { email_configured: true, email_enabled: false } }));
    expect(screen.getByText("Email sending is disabled")).toBeTruthy();
    cleanup();
    renderCard(overview({ readiness: { email_configured: false, email_enabled: false } }));
    expect(screen.getByText("SMTP settings are not configured")).toBeTruthy();
  });

  it("shows the last scheduler result", () => {
    renderCard(
      overview({
        last_run: {
          at: "2027-10-21T04:05:00Z",
          business_date: "2027-10-21",
          result: "queued",
          queued: 2,
          already_queued: 0,
        },
      }),
    );
    expect(screen.getByText("Reminders queued for sending (2)")).toBeTruthy();
    expect(screen.getByText("21 Oct 2027, 09:05")).toBeTruthy();
  });
});

describe("ReminderActivity", () => {
  it("shows an empty state", () => {
    render(<ReminderActivity initial={page([])} />);
    expect(screen.getByText(/No reminders yet/)).toBeTruthy();
  });

  it("lists deliveries with accurate status wording", () => {
    render(
      <ReminderActivity
        initial={page([
          item(),
          item({
            status: "failed_permanent",
            reason: "The SMTP server refused the recipient email address.",
            recipient_categories: ["super_admin", "company_admin"],
          }),
          item({ status: "cancelled_obsolete", attempt_count: 0 }),
        ])}
      />,
    );
    const table = screen.getByRole("table");
    expect(within(table).getAllByText("Accepted by SMTP Server").length).toBe(1);
    expect(within(table).getByText("Failed Permanently")).toBeTruthy();
    expect(within(table).getByText("Cancelled / Obsolete")).toBeTruthy();
    expect(within(table).getByText("Super Admin + Company Admin")).toBeTruthy();
    expect(within(table).getByText(/refused the recipient/)).toBeTruthy();
    expect(screen.getByText(/does not\s+prove it reached the inbox/)).toBeTruthy();
  });

  it("filters by status", async () => {
    const user = userEvent.setup();
    mockedFetch.mockResolvedValue(page([item({ status: "failed_permanent" })]));
    render(<ReminderActivity initial={page([item(), item({ status: "failed_permanent" })])} />);
    await user.click(screen.getByRole("button", { name: /Failed Permanently \(1\)/ }));
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    expect(mockedFetch.mock.calls[0][0]).toBe(historyPath("failed_permanent", 0));
    expect(mockedFetch.mock.calls[0][0]).toContain("status=failed_permanent");
    expect(
      screen.getByRole("button", { name: /Failed Permanently/ }).getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("paginates", async () => {
    const user = userEvent.setup();
    const first = page(Array.from({ length: 10 }, () => item()), 12, 0);
    mockedFetch.mockResolvedValue(page([item(), item()], 12, 10));
    render(<ReminderActivity initial={first} />);
    expect(screen.getByText("1–10 of 12")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Previous/ })).toHaveProperty("disabled", true);
    await user.click(screen.getByRole("button", { name: /Next/ }));
    expect(await screen.findByText("11–12 of 12")).toBeTruthy();
    expect(mockedFetch.mock.calls[0][0]).toBe(historyPath("all", 10));
  });

  it("shows a load error", async () => {
    const user = userEvent.setup();
    mockedFetch.mockRejectedValueOnce(new ApiError(503, "service_unavailable", "Try again."));
    render(<ReminderActivity initial={page([item()])} />);
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("Try again.")).toBeTruthy();
  });

  it("has a mobile list alongside the table", () => {
    render(<ReminderActivity initial={page([item()])} />);
    expect(screen.getByRole("list", { name: "Subscription reminder deliveries" })).toBeTruthy();
  });
});

describe("Email Settings page integration", () => {
  const smtp: EmailSettings = {
    status: "disabled",
    encryption_ready: true,
    allowed_ports: [25, 465, 587, 2525],
    settings: {
      smtp_host: "smtp.gmail.com",
      smtp_port: 587,
      encryption_mode: "starttls",
      smtp_username: "o@example.test",
      password_set: true,
      password_readable: true,
      sender_email: "o@example.test",
      sender_name: "Cheena",
      is_enabled: false,
      version: 1,
      updated_at: "2026-11-05T09:00:00Z",
    },
    history: null,
  };

  it("adds the reminder sections and follows the page's email sending state", () => {
    render(
      <EmailSettingsView
        initial={smtp}
        defaultRecipient="o@example.test"
        reminders={overview()}
        reminderHistory={page([])}
      />,
    );
    expect(screen.getByRole("heading", { name: "Subscription Expiry Reminders" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Reminder Activity" })).toBeTruthy();
    // SMTP sending is off on this page, so the reminder card warns about it.
    const card = screen.getByRole("region", { name: "Subscription Expiry Reminders" });
    expect(within(card).getByText("Email sending is disabled")).toBeTruthy();
  });

  it("shows an error state when reminder data could not be loaded", () => {
    render(
      <EmailSettingsView
        initial={smtp}
        defaultRecipient=""
        reminders={null}
        reminderHistory={null}
      />,
    );
    expect(screen.getByText("Reminder settings are unavailable")).toBeTruthy();
  });
});
