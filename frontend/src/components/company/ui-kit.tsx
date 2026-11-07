"use client";

import type { ReactNode } from "react";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

/** Shared pieces for Company Workspace forms, matching the approved styles. */

export const PRIMARY_BUTTON =
  "h-10 gap-2 bg-gradient-to-r from-[#0b1a3d] to-[#1b4fc4] text-white hover:from-[#0f2352] hover:to-[#2260e0] focus-visible:ring-3 focus-visible:ring-blue-600/40 focus-visible:ring-offset-2";

export const INPUT_CLASS =
  "h-10 bg-white focus-visible:border-blue-600 focus-visible:ring-blue-600/20 aria-invalid:focus-visible:border-destructive";

export const SELECT_CLASS =
  "h-10 w-full rounded-lg border border-input bg-white px-3 text-sm text-slate-900 shadow-xs outline-none focus-visible:border-blue-600 focus-visible:ring-3 focus-visible:ring-blue-600/20 disabled:cursor-not-allowed disabled:opacity-60";

export function Field({
  id,
  label,
  error,
  hint,
  className,
  children,
}: {
  id: string;
  label: ReactNode;
  error?: string | null;
  hint?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("min-w-0 space-y-2", className)}>
      <Label id={`${id}-label`} htmlFor={id} className="text-sm font-medium text-slate-700">
        {label}
      </Label>
      {children}
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-xs text-slate-500">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function ErrorAlert({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
    >
      <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 space-y-2">
        <div>{children}</div>
        {action}
      </div>
    </div>
  );
}

export function SuccessNote({ children }: { children: ReactNode }) {
  return (
    <div
      role="status"
      className="flex items-start gap-2.5 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900"
    >
      <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function Pill({
  tone,
  children,
}: {
  tone: "green" | "slate" | "amber" | "blue" | "navy";
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset",
        tone === "green" && "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
        tone === "slate" && "bg-slate-100 text-slate-600 ring-slate-500/20",
        tone === "amber" && "bg-amber-50 text-amber-800 ring-amber-600/25",
        tone === "blue" && "bg-blue-50 text-blue-700 ring-blue-600/20",
        tone === "navy" && "bg-[#0b1a3d] text-white ring-[#0b1a3d]",
      )}
    >
      {children}
    </span>
  );
}

/** Confirmation for consequential actions (deactivate, retire, ...). */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  busyLabel,
  busy,
  destructive,
  error,
  onConfirm,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  busyLabel: string;
  busy: boolean;
  destructive?: boolean;
  error?: string | null;
  onConfirm: () => void;
  children?: ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-lg font-semibold text-slate-900">{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {children}
          {error && <ErrorAlert>{error}</ErrorAlert>}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              className="h-10"
              disabled={busy}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={busy}
              onClick={onConfirm}
              className={cn(
                destructive
                  ? "h-10 gap-2 bg-red-600 text-white hover:bg-red-700 focus-visible:ring-3 focus-visible:ring-red-600/40"
                  : PRIMARY_BUTTON,
              )}
            >
              {busy && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
              {busy ? busyLabel : confirmLabel}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
