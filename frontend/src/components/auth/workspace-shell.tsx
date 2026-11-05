import type { ReactNode } from "react";
import { Store } from "lucide-react";

import { LogoutButton } from "@/components/auth/logout-button";

/** Minimal authenticated frame shared by the placeholder workspace pages. */
export function WorkspaceShell({
  label,
  userName,
  showLogout = true,
  children,
}: {
  label: string;
  userName?: string;
  showLogout?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen w-full flex-col bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-8">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-[#0b1a3d] to-[#1b4fc4] text-white">
              <Store className="size-4" aria-hidden="true" />
            </div>
            <div className="leading-tight">
              <p className="font-semibold tracking-tight text-slate-900">Cheena</p>
              <p className="text-[0.7rem] uppercase tracking-[0.18em] text-slate-500">{label}</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {userName && <span className="hidden text-sm text-slate-600 sm:inline">{userName}</span>}
            {showLogout && <LogoutButton />}
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-10 sm:px-8">{children}</main>
    </div>
  );
}

export function PlaceholderCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
      <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
      <div className="mt-3 space-y-2 text-sm leading-relaxed text-slate-600">{children}</div>
    </div>
  );
}
