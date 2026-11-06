import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { navFor } from "@/components/company/nav-items";
import { setupLinkFor, validateNewUser } from "@/components/company/users/user-validation";
import { usersPath, UsersView } from "@/components/company/users/users-view";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { CompanyRoleItem, CompanyUser, CompanyUserPage, SetupLinkIssued } from "@/lib/api/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/company/users",
}));
vi.mock("@/lib/api/client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/client")>()),
  apiFetch: vi.fn(),
}));
const mockedFetch = vi.mocked(apiFetch);
beforeEach(() => mockedFetch.mockReset());
afterEach(cleanup);

const ADMIN_ROLE: CompanyRoleItem = {
  id: "r-admin", name: "Company Admin", description: null, system_key: "company_admin",
  is_system: true, is_active: true, permissions: ["users.view"], active_users: 1, total_users: 1,
  version: 1, updated_at: "2026-11-06T00:00:00Z",
};
const USER_ROLE: CompanyRoleItem = {
  ...ADMIN_ROLE, id: "r-user", name: "Company User", system_key: "company_user",
  permissions: ["dashboard.view"],
};
const CLERK: CompanyRoleItem = {
  ...ADMIN_ROLE, id: "r-clerk", name: "Clerk", system_key: null, is_system: false,
  permissions: ["dashboard.view", "reports.view"],
};
const ROLES = [ADMIN_ROLE, USER_ROLE, CLERK];

function person(overrides: Partial<CompanyUser> = {}): CompanyUser {
  return {
    id: crypto.randomUUID(), full_name: "Staff Member", email: "staff@example.test",
    tier: "company_user", is_protected: false, status: "active",
    role: { id: "r-user", name: "Company User", is_system: true, is_active: true },
    setup_pending: false, setup_link_expires_at: null, last_login_at: null,
    created_at: "2026-11-06T00:00:00Z", shop_access: { mode: "none", shop_count: null }, ...overrides,
  };
}

const OWNER = person({
  full_name: "Owner", email: "owner@example.test", tier: "company_admin", is_protected: true,
  role: { id: "r-admin", name: "Company Admin", is_system: true, is_active: true },
});

function page(items: CompanyUser[], active = items.filter((u) => u.status === "active").length, total = items.length): CompanyUserPage {
  return {
    items, total, limit: 10, offset: 0,
    capacity: { active, limit: 15, available: 15 - active, inactive: items.filter((u) => u.status === "inactive").length },
  };
}

function renderView(data = page([OWNER, person()])) {
  return render(<UsersView initial={data} roles={ROLES} />);
}

describe("User Management", () => {
  it("shows capacity from the backend and the protected admin", () => {
    renderView();
    expect(screen.getByTestId("capacity-active-users-value").textContent).toBe("2 / 15");
    expect(screen.getByTestId("capacity-available-slots-value").textContent).toBe("13");
    const table = screen.getByRole("table", { name: "Company users" });
    const ownerRow = within(table).getByText("Owner").closest("tr")!;
    expect(within(ownerRow).getByText("Protected Admin")).toBeTruthy();
    expect(within(ownerRow).queryByRole("button", { name: /Deactivate/ })).toBeNull();
    expect(within(table).getByRole("button", { name: "Deactivate Staff Member" })).toBeTruthy();
  });

  it("warns and disables reactivation when all 15 slots are used", () => {
    const inactive = person({ full_name: "Former", status: "inactive" });
    renderView(page([OWNER, inactive], 15, 2));
    expect(screen.getByText(/All 15 active user slots are occupied/)).toBeTruthy();
    const table = screen.getByRole("table", { name: "Company users" });
    expect(within(table).getByRole("button", { name: "Reactivate Former" })).toHaveProperty("disabled", true);
  });

  it("searches, filters and sorts through the API", async () => {
    const user = userEvent.setup();
    mockedFetch.mockResolvedValue(page([OWNER]));
    renderView();
    await user.type(screen.getByLabelText("Search by name or email"), "own");
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    expect(String(mockedFetch.mock.calls.at(-1)![0])).toContain("search=own");
    await user.selectOptions(screen.getByLabelText("Status"), "inactive");
    await waitFor(() => expect(String(mockedFetch.mock.calls.at(-1)![0])).toContain("status=inactive"));
    await user.selectOptions(screen.getByLabelText("Role"), "r-clerk");
    await waitFor(() => expect(String(mockedFetch.mock.calls.at(-1)![0])).toContain("role_id=r-clerk"));
    await user.click(screen.getByRole("button", { name: "Email" }));
    await waitFor(() => expect(String(mockedFetch.mock.calls.at(-1)![0])).toContain("sort=email"));
  });

  it("shows the no-results and load-error states", async () => {
    const user = userEvent.setup();
    mockedFetch.mockResolvedValueOnce(page([])).mockRejectedValueOnce(
      new ApiError(503, "service_unavailable", "Service unavailable."),
    );
    renderView();
    await user.type(screen.getByLabelText("Search by name or email"), "zzz");
    expect(await screen.findByText("No users match your search or filters.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /Refresh/ }));
    expect(await screen.findByText("Service unavailable.")).toBeTruthy();
  });

  it("paginates", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 10 }, (_, i) => person({ full_name: `P${i}`, email: `p${i}@x.test` }));
    mockedFetch.mockResolvedValue({ ...page(many), offset: 10 });
    renderView({ ...page(many), total: 14 });
    expect(screen.getByText("1–10 of 14")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(String(mockedFetch.mock.calls.at(-1)![0])).toContain("offset=10"));
  });

  it("adds a user and shows the one-time setup link", async () => {
    const user = userEvent.setup();
    const created: SetupLinkIssued = {
      user: person({ full_name: "New Person", email: "new@example.test", setup_pending: true }),
      setup_token: "tok_123", setup_expires_at: "2026-11-09T00:00:00Z",
      capacity: { active: 3, limit: 15, available: 12, inactive: 0 },
    };
    mockedFetch.mockImplementation(async (path) =>
      String(path) === "/company/users" ? created : page([OWNER, person(), created.user], 3));
    renderView();
    await user.click(screen.getByRole("button", { name: "Add User" }));
    const dialog = await screen.findByRole("dialog");
    const roleSelect = within(dialog).getByLabelText("Role") as HTMLSelectElement;
    expect([...roleSelect.options].map((o) => o.textContent)).toEqual(["Company User", "Clerk"]);
    await user.type(within(dialog).getByLabelText("Full name"), "New Person");
    await user.type(within(dialog).getByLabelText("Email address"), "new@example.test");
    await user.click(within(dialog).getByRole("button", { name: "Add user" }));
    expect(await within(dialog).findByText(/One-time password setup link/)).toBeTruthy();
    const link = within(dialog).getByLabelText("Setup link") as HTMLInputElement;
    expect(link.value).toBe(`${window.location.origin}/set-password#token=tok_123`);
    const body = JSON.parse(String(mockedFetch.mock.calls[0][1]?.body));
    expect(body).toEqual({
      full_name: "New Person", email: "new@example.test", role_id: "r-user",
      shop_access: { mode: "none", shop_ids: [] }, // safe default (Phase 3.3)
    });
  });

  it("validates the add-user form and shows server errors on the field", async () => {
    const user = userEvent.setup();
    mockedFetch.mockRejectedValueOnce(new ApiError(409, "email_already_exists", "An account with this email already exists."));
    renderView();
    await user.click(screen.getByRole("button", { name: "Add User" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Add user" }));
    expect(within(dialog).getByText("Enter the full name.")).toBeTruthy();
    expect(within(dialog).getByText("Enter a valid email address.")).toBeTruthy();
    expect(mockedFetch).not.toHaveBeenCalled();
    await user.type(within(dialog).getByLabelText("Full name"), "Dup");
    await user.type(within(dialog).getByLabelText("Email address"), "dup@example.test");
    await user.click(within(dialog).getByRole("button", { name: "Add user" }));
    expect(await within(dialog).findByText("An account with this email already exists.")).toBeTruthy();
  });

  it("blocks Add User when capacity is full", async () => {
    const user = userEvent.setup();
    renderView(page([OWNER], 15, 1));
    await user.click(screen.getByRole("button", { name: "Add User" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/All active user slots are in use/)).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Add user" })).toHaveProperty("disabled", true);
  });

  it("deactivates after confirmation and reports the new capacity", async () => {
    const user = userEvent.setup();
    const staff = person();
    mockedFetch.mockImplementation(async (path) =>
      String(path).endsWith("/deactivate")
        ? { user: { ...staff, status: "inactive" }, capacity: { active: 1, limit: 15, available: 14, inactive: 1 } }
        : page([OWNER, { ...staff, status: "inactive" }], 1));
    renderView(page([OWNER, staff]));
    await user.click(screen.getAllByRole("button", { name: "Deactivate Staff Member" })[0]);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/signed out immediately/)).toBeTruthy();
    await user.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    expect(await screen.findByText("Staff Member was deactivated.")).toBeTruthy();
    expect(screen.getByTestId("capacity-active-users-value").textContent).toBe("1 / 15");
  });

  it("shows the limit error when reactivation races a full workspace", async () => {
    const user = userEvent.setup();
    const former = person({ full_name: "Former", status: "inactive" });
    mockedFetch.mockRejectedValueOnce(new ApiError(409, "user_limit_reached", "All 15 active user slots are in use."));
    renderView(page([OWNER, former], 14, 2));
    await user.click(screen.getAllByRole("button", { name: "Reactivate Former" })[0]);
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Reactivate" }));
    expect(await within(dialog).findByText("All 15 active user slots are in use.")).toBeTruthy();
  });

  it("locks the Company Admin role in the details dialog", async () => {
    const user = userEvent.setup();
    mockedFetch.mockResolvedValue({ mode: "company", shop_count: null, shops: [], editable: false, version: null, updated_at: null });
    renderView();
    await user.click(screen.getAllByRole("button", { name: "View or edit Owner" })[0]);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Company Admin is protected/)).toBeTruthy();
    expect(within(dialog).queryByLabelText("Role")).toBeNull();
  });

  it("changes a user's role", async () => {
    const user = userEvent.setup();
    const staff = person();
    mockedFetch.mockImplementation(async (path, init) =>
      init?.method === "PATCH" ? { ...staff, role: { id: "r-clerk", name: "Clerk", is_system: false, is_active: true } } : page([OWNER, staff]));
    renderView(page([OWNER, staff]));
    await user.click(screen.getAllByRole("button", { name: "View or edit Staff Member" })[0]);
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText("Role"), "r-clerk");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.getByText("Staff Member was updated.")).toBeTruthy());
    const patch = mockedFetch.mock.calls.find((c) => c[1]?.method === "PATCH")!;
    expect(JSON.parse(String(patch[1]?.body))).toEqual({ role_id: "r-clerk" });
  });
});

describe("helpers", () => {
  it("builds query strings and setup links", () => {
    expect(usersPath({ search: " a ", status: "active", role: "r1", sort: "email", order: "desc", offset: 10 }))
      .toBe("/company/users?limit=10&offset=10&sort=email&order=desc&search=a&status=active&role_id=r1");
    expect(setupLinkFor("a+b", "https://app.test")).toBe("https://app.test/set-password#token=a%2Bb");
    expect(validateNewUser({ full_name: "x\ny", email: "a@b.co", role_id: "r" }).full_name).toMatch(/not allowed/);
  });

  it("hides admin areas and unauthorized modules from Company Users", () => {
    expect(navFor("company_user", ["dashboard.view"]).map((i) => i.key)).toEqual(["dashboard"]);
    // Even with a future-module permission, an unbuilt module is not shown to a Company User.
    expect(navFor("company_user", ["dashboard.view", "reports.view"]).map((i) => i.key)).toEqual(["dashboard"]);
    // Navigation only mirrors the backend's capability list (which never grants
    // users.view to a Company User); the pages and APIs are guarded server-side.
    expect(navFor("company_admin", ["dashboard.view", "users.view", "roles.view"]).map((i) => i.key))
      .toEqual(["dashboard", "users", "roles"]);
  });

  it("does not open dialogs stacked on each other", async () => {
    await act(async () => {
      renderView();
    });
    expect(screen.queryAllByRole("dialog")).toHaveLength(0);
  });
});
