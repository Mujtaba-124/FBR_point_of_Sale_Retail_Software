import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DashboardView } from "@/components/super-admin/dashboard-view";
import { DashboardError, DashboardSkeleton } from "@/components/super-admin/states";
import type { CompanyAdminContact, Subscription, SuperAdminDashboard } from "@/lib/api/types";
import { formatDate } from "@/lib/format";

afterEach(cleanup);

const base: Subscription = {
  status: "active",
  start_date: "2026-01-01",
  expiry_date: "2026-12-31",
  last_renewed_on: null,
  total_days: 365,
  days_used: 152,
  days_remaining: 213,
  days_until_start: 0,
  progress_percent: 41.6,
  expiring_soon_threshold_days: 15,
};

const contact: CompanyAdminContact = {
  status: "available",
  count: 1,
  full_name: "Company Admin Person",
  email: "admin@example.test",
  is_active: true,
};

function data(subscription: Partial<Subscription>, overrides: Partial<SuperAdminDashboard> = {}) {
  return {
    today: "2026-06-01",
    timezone: "Asia/Karachi",
    company: { name: "Test Company", account_type: "single_company" },
    company_admin: contact,
    subscription: { ...base, ...subscription },
    ...overrides,
  } satisfies SuperAdminDashboard;
}

const remaining = () => screen.getByTestId("days-remaining").textContent;

describe("DashboardView", () => {
  it("shows backend-computed numbers for an active subscription", () => {
    render(<DashboardView data={data({})} />);

    expect(remaining()).toBe("213");
    expect(screen.getAllByText("Active").length).toBeGreaterThan(0);
    const bar = screen.getByRole("progressbar", { name: "Subscription period elapsed" });
    expect(bar.getAttribute("aria-valuenow")).toBe("41.6");
    expect(bar.getAttribute("aria-valuetext")).toBe("152 days of 365 days used");
    // Shown in both the Company Account card and the Subscription Information list.
    expect(screen.getAllByText("Test Company", { selector: "dd" })).toHaveLength(2);
    expect(screen.getByRole("link", { name: "admin@example.test" }).getAttribute("href")).toBe(
      "mailto:admin@example.test",
    );
  });

  it("shows Expiring Soon with the threshold explanation", () => {
    render(<DashboardView data={data({ status: "expiring_soon", days_remaining: 10, days_used: 355 })} />);
    expect(remaining()).toBe("10");
    expect(screen.getAllByText("Expiring Soon").length).toBeGreaterThan(0);
    expect(screen.getByText(/15 or fewer days remain/)).toBeTruthy();
  });

  it("shows zero on the expiry day while still valid", () => {
    render(<DashboardView data={data({ status: "expiring_soon", days_remaining: 0, days_used: 365, progress_percent: 100 })} />);
    expect(remaining()).toBe("0");
    expect(screen.getByText(/Today is the last valid day/)).toBeTruthy();
  });

  it("shows zero and Expired after expiry, never a negative number", () => {
    render(<DashboardView data={data({ status: "expired", days_remaining: 0, days_used: 365, progress_percent: 100 })} />);
    expect(remaining()).toBe("0");
    expect(screen.getAllByText("Expired").length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(/-\d/);
  });

  it("shows a scheduled subscription that has not started", () => {
    render(<DashboardView data={data({ status: "scheduled", days_used: 0, days_remaining: 365, days_until_start: 10, progress_percent: 0 })} />);
    expect(screen.getAllByText("Not Started").length).toBeGreaterThan(0);
    expect(screen.getByText(/in 10 days/)).toBeTruthy();
  });

  it("shows an honest empty state when no subscription is configured", () => {
    render(
      <DashboardView
        data={data(
          {
            status: "not_configured",
            start_date: null,
            expiry_date: null,
            total_days: null,
            days_used: null,
            days_remaining: null,
            days_until_start: null,
            progress_percent: null,
          },
          { company: { name: null, account_type: "single_company" } },
        )}
      />,
    );
    expect(screen.getByRole("status").textContent).toMatch(/Subscription not configured/);
    expect(remaining()).toBe("—");
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.getAllByText("Not configured").length).toBeGreaterThan(0);
    // No fabricated values or controls.
    expect(screen.queryByRole("button")).toBeNull();
    expect(document.body.textContent).not.toMatch(/\d{4}/); // no dates rendered
  });

  it("never fabricates a renewal date", () => {
    render(<DashboardView data={data({})} />);
    expect(screen.getByText("No renewal recorded")).toBeTruthy();
  });

  it("shows the recorded renewal date when one exists", () => {
    render(<DashboardView data={data({ last_renewed_on: "2026-03-15" })} />);
    expect(screen.getByText("15/03/2026")).toBeTruthy();
  });

  it.each([
    [{ status: "not_found", count: 0, full_name: null, email: null, is_active: null }, /No Company Admin account exists/],
    [{ status: "multiple", count: 2, full_name: null, email: null, is_active: null }, /2 Company Admin accounts; no primary contact designated/],
    [{ ...contact, is_active: false }, /Inactive/],
  ] as [CompanyAdminContact, RegExp][])("handles Company Admin contact state %#", (c, text) => {
    render(<DashboardView data={data({}, { company_admin: c })} />);
    const card = screen.getByRole("region", { name: "Company Account" });
    expect(within(card).getByText(text)).toBeTruthy();
    expect(within(card).queryByRole("button")).toBeNull(); // read-only
  });

  it("labels every card region for assistive technology", () => {
    render(<DashboardView data={data({})} />);
    for (const name of ["Remaining Days", "Subscription Status", "Company Account", "Subscription Period", "Subscription Information"]) {
      expect(screen.getByRole("region", { name })).toBeTruthy();
    }
  });
});

describe("dashboard loading and error states", () => {
  it("announces errors", () => {
    render(<DashboardError />);
    expect(screen.getByRole("alert").textContent).toMatch(/Dashboard unavailable/);
  });

  it("marks the skeleton as busy", () => {
    render(<DashboardSkeleton />);
    expect(screen.getByLabelText("Loading dashboard").getAttribute("aria-busy")).toBe("true");
  });
});

describe("formatDate", () => {
  it("formats calendar dates without time-zone drift", () => {
    expect(formatDate("2026-01-01")).toBe("01/01/2026");
    expect(formatDate("2026-12-31")).toBe("31/12/2026");
    expect(formatDate(null)).toBe("—");
    expect(formatDate("not-a-date")).toBe("—");
  });
});
