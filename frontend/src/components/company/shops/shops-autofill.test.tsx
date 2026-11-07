/**
 * Regression tests for the Shop Management autofill bug: a browser password
 * manager wrote the Company Admin's saved email into the Search box (and into
 * POS ID) and a saved login password into the FBR token field, because the
 * page offered a type="password" input next to formless / unnamed text inputs.
 */
import { Activity, useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ShopAbilities } from "@/components/company/shops/shop-form-dialog";
import { ShopsView } from "@/components/company/shops/shops-view";
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
afterEach(cleanup);

const FULL: ShopAbilities = { create: true, edit: true, toggle: true, manageToken: true };

function shop(overrides: Partial<Shop> = {}): Shop {
  return {
    id: crypto.randomUUID(), name: "Main Store", branch_name: "Gulberg", code: "LHR-01", pos_id: "000123",
    status: "active", fbr_token_status: "configured", fbr_token_updated_at: "2026-11-06T05:00:00Z", sales_tax_rate: "18.00",
    version: 1, created_at: "2026-11-06T05:00:00Z", updated_at: "2026-11-06T05:00:00Z", ...overrides,
  };
}

function page(items: Shop[], summary = { total: items.length, active: items.length, inactive: 0 }): ShopPage {
  return { items, total: items.length, limit: 10, offset: 0, summary, allowance: { mode: "unlimited", max_shops: null, registered_shops: summary.total, available_slots: null, at_capacity: false, over_limit: false } };
}

const MAIN = shop();
const SECOND = shop({ name: "Second Store", branch_name: "DHA", code: "LHR-02", pos_id: "000456" });
const BOTH = page([MAIN, SECOND]);

beforeEach(() => {
  mockedFetch.mockReset();
  // Default backend: list requests return both shops; saves echo a new version.
  mockedFetch.mockImplementation(async (path, init) => {
    if (init?.method === "PATCH") return { ...MAIN, ...JSON.parse(String(init.body)), version: 2 };
    return BOTH;
  });
});

/** Every input must sit inside a form and none may be a password field. */
function expectNoCredentialShape() {
  const inputs = Array.from(document.querySelectorAll("input"));
  expect(inputs.length).toBeGreaterThan(0);
  expect(document.querySelectorAll('input[type="password"]')).toHaveLength(0);
  for (const input of inputs) {
    expect(input.form, `#${input.id} must not be formless`).not.toBeNull();
    expect(input.name, `#${input.id} needs a non-credential name`).not.toMatch(/^$|user|email|login|pass/i);
    expect(input.autocomplete).toBe("off");
  }
}

function expectPasswordManagerOptOut(input: HTMLElement) {
  expect(input.getAttribute("data-1p-ignore")).toBe("true");
  expect(input.getAttribute("data-lpignore")).toBe("true");
  expect(input.getAttribute("data-bwignore")).toBe("true");
  expect(input.getAttribute("data-form-type")).toBe("other");
}

const search = () => screen.getByLabelText(/Search by shop name/) as HTMLInputElement;
const table = () => screen.getByRole("table", { name: "Shops" });
const counters = () =>
  ["total", "active", "inactive"].map((k) => screen.getByTestId(`shops-${k}-shops-value`).textContent);

async function openEdit(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(within(table()).getByRole("button", { name: `Edit ${name}` }));
  return screen.findByRole("dialog");
}

describe("Shops page — autofill and stale state", () => {
  it("opens with an empty, non-credential search box and both shops listed", () => {
    render(<ShopsView initial={BOTH} can={FULL} />);
    const box = search();
    expect(box.value).toBe("");
    expect(box.type).toBe("search");
    expect(box.name).toBe("shop_list_filter");
    expect(box.form?.getAttribute("role")).toBe("search");
    expectPasswordManagerOptOut(box);
    expectNoCredentialShape();
    expect(within(table()).getByText("Main Store")).toBeTruthy();
    expect(within(table()).getByText("Second Store")).toBeTruthy();
    expect(counters()).toEqual(["2", "2", "0"]);
  });

  it("keeps the list unfiltered after editing a shop and returning to it", async () => {
    const user = userEvent.setup();
    render(<ShopsView initial={BOTH} can={FULL} />);
    const dialog = await openEdit(user, "Main Store");
    expectNoCredentialShape(); // search + dialog fields + token field together
    const name = within(dialog).getByLabelText("Shop Name");
    await user.clear(name);
    await user.type(name, "Main Store");
    await user.type(within(dialog).getByLabelText("Branch Name"), " East");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(mockedFetch.mock.calls.some((c) => c[1]?.method === "PATCH")).toBe(true));
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(search().value).toBe("");
    const lists = mockedFetch.mock.calls.filter((c) => !c[1]?.method).map((c) => String(c[0]));
    expect(lists.every((p) => !p.includes("search="))).toBe(true);
    expect(screen.queryByText("No shops match your search or filters.")).toBeNull();
    expect(within(table()).getByText("Second Store")).toBeTruthy();
    expect(counters()).toEqual(["2", "2", "0"]);
  });

  it("starts Add Shop empty every time it is reopened", async () => {
    const user = userEvent.setup();
    render(<ShopsView initial={BOTH} can={FULL} />);
    await user.click(screen.getByRole("button", { name: "Add Shop" }));
    let dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Shop Name"), "Draft");
    await user.type(within(dialog).getByLabelText("POS ID"), "99");
    await user.type(within(dialog).getByLabelText("FBR Token (optional)"), "QA-DUMMY-DRAFT-TOKEN");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await user.click(screen.getByRole("button", { name: "Add Shop" }));
    dialog = await screen.findByRole("dialog");
    for (const label of ["Shop Name", "Branch Name", "Shop Code", "POS ID", "FBR Token (optional)"]) {
      expect((within(dialog).getByLabelText(label) as HTMLInputElement).value, label).toBe("");
    }
    expect(search().value).toBe("");
    expectNoCredentialShape();
  });

  it("loads the intended shop each time Edit is reopened and drops unsaved edits", async () => {
    const user = userEvent.setup();
    render(<ShopsView initial={BOTH} can={FULL} />);
    let dialog = await openEdit(user, "Main Store");
    await user.clear(within(dialog).getByLabelText("POS ID"));
    await user.type(within(dialog).getByLabelText("POS ID"), "777");
    await user.type(within(dialog).getByLabelText("Replacement FBR token"), "QA-DUMMY-UNSAVED");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    dialog = await openEdit(user, "Main Store");
    expect((within(dialog).getByLabelText("POS ID") as HTMLInputElement).value).toBe("000123");
    expect((within(dialog).getByLabelText("Replacement FBR token") as HTMLInputElement).value).toBe("");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    dialog = await openEdit(user, "Second Store");
    expect((within(dialog).getByLabelText("Shop Name") as HTMLInputElement).value).toBe("Second Store");
    expect((within(dialog).getByLabelText("Branch Name") as HTMLInputElement).value).toBe("DHA");
    expect((within(dialog).getByLabelText("Shop Code") as HTMLInputElement).value).toBe("LHR-02");
    expect((within(dialog).getByLabelText("POS ID") as HTMLInputElement).value).toBe("000456");
  });

  it("keeps an intentional search across dialogs and clears it on request", async () => {
    const user = userEvent.setup();
    mockedFetch.mockImplementation(async (path) =>
      String(path).includes("search=second") ? page([SECOND], { total: 2, active: 2, inactive: 0 }) : BOTH);
    render(<ShopsView initial={BOTH} can={FULL} />);
    await user.type(search(), "second");
    await waitFor(() => expect(within(table()).queryByText("Main Store")).toBeNull());
    expect(counters()).toEqual(["2", "2", "0"]); // counters stay company-wide while filtered

    const dialog = await openEdit(user, "Second Store");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(search().value).toBe("second");

    fireEvent.submit(search().form!); // Enter in the search box must not navigate or reset
    expect(search().value).toBe("second");

    await user.clear(search());
    await waitFor(() => expect(within(table()).getByText("Main Store")).toBeTruthy());
    expect(String(mockedFetch.mock.calls.at(-1)![0])).not.toContain("search=");
    expect(counters()).toEqual(["2", "2", "0"]);
  });

  it("survives back/forward (Activity hide/show) without injecting or losing search state", async () => {
    const user = userEvent.setup();
    let setMode: (m: "visible" | "hidden") => void = () => {};
    function Harness() {
      const [mode, set] = useState<"visible" | "hidden">("visible");
      setMode = set;
      return (
        <Activity mode={mode}>
          <ShopsView initial={BOTH} can={FULL} />
        </Activity>
      );
    }
    render(<Harness />);
    const dialog = await openEdit(user, "Main Store");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    act(() => setMode("hidden")); // navigate away (route kept alive by Next.js)
    act(() => setMode("visible")); // browser back
    expect(search().value).toBe("");
    expect(within(table()).getByText("Second Store")).toBeTruthy();

    await user.type(search(), "lhr");
    act(() => setMode("hidden"));
    act(() => setMode("visible"));
    expect(search().value).toBe("lhr"); // a search the user typed is preserved
  });

  it("gives POS ID and the other shop fields no credential shape", async () => {
    const user = userEvent.setup();
    render(<ShopsView initial={BOTH} can={FULL} />);
    await user.click(screen.getByRole("button", { name: "Add Shop" }));
    const dialog = await screen.findByRole("dialog");
    const pos = within(dialog).getByLabelText("POS ID") as HTMLInputElement;
    expect(pos.type).toBe("text");
    expect(pos.name).toBe("shop_pos_id");
    expectPasswordManagerOptOut(pos);
    const names = ["Shop Name", "Branch Name", "Shop Code", "POS ID"].map(
      (l) => (within(dialog).getByLabelText(l) as HTMLInputElement).name,
    );
    expect(names).toEqual(["shop_name", "shop_branch_name", "shop_code", "shop_pos_id"]);
    // The field after POS ID is the token; it must not be a password field the
    // browser could pair POS ID with as "username".
    const token = within(dialog).getByLabelText("FBR Token (optional)") as HTMLInputElement;
    expect(token.type).toBe("text");
    expect(token.form).toBe(pos.form);
    expectNoCredentialShape();
  });

  it("initializes the new-shop token empty and masked, with a reveal toggle", async () => {
    const user = userEvent.setup();
    render(<ShopsView initial={BOTH} can={FULL} />);
    await user.click(screen.getByRole("button", { name: "Add Shop" }));
    const dialog = await screen.findByRole("dialog");
    const token = within(dialog).getByLabelText("FBR Token (optional)") as HTMLInputElement;
    expect(token.value).toBe("");
    expect(token.name).toBe("shop_fbr_integration_token");
    expect(token.dataset.masked).toBe("true");
    expect(token.className).toContain("text-security:disc");
    expectPasswordManagerOptOut(token);
    await user.click(within(dialog).getByRole("button", { name: "Show token" }));
    expect(token.dataset.masked).toBe("false");
    expect(token.className).not.toContain("text-security:disc");
    expect(token.type).toBe("text");
  });

  it("initializes the replacement token empty in its own form and never shows the stored token", async () => {
    const user = userEvent.setup();
    render(<ShopsView initial={BOTH} can={FULL} />);
    const dialog = await openEdit(user, "Main Store");
    const token = within(dialog).getByLabelText("Replacement FBR token") as HTMLInputElement;
    expect(token.value).toBe("");
    expect(token.type).toBe("text");
    expect(token.dataset.masked).toBe("true");
    const profileForm = (within(dialog).getByLabelText("POS ID") as HTMLInputElement).form;
    expect(token.form).not.toBeNull();
    expect(token.form).not.toBe(profileForm); // saving the profile never sends the token
    const replace = within(dialog).getByRole("button", { name: "Replace token" }) as HTMLButtonElement;
    expect(replace.disabled).toBe(true);
    expect(replace.type).toBe("submit");
    expect(within(dialog).getByText("Token configured")).toBeTruthy();
    // No API call fetched or revealed a token value.
    expect(mockedFetch.mock.calls.some((c) => String(c[0]).includes("fbr-token"))).toBe(false);
  });

  it("keeps entered values when the server reports a duplicate", async () => {
    const user = userEvent.setup();
    mockedFetch.mockImplementation(async (path, init) => {
      if (init?.method === "POST") throw new ApiError(409, "shop_pos_id_taken", "Another shop already uses this POS ID.");
      return BOTH;
    });
    render(<ShopsView initial={BOTH} can={FULL} />);
    await user.click(screen.getByRole("button", { name: "Add Shop" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Shop Name"), "Third Store");
    await user.type(within(dialog).getByLabelText("Branch Name"), "Johar Town");
    await user.type(within(dialog).getByLabelText("Shop Code"), "LHR-03");
    await user.type(within(dialog).getByLabelText("POS ID"), "000123");
    await user.type(within(dialog).getByLabelText("Sales Tax %"), "18");
    await user.type(within(dialog).getByLabelText("FBR Token (optional)"), "QA-DUMMY-TOKEN-3");
    await user.click(within(dialog).getByRole("button", { name: "Add shop" }));
    expect(await within(dialog).findByText("Another shop already uses this POS ID.")).toBeTruthy();
    expect((within(dialog).getByLabelText("Shop Name") as HTMLInputElement).value).toBe("Third Store");
    expect((within(dialog).getByLabelText("Shop Code") as HTMLInputElement).value).toBe("LHR-03");
    expect((within(dialog).getByLabelText("POS ID") as HTMLInputElement).value).toBe("000123");
    expect((within(dialog).getByLabelText("FBR Token (optional)") as HTMLInputElement).value).toBe("QA-DUMMY-TOKEN-3");
    expect(document.body.textContent).not.toContain("QA-DUMMY-TOKEN-3");
    expect(search().value).toBe("");
  });

  it("opens the right shop from both the desktop table and the mobile card list", async () => {
    const user = userEvent.setup();
    render(<ShopsView initial={BOTH} can={FULL} />);
    const cards = screen.getByRole("list", { name: "Shops" });
    await user.click(within(cards).getByRole("button", { name: "Edit Second Store" }));
    const dialog = await screen.findByRole("dialog");
    expect((within(dialog).getByLabelText("Shop Code") as HTMLInputElement).value).toBe("LHR-02");
    expect(search().value).toBe("");
    expectNoCredentialShape();
  });
});
