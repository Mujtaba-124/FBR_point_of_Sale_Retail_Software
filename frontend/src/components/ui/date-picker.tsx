"use client";

import { useState } from "react";
import { CalendarDays } from "lucide-react";

import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { dateFromIso, formatDate, isIsoDate, isoFromDate } from "@/lib/format";
import { cn } from "@/lib/utils";

type Props = {
  id: string;
  labelId: string;
  /** Selected date as "YYYY-MM-DD", or "" for none. */
  value: string;
  onChange: (iso: string) => void;
  /** Inclusive bounds as "YYYY-MM-DD". */
  min?: string | null;
  max?: string | null;
  invalid?: boolean;
  describedBy?: string;
  placeholder?: string;
  className?: string;
};

/**
 * Date picker that always shows "DD MMM YYYY" (e.g. "05 Nov 2027"), whatever
 * the browser locale, and hands back "YYYY-MM-DD". Days outside [min, max]
 * cannot be selected. Values are converted only at the calendar boundary via
 * local calendar parts, so there is no time zone shift.
 */
export function DatePicker({
  id,
  labelId,
  value,
  onChange,
  min,
  max,
  invalid,
  describedBy,
  placeholder = "Select a date",
  className,
}: Props) {
  const [open, setOpen] = useState(false);
  const selected = value && isIsoDate(value) ? dateFromIso(value) : undefined;
  const minDate = min ? dateFromIso(min) : undefined;
  const maxDate = max ? dateFromIso(max) : undefined;
  const valueId = `${id}-value`;

  const disabled = [
    ...(minDate ? [{ before: minDate }] : []),
    ...(maxDate ? [{ after: maxDate }] : []),
  ];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        id={id}
        type="button"
        aria-labelledby={`${labelId} ${valueId}`}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        aria-haspopup="dialog"
        className={cn(
          "flex h-11 w-full items-center justify-between gap-3 rounded-lg border border-input bg-white px-3.5 text-left text-sm shadow-xs transition-colors outline-none",
          "hover:border-slate-300 focus-visible:border-blue-600 focus-visible:ring-3 focus-visible:ring-blue-600/20",
          "aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20",
          "data-[popup-open]:border-blue-600",
          className,
        )}
      >
        <span
          id={valueId}
          className={cn("tabular-nums", selected ? "font-medium text-slate-900" : "text-muted-foreground")}
        >
          {selected ? formatDate(value) : placeholder}
        </span>
        <CalendarDays className="size-4 shrink-0 text-slate-500" aria-hidden="true" />
      </PopoverTrigger>
      <PopoverContent
        align="start"
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
            if (date) onChange(isoFromDate(date));
            setOpen(false);
          }}
          defaultMonth={selected ?? minDate}
          startMonth={minDate}
          endMonth={maxDate}
          disabled={disabled}
          captionLayout="dropdown"
          weekStartsOn={1}
          autoFocus
        />
      </PopoverContent>
    </Popover>
  );
}
