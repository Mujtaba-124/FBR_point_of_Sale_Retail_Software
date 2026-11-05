import { Building2, UserRound } from "lucide-react";

import { DashboardCard, DetailList } from "@/components/super-admin/dashboard-card";
import type { CompanyAdminContact } from "@/lib/api/types";

function AdminValue({ contact }: { contact: CompanyAdminContact }) {
  if (contact.status === "not_found") {
    return <span className="text-slate-500">No Company Admin account exists</span>;
  }
  if (contact.status === "multiple") {
    return (
      <span className="text-slate-500">
        {contact.count} Company Admin accounts; no primary contact designated
      </span>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center justify-end gap-2">
      {contact.full_name}
      {contact.is_active === false && (
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 ring-1 ring-inset ring-slate-500/20">
          Inactive
        </span>
      )}
    </span>
  );
}

/** Read-only by design: the Super Admin cannot manage company users. */
export function CompanyAccountCard({
  companyName,
  contact,
  className,
}: {
  companyName: string | null;
  contact: CompanyAdminContact;
  className?: string;
}) {
  return (
    <DashboardCard
      title="Company Account"
      icon={Building2}
      className={className}
      action={
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
          Read-only
        </span>
      }
    >
      <DetailList
        items={[
          {
            label: "Company Name",
            value: companyName ?? <span className="text-slate-500">Not configured</span>,
          },
          { label: "Account Type", value: "Single Company" },
          {
            label: "Company Admin",
            value: <AdminValue contact={contact} />,
          },
          {
            label: "Admin Email",
            value:
              contact.status === "available" && contact.email ? (
                <a
                  href={`mailto:${contact.email}`}
                  className="text-blue-700 underline-offset-4 hover:underline focus-visible:rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/50"
                >
                  {contact.email}
                </a>
              ) : (
                <span className="text-slate-500">—</span>
              ),
          },
        ]}
      />
      <p className="mt-auto flex items-start gap-2 pt-4 text-xs leading-relaxed text-slate-500">
        <UserRound className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
        Company users and business data are managed only in the Company Workspace.
      </p>
    </DashboardCard>
  );
}
