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
      // One treemap per group now: data is the group's flat leaf list.
      const nodes = (props.data as Record<string, unknown>[]).map((leaf, li) =>
        cloneElement(props.content, {
          ...leaf, key: `l${li}`, x: li * 140, y: 0, width: 130, height: 60, depth: 1,
        }));
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

describe("CompositionBox tooltip clamping", () => {
  it("keeps the hover card inside the container when the cursor is at the far edge", () => {
    const { container } = render(<CompositionBox positions={POSITIONS} composition={[]} />);
    fireEvent.mouseOver(screen.getByTestId("tile-XOM"));
    const view = container.querySelector("[aria-label='Holdings by size, colored by sector']")!.parentElement!;
    fireEvent.mouseMove(view, { clientX: 100000, clientY: 100000 });
    const tip = screen.getByTestId("tile-tooltip");
    // The card (208 wide) must end at or before the container's right edge:
    // left + 208 <= container width, and never negative.
    const left = parseFloat(tip.style.left);
    const top = parseFloat(tip.style.top);
    expect(left).toBeGreaterThanOrEqual(0);
    expect(left + 208).toBeLessThanOrEqual(view.parentElement!.getBoundingClientRect().width || 640);
    expect(top).toBeGreaterThanOrEqual(0);
  });
});
