import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceGate } from "@/components/auth/workspace-gate";
import { CompanyDashboardSection } from "@/components/company/dashboard-section";
import { checkWorkspaceAccess, fetchBackendDetailed, getCurrentUser } from "@/lib/auth-server";
import type { CompanyDashboard, CurrentUser, WorkspaceResponse } from "@/lib/api/types";

const redirect = vi.hoisted(() =>
  vi.fn((path: string) => {
    throw new Error(`REDIRECT:${path}`);
  }),
);
vi.mock("next/navigation", () => ({
  redirect,
  usePathname: () => "/company",
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@/lib/auth-server", () => ({
  checkWorkspaceAccess: vi.fn(),
  fetchBackend: vi.fn(),
  fetchBackendDetailed: vi.fn(),
  getCurrentUser: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ signOut: vi.fn() }));
vi.mock("@/lib/navigation", () => ({ hardNavigate: vi.fn() }));

beforeEach(() => {
  vi.mocked(checkWorkspaceAccess).mockReset();
  vi.mocked(fetchBackendDetailed).mockReset();
  vi.mocked(getCurrentUser).mockReset();
  redirect.mockClear();
});
afterEach(cleanup);

function user(category: CurrentUser["access_category"]): CurrentUser {
  return {
    id: "u1",
    email: "person@example.test",
    full_name: "Person",
    access_category: category,
    workspace: category === "super_admin" ? "super_admin" : "company",
  };
}

async function renderGate() {
  const element = await WorkspaceGate({
    workspace: "company",
    label: "Company Workspace",
    shell: (data: WorkspaceResponse, content) => (
      <div data-testid="company-frame" data-role={data.user.access_category}>
        {content}
      </div>
    ),
    children: () => <p>dashboard content</p>,
  });
  render(<>{element}</>);
}

describe("Company Workspace access (layout gate)", () => {
  it("renders the Company frame for an authorized Company Admin", async () => {
    vi.mocked(checkWorkspaceAccess).mockResolvedValue({
      status: "ok",
      data: { workspace: "company", user: user("company_admin") },
    });
    await renderGate();
    expect(screen.getByTestId("company-frame").dataset.role).toBe("company_admin");
    expect(screen.getByText("dashboard content")).toBeTruthy();
    expect(checkWorkspaceAccess).toHaveBeenCalledWith("company");
  });

  it("redirects unauthenticated visitors to sign-in", async () => {
    vi.mocked(checkWorkspaceAccess).mockResolvedValue({ status: "unauthenticated" });
    await expect(renderGate()).rejects.toThrow("REDIRECT:/login?reason=session_expired");
  });

  it("denies a Super Admin (backend 403) without the Company frame", async () => {
    vi.mocked(checkWorkspaceAccess).mockResolvedValue({
      status: "forbidden",
      code: "permission_denied",
    });
    await renderGate();
    expect(screen.queryByTestId("company-frame")).toBeNull();
    expect(screen.queryByText("dashboard content")).toBeNull();
    expect(screen.getByRole("heading", { name: /access denied/i })).toBeTruthy();
  });

  it("keeps the existing expired-subscription screen, with no sidebar or data", async () => {
    vi.mocked(checkWorkspaceAccess).mockResolvedValue({
      status: "forbidden",
      code: "subscription_expired",
    });
    await renderGate();
    expect(screen.queryByTestId("company-frame")).toBeNull();
    expect(screen.queryByText("dashboard content")).toBeNull();
    expect(screen.getByText(/subscription has expired/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /sign out/i })).toBeTruthy();
  });

  it("shows a service message when the backend is unreachable", async () => {
    vi.mocked(checkWorkspaceAccess).mockResolvedValue({ status: "unavailable" });
    await renderGate();
    expect(screen.queryByTestId("company-frame")).toBeNull();
    expect(screen.getByText("Service temporarily unavailable")).toBeTruthy();
  });
});

const SUMMARY: CompanyDashboard = {
  company: { name: "Cheena" },
  metrics: {
    total_shops: { available: true, value: 0, unavailable_reason: null },
    active_shops: { available: true, value: 0, unavailable_reason: null },
    active_users: { available: true, value: 2, unavailable_reason: null },
    pending_approvals: { available: false, value: null, unavailable_reason: "b" },
    pending_fbr_sync: { available: false, value: null, unavailable_reason: "c" },
  },
  sales_overview: { available: false, unavailable_reason: "d" },
  recent_uploads: { available: false, unavailable_reason: "d" },
  shop_allowance: { mode: "unlimited", max_shops: null, registered_shops: 0, available_slots: null, at_capacity: false, over_limit: false },
  context: { scope: "all", shop: null }, metric_scopes: { total_shops: "company", active_users: "company" },
};

async function renderSection() {
  render(<>{await CompanyDashboardSection()}</>);
}

describe("Company dashboard data", () => {
  it("loads the summary for a Company Admin", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({ status: "ok", data: user("company_admin") });
    vi.mocked(fetchBackendDetailed).mockResolvedValue({ status: "ok", data: SUMMARY });
    await renderSection();
    expect(fetchBackendDetailed).toHaveBeenCalledWith("/api/v1/company/dashboard/summary");
    expect(screen.getByRole("region", { name: "Active Users" }).textContent).toContain("2");
  });

  it("asks for the selected shop and falls back to All Shops when it is refused", async () => {
    const id = "11111111-1111-4111-8111-111111111111";
    vi.mocked(getCurrentUser).mockResolvedValue({ status: "ok", data: user("company_admin") });
    vi.mocked(fetchBackendDetailed)
      .mockResolvedValueOnce({ status: "rejected", httpStatus: 409, code: "shop_inactive" })
      .mockResolvedValueOnce({ status: "ok", data: SUMMARY });
    render(<>{await CompanyDashboardSection({ searchParams: Promise.resolve({ shop: id }) })}</>);
    expect(vi.mocked(fetchBackendDetailed).mock.calls.map((c) => c[0])).toEqual([
      `/api/v1/company/dashboard/summary?shop_id=${id}`,
      "/api/v1/company/dashboard/summary",
    ]);
    expect(screen.getByTestId("dashboard-shop-context").textContent).toContain("All Shops");
  });

  it("does not hide other dashboard failures behind a fallback", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({ status: "ok", data: user("company_admin") });
    vi.mocked(fetchBackendDetailed).mockResolvedValueOnce({ status: "unavailable" });
    render(<>{await CompanyDashboardSection({ searchParams: Promise.resolve({ shop: "x" }) })}</>);
    expect(fetchBackendDetailed).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Dashboard unavailable")).toBeTruthy();
  });

  it("never requests admin metrics for a Company User", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({ status: "ok", data: user("company_user") });
    await renderSection();
    expect(fetchBackendDetailed).not.toHaveBeenCalled();
    expect(screen.getByText("Welcome to the Company Workspace")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Active Users" })).toBeNull();
  });

  it("shows an error state instead of zeros when the API fails", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({ status: "ok", data: user("company_admin") });
    vi.mocked(fetchBackendDetailed).mockResolvedValue({ status: "unavailable" });
    await renderSection();
    expect(screen.getByRole("alert").textContent).toMatch(/could not be loaded/);
    expect(screen.queryByText("0")).toBeNull();
  });

  it("shows access denied when the backend refuses the summary", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({ status: "ok", data: user("company_admin") });
    vi.mocked(fetchBackendDetailed).mockResolvedValue({ status: "forbidden", code: "permission_denied" });
    await renderSection();
    expect(screen.getByRole("heading", { name: "Access denied" })).toBeTruthy();
  });

  it("redirects when the session has expired", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({ status: "unauthenticated" });
    await expect(renderSection()).rejects.toThrow("REDIRECT:/login?reason=session_expired");
  });
});
