import type { AssignableShop, ShopAccessMode, ShopAccessSummary } from "@/lib/api/types";

/** Never render more checkboxes than this at once; search narrows the rest. */
export const MAX_VISIBLE_SHOPS = 100;

export const MODE_COPY: Record<ShopAccessMode, { title: string; hint: string }> = {
  all: {
    title: "All Shops",
    hint: "This user can access all shops permitted by their role, including shops created later.",
  },
  selected: {
    title: "Selected Shops Only",
    hint: "This user can access only the shops you tick below, subject to their role.",
  },
  none: {
    title: "No Shop Access",
    hint: "This user cannot access operational shop data until shops are assigned.",
  },
};

export function shopAccessError(mode: ShopAccessMode, selected: ReadonlySet<string>): string | null {
  return mode === "selected" && selected.size === 0
    ? "Select at least one shop, or choose another Shop Access option."
    : null;
}

export function filterShops(shops: AssignableShop[], query: string): AssignableShop[] {
  const q = query.trim().toLowerCase();
  if (!q) return shops;
  return shops.filter((s) => s.name.toLowerCase().includes(q) || s.code.toLowerCase().includes(q));
}

/** Badge text for the user list. */
export function shopAccessLabel(access: ShopAccessSummary): string {
  switch (access.mode) {
    case "company":
    case "all":
      return "All Shops";
    case "selected": {
      const n = access.shop_count ?? 0;
      return `${n.toLocaleString("en-US")} ${n === 1 ? "Shop" : "Shops"}`;
    }
    default:
      return "No Shop Access";
  }
}

export type AccessChange = { added: number; removed: number; expands: boolean; revokes: boolean };

/** What saving would change, for the confirmation step. */
export function describeChange(
  before: { mode: ShopAccessMode; ids: ReadonlySet<string> },
  after: { mode: ShopAccessMode; ids: ReadonlySet<string> },
): AccessChange {
  const beforeIds = before.mode === "selected" ? before.ids : new Set<string>();
  const afterIds = after.mode === "selected" ? after.ids : new Set<string>();
  const added = [...afterIds].filter((id) => !beforeIds.has(id)).length;
  const removed = [...beforeIds].filter((id) => !afterIds.has(id)).length;
  if (before.mode === "selected" && after.mode === "selected") {
    return { added, removed, expands: added > 0, revokes: removed > 0 };
  }
  // A change of mode: none < selected < all (All Shops covers every shop).
  const rank = { none: 0, selected: 1, all: 2 } as const;
  return {
    added,
    removed,
    expands: rank[after.mode] > rank[before.mode],
    revokes: rank[after.mode] < rank[before.mode],
  };
}
