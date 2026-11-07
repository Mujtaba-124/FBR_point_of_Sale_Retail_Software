"use client";

import { useState } from "react";
import { CalendarDays } from "lucide-react";

import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  DATE_DISPLAY_FORMAT,
  dateFromIso,
  formatDate,
  isIsoDate,
  isoFromDate,
  maskDisplayDate,
  parseDisplayDate,
} from "@/lib/format";
import { cn } from "@/lib/utils";

type Props = {
  id: string;
  /** Element that names the field (usually its <label>). */
  labelId: string;
  /** Selected date as "YYYY-MM-DD", or "" for none. */
  value: string;
  /** Receives "YYYY-MM-DD", or "" while the field is empty or not a valid date. */
  onChange: (iso: string) => void;
  /** Inclusive bounds as "YYYY-MM-DD". */
  min?: string | null;
  max?: string | null;
  invalid?: boolean;
  disabled?: boolean;
  describedBy?: string;
  className?: string;
};

function rangeProblem(iso: string, min?: string | null, max?: string | null): string | null {
  if (min && iso < min) return `Choose a date on or after ${formatDate(min)}.`;
  if (max && iso > max) return `Choose a date on or before ${formatDate(max)}.`;
  return null;
}

function clampToRange(day: Date, min?: Date, max?: Date): Date {
  if (min && day < min) return min;
  if (max && day > max) return max;
  return day;
}

/**
 * The application's date field: typed as DD/MM/YYYY (day first, whatever the
 * browser or operating-system locale) or picked from a calendar, and handed
 * back as "YYYY-MM-DD". A native <input type="date"> is not used because its
 * display order follows the browser locale (MM/DD/YYYY in en-US), which led to
 * day/month swaps. Impossible dates (29/02/2027) and dates outside [min, max]
 * are reported, never silently corrected. Dates only cross into JS Date objects
 * through local calendar parts, so no time zone can shift the day.
 */
export function DatePicker({
  id,
  labelId,
  value,
  onChange,
  min,
  max,
  invalid,
  disabled,
  describedBy,
  className,
}: Props) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(() => (isIsoDate(value) ? formatDate(value) : ""));
  const [problem, setProblem] = useState<string | null>(null);
  // Follow value changes made outside the field (reset, calendar, navigation).
  const [shown, setShown] = useState(value);
  if (shown !== value) {
    setShown(value);
    const current = parseDisplayDate(text);
    if (!(current.ok && current.iso === value)) {
      setText(isIsoDate(value) ? formatDate(value) : "");
      setProblem(null);
    }
  }

  const selected = isIsoDate(value) ? dateFromIso(value) : undefined;
  const minDate = min ? dateFromIso(min) : undefined;
  const maxDate = max ? dateFromIso(max) : undefined;
  const hintId = `${id}-format`;
  const problemId = `${id}-problem`;
  const calendarLabelId = `${id}-calendar-label`;

  function emit(iso: string) {
    setShown(iso);
    if (iso !== value) onChange(iso);
  }

  function type(raw: string) {
    const next = maskDisplayDate(raw);
    setText(next);
    setProblem(null);
    if (!next) return emit("");
    const parsed = parseDisplayDate(next);
    emit(parsed.ok && !rangeProblem(parsed.iso, min, max) ? parsed.iso : "");
  }

  /** On leaving the field: tidy a valid date ("7/11/2026" -> "07/11/2026") or explain the problem. */
  function commit() {
    if (!text) return;
    const parsed = parseDisplayDate(text);
    if (!parsed.ok) {
      setProblem(
        parsed.reason === "invalid"
          ? `${text} is not a real date.`
          : `Enter the date as ${DATE_DISPLAY_FORMAT}, for example 07/11/2026.`,
      );
      return;
    }
    const outOfRange = rangeProblem(parsed.iso, min, max);
    if (outOfRange) {
      setProblem(outOfRange);
      return;
    }
    setText(formatDate(parsed.iso));
  }

  const disabledDays = [...(minDate ? [{ before: minDate }] : []), ...(maxDate ? [{ after: maxDate }] : [])];
  const showInvalid = Boolean(invalid || problem);

  return (
    <div className={cn("min-w-0", className)}>
      <div className="relative">
        <input
          id={id}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          spellCheck={false}
          maxLength={10}
          placeholder={DATE_DISPLAY_FORMAT}
          value={text}
          disabled={disabled}
          aria-labelledby={labelId}
          aria-invalid={showInvalid || undefined}
          aria-describedby={[hintId, problem ? problemId : null, describedBy].filter(Boolean).join(" ")}
          onChange={(e) => type(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "ArrowDown" && e.altKey) {
              e.preventDefault();
              setOpen(true);
            }
          }}
          className={cn(
            "h-11 w-full min-w-0 rounded-lg border border-input bg-white py-2 pr-12 pl-3.5 text-sm font-medium text-slate-900 tabular-nums shadow-xs transition-colors outline-none",
            "placeholder:font-normal placeholder:text-muted-foreground",
            "hover:border-slate-300 focus-visible:border-blue-600 focus-visible:ring-3 focus-visible:ring-blue-600/20",
            "aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20",
            "disabled:cursor-not-allowed disabled:bg-slate-50 disabled:opacity-60",
          )}
        />
        <span id={hintId} className="sr-only">
          Format day/month/year, {DATE_DISPLAY_FORMAT}.
        </span>
        <span id={calendarLabelId} className="sr-only">
          Open calendar:
        </span>
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger
            type="button"
            disabled={disabled}
            aria-labelledby={`${calendarLabelId} ${labelId}`}
            aria-haspopup="dialog"
            className={cn(
              "absolute top-1/2 right-1 flex size-9 -translate-y-1/2 items-center justify-center rounded-md text-slate-500 outline-none",
              "hover:bg-slate-100 hover:text-slate-700 focus-visible:ring-3 focus-visible:ring-blue-600/30",
              "disabled:pointer-events-none disabled:opacity-50 data-[popup-open]:text-blue-700",
            )}
          >
            <CalendarDays className="size-4" aria-hidden="true" />
          </PopoverTrigger>
          <PopoverContent
            align="end"
            className="w-auto max-w-[calc(100vw-2rem)] p-0"
            // The calendar owns focus: its autoFocus puts focus on the selected
            // day (so arrow keys work at once). Letting the popover also move
            // focus would fight the calendar's own keyboard navigation.
            initialFocus={false}
          >
            <Calendar
              mode="single"
              selected={selected}
              // Selecting the already-selected day reports `undefined` (a toggle
              // off); treat it as confirming that day instead of clearing it.
              onSelect={(date) => {
                if (date) {
                  const iso = isoFromDate(date);
                  setText(formatDate(iso));
                  setProblem(null);
                  emit(iso);
                }
                setOpen(false);
              }}
              defaultMonth={selected ?? clampToRange(new Date(), minDate, maxDate)}
              startMonth={minDate}
              endMonth={maxDate}
              disabled={disabledDays}
              captionLayout="dropdown"
              weekStartsOn={1}
              autoFocus
            />
          </PopoverContent>
        </Popover>
      </div>
      {problem && (
        <p id={problemId} role="alert" className="mt-1.5 text-xs text-destructive">
          {problem}
        </p>
      )}
    </div>
  );
}
