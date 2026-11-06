import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RenewalHistory } from "@/components/super-admin/subscription/renewal-history";
import { validateNewExpiry } from "@/components/super-admin/subscription/renew-form";
import { SubscriptionManagementView } from "@/components/super-admin/subscription/subscription-management-view";
import { ApiError, apiFetch } from "@/lib/api/client";
import type {
  RenewalPage,
  RenewResponse,
  Subscription,
  SubscriptionManagement,
} from "@/lib/api/types";

const router = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: router.refresh, push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/super-admin/subscription",
}));
vi.mock("@/lib/api/client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/client")>()),
  apiFetch: vi.fn(),
}));
const mockedFetch = vi.mocked(apiFetch);

beforeEach(() => {
  mockedFetch.mockReset();
  router.refresh.mockReset();
});
afterEach(cleanup);

const active: Subscription = {
  status: "active",
  start_date: "2026-11-05",
  expiry_date: "2027-11-04",
  last_renewed_on: null,
  total_days: 365,
  days_used: 1,
  days_remaining: 364,
  days_until_start: 0,
  progress_percent: 0.3,
  expiring_soon_threshold_days: 15,
};

function management(overrides: Partial<SubscriptionManagement> = {}): SubscriptionManagement {
  return {
    today: "2026-11-05",
    timezone: "Asia/Karachi",
    company: { name: "Cheena", account_type: "single_company" },
    subscription: active,
    renewal: {
      can_renew: true,
      min_new_expiry_date: "2027-11-05",
      max_new_expiry_date: "2037-11-02",
    },
    ...overrides,
  };
}

const emptyHistory: RenewalPage = { items: [], total: 0, limit: 10, offset: 0 };

const renewedResponse: RenewResponse = {
  replayed: false,
  renewal: {
    id: "r1",
    renewed_at: "2026-11-05T09:30:00Z",
    previous_expiry_date: "2027-11-04",
    new_expiry_date: "2028-11-04",
    renewal_note: "Annual",
    renewed_by: { full_name: "Owner", email: "owner@example.test" },
  },
  subscription: { ...active, expiry_date: "2028-11-04" },
};

function renderView(data = management(), history = emptyHistory) {
  return render(<SubscriptionManagementView data={data} history={history} allowance={null} />);
}

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Renew Subscription" }));
  return screen.findByRole("dialog");
}

/** Pick a date through the calendar popup (year/month dropdowns, then the day). */
async function pickDate(user: ReturnType<typeof userEvent.setup>, iso: string) {
  await user.click(screen.getByRole("button", { name: /New expiry date/ }));
  const [y, m] = iso.split("-").map(Number);
  await user.selectOptions(await screen.findByRole("combobox", { name: "Choose the Year" }), String(y));
  await user.selectOptions(screen.getByRole("combobox", { name: "Choose the Month" }), String(m - 1));
  const day = await waitFor(() => {
    const button = document.querySelector<HTMLButtonElement>(`td[data-day="${iso}"] button`);
    if (!button) throw new Error(`day ${iso} not rendered`);
    return button;
  });
  await user.click(day);
}

async function reviewWithDate(user: ReturnType<typeof userEvent.setup>, iso: string) {
  await pickDate(user, iso);
  await user.click(screen.getByRole("button", { name: /Review renewal/ }));
}

describe("Subscription overview", () => {
  it("shows the database-backed values", () => {
    renderView();
    const overview = screen.getByRole("region", { name: "Subscription Overview" });
    for (const text of ["Cheena", "05 Nov 2026", "04 Nov 2027", "Active", "365 days", "1 day", "No renewal recorded"]) {
      expect(within(overview).getByText(text)).toBeTruthy();
    }
    expect(screen.getByTestId("days-remaining").textContent).toBe("364");
    expect(screen.getByRole("button", { name: "Renew Subscription" })).toHaveProperty("disabled", false);
  });

  it("disables renewal when no subscription is configured", () => {
    renderView(
      management({
        company: { name: null, account_type: "single_company" },
        subscription: { ...active, status: "not_configured", start_date: null, expiry_date: null, total_days: null, days_used: null, days_remaining: null, progress_percent: null },
        renewal: { can_renew: false, min_new_expiry_date: null, max_new_expiry_date: null },
      }),
    );
    expect(screen.getByRole("button", { name: "Renew Subscription" })).toHaveProperty("disabled", true);
    expect(screen.getAllByRole("status")[0].textContent).toMatch(/Subscription not configured/);
  });
});

describe("Renewal dialog", () => {
  it("opens with read-only current details and closes with Cancel and Escape", async () => {
    const user = userEvent.setup({ delay: null });
    renderView();

    const dialog = await openDialog(user);
    expect(within(dialog).getByText("Cheena")).toBeTruthy();
    expect(within(dialog).getByText("05 Nov 2026")).toBeTruthy();
    expect(within(dialog).getByText("04 Nov 2027")).toBeTruthy();
    expect(within(dialog).queryByRole("textbox", { name: /start/i })).toBeNull();

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await openDialog(user);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("starts at the earliest valid date, shown as DD MMM YYYY", async () => {
    const user = userEvent.setup({ delay: null });
    renderView();
    await openDialog(user);
    const trigger = screen.getByRole("button", { name: /New expiry date/ });
    expect(trigger.textContent).toBe("05 Nov 2027");
    expect(trigger.getAttribute("aria-invalid")).toBeNull();
  });

  it("cannot select the unchanged or an earlier expiry date", async () => {
    const user = userEvent.setup({ delay: null });
    renderView();
    await openDialog(user);
    await user.click(screen.getByRole("button", { name: /New expiry date/ }));

    for (const iso of ["2027-11-04", "2027-11-01"]) {
      const button = document.querySelector<HTMLButtonElement>(`td[data-day="${iso}"] button`)!;
      expect(button.disabled).toBe(true);
      await user.click(button);
    }
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: /New expiry date/ }).textContent).toBe("05 Nov 2027");
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("shows the impact and requires explicit confirmation", async () => {
    const user = userEvent.setup({ delay: null });
    mockedFetch.mockResolvedValue(renewedResponse);
    renderView();
    await openDialog(user);
    await user.type(screen.getByLabelText(/Renewal note/), "Annual");
    await reviewWithDate(user, "2028-11-04");

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("04 Nov 2027 → 04 Nov 2028")).toBeTruthy();
    expect(within(dialog).getByText("+366 days")).toBeTruthy();
    expect(within(dialog).getByText("05 Nov 2026 (unchanged)")).toBeTruthy();
    expect(within(dialog).getByText("731 days")).toBeTruthy(); // new total
    expect(mockedFetch).not.toHaveBeenCalled(); // nothing saved before confirmation

    await user.click(within(dialog).getByRole("button", { name: "Confirm renewal" }));

    expect(mockedFetch).toHaveBeenCalledTimes(1);
    const [path, init] = mockedFetch.mock.calls[0];
    expect(path).toBe("/super-admin/subscription/renew");
    const body = JSON.parse(init!.body as string);
    expect(body).toMatchObject({
      new_expiry_date: "2028-11-04",
      expected_expiry_date: "2027-11-04",
      renewal_note: "Annual",
    });
    expect(body.idempotency_key).toMatch(/^[0-9a-f-]{36}$/);

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("status").textContent).toMatch(/Subscription renewed.*04 Nov 2028/);
    expect(router.refresh).toHaveBeenCalledTimes(1); // Dashboard/history re-fetch
  });

  it("sends one request for repeated confirm clicks", async () => {
    const user = userEvent.setup({ delay: null });
    let resolve: (v: RenewResponse) => void = () => {};
    mockedFetch.mockImplementation(() => new Promise((r) => (resolve = r as typeof resolve)));
    renderView();
    await openDialog(user);
    await reviewWithDate(user, "2028-11-04");

    const confirm = screen.getByRole("button", { name: "Confirm renewal" });
    await user.click(confirm);
    await user.click(confirm);
    expect(mockedFetch).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Renewing…" })).toHaveProperty("disabled", true);

    await act(async () => resolve(renewedResponse));
  });

  it("retries with the same idempotency key after a network error", async () => {
    const user = userEvent.setup({ delay: null });
    mockedFetch
      .mockRejectedValueOnce(new ApiError(0, "network_error", "Unable to reach the server."))
      .mockResolvedValueOnce(renewedResponse);
    renderView();
    await openDialog(user);
    await reviewWithDate(user, "2028-11-04");

    await user.click(screen.getByRole("button", { name: "Confirm renewal" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/Unable to reach the server/);
    await user.click(screen.getByRole("button", { name: "Confirm renewal" }));

    const keys = mockedFetch.mock.calls.map(([, init]) => JSON.parse(init!.body as string).idempotency_key);
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it("offers a reload when the subscription changed meanwhile (409)", async () => {
    const user = userEvent.setup({ delay: null });
    mockedFetch.mockRejectedValue(
      new ApiError(409, "stale_subscription", "The subscription was changed after this form was opened."),
    );
    renderView();
    await openDialog(user);
    await reviewWithDate(user, "2028-11-04");
    await user.click(screen.getByRole("button", { name: "Confirm renewal" }));

    expect((await screen.findByRole("alert")).textContent).toMatch(/changed after this form/);
    await user.click(screen.getByRole("button", { name: "Reload subscription" }));
    expect(router.refresh).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("returns to the form with the backend message on 422", async () => {
    const user = userEvent.setup({ delay: null });
    mockedFetch.mockRejectedValue(
      new ApiError(422, "invalid_renewal", "The new expiry date must be later than today."),
    );
    renderView();
    await openDialog(user);
    await reviewWithDate(user, "2028-11-04");
    await user.click(screen.getByRole("button", { name: "Confirm renewal" }));

    expect((await screen.findByRole("alert")).textContent).toMatch(/later than today/);
    expect(screen.getByLabelText("New expiry date")).toBeTruthy();
  });

  it("is operable from the keyboard", async () => {
    const user = userEvent.setup({ delay: null });
    renderView();
    screen.getByRole("button", { name: "Renew Subscription" }).focus();
    await user.keyboard("{Enter}");
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("validateNewExpiry", () => {
  const rules = management().renewal;
  it.each([
    ["", "Choose a new expiry date."],
    ["2027-02-30", "Enter a valid date."],
    ["2027-11-04", /on or after/],
    ["2040-01-01", /on or before/],
  ])("rejects %s", (value, message) => {
    expect(validateNewExpiry(value, rules)).toMatch(message);
  });
  it("accepts a date inside the window", () => {
    expect(validateNewExpiry("2028-11-04", rules)).toBeNull();
  });
});

describe("RenewalHistory", () => {
  it("shows an empty state without fabricated rows", () => {
    render(<RenewalHistory initial={emptyHistory} />);
    expect(screen.getByText("No renewals yet")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("lists renewals read-only, with times in Pakistan time", () => {
    render(<RenewalHistory initial={{ items: [renewedResponse.renewal], total: 1, limit: 10, offset: 0 }} />);
    const table = screen.getByRole("table");
    expect(within(table).getByText("05 Nov 2026, 14:30")).toBeTruthy(); // 09:30 UTC = 14:30 PKT
    expect(within(table).getByText("04 Nov 2027")).toBeTruthy();
    expect(within(table).getByText("04 Nov 2028")).toBeTruthy();
    expect(within(table).getByText("Owner")).toBeTruthy();
    expect(within(table).getByText("Annual")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull(); // no edit/delete controls
  });

  it("pages through older renewals", async () => {
    const user = userEvent.setup({ delay: null });
    const items = Array.from({ length: 10 }, (_, i) => ({ ...renewedResponse.renewal, id: `r${i}` }));
    mockedFetch.mockResolvedValue({ items: [{ ...renewedResponse.renewal, id: "old" }], total: 11, limit: 10, offset: 10 });
    render(<RenewalHistory initial={{ items, total: 11, limit: 10, offset: 0 }} />);

    expect(screen.getByText("Showing 1–10 of 11")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /Older/ }));
    expect(mockedFetch).toHaveBeenCalledWith("/super-admin/subscription/renewals?limit=10&offset=10");
    expect(await screen.findByText("Showing 11–11 of 11")).toBeTruthy();
  });
});
