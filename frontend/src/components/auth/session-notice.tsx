"use client";

import { useSearchParams } from "next/navigation";
import { Info } from "lucide-react";

/** Shown above the form when the proxy sent the user back after their session ended. */
export function SessionNotice() {
  const reason = useSearchParams().get("reason");
  if (reason !== "session_expired") return null;

  return (
    <div
      role="status"
      className="mb-6 flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900"
    >
      <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <p>Your session has ended. Please sign in again.</p>
    </div>
  );
}
