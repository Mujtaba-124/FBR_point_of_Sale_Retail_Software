import type { Metadata } from "next";
import { Suspense } from "react";
import { Store } from "lucide-react";

import { BrandPanel } from "@/components/auth/brand-panel";
import { LoginForm } from "@/components/auth/login-form";
import { SessionNotice } from "@/components/auth/session-notice";

export const metadata: Metadata = {
  title: "Sign In | Cheena FBR POS Software",
  description: "Sign in to Cheena FBR POS Software.",
};

export default function LoginPage() {
  return (
    <div className="flex min-h-screen w-full bg-slate-50">
      <BrandPanel />

      <main className="flex flex-1 items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-md">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <div className="flex size-10 items-center justify-center rounded-xl bg-gradient-to-br from-[#0b1a3d] to-[#1b4fc4] text-white">
              <Store className="size-5" aria-hidden="true" />
            </div>
            <div className="leading-tight">
              <p className="font-semibold tracking-tight text-slate-900">Cheena</p>
              <p className="text-[0.7rem] uppercase tracking-[0.18em] text-slate-500">
                FBR POS Software
              </p>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
            <div className="mb-8 space-y-2">
              <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
                Welcome Back
              </h1>
              <p className="text-sm leading-relaxed text-slate-500">
                Sign in with your account to manage sales, approvals and FBR
                reporting.
              </p>
            </div>
            {/* Renders nothing unless the user was sent back after a session ended. */}
            <Suspense fallback={null}>
              <SessionNotice />
            </Suspense>
            <LoginForm />
          </div>

          <p className="mt-6 text-center text-xs text-slate-500">
            Access is limited to authorized company users.
          </p>
        </div>
      </main>
    </div>
  );
}
