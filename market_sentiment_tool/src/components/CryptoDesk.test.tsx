import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import CryptoDesk from "@/components/CryptoDesk";

const DESK = {
  as_of: "2026-11-03T08:00:00Z",
  sources: { fees: "live", revenue: "live", protocols: "live", chains: "live", markets: "live" },
  rows: [
    { key: "lido", name: "Lido", kind: "protocol", symbol: "LDO", price: 0.32, change_24h: 1.2,
      mcap: 269_000_000, fdv: 324_000_000, fees_24h: 1_489_590, revenue_24h: 90_509,
      pf: 0.5, ps: 9.8, fee_trend_7d: -47.3, fee_trend_30d: -12.0, tvl: 21_800_000_000 },
    { key: "base", name: "Base", kind: "network", symbol: null, price: null, change_24h: null,
      mcap: null, fdv: null, fees_24h: 74_443, revenue_24h: 74_089,
      pf: null, ps: null, fee_trend_7d: -5.1, fee_trend_30d: 2.0, tvl: 5_900_000_000 },
    { key: "hyperliquid", name: "Hyperliquid", kind: "protocol", symbol: "HYPE", price: 83.09, change_24h: -2.0,
      mcap: 19_900_000_000, fdv: 83_000_000_000, fees_24h: 3_203_109, revenue_24h: 2_390_506,
      pf: 17.0, ps: 90.6, fee_trend_7d: -0.3, fee_trend_30d: 4.0, tvl: 8_200_000_000 },
  ],
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("CryptoDesk", () => {
  it("renders the desk rows with multiples, compact money and honest nulls", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(DESK), { status: 200 })));
    render(<CryptoDesk />);
    expect(await screen.findByText("Lido")).toBeInTheDocument();
    expect(screen.getByText("0.5×")).toBeInTheDocument();
    expect(screen.getByText("$1.5M")).toBeInTheDocument(); // Lido fees, compact
    expect(screen.getByText("$21.8B")).toBeInTheDocument(); // Lido TVL
    // Base has no token: price and multiples read as dashes, fees still show.
    expect(screen.getByText(/no reliable free/)).toBeInTheDocument();
    const baseRow = screen.getByText("Base").closest("tr")!;
    expect(baseRow.textContent).toContain("$74.4K");
    expect(baseRow.textContent).toContain("network");
  });

  it("re-sorts by fees on demand", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(DESK), { status: 200 })));
    const { container } = render(<CryptoDesk />);
    await screen.findByText("Lido");
    fireEvent.click(screen.getByRole("button", { name: "Fees" }));
    const firstRow = container.querySelector("tbody tr");
    expect(firstRow?.textContent).toContain("Hyperliquid"); // highest fees first
  });

  it("shows a plain unavailable line when the desk cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 503 })));
    render(<CryptoDesk />);
    expect(await screen.findByText(/could not be reached/)).toBeInTheDocument();
  });
});
