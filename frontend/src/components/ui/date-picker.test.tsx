import { useState } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { DatePicker } from "@/components/ui/date-picker";
import { dateFromIso, formatDate, isoFromDate } from "@/lib/format";

afterEach(cleanup);

function Harness({ initial = "2027-11-05", onValue }: { initial?: string; onValue?: (v: string) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <div>
      <span id="label">New expiry date</span>
      <DatePicker
        id="picker"
        labelId="label"
        value={value}
        min="2027-11-05"
        max="2037-11-02"
        onChange={(v) => {
          setValue(v);
          onValue?.(v);
        }}
      />
      <output data-testid="iso">{value}</output>
    </div>
  );
}

const trigger = () => screen.getByRole("button", { name: /New expiry date/ });
const dayButton = (iso: string) =>
  document.querySelector<HTMLButtonElement>(`td[data-day="${iso}"] button`);

describe("DatePicker", () => {
  it("shows the value as DD MMM YYYY, independent of the browser locale", () => {
    render(<Harness />);
    expect(trigger().textContent).toBe("05 Nov 2027");
    // The accessible name includes the label and the selected value.
    expect(trigger().getAttribute("aria-labelledby")).toBe("label picker-value");
  });

  it("opens on click, selects a day, closes, and returns YYYY-MM-DD", async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness />);

    await user.click(trigger());
    expect(await screen.findByRole("grid")).toBeTruthy();
    await user.click(dayButton("2027-11-20")!);

    await waitFor(() => expect(screen.queryByRole("grid")).toBeNull());
    expect(trigger().textContent).toBe("20 Nov 2027");
    expect(screen.getByTestId("iso").textContent).toBe("2027-11-20");
  });

  it("is keyboard operable: focus moves into the calendar, arrows move, Enter selects", async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness />);

    trigger().focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(document.activeElement?.closest("td")?.getAttribute("data-day")).toBe("2027-11-05"));

    const focusedDay = () => document.activeElement?.closest("td")?.getAttribute("data-day");
    await user.keyboard("{ArrowRight}"); // +1 day
    await waitFor(() => expect(focusedDay()).toBe("2027-11-06"));
    await user.keyboard("{ArrowDown}"); // +1 week
    await waitFor(() => expect(focusedDay()).toBe("2027-11-13"));
    await user.keyboard("{Enter}");

    await waitFor(() => expect(screen.queryByRole("grid")).toBeNull());
    expect(screen.getByTestId("iso").textContent).toBe("2027-11-13");
    await waitFor(() => expect(document.activeElement).toBe(trigger())); // focus returns
  });

  it("closes with Escape without changing the value", async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness />);
    await user.click(trigger());
    await screen.findByRole("grid");
    await user.keyboard("{ArrowRight}{Escape}");
    await waitFor(() => expect(screen.queryByRole("grid")).toBeNull());
    expect(screen.getByTestId("iso").textContent).toBe("2027-11-05");
  });

  it("disables days outside the allowed range and limits navigation to it", async () => {
    const user = userEvent.setup({ delay: null });
    render(<Harness />);
    await user.click(trigger());
    await screen.findByRole("grid");

    expect(dayButton("2027-11-04")?.disabled).toBe(true);
    expect(dayButton("2027-11-05")?.disabled).toBe(false);
    const years = [...screen.getByRole("combobox", { name: "Choose the Year" }).querySelectorAll("option")].map(
      (o) => Number(o.value),
    );
    expect(Math.min(...years)).toBe(2027);
    expect(Math.max(...years)).toBe(2037);

    await user.selectOptions(screen.getByRole("combobox", { name: "Choose the Year" }), "2037");
    await user.selectOptions(screen.getByRole("combobox", { name: "Choose the Month" }), "10");
    await waitFor(() => expect(dayButton("2037-11-02")?.disabled).toBe(false));
    expect(dayButton("2037-11-03")?.disabled).toBe(true);
  });
});

describe("date-only conversion is time zone safe", () => {
  const zones = ["UTC", "Asia/Karachi", "America/Los_Angeles", "Pacific/Kiritimati", "Pacific/Pago_Pago"];
  const dates = ["2027-11-05", "2027-11-04", "2028-02-29", "2027-03-28", "2027-12-31", "2028-01-01"];
  const originalTz = process.env.TZ;

  afterEach(() => {
    process.env.TZ = originalTz;
  });

  it.each(zones)("round-trips and formats without shifting the day in %s", (zone) => {
    process.env.TZ = zone;
    for (const iso of dates) {
      expect(isoFromDate(dateFromIso(iso))).toBe(iso);
    }
    expect(formatDate("2027-11-05")).toBe("05 Nov 2027");
    expect(formatDate("2028-11-04")).toBe("04 Nov 2028");
  });
});
