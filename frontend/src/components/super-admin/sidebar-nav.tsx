"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { SUPER_ADMIN_NAV, isActive } from "@/components/super-admin/nav-items";
import { cn } from "@/lib/utils";

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav aria-label="Super Admin">
      <p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-blue-200/65">
        Super Admin
      </p>
      <ul className="space-y-1">
        {SUPER_ADMIN_NAV.map(({ href, label, icon: Icon, comingSoon }) => {
          const active = isActive(pathname, href);
          return (
            <li key={href}>
              <Link
                href={href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "group flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm leading-snug font-medium transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300/70",
                  active
                    ? "bg-white/12 text-white shadow-[inset_3px_0_0_0_var(--color-sky-400)]"
                    : "text-blue-100/75 hover:bg-white/6 hover:text-white",
                )}
              >
                <Icon
                  className={cn("size-4 shrink-0", active ? "text-sky-300" : "text-blue-200/70")}
                  aria-hidden="true"
                />
                <span className="flex-1">{label}</span>
                {comingSoon && (
                  <span className="shrink-0 rounded-full bg-white/8 px-2 py-0.5 text-[11px] font-medium text-blue-100/75 ring-1 ring-white/10">
                    Soon
                    <span className="sr-only"> (not available yet)</span>
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
