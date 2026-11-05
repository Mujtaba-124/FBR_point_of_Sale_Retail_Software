import { Store } from "lucide-react";

/** Same mark as the approved login page, sized for the dashboard chrome. */
export function SuperAdminBrand() {
  return (
    <div className="flex items-center gap-3">
      <div className="flex size-10 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/20">
        <Store className="size-5 text-white" aria-hidden="true" />
      </div>
      <div className="leading-tight">
        <p className="font-semibold tracking-tight text-white">Cheena</p>
        <p className="text-[11px] uppercase tracking-[0.18em] text-sky-200/80">
          FBR POS Software
        </p>
      </div>
    </div>
  );
}
