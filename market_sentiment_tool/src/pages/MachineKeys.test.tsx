import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import MachineKeys from "@/pages/MachineKeys";
import { adminJson } from "@/lib/workshop";

vi.mock("@/lib/workshop", () => ({ adminJson: vi.fn() }));
const mockAdmin = vi.mocked(adminJson);

const KEY_ROW = {
  id: 3,
  label: "mac scripts",
  scopes: ["orders:place"],
  max_qty: 100,
  max_notional: 25000,
  daily_cap: 50,
  created_at: "2026-11-01T12:00:00+00:00",
  last_used_at: null,
  revoked_at: null,
};

describe("MachineKeys page", () => {
  beforeEach(() => {
    mockAdmin.mockReset();
  });

  it("lists keys from the admin API", async () => {
    mockAdmin.mockResolvedValue({ keys: [KEY_ROW] });
    render(<MachineKeys />);
    expect(await screen.findByText("mac scripts")).toBeTruthy();
    expect(screen.getByText("Active")).toBeTruthy();
    expect(screen.getByText(/max 100 shares/)).toBeTruthy();
  });

  it("shows a freshly created key exactly in the once-only banner", async () => {
    mockAdmin
      .mockResolvedValueOnce({ keys: [] }) // initial load
      .mockResolvedValueOnce({ ...KEY_ROW, key: "thk_0123456789abcdef0123456789abcdef" }) // create
      .mockResolvedValueOnce({ keys: [KEY_ROW] }); // reload
    render(<MachineKeys />);
    await screen.findByText("No keys yet.");
    fireEvent.change(screen.getByPlaceholderText("mac scripts"), { target: { value: "mac scripts" } });
    fireEvent.click(screen.getByLabelText("orders:place"));
    fireEvent.click(screen.getByText("Create key"));
    expect(await screen.findByText("thk_0123456789abcdef0123456789abcdef")).toBeTruthy();
    expect(screen.getByText(/Copy this key now/)).toBeTruthy();
    const createCall = mockAdmin.mock.calls.find((c) => c[0] === "/api/admin/keys" && c[1]?.method === "POST");
    expect(createCall).toBeTruthy();
    expect(JSON.parse(String(createCall?.[1]?.body)).scopes).toEqual(["orders:place"]);
  });

  it("offers classifications:write and can create a key holding only it", async () => {
    const clsRow = { ...KEY_ROW, id: 4, label: "muse classifications", scopes: ["classifications:write"] };
    mockAdmin
      .mockResolvedValueOnce({ keys: [] }) // initial load
      .mockResolvedValueOnce({ ...clsRow, key: "thk_0123456789abcdef0123456789abcdef" }) // create
      .mockResolvedValueOnce({ keys: [clsRow] }); // reload
    render(<MachineKeys />);
    await screen.findByText("No keys yet.");
    // The scope is offered in the New key form…
    const clsBox = screen.getByLabelText("classifications:write") as HTMLInputElement;
    expect(clsBox.type).toBe("checkbox");
    // …and grantable on its own: tick only it (no scope is ticked by default).
    fireEvent.change(screen.getByPlaceholderText("mac scripts"), { target: { value: "muse classifications" } });
    fireEvent.click(clsBox);
    const createButton = screen.getByText("Create key") as HTMLButtonElement;
    expect(createButton.disabled).toBe(false);
    fireEvent.click(createButton);
    expect(await screen.findByText("thk_0123456789abcdef0123456789abcdef")).toBeTruthy();
    const createCall = mockAdmin.mock.calls.find((c) => c[0] === "/api/admin/keys" && c[1]?.method === "POST");
    expect(createCall).toBeTruthy();
    expect(JSON.parse(String(createCall?.[1]?.body)).scopes).toEqual(["classifications:write"]);
  });

  it("revokes through a two-step confirm", async () => {
    mockAdmin
      .mockResolvedValueOnce({ keys: [KEY_ROW] })
      .mockResolvedValueOnce({ ...KEY_ROW, revoked_at: "2026-11-01T13:00:00+00:00" })
      .mockResolvedValueOnce({ keys: [{ ...KEY_ROW, revoked_at: "2026-11-01T13:00:00+00:00" }] });
    render(<MachineKeys />);
    await screen.findByText("mac scripts");
    fireEvent.click(screen.getByText("Revoke"));
    fireEvent.click(screen.getByText("Confirm revoke"));
    await waitFor(() =>
      expect(mockAdmin.mock.calls.some((c) => c[0] === "/api/admin/keys/3/revoke")).toBe(true),
    );
    expect(await screen.findByText(/Revoked/)).toBeTruthy();
  });

  it("starts with no scope ticked and cannot create a key until one is picked", async () => {
    mockAdmin.mockResolvedValue({ keys: [] });
    render(<MachineKeys />);
    await screen.findByText("No keys yet.");
    fireEvent.change(screen.getByPlaceholderText("mac scripts"), { target: { value: "mac scripts" } });
    for (const box of screen.getAllByRole("checkbox")) {
      expect((box as HTMLInputElement).checked).toBe(false);
    }
    const createButton = screen.getByText("Create key") as HTMLButtonElement;
    expect(createButton.disabled).toBe(true);
    expect(screen.getByText("Pick at least one scope.")).toBeTruthy();
  });

  it("enables creation once a scope is ticked", async () => {
    mockAdmin.mockResolvedValue({ keys: [] });
    render(<MachineKeys />);
    await screen.findByText("No keys yet.");
    fireEvent.change(screen.getByPlaceholderText("mac scripts"), { target: { value: "mac scripts" } });
    fireEvent.click(screen.getByLabelText("orders:read"));
    const createButton = screen.getByText("Create key") as HTMLButtonElement;
    expect(createButton.disabled).toBe(false);
    expect(screen.queryByText("Pick at least one scope.")).toBeNull();
  });
});
