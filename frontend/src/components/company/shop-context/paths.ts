/**
 * Which Company Workspace pages follow the shop context.
 *
 * The selection lives in the URL (`?shop=<immutable shop id>`) on these pages
 * only, so reload, Back/Forward and shared links behave predictably and no
 * browser storage is involved. Administrative pages (User Management, Roles &
 * Permissions, Shop Management) are company-wide and never receive it.
 *
 * Future modules (uploads, approvals, FBR sync, reports) are added here when
 * they are built.
 */
export const SHOP_PARAM = "shop";

const SHOP_AWARE_PATHS = ["/company"] as const;

export function isShopAwarePath(pathname: string): boolean {
  return (SHOP_AWARE_PATHS as readonly string[]).includes(pathname);
}

/** `href` with the selection attached, if `href` is a shop-aware page. */
export function withShop(href: string, shopId: string | null): string {
  if (!shopId || !isShopAwarePath(href)) return href;
  return `${href}?${new URLSearchParams({ [SHOP_PARAM]: shopId })}`;
}

/** "Name — CODE", the label used wherever one shop is shown. */
export function shopLabel(shop: { name: string; code: string }): string {
  return `${shop.name} — ${shop.code}`;
}
