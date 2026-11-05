const DATE_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/**
 * Format a backend calendar date ("YYYY-MM-DD") as "05 Nov 2026".
 * Parsed as a UTC calendar date so the viewer's time zone can never shift it.
 */
export function formatDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) return "—";
  const [, y, m, d] = match;
  return DATE_FORMAT.format(new Date(Date.UTC(Number(y), Number(m) - 1, Number(d))));
}

const DATE_TIME_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Asia/Karachi",
});

/** Format a stored UTC timestamp in Pakistan time: "05 Nov 2026, 14:30". */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : DATE_TIME_FORMAT.format(d);
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
