"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Re-requests the server-rendered dashboard data from the backend. */
export function RefreshButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <Button
      type="button"
      variant="outline"
      onClick={() => startTransition(() => router.refresh())}
      disabled={pending}
      className="h-9 gap-2 rounded-lg bg-white px-3 focus-visible:ring-3 focus-visible:ring-blue-600/40"
    >
      <RefreshCw className={cn("size-4", pending && "animate-spin")} aria-hidden="true" />
      {pending ? "Refreshing…" : "Refresh"}
    </Button>
  );
}
