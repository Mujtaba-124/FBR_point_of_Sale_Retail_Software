import { Suspense, type ReactNode } from "react";

import { SuperAdminBrand } from "@/components/super-admin/brand";
import { MobileNav } from "@/components/super-admin/mobile-nav";
import { SidebarNav } from "@/components/super-admin/sidebar-nav";
import {
  SidebarProfile,
  SidebarProfileSkeleton,
} from "@/components/super-admin/sidebar-profile";

/**
 * Super Admin workspace frame. Access is enforced by proxy.ts (navigation)
 * and by the backend on every API call; the request-time parts (profile,
 * page data) stream in behind <Suspense>.
 */
export default function SuperAdminLayout({ children }: { children: ReactNode }) {
  const profile = (
    <Suspense fallback={<SidebarProfileSkeleton />}>
      <SidebarProfile />
    </Suspense>
  );

  return (
    <div className="flex min-h-screen w-full bg-slate-50">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col gap-8 bg-gradient-to-b from-[#050b1f] via-[#0b1a3d] to-[#0e2357] px-4 py-6 lg:flex">
        <SuperAdminBrand />
        <div className="flex-1">
          <SidebarNav />
        </div>
        {profile}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <MobileNav profile={profile} />
        {/* Fills the workspace; the cap only applies on ultra-wide screens. */}
        <main className="mx-auto w-full max-w-[1760px] flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}
