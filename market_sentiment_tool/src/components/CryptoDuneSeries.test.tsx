import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/getJson", () => ({ getJson: vi.fn() }));
import { getJson } from "@/lib/getJson";
import CryptoDuneSeries from "@/components/CryptoDuneSeries";

const mockGet = vi.mocked(getJson);

describe("CryptoDuneSeries", () => {
  it("shows the cached series as one aggregate line", async () => {
    mockGet.mockResolvedValue({ series: [{
      key: "USDT_REMIT_COST", query_id: 8877269, value_column: "crypto_total_cost",
      n_points: 184, first_date: "2026-04-01", last_date: "2026-10-01", updated_at: "2026-11-03T14:00:00Z",
    }]});
    render(<CryptoDuneSeries />);
    expect(await screen.findByText("USDT_REMIT_COST")).toBeInTheDocument();
    expect(screen.getByText(/184 days/)).toBeInTheDocument();
    expect(screen.getByText(/Oct 1, 2026/)).toBeInTheDocument();
  });

  it("renders nothing when the cache is empty", async () => {
    mockGet.mockResolvedValue({ series: [] });
    const { container } = render(<CryptoDuneSeries />);
    await new Promise((r) => setTimeout(r, 20));
    expect(container.textContent).toBe("");
  });
});
