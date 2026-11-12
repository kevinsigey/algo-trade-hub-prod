import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { FifteenDeclineMonitor, type DeclineRow } from "@/components/FifteenDeclineMonitor";

const cell = (trades: number, pnl: number | null) => ({ trades, pnl_per_trade: pnl });
const ROWS: DeclineRow[] = [
  { day: "2026-11-12", series: "Natural gas", live: cell(12, 0.025), blend: cell(4, 0.08), volregime: cell(0, null) },
  { day: "2026-11-12", series: "Copper", live: cell(30, -0.062), blend: cell(0, null), volregime: cell(0, null) },
  { day: "2026-11-09", series: "Natural gas", live: cell(11, 0.174), blend: cell(0, null), volregime: cell(0, null) },
];

describe("FifteenDeclineMonitor", () => {
  it("shows the three models side by side per day and market, newest first", () => {
    render(<FifteenDeclineMonitor rows={ROWS} />);
    const table = screen.getByRole("table", { name: "15-minute decline monitor" });
    for (const label of ["Live rule", "Blend", "Vol-regime"]) expect(within(table).getByText(label)).toBeInTheDocument();
    const body = within(table).getAllByRole("row").slice(2);
    expect(body).toHaveLength(3);
    expect(within(body[0]).getByText("11-12")).toBeInTheDocument();
    expect(within(body[2]).getByText("+17.4¢")).toBeInTheDocument();
    expect(within(table).getByText("−6.2¢")).toBeInTheDocument();
    expect(within(table).getByText("+8.0¢")).toBeInTheDocument();
  });

  it("sorts by a column on click and flips on a second click", () => {
    render(<FifteenDeclineMonitor rows={ROWS} />);
    const table = screen.getByRole("table", { name: "15-minute decline monitor" });
    const liveCents = within(table).getAllByRole("button", { name: /Per trade/ })[0];
    fireEvent.click(liveCents);
    let body = within(table).getAllByRole("row").slice(2);
    expect(within(body[0]).getByText("+17.4¢")).toBeInTheDocument();
    expect(liveCents.closest("th")).toHaveAttribute("aria-sort", "descending");
    fireEvent.click(liveCents);
    body = within(table).getAllByRole("row").slice(2);
    expect(within(body[0]).getByText("−6.2¢")).toBeInTheDocument();
  });

  it("says so when there are no rows", () => {
    render(<FifteenDeclineMonitor rows={[]} />);
    expect(screen.getByText(/No decisions in the last two weeks/)).toBeInTheDocument();
  });
});
