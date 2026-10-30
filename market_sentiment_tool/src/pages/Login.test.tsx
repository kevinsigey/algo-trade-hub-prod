import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Login from "@/pages/Login";

const auth = vi.hoisted(() => ({
  listener: null as null | ((event: string) => void),
  updateUser: vi.fn(async () => ({ error: null })),
  resetPasswordForEmail: vi.fn(async () => ({ error: null })),
  signInWithPassword: vi.fn(async () => ({ error: null })),
}));
vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      onAuthStateChange: (cb: (event: string) => void) => {
        auth.listener = cb;
        return { data: { subscription: { unsubscribe() {} } } };
      },
      updateUser: auth.updateUser,
      resetPasswordForEmail: auth.resetPasswordForEmail,
      signInWithPassword: auth.signInWithPassword,
    },
  },
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Login", () => {
  it("sends a reset link that comes back to this site's login page", async () => {
    render(<MemoryRouter><Login /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "k@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    await waitFor(() => expect(auth.resetPasswordForEmail).toHaveBeenCalledWith("k@example.com", { redirectTo: `${window.location.origin}/login` }));
    expect(await screen.findByText(/Check your email/)).toBeInTheDocument();
  });

  it("asks for a new password when a recovery link opens it", async () => {
    render(<MemoryRouter><Login /></MemoryRouter>);
    act(() => auth.listener?.("PASSWORD_RECOVERY"));
    fireEvent.change(await screen.findByLabelText("New password"), { target: { value: "a-long-pass-123" } });
    fireEvent.change(screen.getByLabelText("New password again"), { target: { value: "a-long-pass-124" } });
    fireEvent.click(screen.getByRole("button", { name: "Set password" }));
    expect(await screen.findByText("The two passwords don't match.")).toBeInTheDocument();
    expect(auth.updateUser).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("New password again"), { target: { value: "a-long-pass-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Set password" }));
    await waitFor(() => expect(auth.updateUser).toHaveBeenCalledWith({ password: "a-long-pass-123" }));
  });
});
