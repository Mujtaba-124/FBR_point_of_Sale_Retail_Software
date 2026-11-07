import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Store } from "lucide-react";

import { CompanyMobileNav } from "@/components/company/mobile-nav";
import { COMPANY_NAV, navFor } from "@/components/company/nav-items";
import { CompanySidebarNav } from "@/components/company/sidebar-nav";
import {
  CompanyDashboardSkeleton,
  CompanyDashboardView,
  SummaryCard,
} from "@/components/company/dashboard-view";
import { ProfileCard } from "@/components/super-admin/sidebar-profile";
import type { CompanyDashboard } from "@/lib/api/types";
import { signOut } from "@/lib/auth";
import { hardNavigate } from "@/lib/navigation";

const pathname = vi.hoisted(() => ({ value: "/company" }));
vi.mock("next/navigation", () => ({
  usePathname: () => pathname.value,
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }),
  redirect: vi.fn(),
}));
vi.mock("next/headers", () => ({ headers: vi.fn() }));
vi.mock("@/lib/auth", () => ({ signOut: vi.fn() }));
vi.mock("@/lib/navigation", () => ({ hardNavigate: vi.fn() }));

beforeEach(() => {
  pathname.value = "/company";
  vi.mocked(signOut).mockReset();
  vi.mocked(hardNavigate).mockReset();
});
afterEach(cleanup);

const ADMIN_PERMS = COMPANY_NAV.map((i) => i.permission);

const UNAVAILABLE = (reason: string) => ({
  available: false,
  value: null,
  unavailable_reason: reason,
});

function dashboard(activeUsers: number | null = 3): CompanyDashboard {
  return {
    company: { name: "Cheena" },
    metrics: {
      total_shops: { available: true, value: 4, unavailable_reason: null },
      active_shops: { available: true, value: 3, unavailable_reason: null },
      active_users:
        activeUsers === null
          ? UNAVAILABLE("x")
          : { available: true, value: activeUsers, unavailable_reason: null },
      pending_approvals: UNAVAILABLE("approval_workflow_not_available"),
      pending_fbr_sync: UNAVAILABLE("fbr_sync_not_available"),
    },
    sales_overview: { available: true, unavailable_reason: null, uploads: 0, records: 0, total_amount: "0", total_sales_tax: "0", total_net_amount: "0", status_note: "Draft uploads: not yet approved or sent to FBR." },
    recent_uploads: { available: true, unavailable_reason: null, items: [] },
    shop_allowance: { mode: "unlimited", max_shops: null, registered_shops: 4, available_slots: null, at_capacity: false, over_limit: false },
    context: { scope: "all", shop: null }, metric_scopes: { total_shops: "company", active_users: "company" },
  };
}

describe("Company sidebar", () => {
  it("links the built modules and shows unfinished ones as disabled for a Company Admin", () => {
    render(<CompanySidebarNav role="company_admin" permissions={ADMIN_PERMS} />);
    const nav = screen.getByRole("navigation", { name: "Company Workspace" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/company",
      "/company/users",
      "/company/roles",
      "/company/shops",
      "/company/uploads", // Excel Uploads (Phase 4)
    ]);
    for (const label of ["Approvals", "FBR Sync", "Reports"]) {
      const entry = within(nav).getByText(label).closest("[aria-disabled]");
      expect(entry?.getAttribute("aria-disabled")).toBe("true");
      expect(entry?.tagName).not.toBe("A");
    }
    expect(within(nav).getAllByText(/not available yet/)).toHaveLength(3);
  });

  it("marks Dashboard as the current page", () => {
    render(<CompanySidebarNav role="company_admin" permissions={ADMIN_PERMS} />);
    expect(screen.getByRole("link", { name: "Dashboard" }).getAttribute("aria-current")).toBe(
      "page",
    );
  });

  it("hides modules a Company User has no rights to", () => {
    render(<CompanySidebarNav role="company_user" permissions={["dashboard.view"]} />);
    const nav = screen.getByRole("navigation", { name: "Company Workspace" });
    expect(nav.textContent).toMatch(/Dashboard/);
    expect(nav.textContent).not.toMatch(/User Management|Shops|Excel|Approvals|FBR|Reports/);
    expect(navFor("company_user", ["dashboard.view"]).map((i) => i.key)).toEqual(["dashboard"]);
  });

  it("never exposes Super Admin areas or routes for unfinished modules", () => {
    render(<CompanySidebarNav role="company_admin" permissions={ADMIN_PERMS} />);
    const text = screen.getByRole("navigation").textContent ?? "";
    expect(text).not.toMatch(/Subscription|Email Settings|SMTP|Super Admin/);
    expect(COMPANY_NAV.filter((i) => i.href).map((i) => i.href)).toEqual([
      "/company",
      "/company/users",
      "/company/roles",
      "/company/shops",
      "/company/uploads",
    ]);
    expect(navFor("super_admin", ADMIN_PERMS)).toEqual([]);
  });

  it("opens the mobile drawer and closes it after choosing Dashboard", async () => {
    const user = userEvent.setup();
    render(<CompanyMobileNav role="company_admin" permissions={ADMIN_PERMS} profile={<p>profile slot</p>} />);
    await user.click(screen.getByRole("button", { name: "Open navigation menu" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toMatch(/profile slot/);
    const link = within(dialog).getByRole("link", { name: "Dashboard" });
    link.addEventListener("click", (e) => e.preventDefault());
    await user.click(link);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("closes the drawer with Escape", async () => {
    const user = userEvent.setup();
    render(<CompanyMobileNav role="company_admin" permissions={ADMIN_PERMS} profile={null} />);
    await user.click(screen.getByRole("button", { name: "Open navigation menu" }));
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("signs out through the existing flow", async () => {
    vi.mocked(signOut).mockResolvedValue(undefined);
    render(<ProfileCard name="Company Admin Person" email="admin@example.test" />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(hardNavigate).toHaveBeenCalledWith("/login"));
  });
});

describe("Company dashboard", () => {
  it("shows the real Active Users count", () => {
    render(<CompanyDashboardView data={dashboard(3)} />);
    const card = screen.getByRole("region", { name: "Active Users" });
    expect(within(card).getByText("3")).toBeTruthy();
    expect(within(card).queryByText("Not available yet")).toBeNull();
  });

  it("shows a genuine zero as zero", () => {
    render(<CompanyDashboardView data={dashboard(0)} />);
    const card = screen.getByRole("region", { name: "Active Users" });
    expect(within(card).getByTestId("metric-active-users-value").textContent).toBe("0");
  });

  it("never shows zero for modules that do not exist yet", () => {
    render(<CompanyDashboardView data={dashboard()} />);
    for (const name of ["Pending Approvals", "Pending FBR Sync"]) {
      const card = screen.getByRole("region", { name });
      const value = within(card).getByTestId(/-value$/);
      expect(value.textContent).toMatch(/^—/);
      expect(value.textContent).not.toMatch(/0/);
      expect(within(card).getByText("Not available yet")).toBeTruthy();
    }
  });

  it("shows real (here zero) sales totals, labelled as Draft", () => {
    render(<CompanyDashboardView data={dashboard()} />);
    const sales = screen.getByRole("region", { name: "Sales Overview" });
    for (const label of ["Total Sales Amount", "Sales Tax Amount", "Net Sales Amount", "Uploaded Invoices"]) {
      expect(within(sales).getByText(label)).toBeTruthy();
    }
    expect(within(sales).getByTestId("sales-net-sales-amount").textContent).toBe("0.00");
    expect(within(sales).getByText("Draft")).toBeTruthy();
    expect(within(sales).getByText(/No sales files have been uploaded/)).toBeTruthy();
  });

  it("shows saved upload totals and recent uploads", () => {
    const data = dashboard();
    data.sales_overview = { ...data.sales_overview, uploads: 2, records: 3, total_amount: "6000", total_sales_tax: "1080", total_net_amount: "7080" };
    data.recent_uploads = {
      available: true,
      unavailable_reason: null,
      items: [{ id: "b1", sales_date: "2026-11-06", shop_name: "Main", shop_code: "CH-001", total_records: 3, total_net_amount: "7080.00", status: "draft", uploaded_at: "2026-11-07T05:00:00Z" }],
    };
    render(<CompanyDashboardView data={data} />);
    const sales = screen.getByRole("region", { name: "Sales Overview" });
    expect(within(sales).getByTestId("sales-net-sales-amount").textContent).toBe("7,080.00");
    expect(within(sales).getByTestId("sales-uploaded-invoices").textContent).toBe("3");
    expect(within(sales).getByText(/not yet approved or sent to FBR/)).toBeTruthy();
    const recent = screen.getByRole("region", { name: "Recent Excel Uploads" });
    expect(within(recent).getByRole("link").getAttribute("href")).toBe("/company/uploads/b1");
    expect(recent.textContent).toContain("06/11/2026");
  });

  it("shows the empty upload activity", () => {
    render(<CompanyDashboardView data={dashboard()} />);
    const uploads = screen.getByRole("region", { name: "Recent Excel Uploads" });
    expect(within(uploads).getByText("No Excel uploads yet.")).toBeTruthy();
    expect(within(uploads).queryByRole("table")).toBeNull();
  });

  it("links built modules and disables unfinished quick actions", async () => {
    render(<CompanyDashboardView data={dashboard()} />);
    const actions = screen.getByRole("region", { name: "Quick Actions" });
    const links = within(actions).getAllByRole("link");
    expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Manage Shops", "/company/shops"],
      ["Manage Users", "/company/users"],
      ["Upload Excel", "/company/uploads"],
    ]);
    const buttons = within(actions).getAllByRole("button");
    expect(buttons.map((b) => b.textContent?.replace("Soon", "").trim())).toEqual(["View Reports"]);
    for (const b of buttons) expect((b as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the real Total Shops count with active and inactive", () => {
    render(<CompanyDashboardView data={dashboard()} />);
    const card = screen.getByRole("region", { name: "Total Shops" });
    expect(within(card).getByTestId("metric-total-shops-value").textContent).toBe("4");
    expect(within(card).getByText("3 active · 1 inactive")).toBeTruthy();
    expect(within(card).queryByText("Not available yet")).toBeNull();
  });

  it("uses semantic headings and shows the company name", () => {
    render(<CompanyDashboardView data={dashboard()} />);
    expect(screen.getAllByRole("heading", { level: 2 }).length).toBeGreaterThanOrEqual(7);
    expect(screen.getByText("Cheena")).toBeTruthy();
  });

  it("renders an accessible loading skeleton", () => {
    render(<CompanyDashboardSkeleton />);
    expect(screen.getByLabelText("Loading dashboard").getAttribute("aria-busy")).toBe("true");
  });

  it("summary card handles an unavailable metric without a value", () => {
    render(
      <SummaryCard
        icon={Store}
        label="Example"
        metric={{ available: false, value: null, unavailable_reason: "x" }}
        pendingNote="Coming later."
      />,
    );
    expect(screen.getByText("Coming later.")).toBeTruthy();
    expect(screen.getByTestId("metric-example-value").textContent).toContain("not available yet");
  });
});
