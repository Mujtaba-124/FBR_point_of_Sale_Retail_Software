import { CalendarX2 } from "lucide-react";

import { PlaceholderCard, WorkspaceShell } from "@/components/auth/workspace-shell";
import type { SubscriptionErrorCode } from "@/lib/api/types";

const MESSAGES: Record<SubscriptionErrorCode, { title: string; body: string }> = {
  subscription_expired: {
    title: "Subscription expired",
    body: "Your software subscription has expired. Please contact your administrator for renewal.",
  },
  subscription_not_started: {
    title: "Subscription not started",
    body: "Your software subscription has not started yet. Please contact your administrator.",
  },
  subscription_not_configured: {
    title: "Subscription not active",
    body: "Your software subscription is not active. Please contact your administrator.",
  },
};

/**
 * Shown to a signed-in Company account whose access is blocked by the
 * subscription. No business data, no Super Admin navigation, no renewal
 * controls: only the explanation and Sign Out.
 */
export function SubscriptionRestricted({ code }: { code: SubscriptionErrorCode }) {
  const { title, body } = MESSAGES[code];
  return (
    <WorkspaceShell label="Company Workspace">
      <div role="alert">
        <PlaceholderCard title={title}>
          <p className="flex items-start gap-2">
            <CalendarX2 className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden="true" />
            {body}
          </p>
          <p>Access is restored automatically once the subscription has been renewed.</p>
        </PlaceholderCard>
      </div>
    </WorkspaceShell>
  );
}
