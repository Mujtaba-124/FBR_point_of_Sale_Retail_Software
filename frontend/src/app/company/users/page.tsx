import type { Metadata } from "next";
import { Suspense } from "react";

import { UsersSection } from "@/components/company/users/users-section";
import { UsersSkeleton } from "@/components/company/users/users-view";
import { Topbar } from "@/components/super-admin/topbar";

export const metadata: Metadata = {
  title: "User Management | Cheena FBR POS Software",
  robots: { index: false },
};

export default function UserManagementPage() {
  return (
    <Suspense
      fallback={
        <div className="space-y-6">
          <Topbar
            title="User Management"
            description="Manage company users, their access and permissions."
          />
          <UsersSkeleton />
        </div>
      }
    >
      <UsersSection />
    </Suspense>
  );
}
