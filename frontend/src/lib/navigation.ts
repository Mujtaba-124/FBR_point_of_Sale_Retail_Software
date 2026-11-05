/**
 * Full-page navigation for authentication transitions (sign-in / sign-out).
 *
 * With Cache Components, client-side navigation keeps previously visited
 * routes mounted but hidden (React <Activity>) and restores their state on
 * return. After a change of identity that state must not survive: a preserved
 * login form would come back stuck in its "Signing in…" state and still hold
 * the typed password, and a preserved workspace could show the previous
 * user's data. A full page load discards all client-side state.
 * See node_modules/next/dist/docs/01-app/02-guides/preserving-ui-state.md.
 */
export function hardNavigate(path: string): void {
  window.location.replace(path);
}
