import type { Metadata } from "next";

import { AccessDenied } from "@/components/auth/access-denied";

export const metadata: Metadata = {
  title: "Access Denied | Cheena FBR POS Software",
  robots: { index: false },
};

/** Target of the proxy's 403 rewrite when a user opens another workspace. */
export default function AccessDeniedPage() {
  return <AccessDenied />;
}
