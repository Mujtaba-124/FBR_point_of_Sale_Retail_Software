import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CompanyDashboardView } from "@/components/company/dashboard-view";
import type { ShopAbilities } from "@/components/company/shops/shop-form-dialog";
import { ShopsView } from "@/components/company/shops/shops-view";
import { ShopAllowanceCard } from "@/components/super-admin/subscription/shop-allowance-card";
import { parseShopLimit, slotsLeft } from "@/components/super-admin/subscription/shop-allowance-rules";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { CompanyDashboard, Shop, ShopAllowance, ShopAllowanceSummary, ShopPage } from "@/lib/api/types";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh, push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/super-admin/subscription",
}));
vi.mock("@/lib/api/client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/client")>()),
  apiFetch: vi.fn(),
}));
const mockedFetch = vi.mocked(apiFetch);
beforeEach(() => {
  mockedFetch.mockReset();
  refresh.mockReset();
});
afterEach(cleanup);

function allowance(overrides: Partial<ShopAllowance> = {}): ShopAllowance {
  return {
    mode: "unlimited",
    max_shops: null,
    registered_shops: 2,
    available_slots: null,
    at_capacity: false,
    over_limit: false,
    version: 1,
    last_updated_at: null,
    ...overrides,
  };
}

const limited = (max: number, used: number): ShopAllowanceSummary => ({
  mode: "limited",
  max_shops: max,
  registered_shops: used,
  available_slots: Math.max(0, max - used),
  at_capacity: used >= max,
  over_limit: used > max,
});

const text = (id: string) => screen.getByTestId(id).textContent;

describe("Super Admin — Shop Allowance card", () => {
  it("shows the unlimited state with aggregate numbers only", () => {
    render(<ShopAllowanceCard initial={allowance()} />);
    expect(screen.getByRole("heading", { name: "Shop Allowance" })).toBeTruthy();
    expect(text("allowance-mode")).toBe("Unlimited");
    expect(text("allowance-max")).toBe("Unlimited Shops");
    expect(text("allowance-used")).toBe("2");
    expect(text("allowance-available")).toBe("Unlimited");
    expect(text("allowance-updated")).toBe("Not changed yet");
    const group = screen.getByRole("group", { name: "Allowance" });
    expect((within(group).getByLabelText("Unlimited Shops") as HTMLInputElement).checked).toBe(true);
    expect(screen.queryByLabelText("Maximum Shops")).toBeNull(); // no number in Unlimited mode
    expect((screen.getByRole("button", { name: "Save Changes" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows a limited allowance as usage over limit", () => {
    render(
      <ShopAllowanceCard
        initial={allowance({ ...limited(5, 2), version: 3, last_updated_at: "2026-11-06T09:00:00Z" })}
      />,
    );
    expect(text("allowance-mode")).toBe("Limited");
    expect(text("allowance-max")).toBe("5");
    expect(text("allowance-used")).toBe("2 / 5");
    expect(text("allowance-available")).toBe("3");
    expect(text("allowance-updated")).not.toBe("Not changed yet");
    expect((screen.getByLabelText("Maximum Shops") as HTMLInputElement).value).toBe("5");
  });

  it.each(["0", "-1", "2.5", "abc", "1e3", ""])("rejects the limit %j without opening the review", async (raw) => {
    const user = userEvent.setup();
    render(<ShopAllowanceCard initial={allowance()} />);
    await user.click(screen.getByLabelText("Limited Shops"));
    const input = screen.getByLabelText("Maximum Shops");
    await user.clear(input);
    if (raw) await user.type(input, raw);
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("reviews, confirms once and saves a finite allowance", async () => {
    const user = userEvent.setup();
    let resolve: (v: unknown) => void = () => {};
    mockedFetch.mockImplementationOnce(() => new Promise((r) => (resolve = r)));
    render(<ShopAllowanceCard initial={allowance()} />);
    await user.click(screen.getByLabelText("Limited Shops"));
    const input = screen.getByLabelText("Maximum Shops");
    await user.clear(input);
    await user.type(input, "10");
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Unlimited Shops")).toBeTruthy();
    expect(within(dialog).getByText("Maximum 10 shops")).toBeTruthy();
    expect(mockedFetch).not.toHaveBeenCalled(); // nothing is saved before confirming
    const confirm = within(dialog).getByRole("button", { name: "Confirm and save" });
    await user.click(confirm);
    await user.click(within(dialog).getByRole("button", { name: /Saving/ })).catch(() => {});
    expect(mockedFetch).toHaveBeenCalledTimes(1); // double submit is ignored
    const [path, init] = mockedFetch.mock.calls[0];
    expect(path).toBe("/super-admin/shop-allowance");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ mode: "limited", max_shops: 10, expected_version: 1 });
    resolve({ allowance: allowance({ ...limited(10, 2), version: 2, last_updated_at: "2026-11-06T10:00:00Z" }), changed: true });
    expect(await screen.findByText(/Shop allowance saved: Maximum 10 shops/)).toBeTruthy();
    expect(text("allowance-used")).toBe("2 / 10");
    expect(refresh).toHaveBeenCalled();
  });

  it("switches to Unlimited without sending a number", async () => {
    const user = userEvent.setup();
    mockedFetch.mockResolvedValueOnce({ allowance: allowance({ version: 4 }), changed: true });
    render(<ShopAllowanceCard initial={allowance({ ...limited(3, 3), version: 3 })} />);
    await user.click(screen.getByLabelText("Unlimited Shops"));
    expect(screen.queryByLabelText("Maximum Shops")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm and save" }));
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    expect(JSON.parse(String(mockedFetch.mock.calls[0][1]?.body))).toEqual({
      mode: "unlimited",
      max_shops: null,
      expected_version: 3,
    });
  });

  it("explains a reduction below current usage before and during review", async () => {
    const user = userEvent.setup();
    render(<ShopAllowanceCard initial={allowance({ registered_shops: 8 })} />);
    await user.click(screen.getByLabelText("Limited Shops"));
    const input = screen.getByLabelText("Maximum Shops");
    await user.clear(input);
    await user.type(input, "5");
    expect(screen.getByText(/8 shops are already registered/).textContent).toMatch(/No shop will be deactivated or deleted/);
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/below current usage/)).toBeTruthy();
    expect(within(dialog).getByText("0")).toBeTruthy(); // available after saving, never negative
  });

  it("shows the over-limit state with zero available slots", () => {
    render(<ShopAllowanceCard initial={allowance({ ...limited(5, 8), version: 2 })} />);
    expect(text("allowance-used")).toBe("8 / 5");
    expect(text("allowance-available")).toBe("0");
    expect(screen.getByText(/Over limit/)).toBeTruthy();
  });

  it("reports a stale form and reloads the latest values", async () => {
    const user = userEvent.setup();
    mockedFetch.mockRejectedValueOnce(
      new ApiError(409, "stale_shop_allowance", "The shop allowance was changed after this form was opened."),
    );
    const { rerender } = render(<ShopAllowanceCard initial={allowance()} />);
    await user.click(screen.getByLabelText("Limited Shops"));
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Confirm and save" }));
    expect(await within(dialog).findByText(/changed after this form was opened/)).toBeTruthy();
    await user.click(within(dialog).getByRole("button", { name: "Load latest values" }));
    expect(refresh).toHaveBeenCalled();
    rerender(<ShopAllowanceCard initial={allowance({ ...limited(20, 2), version: 2 })} />);
    expect(text("allowance-used")).toBe("2 / 20");
    expect((screen.getByLabelText("Maximum Shops") as HTMLInputElement).value).toBe("20");
  });

  it("validates limits like the backend", () => {
    expect(parseShopLimit("5")).toEqual({ value: 5, error: null });
    expect(parseShopLimit(" 100 ").value).toBe(100);
    for (const bad of ["0", "-3", "4.0", "1,000", "100001", "five"]) expect(parseShopLimit(bad).error).toBeTruthy();
    expect(slotsLeft(5, 8)).toBe(0);
    expect(slotsLeft(null, 8)).toBeNull();
  });
});

// --- Company Workspace ------------------------------------------------------------------

const FULL: ShopAbilities = { create: true, edit: true, toggle: true, manageToken: true };

function shop(n: number, status: Shop["status"] = "active"): Shop {
  return {
    id: `id-${n}`,
    name: `Shop ${n}`,
    branch_name: "B",
    code: `C${n}`,
    pos_id: `P${n}`,
    status,
    fbr_token_status: "not_configured",
    sales_tax_rate: "18.00",
    fbr_token_updated_at: null,
    version: 1,
    created_at: "2026-11-06T05:00:00Z",
    updated_at: "2026-11-06T05:00:00Z",
  };
}

function shopPage(items: Shop[], a: ShopAllowanceSummary): ShopPage {
  const active = items.filter((s) => s.status === "active").length;
  return {
    items,
    total: items.length,
    limit: 10,
    offset: 0,
    summary: { total: items.length, active, inactive: items.length - active },
    allowance: a,
  };
}

const UNLIMITED: ShopAllowanceSummary = {
  mode: "unlimited",
  max_shops: null,
  registered_shops: 2,
  available_slots: null,
  at_capacity: false,
  over_limit: false,
};

describe("Company Shops — allowance indicator", () => {
  it("shows limited usage and available slots", () => {
    render(<ShopsView initial={shopPage([shop(1), shop(2)], limited(5, 2))} can={FULL} />);
    expect(text("allowance-registered")).toBe("2 / 5");
    expect(text("allowance-available")).toBe("3");
    expect((screen.getByRole("button", { name: "Add Shop" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows unlimited usage", () => {
    render(<ShopsView initial={shopPage([shop(1), shop(2)], UNLIMITED)} can={FULL} />);
    expect(text("allowance-registered")).toBe("2");
    expect(text("allowance-available")).toBe("Unlimited");
  });

  it("disables Add Shop at capacity but keeps the other actions", () => {
    render(<ShopsView initial={shopPage([shop(1), shop(2, "inactive")], limited(2, 2))} can={FULL} />);
    const add = screen.getByRole("button", { name: "Add Shop" }) as HTMLButtonElement;
    expect(add.disabled).toBe(true);
    const status = screen.getByRole("status");
    expect(status.textContent).toMatch(/Shop limit reached/);
    expect(status.textContent).toMatch(/assigned by the Super Admin/);
    expect(add.getAttribute("aria-describedby")).toBe(status.id);
    const table = screen.getByRole("table", { name: "Shops" });
    expect((within(table).getByRole("button", { name: "Edit Shop 1" }) as HTMLButtonElement).disabled).toBe(false);
    expect((within(table).getByRole("button", { name: "Deactivate Shop 1" }) as HTMLButtonElement).disabled).toBe(false);
    expect((within(table).getByRole("button", { name: "Reactivate Shop 2" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByLabelText(/Maximum Shops/)).toBeNull(); // no Super Admin controls here
  });

  it("explains an over-limit allowance", () => {
    const eight = Array.from({ length: 8 }, (_, i) => shop(i + 1));
    render(<ShopsView initial={shopPage(eight, limited(5, 8))} can={FULL} />);
    expect(text("allowance-registered")).toBe("8 / 5");
    expect(text("allowance-available")).toBe("0");
    expect(screen.getByRole("status").textContent).toMatch(/above the allowance of 5\. Existing shops stay available/);
  });

  it("shows the server's limit error and refreshes the indicator", async () => {
    const user = userEvent.setup();
    const full = shopPage([shop(1), shop(2), shop(3)], limited(3, 3));
    mockedFetch.mockImplementation(async (_path, init) => {
      if (init?.method === "POST") {
        throw new ApiError(409, "shop_limit_reached", "Shop limit reached: 3 of 3 allowed shops are registered.");
      }
      return full;
    });
    render(<ShopsView initial={shopPage([shop(1), shop(2)], limited(3, 2))} can={FULL} />);
    await user.click(screen.getByRole("button", { name: "Add Shop" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Shop Name"), "Late");
    await user.type(within(dialog).getByLabelText("Branch Name"), "B");
    await user.type(within(dialog).getByLabelText("Shop Code"), "LATE");
    await user.type(within(dialog).getByLabelText("POS ID"), "9");
    await user.type(within(dialog).getByLabelText("Sales Tax %"), "18");
    await user.click(within(dialog).getByRole("button", { name: "Add shop" }));
    expect(await within(dialog).findByText(/Shop limit reached: 3 of 3/)).toBeTruthy();
    await waitFor(() => expect(text("allowance-registered")).toBe("3 / 3"));
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect((screen.getByRole("button", { name: "Add Shop" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("gives a view-only user the indicator without any create or admin control", () => {
    const viewOnly: ShopAbilities = { create: false, edit: false, toggle: false, manageToken: false };
    render(<ShopsView initial={shopPage([shop(1)], limited(1, 1))} can={viewOnly} />);
    expect(screen.queryByRole("button", { name: "Add Shop" })).toBeNull();
    expect(text("allowance-registered")).toBe("1 / 1");
    expect(screen.getByRole("status").textContent).not.toMatch(/New shops cannot be added/);
  });
});

describe("Company Dashboard — Total Shops", () => {
  function dashboard(a: ShopAllowanceSummary, total = a.registered_shops): CompanyDashboard {
    const off = { available: false, value: null, unavailable_reason: "x" } as const;
    return {
      company: { name: "Cheena" },
      metrics: {
        total_shops: { available: true, value: total, unavailable_reason: null },
        active_shops: { available: true, value: total, unavailable_reason: null },
        active_users: { available: true, value: 3, unavailable_reason: null },
        pending_approvals: off,
        pending_fbr_sync: off,
      },
      sales_overview: { available: true, unavailable_reason: null, uploads: 0, records: 0, total_amount: "0", total_sales_tax: "0", total_net_amount: "0", status_note: "Draft uploads: not yet approved or sent to FBR." },
      recent_uploads: { available: true, unavailable_reason: null, items: [] },
      shop_allowance: a,
      context: { scope: "all", shop: null }, metric_scopes: { total_shops: "company", active_users: "company" },
    };
  }

  it("shows usage against a limited allowance", () => {
    render(<CompanyDashboardView data={dashboard(limited(10, 2))} />);
    expect(text("metric-total-shops-value")).toBe("2 / 10");
    expect(text("metric-total-shops-note")).toBe("8 slots available");
    expect(text("metric-active-users-value")).toBe("3"); // other cards unchanged
  });

  it("shows the count alone when unlimited", () => {
    render(<CompanyDashboardView data={dashboard(UNLIMITED)} />);
    expect(text("metric-total-shops-value")).toBe("2");
    expect(text("metric-total-shops-note")).toBe("Unlimited shops allowed");
  });

  it("flags a full allowance", () => {
    render(<CompanyDashboardView data={dashboard(limited(5, 8))} />);
    expect(text("metric-total-shops-value")).toBe("8 / 5");
    expect(text("metric-total-shops-note")).toBe("Shop limit reached");
  });
});
