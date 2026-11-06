import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PermissionMatrix } from "@/components/company/roles/permission-matrix";
import { validateRoleName } from "@/components/company/roles/role-form-dialog";
import { RolesView } from "@/components/company/roles/roles-view";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { CompanyRoleItem, PermissionCatalog } from "@/lib/api/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/company/roles",
}));
vi.mock("@/lib/api/client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/client")>()),
  apiFetch: vi.fn(),
}));
const mockedFetch = vi.mocked(apiFetch);
beforeEach(() => mockedFetch.mockReset());
afterEach(cleanup);

const CATALOG: PermissionCatalog = {
  baseline: ["dashboard.view"],
  modules: [
    { key: "dashboard", label: "Dashboard", available: true, admin_only: false, capabilities: [{ key: "dashboard.view", label: "View", column: "view" }] },
    { key: "users", label: "User Management", available: true, admin_only: true, capabilities: [{ key: "users.view", label: "View", column: "view" }] },
    { key: "shops", label: "Shops", available: false, admin_only: false, capabilities: [
      { key: "shops.view", label: "View", column: "view" },
      { key: "shops.delete", label: "Delete", column: "delete" },
    ] },
    { key: "fbr_sync", label: "FBR Sync", available: false, admin_only: false, capabilities: [
      { key: "fbr_sync.control", label: "Start / Stop", column: "special" },
      { key: "fbr_sync.retry", label: "Retry", column: "special" },
    ] },
  ],
};

function role(overrides: Partial<CompanyRoleItem>): CompanyRoleItem {
  return {
    id: crypto.randomUUID(), name: "Role", description: null, system_key: null, is_system: false,
    is_active: true, permissions: ["dashboard.view"], active_users: 0, total_users: 0, version: 1,
    updated_at: "2026-11-06T00:00:00Z", ...overrides,
  };
}

const ADMIN = role({ name: "Company Admin", system_key: "company_admin", is_system: true, active_users: 1, total_users: 1,
  permissions: ["dashboard.view", "users.view", "shops.view", "shops.delete", "fbr_sync.control", "fbr_sync.retry"] });
const USER = role({ name: "Company User", system_key: "company_user", is_system: true });
const CLERK = role({ name: "Clerk", description: "Front desk", permissions: ["dashboard.view", "shops.view"], active_users: 2, total_users: 3 });

function renderView(roles = [ADMIN, USER, CLERK]) {
  return render(<RolesView initial={roles} catalog={CATALOG} />);
}

describe("Roles & Permissions", () => {
  it("lists roles with system roles distinguished and protected", () => {
    renderView();
    const table = screen.getByRole("table", { name: "Company roles" });
    expect(within(table).getAllByText("System role")).toHaveLength(2);
    expect(within(table).getByRole("button", { name: "View Company Admin" })).toBeTruthy();
    expect(within(table).queryByRole("button", { name: "Retire Company Admin" })).toBeNull();
    expect(within(table).getByRole("button", { name: "Retire Clerk" })).toBeTruthy();
    expect(within(table).getByText("2 active · 1 inactive")).toBeTruthy();
  });

  it("shows a system role read-only", async () => {
    const user = userEvent.setup();
    renderView();
    await user.click(within(screen.getByRole("table", { name: "Company roles" })).getByRole("button", { name: "View Company Admin" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Protected system role/)).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: /Save/ })).toBeNull();
    for (const box of within(dialog).getAllByRole("checkbox")) {
      expect((box as HTMLInputElement).disabled).toBe(true);
      expect((box as HTMLInputElement).checked).toBe(true);
    }
  });

  it("creates a custom role from the permission matrix", async () => {
    const user = userEvent.setup();
    mockedFetch.mockImplementation(async (path, init) =>
      init?.method === "POST" ? role({ name: "Shop Lead" }) : { items: [ADMIN, USER, CLERK] });
    renderView();
    await user.click(screen.getByRole("button", { name: "Create Role" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Role name"), "Shop Lead");
    const view = within(dialog).getByLabelText(/^View \(Shops/);
    await user.click(view);
    await user.click(within(dialog).getByLabelText(/^Retry \(FBR Sync/));
    // Baseline and admin-only capabilities are locked.
    expect(within(dialog).getByLabelText(/^View \(Dashboard/)).toHaveProperty("disabled", true);
    expect(within(dialog).getByLabelText(/^View \(User Management/)).toHaveProperty("disabled", true);
    await user.click(within(dialog).getByRole("button", { name: "Create role" }));
    await waitFor(() => expect(screen.getByText("Shop Lead was saved.")).toBeTruthy());
    const post = mockedFetch.mock.calls.find((c) => c[1]?.method === "POST")!;
    expect(JSON.parse(String(post[1]?.body))).toEqual({
      name: "Shop Lead", description: null, permissions: ["fbr_sync.retry", "shops.view"],
    });
  });

  it("validates names and shows duplicate-name errors on the field", async () => {
    const user = userEvent.setup();
    mockedFetch.mockRejectedValueOnce(new ApiError(409, "role_name_taken", "A role with this name already exists."));
    renderView();
    await user.click(screen.getByRole("button", { name: "Create Role" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Create role" }));
    expect(within(dialog).getByText("The role name must be 2-60 characters.")).toBeTruthy();
    await user.type(within(dialog).getByLabelText("Role name"), "Clerk");
    await user.click(within(dialog).getByRole("button", { name: "Create role" }));
    expect(await within(dialog).findByText("A role with this name already exists.")).toBeTruthy();
    expect(validateRoleName("a")).not.toBeNull();
    expect(validateRoleName("Good name")).toBeNull();
  });

  it("edits a custom role with its version", async () => {
    const user = userEvent.setup();
    mockedFetch.mockImplementation(async (path, init) =>
      init?.method === "PATCH" ? { ...CLERK, version: 2 } : { items: [ADMIN, USER, CLERK] });
    renderView();
    await user.click(within(screen.getByRole("table", { name: "Company roles" })).getByRole("button", { name: "Edit Clerk" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByLabelText(/^Delete \(Shops/));
    await user.click(within(dialog).getByRole("button", { name: "Save role" }));
    await waitFor(() => expect(mockedFetch.mock.calls.some((c) => c[1]?.method === "PATCH")).toBe(true));
    const patch = mockedFetch.mock.calls.find((c) => c[1]?.method === "PATCH")!;
    expect(patch[0]).toBe(`/company/roles/${CLERK.id}`);
    expect(JSON.parse(String(patch[1]?.body))).toMatchObject({
      expected_version: 1, permissions: ["dashboard.view", "shops.delete", "shops.view"],
    });
  });

  it("requires a reassignment target to retire an assigned role", async () => {
    const user = userEvent.setup();
    mockedFetch.mockImplementation(async (path) =>
      String(path).endsWith("/retire") ? { ...CLERK, is_active: false } : { items: [ADMIN, USER, { ...CLERK, is_active: false }] });
    renderView();
    await user.click(within(screen.getByRole("table", { name: "Company roles" })).getByRole("button", { name: "Retire Clerk" }));
    const dialog = await screen.findByRole("dialog");
    const select = within(dialog).getByLabelText("Move users to") as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent)).toEqual(["Choose a role", "Company User"]);
    await user.selectOptions(select, USER.id);
    await user.click(within(dialog).getByRole("button", { name: "Retire role" }));
    await waitFor(() => expect(screen.getByText("Clerk was retired.")).toBeTruthy());
    const call = mockedFetch.mock.calls.find((c) => String(c[0]).endsWith("/retire"))!;
    expect(JSON.parse(String(call[1]?.body))).toEqual({ expected_version: 1, reassign_to_role_id: USER.id });
  });

  it("shows the server error when retiring fails", async () => {
    const user = userEvent.setup();
    mockedFetch.mockRejectedValueOnce(new ApiError(409, "role_in_use", "This role is assigned to 3 user(s)."));
    renderView();
    await user.click(within(screen.getByRole("table", { name: "Company roles" })).getByRole("button", { name: "Retire Clerk" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Retire role" }));
    expect(await within(dialog).findByText("This role is assigned to 3 user(s).")).toBeTruthy();
  });
});

describe("PermissionMatrix", () => {
  it("marks unavailable and admin-only modules", () => {
    render(<PermissionMatrix catalog={CATALOG} selected={new Set()} />);
    const table = screen.getByRole("table", { name: "Module permissions" });
    expect(within(table).getAllByText("Not available yet")).toHaveLength(2);
    expect(within(table).getByText("Company Admin only")).toBeTruthy();
    expect(within(table).getByLabelText(/^View \(Dashboard/)).toHaveProperty("checked", true);
  });
});
