"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { isShopAwarePath, SHOP_PARAM, withShop } from "@/components/company/shop-context/paths";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { ShopOption, ShopOptions } from "@/lib/api/types";

/**
 * Company Workspace shop context ("All Shops" or one shop).
 *
 * Mechanism:
 * - Source of truth on shop-aware pages is the URL: `?shop=<id>`. Reload,
 *   Back/Forward and links reproduce the same context; nothing is written to
 *   browser storage.
 * - The provider (mounted once in the Company layout) remembers the last
 *   selection in memory, so links back to shop-aware pages from the
 *   company-wide administrative pages keep it.
 * - Every selection is re-checked by the backend (`/company/shop-options`) on
 *   navigation and when the tab becomes visible again. A shop that became
 *   inactive, disappeared or is no longer allowed is dropped: the page falls
 *   back to All Shops with a notice, never to another shop.
 * - The provider is keyed by user ID and sign-in/out are full page loads, so
 *   no selection survives a change of account on a shared browser.
 * The selection is a filter only; the backend authorizes every request.
 */

type Status = "disabled" | "loading" | "ready" | "error";
export type ShopContextNotice = { tone: "warning" | "info"; message: string };

export type ShopAccessInfo = {
  /** company: Company Admin; all / selected / none: a Company User's shop access. */
  mode: "company" | "all" | "selected" | "none";
  /** "All Shops" for the Company Admin, "All Assigned Shops" for Company Users. */
  allLabel: string;
};

export const NO_SHOPS_MESSAGE = "No shops have been assigned to your account. Contact your Company Admin.";

export type ShopContextValue = {
  enabled: boolean;
  access: ShopAccessInfo;
  /**
   * False until the server has said which shops this account covers. Until
   * then `access` is only a placeholder: never show its label as the scope
   * (a Company User is not "All Shops"; a failed load is not a scope at all).
   */
  accessKnown: boolean;
  status: Status;
  options: ShopOption[];
  truncated: boolean;
  /** Does the current page follow the shop context? */
  applies: boolean;
  /** Selected shop ID, or null for All Shops. */
  selectedId: string | null;
  /** Latest name/code of the selected shop (from the server). */
  selected: ShopOption | null;
  notice: ShopContextNotice | null;
  dismissNotice: () => void;
  select: (shopId: string | null) => void;
  retry: () => void;
  hrefFor: (href: string) => string;
};

const COMPANY_ACCESS: ShopAccessInfo = { mode: "company", allLabel: "All Shops" };

const DISABLED: ShopContextValue = {
  enabled: false,
  access: COMPANY_ACCESS,
  accessKnown: false,
  status: "disabled",
  options: [],
  truncated: false,
  applies: false,
  selectedId: null,
  selected: null,
  notice: null,
  dismissNotice: () => {},
  select: () => {},
  retry: () => {},
  hrefFor: (href) => href,
};

const Context = createContext<ShopContextValue>(DISABLED);

export function useShopContext(): ShopContextValue {
  return useContext(Context);
}

function fallbackMessage(verdict: string, allLabel: string): string {
  const reason =
    verdict === "inactive"
      ? "The previously selected shop is no longer active."
      : verdict === "invalid"
        ? "The shop in this link is not valid."
        : "The previously selected shop is no longer available to you.";
  return `${reason} Showing ${allLabel}.`;
}

export function ShopContextProvider({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  const pathname = usePathname();
  const search = useSearchParams();
  const router = useRouter();
  const applies = isShopAwarePath(pathname);
  const urlShop = applies ? search.get(SHOP_PARAM) || null : null;

  const [remembered, setRemembered] = useState<string | null>(urlShop);
  const [data, setData] = useState<ShopOptions | null>(null);
  const [status, setStatus] = useState<Status>(enabled ? "loading" : "disabled");
  const [revoked, setRevoked] = useState(false);
  const [notice, setNotice] = useState<ShopContextNotice | null>(null);
  const [tick, setTick] = useState(0);
  const request = useRef(0);

  // On shop-aware pages the URL decides; elsewhere the last selection is kept for links.
  const [seenUrl, setSeenUrl] = useState<{ applies: boolean; shop: string | null }>({ applies, shop: urlShop });
  if (seenUrl.applies !== applies || seenUrl.shop !== urlShop) {
    setSeenUrl({ applies, shop: urlShop });
    if (applies) setRemembered(urlShop);
  }
  const active = enabled && !revoked;
  const selectedId = active ? (applies ? urlShop : remembered) : null;

  // Latest navigation values for the async fetch callback (keeps the effect's
  // dependencies to what should trigger a refresh).
  const latest = useRef({ applies, urlShop, pathname, router });
  useEffect(() => {
    latest.current = { applies, urlShop, pathname, router };
  });

  const dropSelection = useCallback((message: string) => {
    const now = latest.current;
    setRemembered(null);
    setNotice({ tone: "warning", message });
    if (now.applies && now.urlShop) now.router.replace(now.pathname);
  }, []);

  useEffect(() => {
    if (!active) return;
    const id = ++request.current;
    const query = new URLSearchParams(selectedId ? { selected: selectedId } : {});
    apiFetch<ShopOptions>(`/company/shop-options?${query}`)
      .then((result) => {
        if (id !== request.current) return;
        setData(result);
        setStatus("ready");
        const verdict = result.selection.status;
        if (selectedId && verdict !== "active") dropSelection(fallbackMessage(verdict, result.access.all_label));
      })
      .catch((error: unknown) => {
        if (id !== request.current) return;
        if (error instanceof ApiError && error.status === 403 && error.code === "permission_denied") {
          // Role changed: the account no longer uses a shop context.
          setRevoked(true);
          setData(null);
          if (selectedId) dropSelection("Shop selection is no longer available for your account.");
          return;
        }
        setStatus("error");
      });
    // pathname: refresh from the server on every navigation.
  }, [active, selectedId, pathname, tick, dropSelection]);

  // Catch deactivations or renames made elsewhere while this tab was in the background.
  useEffect(() => {
    if (!active) return;
    const onVisible = () => document.visibilityState === "visible" && setTick((t) => t + 1);
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [active]);

  const select = useCallback(
    (shopId: string | null) => {
      if (!active || !applies) return;
      setNotice(null);
      // push, not replace: Back returns to the previous selection.
      router.push(shopId ? withShop(pathname, shopId) : pathname);
    },
    [active, applies, pathname, router],
  );

  const value = useMemo<ShopContextValue>(() => {
    if (!active) return { ...DISABLED, notice, dismissNotice: () => setNotice(null) };
    const options = data?.items ?? [];
    const verdict = data?.selection;
    const selected =
      selectedId === null
        ? null
        : (options.find((o) => o.id === selectedId) ??
          (verdict?.status === "active" && verdict.shop?.id === selectedId ? verdict.shop : null));
    return {
      enabled: true,
      access: data ? { mode: data.access.mode, allLabel: data.access.all_label } : COMPANY_ACCESS,
      accessKnown: data !== null,
      status,
      options,
      truncated: data?.truncated ?? false,
      applies,
      selectedId,
      selected,
      notice,
      dismissNotice: () => setNotice(null),
      select,
      retry: () => {
        setStatus("loading");
        setTick((t) => t + 1);
      },
      hrefFor: (href) => withShop(href, selectedId),
    };
  }, [active, data, status, applies, selectedId, notice, select]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}
