"use client";

import { useState } from "react";
import { Check, Copy, KeyRound } from "lucide-react";

import { setupLinkFor } from "@/components/company/users/user-validation";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";

/** Shows a freshly issued one-time setup link. It is never shown again. */
export function SetupLinkPanel({
  token,
  expiresAt,
  name,
}: {
  token: string;
  expiresAt: string;
  name: string;
}) {
  const [copied, setCopied] = useState(false);
  const link = setupLinkFor(token, typeof window === "undefined" ? "" : window.location.origin);

  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="space-y-3 rounded-xl border border-blue-200 bg-blue-50/60 p-4">
      <p className="flex items-center gap-2 text-sm font-semibold text-blue-950">
        <KeyRound className="size-4" aria-hidden="true" />
        One-time password setup link for {name}
      </p>
      <label htmlFor="setup-link" className="sr-only">
        Setup link
      </label>
      <input
        id="setup-link"
        readOnly
        value={link}
        onFocus={(e) => e.currentTarget.select()}
        className="h-10 w-full rounded-lg border border-blue-200 bg-white px-3 font-mono text-xs text-slate-800"
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-blue-900/80">
          Valid until {formatDateTime(expiresAt)} PKT, single use. It is shown only now: share it
          with the user directly. No password is ever emailed.
        </p>
        <Button type="button" variant="outline" className="h-9 gap-2 bg-white" onClick={() => void copy()}>
          {copied ? (
            <Check className="size-4" aria-hidden="true" />
          ) : (
            <Copy className="size-4" aria-hidden="true" />
          )}
          {copied ? "Copied" : "Copy link"}
        </Button>
      </div>
    </div>
  );
}
