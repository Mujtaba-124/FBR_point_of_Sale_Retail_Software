import type { Metadata } from "next";
import { Store } from "lucide-react";

import { SetPasswordForm } from "@/components/auth/set-password-form";

export const metadata: Metadata = {
  title: "Set Your Password | Cheena FBR POS Software",
  robots: { index: false, follow: false },
  // The setup token lives in the URL fragment; never leak this page's URL.
  referrer: "no-referrer",
};

export default function SetPasswordPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="mb-6 flex items-center gap-3">
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
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">Set your password</h1>
        <p className="mt-1 mb-5 text-sm text-slate-500">
          Choose the password you will use to sign in.
        </p>
        <SetPasswordForm />
      </div>
    </main>
  );
}
