import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { AlertCircle, ShieldAlert } from "lucide-react";

import { filtersFromParams, mayReplaceDrafts, type UploadFilters, uploadsPath } from "@/components/company/uploads/constants";
import { UploadsView } from "@/components/company/uploads/uploads-view";
import { DashboardSkeleton, StateCard } from "@/components/super-admin/states";
import { Topbar } from "@/components/super-admin/topbar";
import type { UploadPage } from "@/lib/api/types";
import { fetchBackendDetailed, getCurrentUser } from "@/lib/auth-server";

export const metadata: Metadata = {
  title: "Excel Uploads | Cheena FBR POS Software",
  robots: { index: false },
};

type SearchParams = Promise<Record<string, string | string[] | undefined>>;
type MeWithPermissions = { permissions?: string[] };

function listPath(shop: string | null, filters: UploadFilters): `/api/v1/${string}` {
  return `/api/v1${uploadsPath(shop, filters)}`;
}

async function UploadsSection({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const shop = typeof params.shop === "string" && params.shop ? params.shop : null;
  const filters = filtersFromParams((name) => {
    const v = params[name];
    return typeof v === "string" ? v : null;
  });
  const [me, first] = await Promise.all([getCurrentUser(), fetchBackendDetailed<UploadPage>(listPath(shop, filters))]);
  // A refused shop (inactive, unassigned, invalid): show the user's own scope; the
  // shop selector explains the fallback and cleans the URL.
  const list = first.status === "rejected" && shop ? await fetchBackendDetailed<UploadPage>(listPath(null, filters)) : first;
  if (me.status === "unauthenticated" || list.status === "unauthenticated") redirect("/login?reason=session_expired");
  if (list.status === "forbidden") {
    return (
      <StateCard icon={ShieldAlert} title="Access denied" tone="error" role="alert">
        <p>Your role does not include access to Excel Uploads.</p>
      </StateCard>
    );
  }
  if (list.status !== "ok" || me.status !== "ok") {
    return (
      <StateCard icon={AlertCircle} title="Uploads unavailable" tone="error" role="alert">
        <p>The uploads could not be loaded. Please refresh in a moment.</p>
      </StateCard>
    );
  }
  // Display hints only: the backend re-checks every action, shop and status.
  const granted = new Set((me.data as MeWithPermissions).permissions ?? []);
  return <UploadsView initial={list.data} initialFilters={filters} can={{ upload: granted.has("uploads.upload"), replace: mayReplaceDrafts(granted) }} />;
}

export default function UploadsPage({ searchParams }: { searchParams: SearchParams }) {
  return (
    <Suspense
      fallback={
        <div className="space-y-6">
          <Topbar title="Excel Uploads" description="Upload daily sales files per shop, check them, and keep them as Drafts." />
          <DashboardSkeleton />
        </div>
      }
    >
      <UploadsSection searchParams={searchParams} />
    </Suspense>
  );
}
