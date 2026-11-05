import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LogoutButton } from "@/components/auth/logout-button";
import { ApiError } from "@/lib/api/client";
import { signOut } from "@/lib/auth";
import { hardNavigate } from "@/lib/navigation";

vi.mock("@/lib/auth", () => ({ signOut: vi.fn() }));
vi.mock("@/lib/navigation", () => ({ hardNavigate: vi.fn() }));

const mockedSignOut = vi.mocked(signOut);
const mockedNavigate = vi.mocked(hardNavigate);

beforeEach(() => {
  mockedSignOut.mockReset();
  mockedNavigate.mockReset();
});
afterEach(cleanup);

describe("LogoutButton", () => {
  it("signs out, then does a full page load of /login", async () => {
    mockedSignOut.mockResolvedValue(undefined);
    render(<LogoutButton />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(mockedNavigate).toHaveBeenCalledWith("/login"));
  });

  it("shows the error and becomes clickable again when sign-out fails", async () => {
    mockedSignOut.mockRejectedValue(
      new ApiError(403, "csrf_failed", "The request could not be verified."),
    );
    render(<LogoutButton />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "The request could not be verified.",
    );
    expect(screen.getByRole("button", { name: "Sign out" })).toHaveProperty("disabled", false);
    expect(mockedNavigate).not.toHaveBeenCalled();
  });

  it("ignores repeated clicks while signing out", async () => {
    mockedSignOut.mockImplementation(() => new Promise(() => {}));
    render(<LogoutButton />);
    const user = userEvent.setup();
    const button = screen.getByRole("button", { name: "Sign out" });
    await user.click(button);
    await user.click(button);
    expect(mockedSignOut).toHaveBeenCalledTimes(1);
  });
});
