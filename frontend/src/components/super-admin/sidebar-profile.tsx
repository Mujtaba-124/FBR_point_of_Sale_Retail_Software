import { redirect } from "next/navigation";

import { LogoutButton } from "@/components/auth/logout-button";
import { getCurrentUser } from "@/lib/auth-server";
import { initials } from "@/lib/format";

const DARK_LOGOUT =
  "w-full justify-center border-white/15 bg-white/5 text-blue-50 hover:bg-white/10 hover:text-white";

export function ProfileCard({ name, email }: { name: string; email: string }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 rounded-xl bg-white/5 p-3 ring-1 ring-white/10">
        <span
          aria-hidden="true"
          className="flex size-9 shrink-0 items-center justify-center rounded-full bg-sky-400/20 text-xs font-semibold text-sky-100 ring-1 ring-sky-300/30"
        >
          {initials(name)}
        </span>
        <div className="min-w-0 leading-tight">
          <p className="truncate text-sm font-medium text-white">{name}</p>
          <p className="truncate text-xs text-blue-200/70" title={email}>
            {email}
          </p>
        </div>
      </div>
      <LogoutButton className={DARK_LOGOUT} />
    </div>
  );
}

/** Reads the signed-in user (request-time). Render inside <Suspense>. */
export async function SidebarProfile() {
  const result = await getCurrentUser();
  if (result.status === "unauthenticated") redirect("/login?reason=session_expired");
  if (result.status !== "ok") {
    return <LogoutButton className={DARK_LOGOUT} />;
  }
  return <ProfileCard name={result.data.full_name} email={result.data.email} />;
}

export function SidebarProfileSkeleton() {
  return (
    <div className="h-[6.5rem] animate-pulse rounded-xl bg-white/5 ring-1 ring-white/10" aria-hidden="true" />
  );
}
