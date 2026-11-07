import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { AlertCircle, SearchX, ShieldAlert } from "lucide-react";

import { UploadDetailView } from "@/components/company/uploads/upload-detail-view";
import { mayReplaceDrafts } from "@/components/company/uploads/constants";
import { DashboardSkeleton, StateCard } from "@/components/super-admin/states";
import type { SalesRecordPage, UploadDetail } from "@/lib/api/types";
import { fetchBackendDetailed, getCurrentUser } from "@/lib/auth-server";

export const metadata: Metadata = {
  title: "Upload | Cheena FBR POS Software",
  robots: { index: false },
};

type MeWithPermissions = { permissions?: string[] };
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function DetailSection({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!UUID_RE.test(id)) return <NotFound />;
  const [me, detail, records] = await Promise.all([
    getCurrentUser(),
    fetchBackendDetailed<UploadDetail>(`/api/v1/company/uploads/${id}`),
    fetchBackendDetailed<SalesRecordPage>(`/api/v1/company/uploads/${id}/records?limit=25&offset=0`),
  ]);
  if (me.status === "unauthenticated" || detail.status === "unauthenticated") redirect("/login?reason=session_expired");
  if (detail.status === "forbidden") {
    return (
      <StateCard icon={ShieldAlert} title="Access denied" tone="error" role="alert">
        <p>Your role does not include access to Excel Uploads.</p>
      </StateCard>
    );
  }
  // Unknown, or a shop outside this account's access: the same answer (no existence leak).
  if (detail.status === "rejected") return <NotFound />;
  if (detail.status !== "ok" || records.status !== "ok" || me.status !== "ok") {
    return (
      <StateCard icon={AlertCircle} title="Upload unavailable" tone="error" role="alert">
        <p>The upload could not be loaded. Please refresh in a moment.</p>
      </StateCard>
    );
  }
  const granted = new Set((me.data as MeWithPermissions).permissions ?? []);
  return <UploadDetailView detail={detail.data} initialRecords={records.data} canReplace={mayReplaceDrafts(granted)} />;
}

function NotFound() {
  return (
    <StateCard icon={SearchX} title="Upload not found" role="status">
      <p>This upload does not exist or belongs to a shop you cannot access.</p>
    </StateCard>
  );
}

export default function UploadDetailPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<DashboardSkeleton />}>
      <DetailSection params={params} />
    </Suspense>
  );
}
