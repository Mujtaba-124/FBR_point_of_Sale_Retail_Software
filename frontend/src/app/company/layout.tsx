import { Suspense, type ReactNode } from "react";

import { WorkspaceGate, WorkspaceLoading } from "@/components/auth/workspace-gate";
import { CompanyFrame } from "@/components/company/company-frame";
import { ShopContextProvider } from "@/components/company/shop-context/shop-context-provider";

/**
 * Company Workspace. proxy.ts sends other workspaces away; the backend's
 * /company/workspace check (role + valid subscription) decides here whether
 * the frame is shown at all. Expired or not-started subscriptions show the
 * existing restricted screen instead, with no sidebar.
 */
export default function CompanyLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<WorkspaceLoading />}>
      <WorkspaceGate
        workspace="company"
        label="Company Workspace"
        shell={(data, content) => (
          // Keyed by account: a selection can never carry over to another user.
          <ShopContextProvider key={data.user.id} enabled={data.shop_context_enabled === true}>
            <CompanyFrame role={data.user.access_category} permissions={data.permissions ?? []}>
              {content}
            </CompanyFrame>
          </ShopContextProvider>
        )}
      >
        {() => children}
      </WorkspaceGate>
    </Suspense>
  );
}
