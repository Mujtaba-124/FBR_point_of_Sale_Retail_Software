import { FileSpreadsheet, ShieldCheck, Store, Workflow } from "lucide-react";

const highlights = [
  { icon: FileSpreadsheet, text: "Structured Excel invoice import" },
  { icon: ShieldCheck, text: "Owner approval before anything is sent" },
  { icon: Workflow, text: "Controlled, traceable FBR synchronization" },
];

export function BrandPanel() {
  return (
    <aside className="relative hidden overflow-hidden bg-gradient-to-br from-[#050b1f] via-[#0b1a3d] to-[#123a8f] text-white lg:flex lg:w-[48%] xl:w-[52%]">
      {/* Decorative layers */}
      <div
        aria-hidden="true"
        className="absolute inset-0 opacity-[0.12] [background-image:linear-gradient(to_right,white_1px,transparent_1px),linear-gradient(to_bottom,white_1px,transparent_1px)] [background-size:56px_56px] [mask-image:radial-gradient(ellipse_at_30%_20%,black,transparent_70%)]"
      />
      <div
        aria-hidden="true"
        className="absolute -right-32 -top-32 size-[28rem] rounded-full border border-white/10"
      />
      <div
        aria-hidden="true"
        className="absolute -right-12 -top-12 size-[18rem] rounded-full border border-white/10"
      />
      <div
        aria-hidden="true"
        className="absolute -bottom-40 -left-24 size-[30rem] rotate-12 rounded-[3rem] border border-sky-300/10 bg-sky-400/5"
      />
      <div
        aria-hidden="true"
        className="absolute bottom-24 right-16 size-40 -rotate-12 rounded-3xl bg-gradient-to-br from-sky-400/20 to-transparent blur-2xl"
      />

      <div className="relative z-10 flex w-full flex-col justify-between p-12 xl:p-16">
        <div className="flex items-center gap-3">
          <div className="flex size-11 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/20 backdrop-blur">
            <Store className="size-5" aria-hidden="true" />
          </div>
          <div className="leading-tight">
            <p className="text-lg font-semibold tracking-tight">Cheena</p>
            <p className="text-xs uppercase tracking-[0.2em] text-sky-200/80">
              FBR POS Software
            </p>
          </div>
        </div>

        <div className="max-w-lg space-y-8">
          <div className="space-y-5">
            <p className="text-4xl font-semibold leading-tight tracking-tight xl:text-5xl">
              Secure FBR POS reporting for every shop.
            </p>
            <p className="text-base leading-relaxed text-blue-100/80">
              Import daily sales, review them with your team, and synchronize
              approved invoices with FBR from one controlled, auditable
              workspace.
            </p>
          </div>

          <ul className="space-y-4">
            {highlights.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3 text-sm text-blue-50/90">
                <span className="flex size-8 items-center justify-center rounded-lg bg-white/10 ring-1 ring-white/15">
                  <Icon className="size-4 text-sky-300" aria-hidden="true" />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>

        <p className="text-xs text-blue-200/60">
          &copy; Cheena. All rights reserved.
        </p>
      </div>
    </aside>
  );
}
