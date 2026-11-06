import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  passwordProblem,
  readTokenFromHash,
  SetPasswordForm,
} from "@/components/auth/set-password-form";
import { ApiError, apiFetch } from "@/lib/api/client";

vi.mock("@/lib/api/client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/client")>()),
  apiFetch: vi.fn(),
}));
const mockedFetch = vi.mocked(apiFetch);
beforeEach(() => {
  mockedFetch.mockReset();
  window.history.replaceState(null, "", "/set-password#token=tok_abc");
});
afterEach(cleanup);

const INFO = { full_name: "New Person", email: "ne***@example.test", expires_at: "2026-11-09T00:00:00Z" };

describe("Set password", () => {
  it("reads the token from the fragment and removes it from the address bar", async () => {
    mockedFetch.mockResolvedValue(INFO);
    render(<SetPasswordForm />);
    expect(await screen.findByText("New Person")).toBeTruthy();
    expect(window.location.hash).toBe("");
    expect(JSON.parse(String(mockedFetch.mock.calls[0][1]?.body))).toEqual({ token: "tok_abc" });
  });

  it("sets the password once and offers sign-in", async () => {
    const user = userEvent.setup();
    mockedFetch.mockResolvedValueOnce(INFO).mockResolvedValueOnce(undefined);
    render(<SetPasswordForm />);
    await screen.findByText("New Person");
    await user.type(screen.getByLabelText("New password"), "Correct-Horse-42");
    await user.type(screen.getByLabelText("Confirm password"), "Correct-Horse-42");
    await user.click(screen.getByRole("button", { name: "Set password" }));
    expect(await screen.findByText(/Your password is set/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Sign in" }).getAttribute("href")).toBe("/login");
    expect(JSON.parse(String(mockedFetch.mock.calls[1][1]?.body))).toEqual({
      token: "tok_abc", password: "Correct-Horse-42",
    });
  });

  it("validates the password before sending", async () => {
    const user = userEvent.setup();
    mockedFetch.mockResolvedValue(INFO);
    render(<SetPasswordForm />);
    await screen.findByText("New Person");
    await user.type(screen.getByLabelText("New password"), "short");
    await user.click(screen.getByRole("button", { name: "Set password" }));
    expect(screen.getByText("Use at least 12 characters.")).toBeTruthy();
    expect(mockedFetch).toHaveBeenCalledTimes(1);
    expect(passwordProblem("Correct-Horse-42", "Different-Horse-42")).toBe("The passwords do not match.");
  });

  it("explains an invalid, expired or used link", async () => {
    mockedFetch.mockRejectedValueOnce(new ApiError(400, "invalid_setup_link", "This setup link is invalid, expired or already used."));
    render(<SetPasswordForm />);
    expect(await screen.findByText(/invalid, expired or already used/)).toBeTruthy();
  });

  it("handles a missing token without calling the API", async () => {
    window.history.replaceState(null, "", "/set-password");
    render(<SetPasswordForm />);
    await waitFor(() => expect(screen.getByText(/Ask your Company Admin for a new link/)).toBeTruthy());
    expect(mockedFetch).not.toHaveBeenCalled();
    expect(readTokenFromHash("#token=a")).toBe("a");
    expect(readTokenFromHash("#x=1")).toBeNull();
  });
});
