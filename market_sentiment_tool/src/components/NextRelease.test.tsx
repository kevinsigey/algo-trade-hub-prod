import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NextRelease, headline, strikeOf, type Preview } from "./NextRelease";

const row = (target: string, probability: number, market_prob: number | null, payload = {}): Preview => ({
  target, forecaster: "labor_nowcast", forecaster_version: "labor-v1", family: "labor",
  close_at: "2026-11-06T13:29:00Z", probability, market_prob, payload: { mu_k: 112.4, ...payload }, computed_at: "2026-10-29T00:00:00Z",
});

describe("NextRelease", () => {
  it("reads jobs strikes in thousands and CPI strikes in percent", () => {
    expect(strikeOf("kalshi:KXPAYROLLS-26OCT-T100000", "labor")).toBe("100k");
    expect(strikeOf("kalshi:KXCPI-26OCT-T0.3", "cpi")).toBe("0.3%");
  });

  it("shows the estimate, the date, and ours beside Kalshi's, sorted by strike", () => {
    render(<NextRelease family="labor" title="Next jobs report" previews={[
      row("kalshi:KXPAYROLLS-26OCT-T200000", 0.12, 0.2), row("kalshi:KXPAYROLLS-26OCT-T100000", 0.52, 0.6)]} />);
    expect(screen.getByText("112k jobs")).toBeTruthy();
    expect(screen.getByText(/not locked in/)).toBeTruthy();
    const cells = screen.getAllByRole("row").slice(1).map((r) => r.textContent);
    expect(cells).toEqual(["100k52%60%", "200k12%20%"]);
  });

  it("shows only the next release when a later month is also open", () => {
    const later = { ...row("kalshi:KXPAYROLLS-26NOV-T100000", 0.9, 0.9), close_at: "2026-12-04T13:29:00Z" };
    render(<NextRelease family="labor" title="Next jobs report" previews={[later, row("kalshi:KXPAYROLLS-26OCT-T100000", 0.52, 0.6)]} />);
    expect(screen.getAllByRole("row")).toHaveLength(2); // header + the October strike only
    expect(screen.getByText("52%")).toBeTruthy();
    expect(screen.queryByText("90%")).toBeNull();
  });

  it("renders nothing when there is no preview for that family", () => {
    const { container } = render(<NextRelease family="cpi" title="x" previews={[row("kalshi:KXPAYROLLS-26OCT-T0", 0.9, 0.9)]} />);
    expect(container.firstChild).toBeNull();
  });

  it("has no headline without the model's own number", () => {
    expect(headline([row("t", 0.5, 0.5, { mu_k: null })], "labor")).toBeNull();
  });
});
