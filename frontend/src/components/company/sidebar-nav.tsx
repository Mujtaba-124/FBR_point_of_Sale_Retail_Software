"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { isCompanyActive, navFor } from "@/components/company/nav-items";
import { useShopContext } from "@/components/company/shop-context/shop-context-provider";
import type { AccessCategory } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const ITEM =
  "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm leading-snug font-medium transition-colors";

/**
 * Same visual language as the Super Admin sidebar. Modules that are not built
 * yet are shown as disabled entries with no link, so nothing unfinished can be
 * opened.
 */
export function CompanySidebarNav({
  role,
  permissions,
  onNavigate,
}: {
  role: AccessCategory;
  permissions: readonly string[];
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  // Links to shop-aware pages keep the selected shop context.
  const { hrefFor } = useShopContext();

  return (
    <nav aria-label="Company Workspace">
      <p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-blue-200/65">
        Company Workspace
      </p>
      <ul className="space-y-1">
        {navFor(role, permissions).map(({ key, href, label, icon: Icon }) => {
          if (!href) {
            return (
              <li key={key}>
                <span
                  aria-disabled="true"
                  className={cn(ITEM, "cursor-not-allowed text-blue-100/45")}
                >
                  <Icon className="size-4 shrink-0 text-blue-200/40" aria-hidden="true" />
                  <span className="min-w-0 flex-1 truncate" title={label}>{label}</span>
                  <span className="shrink-0 rounded-full bg-white/6 px-2 py-0.5 text-[11px] font-medium text-blue-100/60 ring-1 ring-white/10">
                    Soon
                    <span className="sr-only"> (not available yet)</span>
                  </span>
                </span>
              </li>
            );
          }
          const active = isCompanyActive(pathname, href);
          return (
            <li key={key}>
              <Link
                href={hrefFor(href)}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={cn(
                  ITEM,
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
                <span className="min-w-0 flex-1 truncate" title={label}>{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
