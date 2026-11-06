"use client";

import { Lock } from "lucide-react";

import { Pill } from "@/components/company/ui-kit";
import type { CapabilityColumn, PermissionCatalog } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const COLUMNS: { key: CapabilityColumn; label: string }[] = [
  { key: "view", label: "View" },
  { key: "create", label: "Create" },
  { key: "edit", label: "Edit" },
  { key: "delete", label: "Delete" },
  { key: "special", label: "Special actions" },
];

/**
 * Module-by-capability grid. Admin-only modules are locked; the Dashboard view
 * is the baseline every account has; modules that are not built yet are
 * clearly marked, and granting them now only prepares the role.
 */
export function PermissionMatrix({
  catalog,
  selected,
  onToggle,
  readOnly = false,
  adminRole = false,
}: {
  catalog: PermissionCatalog;
  selected: ReadonlySet<string>;
  onToggle?: (key: string, checked: boolean) => void;
  readOnly?: boolean;
  adminRole?: boolean;
}) {
  const baseline = new Set(catalog.baseline);
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table className="w-full min-w-[640px] text-left text-sm">
          <caption className="sr-only">Module permissions</caption>
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">
                Module
              </th>
              {COLUMNS.map((c) => (
                <th key={c.key} scope="col" className="px-3 py-2 font-medium">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {catalog.modules.map((module) => {
              const locked = readOnly || module.admin_only;
              return (
                <tr key={module.key} className={cn(!module.available && "bg-slate-50/50")}>
                  <th scope="row" className="px-3 py-2.5 align-top font-medium text-slate-900">
                    <span className="block">{module.label}</span>
                    <span className="mt-1 flex flex-wrap gap-1">
                      {module.admin_only && (
                        <Pill tone="navy">
                          <Lock className="size-3" aria-hidden="true" />
                          Company Admin only
                        </Pill>
                      )}
                      {!module.available && <Pill tone="slate">Not available yet</Pill>}
                    </span>
                  </th>
                  {COLUMNS.map((column) => {
                    const caps = module.capabilities.filter((c) => c.column === column.key);
                    return (
                      <td key={column.key} className="px-3 py-2.5 align-top">
                        {caps.length === 0 ? (
                          <span className="text-slate-300" aria-label="Not applicable">
                            —
                          </span>
                        ) : (
                          <span className="flex flex-col gap-1.5">
                            {caps.map((cap) => {
                              const isBaseline = baseline.has(cap.key);
                              const checked = adminRole || isBaseline || selected.has(cap.key);
                              const disabled = locked || adminRole || isBaseline;
                              const id = `perm-${cap.key}`;
                              return (
                                <label
                                  key={cap.key}
                                  htmlFor={id}
                                  className={cn(
                                    "inline-flex items-start gap-2 text-xs",
                                    disabled ? "text-slate-500" : "cursor-pointer text-slate-700",
                                  )}
                                >
                                  <input
                                    id={id}
                                    type="checkbox"
                                    checked={checked}
                                    disabled={disabled}
                                    onChange={(e) => onToggle?.(cap.key, e.target.checked)}
                                    className="mt-0.5 size-4 accent-blue-700"
                                  />
                                  <span>
                                    {cap.label}
                                    <span className="sr-only">
                                      {" "}
                                      ({module.label}
                                      {!module.available ? ", module not available yet" : ""}
                                      {module.admin_only ? ", Company Admin only" : ""})
                                    </span>
                                  </span>
                                </label>
                              );
                            })}
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-slate-500">
        Dashboard access is included for every account. User Management and Roles & Permissions
        stay with the Company Admin. Permissions for modules marked &quot;Not available yet&quot;
        are saved on the role but do nothing until that module is released.
      </p>
    </div>
  );
}
