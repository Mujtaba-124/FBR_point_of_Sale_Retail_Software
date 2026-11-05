import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "@/components/auth/login-form";
import { SubscriptionRestricted } from "@/components/auth/subscription-restricted";
import { ApiError } from "@/lib/api/client";
import { signIn, signOut } from "@/lib/auth";
import { hardNavigate } from "@/lib/navigation";

vi.mock("@/lib/auth", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/auth")>()),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("@/lib/navigation", () => ({ hardNavigate: vi.fn() }));

beforeEach(() => {
  vi.mocked(signIn).mockReset();
  vi.mocked(signOut).mockReset();
  vi.mocked(hardNavigate).mockReset();
});
afterEach(cleanup);

const EXPIRED =
  "Your software subscription has expired. Please contact your administrator for renewal.";

describe("Expired subscription at sign-in", () => {
  it("shows the backend message by code, never redirects, and resets the button", async () => {
    const user = userEvent.setup({ delay: null });
    vi.mocked(signIn).mockRejectedValue(new ApiError(403, "subscription_expired", EXPIRED));
    render(<LoginForm />);

    await user.type(screen.getByLabelText("Email Address"), "admin@example.test");
    await user.type(screen.getByLabelText("Password"), "secret-pass-1");
    await user.click(screen.getByRole("button", { name: "Sign In" }));

    expect((await screen.findByRole("alert")).textContent).toBe(EXPIRED);
    expect(hardNavigate).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Sign In" })).toHaveProperty("disabled", false);
  });

  it.each([
    ["subscription_not_started", "Your software subscription has not started yet. Please contact your administrator."],
    ["subscription_not_configured", "Your software subscription is not active. Please contact your administrator."],
  ])("shows the backend message for %s", async (code, message) => {
    const user = userEvent.setup({ delay: null });
    vi.mocked(signIn).mockRejectedValue(new ApiError(403, code, message));
    render(<LoginForm />);
    await user.type(screen.getByLabelText("Email Address"), "user@example.test");
    await user.type(screen.getByLabelText("Password"), "secret-pass-1");
    await user.click(screen.getByRole("button", { name: "Sign In" }));
    expect((await screen.findByRole("alert")).textContent).toBe(message);
  });
});

describe("SubscriptionRestricted", () => {
  it("explains the block, offers only Sign Out, and shows no business or admin controls", async () => {
    vi.mocked(signOut).mockResolvedValue(undefined);
    render(<SubscriptionRestricted code="subscription_expired" />);

    expect(screen.getByRole("alert").textContent).toMatch(/Subscription expired/);
    expect(screen.getByText(EXPIRED)).toBeTruthy();
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Sign out"]);
    expect(screen.queryByRole("link")).toBeNull(); // no Super Admin navigation
    expect(screen.queryByRole("button", { name: /renew/i })).toBeNull(); // no renewal control

    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(hardNavigate).toHaveBeenCalledWith("/login"));
  });

  it.each([
    ["subscription_not_started", /not started yet/],
    ["subscription_not_configured", /not active/],
  ] as const)("renders the %s state", (code, text) => {
    render(<SubscriptionRestricted code={code} />);
    expect(screen.getByRole("alert").textContent).toMatch(text);
  });
});
