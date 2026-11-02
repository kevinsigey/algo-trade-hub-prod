import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { SectorTonePanel } from "@/components/SectorTonePanel";

vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: null } }), onAuthStateChange: () => ({ data: { subscription: { unsubscribe: () => {} } } }) } },
}));

afterEach(() => vi.unstubAllGlobals());

describe("SectorTonePanel", () => {
  it("renders every sector's tone and z, with a dash for an unreadable basket", async () => {
    const body = {
      as_of: "2026-11-01",
      sectors: [
        { sector: "energy", basket: "ENERGY", etf: "XLE", tone_day: "2026-10-31", tone: -4.25, z: -1.83 },
        { sector: "technology", basket: "TECHNOLOGY", etf: "XLK", tone_day: null, tone: null, z: null },
      ],
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => body })) as unknown as typeof fetch);
    render(<SectorTonePanel />);
    await waitFor(() => expect(screen.getByText("energy")).toBeTruthy());
    expect(screen.getByText("XLE")).toBeTruthy();
    expect(screen.getByText("-1.83")).toBeTruthy();
    expect(screen.getByText("technology")).toBeTruthy();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });

  it("renders nothing when the read fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("down"); }) as unknown as typeof fetch);
    const { container } = render(<SectorTonePanel />);
    await waitFor(() => expect(container.textContent).toBe(""));
  });
});
