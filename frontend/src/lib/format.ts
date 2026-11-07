import { isValid, parse } from "date-fns";

/**
 * Application date standard: calendar dates are shown as DD/MM/YYYY and
 * timestamps as DD/MM/YYYY HH:mm (24-hour, Pakistan time), whatever the
 * browser locale. The API and the database keep ISO values ("YYYY-MM-DD",
 * UTC timestamps); only these helpers turn them into text for people.
 */
export const DATE_DISPLAY_FORMAT = "DD/MM/YYYY";
export const BUSINESS_TIME_ZONE = "Asia/Karachi";

const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Format a backend calendar date ("YYYY-MM-DD") as "07/11/2026".
 * Pure text rearrangement: no Date object, so no time zone can shift the day.
 */
export function formatDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const match = ISO_DATE_RE.exec(isoDate);
  if (!match) return "—";
  const [, y, m, d] = match;
  return `${d}/${m}/${y}`;
}

const DATE_TIME_PARTS = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: BUSINESS_TIME_ZONE,
});

/** Format a stored UTC timestamp in Pakistan time: "07/11/2026 11:41". */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  // Assembled from parts so the separators never depend on the locale data.
  const part = Object.fromEntries(DATE_TIME_PARTS.formatToParts(d).map((p) => [p.type, p.value]));
  return `${part.day}/${part.month}/${part.year} ${part.hour}:${part.minute}`;
}

/** Today's calendar date in Pakistan time as "YYYY-MM-DD". */
export function todayInBusinessTz(now: Date = new Date()): string {
  const part = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", { timeZone: BUSINESS_TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit" })
      .formatToParts(now)
      .map((p) => [p.type, p.value]),
  );
  return `${part.year}-${part.month}-${part.day}`;
}

export type DisplayDateResult = { ok: true; iso: string } | { ok: false; reason: "format" | "invalid" };

const DISPLAY_DATE_RE = /^\d{1,2}\/\d{1,2}\/\d{4}$/;

/**
 * Parse a typed DD/MM/YYYY date ("07/11/2026" = 7 November 2026; one-digit day
 * or month allowed) into "YYYY-MM-DD". Day first, always: never guessed from
 * the browser locale. date-fns rejects impossible dates such as 29/02/2027.
 */
export function parseDisplayDate(text: string): DisplayDateResult {
  const value = text.trim();
  if (!DISPLAY_DATE_RE.test(value)) return { ok: false, reason: "format" };
  const parsed = parse(value, "d/M/yyyy", new Date(2000, 0, 1));
  if (!isValid(parsed) || parsed.getFullYear() < 1900) return { ok: false, reason: "invalid" };
  return { ok: true, iso: isoFromDate(parsed) };
}

/**
 * Shape keyboard input as DD/MM/YYYY while typing: digits only plus "/", with
 * the slashes added automatically (phones' numeric keypads have none).
 * "07112026" -> "07/11/2026"; "7/11/2026" stays as typed.
 */
export function maskDisplayDate(raw: string): string {
  const parts = ["", "", ""];
  let segment = 0;
  for (const ch of raw.replace(/[.\-\s]/g, "/")) {
    if (ch === "/") {
      if (parts[segment].length > 0 && segment < 2) segment += 1;
      continue;
    }
    if (!/\d/.test(ch)) continue;
    if (segment < 2 && parts[segment].length === 2) segment += 1;
    if (segment === 2 && parts[2].length === 4) break;
    parts[segment] += ch;
  }
  return parts[0] + (segment >= 1 ? `/${parts[1]}` : "") + (segment >= 2 ? `/${parts[2]}` : "");
}

/** Whole calendar days from a to b (both "YYYY-MM-DD"); display only. */
export function daysBetween(a: string, b: string): number {
  const toUtc = (s: string) => {
    const [y, m, d] = s.split("-").map(Number);
    return Date.UTC(y, m - 1, d);
  };
  return Math.round((toUtc(b) - toUtc(a)) / 86_400_000);
}

/**
 * Calendar-date bridge for date pickers, which work with JS Date objects.
 * The Date is built from local calendar parts (local midnight) and read back
 * the same way, so the round trip never crosses a time zone boundary and the
 * day can't shift, whatever the browser's time zone.
 */
export function dateFromIso(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function isoFromDate(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [y, m, d] = value.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
}

export function pluralDays(count: number): string {
  return `${count.toLocaleString("en-US")} ${count === 1 ? "day" : "days"}`;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = (parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "");
  return letters.toUpperCase() || "?";
}
