"use client";

import { useRef, useState } from "react";
import { Loader2, LogOut } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { signOut } from "@/lib/auth";
import { hardNavigate } from "@/lib/navigation";
import { cn } from "@/lib/utils";

export function LogoutButton({ className }: { className?: string } = {}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);

  async function handleLogout() {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setError(null);
    try {
      await signOut();
      // Full page load: discards the workspace and any preserved routes.
      hardNavigate("/login");
    } catch (err) {
      inFlight.current = false;
      setPending(false);
      setError(err instanceof ApiError ? err.message : "Sign-out failed. Please try again.");
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Button
        type="button"
        variant="outline"
        onClick={handleLogout}
        disabled={pending}
        className={cn(
          "h-9 gap-2 rounded-lg px-3 focus-visible:ring-3 focus-visible:ring-blue-600/40",
          className,
        )}
      >
        {pending ? (
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        ) : (
          <LogOut className="size-4" aria-hidden="true" />
        )}
        {pending ? "Signing out…" : "Sign out"}
      </Button>
    </div>
  );
}
