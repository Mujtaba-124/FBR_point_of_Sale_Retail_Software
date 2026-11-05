import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EmailSettingsView } from "@/components/super-admin/email/email-settings-view";
import {
  emptyValues,
  hostProblem,
  isDirty,
  toRequest,
  validateSmtpForm,
} from "@/components/super-admin/email/email-validation";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { EmailCheckResult, EmailSettings, SmtpSettings } from "@/lib/api/types";

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

const PORTS = [25, 465, 587, 2525];

function smtp(overrides: Partial<SmtpSettings> = {}): SmtpSettings {
  return {
    smtp_host: "smtp.gmail.com",
    smtp_port: 587,
    encryption_mode: "starttls",
    smtp_username: "owner@example.test",
    password_set: true,
    password_readable: true,
    sender_email: "owner@example.test",
    sender_name: "Cheena FBR POS",
    is_enabled: false,
    version: 3,
    updated_at: "2026-11-05T09:00:00Z",
    ...overrides,
  };
}

function data(settings: SmtpSettings | null, overrides: Partial<EmailSettings> = {}): EmailSettings {
  return {
    status: settings ? (settings.is_enabled ? "configured" : "disabled") : "not_configured",
    encryption_ready: true,
    allowed_ports: PORTS,
    settings,
    history: settings
      ? {
          last_test_status: null,
          last_test_kind: null,
          last_test_at: null,
          last_success_at: null,
          last_failure_at: null,
          last_failure_code: null,
          last_failure_message: null,
        }
      : null,
    ...overrides,
  };
}

function renderView(initial: EmailSettings) {
  return render(
    <EmailSettingsView
      initial={initial}
      defaultRecipient="admin@example.test"
      reminders={null}
      reminderHistory={null}
    />,
  );
}

function lastBody(): Record<string, unknown> {
  const call = mockedFetch.mock.calls.at(-1)!;
  return JSON.parse(String(call[1]?.body));
}

describe("validation", () => {
  it("rejects local and malformed hosts", () => {
    expect(hostProblem("smtp.gmail.com")).toBeNull();
    expect(hostProblem("localhost")).toMatch(/not allowed/);
    expect(hostProblem("printer.local")).toMatch(/not allowed/);
    expect(hostProblem("smtp")).toMatch(/valid host/);
    expect(hostProblem("")).toMatch(/Enter/);
  });

  it("checks ports, passwords and header injection", () => {
    const base = {
      ...emptyValues(),
      smtp_host: "smtp.gmail.com",
      smtp_username: "a@example.test",
      sender_email: "a@example.test",
    };
    const opts = { allowedPorts: PORTS, passwordStored: false };
    expect(validateSmtpForm({ ...base, smtp_password: "x" }, opts)).toEqual({});
    expect(validateSmtpForm(base, opts).smtp_password).toMatch(/Enter the SMTP password/);
    expect(validateSmtpForm(base, { ...opts, passwordStored: true })).toEqual({});
    expect(validateSmtpForm({ ...base, smtp_password: "x", smtp_port: "8080" }, opts).smtp_port)
      .toBeTruthy();
    expect(
      validateSmtpForm({ ...base, smtp_password: "x", sender_name: "A\r\nBcc: x@y.z" }, opts)
        .sender_name,
    ).toMatch(/not allowed/);
  });

  it("sends a blank password as null so the stored one is kept", () => {
    const body = toRequest({ ...emptyValues(), smtp_host: " smtp.gmail.com " }, 4);
    expect(body.smtp_password).toBeNull();
    expect(body.smtp_host).toBe("smtp.gmail.com");
    expect(body.expected_version).toBe(4);
  });

  it("treats a typed password as an unsaved change", () => {
    const s = smtp();
    const values = { ...emptyValues(), ...toValues(s) };
    expect(isDirty(values, s)).toBe(false);
    expect(isDirty({ ...values, smtp_password: "new" }, s)).toBe(true);
  });
});

function toValues(s: SmtpSettings) {
  return {
    smtp_host: s.smtp_host,
    smtp_port: String(s.smtp_port),
    encryption_mode: s.encryption_mode,
    smtp_username: s.smtp_username ?? "",
    smtp_password: "",
    sender_email: s.sender_email,
    sender_name: s.sender_name,
  };
}

describe("EmailSettingsView", () => {
  it("shows the Not Configured state", () => {
    renderView(data(null));
    expect(screen.getAllByText("Not Configured").length).toBeGreaterThan(0);
    expect(screen.getByRole("switch")).toHaveProperty("ariaDisabled", "true");
    expect(screen.getByRole("button", { name: /Test Connection/ })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Save settings" })).toBeTruthy();
  });

  it("never shows the stored password and marks it as configured", () => {
    renderView(data(smtp()));
    expect(screen.getByText("Password configured")).toBeTruthy();
    const password = screen.getByLabelText(/SMTP password/) as HTMLInputElement;
    expect(password.value).toBe("");
    expect(password.type).toBe("password");
    expect(password.autocomplete).toBe("new-password");
    expect(screen.getByText("Leave blank to keep the saved password.")).toBeTruthy();
    expect(screen.getAllByText("Email Sending Disabled").length).toBeGreaterThan(0);
  });

  it("toggles password visibility", async () => {
    const user = userEvent.setup();
    renderView(data(null));
    const password = screen.getByLabelText(/SMTP password/) as HTMLInputElement;
    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(password.type).toBe("text");
    await user.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password.type).toBe("password");
  });

  it("saves with a blank password to keep the stored one", async () => {
    const user = userEvent.setup();
    const saved = data(smtp({ sender_name: "Billing", version: 4 }));
    mockedFetch.mockResolvedValue(saved);
    renderView(data(smtp()));
    const name = screen.getByLabelText("Sender name");
    await user.clear(name);
    await user.type(name, "Billing");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(1));
    expect(mockedFetch.mock.calls[0][0]).toBe("/super-admin/email-settings");
    expect(mockedFetch.mock.calls[0][1]?.method).toBe("PUT");
    expect(lastBody()).toMatchObject({
      smtp_password: null,
      sender_name: "Billing",
      expected_version: 3,
    });
    expect(await screen.findByText(/Settings saved/)).toBeTruthy();
  });

  it("clears the typed password after saving", async () => {
    const user = userEvent.setup();
    mockedFetch.mockResolvedValue(data(smtp({ version: 4 })));
    renderView(data(smtp()));
    const password = screen.getByLabelText(/SMTP password/) as HTMLInputElement;
    await user.type(password, "abcdabcdabcdabcd");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(password.value).toBe(""));
    expect(lastBody().smtp_password).toBe("abcdabcdabcdabcd");
  });

  it("shows field errors without calling the API", async () => {
    const user = userEvent.setup();
    renderView(data(null));
    await user.type(screen.getByLabelText("SMTP host"), "localhost");
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    expect(await screen.findByText(/This SMTP host is not allowed/)).toBeTruthy();
    expect(screen.getByText("Enter a valid sender email address.")).toBeTruthy();
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("fills Gmail settings and switches the port with the encryption mode", async () => {
    const user = userEvent.setup();
    renderView(data(null));
    await user.click(screen.getByRole("button", { name: "Use Gmail settings" }));
    expect((screen.getByLabelText("SMTP host") as HTMLInputElement).value).toBe("smtp.gmail.com");
    await user.click(screen.getByRole("radio", { name: /SSL\/TLS/ }));
    expect((screen.getByLabelText("Port") as HTMLInputElement).value).toBe("465");
    await user.click(screen.getByRole("radio", { name: /STARTTLS/ }));
    expect((screen.getByLabelText("Port") as HTMLInputElement).value).toBe("587");
  });

  it("shows the server's stale-version error with a reload action", async () => {
    const user = userEvent.setup();
    mockedFetch.mockRejectedValueOnce(
      new ApiError(409, "stale_email_settings", "The email settings were changed."),
    );
    renderView(data(smtp()));
    await user.type(screen.getByLabelText("Sender name"), "x");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("The email settings were changed.")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Reload settings" }).length).toBe(1);
  });

  it("warns when the encryption key is missing", () => {
    renderView(data(null, { encryption_ready: false }));
    expect(screen.getByText("Encryption key not set up")).toBeTruthy();
  });

  it("asks to re-enter an unreadable password and blocks tests", () => {
    renderView(data(smtp({ password_readable: false, is_enabled: true })));
    expect(screen.getByText("Re-enter the SMTP password")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Test Connection/ })).toHaveProperty("disabled", true);
  });

  it("enables sending through the switch", async () => {
    const user = userEvent.setup();
    mockedFetch.mockResolvedValue(data(smtp({ is_enabled: true, version: 4 })));
    renderView(data(smtp()));
    await user.click(screen.getByRole("switch"));
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    expect(mockedFetch.mock.calls[0][0]).toBe("/super-admin/email-settings/sending");
    expect(lastBody()).toEqual({ enabled: true, expected_version: 3 });
    expect(await screen.findByText("Email sending is enabled")).toBeTruthy();
    expect(screen.getAllByText("Configured").length).toBeGreaterThan(0);
  });

  it("disables Send Test Email while sending is disabled", () => {
    renderView(data(smtp({ is_enabled: false })));
    expect(screen.getByRole("button", { name: /Send Test Email/ })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: /Test Connection/ })).toHaveProperty("disabled", false);
    expect(screen.getByText("Enable email sending to send a test email.")).toBeTruthy();
  });

  it("blocks tests while there are unsaved changes", async () => {
    const user = userEvent.setup();
    renderView(data(smtp({ is_enabled: true })));
    await user.type(screen.getByLabelText("Sender name"), "x");
    expect(screen.getByText(/You have unsaved changes/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Test Connection/ })).toHaveProperty("disabled", true);
  });

  it("runs a connection test and shows the result", async () => {
    const user = userEvent.setup();
    const result: EmailCheckResult = {
      kind: "connection",
      ok: true,
      code: null,
      message: "Connection successful. No email was sent.",
      tested_at: "2026-11-05T09:05:00Z",
      replayed: false,
      email_settings: data(smtp()),
    };
    mockedFetch.mockResolvedValue(result);
    renderView(data(smtp()));
    await user.click(screen.getByRole("button", { name: /Test Connection/ }));
    expect(await screen.findByText("Connection test passed")).toBeTruthy();
    expect(screen.getByText("Connection successful. No email was sent.")).toBeTruthy();
    expect(mockedFetch.mock.calls[0][0]).toBe("/super-admin/email-settings/test-connection");
  });

  it("shows a failed test's safe message", async () => {
    const user = userEvent.setup();
    mockedFetch.mockResolvedValue({
      kind: "connection",
      ok: false,
      code: "smtp_auth_failed",
      message: "The SMTP server rejected the username or password.",
      tested_at: "2026-11-05T09:05:00Z",
      replayed: false,
      email_settings: data(smtp()),
    } satisfies EmailCheckResult);
    renderView(data(smtp()));
    await user.click(screen.getByRole("button", { name: /Test Connection/ }));
    expect(await screen.findByText("Connection test failed")).toBeTruthy();
  });

  it("reuses the idempotency key only after a network error", async () => {
    const user = userEvent.setup();
    const ok: EmailCheckResult = {
      kind: "email",
      ok: true,
      code: null,
      message: "Test email accepted by the SMTP server. Please check the recipient inbox.",
      tested_at: "2026-11-05T09:05:00Z",
      replayed: false,
      email_settings: data(smtp({ is_enabled: true })),
    };
    mockedFetch
      .mockRejectedValueOnce(new ApiError(0, "network_error", "Unable to reach the server."))
      .mockResolvedValueOnce(ok)
      .mockResolvedValueOnce(ok);
    renderView(data(smtp({ is_enabled: true })));
    const send = screen.getByRole("button", { name: /Send Test Email/ });

    await user.click(send);
    expect(await screen.findByText(/Retrying is safe/)).toBeTruthy();
    const first = lastBody();
    expect(first.recipient_email).toBe("admin@example.test");

    await user.click(send);
    expect(await screen.findByText("Test email accepted")).toBeTruthy();
    expect(
      screen.getByText("Test email accepted by the SMTP server. Please check the recipient inbox."),
    ).toBeTruthy();
    expect(lastBody().idempotency_key).toBe(first.idempotency_key);

    await user.click(send);
    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(3));
    expect(lastBody().idempotency_key).not.toBe(first.idempotency_key);
  });

  it("validates the recipient before sending", async () => {
    const user = userEvent.setup();
    renderView(data(smtp({ is_enabled: true })));
    const input = screen.getByLabelText("Send a test email to");
    await user.clear(input);
    await user.type(input, "not-an-email");
    await user.click(screen.getByRole("button", { name: /Send Test Email/ }));
    expect(await screen.findByText("Enter a valid recipient email address.")).toBeTruthy();
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("shows the last success and failure", () => {
    renderView(
      data(smtp(), {
        history: {
          last_test_status: "failure",
          last_test_kind: "connection",
          last_test_at: "2026-11-05T10:00:00Z",
          last_success_at: "2026-11-05T09:00:00Z",
          last_failure_at: "2026-11-05T10:00:00Z",
          last_failure_code: "smtp_timeout",
          last_failure_message: "The SMTP server did not respond in time.",
        },
      }),
    );
    expect(screen.getByText("Last successful test")).toBeTruthy();
    expect(screen.getAllByText("05 Nov 2026, 15:00")).toHaveLength(2); // PKT: tested + failed
    // Last success, plus "Last updated" in the overview (same 09:00 UTC timestamp).
    expect(screen.getAllByText("05 Nov 2026, 14:00")).toHaveLength(2);
    expect(screen.getByText("The SMTP server did not respond in time.")).toBeTruthy();
  });
});
