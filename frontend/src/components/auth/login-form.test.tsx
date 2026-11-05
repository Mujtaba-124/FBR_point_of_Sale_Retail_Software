/**
 * Regression tests for the login â†’ logout â†’ login bug.
 *
 * Root cause: with Cache Components, Next.js hides visited routes with
 * React <Activity> instead of unmounting them, so the login form came back
 * after sign-out still in its "Signing inâ€¦" (disabled) state and still
 * holding the typed password. <Activity> is used directly here to reproduce
 * exactly what the router does.
 */
import { Activity, type ReactNode } from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "@/components/auth/login-form";
import { ApiError } from "@/lib/api/client";
import type { CurrentUser } from "@/lib/api/types";
import { signIn } from "@/lib/auth";
import { hardNavigate } from "@/lib/navigation";

vi.mock("@/lib/auth", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/auth")>()),
  signIn: vi.fn(),
}));
vi.mock("@/lib/navigation", () => ({ hardNavigate: vi.fn() }));

const mockedSignIn = vi.mocked(signIn);
const mockedNavigate = vi.mocked(hardNavigate);

const companyAdmin: CurrentUser = {
  id: "1",
  email: "admin@example.test",
  full_name: "Admin",
  access_category: "company_admin",
  workspace: "company",
};
const superAdmin: CurrentUser = {
  ...companyAdmin,
  id: "2",
  access_category: "super_admin",
  workspace: "super_admin",
};

function Harness({ visible, children }: { visible: boolean; children: ReactNode }) {
  return <Activity mode={visible ? "visible" : "hidden"}>{children}</Activity>;
}

const submitButton = () => screen.getByRole("button", { name: /sign(ing)? in/i });
const passwordInput = () => screen.getByLabelText("Password") as HTMLInputElement;

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>, password = "secret-pass-1") {
  await user.clear(screen.getByLabelText("Email Address"));
  await user.type(screen.getByLabelText("Email Address"), "admin@example.test");
  await user.clear(passwordInput());
  await user.type(passwordInput(), password);
  await user.click(submitButton());
}

beforeEach(() => {
  mockedSignIn.mockReset();
  mockedNavigate.mockReset();
});
afterEach(cleanup);

describe("LoginForm session lifecycle", () => {
  it("is usable again (not stuck, no password kept) after being hidden and re-shown", async () => {
    const user = userEvent.setup({ delay: null });
    mockedSignIn.mockResolvedValue(companyAdmin);
    const { rerender } = render(
      <Harness visible>
        <LoginForm />
      </Harness>,
    );

    await fillAndSubmit(user);
    await waitFor(() => expect(mockedNavigate).toHaveBeenCalledWith("/company"));
    expect(submitButton()).toHaveProperty("disabled", true); // loading while navigating

    // Router hides the login route (user is in the workspace)...
    rerender(
      <Harness visible={false}>
        <LoginForm />
      </Harness>,
    );
    // ...and restores it after sign-out.
    rerender(
      <Harness visible>
        <LoginForm />
      </Harness>,
    );

    expect(submitButton().textContent).toBe("Sign In");
    expect(submitButton()).toHaveProperty("disabled", false);
    expect(passwordInput().value).toBe("");

    // And signing in again works without a reload.
    mockedSignIn.mockResolvedValue(superAdmin);
    await fillAndSubmit(user);
    await waitFor(() => expect(mockedNavigate).toHaveBeenLastCalledWith("/super-admin"));
    expect(mockedSignIn).toHaveBeenCalledTimes(2);
  });

  it("survives five consecutive login/hide/show cycles", async () => {
    const user = userEvent.setup({ delay: null });
    mockedSignIn.mockResolvedValue(companyAdmin);
    const { rerender } = render(
      <Harness visible>
        <LoginForm />
      </Harness>,
    );
    for (let i = 0; i < 5; i++) {
      await fillAndSubmit(user);
      await waitFor(() => expect(mockedNavigate).toHaveBeenCalledTimes(i + 1));
      rerender(<Harness visible={false}><LoginForm /></Harness>);
      rerender(<Harness visible><LoginForm /></Harness>);
      expect(submitButton()).toHaveProperty("disabled", false);
    }
    expect(mockedSignIn).toHaveBeenCalledTimes(5);
  });

  it("uses a full page navigation to the workspace returned by the backend", async () => {
    const user = userEvent.setup({ delay: null });
    mockedSignIn.mockResolvedValue(superAdmin);
    render(<LoginForm />);
    await fillAndSubmit(user);
    await waitFor(() => expect(mockedNavigate).toHaveBeenCalledWith("/super-admin"));
  });

  it("resets the loading state on failure, then accepts valid credentials", async () => {
    const user = userEvent.setup({ delay: null });
    mockedSignIn.mockRejectedValueOnce(
      new ApiError(401, "invalid_credentials", "Invalid email or password."),
    );
    render(<LoginForm />);

    await fillAndSubmit(user, "wrong-pass");
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "Invalid email or password.",
    );
    expect(submitButton().textContent).toBe("Sign In");
    expect(submitButton()).toHaveProperty("disabled", false);

    mockedSignIn.mockResolvedValueOnce(companyAdmin);
    await fillAndSubmit(user);
    await waitFor(() => expect(mockedNavigate).toHaveBeenCalledWith("/company"));
  });

  it.each([
    [new ApiError(0, "network_error", "Unable to reach the server. Check your connection and try again.")],
    [new ApiError(503, "service_unavailable", "Sign-in is temporarily unavailable. Try again shortly.")],
    [new ApiError(500, "server_error", "Something went wrong on our side. Please try again.")],
    [new Error("unexpected")],
  ])("shows a safe message and recovers from %s", async (error) => {
    const user = userEvent.setup({ delay: null });
    mockedSignIn.mockRejectedValueOnce(error);
    render(<LoginForm />);
    await fillAndSubmit(user);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toBe("");
    expect(alert.textContent).not.toContain("unexpected");
    expect(submitButton()).toHaveProperty("disabled", false);
    expect(mockedNavigate).not.toHaveBeenCalled();
  });

  it("ignores duplicate submissions while a sign-in is in flight", async () => {
    const user = userEvent.setup({ delay: null });
    let resolve: (u: CurrentUser) => void = () => {};
    mockedSignIn.mockImplementation(() => new Promise((r) => (resolve = r)));
    render(<LoginForm />);

    await fillAndSubmit(user);
    await user.keyboard("{Enter}");
    await user.keyboard("{Enter}");
    expect(mockedSignIn).toHaveBeenCalledTimes(1);

    await act(async () => resolve(companyAdmin));
    expect(mockedNavigate).toHaveBeenCalledTimes(1);
  });

  it("never falls back to a GET submission that would put the password in the URL", () => {
    render(<LoginForm />);
    const form = screen.getByRole("form", { name: "Sign in" });
    expect(form.getAttribute("method")).toBe("post");
  });

  it("resets when the page is restored from the back/forward cache", async () => {
    const user = userEvent.setup({ delay: null });
    mockedSignIn.mockResolvedValue(companyAdmin);
    render(<LoginForm />);
    await fillAndSubmit(user);
    await waitFor(() => expect(submitButton()).toHaveProperty("disabled", true));

    const event = new Event("pageshow");
    Object.defineProperty(event, "persisted", { value: true });
    act(() => {
      window.dispatchEvent(event);
    });

    expect(submitButton()).toHaveProperty("disabled", false);
    expect(passwordInput().value).toBe("");
  });
});
