import { CalendarClock, LayoutDashboard, Mail, type LucideIcon } from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Module not built yet: the route shows a "Coming soon" state. */
  comingSoon?: boolean;
};

export const SUPER_ADMIN_NAV: NavItem[] = [
  { href: "/super-admin", label: "Dashboard", icon: LayoutDashboard },
  { href: "/super-admin/subscription", label: "Subscription Management", icon: CalendarClock },
  { href: "/super-admin/email-settings", label: "Email Settings", icon: Mail },
];

export function isActive(pathname: string, href: string): boolean {
  return href === "/super-admin" ? pathname === href : pathname.startsWith(href);
}
