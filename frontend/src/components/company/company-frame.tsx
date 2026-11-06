import { Suspense, type ReactNode } from "react";

import { CompanyMobileNav } from "@/components/company/mobile-nav";
import { ShopContextNoticeBar } from "@/components/company/shop-context/shop-context-notice";
import { ShopSelector } from "@/components/company/shop-context/shop-selector";
import { CompanySidebarNav } from "@/components/company/sidebar-nav";
import { SuperAdminBrand as Brand } from "@/components/super-admin/brand";
import {
  SidebarProfile,
  SidebarProfileSkeleton,
} from "@/components/super-admin/sidebar-profile";
import type { AccessCategory } from "@/lib/api/types";

/**
 * Company Workspace frame: same navy sidebar, spacing and content surface as
 * the Super Admin workspace, with Company navigation only. Rendered only after
 * the backend has authorized Company access (role + valid subscription).
 */
export function CompanyFrame({
  role,
  permissions,
  children,
}: {
  role: AccessCategory;
  permissions: readonly string[];
  children: ReactNode;
}) {
  const profile = (
    <Suspense fallback={<SidebarProfileSkeleton />}>
      <SidebarProfile />
    </Suspense>
  );

  return (
    <div className="flex min-h-screen w-full bg-slate-50">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col gap-8 overflow-y-auto bg-gradient-to-b from-[#050b1f] via-[#0b1a3d] to-[#0e2357] px-4 py-6 lg:flex">
        <Brand />
        <div className="flex-1 space-y-6">
          <ShopSelector />
          <CompanySidebarNav role={role} permissions={permissions} />
        </div>
        {profile}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <CompanyMobileNav role={role} permissions={permissions} profile={profile} />
        <main className="mx-auto w-full max-w-[1760px] flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <ShopContextNoticeBar />
          {children}
        </main>
      </div>
    </div>
  );
}
