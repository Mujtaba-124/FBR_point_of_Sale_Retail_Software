import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MobileNav } from "@/components/super-admin/mobile-nav";
import { SidebarNav } from "@/components/super-admin/sidebar-nav";
import { ProfileCard } from "@/components/super-admin/sidebar-profile";
import { signOut } from "@/lib/auth";
import { hardNavigate } from "@/lib/navigation";

const pathname = vi.hoisted(() => ({ value: "/super-admin" }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathname.value,
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }),
  redirect: vi.fn(),
}));
vi.mock("next/headers", () => ({ headers: vi.fn() }));
vi.mock("@/lib/auth", () => ({ signOut: vi.fn() }));
vi.mock("@/lib/navigation", () => ({ hardNavigate: vi.fn() }));

beforeEach(() => {
  pathname.value = "/super-admin";
  vi.mocked(signOut).mockReset();
  vi.mocked(hardNavigate).mockReset();
});
afterEach(cleanup);

describe("SidebarNav", () => {
  it("lists only the Super Admin modules", () => {
    render(<SidebarNav />);
    const nav = screen.getByRole("navigation", { name: "Super Admin" });
    const links = nav.querySelectorAll("a");
    expect([...links].map((a) => a.getAttribute("href"))).toEqual([
      "/super-admin",
      "/super-admin/subscription",
      "/super-admin/email-settings",
    ]);
    expect(nav.textContent).not.toMatch(/Shop|Invoice|Upload|FBR|Report|Users/);
  });

  it("marks the current page", () => {
    pathname.value = "/super-admin/email-settings";
    render(<SidebarNav />);
    expect(screen.getByRole("link", { name: /Email Settings/ }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(screen.getByRole("link", { name: /^Dashboard/ }).getAttribute("aria-current")).toBeNull();
  });

  it("shows every Super Admin module as available", () => {
    render(<SidebarNav />);
    expect(screen.getByRole("link", { name: "Subscription Management" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Email Settings" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeTruthy();
    expect(screen.queryByText(/not available yet/)).toBeNull();
  });
});

describe("MobileNav", () => {
  it("opens the drawer from the menu button and closes it with Escape", async () => {
    const user = userEvent.setup();
    render(<MobileNav profile={<p>profile slot</p>} />);

    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Open navigation menu" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toMatch(/Dashboard/);
    expect(dialog.textContent).toMatch(/profile slot/);

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("closes after choosing a destination", async () => {
    const user = userEvent.setup();
    render(<MobileNav profile={null} />);
    await user.click(screen.getByRole("button", { name: "Open navigation menu" }));
    const dialog = await screen.findByRole("dialog");
    const link = [...dialog.querySelectorAll("a")].find((a) => a.textContent?.includes("Email Settings"))!;
    link.addEventListener("click", (e) => e.preventDefault()); // stay in jsdom
    await user.click(link);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("ProfileCard", () => {
  it("shows the signed-in Super Admin and signs out with a full page load", async () => {
    vi.mocked(signOut).mockResolvedValue(undefined);
    render(<ProfileCard name="Super Admin Person" email="owner@example.test" />);

    expect(screen.getByText("Super Admin Person")).toBeTruthy();
    expect(screen.getByText("owner@example.test")).toBeTruthy();
    expect(screen.getByText("SP")).toBeTruthy();

    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(hardNavigate).toHaveBeenCalledWith("/login"));
  });
});
