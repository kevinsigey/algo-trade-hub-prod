import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import Login, { RecoveryRedirect } from "@/pages/Login";

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
      getSession: async () => ({ data: { session: null } }),
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


describe("a reset link that lands anywhere on the site", () => {
  it("is sent to the new-password form instead of just signing in", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <RecoveryRedirect />
        <Routes>
          <Route path="/" element={<p>Portfolio</p>} />
          <Route path="/login" element={<Login />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("Portfolio")).toBeInTheDocument();
    act(() => auth.listener?.("PASSWORD_RECOVERY"));
    expect(await screen.findByRole("heading", { name: "Set a new password" })).toBeInTheDocument();
  });

  it("opens the form when /login is reached with reset=1", () => {
    render(<MemoryRouter initialEntries={["/login?reset=1"]}><Login /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Set a new password" })).toBeInTheDocument();
  });
});
