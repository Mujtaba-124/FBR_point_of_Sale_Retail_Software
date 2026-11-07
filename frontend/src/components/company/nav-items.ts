import {
  BarChart3,
  ClipboardCheck,
  FileSpreadsheet,
  LayoutDashboard,
  RefreshCcw,
  ShieldCheck,
  Store,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { AccessCategory } from "@/lib/api/types";

export type CompanyNavItem = {
  key: string;
  label: string;
  icon: LucideIcon;
  /** Set only for modules that exist. Unfinished modules have no route at all. */
  href?: string;
  /** Capability that makes the entry visible (mirrors the backend check). */
  permission: string;
};

export const COMPANY_NAV: CompanyNavItem[] = [
  { key: "dashboard", label: "Dashboard", icon: LayoutDashboard, href: "/company", permission: "dashboard.view" },
  { key: "users", label: "User Management", icon: Users, href: "/company/users", permission: "users.view" },
  { key: "roles", label: "Roles & Permissions", icon: ShieldCheck, href: "/company/roles", permission: "roles.view" },
  { key: "shops", label: "Shops", icon: Store, href: "/company/shops", permission: "shops.view" },
  { key: "uploads", label: "Excel Uploads", icon: FileSpreadsheet, href: "/company/uploads", permission: "uploads.view" },
  { key: "approvals", label: "Approvals", icon: ClipboardCheck, permission: "approvals.view" },
  { key: "fbr-sync", label: "FBR Sync", icon: RefreshCcw, permission: "fbr_sync.view" },
  { key: "reports", label: "Reports", icon: BarChart3, permission: "reports.view" },
];

/**
 * Entries a user may see: they must hold the capability. Unfinished modules
 * ("Soon") are shown to the Company Admin only; Company Users see implemented
 * modules they are authorized for, nothing else.
 */
export function navFor(role: AccessCategory, permissions: readonly string[]): CompanyNavItem[] {
  if (role === "super_admin") return [];
  const granted = new Set(permissions);
  return COMPANY_NAV.filter(
    (item) => granted.has(item.permission) && (item.href !== undefined || role === "company_admin"),
  );
}

export function isCompanyActive(pathname: string, href: string): boolean {
  return href === "/company" ? pathname === href : pathname.startsWith(href);
}
