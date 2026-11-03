import { cloneElement, type ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import CompositionBox from "@/components/CompositionMap";
import type { PositionRow } from "@/lib/paperPortfolio";

// jsdom gives recharts no size, so stand the Treemap in with a fake that walks
// the grouped data and calls the content renderer with real geometry per node.
vi.mock("recharts", async () => {
  const orig = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...orig,
    ResponsiveContainer: ({ children }: { children: ReactElement }) => <div>{children}</div>,
    Treemap: (props: { data: unknown[]; content: ReactElement }) => {
      const nodes: ReactElement[] = [];
      (props.data as { name: string; pct: number; sector: string | null; children: Record<string, unknown>[] }[])
        .forEach((g, gi) => {
          nodes.push(cloneElement(props.content, {
            key: `g${gi}`, x: 0, y: gi * 100, width: 400, height: 96, depth: 1,
            name: g.name, pct: g.pct, sector: g.sector,
          }));
          g.children.forEach((leaf, li) => {
            nodes.push(cloneElement(props.content, {
              ...leaf, key: `l${gi}-${li}`,
              x: li * 140, y: gi * 100 + 30, width: 130, height: 60, depth: 2,
            }));
          });
        });
      return <svg data-testid="treemap">{nodes}</svg>;
    },
  };
});

const POSITIONS: PositionRow[] = [
  { symbol: "XLE", sector: "Energy", qty: 115, side: "long", market_value: 10000, pct_of_book: 10, unrealized_pl: 100, idea: "No idea yet (manual)" },
  { symbol: "XOM", sector: "Energy", qty: 49, side: "long", market_value: 8000, pct_of_book: 8, unrealized_pl: -50, idea: "No idea yet (manual)" },
  { symbol: "GLD", sector: "Commodities (Gold)", qty: 28, side: "long", market_value: 10000, pct_of_book: 10, unrealized_pl: 640, idea: "Lab2 ASML gate" },
  { symbol: "Cash", sector: "Cash", qty: null, side: null, market_value: 72000, pct_of_book: 72, unrealized_pl: null, idea: null },
];

const COMPOSITION = [
  { idea: "No idea yet (manual)", pct_of_book: 18, unrealized_pl: 50 },
  { idea: "Lab2 ASML gate", pct_of_book: 10, unrealized_pl: 640 },
];

afterEach(() => cleanup());

describe("CompositionBox", () => {
  it("renders a labeled sector legend with each sector's total weight", () => {
    render(<CompositionBox positions={POSITIONS} composition={COMPOSITION} />);
    const legend = screen.getByLabelText("Sector legend");
    expect(within(legend).getByText("Energy")).toBeInTheDocument();
    expect(within(legend).getByText("18%")).toBeInTheDocument();
    expect(within(legend).getByText("Commodities (Gold)")).toBeInTheDocument();
    expect(within(legend).getByText("Cash")).toBeInTheDocument();
    expect(within(legend).getByText("72%")).toBeInTheDocument();
  });

  it("groups tiles under labeled sector super-tiles, tiles colored by sector", () => {
    render(<CompositionBox positions={POSITIONS} composition={COMPOSITION} />);
    expect(screen.getByText("Energy · 18%")).toBeInTheDocument();
    expect(screen.getByText("XLE 10%")).toBeInTheDocument();
    const tile = screen.getByTestId("tile-XLE");
    expect(tile.querySelector("rect")).toHaveAttribute("fill", "#fb923c"); // Energy's hue
    expect(screen.getByTestId("tile-GLD").querySelector("rect")).toHaveAttribute("fill", "#eab308");
  });

  it("switches to idea grouping and keeps sector colors on the tiles", () => {
    render(<CompositionBox positions={POSITIONS} composition={COMPOSITION} />);
    fireEvent.click(screen.getByRole("button", { name: "By idea" }));
    expect(screen.getByText("No idea yet (manual) · 18%")).toBeInTheDocument();
    expect(screen.queryByText("Energy · 18%")).toBeNull();
    expect(screen.getByTestId("tile-XLE").querySelector("rect")).toHaveAttribute("fill", "#fb923c");
    fireEvent.click(screen.getByRole("button", { name: "By sector" }));
    expect(screen.getByText("Energy · 18%")).toBeInTheDocument();
  });

  it("shows the full holding line on hover", () => {
    render(<CompositionBox positions={POSITIONS} composition={COMPOSITION} />);
    fireEvent.mouseOver(screen.getByTestId("tile-XOM"));
    const tip = screen.getByTestId("tile-tooltip");
    expect(within(tip).getByText("XOM")).toBeInTheDocument();
    expect(within(tip).getByText("Energy")).toBeInTheDocument();
    expect(within(tip).getByText("$8,000")).toBeInTheDocument();
    expect(within(tip).getByText("8.0%")).toBeInTheDocument();
    expect(within(tip).getByText("49")).toBeInTheDocument();
    expect(within(tip).getByText("No idea yet (manual)")).toBeInTheDocument();
    fireEvent.mouseOut(screen.getByTestId("tile-XOM"));
    expect(screen.queryByTestId("tile-tooltip")).toBeNull();
  });

  it("pops out into a larger dialog with the same legend and toggle", () => {
    render(<CompositionBox positions={POSITIONS} composition={COMPOSITION} />);
    fireEvent.click(screen.getByRole("button", { name: "Expand composition" }));
    const dialog = screen.getByRole("dialog", { name: "Composition" });
    expect(within(dialog).getByText("Energy · 18%")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Sector legend")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "By idea" }));
    expect(within(dialog).getByText("Lab2 ASML gate · 10%")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
