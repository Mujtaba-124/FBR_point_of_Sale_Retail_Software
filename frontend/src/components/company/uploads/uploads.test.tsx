import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ShopContextProvider } from "@/components/company/shop-context/shop-context-provider";
import { RecordsTable } from "@/components/company/uploads/records-table";
import { UploadDetailView } from "@/components/company/uploads/upload-detail-view";
import { UploadDialog } from "@/components/company/uploads/upload-dialog";
import { filtersFromParams, mayReplaceDrafts } from "@/components/company/uploads/constants";
import { fileSize, money, plain } from "@/components/company/uploads/upload-format";
import { UploadsView } from "@/components/company/uploads/uploads-view";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { SalesRecordRow, ShopOptions, UploadBatch, UploadDetail, UploadPage, UploadPreview } from "@/lib/api/types";
import { formatDate, todayInBusinessTz } from "@/lib/format";

const nav = vi.hoisted(() => ({ pathname: "/company/uploads", search: new URLSearchParams(), push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useSearchParams: () => nav.search,
  useRouter: () => ({ push: nav.push, replace: nav.replace, refresh: nav.refresh }),
}));
vi.mock("@/lib/api/client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/client")>()),
  apiFetch: vi.fn(),
}));
const mockedFetch = vi.mocked(apiFetch);
afterEach(cleanup);

const SHOP = { id: "s-1", name: "Cheena Main Shop", code: "CH-001" };
const OPTIONS: ShopOptions = {
  items: [SHOP, { id: "s-2", name: "Cheena Main Shop", code: "CH-002" }],
  total: 2,
  truncated: false,
  selection: { status: "all", shop: null },
  access: { mode: "company", all_label: "All Shops" },
};

function row(n: number, overrides: Partial<SalesRecordRow> = {}): SalesRecordRow {
  return {
    excel_row: n, sale_date: "2026-11-06", sale_time: "09:30:00", item: "Cotton Shirt", customer_name: "Ali Raza", cnic_ntn: "•••••-••••567-1",
    quantity: "2", rate: "1000", amount: "2000.00", tax_percent: "18.0000", tax_amount: "360.00", net_amount: "2360.00", ...overrides,
  };
}

function batch(overrides: Partial<UploadBatch> = {}): UploadBatch {
  return {
    id: "b-1", shop: { ...SHOP, status: "active" }, sales_date: "2026-11-06", filename: "sales.xlsx", status: "draft",
    current_revision: 1, total_records: 2, totals: { amount: "4000.00", sales_tax: "720.00", net_amount: "4720.00" },
    template_format: "standard_8col", applied_sales_tax_rate: "18.0000", tax_rate_source: "shop",
    uploaded_by: "Owner", uploaded_at: "2026-11-07T05:00:00Z", created_at: "2026-11-07T05:00:00Z", can_replace: true, ...overrides,
  };
}

function page(items: UploadBatch[]): UploadPage {
  return { items, total: items.length, limit: 10, offset: 0, context: { scope: "all", shop: null } };
}

function preview(overrides: Partial<UploadPreview> = {}): UploadPreview {
  return {
    shop: { ...SHOP, status: "active" }, sales_date: "2026-11-06", filename: "sales.xlsx", file_size: 9000, checksum: "a".repeat(64),
    total_rows: 2, valid_rows: 2, invalid_rows: 0, error_count: 0, errors: [], errors_truncated: false, rounding_differences: 0,
    applied_sales_tax_rate: "18.00", tax_rate_source: "shop",
    totals: { amount: "4000", sales_tax: "720", net_amount: "4720" }, rows: [row(2), row(3)], can_save: true, existing: null, ...overrides,
  };
}

const FILE = () => new File([new Uint8Array([80, 75, 3, 4])], "sales.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });

beforeEach(() => {
  mockedFetch.mockReset();
  nav.search = new URLSearchParams();
  nav.pathname = "/company/uploads";
  nav.refresh.mockReset();
});

describe("formatting", () => {
  it("formats exact decimal strings without floats", () => {
    expect(money("2459.9")).toBe("2,459.90");
    expect(money("1234567890123.45")).toBe("1,234,567,890,123.45");
    expect(money("0")).toBe("0.00");
    expect(money("0.105")).toBe("0.11");
    expect(plain("33.3330")).toBe("33.333");
    expect(plain("1500")).toBe("1,500");
    expect(formatDate("2026-11-07")).toBe("07/11/2026");
    expect(fileSize(2048)).toBe("2.0 KB");
  });

  it("renders the 8 Excel input columns, then the system-calculated tax columns", () => {
    render(<RecordsTable rows={[row(2)]} caption="Rows" />);
    const groups = screen.getAllByRole("columnheader").filter((h) => h.getAttribute("scope") === "colgroup").map((h) => h.textContent);
    expect(groups).toEqual(["Excel input", "Calculated by the system"]);
    const headers = screen.getAllByRole("columnheader").filter((h) => h.getAttribute("scope") === "col").map((h) => h.textContent);
    expect(headers.slice(1)).toEqual([
      "Date", "Time", "Item", "Customer Name", "CNIC/NTN", "Quantity", "Rate", "Amount", "Sales Tax %", "Sales Tax Amount", "Net Amount",
    ]);
    expect(screen.getByText("Cotton Shirt")).toBeTruthy();
    expect(screen.getByText("18%")).toBeTruthy();
    expect(screen.getByText("•••••-••••567-1")).toBeTruthy();
    expect(screen.getByLabelText(/scrolls sideways/).className).toContain("overflow-x-auto");
  });

  it("shows legacy 10-column rows honestly: no invented Item, tax as uploaded", () => {
    render(<RecordsTable rows={[row(2, { item: null, tax_percent: "17.0000" })]} caption="Old rows" legacy />);
    const groups = screen.getAllByRole("columnheader").filter((h) => h.getAttribute("scope") === "colgroup").map((h) => h.textContent);
    expect(groups).toEqual(["From the file (previous 10-column template)", "Tax as uploaded"]);
    expect(screen.getByLabelText("Not recorded").textContent).toBe("—");
    expect(screen.getByText("17%")).toBeTruthy();
  });
});

describe("Upload History", () => {
  it("lists uploads with totals, status and actions", () => {
    render(<UploadsView initial={page([batch(), batch({ id: "b-2", can_replace: false, status: "wait_for_approval" })])} can={{ upload: true, replace: true }} />);
    const table = screen.getByRole("table", { name: "Excel uploads" });
    expect(within(table).getAllByText("4,720.00")).toHaveLength(2);
    expect(within(table).getByText("Draft")).toBeTruthy();
    expect(within(table).getByText("Wait for Approval")).toBeTruthy();
    expect(within(table).getAllByRole("button", { name: /Replace Draft/ })).toHaveLength(1);
    expect(within(table).getAllByRole("link", { name: /View upload/ })[0].getAttribute("href")).toBe("/company/uploads/b-1");
    expect(within(table).getAllByRole("link", { name: /Download original/ })[0].getAttribute("href")).toBe("/api/v1/company/uploads/b-1/revisions/1/original");
    expect(screen.getByRole("link", { name: /Download template/ }).getAttribute("href")).toBe("/api/v1/company/uploads/template");
  });

  it("filters on the server by date range, status and the selected shop", async () => {
    const user = userEvent.setup();
    nav.search = new URLSearchParams({ shop: "s-1" });
    window.history.replaceState(null, "", "/company/uploads?shop=s-1");
    mockedFetch.mockResolvedValue(page([]));
    render(<UploadsView initial={page([batch()])} can={{ upload: true, replace: true }} />);
    // Typed day first: 01/11/2026 is 1 November, not 11 January.
    await user.type(screen.getByRole("textbox", { name: "Date From" }), "01/11/2026");
    await user.type(screen.getByRole("textbox", { name: "Date To" }), "06/11/2026");
    await user.selectOptions(screen.getByLabelText("Status"), "draft");
    await waitFor(() => {
      const last = String(mockedFetch.mock.calls.at(-1)![0]);
      expect(last).toContain("shop=s-1");
      expect(last).toContain("date_from=2026-11-01");
      expect(last).toContain("date_to=2026-11-06");
      expect(last).toContain("status=draft");
    });
    expect(await screen.findByText("No uploads match these filters.")).toBeTruthy();
    // Kept in the URL as ISO values, so reload and Back/Forward show the same list.
    const url = new URL(window.location.href);
    expect(url.searchParams.get("from")).toBe("2026-11-01");
    expect(url.searchParams.get("to")).toBe("2026-11-06");
    expect(url.searchParams.get("status")).toBe("draft");
    expect(url.searchParams.get("shop")).toBe("s-1");
  });

  it("restores filters from the URL as DD/MM/YYYY and clears them", async () => {
    const user = userEvent.setup();
    window.history.replaceState(null, "", "/company/uploads?from=2026-11-01&to=2026-11-07");
    mockedFetch.mockResolvedValue(page([batch()]));
    const filters = filtersFromParams((k) => new URL(window.location.href).searchParams.get(k));
    render(<UploadsView initial={page([batch()])} initialFilters={filters} can={{ upload: true, replace: true }} />);
    const from = screen.getByRole("textbox", { name: "Date From" }) as HTMLInputElement;
    expect(from.value).toBe("01/11/2026");
    expect((screen.getByRole("textbox", { name: "Date To" }) as HTMLInputElement).value).toBe("07/11/2026");
    await user.clear(from);
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    expect(String(mockedFetch.mock.calls.at(-1)![0])).not.toContain("date_from");
    expect(new URL(window.location.href).searchParams.get("from")).toBeNull();
  });

  it("does not allow Date From after Date To", async () => {
    const user = userEvent.setup();
    mockedFetch.mockResolvedValue(page([]));
    render(<UploadsView initial={page([batch()])} initialFilters={{ from: "", to: "2026-11-05", status: "", offset: 0 }} can={{ upload: true, replace: true }} />);
    await user.type(screen.getByRole("textbox", { name: "Date From" }), "07/11/2026");
    await user.tab();
    expect(screen.getByRole("alert").textContent).toBe("Choose a date on or before 05/11/2026.");
    expect(mockedFetch.mock.calls.some((c) => String(c[0]).includes("date_from"))).toBe(false);
  });

  it("ignores malformed or reversed URL filters", () => {
    const get = (q: string) => (k: string) => new URLSearchParams(q).get(k);
    expect(filtersFromParams(get("from=07/11/2026&to=2026-02-30&status=bogus"))).toEqual({ from: "", to: "", status: "", offset: 0 });
    expect(filtersFromParams(get("from=2026-11-08&to=2026-11-07"))).toEqual({ from: "", to: "", status: "", offset: 0 });
    expect(filtersFromParams(get("from=2026-10-31&to=2026-11-01&status=draft"))).toEqual({ from: "2026-10-31", to: "2026-11-01", status: "draft", offset: 0 });
  });

  it("offers Replace Draft only with View, Upload and Replace draft together (as the server)", () => {
    expect(mayReplaceDrafts(new Set(["uploads.view", "uploads.upload", "uploads.edit_draft"]))).toBe(true);
    expect(mayReplaceDrafts(new Set(["uploads.edit_draft"]))).toBe(false);
    expect(mayReplaceDrafts(new Set(["uploads.view", "uploads.edit_draft"]))).toBe(false);
    expect(mayReplaceDrafts(new Set(["uploads.upload", "uploads.edit_draft"]))).toBe(false);
    expect(mayReplaceDrafts(new Set(["uploads.view", "uploads.upload", "uploads.delete_draft", "uploads.submit"]))).toBe(false);
  });

  it("shows no Delete or Submit actions: those modules are not built", () => {
    render(<UploadsView initial={page([batch()])} can={{ upload: true, replace: true }} />);
    expect(screen.queryByRole("button", { name: /Delete/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Submit/i })).toBeNull();
    expect(screen.queryByRole("link", { name: /Delete|Submit/i })).toBeNull();
  });

  it("hides upload and replace controls without the permissions", () => {
    render(<UploadsView initial={page([batch()])} can={{ upload: false, replace: false }} />);
    expect(screen.queryByRole("button", { name: "New upload" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Replace Draft/ })).toBeNull();
  });
});

function renderDialog(props: Partial<Parameters<typeof UploadDialog>[0]> = {}) {
  const onSaved = vi.fn();
  render(
    <ShopContextProvider enabled>
      <UploadDialog onOpenChange={() => {}} onSaved={onSaved} canReplace {...props} />
    </ShopContextProvider>,
  );
  return onSaved;
}

/** Routes the mocked API by path; returns the recorded calls. */
function backend(handlers: { preview?: () => unknown; create?: () => unknown; replace?: () => unknown }) {
  mockedFetch.mockImplementation(async (path) => {
    const p = String(path);
    if (p.startsWith("/company/shop-options")) return OPTIONS;
    if (p.startsWith("/company/uploads/preview")) return handlers.preview?.();
    if (p.includes("/replace")) return handlers.replace?.();
    if (p.startsWith("/company/uploads?")) return handlers.create?.();
    throw new Error(p);
  });
}

async function fillForm(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => expect(screen.getAllByRole("option").length).toBeGreaterThan(1));
  await user.selectOptions(screen.getByLabelText("Shop"), "s-1");
  await user.type(screen.getByRole("textbox", { name: "Sales date" }), "06/11/2026");
  await user.upload(screen.getByLabelText("Excel file"), FILE());
}

describe("New upload dialog", () => {
  it("requires shop, date and file before checking", async () => {
    const user = userEvent.setup();
    backend({});
    renderDialog();
    await user.click(screen.getByRole("button", { name: "Check file" }));
    expect(screen.getByText("Choose a shop.")).toBeTruthy();
    expect(mockedFetch.mock.calls.some((c) => String(c[0]).includes("preview"))).toBe(false);
  });

  it("takes the sales date as DD/MM/YYYY and refuses future dates", async () => {
    const user = userEvent.setup();
    backend({});
    renderDialog();
    const field = screen.getByRole("textbox", { name: "Sales date" }) as HTMLInputElement;
    expect(field.placeholder).toBe("DD/MM/YYYY");
    const [y, m, d] = todayInBusinessTz().split("-").map(Number);
    const tomorrow = new Date(Date.UTC(y, m - 1, d + 1));
    const typed = [tomorrow.getUTCDate(), tomorrow.getUTCMonth() + 1].map((n) => String(n).padStart(2, "0")).join("/") + `/${tomorrow.getUTCFullYear()}`;
    await user.type(field, typed);
    await user.tab();
    expect(screen.getByRole("alert").textContent).toBe(`Choose a date on or before ${formatDate(todayInBusinessTz())}.`);
    await user.click(screen.getByRole("button", { name: "Check file" }));
    expect(mockedFetch.mock.calls.some((c) => String(c[0]).includes("preview"))).toBe(false);
  });

  it("shows row-level problems and offers no save", async () => {
    const user = userEvent.setup();
    backend({
      preview: () =>
        preview({
          can_save: false, valid_rows: 1, invalid_rows: 1, error_count: 2,
          errors: [
            { row: 8, column: "Date", code: "date_mismatch", message: "Date 05/11/2026 does not match the selected sales date 06/11/2026." },
            { row: 15, column: "Net Amount", code: "calculation_mismatch", message: "Net Amount 2,370.00 does not equal Amount + Sale Tax Amount (2,360.00)." },
          ],
        }),
    });
    renderDialog();
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Check file" }));
    const problems = await screen.findByRole("list", { name: "Problems by row" });
    expect(problems.textContent).toContain("Row 8 — Date: Date 05/11/2026 does not match");
    expect(problems.textContent).toContain("Row 15 — Net Amount");
    expect(screen.queryByRole("button", { name: "Save as Draft" })).toBeNull();
  });

  it("checks then saves the same file with the checksum from the check", async () => {
    const user = userEvent.setup();
    backend({ preview: () => preview(), create: () => batch() });
    const onSaved = renderDialog();
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Check file" }));
    expect(await screen.findByText(/All 2 rows passed the checks/)).toBeTruthy();
    expect(screen.getByRole("table", { name: "Preview of valid rows" })).toBeTruthy();
    const check = mockedFetch.mock.calls.find((c) => String(c[0]).includes("/preview"))!;
    expect(String(check[0])).toBe("/company/uploads/preview?shop_id=s-1&sales_date=2026-11-06&filename=sales.xlsx");
    expect(check[1]?.body).toBeInstanceOf(File);
    expect(new Headers(check[1]?.headers).get("Content-Type")).toContain("spreadsheetml");
    await user.click(screen.getByRole("button", { name: "Save as Draft" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const save = mockedFetch.mock.calls.find((c) => String(c[0]).startsWith("/company/uploads?"))!;
    expect(String(save[0])).toContain(`expected_checksum=${"a".repeat(64)}`);
    expect(String(save[0])).toContain("expected_tax_rate=18.00"); // the rate the user saw
    expect(await screen.findByText(/Saved as/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "View upload" }).getAttribute("href")).toBe("/company/uploads/b-1");
  });

  it("View upload after saving from Upload History navigates and closes the dialog", async () => {
    const user = userEvent.setup();
    backend({ preview: () => preview(), create: () => batch() });
    const onOpenChange = vi.fn();
    renderDialog({ onOpenChange });
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Check file" }));
    await user.click(await screen.findByRole("button", { name: "Save as Draft" }));
    const link = await screen.findByRole("link", { name: "View upload" });
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    link.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(false); // the link performs the navigation
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("offers a confirmed replacement when a Draft already exists", async () => {
    const user = userEvent.setup();
    backend({
      preview: () => preview({ can_save: false, existing: { id: "b-1", status: "draft", current_revision: 1, total_records: 5, can_replace: true } }),
      replace: () => batch({ current_revision: 2 }),
    });
    const onSaved = renderDialog();
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Check file" }));
    expect(await screen.findByText(/An upload already exists for this shop and date/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Save as Draft" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Replace Draft…" }));
    expect(screen.getByRole("group", { name: "Confirm replacement" }).textContent).toMatch(/earlier file and its records stay in the history/);
    await user.click(screen.getByRole("button", { name: "Confirm replacement" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ current_revision: 2 }), true));
    const call = mockedFetch.mock.calls.find((c) => String(c[0]).includes("/replace"))!;
    expect(String(call[0])).toContain("/company/uploads/b-1/replace?");
    expect(String(call[0])).toContain("expected_revision=1");
    expect(String(call[0])).toContain("expected_tax_rate=18.00");
    expect((await screen.findByText(/Saved as/)).textContent).toMatch(/revision 2/);
  });

  it("shows the applied shop Sales Tax % and labels calculated totals", async () => {
    const user = userEvent.setup();
    backend({ preview: () => preview({ applied_sales_tax_rate: "17.50", invalid_rows: 1, total_rows: 3, valid_rows: 2 }) });
    renderDialog();
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Check file" }));
    const result = await screen.findByRole("region", { name: "File check result" });
    expect(within(result).getByText("Sales Tax % (applied)").nextElementSibling?.textContent).toBe("17.5%");
    expect(within(result).getByText("From Shop Management")).toBeTruthy();
    expect(within(result).getByText("Sales tax (valid rows only)")).toBeTruthy();
    expect(within(result).getAllByText("Calculated")).toHaveLength(2);
    expect(within(result).getByText(/Tax exclusive: Sales Tax = Amount × 17.5%/)).toBeTruthy();
  });

  it("asks for a new check when the shop's Sales Tax % changed after the preview", async () => {
    const user = userEvent.setup();
    backend({
      preview: () => preview(),
      create: () => {
        throw new ApiError(409, "tax_rate_changed", "The Sales Tax % for this upload changed from 18% to 17% after the file was checked.");
      },
    });
    const onSaved = renderDialog();
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Check file" }));
    await user.click(await screen.findByRole("button", { name: "Save as Draft" }));
    expect(await screen.findByText(/changed from 18% to 17%/)).toBeTruthy();
    expect(screen.queryByRole("region", { name: "File check result" })).toBeNull(); // old totals hidden
    expect(screen.queryByRole("button", { name: "Save as Draft" })).toBeNull();
    expect(screen.getByRole("button", { name: "Check file" })).toBeTruthy();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("explains an unconfigured shop rate", async () => {
    const user = userEvent.setup();
    backend({
      preview: () => {
        throw new ApiError(409, "sales_tax_not_configured", "Sales Tax % is not configured for this shop. Configure it in Shop Management before uploading.");
      },
    });
    renderDialog();
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Check file" }));
    expect(await screen.findByText(/Configure it in Shop Management before uploading/)).toBeTruthy();
  });

  it("refuses non-xlsx files and several dropped files", async () => {
    const user = userEvent.setup({ applyAccept: false }); // let the .csv reach the component
    backend({});
    renderDialog();
    await waitFor(() => expect(screen.getAllByRole("option").length).toBeGreaterThan(1));
    const input = screen.getByLabelText("Excel file");
    await user.upload(input, new File(["a,b"], "sales.csv", { type: "text/csv" }));
    expect(screen.getByText("Choose an Excel .xlsx file.")).toBeTruthy();
    const zone = screen.getByText(/Drag the Excel file here/).parentElement!;
    fireEvent.drop(zone, { dataTransfer: { files: [FILE(), FILE()] } });
    expect(screen.getByText("Upload one file at a time.")).toBeTruthy();
  });

  it("explains an account without assigned shops", async () => {
    mockedFetch.mockResolvedValue({ ...OPTIONS, items: [], total: 0, access: { mode: "none", all_label: "All Assigned Shops" } });
    renderDialog();
    expect(await screen.findByText(/No shops have been assigned to your account/)).toBeTruthy();
  });

  it("reports server errors such as a shop that became inactive", async () => {
    const user = userEvent.setup();
    backend({
      preview: () => preview(),
      create: () => {
        throw new ApiError(409, "shop_inactive", "The selected shop is no longer active. Choose an active shop or All Shops.");
      },
    });
    renderDialog();
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Check file" }));
    await user.click(await screen.findByRole("button", { name: "Save as Draft" }));
    expect(await screen.findByText(/no longer active/)).toBeTruthy();
  });
});

describe("Upload detail", () => {
  const detail: UploadDetail = {
    batch: batch({ current_revision: 2 }),
    revisions: [
      { revision_number: 2, filename: "fixed.xlsx", file_size: 9000, checksum: "b".repeat(64), total_records: 2, totals: { amount: "4000", sales_tax: "720", net_amount: "4720" }, template_format: "standard_8col", applied_sales_tax_rate: "18.0000", tax_rate_source: "draft", uploaded_by: "Owner", uploaded_at: "2026-11-07T06:00:00Z", is_current: true },
      { revision_number: 1, filename: "sales.xlsx", file_size: 8000, checksum: "a".repeat(64), total_records: 1, totals: { amount: "2000", sales_tax: "360", net_amount: "2360" }, template_format: "legacy_10col", applied_sales_tax_rate: "18.0000", tax_rate_source: "legacy_rows", uploaded_by: "Owner", uploaded_at: "2026-11-07T05:00:00Z", is_current: false },
    ],
  };

  it("shows the summary, the revision history and switches revisions", async () => {
    const user = userEvent.setup();
    mockedFetch.mockResolvedValue({ items: [row(2)], total: 1, limit: 25, offset: 0, revision: 1 });
    render(<UploadDetailView detail={detail} initialRecords={{ items: [row(2), row(3)], total: 2, limit: 25, offset: 0, revision: 2 }} canReplace />);
    expect(screen.getByRole("heading", { name: /Cheena Main Shop — 06\/11\/2026/ })).toBeTruthy();
    expect(screen.getByTestId("applied-tax-rate").textContent).toBe("18%");
    const history = screen.getByRole("table", { name: "Revisions of this upload" });
    expect(within(history).getByText("10 columns (previous)")).toBeTruthy();
    expect(within(history).getByText("8 columns")).toBeTruthy();
    expect(screen.getByText("Not yet approved or sent to FBR.")).toBeTruthy();
    expect(screen.getAllByRole("link", { name: /Download original file of revision/ }).map((a) => a.getAttribute("href"))).toEqual([
      "/api/v1/company/uploads/b-1/revisions/2/original",
      "/api/v1/company/uploads/b-1/revisions/1/original",
    ]);
    await user.click(screen.getByRole("button", { name: "Show records of revision 1" }));
    await waitFor(() => expect(String(mockedFetch.mock.calls.at(-1)![0])).toContain("revision=1"));
    expect(await screen.findByText(/Sales records — revision 1/)).toBeTruthy();
    expect(screen.getByText("From the file (previous 10-column template)")).toBeTruthy(); // legacy revision
    expect(screen.getByRole("button", { name: "Replace Draft" })).toBeTruthy();
  });

  it("shows a mixed-rate legacy upload as Mixed and offers no replacement", () => {
    const mixed: UploadDetail = {
      batch: batch({ template_format: "legacy_10col", applied_sales_tax_rate: null, tax_rate_source: "legacy_mixed", can_replace: false }),
      revisions: [{ ...detail.revisions[1], revision_number: 1, is_current: true, applied_sales_tax_rate: null, tax_rate_source: "legacy_mixed" }],
    };
    render(<UploadDetailView detail={mixed} initialRecords={{ items: [row(2, { item: null })], total: 1, limit: 25, offset: 0, revision: 1 }} canReplace />);
    expect(screen.getByTestId("applied-tax-rate").textContent).toBe("Mixed");
    expect(screen.getByText("Rows use different rates (previous template)")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Replace Draft" })).toBeNull();
  });

  // QA-EXCEL-001: after Replace Draft on this page, "View upload" pointed at the
  // current URL, so it neither navigated nor closed the dialog.
  async function replaceFromDetail(user: ReturnType<typeof userEvent.setup>) {
    nav.pathname = "/company/uploads/b-1";
    mockedFetch.mockImplementation(async (path) => {
      const p = String(path);
      if (p.startsWith("/company/shop-options")) return OPTIONS;
      if (p.startsWith("/company/uploads/preview")) {
        return preview({ can_save: false, existing: { id: "b-1", status: "draft", current_revision: 2, total_records: 2, can_replace: true } });
      }
      if (p.includes("/replace")) {
        return batch({ current_revision: 3, total_records: 2, totals: { amount: "4500.00", sales_tax: "810.00", net_amount: "5310.00" } });
      }
      if (p.includes("/records")) return { items: [row(2)], total: 1, limit: 25, offset: 0, revision: 3 };
      throw new Error(p);
    });
    render(
      <ShopContextProvider enabled>
        <UploadDetailView detail={detail} initialRecords={{ items: [row(2), row(3)], total: 2, limit: 25, offset: 0, revision: 2 }} canReplace />
      </ShopContextProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Replace Draft" }));
    await user.upload(await screen.findByLabelText("Excel file"), FILE());
    await user.click(screen.getByRole("button", { name: "Check file" }));
    await user.click(await screen.findByRole("button", { name: "Replace Draft…" }));
    await user.click(screen.getByRole("button", { name: "Confirm replacement" }));
    return screen.findByRole("link", { name: "View upload" });
  }

  it("View upload on the same upload's page closes the dialog and shows the new revision", async () => {
    const user = userEvent.setup();
    const link = await replaceFromDetail(user);
    expect(screen.getByText(/Saved as/).textContent).toMatch(/revision 3.*5,310\.00/);
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    link.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(true); // no same-URL navigation
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(nav.refresh).toHaveBeenCalled(); // summary and history come back from the server
    // The current revision's records are loaded (the server refresh supplies its heading).
    await waitFor(() => expect(mockedFetch.mock.calls.some((c) => String(c[0]).includes("/records?revision=3"))).toBe(true));
    expect(screen.getByText("Draft replaced: revision 3 is now current.")).toBeTruthy();
  });

  it("View upload works from the keyboard and leaves nothing open", async () => {
    const user = userEvent.setup();
    const link = await replaceFromDetail(user);
    link.focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.queryByRole("link", { name: "View upload" })).toBeNull();
    expect(screen.getByRole("button", { name: "Replace Draft" })).toBeTruthy();
  });
});
