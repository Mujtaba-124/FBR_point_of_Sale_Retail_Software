"use client";

import { useState, type ReactNode } from "react";
import { Menu } from "lucide-react";

import { SuperAdminBrand } from "@/components/super-admin/brand";
import { SidebarNav } from "@/components/super-admin/sidebar-nav";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

/** Below the lg breakpoint the sidebar moves into an accessible drawer. */
export function MobileNav({ profile }: { profile: ReactNode }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="flex items-center justify-between bg-gradient-to-r from-[#050b1f] to-[#0b1a3d] px-4 py-3 lg:hidden">
      <SuperAdminBrand />
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger
          aria-label="Open navigation menu"
          className="flex size-10 items-center justify-center rounded-lg text-white ring-1 ring-white/15 transition-colors hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300/70"
        >
          <Menu className="size-5" aria-hidden="true" />
        </SheetTrigger>
        <SheetContent
          side="left"
          className="w-72 max-w-[85vw] gap-0 border-r-0 bg-gradient-to-b from-[#050b1f] via-[#0b1a3d] to-[#0e2357] p-0 text-white [&_[data-slot=sheet-close]]:text-white"
        >
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <div className="flex h-full flex-col gap-8 p-5">
            <SuperAdminBrand />
            <div className="flex-1">
              <SidebarNav onNavigate={() => setOpen(false)} />
            </div>
            {profile}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
