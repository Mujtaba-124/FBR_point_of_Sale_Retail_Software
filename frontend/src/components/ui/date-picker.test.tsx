import { useState } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { DatePicker } from "@/components/ui/date-picker";
import {
  dateFromIso,
  formatDate,
  formatDateTime,
  isoFromDate,
  maskDisplayDate,
  parseDisplayDate,
  todayInBusinessTz,
} from "@/lib/format";

afterEach(cleanup);

function Harness({
  initial = "2027-11-05",
  min = "2027-11-05",
  max = "2037-11-02",
}: {
  initial?: string;
  min?: string | null;
  max?: string | null;
}) {
  const [value, setValue] = useState(initial);
  return (
    <div>
      <label id="label" htmlFor="picker">
        New expiry date
      </label>
      <DatePicker id="picker" labelId="label" value={value} min={min} max={max} onChange={setValue} />
      <output data-testid="iso">{value}</output>
      <button type="button" onClick={() => setValue("")}>
        Reset
      </button>
    </div>
  );
}

const field = () => screen.getByRole("textbox", { name: "New expiry date" }) as HTMLInputElement;
const calendarButton = () => screen.getByRole("button", { name: /Open calendar: New expiry date/ });
const iso = () => screen.getByTestId("iso").textContent;
const dayButton = (value: string) => document.querySelector<HTMLButtonElement>(`td[data-day="${value}"] button`);

describe("DatePicker (DD/MM/YYYY)", () => {
  it("shows the value as DD/MM/YYYY, with the format announced to screen readers", () => {
    render(<Harness />);
    expect(field().value).toBe("05/11/2027");
    expect(field().placeholder).toBe("DD/MM/YYYY");
    expect(field().getAttribute("aria-describedby")).toContain("picker-format");
    expect(document.getElementById("picker-format")?.textContent).toMatch(/DD\/MM\/YYYY/);
    // Not a native date input: its display order would follow the browser locale.
    expect(field().type).toBe("text");
  });

  it("reads typed dates day first: 07/11/2026 is 7 November, 11/07/2026 is 11 July", async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness initial="" min={null} max={null} />);
    await user.type(field(), "07/11/2026");
    expect(iso()).toBe("2026-11-07");
    await user.clear(field());
    await user.type(field(), "11/07/2026");
    expect(iso()).toBe("2026-07-11");
    await user.clear(field());
    await user.type(field(), "05/11/2027");
    expect(iso()).toBe("2027-11-05");
  });

  it("adds the slashes for digits-only typing (numeric keypads) and tidies short forms", async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness initial="" min={null} max={null} />);
    await user.type(field(), "31122026");
    expect(field().value).toBe("31/12/2026");
    expect(iso()).toBe("2026-12-31");
    await user.clear(field());
    await user.type(field(), "1/1/2027");
    await user.tab();
    expect(field().value).toBe("01/01/2027");
    expect(iso()).toBe("2027-01-01");
  });

  it("accepts 29/02/2028 and rejects 29/02/2027 with a message, never shifting it", async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness initial="" min={null} max={null} />);
    await user.type(field(), "29/02/2028");
    expect(iso()).toBe("2028-02-29");
    await user.clear(field());
    await user.type(field(), "29/02/2027");
    expect(iso()).toBe("");
    await user.tab();
    expect(screen.getByRole("alert").textContent).toBe("29/02/2027 is not a real date.");
    expect(field().getAttribute("aria-invalid")).toBe("true");
    expect(field().value).toBe("29/02/2027"); // kept for correction, not "fixed" to 01/03
  });

  it("explains the format for incomplete input and clears the value", async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness />);
    await user.clear(field());
    await user.type(field(), "07/11");
    expect(iso()).toBe("");
    await user.tab();
    expect(screen.getByRole("alert").textContent).toBe("Enter the date as DD/MM/YYYY, for example 07/11/2026.");
    // Correcting it removes the message.
    await user.type(field(), "/2027");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(iso()).toBe("2027-11-07");
  });

  it("refuses typed dates outside the allowed range", async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness />);
    await user.clear(field());
    await user.type(field(), "04/11/2027");
    await user.tab();
    expect(iso()).toBe("");
    expect(screen.getByRole("alert").textContent).toBe("Choose a date on or after 05/11/2027.");
    await user.clear(field());
    await user.type(field(), "03/11/2037");
    await user.tab();
    expect(screen.getByRole("alert").textContent).toBe("Choose a date on or before 02/11/2037.");
  });

  it("follows value changes made outside the field (reset)", async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Reset" }));
    expect(field().value).toBe("");
  });

  it("picks 07/11/2026 from the calendar and returns 2026-11-07", async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness initial="2026-11-01" min={null} max="2026-12-31" />);
    await user.click(calendarButton());
    expect(await screen.findByRole("grid")).toBeTruthy();
    await user.click(dayButton("2026-11-07")!);
    await waitFor(() => expect(screen.queryByRole("grid")).toBeNull());
    expect(field().value).toBe("07/11/2026");
    expect(iso()).toBe("2026-11-07");
  });

  it("is keyboard operable: Alt+ArrowDown opens the calendar, arrows move, Enter selects", async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness />);
    field().focus();
    await user.keyboard("{Alt>}{ArrowDown}{/Alt}");
    await waitFor(() => expect(document.activeElement?.closest("td")?.getAttribute("data-day")).toBe("2027-11-05"));
    const focusedDay = () => document.activeElement?.closest("td")?.getAttribute("data-day");
    await user.keyboard("{ArrowRight}");
    await waitFor(() => expect(focusedDay()).toBe("2027-11-06"));
    await user.keyboard("{ArrowDown}");
    await waitFor(() => expect(focusedDay()).toBe("2027-11-13"));
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.queryByRole("grid")).toBeNull());
    expect(iso()).toBe("2027-11-13");
    expect(field().value).toBe("13/11/2027");
  });

  it("closes the calendar with Escape without changing the value", async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness />);
    await user.click(calendarButton());
    await screen.findByRole("grid");
    await user.keyboard("{ArrowRight}{Escape}");
    await waitFor(() => expect(screen.queryByRole("grid")).toBeNull());
    expect(iso()).toBe("2027-11-05");
  });

  it("disables calendar days outside the allowed range and limits navigation to it", async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness />);
    await user.click(calendarButton());
    await screen.findByRole("grid");
    expect(dayButton("2027-11-04")?.disabled).toBe(true);
    expect(dayButton("2027-11-05")?.disabled).toBe(false);
    const years = [...screen.getByRole("combobox", { name: "Choose the Year" }).querySelectorAll("option")].map((o) =>
      Number(o.value),
    );
    expect(Math.min(...years)).toBe(2027);
    expect(Math.max(...years)).toBe(2037);
  });
});

describe("date helpers", () => {
  it.each([
    ["07/11/2026", "2026-11-07"],
    ["11/07/2026", "2026-07-11"],
    ["05/11/2027", "2027-11-05"],
    ["31/12/2026", "2026-12-31"],
    ["01/01/2027", "2027-01-01"],
    ["29/02/2028", "2028-02-29"],
    ["7/1/2027", "2027-01-07"],
  ])("parses %s as %s", (text, expected) => {
    expect(parseDisplayDate(text)).toEqual({ ok: true, iso: expected });
  });

  it.each(["29/02/2027", "31/04/2026", "00/01/2026", "32/01/2026", "15/13/2026", "01/01/0999"])(
    "rejects the impossible date %s",
    (text) => {
      expect(parseDisplayDate(text)).toEqual({ ok: false, reason: "invalid" });
    },
  );

  it.each(["", "2026-11-07", "07-11-26", "07/11", "07/11/26", "Nov 7 2026"])("rejects %j as not DD/MM/YYYY", (text) => {
    expect(parseDisplayDate(text)).toEqual({ ok: false, reason: "format" });
  });

  it("masks typing into DD/MM/YYYY", () => {
    expect(maskDisplayDate("07112026")).toBe("07/11/2026");
    expect(maskDisplayDate("0711")).toBe("07/11");
    expect(maskDisplayDate("071")).toBe("07/1");
    expect(maskDisplayDate("07/")).toBe("07/");
    expect(maskDisplayDate("7/11/2026")).toBe("7/11/2026");
    expect(maskDisplayDate("07.11.2026")).toBe("07/11/2026");
    expect(maskDisplayDate("07/11/20261")).toBe("07/11/2026");
    expect(maskDisplayDate("ab07x11")).toBe("07/11");
  });

  it("formats calendar dates and timestamps as DD/MM/YYYY [HH:mm] in Pakistan time", () => {
    expect(formatDate("2026-11-07")).toBe("07/11/2026");
    expect(formatDate("2027-01-07")).toBe("07/01/2027");
    expect(formatDate(null)).toBe("—");
    expect(formatDate("07/11/2026")).toBe("—"); // only ISO input is accepted
    expect(formatDateTime("2026-11-07T06:41:00Z")).toBe("07/11/2026 11:41");
    expect(formatDateTime("2026-12-31T19:30:00Z")).toBe("01/01/2027 00:30"); // already 1 Jan in PKT
    expect(formatDateTime("2026-11-07T18:05:00Z")).toBe("07/11/2026 23:05"); // 24-hour
    expect(formatDateTime("not a date")).toBe("—");
  });

  it("gives today's date in Pakistan time", () => {
    expect(todayInBusinessTz(new Date("2026-11-06T20:30:00Z"))).toBe("2026-11-07"); // PKT is UTC+5
    expect(todayInBusinessTz(new Date("2026-11-06T18:59:00Z"))).toBe("2026-11-06");
  });
});

describe("date-only conversion is time zone safe", () => {
  const zones = ["UTC", "Asia/Karachi", "America/New_York", "Europe/London", "Pacific/Kiritimati", "Pacific/Pago_Pago"];
  const dates = ["2027-11-05", "2026-11-07", "2028-02-29", "2027-03-28", "2026-12-31", "2027-01-01"];
  const originalTz = process.env.TZ;

  afterEach(() => {
    process.env.TZ = originalTz;
  });

  it.each(zones)("round-trips, parses and formats without shifting the day in %s", (zone) => {
    process.env.TZ = zone;
    for (const value of dates) {
      expect(isoFromDate(dateFromIso(value))).toBe(value);
      expect(parseDisplayDate(formatDate(value))).toEqual({ ok: true, iso: value });
    }
    expect(formatDate("2027-11-05")).toBe("05/11/2027");
    expect(formatDateTime("2026-11-07T06:41:00Z")).toBe("07/11/2026 11:41");
  });

  it("does not depend on the browser locale (en-US and en-GB)", () => {
    const original = Object.getOwnPropertyDescriptor(Navigator.prototype, "language");
    for (const language of ["en-US", "en-GB"]) {
      Object.defineProperty(navigator, "language", { value: language, configurable: true });
      expect(formatDate("2026-11-07")).toBe("07/11/2026");
      expect(parseDisplayDate("07/11/2026")).toEqual({ ok: true, iso: "2026-11-07" });
    }
    if (original) Object.defineProperty(navigator, "language", original);
  });
});
