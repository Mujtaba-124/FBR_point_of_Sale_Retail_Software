import { redirect } from "next/navigation";
import type { LucideIcon } from "lucide-react";

import { StateCard, DashboardError, DashboardForbidden } from "@/components/super-admin/states";
import { checkWorkspaceAccess } from "@/lib/auth-server";

/**
 * Placeholder for a module that is not built yet. It still asks the backend
 * to authorize the Super Admin, and offers no controls.
 */
export async function ComingSoon({
  icon,
  title,
  description,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
}) {
  const access = await checkWorkspaceAccess("super_admin");
  if (access.status === "unauthenticated") redirect("/login?reason=session_expired");
  if (access.status === "forbidden") return <DashboardForbidden />;
  if (access.status === "unavailable") return <DashboardError />;

  return (
    <StateCard icon={icon} title={`${title} is not available yet`} role="status">
      <p>{description}</p>
      <p className="inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
        Coming soon
      </p>
    </StateCard>
  );
}
