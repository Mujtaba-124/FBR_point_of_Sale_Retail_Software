import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CompanyDashboardView } from "@/components/company/dashboard-view";
import { ShopContextNoticeBar } from "@/components/company/shop-context/shop-context-notice";
import { ShopContextProvider } from "@/components/company/shop-context/shop-context-provider";
import { ShopSelector } from "@/components/company/shop-context/shop-selector";
import { isShopAwarePath, withShop } from "@/components/company/shop-context/paths";
import { CompanySidebarNav } from "@/components/company/sidebar-nav";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { CompanyDashboard, ShopOption, ShopOptions } from "@/lib/api/types";

const nav = vi.hoisted(() => ({
  pathname: "/company",
  search: new URLSearchParams(),
  push: vi.fn(),
  replace: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useSearchParams: () => nav.search,
  useRouter: () => ({ push: nav.push, replace: nav.replace, refresh: vi.fn() }),
}));
vi.mock("@/lib/api/client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/client")>()),
  apiFetch: vi.fn(),
}));
const mockedFetch = vi.mocked(apiFetch);

const A: ShopOption = { id: "11111111-1111-4111-8111-111111111111", name: "Cheena Main Shop", code: "CH-001" };
const B: ShopOption = { id: "22222222-2222-4222-8222-222222222222", name: "Cheena Main Shop", code: "CH-002" };

function options(items: ShopOption[], selection: ShopOptions["selection"] = { status: "all", shop: null }): ShopOptions {
  return { items, total: items.length, truncated: false, selection, access: { mode: "company", all_label: "All Shops" } };
}

function at(pathname: string, shop?: string) {
  nav.pathname = pathname;
  nav.search = new URLSearchParams(shop ? { shop } : {});
}

beforeEach(() => {
  at("/company");
  nav.push.mockReset();
  nav.replace.mockReset();
  mockedFetch.mockReset();
  mockedFetch.mockResolvedValue(options([A, B]));
});
afterEach(cleanup);

function Workspace({ enabled = true }: { enabled?: boolean }) {
  return (
    <ShopContextProvider enabled={enabled}>
      <ShopSelector />
      <ShopContextNoticeBar />
      <CompanySidebarNav role="company_admin" permissions={["dashboard.view", "users.view", "shops.view"]} />
    </ShopContextProvider>
  );
}

const trigger = () => within(screen.getByTestId("shop-selector")).getByRole("button");

describe("Shop selector", () => {
  it("defaults to All Shops and asks the server for active options", async () => {
    render(<Workspace />);
    await waitFor(() => expect(mockedFetch).toHaveBeenCalledWith("/company/shop-options?"));
    expect(trigger().textContent).toContain("All Shops");
    expect(trigger().textContent).toContain("Consolidated view");
    expect(trigger().getAttribute("aria-haspopup")).toBe("listbox");
  });

  it("says it is loading, not All Shops, before the server answers", async () => {
    let answer: (value: ShopOptions) => void = () => {};
    mockedFetch.mockReturnValue(new Promise<ShopOptions>((resolve) => (answer = resolve)));
    render(<Workspace />);
    expect(trigger().textContent).toContain("Loading shops…");
    expect(trigger().textContent).not.toContain("All Shops");
    await act(async () => answer({ ...options([A]), access: { mode: "selected", all_label: "All Assigned Shops" } }));
    expect(trigger().textContent).toContain("All Assigned Shops");
    expect(trigger().textContent).toContain("Your assigned shops");
  });

  it("never shows a failed load as All Shops", async () => {
    mockedFetch.mockRejectedValue(new ApiError(503, "unavailable", "Service unavailable"));
    render(<Workspace />);
    await waitFor(() => expect(trigger().textContent).toContain("Shops unavailable"));
    expect(trigger().textContent).not.toContain("All Shops");
  });

  it("lists All Shops first, then shops by name and code, without POS IDs", async () => {
    const user = userEvent.setup();
    render(<Workspace />);
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    await user.click(trigger());
    const list = await screen.findByRole("listbox", { name: "Shops" });
    const rows = within(list).getAllByRole("option").map((o) => o.textContent);
    expect(rows).toEqual([
      "All ShopsConsolidated company view",
      "Cheena Main ShopCH-001",
      "Cheena Main ShopCH-002", // identical names are told apart by the code
    ]);
    expect(within(list).getAllByRole("option")[0].getAttribute("aria-selected")).toBe("true");
  });

  it("selects a shop through the URL and back to All Shops", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Workspace />);
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    await user.click(trigger());
    await user.click(await screen.findByRole("option", { name: /CH-002/ }));
    expect(nav.push).toHaveBeenCalledWith(`/company?shop=${B.id}`);

    at("/company", B.id);
    mockedFetch.mockResolvedValue(options([A, B], { status: "active", shop: B }));
    rerender(<Workspace />);
    await waitFor(() => expect(trigger().textContent).toContain("CH-002"));
    await user.click(trigger());
    await user.click(await screen.findByRole("option", { name: /All Shops/ }));
    expect(nav.push).toHaveBeenLastCalledWith("/company");
  });

  it("is searchable and keyboard operable", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 40 }, (_, i) => ({ id: `id-${i}`, name: `Branch Store ${i}`, code: `BS-${i}` }));
    mockedFetch.mockResolvedValue(options([A, ...many]));
    render(<Workspace />);
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    trigger().focus();
    await user.keyboard("{Enter}");
    const search = await screen.findByRole("combobox", { name: /Find a shop/ });
    await waitFor(() => expect(document.activeElement).toBe(search));
    await user.type(search, "ch-001");
    expect(screen.getAllByRole("option")).toHaveLength(1);
    await user.keyboard("{Enter}");
    expect(nav.push).toHaveBeenCalledWith(`/company?shop=${A.id}`);
  });

  it("shows the latest name for the selected shop ID (rename)", async () => {
    at("/company", A.id);
    const renamed = { ...A, name: "Renamed Flagship" };
    mockedFetch.mockResolvedValue(options([renamed, B], { status: "active", shop: renamed }));
    render(<Workspace />);
    await waitFor(() => expect(trigger().textContent).toContain("Renamed Flagship"));
    expect(mockedFetch).toHaveBeenCalledWith(`/company/shop-options?selected=${A.id}`);
  });

  it.each([
    ["inactive", "no longer active"],
    ["not_found", "no longer available"],
    ["invalid", "not valid"],
  ] as const)("falls back to All Shops when the selection is %s", async (status, message) => {
    at("/company", A.id);
    mockedFetch.mockResolvedValue(options([B], { status, shop: null }));
    render(<Workspace />);
    expect(await screen.findByRole("status")).toHaveProperty("textContent", expect.stringContaining(message));
    expect(nav.replace).toHaveBeenCalledWith("/company"); // never another shop
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("is read-only on company-wide pages and keeps the selection for links back", async () => {
    at("/company", A.id);
    mockedFetch.mockResolvedValue(options([A, B], { status: "active", shop: A }));
    const { rerender } = render(<Workspace />);
    await waitFor(() => expect(trigger().textContent).toContain("CH-001"));

    at("/company/users");
    rerender(<Workspace />);
    expect(trigger()).toHaveProperty("disabled", true);
    expect(trigger().textContent).toContain("Company-wide page");
    expect(screen.getByText(/always cover the whole company/)).toBeTruthy();
    const links = within(screen.getByRole("navigation", { name: "Company Workspace" })).getAllByRole("link");
    const hrefs = Object.fromEntries(links.map((a) => [a.textContent, a.getAttribute("href")]));
    expect(hrefs["Dashboard"]).toBe(`/company?shop=${A.id}`);
    expect(hrefs["User Management"]).toBe("/company/users"); // never filtered
    expect(hrefs["Shops"]).toBe("/company/shops");
  });

  it("is absent for accounts without a shop context", async () => {
    render(<Workspace enabled={false} />);
    expect(screen.queryByTestId("shop-selector")).toBeNull();
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("disappears when the role no longer allows a shop context", async () => {
    at("/company", A.id);
    mockedFetch.mockRejectedValueOnce(new ApiError(403, "permission_denied", "No."));
    render(<Workspace />);
    expect(await screen.findByText(/no longer available for your account/)).toBeTruthy();
    expect(screen.queryByTestId("shop-selector")).toBeNull();
    expect(nav.replace).toHaveBeenCalledWith("/company");
  });

  it("shows an honest empty state", async () => {
    const user = userEvent.setup();
    mockedFetch.mockResolvedValue(options([]));
    render(<Workspace />);
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    await user.click(trigger());
    expect(await screen.findByText(/No active shops yet/)).toBeTruthy();
    expect(screen.getAllByRole("option")).toHaveLength(1); // All Shops only
  });

  it("shows a load error with retry, while All Shops still works", async () => {
    const user = userEvent.setup();
    mockedFetch.mockRejectedValueOnce(new ApiError(503, "service_unavailable", "Down."));
    render(<Workspace />);
    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(1));
    await user.click(trigger());
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Shops could not be loaded");
    await user.click(within(alert).getByRole("button", { name: /Retry/ }));
    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("option", { name: /CH-001/ })).toBeTruthy();
  });

  it("keeps long names readable", async () => {
    const user = userEvent.setup();
    const long = { id: "long", name: "The Exceptionally Long Named Cheena Flagship Superstore And Warehouse", code: "LONG-1" };
    at("/company", long.id);
    mockedFetch.mockResolvedValue(options([long], { status: "active", shop: long }));
    render(<Workspace />);
    await waitFor(() => expect(trigger().textContent).toContain("Exceptionally"));
    expect(within(trigger()).getByTitle(long.name).className).toContain("truncate");
    await user.click(trigger());
    expect(within(await screen.findByRole("listbox")).getByTitle(long.name).className).toContain("break-words");
  });

  it("refreshes from the server when the tab becomes visible again", async () => {
    render(<Workspace />);
    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(1));
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(2));
  });
});

describe("Shop-aware paths", () => {
  it("only the dashboard follows the context today", () => {
    expect(isShopAwarePath("/company")).toBe(true);
    for (const p of ["/company/users", "/company/roles", "/company/shops"]) expect(isShopAwarePath(p)).toBe(false);
    expect(withShop("/company", "x")).toBe("/company?shop=x");
    expect(withShop("/company/shops", "x")).toBe("/company/shops");
    expect(withShop("/company", null)).toBe("/company");
  });
});

describe("Dashboard shop context", () => {
  function summary(context: CompanyDashboard["context"]): CompanyDashboard {
    const off = { available: false, value: null, unavailable_reason: "x" } as const;
    return {
      company: { name: "Cheena" },
      metrics: {
        total_shops: { available: true, value: 2, unavailable_reason: null },
        active_shops: { available: true, value: 2, unavailable_reason: null },
        active_users: { available: true, value: 3, unavailable_reason: null },
        pending_approvals: off,
        pending_fbr_sync: off,
      },
      sales_overview: { available: true, unavailable_reason: null, uploads: 0, records: 0, total_amount: "0", total_sales_tax: "0", total_net_amount: "0", status_note: "Draft uploads: not yet approved or sent to FBR." },
      recent_uploads: { available: true, unavailable_reason: null, items: [] },
      shop_allowance: { mode: "unlimited", max_shops: null, registered_shops: 2, available_slots: null, at_capacity: false, over_limit: false },
      context,
      metric_scopes: { total_shops: "company", active_shops: "company", active_users: "company", pending_approvals: "context" },
    };
  }

  it("shows All Shops without extra labels", () => {
    render(<CompanyDashboardView data={summary({ scope: "all", shop: null })} />);
    expect(screen.getByTestId("dashboard-shop-context").textContent).toContain("All Shops");
    expect(screen.queryByText("Company-wide")).toBeNull();
  });

  it("indicates the selected shop and labels company-wide figures", () => {
    render(<CompanyDashboardView data={summary({ scope: "shop", shop: B })} />);
    expect(screen.getByTestId("dashboard-shop-context").textContent).toContain("Cheena Main Shop — CH-002");
    expect(screen.getByTestId("metric-total-shops-scope").textContent).toBe("Company-wide");
    expect(screen.getByTestId("metric-active-users-scope").textContent).toBe("Company-wide");
    expect(screen.getByTestId("metric-total-shops-value").textContent).toBe("2"); // nothing invented
    expect(screen.getAllByText(/Will show CH-002 only/).length).toBe(2); // approvals + FBR sync
  });
});
