import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { navFor } from "@/components/company/nav-items";
import type { ShopAbilities } from "@/components/company/shops/shop-form-dialog";
import { tokenProblem, validateShop } from "@/components/company/shops/shop-validation";
import { shopsPath, ShopsView } from "@/components/company/shops/shops-view";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { Shop, ShopPage } from "@/lib/api/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/company/shops",
}));
vi.mock("@/lib/api/client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/client")>()),
  apiFetch: vi.fn(),
}));
const mockedFetch = vi.mocked(apiFetch);
beforeEach(() => mockedFetch.mockReset());
afterEach(cleanup);

const FULL: ShopAbilities = { create: true, edit: true, toggle: true, manageToken: true };
const VIEW_ONLY: ShopAbilities = { create: false, edit: false, toggle: false, manageToken: false };

function shop(overrides: Partial<Shop> = {}): Shop {
  return {
    id: crypto.randomUUID(), name: "Main Store", branch_name: "Gulberg", code: "LHR-01", pos_id: "000123",
    status: "active", fbr_token_status: "configured", fbr_token_updated_at: "2026-11-06T05:00:00Z",
    version: 1, created_at: "2026-11-06T05:00:00Z", updated_at: "2026-11-06T05:00:00Z", ...overrides,
  };
}

function page(items: Shop[], total = items.length): ShopPage {
  const active = items.filter((s) => s.status === "active").length;
  return {
    items,
    total,
    limit: 10,
    offset: 0,
    summary: { total, active, inactive: total - active },
    allowance: { mode: "unlimited", max_shops: null, registered_shops: total, available_slots: null, at_capacity: false, over_limit: false },
  };
}

function renderView(data = page([shop()]), can = FULL) {
  return render(<ShopsView initial={data} can={can} />);
}

describe("Shop Management", () => {
  it("shows real summary counts and the shop table", () => {
    renderView(page([shop(), shop({ name: "Old Branch", code: "OLD", pos_id: "9", status: "inactive", fbr_token_status: "not_configured" })]));
    expect(screen.getByTestId("shops-total-shops-value").textContent).toBe("2");
    expect(screen.getByTestId("shops-active-shops-value").textContent).toBe("1");
    expect(screen.getByTestId("shops-inactive-shops-value").textContent).toBe("1");
    const table = screen.getByRole("table", { name: "Shops" });
    expect(within(table).getByText("000123")).toBeTruthy(); // leading zeros kept
    expect(within(table).getByText("Token configured")).toBeTruthy();
    expect(within(table).getByText("Token not configured")).toBeTruthy();
    expect(within(table).getByRole("button", { name: "Reactivate Old Branch" })).toBeTruthy();
  });

  it("shows the empty state", () => {
    renderView(page([]));
    expect(screen.getByText("No shops yet.")).toBeTruthy();
    expect(screen.getByText(/Add your first shop/)).toBeTruthy();
  });

  it("hides actions the role does not allow", () => {
    renderView(page([shop()]), VIEW_ONLY);
    expect(screen.queryByRole("button", { name: "Add Shop" })).toBeNull();
    const table = screen.getByRole("table", { name: "Shops" });
    expect(within(table).queryByRole("button", { name: /Deactivate/ })).toBeNull();
    expect(within(table).getByRole("button", { name: "View Main Store" })).toBeTruthy();
  });

  it("searches, filters, sorts and paginates through the API", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 10 }, (_, i) => shop({ name: `S${i}`, code: `C${i}`, pos_id: `${i}` }));
    mockedFetch.mockResolvedValue({ ...page(many, 14), offset: 10 });
    renderView(page(many, 14));
    expect(screen.getByText("1–10 of 14")).toBeTruthy();
    await user.type(screen.getByLabelText(/Search by shop name/), "lhr");
    await waitFor(() => expect(String(mockedFetch.mock.calls.at(-1)![0])).toContain("search=lhr"));
    await user.selectOptions(screen.getByLabelText("Status"), "inactive");
    await waitFor(() => expect(String(mockedFetch.mock.calls.at(-1)![0])).toContain("status=inactive"));
    await user.click(screen.getByRole("button", { name: "POS ID" }));
    await waitFor(() => expect(String(mockedFetch.mock.calls.at(-1)![0])).toContain("sort=pos_id"));
  });

  it("adds a shop with an optional token and never echoes it", async () => {
    const user = userEvent.setup();
    const created = shop({ name: "New Shop", code: "NEW-1", pos_id: "007" });
    mockedFetch.mockImplementation(async (path, init) => (init?.method === "POST" ? created : page([created])));
    renderView(page([]));
    await user.click(screen.getByRole("button", { name: "Add Shop" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Shop Name"), "  New   Shop ");
    await user.type(within(dialog).getByLabelText("Branch Name"), "DHA");
    await user.type(within(dialog).getByLabelText("Shop Code"), "NEW-1");
    await user.type(within(dialog).getByLabelText("POS ID"), "007");
    const tokenField = within(dialog).getByLabelText("FBR Token (optional)") as HTMLInputElement;
    expect(tokenField.type).toBe("text"); // masked with CSS, never a password field
    expect(tokenField.dataset.masked).toBe("true");
    await user.type(tokenField, "QA-DUMMY-TOKEN-123");
    await user.click(within(dialog).getByRole("button", { name: "Add shop" }));
    await waitFor(() => expect(screen.getByText("New Shop was added.")).toBeTruthy());
    const post = mockedFetch.mock.calls.find((c) => c[1]?.method === "POST")!;
    expect(JSON.parse(String(post[1]?.body))).toEqual({
      name: "New Shop", branch_name: "DHA", code: "NEW-1", pos_id: "007", fbr_token: "QA-DUMMY-TOKEN-123",
    });
    expect(document.body.textContent).not.toContain("QA-DUMMY-TOKEN-123");
  });

  it("does not offer the token field without the integration permission", async () => {
    const user = userEvent.setup();
    renderView(page([]), { ...FULL, manageToken: false });
    await user.click(screen.getByRole("button", { name: "Add Shop" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByLabelText(/FBR Token/)).toBeNull();
    expect(within(dialog).getByText(/Manage FBR token permission/)).toBeTruthy();
  });

  it("shows field errors locally and duplicate-code errors from the server", async () => {
    const user = userEvent.setup();
    mockedFetch.mockRejectedValueOnce(new ApiError(409, "shop_code_taken", "Another shop already uses this Shop Code."));
    renderView(page([]));
    await user.click(screen.getByRole("button", { name: "Add Shop" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Add shop" }));
    expect(within(dialog).getByText("Enter the shop name.")).toBeTruthy();
    expect(mockedFetch).not.toHaveBeenCalled();
    await user.type(within(dialog).getByLabelText("Shop Name"), "Dup");
    await user.type(within(dialog).getByLabelText("Branch Name"), "B");
    await user.type(within(dialog).getByLabelText("Shop Code"), "LHR-01");
    await user.type(within(dialog).getByLabelText("POS ID"), "1");
    await user.click(within(dialog).getByRole("button", { name: "Add shop" }));
    expect(await within(dialog).findByText("Another shop already uses this Shop Code.")).toBeTruthy();
  });

  it("edits with the version and keeps the token blank by default", async () => {
    const user = userEvent.setup();
    const s = shop();
    mockedFetch.mockImplementation(async (path, init) => (init?.method === "PATCH" ? { ...s, name: "Flagship", version: 2 } : page([s])));
    renderView(page([s]));
    await user.click(within(screen.getByRole("table", { name: "Shops" })).getByRole("button", { name: "Edit Main Store" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Token configured")).toBeTruthy();
    expect((within(dialog).getByLabelText("Replacement FBR token") as HTMLInputElement).value).toBe("");
    expect(within(dialog).getByRole("button", { name: "Replace token" })).toHaveProperty("disabled", true);
    const name = within(dialog).getByLabelText("Shop Name");
    await user.clear(name);
    await user.type(name, "Flagship");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(mockedFetch.mock.calls.some((c) => c[1]?.method === "PATCH")).toBe(true));
    const patch = mockedFetch.mock.calls.find((c) => c[1]?.method === "PATCH")!;
    const sent = JSON.parse(String(patch[1]?.body));
    expect(sent).toMatchObject({ expected_version: 1, name: "Flagship" });
    expect(sent).not.toHaveProperty("fbr_token");
  });

  it("replaces the token only through the explicit token action", async () => {
    const user = userEvent.setup();
    const s = shop();
    mockedFetch.mockImplementation(async (path, init) => (init?.method === "PUT" ? { ...s, version: 2 } : page([s])));
    renderView(page([s]));
    await user.click(within(screen.getByRole("table", { name: "Shops" })).getByRole("button", { name: "Edit Main Store" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Replacement FBR token"), "QA-NEW-DUMMY-TOKEN");
    await user.click(within(dialog).getByRole("button", { name: "Replace token" }));
    expect(await within(dialog).findByText("FBR token replaced.")).toBeTruthy();
    const put = mockedFetch.mock.calls.find((c) => c[1]?.method === "PUT")!;
    expect(put[0]).toBe(`/company/shops/${s.id}/fbr-token`);
    expect(JSON.parse(String(put[1]?.body))).toEqual({ fbr_token: "QA-NEW-DUMMY-TOKEN", expected_version: 1 });
    expect((within(dialog).getByLabelText("Replacement FBR token") as HTMLInputElement).value).toBe("");
  });

  it("offers a reload when the form is stale", async () => {
    const user = userEvent.setup();
    mockedFetch.mockRejectedValueOnce(new ApiError(409, "stale_shop", "This shop was changed after the form was opened."));
    renderView();
    await user.click(within(screen.getByRole("table", { name: "Shops" })).getByRole("button", { name: "Edit Main Store" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Branch Name"), " East");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(await within(dialog).findByText("This shop was changed after the form was opened.")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Reload shops" })).toBeTruthy();
  });

  it("deactivates after confirmation", async () => {
    const user = userEvent.setup();
    const s = shop();
    mockedFetch.mockImplementation(async (path) =>
      String(path).endsWith("/deactivate") ? { ...s, status: "inactive", version: 2 } : page([{ ...s, status: "inactive" }]));
    renderView(page([s]));
    await user.click(within(screen.getByRole("table", { name: "Shops" })).getByRole("button", { name: "Deactivate Main Store" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Nothing is deleted/)).toBeTruthy();
    await user.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(screen.getByText("Main Store was deactivated.")).toBeTruthy());
    const call = mockedFetch.mock.calls.find((c) => String(c[0]).endsWith("/deactivate"))!;
    expect(JSON.parse(String(call[1]?.body))).toEqual({ expected_version: 1 });
  });

  it("shows a load error with retry", async () => {
    const user = userEvent.setup();
    mockedFetch.mockRejectedValueOnce(new ApiError(503, "service_unavailable", "Service unavailable."));
    renderView();
    await user.click(screen.getByRole("button", { name: /Refresh/ }));
    expect(await screen.findByText("Service unavailable.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });

  it("renders a card list for small screens", () => {
    renderView();
    expect(screen.getByRole("list", { name: "Shops" })).toBeTruthy();
  });
});

describe("helpers and navigation", () => {
  it("validates like the backend", () => {
    expect(validateShop({ name: " ", branch_name: "B", code: "ok", pos_id: "1" }).name).toBeTruthy();
    expect(validateShop({ name: "A", branch_name: "B", code: "bad code", pos_id: "1" }).code).toBeTruthy();
    expect(validateShop({ name: "A", branch_name: "B", code: "ok", pos_id: "0012" })).toEqual({});
    expect(tokenProblem("short")).toBeTruthy();
    expect(tokenProblem("has space inside")).toBeTruthy();
    expect(tokenProblem("QA-DUMMY-TOKEN")).toBeNull();
    expect(shopsPath({ search: " x ", status: "active", sort: "code", order: "desc", offset: 10 }))
      .toBe("/company/shops?limit=10&offset=10&sort=code&order=desc&search=x&status=active");
  });

  it("shows Shops only with the view permission", () => {
    expect(navFor("company_user", ["dashboard.view"]).map((i) => i.key)).toEqual(["dashboard"]);
    expect(navFor("company_user", ["dashboard.view", "shops.view"]).map((i) => i.key)).toEqual(["dashboard", "shops"]);
    expect(navFor("super_admin", ["shops.view"])).toEqual([]);
  });
});
