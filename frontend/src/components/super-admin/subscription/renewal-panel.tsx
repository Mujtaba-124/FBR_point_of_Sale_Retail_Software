"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CalendarPlus, CheckCircle2, RotateCcw } from "lucide-react";

import { DashboardCard } from "@/components/super-admin/dashboard-card";
import { RenewForm } from "@/components/super-admin/subscription/renew-form";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { RenewResponse, RenewalRules, Subscription } from "@/lib/api/types";
import { formatDate } from "@/lib/format";

type Props = {
  companyName: string | null;
  subscription: Subscription;
  rules: RenewalRules;
  today: string;
  className?: string;
};

export function RenewalPanel({ companyName, subscription, rules, today, className }: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [renewed, setRenewed] = useState<RenewResponse | null>(null);

  function openDialog() {
    setAttempt((n) => n + 1); // fresh form + idempotency key per attempt
    setOpen(true);
  }

  function handleRenewed(result: RenewResponse) {
    setOpen(false);
    setRenewed(result);
    // Re-render this page from the backend and clear the client router cache,
    // so the Dashboard and history show the new expiry immediately.
    router.refresh();
  }

  function reload() {
    setOpen(false);
    router.refresh();
  }

  return (
    <DashboardCard title="Renew Subscription" icon={CalendarPlus} className={className}>
      <div className="flex flex-1 flex-col gap-4">
        {renewed && (
          <div
            role="status"
            className="flex items-start gap-2.5 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900"
          >
            <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <p>
              {renewed.replayed ? "This renewal was already saved. " : "Subscription renewed. "}
              Valid through <strong>{formatDate(renewed.renewal.new_expiry_date)}</strong>.
            </p>
          </div>
        )}

        {rules.can_renew ? (
          <p className="text-sm leading-relaxed text-slate-600">
            Extend the expiry date beyond {formatDate(subscription.expiry_date)}. The start date
            stays the same and every renewal is kept in the history below.
          </p>
        ) : (
          <p className="text-sm leading-relaxed text-slate-600">
            Renewal is available once the initial subscription has been configured by the system
            operator.
          </p>
        )}

        <div className="mt-auto flex flex-wrap gap-2">
          <Button
            type="button"
            onClick={openDialog}
            disabled={!rules.can_renew}
            className="h-10 gap-2 rounded-lg bg-gradient-to-r from-[#0b1a3d] to-[#1b4fc4] px-4 text-white shadow-sm hover:from-[#0f2352] hover:to-[#2260e0] focus-visible:ring-3 focus-visible:ring-blue-600/40 focus-visible:ring-offset-2"
          >
            <RotateCcw className="size-4" aria-hidden="true" />
            Renew Subscription
          </Button>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-lg font-semibold text-slate-900">
              Renew subscription
            </DialogTitle>
            <DialogDescription>
              Set a later expiry date. You will review the change before it is saved.
            </DialogDescription>
          </DialogHeader>
          {rules.can_renew && subscription.expiry_date && subscription.start_date && (
            <RenewForm
              key={attempt}
              companyName={companyName}
              subscription={subscription}
              rules={rules}
              today={today}
              onRenewed={handleRenewed}
              onCancel={() => setOpen(false)}
              onStale={reload}
            />
          )}
        </DialogContent>
      </Dialog>
    </DashboardCard>
  );
}
