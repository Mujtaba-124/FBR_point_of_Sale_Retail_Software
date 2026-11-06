import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { AlertCircle, ShieldAlert } from "lucide-react";

import { SHOPS_PAGE_SIZE } from "@/components/company/shops/constants";
import { ShopsSkeleton, ShopsView } from "@/components/company/shops/shops-view";
import { StateCard } from "@/components/super-admin/states";
import { Topbar } from "@/components/super-admin/topbar";
import type { ShopPage } from "@/lib/api/types";
import { fetchBackend, getCurrentUser } from "@/lib/auth-server";

export const metadata: Metadata = {
  title: "Shop Management | Cheena FBR POS Software",
  robots: { index: false },
};

type MeWithPermissions = { permissions?: string[] };

async function ShopsSection() {
  const [shops, me] = await Promise.all([
    fetchBackend<ShopPage>(`/api/v1/company/shops?limit=${SHOPS_PAGE_SIZE}&offset=0&sort=name&order=asc`),
    getCurrentUser(),
  ]);
  if (shops.status === "unauthenticated" || me.status === "unauthenticated") {
    redirect("/login?reason=session_expired");
  }
  if (shops.status === "forbidden") {
    return (
      <StateCard icon={ShieldAlert} title="Access denied" tone="error" role="alert">
        <p>Your role does not include access to Shop Management.</p>
      </StateCard>
    );
  }
  if (shops.status !== "ok" || me.status !== "ok") {
    return (
      <StateCard icon={AlertCircle} title="Shops unavailable" tone="error" role="alert">
        <p>The shops could not be loaded. Please refresh in a moment.</p>
      </StateCard>
    );
  }
  // Display hints only: the backend re-checks every action.
  const granted = new Set((me.data as MeWithPermissions).permissions ?? []);
  return (
    <ShopsView
      initial={shops.data}
      can={{
        create: granted.has("shops.create"),
        edit: granted.has("shops.edit"),
        toggle: granted.has("shops.delete"),
        manageToken: granted.has("shops.manage_integration"),
      }}
    />
  );
}

export default function ShopsPage() {
  return (
    <Suspense
      fallback={
        <div className="space-y-6">
          <Topbar title="Shop Management" description="Manage your shops and FBR POS integration settings." />
          <ShopsSkeleton />
        </div>
      }
    >
      <ShopsSection />
    </Suspense>
  );
}
