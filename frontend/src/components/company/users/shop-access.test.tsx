import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ShopContextNoticeBar } from "@/components/company/shop-context/shop-context-notice";
import { ShopContextProvider } from "@/components/company/shop-context/shop-context-provider";
import { ShopSelector } from "@/components/company/shop-context/shop-selector";
import { AddUserDialog } from "@/components/company/users/add-user-dialog";
import { EditUserDialog } from "@/components/company/users/edit-user-dialog";
import { ShopAccessBadge } from "@/components/company/users/shop-access-badge";
import { describeChange, shopAccessLabel } from "@/components/company/users/shop-access-rules";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { AssignableShop, CompanyRoleItem, CompanyUser, ShopAccessDetail, ShopOptions } from "@/lib/api/types";

const nav = vi.hoisted(() => ({ pathname: "/company", search: new URLSearchParams(), push: vi.fn(), replace: vi.fn() }));
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
afterEach(cleanup);

const CH1: AssignableShop = { id: "s-1", name: "Cheena Main Shop", code: "CH-001", status: "active" };
const CH2: AssignableShop = { id: "s-2", name: "Cheena Main Shop", code: "CH-002", status: "active" };
const OLD: AssignableShop = { id: "s-3", name: "Closed Branch", code: "OLD-1", status: "inactive" };
const SHOPS = [CH1, CH2, OLD];

const ROLE: CompanyRoleItem = {
  id: "r-user", name: "Company User", description: null, system_key: "company_user", is_system: true,
  is_active: true, permissions: ["dashboard.view"], active_users: 1, total_users: 1, version: 1,
  updated_at: "2026-11-06T00:00:00Z",
};
const CLERK: CompanyRoleItem = { ...ROLE, id: "r-clerk", name: "Clerk", system_key: null, is_system: false };

function person(overrides: Partial<CompanyUser> = {}): CompanyUser {
  return {
    id: "u-1", full_name: "Hamza", email: "hamza@example.test", tier: "company_user", is_protected: false,
    status: "active", role: { id: "r-user", name: "Company User", is_system: true, is_active: true },
    setup_pending: false, setup_link_expires_at: null, last_login_at: null, created_at: "2026-11-06T00:00:00Z",
    shop_access: { mode: "none", shop_count: null }, ...overrides,
  };
}

function detail(overrides: Partial<ShopAccessDetail> = {}): ShopAccessDetail {
  return { mode: "selected", shop_count: 1, shops: [CH1], editable: true, version: 3, updated_at: null, ...overrides };
}

/** Routes the mocked API by path. */
function backend(handlers: { access?: () => unknown; save?: (body: unknown) => unknown; create?: (body: unknown) => unknown } = {}) {
  mockedFetch.mockImplementation(async (path, init) => {
    const p = String(path);
    if (p === "/company/shop-assignment-options") return { items: SHOPS, total: SHOPS.length };
    if (p.endsWith("/shop-access") && init?.method === "PUT") return handlers.save?.(JSON.parse(String(init.body)));
    if (p.endsWith("/shop-access")) return handlers.access?.() ?? detail();
    if (p === "/company/users" && init?.method === "POST") return handlers.create?.(JSON.parse(String(init.body)));
    if (p.startsWith("/company/users/") && init?.method === "PATCH") return person({ full_name: "Renamed" });
    throw new Error(`unexpected ${p}`);
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
  nav.pathname = "/company";
  nav.search = new URLSearchParams();
});

function created(body: { shop_access: { mode: string } }) {
  return {
    user: person({ shop_access: { mode: body.shop_access.mode as "none", shop_count: null } }),
    setup_token: "tok", setup_expires_at: "2026-11-09T00:00:00Z",
    capacity: { active: 2, limit: 15, available: 13, inactive: 0 },
  };
}

async function fillNewUser(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Full name"), "Hamza");
  await user.type(screen.getByLabelText("Email address"), "hamza@example.test");
}

describe("Add User — Shop Access", () => {
  it("defaults to No Shop Access", async () => {
    const user = userEvent.setup();
    const sent: unknown[] = [];
    backend({ create: (b) => (sent.push(b), created(b as never)) });
    render(<AddUserDialog open onOpenChange={() => {}} roles={[ROLE]} slotsAvailable={5} onCreated={() => {}} />);
    const group = screen.getByRole("group", { name: "Shop Access" });
    expect((within(group).getByLabelText("No Shop Access") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(/cannot access operational shop data until shops are assigned/)).toBeTruthy();
    await fillNewUser(user);
    await user.click(screen.getByRole("button", { name: "Add user" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ shop_access: { mode: "none", shop_ids: [] } });
  });

  it("adds a user with All Shops", async () => {
    const user = userEvent.setup();
    const sent: unknown[] = [];
    backend({ create: (b) => (sent.push(b), created(b as never)) });
    render(<AddUserDialog open onOpenChange={() => {}} roles={[ROLE]} slotsAvailable={5} onCreated={() => {}} />);
    await fillNewUser(user);
    await user.click(screen.getByLabelText("All Shops"));
    expect(screen.getByText(/including shops created later/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Add user" }));
    await waitFor(() => expect(sent[0]).toMatchObject({ shop_access: { mode: "all", shop_ids: [] } }));
  });

  it("adds a user with selected shops, telling duplicate names apart by code", async () => {
    const user = userEvent.setup();
    const sent: unknown[] = [];
    backend({ create: (b) => (sent.push(b), created(b as never)) });
    render(<AddUserDialog open onOpenChange={() => {}} roles={[ROLE]} slotsAvailable={5} onCreated={() => {}} />);
    await fillNewUser(user);
    await user.click(screen.getByLabelText("Selected Shops Only"));
    const list = await screen.findByRole("group", { name: "Shops" });
    const rows = within(list).getAllByRole("listitem").map((li) => li.textContent);
    expect(rows).toEqual(["Cheena Main ShopCH-001", "Cheena Main ShopCH-002", "Closed BranchOLD-1Inactive"]);
    // Empty selection is refused locally.
    await user.click(screen.getByRole("button", { name: "Add user" }));
    expect(screen.getByText(/Select at least one shop/)).toBeTruthy();
    expect(sent).toHaveLength(0);
    await user.click(within(list).getAllByRole("checkbox")[0]);
    expect(screen.getByText("1 shop selected")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Add user" }));
    await waitFor(() => expect(sent[0]).toMatchObject({ shop_access: { mode: "selected", shop_ids: ["s-1"] } }));
  });

  it("searches and selects several shops", async () => {
    const user = userEvent.setup();
    backend();
    render(<AddUserDialog open onOpenChange={() => {}} roles={[ROLE]} slotsAvailable={5} onCreated={() => {}} />);
    await user.click(screen.getByLabelText("Selected Shops Only"));
    await screen.findByRole("group", { name: "Shops" });
    await user.type(screen.getByLabelText("Search shops by name or code"), "ch-00");
    const boxes = within(screen.getByRole("group", { name: "Shops" })).getAllByRole("checkbox");
    expect(boxes).toHaveLength(2);
    await user.click(boxes[0]);
    await user.click(boxes[1]);
    expect(screen.getByText("2 shops selected")).toBeTruthy();
    const chips = screen.getByRole("list", { name: "Selected shops" });
    expect(within(chips).getAllByRole("listitem")).toHaveLength(2);
    await user.click(within(chips).getByRole("button", { name: "Remove Cheena Main Shop CH-002" }));
    expect(screen.getByText("1 shop selected")).toBeTruthy();
  });

  it("caps the rendered checklist for large shop lists", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 450 }, (_, i) => ({ id: `m-${i}`, name: `Outlet ${i}`, code: `O-${i}`, status: "active" as const }));
    mockedFetch.mockResolvedValue({ items: many, total: many.length });
    render(<AddUserDialog open onOpenChange={() => {}} roles={[ROLE]} slotsAvailable={5} onCreated={() => {}} />);
    await user.click(screen.getByLabelText("Selected Shops Only"));
    const list = await screen.findByRole("group", { name: "Shops" });
    expect(within(list).getAllByRole("checkbox")).toHaveLength(100);
    expect(screen.getByText(/first 100 of 450 matching shops/)).toBeTruthy();
  });

  it("shows a load error with retry", async () => {
    const user = userEvent.setup();
    mockedFetch.mockRejectedValueOnce(new ApiError(503, "service_unavailable", "Shops are unavailable."));
    render(<AddUserDialog open onOpenChange={() => {}} roles={[ROLE]} slotsAvailable={5} onCreated={() => {}} />);
    await user.click(screen.getByLabelText("Selected Shops Only"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Shops are unavailable.");
    backend();
    await user.click(within(alert).getByRole("button", { name: /Retry/ }));
    expect(await screen.findByRole("group", { name: "Shops" })).toBeTruthy();
  });
});

describe("Edit User — Shop Access", () => {
  function renderEdit(u = person({ shop_access: { mode: "selected", shop_count: 1 } }), onShopAccessSaved = vi.fn()) {
    render(<EditUserDialog user={u} roles={[ROLE, CLERK]} onOpenChange={() => {}} onSaved={() => {}} onShopAccessSaved={onShopAccessSaved} />);
    return onShopAccessSaved;
  }

  it("shows the saved assignment and saves a change after review", async () => {
    const user = userEvent.setup();
    const sent: unknown[] = [];
    backend({ save: (b) => (sent.push(b), { access: detail({ shops: [CH1, CH2], shop_count: 2, version: 4 }), changed: true }) });
    const saved = renderEdit();
    const form = await screen.findByRole("form", { name: "Shop access" });
    expect((within(form).getByLabelText("Selected Shops Only") as HTMLInputElement).checked).toBe(true);
    const boxes = within(await within(form).findByRole("group", { name: "Shops" })).getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes.map((b) => b.checked)).toEqual([true, false, false]);
    expect(within(form).getByRole("button", { name: "Save shop access" })).toHaveProperty("disabled", true);
    await user.click(boxes[1]);
    await user.click(within(form).getByRole("button", { name: "Save shop access" }));
    const review = within(form).getByRole("group", { name: "Review shop access change" });
    expect(review.textContent).toMatch(/more shop data/);
    expect(review.textContent).toMatch(/1 added, 0 removed/);
    expect(sent).toHaveLength(0); // nothing saved before confirming
    await user.click(within(review).getByRole("button", { name: "Confirm shop access" }));
    await waitFor(() => expect(sent).toEqual([{ mode: "selected", shop_ids: ["s-1", "s-2"], expected_version: 3 }]));
    expect(await within(form).findByText("Shop access saved.")).toBeTruthy();
    expect(saved).toHaveBeenCalled();
  });

  it("warns before revoking access", async () => {
    const user = userEvent.setup();
    backend({ save: () => ({ access: detail({ mode: "none", shops: [], shop_count: null, version: 4 }), changed: true }) });
    renderEdit();
    const form = await screen.findByRole("form", { name: "Shop access" });
    await user.click(within(form).getByLabelText("No Shop Access"));
    await user.click(within(form).getByRole("button", { name: "Save shop access" }));
    expect(within(form).getByRole("group", { name: "Review shop access change" }).textContent).toMatch(/removes access immediately/);
  });

  it("reports a stale form and reloads the latest assignment", async () => {
    const user = userEvent.setup();
    let version = 3;
    backend({
      access: () => detail({ version }),
      save: () => {
        throw new ApiError(409, "stale_shop_access", "This user's shop access was changed after the form was opened.");
      },
    });
    renderEdit();
    const form = await screen.findByRole("form", { name: "Shop access" });
    await user.click(within(form).getByLabelText("All Shops"));
    await user.click(within(form).getByRole("button", { name: "Save shop access" }));
    await user.click(within(form).getByRole("button", { name: "Confirm shop access" }));
    expect(await within(form).findByText(/changed after the form was opened/)).toBeTruthy();
    version = 5;
    await user.click(within(form).getByRole("button", { name: "Load latest" }));
    await waitFor(() => expect(mockedFetch.mock.calls.filter((c) => String(c[0]).endsWith("/shop-access") && !c[1]?.method)).toHaveLength(2));
  });

  it("keeps role and shop access independent", async () => {
    const user = userEvent.setup();
    const patches: unknown[] = [];
    mockedFetch.mockImplementation(async (path, init) => {
      if (init?.method === "PATCH") {
        patches.push(JSON.parse(String(init.body)));
        return person();
      }
      if (String(path) === "/company/shop-assignment-options") return { items: SHOPS, total: 3 };
      return detail();
    });
    renderEdit();
    await screen.findByRole("form", { name: "Shop access" });
    await user.selectOptions(screen.getByLabelText("Role"), "r-clerk");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(patches).toEqual([{ role_id: "r-clerk" }])); // no shop fields
  });

  it("is read-only for the protected Company Admin", async () => {
    backend({ access: () => detail({ mode: "company", shops: [], shop_count: null, editable: false, version: null }) });
    renderEdit(person({ tier: "company_admin", is_protected: true, shop_access: { mode: "company", shop_count: null } }));
    expect(await screen.findByText(/Company Admin always has access to all shops/)).toBeTruthy();
    expect(screen.queryByRole("form", { name: "Shop access" })).toBeNull();
  });

  it("shows a load error with retry", async () => {
    mockedFetch.mockRejectedValueOnce(new ApiError(503, "x", "Shop access could not be loaded."));
    renderEdit();
    expect(await screen.findByText("Shop access could not be loaded.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });
});

describe("User list badges", () => {
  it.each([
    [{ mode: "company", shop_count: null }, "All Shops"],
    [{ mode: "all", shop_count: null }, "All Shops"],
    [{ mode: "selected", shop_count: 2 }, "2 Shops"],
    [{ mode: "selected", shop_count: 1 }, "1 Shop"],
    [{ mode: "none", shop_count: null }, "No Shop Access"],
  ] as const)("labels %o as %s", (access, label) => {
    expect(shopAccessLabel(access)).toBe(label);
    render(<ShopAccessBadge user={person({ shop_access: access })} />);
    expect(screen.getByTestId("shop-access-badge").textContent).toContain(label);
  });

  it("lists the assigned shops on demand", async () => {
    const user = userEvent.setup();
    backend({ access: () => detail({ shops: [CH1, OLD], shop_count: 2 }) });
    render(<ShopAccessBadge user={person({ shop_access: { mode: "selected", shop_count: 2 } })} />);
    await user.click(screen.getByRole("button", { name: /2 Shops: show shops assigned to Hamza/ }));
    const list = await screen.findByRole("list", { name: "Shops assigned to Hamza" });
    expect(list.textContent).toContain("CH-001");
    expect(list.textContent).toContain("OLD-1");
  });
});

describe("Change summary", () => {
  it("classifies expansion and revocation", () => {
    const one = new Set(["a"]);
    expect(describeChange({ mode: "none", ids: new Set() }, { mode: "all", ids: new Set() })).toMatchObject({ expands: true, revokes: false });
    expect(describeChange({ mode: "all", ids: new Set() }, { mode: "selected", ids: one })).toMatchObject({ expands: false, revokes: true });
    expect(describeChange({ mode: "selected", ids: one }, { mode: "selected", ids: new Set(["b"]) })).toEqual({ added: 1, removed: 1, expands: true, revokes: true });
  });
});

describe("Selector for Company Users", () => {
  function options(mode: ShopOptions["access"]["mode"], items = [{ id: "s-1", name: "Cheena Main Shop", code: "CH-001" }]): ShopOptions {
    return { items, total: items.length, truncated: false, selection: { status: "all", shop: null }, access: { mode, all_label: "All Assigned Shops" } };
  }

  it("labels the combined option All Assigned Shops", async () => {
    const user = userEvent.setup();
    mockedFetch.mockResolvedValue(options("selected"));
    render(<ShopContextProvider enabled><ShopSelector /></ShopContextProvider>);
    const trigger = within(screen.getByTestId("shop-selector")).getByRole("button");
    await waitFor(() => expect(trigger.textContent).toContain("All Assigned Shops"));
    expect(trigger.textContent).toContain("Your assigned shops");
    await user.click(trigger);
    expect((await screen.findAllByRole("option"))[0].textContent).toBe("All Assigned ShopsEvery shop assigned to you");
  });

  it("explains an account without assigned shops", async () => {
    mockedFetch.mockResolvedValue(options("none", []));
    render(<ShopContextProvider enabled><ShopSelector /><ShopContextNoticeBar /></ShopContextProvider>);
    const trigger = within(screen.getByTestId("shop-selector")).getByRole("button");
    await waitFor(() => expect(trigger.textContent).toContain("No shops assigned"));
    expect(trigger).toHaveProperty("disabled", true);
    expect(screen.getByRole("status").textContent).toBe("No shops have been assigned to your account. Contact your Company Admin.");
  });

  it("falls back to All Assigned Shops when a selected shop is revoked", async () => {
    nav.search = new URLSearchParams({ shop: "s-9" });
    mockedFetch.mockResolvedValue({ ...options("selected"), selection: { status: "not_found", shop: null } });
    render(<ShopContextProvider enabled><ShopSelector /><ShopContextNoticeBar /></ShopContextProvider>);
    expect(await screen.findByText("The previously selected shop is no longer available to you. Showing All Assigned Shops.")).toBeTruthy();
    expect(nav.replace).toHaveBeenCalledWith("/company");
  });
});
